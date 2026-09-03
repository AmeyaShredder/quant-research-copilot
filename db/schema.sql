-- =====================================================================
-- quant-research-copilot :: schema.sql
-- Hand-written DDL, reviewed BEFORE any ORM model is generated from it.
-- Target: PostgreSQL 15+
-- Design notes (see README "Schema Design Rationale" for the long version):
--   * 3NF baseline. The one deliberate denormalization is `signals`
--     storing a jsonb `components` blob alongside the scalar
--     `aggregated_score` — the components are a variable-shape audit
--     trail (which sub-scores fed the aggregate), not something we
--     query relationally, so normalizing them into their own table
--     would just add join overhead for zero query benefit.
--   * Cascade policy: deleting a raw_document cascades to its
--     extractions (an extraction with no source document is meaningless
--     and shouldn't be orphaned silently). Deleting an extraction
--     cascades to its critic_reviews for the same reason. We do NOT
--     cascade signals or backtest_runs from documents/extractions —
--     those are downstream aggregates that should survive and instead
--     just stop being fed by new data. evaluation_labels also cascade
--     with their document, since a label with no document is meaningless.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- raw_documents: staging table. Everything lands here before any LLM
-- touches it. content_hash is the dedup key (sha256 of normalized text).
-- ---------------------------------------------------------------------
CREATE TABLE raw_documents (
    document_id     BIGSERIAL PRIMARY KEY,
    source          TEXT        NOT NULL,              -- 'news' | 'edgar' | 'transcript'
    ticker          TEXT        NOT NULL,
    doc_type        TEXT        NOT NULL,               -- '8-K' | '10-Q' | 'news_article' | 'transcript'
    raw_text        TEXT        NOT NULL,
    content_hash    CHAR(64)    NOT NULL,                -- sha256 hex digest
    source_url      TEXT,
    published_at    TIMESTAMPTZ,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_raw_documents_content_hash UNIQUE (content_hash)
);

COMMENT ON TABLE raw_documents IS
    'Staging table for every ingested document, pre-LLM. content_hash '
    'uniqueness makes re-ingestion idempotent for free.';

-- ---------------------------------------------------------------------
-- extractions: Extractor agent output, one row per (document, model run).
-- A document CAN have more than one extraction row if re-run with a
-- different model/prompt version — that's intentional, not a bug, so we
-- do NOT put a uniqueness constraint on document_id alone.
-- ---------------------------------------------------------------------
CREATE TABLE extractions (
    extraction_id   BIGSERIAL PRIMARY KEY,
    document_id     BIGINT      NOT NULL REFERENCES raw_documents(document_id) ON DELETE CASCADE,
    entities        JSONB       NOT NULL DEFAULT '[]',   -- e.g. [{"ticker": "AAPL", "role": "subject"}]
    event_type      TEXT        NOT NULL,                -- 'earnings_beat' | 'guidance_cut' | 'litigation' | ...
    sentiment_score NUMERIC(4,3) NOT NULL,
    confidence      NUMERIC(4,3) NOT NULL,
    evidence_quote  TEXT        NOT NULL,
    model_used      TEXT        NOT NULL,
    extracted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_sentiment_range CHECK (sentiment_score BETWEEN -1 AND 1),
    CONSTRAINT chk_confidence_range CHECK (confidence BETWEEN 0 AND 1)
);

-- ---------------------------------------------------------------------
-- critic_reviews: Critic agent's verdict on an extraction.
-- ---------------------------------------------------------------------
CREATE TABLE critic_reviews (
    review_id       BIGSERIAL PRIMARY KEY,
    extraction_id   BIGINT      NOT NULL REFERENCES extractions(extraction_id) ON DELETE CASCADE,
    verdict         TEXT        NOT NULL,                -- 'supported' | 'unsupported' | 'overconfident' | 'contradictory'
    reasoning       TEXT        NOT NULL,
    reviewed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_verdict_values CHECK (
        verdict IN ('supported', 'unsupported', 'overconfident', 'contradictory')
    )
);

-- Partial index: the pipeline's hot query is "give me extractions that
-- haven't been critiqued yet" (worker queue pattern). A full index on
-- extraction_id would work too, but this partial index only covers the
-- actually-useful subset and stays small as the reviewed backlog grows.
CREATE INDEX idx_extractions_unreviewed
    ON extractions (extraction_id)
    WHERE extraction_id NOT IN (SELECT extraction_id FROM critic_reviews);

-- ---------------------------------------------------------------------
-- signals: daily grain, one row per ticker/day. This is what the
-- backtest and dashboard actually read.
-- ---------------------------------------------------------------------
CREATE TABLE signals (
    signal_id         BIGSERIAL PRIMARY KEY,
    ticker            TEXT        NOT NULL,
    date              DATE        NOT NULL,
    aggregated_score  NUMERIC(6,4) NOT NULL,
    components        JSONB       NOT NULL DEFAULT '{}',  -- audit trail: {"news": 0.3, "filing": -0.1, "n_docs": 4}
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_signals_ticker_date UNIQUE (ticker, date)
);

-- Main query pattern for this table is "give me ticker X's signal
-- history" and "give me all tickers' signals for date Y" — a composite
-- index on (ticker, date) serves both, since date can still be used
-- via index skip scan / leading-column scans for the second pattern
-- and is the leading column search for the first.
CREATE INDEX idx_signals_ticker_date ON signals (ticker, date);

-- ---------------------------------------------------------------------
-- backtest_runs / backtest_positions: proper parent/child. Each sweep
-- point, baseline, and "real" run is its own backtest_runs row, so
-- comparisons are just a SQL join between two run_ids.
-- ---------------------------------------------------------------------
CREATE TABLE backtest_runs (
    run_id          BIGSERIAL PRIMARY KEY,
    label           TEXT        NOT NULL,                -- 'signal_v1' | 'baseline_momentum' | 'sweep_decay_0.9'
    config          JSONB       NOT NULL,                 -- full run config for reproducibility
    sharpe          NUMERIC(6,3),
    max_drawdown    NUMERIC(6,4),
    hit_rate        NUMERIC(5,4),
    turnover        NUMERIC(6,4),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE backtest_positions (
    position_id     BIGSERIAL PRIMARY KEY,
    run_id          BIGINT      NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    date            DATE        NOT NULL,
    ticker          TEXT        NOT NULL,
    position        NUMERIC(4,3) NOT NULL,                -- -1 (short) .. +1 (long), sized
    pnl             NUMERIC(10,4) NOT NULL,
    CONSTRAINT uq_backtest_positions_run_date_ticker UNIQUE (run_id, date, ticker)
);

CREATE INDEX idx_backtest_positions_run_id ON backtest_positions (run_id);

-- ---------------------------------------------------------------------
-- llm_call_log: observability. Every LLM call, any stage, logged here.
-- ---------------------------------------------------------------------
CREATE TABLE llm_call_log (
    call_id           BIGSERIAL PRIMARY KEY,
    stage             TEXT        NOT NULL,               -- 'extractor' | 'critic'
    document_id       BIGINT      REFERENCES raw_documents(document_id) ON DELETE SET NULL,
    prompt_tokens     INTEGER     NOT NULL,
    completion_tokens INTEGER     NOT NULL,
    latency_ms        INTEGER     NOT NULL,
    cost_usd          NUMERIC(8,5) NOT NULL,
    called_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_llm_call_log_called_at ON llm_call_log (called_at);

-- ---------------------------------------------------------------------
-- evaluation_labels: golden set for the eval harness.
-- ---------------------------------------------------------------------
CREATE TABLE evaluation_labels (
    label_id            BIGSERIAL PRIMARY KEY,
    document_id         BIGINT      NOT NULL REFERENCES raw_documents(document_id) ON DELETE CASCADE,
    true_event_type      TEXT        NOT NULL,
    true_sentiment_score NUMERIC(4,3) NOT NULL,
    labeled_by          TEXT        NOT NULL,
    labeled_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_evaluation_labels_document UNIQUE (document_id),
    CONSTRAINT chk_true_sentiment_range CHECK (true_sentiment_score BETWEEN -1 AND 1)
);

-- ---------------------------------------------------------------------
-- Dedup lookup index — separate from the UNIQUE constraint's implicit
-- btree only because we call it out explicitly as a deliberate design
-- choice in the README; in practice the UNIQUE constraint above already
-- creates this index, so this line is intentionally commented out to
-- avoid a duplicate index (documented here so the decision is visible).
-- ---------------------------------------------------------------------
-- CREATE INDEX idx_raw_documents_content_hash ON raw_documents (content_hash);  -- redundant w/ UNIQUE

COMMIT;

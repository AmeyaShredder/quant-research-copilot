# quant-research-copilot

A multi-agent LLM system that researches, evaluates, and monitors trading
signals derived from unstructured data (news, SEC filings, earnings-call
transcripts), with a real evaluation harness, a normalized Postgres
schema with a proper repository layer, and a Streamlit observability
dashboard.


---

## Architecture

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ news (yfin)  │   │ EDGAR filings│   │ sample        │
│              │   │ (8-K, 10-Q)  │   │ transcripts   │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │  DataSource.run() — fetch/normalize/dedupe     │
       └──────────────────┴────────────────────────────┘
                           │
                           ▼
                 raw_documents (staging)
                           │  content_hash UNIQUE ⇒ idempotent
                           ▼
                 ┌──────────────────┐
                 │  Extractor agent  │──▶ extractions
                 └──────────────────┘
                           │
                           ▼
                 ┌──────────────────┐
                 │   Critic agent    │──▶ critic_reviews
                 └──────────────────┘
                           │
                           ▼
                 signal/aggregator.py (weighted, critic-filtered)
                           │
                           ▼
                        signals  (ticker, date, aggregated_score)
                           │
             ┌─────────────┴──────────────┐
             ▼                             ▼
   signal/construct.py            evaluation/harness.py
   (rolling z-score, SQL)         (vs. evaluation_labels)
             │
             ▼
   backtest/engine.py + baseline.py + sweep.py
             │
             ▼
   backtest_runs / backtest_positions
             │
             ▼
   dashboard/app.py  (reads db/views.sql directly)
```

Package layout:
```
/ingestion    DataSource interface + news/edgar/transcript sources
/db           schema.sql, views.sql, models.py, repositories.py, session.py, migrations/
/agents       llm_client.py, extractor.py, critic.py, pipeline.py
/signal       aggregator.py (conflict resolution), construct.py (rolling z-score)
/backtest     engine.py, baseline.py, sweep.py
/evaluation   harness.py, load_golden_set.py
/dashboard    app.py (Streamlit)
/tests        pytest suite
/config       config.yaml, golden_set.csv, sample_transcripts/
```

### ER diagram

```mermaid
erDiagram
    raw_documents ||--o{ extractions : "has"
    extractions ||--o{ critic_reviews : "reviewed by"
    raw_documents ||--o{ evaluation_labels : "labeled"
    raw_documents ||--o{ llm_call_log : "logged calls for"
    backtest_runs ||--o{ backtest_positions : "contains"

    raw_documents {
        bigint document_id PK
        text source
        text ticker
        text doc_type
        text raw_text
        char content_hash UK
        timestamptz ingested_at
    }
    extractions {
        bigint extraction_id PK
        bigint document_id FK
        jsonb entities
        text event_type
        numeric sentiment_score
        numeric confidence
        text evidence_quote
        text model_used
    }
    critic_reviews {
        bigint review_id PK
        bigint extraction_id FK
        text verdict
        text reasoning
    }
    signals {
        bigint signal_id PK
        text ticker
        date date
        numeric aggregated_score
        jsonb components
    }
    backtest_runs {
        bigint run_id PK
        text label
        jsonb config
        numeric sharpe
        numeric max_drawdown
        numeric hit_rate
    }
    backtest_positions {
        bigint position_id PK
        bigint run_id FK
        date date
        text ticker
        numeric position
        numeric pnl
    }
    llm_call_log {
        bigint call_id PK
        text stage
        int prompt_tokens
        int completion_tokens
        numeric cost_usd
    }
    evaluation_labels {
        bigint label_id PK
        bigint document_id FK
        text true_event_type
        numeric true_sentiment_score
    }
```

---

## Setup

```bash
# 1. Start Postgres
docker compose up -d
# wait for healthcheck: docker compose ps

# 2. Install deps
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Set env vars
export DATABASE_URL="postgresql+psycopg://qrc:qrc@localhost:5432/quant_research_copilot"
export ANTHROPIC_API_KEY="sk-ant-..."
export EDGAR_USER_AGENT="Your Name your@email.com"

# 4. Run migrations (this is how schema.sql actually gets applied —
#    the migrations in db/migrations/versions/ mirror schema.sql exactly)
alembic upgrade head

# 5. Create the analytical views (not managed by Alembic — see note below)
psql "$DATABASE_URL" -f db/views.sql

# NOTE on "No module named 'db'": run the commands below from the repo
# root (where this README lives). Anything invoked with `python -m ...`
# or `python -c "..."` from the root works automatically, because
# Python puts the current directory on sys.path in those two modes.
# `streamlit run dashboard/app.py` and `python evaluation/load_golden_set.py`
# are exceptions — they run the target file directly, which normally
# puts only that file's own folder on sys.path, not the root — so both
# files carry a small sys.path bootstrap to fix this regardless of cwd.
# If you add your own entrypoint script under a subfolder, add the same
# two-line bootstrap (see the top of dashboard/app.py) or run it as
# `python -m your.module.path` instead.

# 6. Run the pipeline for one ticker
python -c "
from agents.llm_client import LLMClient
from agents.pipeline import run_pipeline_for_ticker
from ingestion.news_source import YFinanceNewsSource
from ingestion.edgar_source import EdgarFilingSource
from ingestion.transcript_source import SampleTranscriptSource

sources = [YFinanceNewsSource(), EdgarFilingSource(), SampleTranscriptSource()]
run_pipeline_for_ticker('AAPL', sources, LLMClient())
"

# 7. Aggregate today's signal, run backtests, launch dashboard
python -m evaluation.load_golden_set
streamlit run dashboard/app.py
```

**Why views.sql is separate from Alembic:** views are derived/reporting
objects, not part of the transactional data model migrations exist to
version. Keeping `CREATE OR REPLACE VIEW` in a plain `.sql` file that's
just re-applied (idempotently — `CREATE OR REPLACE`) keeps Alembic's
migration history focused on actual schema changes. This is a judgment
call, not a hard rule — a team that wants view changes in the same audit
trail as table changes would be justified in moving these into Alembic
migrations instead.

---

## Indexing strategy & EXPLAIN ANALYZE evidence

Indexes added (see `db/schema.sql` for full rationale comments):

| Index | Table | Reason |
|---|---|---|
| `uq_raw_documents_content_hash` (implicit from UNIQUE) | raw_documents | O(1) dedup lookup on ingest |
| `idx_signals_ticker_date` | signals | main query pattern: "history for ticker X" / "cross-section for date Y" |
| `idx_backtest_positions_run_id` | backtest_positions | join fan-out from backtest_runs |
| `idx_llm_call_log_called_at` | llm_call_log | time-range scans for the cost dashboard |
| `idx_extractions_unreviewed` (partial) | extractions | worker-queue query: "next extraction with no critic review yet" — partial so the index stays small as the reviewed backlog grows, instead of indexing the whole table |

**Regenerating real EXPLAIN ANALYZE numbers (do this before the
interview — the table below is illustrative, generated from a synthetic
dataset shape, not a live run):**

```bash
psql "$DATABASE_URL" -c "EXPLAIN ANALYZE SELECT * FROM signals WHERE ticker = 'AAPL' ORDER BY date DESC LIMIT 30;"
psql "$DATABASE_URL" -c "EXPLAIN ANALYZE SELECT * FROM raw_documents WHERE content_hash = '<some hash>';"
psql "$DATABASE_URL" -c "EXPLAIN ANALYZE SELECT extraction_id FROM extractions WHERE extraction_id NOT IN (SELECT extraction_id FROM critic_reviews) LIMIT 10;"
```

Illustrative before/after shape you should expect to see (seq scan →
index scan, ms → sub-ms once the table has enough rows for the planner
to prefer the index — Postgres won't use an index on a tiny table, so
you may need to seed a few thousand synthetic rows to see the crossover
clearly):

| Query | Before (no index) | After (with index) |
|---|---|---|
| `signals` by `(ticker, date)` | `Seq Scan on signals (cost=0.00..1850.00 rows=40) actual time=12.400..38.900` | `Index Scan using idx_signals_ticker_date (cost=0.42..8.50 rows=40) actual time=0.031..0.089` |
| `raw_documents` by `content_hash` | `Seq Scan on raw_documents actual time=9.800..25.100` | `Index Scan using uq_raw_documents_content_hash actual time=0.018..0.021` |
| unreviewed `extractions` | `Seq Scan on extractions ... Filter: (NOT (hashed SubPlan 1))` | `Index Scan using idx_extractions_unreviewed actual time=0.015..0.040` |

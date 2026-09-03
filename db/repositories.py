"""
Repository layer. Application code (agents, signal construction,
backtest, evaluation, dashboard) never writes raw SQL inline — it calls
into one of these repositories instead.

Each repository has:
  - ORM-based methods for standard CRUD
  - hand-written raw SQL for analytical work the ORM is awkward at

The four raw-SQL analytical queries required by the spec are marked
below with which SQL feature they exercise:
  1. rolling z-score signal        -> window function (AVG OVER, STDDEV OVER)
  2. cost-per-stage rollup         -> GROUP BY ... HAVING
  3. extraction agreement by src   -> CTE + LEFT JOIN aggregation
  4. day-over-day signal momentum  -> LAG window function
"""
from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.models import (
    BacktestPosition,
    BacktestRun,
    CriticReview,
    EvaluationLabel,
    Extraction,
    LlmCallLog,
    RawDocument,
    Signal,
)


def content_hash(text_body: str) -> str:
    return hashlib.sha256(text_body.strip().encode("utf-8")).hexdigest()


class DocumentRepository:
    def __init__(self, session: Session):
        self.session = session

    # ---- ORM CRUD -----------------------------------------------------
    def insert_if_new(self, *, source: str, ticker: str, doc_type: str,
                       raw_text: str, source_url: Optional[str] = None,
                       published_at=None) -> Optional[RawDocument]:
        """Idempotent insert. Returns None (no insert) if content_hash
        already exists — this is how the pipeline gets resumability for
        free instead of checking existence in application logic first."""
        h = content_hash(raw_text)
        existing = self.session.query(RawDocument).filter_by(content_hash=h).one_or_none()
        if existing is not None:
            return None
        doc = RawDocument(
            source=source, ticker=ticker, doc_type=doc_type, raw_text=raw_text,
            content_hash=h, source_url=source_url, published_at=published_at,
        )
        self.session.add(doc)
        self.session.flush()  # populate document_id without committing
        return doc

    def get(self, document_id: int) -> Optional[RawDocument]:
        return self.session.get(RawDocument, document_id)

    def unlabeled_sample(self, limit: int = 50) -> list[RawDocument]:
        return (
            self.session.query(RawDocument)
            .outerjoin(EvaluationLabel, EvaluationLabel.document_id == RawDocument.document_id)
            .filter(EvaluationLabel.label_id.is_(None))
            .order_by(RawDocument.ingested_at.desc())
            .limit(limit)
            .all()
        )

    # ---- raw SQL --------------------------------------------------------
    def extraction_agreement_by_source(self) -> list[dict[str, Any]]:
        """
        CTE + LEFT JOIN aggregation: critic agreement rate broken out by
        document source. Mirrors v_extraction_accuracy_by_source but kept
        here too as a standalone example of hand-written analytical SQL
        (per spec requirement) rather than only living in a view.
        """
        sql = text("""
            WITH extraction_verdicts AS (
                SELECT
                    d.source,
                    e.extraction_id,
                    cr.verdict
                FROM extractions e
                JOIN raw_documents d ON d.document_id = e.document_id
                LEFT JOIN critic_reviews cr ON cr.extraction_id = e.extraction_id
            )
            SELECT
                source,
                COUNT(*) AS n_extractions,
                ROUND(AVG(CASE WHEN verdict = 'supported' THEN 1.0 ELSE 0.0 END)::numeric, 4)
                    AS agreement_rate
            FROM extraction_verdicts
            GROUP BY source
            ORDER BY source;
        """)
        return [dict(row._mapping) for row in self.session.execute(sql)]


class SignalRepository:
    def __init__(self, session: Session):
        self.session = session

    # ---- ORM CRUD -----------------------------------------------------
    def upsert(self, *, ticker: str, as_of: date, aggregated_score: Decimal,
               components: dict[str, Any]) -> Signal:
        existing = self.session.query(Signal).filter_by(ticker=ticker, date=as_of).one_or_none()
        if existing:
            existing.aggregated_score = aggregated_score
            existing.components = components
            return existing
        sig = Signal(ticker=ticker, date=as_of, aggregated_score=aggregated_score, components=components)
        self.session.add(sig)
        self.session.flush()
        return sig

    def history(self, ticker: str, limit: int = 250) -> list[Signal]:
        return (
            self.session.query(Signal)
            .filter_by(ticker=ticker)
            .order_by(Signal.date.desc())
            .limit(limit)
            .all()
        )

    # ---- raw SQL --------------------------------------------------------
    def rolling_zscore(self, *, window_days: int = 20) -> list[dict[str, Any]]:
        """
        Window function query: cross-sectional signal recomputed as a
        rolling z-score per ticker, done in SQL rather than pandas.
        Uses AVG(...) OVER (rolling window) and STDDEV(...) OVER
        (rolling window), partitioned per ticker, ordered by date.
        """
        sql = text("""
            SELECT
                ticker,
                date,
                aggregated_score,
                AVG(aggregated_score) OVER w   AS rolling_mean,
                STDDEV(aggregated_score) OVER w AS rolling_stddev,
                CASE
                    WHEN STDDEV(aggregated_score) OVER w IS NULL
                      OR STDDEV(aggregated_score) OVER w = 0 THEN 0
                    ELSE (aggregated_score - AVG(aggregated_score) OVER w)
                         / NULLIF(STDDEV(aggregated_score) OVER w, 0)
                END AS rolling_zscore
            FROM signals
            WINDOW w AS (
                PARTITION BY ticker
                ORDER BY date
                ROWS BETWEEN :window_days PRECEDING AND CURRENT ROW
            )
            ORDER BY ticker, date;
        """)
        return [dict(row._mapping) for row in self.session.execute(sql, {"window_days": window_days - 1})]

    def day_over_day_momentum(self, ticker: str) -> list[dict[str, Any]]:
        """
        LAG window function: prior-day signal value alongside today's,
        so momentum (delta) is a plain subtraction, not a self-join.
        """
        sql = text("""
            SELECT
                date,
                aggregated_score,
                LAG(aggregated_score) OVER (ORDER BY date) AS prior_day_score,
                aggregated_score - LAG(aggregated_score) OVER (ORDER BY date) AS delta
            FROM signals
            WHERE ticker = :ticker
            ORDER BY date;
        """)
        return [dict(row._mapping) for row in self.session.execute(sql, {"ticker": ticker})]


class BacktestRepository:
    def __init__(self, session: Session):
        self.session = session

    # ---- ORM CRUD -----------------------------------------------------
    def create_run(self, *, label: str, config: dict[str, Any]) -> BacktestRun:
        run = BacktestRun(label=label, config=config)
        self.session.add(run)
        self.session.flush()
        return run

    def record_metrics(self, run: BacktestRun, *, sharpe: float, max_drawdown: float,
                        hit_rate: float, turnover: float) -> None:
        run.sharpe = Decimal(str(sharpe))
        run.max_drawdown = Decimal(str(max_drawdown))
        run.hit_rate = Decimal(str(hit_rate))
        run.turnover = Decimal(str(turnover))

    def add_positions(self, run_id: int, rows: list[dict[str, Any]]) -> None:
        self.session.bulk_insert_mappings(
            BacktestPosition,
            [{**r, "run_id": run_id} for r in rows],
        )

    # ---- raw SQL --------------------------------------------------------
    def compare_runs(self, run_id_a: int, run_id_b: int) -> dict[str, Any]:
        sql = text("""
            SELECT a.label AS label_a, a.sharpe AS sharpe_a, a.max_drawdown AS dd_a,
                   b.label AS label_b, b.sharpe AS sharpe_b, b.max_drawdown AS dd_b,
                   (a.sharpe - b.sharpe) AS sharpe_delta
            FROM backtest_runs a, backtest_runs b
            WHERE a.run_id = :a AND b.run_id = :b;
        """)
        row = self.session.execute(sql, {"a": run_id_a, "b": run_id_b}).one()
        return dict(row._mapping)


class ObservabilityRepository:
    def __init__(self, session: Session):
        self.session = session

    def log_call(self, *, stage: str, document_id: Optional[int], prompt_tokens: int,
                 completion_tokens: int, latency_ms: int, cost_usd: Decimal) -> None:
        self.session.add(LlmCallLog(
            stage=stage, document_id=document_id, prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens, latency_ms=latency_ms, cost_usd=cost_usd,
        ))

    # ---- raw SQL --------------------------------------------------------
    def cost_per_stage_rollup(self, min_calls: int = 1) -> list[dict[str, Any]]:
        """
        GROUP BY ... HAVING: per-stage cost/latency rollup, filtered to
        stages with at least `min_calls` logged calls (drops noise from
        one-off manual test invocations during development).
        """
        sql = text("""
            SELECT
                stage,
                COUNT(*)                AS n_calls,
                SUM(cost_usd)            AS total_cost_usd,
                AVG(latency_ms)::int     AS avg_latency_ms,
                SUM(prompt_tokens + completion_tokens) AS total_tokens
            FROM llm_call_log
            GROUP BY stage
            HAVING COUNT(*) >= :min_calls
            ORDER BY total_cost_usd DESC;
        """)
        return [dict(row._mapping) for row in self.session.execute(sql, {"min_calls": min_calls})]


class EvaluationRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_label(self, *, document_id: int, true_event_type: str,
                  true_sentiment_score: Decimal, labeled_by: str) -> EvaluationLabel:
        label = EvaluationLabel(
            document_id=document_id, true_event_type=true_event_type,
            true_sentiment_score=true_sentiment_score, labeled_by=labeled_by,
        )
        self.session.add(label)
        self.session.flush()
        return label

    # ---- raw SQL --------------------------------------------------------
    def precision_recall_f1_by_event_type(self) -> list[dict[str, Any]]:
        """
        SQL join between extractions and evaluation_labels for per-class
        precision/recall/F1 on event_type classification, rather than
        pulling both tables into Python and comparing there.
        """
        sql = text("""
            WITH joined AS (
                SELECT e.event_type AS predicted, el.true_event_type AS actual
                FROM extractions e
                JOIN evaluation_labels el ON el.document_id = e.document_id
            ),
            per_class AS (
                SELECT
                    coalesce(p.cls, a.cls) AS event_type,
                    COUNT(*) FILTER (WHERE j.predicted = j.actual AND j.actual = coalesce(p.cls, a.cls))
                        AS true_positives,
                    COUNT(*) FILTER (WHERE j.predicted = coalesce(p.cls, a.cls) AND j.actual <> coalesce(p.cls, a.cls))
                        AS false_positives,
                    COUNT(*) FILTER (WHERE j.actual = coalesce(p.cls, a.cls) AND j.predicted <> coalesce(p.cls, a.cls))
                        AS false_negatives
                FROM joined j
                CROSS JOIN LATERAL (SELECT j.predicted AS cls) p
                CROSS JOIN LATERAL (SELECT j.actual AS cls) a
                GROUP BY coalesce(p.cls, a.cls)
            )
            SELECT
                event_type,
                true_positives, false_positives, false_negatives,
                ROUND(true_positives::numeric / NULLIF(true_positives + false_positives, 0), 4) AS precision,
                ROUND(true_positives::numeric / NULLIF(true_positives + false_negatives, 0), 4) AS recall,
                ROUND(
                    2.0 * true_positives / NULLIF(2 * true_positives + false_positives + false_negatives, 0),
                    4
                ) AS f1
            FROM per_class
            ORDER BY event_type;
        """)
        return [dict(row._mapping) for row in self.session.execute(sql)]

    def sentiment_mae(self) -> float:
        sql = text("""
            SELECT AVG(ABS(e.sentiment_score - el.true_sentiment_score)) AS mae
            FROM extractions e
            JOIN evaluation_labels el ON el.document_id = e.document_id;
        """)
        row = self.session.execute(sql).one()
        return float(row.mae) if row.mae is not None else float("nan")

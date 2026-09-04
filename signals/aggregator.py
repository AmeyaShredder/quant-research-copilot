"""
Combines extractions per ticker/day into `signals`.

Conflict-resolution rule (documented per spec requirement, see also
README "Signal Construction"):
    Within a (ticker, date) bucket, each extraction's sentiment_score is
    weighted by its own `confidence` AND by a source-type weight
    (filings > transcripts > news, since filings are the least noisy
    channel). The aggregated_score is the confidence*source-weighted
    mean. If the Critic marked an extraction "unsupported" or
    "contradictory", that extraction is EXCLUDED entirely from the
    aggregate rather than down-weighted — a critic-rejected extraction
    is not partial evidence, it's noise.
    Ties / all-excluded buckets: aggregated_score = 0.0, components
    records n_docs = 0 so the dashboard can visibly distinguish "no
    signal" from "neutral signal".
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.repositories import SignalRepository

SOURCE_WEIGHTS = {"edgar": 1.2, "transcript": 1.0, "news": 0.8}
REJECTED_VERDICTS = {"unsupported", "contradictory"}


def aggregate_day(session: Session, ticker: str, as_of: date) -> dict[str, Any]:
    rows = session.execute(
        text("""
            SELECT
                e.sentiment_score, e.confidence, d.source,
                cr.verdict
            FROM extractions e
            JOIN raw_documents d ON d.document_id = e.document_id
            LEFT JOIN critic_reviews cr ON cr.extraction_id = e.extraction_id
            WHERE d.ticker = :ticker
              AND date(e.extracted_at) = :as_of
        """),
        {"ticker": ticker, "as_of": as_of},
    ).all()

    weighted_sum = Decimal("0")
    weight_total = Decimal("0")
    n_used, n_rejected = 0, 0

    for row in rows:
        if row.verdict in REJECTED_VERDICTS:
            n_rejected += 1
            continue
        w = Decimal(str(row.confidence)) * Decimal(str(SOURCE_WEIGHTS.get(row.source, 1.0)))
        weighted_sum += Decimal(str(row.sentiment_score)) * w
        weight_total += w
        n_used += 1

    aggregated_score = (weighted_sum / weight_total) if weight_total > 0 else Decimal("0")
    components = {"n_docs": n_used, "n_rejected": n_rejected, "weight_total": float(weight_total)}

    signal = SignalRepository(session).upsert(
        ticker=ticker, as_of=as_of, aggregated_score=aggregated_score, components=components
    )
    return {"ticker": ticker, "date": as_of, "aggregated_score": float(aggregated_score), **components}

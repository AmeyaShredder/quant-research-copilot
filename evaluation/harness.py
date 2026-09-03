"""
Evaluation harness against the golden set in evaluation_labels
(30-50 manually labeled documents). Precision/recall/F1 and sentiment
MAE are computed via SQL joins in the repository layer, not by pulling
both tables into Python and comparing there.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.repositories import EvaluationRepository, ObservabilityRepository


def run_evaluation(session: Session) -> dict[str, Any]:
    eval_repo = EvaluationRepository(session)
    obs_repo = ObservabilityRepository(session)

    per_class = eval_repo.precision_recall_f1_by_event_type()
    sentiment_mae = eval_repo.sentiment_mae()
    cost_rollup = obs_repo.cost_per_stage_rollup()
    disagreement_correlation = critic_disagreement_vs_label_error(session)

    macro_f1 = (
        sum(row["f1"] for row in per_class if row["f1"] is not None) / len(per_class)
        if per_class else 0.0
    )

    return {
        "per_class_metrics": per_class,
        "macro_f1": round(macro_f1, 4),
        "sentiment_mae": round(sentiment_mae, 4) if sentiment_mae == sentiment_mae else None,  # NaN check
        "cost_rollup": cost_rollup,
        "critic_disagreement_vs_label_error": disagreement_correlation,
    }


def critic_disagreement_vs_label_error(session: Session) -> dict[str, Any]:
    """
    Does Critic disagreement predict labeling error? Buckets extractions
    by critic verdict and reports mean |sentiment error| and event-type
    mismatch rate in each bucket — if the Critic is doing useful work,
    the 'unsupported'/'contradictory' buckets should show markedly worse
    accuracy than 'supported'.
    """
    sql = text("""
        SELECT
            coalesce(cr.verdict, 'no_review') AS verdict,
            COUNT(*) AS n,
            ROUND(AVG(ABS(e.sentiment_score - el.true_sentiment_score))::numeric, 4) AS avg_sentiment_error,
            ROUND(AVG(CASE WHEN e.event_type <> el.true_event_type THEN 1.0 ELSE 0.0 END)::numeric, 4)
                AS event_mismatch_rate
        FROM extractions e
        JOIN evaluation_labels el ON el.document_id = e.document_id
        LEFT JOIN critic_reviews cr ON cr.extraction_id = e.extraction_id
        GROUP BY coalesce(cr.verdict, 'no_review')
        ORDER BY avg_sentiment_error DESC NULLS LAST;
    """)
    return [dict(row._mapping) for row in session.execute(sql)]

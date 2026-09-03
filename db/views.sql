-- =====================================================================
-- Analytical views. The dashboard (Part F) reads these directly instead
-- of recomputing aggregation logic in Python — DB does aggregation,
-- dashboard just renders.
-- =====================================================================

BEGIN;

-- v_daily_pipeline_cost: LLM spend per day per stage, for the cost
-- panel. Uses a GROUP BY ... HAVING to only surface days with material
-- spend (filters out near-zero noise days from ad-hoc test calls).
CREATE OR REPLACE VIEW v_daily_pipeline_cost AS
SELECT
    date_trunc('day', called_at)::date AS call_date,
    stage,
    COUNT(*)                            AS n_calls,
    SUM(prompt_tokens)                  AS total_prompt_tokens,
    SUM(completion_tokens)              AS total_completion_tokens,
    SUM(cost_usd)                       AS total_cost_usd,
    AVG(latency_ms)                     AS avg_latency_ms
FROM llm_call_log
GROUP BY date_trunc('day', called_at)::date, stage
HAVING SUM(cost_usd) > 0
ORDER BY call_date DESC, stage;

-- v_extraction_accuracy_by_source: Critic agreement rate + eval-label
-- accuracy, broken out by source type (news vs. edgar vs. transcript).
CREATE OR REPLACE VIEW v_extraction_accuracy_by_source AS
SELECT
    d.source,
    COUNT(DISTINCT e.extraction_id)                                   AS n_extractions,
    ROUND(
        AVG(CASE WHEN cr.verdict = 'supported' THEN 1.0 ELSE 0.0 END)::numeric,
        4
    )                                                                  AS critic_agreement_rate,
    ROUND(
        AVG(CASE WHEN el.true_event_type = e.event_type THEN 1.0 ELSE 0.0 END)::numeric,
        4
    )                                                                  AS event_type_accuracy,
    ROUND(
        AVG(ABS(e.sentiment_score - el.true_sentiment_score))::numeric,
        4
    )                                                                  AS sentiment_mae
FROM extractions e
JOIN raw_documents d       ON d.document_id = e.document_id
LEFT JOIN critic_reviews cr ON cr.extraction_id = e.extraction_id
LEFT JOIN evaluation_labels el ON el.document_id = e.document_id
GROUP BY d.source
ORDER BY d.source;

-- v_signal_vs_baseline_performance: side-by-side backtest comparison.
-- Self-join on backtest_runs by label so "signal vs baseline" is just
-- selecting from this view, not a special-cased script.
CREATE OR REPLACE VIEW v_signal_vs_baseline_performance AS
SELECT
    s.label       AS signal_label,
    s.sharpe      AS signal_sharpe,
    s.max_drawdown AS signal_max_drawdown,
    s.hit_rate    AS signal_hit_rate,
    b.label       AS baseline_label,
    b.sharpe      AS baseline_sharpe,
    b.max_drawdown AS baseline_max_drawdown,
    b.hit_rate    AS baseline_hit_rate,
    (s.sharpe - b.sharpe) AS sharpe_delta
FROM backtest_runs s
CROSS JOIN backtest_runs b
WHERE s.label LIKE 'signal_%'
  AND b.label LIKE 'baseline_%'
ORDER BY s.created_at DESC, b.created_at DESC;

COMMIT;

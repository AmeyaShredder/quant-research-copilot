"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_documents",
        sa.Column("document_id", sa.BigInteger(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("content_hash", name="uq_raw_documents_content_hash"),
    )

    op.create_table(
        "extractions",
        sa.Column("extraction_id", sa.BigInteger(), primary_key=True),
        sa.Column("document_id", sa.BigInteger(),
                  sa.ForeignKey("raw_documents.document_id", ondelete="CASCADE"), nullable=False),
        sa.Column("entities", postgresql.JSONB(), server_default="[]"),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("sentiment_score", sa.Numeric(4, 3), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("evidence_quote", sa.Text(), nullable=False),
        sa.Column("model_used", sa.Text(), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("sentiment_score BETWEEN -1 AND 1", name="chk_sentiment_range"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="chk_confidence_range"),
    )

    op.create_table(
        "signals",
        sa.Column("signal_id", sa.BigInteger(), primary_key=True),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("aggregated_score", sa.Numeric(6, 4), nullable=False),
        sa.Column("components", postgresql.JSONB(), server_default="{}"),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "date", name="uq_signals_ticker_date"),
    )
    op.create_index("idx_signals_ticker_date", "signals", ["ticker", "date"])

    op.create_table(
        "backtest_runs",
        sa.Column("run_id", sa.BigInteger(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("sharpe", sa.Numeric(6, 3)),
        sa.Column("max_drawdown", sa.Numeric(6, 4)),
        sa.Column("hit_rate", sa.Numeric(5, 4)),
        sa.Column("turnover", sa.Numeric(6, 4)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "backtest_positions",
        sa.Column("position_id", sa.BigInteger(), primary_key=True),
        sa.Column("run_id", sa.BigInteger(),
                  sa.ForeignKey("backtest_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("position", sa.Numeric(4, 3), nullable=False),
        sa.Column("pnl", sa.Numeric(10, 4), nullable=False),
        sa.UniqueConstraint("run_id", "date", "ticker", name="uq_backtest_positions_run_date_ticker"),
    )
    op.create_index("idx_backtest_positions_run_id", "backtest_positions", ["run_id"])

    op.create_table(
        "llm_call_log",
        sa.Column("call_id", sa.BigInteger(), primary_key=True),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("document_id", sa.BigInteger(),
                  sa.ForeignKey("raw_documents.document_id", ondelete="SET NULL")),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(8, 5), nullable=False),
        sa.Column("called_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_llm_call_log_called_at", "llm_call_log", ["called_at"])

    op.create_table(
        "evaluation_labels",
        sa.Column("label_id", sa.BigInteger(), primary_key=True),
        sa.Column("document_id", sa.BigInteger(),
                  sa.ForeignKey("raw_documents.document_id", ondelete="CASCADE"), nullable=False),
        sa.Column("true_event_type", sa.Text(), nullable=False),
        sa.Column("true_sentiment_score", sa.Numeric(4, 3), nullable=False),
        sa.Column("labeled_by", sa.Text(), nullable=False),
        sa.Column("labeled_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", name="uq_evaluation_labels_document"),
        sa.CheckConstraint("true_sentiment_score BETWEEN -1 AND 1", name="chk_true_sentiment_range"),
    )


def downgrade() -> None:
    op.drop_table("evaluation_labels")
    op.drop_index("idx_llm_call_log_called_at", table_name="llm_call_log")
    op.drop_table("llm_call_log")
    op.drop_index("idx_backtest_positions_run_id", table_name="backtest_positions")
    op.drop_table("backtest_positions")
    op.drop_table("backtest_runs")
    op.drop_index("idx_signals_ticker_date", table_name="signals")
    op.drop_table("signals")
    op.drop_table("extractions")
    op.drop_table("raw_documents")

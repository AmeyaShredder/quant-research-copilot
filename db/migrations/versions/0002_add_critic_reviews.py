"""add critic_reviews table + unreviewed-extractions partial index

The Critic agent was added after the Extractor pipeline was already
running in prod against the initial schema, hence this being a separate
migration rather than folded into 0001 — this is the real order things
were built in.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "critic_reviews",
        sa.Column("review_id", sa.BigInteger(), primary_key=True),
        sa.Column("extraction_id", sa.BigInteger(),
                  sa.ForeignKey("extractions.extraction_id", ondelete="CASCADE"), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "verdict IN ('supported','unsupported','overconfident','contradictory')",
            name="chk_verdict_values",
        ),
    )

    # Partial index added in the same migration since it depends on the
    # new table existing. Worker-queue pattern: "next unreviewed extraction".
    op.execute("""
        CREATE INDEX idx_extractions_unreviewed
        ON extractions (extraction_id)
        WHERE extraction_id NOT IN (SELECT extraction_id FROM critic_reviews)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_extractions_unreviewed")
    op.drop_table("critic_reviews")

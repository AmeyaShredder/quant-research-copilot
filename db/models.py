"""
SQLAlchemy models — generated FROM schema.sql, not the other way around.
Every column here should trace back to a line in db/schema.sql. If they
ever drift, schema.sql + the Alembic migration history are the source of
truth; regenerate this file to match, not vice versa.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RawDocument(Base):
    __tablename__ = "raw_documents"
    __table_args__ = (UniqueConstraint("content_hash", name="uq_raw_documents_content_hash"),)

    document_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    published_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    extractions: Mapped[list["Extraction"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    labels: Mapped[list["EvaluationLabel"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Extraction(Base):
    __tablename__ = "extractions"
    __table_args__ = (
        CheckConstraint("sentiment_score BETWEEN -1 AND 1", name="chk_sentiment_range"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="chk_confidence_range"),
    )

    extraction_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("raw_documents.document_id", ondelete="CASCADE"))
    entities: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["RawDocument"] = relationship(back_populates="extractions")
    critic_reviews: Mapped[list["CriticReview"]] = relationship(back_populates="extraction", cascade="all, delete-orphan")


class CriticReview(Base):
    __tablename__ = "critic_reviews"
    __table_args__ = (
        CheckConstraint(
            "verdict IN ('supported','unsupported','overconfident','contradictory')",
            name="chk_verdict_values",
        ),
    )

    review_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    extraction_id: Mapped[int] = mapped_column(ForeignKey("extractions.extraction_id", ondelete="CASCADE"))
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    extraction: Mapped["Extraction"] = relationship(back_populates="critic_reviews")


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("ticker", "date", name="uq_signals_ticker_date"),)

    signal_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    aggregated_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    components: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    sharpe: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 3))
    max_drawdown: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))
    hit_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    turnover: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    positions: Mapped[list["BacktestPosition"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class BacktestPosition(Base):
    __tablename__ = "backtest_positions"
    __table_args__ = (
        UniqueConstraint("run_id", "date", "ticker", name="uq_backtest_positions_run_date_ticker"),
    )

    position_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.run_id", ondelete="CASCADE"))
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    pnl: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)

    run: Mapped["BacktestRun"] = relationship(back_populates="positions")


class LlmCallLog(Base):
    __tablename__ = "llm_call_log"

    call_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("raw_documents.document_id", ondelete="SET NULL")
    )
    prompt_tokens: Mapped[int] = mapped_column(nullable=False)
    completion_tokens: Mapped[int] = mapped_column(nullable=False)
    latency_ms: Mapped[int] = mapped_column(nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    called_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvaluationLabel(Base):
    __tablename__ = "evaluation_labels"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_evaluation_labels_document"),
        CheckConstraint("true_sentiment_score BETWEEN -1 AND 1", name="chk_true_sentiment_range"),
    )

    label_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("raw_documents.document_id", ondelete="CASCADE"))
    true_event_type: Mapped[str] = mapped_column(Text, nullable=False)
    true_sentiment_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    labeled_by: Mapped[str] = mapped_column(Text, nullable=False)
    labeled_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["RawDocument"] = relationship(back_populates="labels")

import datetime as dt
from decimal import Decimal

import pytest

from db.repositories import DocumentRepository, SignalRepository, content_hash


def test_insert_if_new_is_idempotent(session):
    repo = DocumentRepository(session)
    doc1 = repo.insert_if_new(source="news", ticker="AAPL", doc_type="news_article", raw_text="Apple beats estimates.")
    assert doc1 is not None

    doc2 = repo.insert_if_new(source="news", ticker="AAPL", doc_type="news_article", raw_text="Apple beats estimates.")
    assert doc2 is None, "re-ingesting identical text must be a no-op, not a duplicate row"


def test_content_hash_is_stable_and_whitespace_insensitive():
    a = content_hash("Apple beats estimates.")
    b = content_hash("  Apple beats estimates.  ")
    assert a == b


def test_signal_upsert_updates_existing_row(session):
    repo = SignalRepository(session)
    today = dt.date.today()
    s1 = repo.upsert(ticker="AAPL", as_of=today, aggregated_score=Decimal("0.5"), components={"n_docs": 1})
    s2 = repo.upsert(ticker="AAPL", as_of=today, aggregated_score=Decimal("0.9"), components={"n_docs": 2})
    assert s1.signal_id == s2.signal_id
    assert s2.aggregated_score == Decimal("0.9")


def test_rolling_zscore_window_function_runs(session):
    repo = SignalRepository(session)
    base = dt.date.today() - dt.timedelta(days=5)
    for i, score in enumerate([0.1, 0.2, -0.1, 0.3, 0.0]):
        repo.upsert(ticker="MSFT", as_of=base + dt.timedelta(days=i),
                    aggregated_score=Decimal(str(score)), components={})
    session.flush()

    rows = repo.rolling_zscore(window_days=3)
    msft_rows = [r for r in rows if r["ticker"] == "MSFT"]
    assert len(msft_rows) == 5
    assert all("rolling_zscore" in r for r in msft_rows)

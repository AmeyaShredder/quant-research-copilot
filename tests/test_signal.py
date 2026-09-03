import datetime as dt
from decimal import Decimal

from db.models import CriticReview, Extraction, RawDocument
from signal.aggregator import aggregate_day


def _make_document(session, *, source: str) -> RawDocument:
    doc = RawDocument(
        source=source, ticker="AAPL", doc_type="news_article",
        raw_text=f"doc-{source}-{dt.datetime.now().timestamp()}",
        content_hash=f"hash-{source}-{dt.datetime.now().timestamp()}",
    )
    session.add(doc)
    session.flush()
    return doc


def test_rejected_extractions_are_excluded_from_aggregate(session):
    today = dt.date.today()

    good_doc = _make_document(session, source="edgar")
    good_ex = Extraction(
        document_id=good_doc.document_id, entities=[], event_type="earnings_beat",
        sentiment_score=Decimal("0.8"), confidence=Decimal("0.9"),
        evidence_quote="q", model_used="test",
    )
    session.add(good_ex)
    session.flush()

    bad_doc = _make_document(session, source="news")
    bad_ex = Extraction(
        document_id=bad_doc.document_id, entities=[], event_type="earnings_miss",
        sentiment_score=Decimal("-0.9"), confidence=Decimal("0.9"),
        evidence_quote="q", model_used="test",
    )
    session.add(bad_ex)
    session.flush()
    session.add(CriticReview(extraction_id=bad_ex.extraction_id, verdict="unsupported", reasoning="fabricated quote"))
    session.flush()

    # extracted_at defaults to now() server-side; force both to "today" for this test's date() filter
    session.execute(
        Extraction.__table__.update().where(Extraction.extraction_id.in_(
            [good_ex.extraction_id, bad_ex.extraction_id]
        )).values(extracted_at=dt.datetime.now())
    )

    result = aggregate_day(session, "AAPL", today)

    assert result["n_docs"] == 1, "only the non-rejected extraction should count"
    assert result["n_rejected"] == 1
    # aggregated score should equal the single surviving extraction's sentiment (0.8),
    # since it's the only contributor to the weighted mean.
    assert abs(result["aggregated_score"] - 0.8) < 1e-6


def test_empty_bucket_returns_neutral_zero_with_n_docs_zero(session):
    result = aggregate_day(session, "NOSUCHTICKER", dt.date.today())
    assert result["aggregated_score"] == 0.0
    assert result["n_docs"] == 0

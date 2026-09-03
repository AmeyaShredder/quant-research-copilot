"""
Orchestrates one pass of: ingest -> extract -> critique, per ticker.
Resumable/idempotent: DocumentRepository.insert_if_new returns None for
documents whose content_hash already exists, so re-running this on a
schedule naturally skips duplicates rather than needing "have I seen
this before?" checks scattered through application logic.
"""
from __future__ import annotations

import logging

from db.repositories import DocumentRepository
from db.session import get_session
from agents.llm_client import LLMClient
from agents.extractor import ExtractorAgent
from agents.critic import CriticAgent
from ingestion.base import DataSource

logger = logging.getLogger(__name__)


def run_pipeline_for_ticker(ticker: str, sources: list[DataSource], llm: LLMClient) -> dict[str, int]:
    extractor = ExtractorAgent(llm)
    critic = CriticAgent(llm)

    stats = {"ingested": 0, "skipped_duplicate": 0, "extracted": 0, "critiqued": 0}

    for source in sources:
        docs = source.run(ticker)
        for normalized in docs:
            # Each document's ingest + extraction + critic review commits
            # as one unit of work per the transaction-boundary design in
            # db/session.py (Part B.7).
            with get_session() as session:
                repo = DocumentRepository(session)
                record = repo.insert_if_new(
                    source=normalized.source,
                    ticker=normalized.ticker,
                    doc_type=normalized.doc_type,
                    raw_text=normalized.raw_text,
                    source_url=normalized.source_url,
                    published_at=normalized.published_at,
                )
                if record is None:
                    stats["skipped_duplicate"] += 1
                    continue
                stats["ingested"] += 1

                extraction = extractor.run(session, record)
                stats["extracted"] += 1

                critic.run(session, record, extraction)
                stats["critiqued"] += 1

    logger.info("pipeline run for %s: %s", ticker, stats)
    return stats

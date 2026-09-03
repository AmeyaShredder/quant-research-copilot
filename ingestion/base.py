"""
Common interface every ingestion source implements: fetch, normalize,
dedupe. Dedupe here is a light client-side pass (exact-duplicate text
within one fetch batch); the *authoritative* dedupe is the DB's
content_hash UNIQUE constraint via DocumentRepository.insert_if_new.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class NormalizedDocument:
    source: str
    ticker: str
    doc_type: str
    raw_text: str
    source_url: Optional[str] = None
    published_at: Optional[datetime] = None


class DataSource(abc.ABC):
    """Pluggable ingestion source interface."""

    name: str

    @abc.abstractmethod
    def fetch(self, ticker: str, **kwargs) -> list[dict]:
        """Hit the underlying API/feed, return raw provider-shaped records."""
        raise NotImplementedError

    @abc.abstractmethod
    def normalize(self, ticker: str, raw_record: dict) -> NormalizedDocument:
        """Map a provider-shaped record into our common NormalizedDocument."""
        raise NotImplementedError

    def dedupe(self, docs: list[NormalizedDocument]) -> list[NormalizedDocument]:
        """Client-side pass: drop exact-duplicate raw_text within this batch."""
        seen: set[str] = set()
        out: list[NormalizedDocument] = []
        for d in docs:
            key = d.raw_text.strip()
            if key in seen:
                continue
            seen.add(key)
            out.append(d)
        return out

    def run(self, ticker: str, **kwargs) -> list[NormalizedDocument]:
        raw = self.fetch(ticker, **kwargs)
        normalized = [self.normalize(ticker, r) for r in raw]
        return self.dedupe(normalized)

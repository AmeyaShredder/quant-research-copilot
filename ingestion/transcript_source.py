"""
Earnings call transcript source.

IMPORTANT / README-worthy caveat: there is no reliable free full-transcript
API with no key at time of writing. Rather than pretend otherwise, this
source reads from a small hand-collected sample set of 5-10 transcripts
checked into config/sample_transcripts/ (public excerpts, cited by URL).
This is CLEARLY A SAMPLE, not full coverage — do not represent it as a
live transcript feed in the README or in an interview.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from ingestion.base import DataSource, NormalizedDocument

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "..", "config", "sample_transcripts")


class SampleTranscriptSource(DataSource):
    name = "transcript"

    def fetch(self, ticker: str, **kwargs) -> list[dict]:
        path = os.path.join(SAMPLE_DIR, f"{ticker.upper()}.json")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return json.load(f)

    def normalize(self, ticker: str, raw_record: dict) -> NormalizedDocument:
        published_at = None
        if raw_record.get("date"):
            try:
                published_at = datetime.strptime(raw_record["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                published_at = None
        return NormalizedDocument(
            source=self.name,
            ticker=ticker,
            doc_type="transcript",
            raw_text=raw_record.get("excerpt", ""),
            source_url=raw_record.get("source_url"),
            published_at=published_at,
        )

"""
SEC EDGAR full-text search source — free, no API key. Docs:
https://www.sec.gov/edgar/search/#/ (the /efts/... endpoint backs the UI)

EDGAR requires a descriptive User-Agent identifying the requester; set
EDGAR_USER_AGENT in your environment ("Your Name your@email.com") before
running this in anger — SEC will rate-limit/block generic UAs.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from ingestion.base import DataSource, NormalizedDocument

EDGAR_FTS_URL = "https://efts.sec.gov/LATEST/search-index"


class EdgarFilingSource(DataSource):
    name = "edgar"

    def __init__(self, forms: tuple[str, ...] = ("8-K", "10-Q")):
        self.forms = forms

    def fetch(self, ticker: str, **kwargs) -> list[dict]:
        headers = {"User-Agent": os.environ.get("EDGAR_USER_AGENT", "quant-research-copilot research@example.com")}
        results: list[dict] = []
        for form in self.forms:
            params = {"q": ticker, "forms": form, "dateRange": "custom"}
            resp = requests.get(EDGAR_FTS_URL, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            for hit in data.get("hits", {}).get("hits", []):
                src = hit.get("_source", {})
                results.append({
                    "form": form,
                    "display_names": src.get("display_names", []),
                    "file_date": src.get("file_date"),
                    "accession_no": src.get("adsh"),
                    "root_form": src.get("root_form"),
                    "summary": src.get("summary", src.get("file_description", "")),
                    "id": hit.get("_id"),
                })
        return results

    def normalize(self, ticker: str, raw_record: dict) -> NormalizedDocument:
        accession = raw_record.get("accession_no", "")
        url = None
        if accession:
            acc_no_dashes = accession.replace("-", "")
            url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum={acc_no_dashes}"
        raw_text = (
            f"Form {raw_record.get('form')} filed by "
            f"{', '.join(raw_record.get('display_names', [])) or ticker} "
            f"on {raw_record.get('file_date')}. {raw_record.get('summary', '')}"
        ).strip()
        published_at = None
        if raw_record.get("file_date"):
            try:
                published_at = datetime.strptime(raw_record["file_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                published_at = None
        return NormalizedDocument(
            source=self.name,
            ticker=ticker,
            doc_type=raw_record.get("form", "filing"),
            raw_text=raw_text,
            source_url=url,
            published_at=published_at,
        )

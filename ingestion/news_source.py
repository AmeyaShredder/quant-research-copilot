"""
News ingestion via yfinance's `.news` property (free, no key required).
Falls back gracefully — yfinance's news schema has changed across
versions in the past, so we defensively .get() everything.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ingestion.base import DataSource, NormalizedDocument


class YFinanceNewsSource(DataSource):
    name = "news"

    def fetch(self, ticker: str, **kwargs) -> list[dict]:
        import yfinance as yf  # imported lazily so the module is importable without the dep at test time

        tk = yf.Ticker(ticker)
        return tk.news or []

    def normalize(self, ticker: str, raw_record: dict) -> NormalizedDocument:
        content = raw_record.get("content", raw_record)  # newer yfinance nests under "content"
        title = content.get("title", "")
        summary = content.get("summary", "") or content.get("description", "")
        raw_text = f"{title}\n\n{summary}".strip()
        url = (content.get("canonicalUrl") or {}).get("url") if isinstance(content.get("canonicalUrl"), dict) else content.get("link")
        pub_date = content.get("pubDate")
        published_at = None
        if pub_date:
            try:
                published_at = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
            except ValueError:
                published_at = None
        return NormalizedDocument(
            source=self.name,
            ticker=ticker,
            doc_type="news_article",
            raw_text=raw_text,
            source_url=url,
            published_at=published_at or datetime.now(timezone.utc),
        )

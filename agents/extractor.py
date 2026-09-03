"""
Extractor agent: reads a raw document, returns structured JSON
(entities/tickers, event type, sentiment -1..1, confidence, evidence
quote), written to `extractions` via the repository layer.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from agents.llm_client import LLMClient
from db.models import Extraction, RawDocument

SYSTEM_PROMPT = """You are a financial-document extraction agent. Given a \
document (news article, SEC filing, or earnings-call excerpt), extract:
- entities: list of {"ticker": str, "role": str} objects mentioned
- event_type: one short snake_case label, e.g. earnings_beat, earnings_miss,
  guidance_cut, guidance_raise, litigation, mgmt_change, product_launch, other
- sentiment_score: float from -1 (very negative) to 1 (very positive)
- confidence: float from 0 to 1, your confidence in this extraction
- evidence_quote: the exact short quote (<= 200 chars) from the document
  that most directly supports event_type and sentiment_score

Respond with ONLY a JSON object with exactly these keys. No prose, no
markdown fences."""


class ExtractorAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(self, session: Session, document: RawDocument) -> Extraction:
        result = self.llm.call_json(
            system=SYSTEM_PROMPT,
            user=f"TICKER: {document.ticker}\nDOC_TYPE: {document.doc_type}\n\n{document.raw_text}",
            session=session,
            stage="extractor",
            document_id=document.document_id,
        )
        extraction = Extraction(
            document_id=document.document_id,
            entities=result.get("entities", []),
            event_type=result["event_type"],
            sentiment_score=Decimal(str(result["sentiment_score"])),
            confidence=Decimal(str(result["confidence"])),
            evidence_quote=result["evidence_quote"][:2000],
            model_used=self.llm.model,
        )
        session.add(extraction)
        session.flush()
        return extraction

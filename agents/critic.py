"""
Critic agent: reviews the Extractor's output against the source text,
flags unsupported/overconfident/contradictory extractions, writes to
`critic_reviews`. Agreement/disagreement rate is surfaced via
v_extraction_accuracy_by_source and DocumentRepository.extraction_agreement_by_source.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from agents.llm_client import LLMClient
from db.models import CriticReview, Extraction, RawDocument

SYSTEM_PROMPT = """You are a critic agent reviewing another model's \
extraction against the original source text. Verdicts:
- "supported": the evidence_quote genuinely appears in the source and
  the event_type/sentiment are a reasonable read of it
- "unsupported": the evidence_quote is fabricated or not in the source
- "overconfident": the extraction is plausible but confidence is too
  high given how ambiguous the source text is
- "contradictory": the source text contradicts the extracted sentiment
  or event_type

Respond with ONLY a JSON object: {"verdict": "...", "reasoning": "..."}.
Reasoning should be 1-2 sentences. No markdown fences."""


class CriticAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(self, session: Session, document: RawDocument, extraction: Extraction) -> CriticReview:
        user = (
            f"SOURCE TEXT:\n{document.raw_text}\n\n"
            f"EXTRACTION TO REVIEW:\n"
            f"event_type: {extraction.event_type}\n"
            f"sentiment_score: {extraction.sentiment_score}\n"
            f"confidence: {extraction.confidence}\n"
            f"evidence_quote: {extraction.evidence_quote}"
        )
        result = self.llm.call_json(
            system=SYSTEM_PROMPT,
            user=user,
            session=session,
            stage="critic",
            document_id=document.document_id,
        )
        review = CriticReview(
            extraction_id=extraction.extraction_id,
            verdict=result["verdict"],
            reasoning=result["reasoning"],
        )
        session.add(review)
        session.flush()
        return review

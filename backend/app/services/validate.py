from backend.app.prompts import PROMPT_VERSION
from backend.app.schemas import TriageResult
from backend.app.services.gemini import MODEL_NAME


def validate_triage_result(
    ticket_id: int,
    data: dict,
    latency_ms: int,
) -> TriageResult:
    result = TriageResult.model_validate(
        {
            **data,
            "ticket_id": ticket_id,
            "model": MODEL_NAME,
            "prompt_version": PROMPT_VERSION,
            "latency_ms": latency_ms,
            "status": "ok",
            "error": None,
        }
    )

    # The application determines human review.
    # This prevents the LLM from overriding this safety rule.
    result.needs_human_review = (
        result.confidence < 0.6
        or result.urgency.value == "Critical"
    )

    return result
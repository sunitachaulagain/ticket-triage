"""Batch triage service.

Runs one ticket or the whole dataset through the Gemini triage pipeline:

    ticket -> build_triage_prompt -> call_gemini -> extract_model_output
           -> validate_triage_result

Processing is sequential on purpose so the real batch runtime can be
measured before any concurrency is introduced.
"""

import time

from backend.app.dataset import SupportTicket, load_tickets
from backend.app.prompts import PROMPT_VERSION, build_triage_prompt
from backend.app.schemas import TriageResult, TriageStatus
from backend.app.services.gemini import MODEL_NAME, call_gemini
from backend.app.services.parser import extract_model_output
from backend.app.services.triage_schema import TRIAGE_RESPONSE_SCHEMA
from backend.app.services.validate import validate_triage_result


# TriageResult allows these to be null so failed tickets can be reported
# without inventing a classification. Checking them here keeps the success
# path exactly as strict as before.
REQUIRED_AI_FIELDS = (
    "urgency",
    "category",
    "sentiment",
    "suggested_reply",
    "confidence",
    "rationale",
    "needs_human_review",
    "tags",
)

MAX_ERROR_LENGTH = 500


async def triage_ticket(ticket: SupportTicket) -> TriageResult:
    """Triage a single ticket. Raises on failure; triage_batch handles that."""
    prompt = build_triage_prompt(ticket.id, ticket.message)

    data, latency_ms = await call_gemini(
        prompt,
        TRIAGE_RESPONSE_SCHEMA,
    )

    raw = extract_model_output(data)

    missing = [name for name in REQUIRED_AI_FIELDS if name not in raw]

    if missing:
        raise ValueError(
            "Gemini response is missing required fields: "
            + ", ".join(missing)
        )

    return validate_triage_result(ticket.id, raw, latency_ms)


def build_failed_result(
    ticket_id: int,
    latency_ms: int,
    error: str,
) -> TriageResult:
    """Build a failed result without inventing any AI classification."""
    if len(error) > MAX_ERROR_LENGTH:
        error = error[:MAX_ERROR_LENGTH] + "... (truncated)"

    return TriageResult(
        ticket_id=ticket_id,
        needs_human_review=True,
        model=MODEL_NAME,
        prompt_version=PROMPT_VERSION,
        latency_ms=latency_ms,
        status=TriageStatus.FAILED,
        error=error,
    )


async def triage_batch() -> list[TriageResult]:
    """Triage every ticket in the dataset, sequentially.

    A single ticket failure never stops the batch. A dataset loading
    failure does propagate, since there would be no ticket IDs to report.
    """
    tickets = load_tickets()

    results: list[TriageResult] = []

    for ticket in tickets:
        start = time.perf_counter()

        try:
            results.append(await triage_ticket(ticket))
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)

            results.append(
                build_failed_result(
                    ticket_id=ticket.id,
                    latency_ms=latency_ms,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    return results
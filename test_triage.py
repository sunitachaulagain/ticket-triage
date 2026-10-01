"""Single-ticket smoke test for the triage pipeline.

Run explicitly:

    python test_triage.py

Triages ONE ticket (the first in the dataset) and asserts the validated
result is internally consistent. This is not the batch runner.
"""

import asyncio
import json

from backend.app.dataset import load_tickets
from backend.app.prompts import build_triage_prompt
from backend.app.services.gemini import call_gemini
from backend.app.services.triage_schema import TRIAGE_RESPONSE_SCHEMA
from backend.app.services.parser import extract_model_output
from backend.app.services.validate import validate_triage_result
from backend.app.schemas import TriageStatus


async def main() -> None:
    tickets = load_tickets()
    ticket = tickets[0]

    prompt = build_triage_prompt(ticket.id, ticket.message)

    data, latency_ms = await call_gemini(
        prompt,
        TRIAGE_RESPONSE_SCHEMA,
    )

    print(f"Ticket ID: {ticket.id}")
    print(f"Latency: {latency_ms} ms")

    raw = extract_model_output(data)

    print("\nRaw model output:")
    print(json.dumps(raw, indent=2))

    result = validate_triage_result(
        ticket.id,
        raw,
        latency_ms,
    )

    print("\nValidated TriageResult:")
    print(json.dumps(result.model_dump(mode="json"), indent=2))

    expected_review = result.confidence < 0.6 or result.urgency.value == "Critical"

    assert result.ticket_id == ticket.id, "ticket_id does not match source ticket"
    assert result.status is TriageStatus.OK, "status should be ok on a successful run"
    assert result.latency_ms == latency_ms, "latency_ms was not carried through"
    assert result.latency_ms >= 0, "latency_ms must not be negative"
    assert result.model, "model should be populated"
    assert result.prompt_version, "prompt_version should be populated"
    assert result.error is None, "error should be None on a successful run"

    assert 0.0 <= result.confidence <= 1.0, "confidence must be between 0 and 1"
    assert result.suggested_reply.strip(), "suggested_reply must not be empty"
    assert len(result.rationale) <= 240, "rationale must be 240 characters or fewer"
    assert result.tags is not None, "tags should always be present"

    assert (
        result.needs_human_review is expected_review
    ), "needs_human_review must follow the application rule (low confidence or Critical)"

    print("\nAll smoke assertions passed.")


if __name__ == "__main__":
    asyncio.run(main())
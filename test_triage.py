import asyncio
import json

from backend.app.dataset import load_tickets
from backend.app.prompts import build_triage_prompt
from backend.app.services.gemini import call_gemini
from backend.app.services.triage_schema import TRIAGE_RESPONSE_SCHEMA
from backend.app.services.parser import extract_model_output
from backend.app.services.validate import validate_triage_result


async def main():
    tickets = load_tickets()
    ticket = tickets[0]

    prompt = build_triage_prompt(ticket.id, ticket.message)

    data, latency_ms = await call_gemini(
        prompt,
        TRIAGE_RESPONSE_SCHEMA,
    )

    print(f"Ticket ID: {ticket.id}")
    print(f"Latency: {latency_ms} ms")

    result = extract_model_output(data)

    validated = validate_triage_result(
        ticket.id,
        result,
        latency_ms,
    )



if __name__ == "__main__":
    asyncio.run(main())
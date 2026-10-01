import time

import httpx

from backend.app.config import GEMINI_API_KEY
from backend.app.prompts import SYSTEM_PROMPT


MODEL_NAME = "gemini-3.5-flash-lite"

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"


async def call_gemini(
    user_prompt: str,
    response_schema: dict,
) -> tuple[dict, int]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    payload = {
        "model": MODEL_NAME,
        "system_instruction": SYSTEM_PROMPT,
        "input": user_prompt,
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": response_schema,
        },
    }

    headers = {
        "x-goog-api-key": GEMINI_API_KEY,
        "Content-Type": "application/json",
    }

    start = time.perf_counter()

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            GEMINI_URL,
            headers=headers,
            json=payload,
        )

    latency_ms = int((time.perf_counter() - start) * 1000)

    response.raise_for_status()

    data = response.json()

    return data, latency_ms
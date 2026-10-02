import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx

from backend.app.config import GEMINI_API_KEY
from backend.app.prompts import SYSTEM_PROMPT


MODEL_NAME = "gemini-3.5-flash-lite"

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

# Rate limiting is the only failure worth repeating: a 429 means the request
# was rejected for quota reasons and will be accepted once the window resets.
# Client errors (400, 401, 403, 404) would fail identically on a retry, and
# server errors (5xx) are not known to be transient here, so neither is
# retried. Transport failures and timeouts are not retried for the same
# reason: they carry no signal that a second attempt would behave differently.
MAX_RETRIES = 3

BACKOFF_BASE_SECONDS = 1.0


def _should_retry(response: httpx.Response) -> bool:
    return response.status_code == 429


def _backoff_seconds(attempt: int) -> float:
    """Delay before the retry that follows ``attempt``, so 1s, 2s, 4s."""
    return BACKOFF_BASE_SECONDS * (2 ** attempt)


async def call_gemini(
    user_prompt: str,
    response_schema: dict,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[dict, int]:
    """Call Gemini once, retrying only on HTTP 429.

    ``sleep`` and ``transport`` are injection points so tests can drive the
    retry path without waiting or opening a socket.
    """
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

    async with httpx.AsyncClient(timeout=60.0, transport=transport) as client:
        for attempt in range(MAX_RETRIES + 1):
            response = await client.post(
                GEMINI_URL,
                headers=headers,
                json=payload,
            )

            if not _should_retry(response):
                break

            if attempt == MAX_RETRIES:
                # Retries are exhausted. Surface the 429 rather than sleeping
                # again, so the caller sees the original rate limit error.
                response.raise_for_status()

            await sleep(_backoff_seconds(attempt))

    # Measured after the loop so backoff delays are part of the reported
    # latency, not hidden by them.
    latency_ms = int((time.perf_counter() - start) * 1000)

    response.raise_for_status()

    data = response.json()

    return data, latency_ms
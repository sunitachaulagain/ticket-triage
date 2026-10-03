import asyncio
import math
import random
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

# When the server tells us when to come back, that is a better answer than a
# guess, so a valid Retry-After replaces the backoff curve. It is still
# bounded: an unbounded Retry-After would hold a concurrency slot far longer
# than the rest of the batch is worth waiting for.
MAX_RETRY_DELAY_SECONDS = 30.0

# Concurrent tickets that all receive a 429 would otherwise retry in lockstep
# and keep hitting the same rate limit window. Spreading the delay breaks that
# synchronisation. Jitter is applied before the cap, so MAX_RETRY_DELAY_SECONDS
# stays a true upper bound on any single sleep.
JITTER_MIN = 0.8
JITTER_MAX = 1.2


def _should_retry(response: httpx.Response) -> bool:
    return response.status_code == 429


def _backoff_seconds(attempt: int) -> float:
    """Delay before the retry that follows ``attempt``, so 1s, 2s, 4s."""
    return BACKOFF_BASE_SECONDS * (2 ** attempt)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Seconds requested by a valid ``Retry-After`` header, else ``None``.

    Only the numeric form is honoured. Gemini sends seconds, and resolving an
    HTTP-date would mean trusting the local clock with the answer, so an
    unparseable value falls back to the backoff curve instead of being guessed
    at.
    """
    raw = response.headers.get("Retry-After")

    if raw is None:
        return None

    try:
        seconds = float(raw.strip())
    except (AttributeError, ValueError):
        # float() also accepts "nan" and "inf", neither of which is a delay.
        return None

    if not math.isfinite(seconds) or seconds < 0:
        return None

    return seconds


def _retry_delay_seconds(
    response: httpx.Response,
    attempt: int,
    jitter: Callable[[float, float], float],
) -> float:
    """Delay before the retry that follows ``attempt``.

    A valid ``Retry-After`` wins over the exponential backoff; anything else
    uses it. The result is jittered so simultaneous 429s do not retry at the
    same instant, then capped so no single sleep exceeds
    ``MAX_RETRY_DELAY_SECONDS``.
    """
    requested = _retry_after_seconds(response)

    delay = _backoff_seconds(attempt) if requested is None else requested

    return min(
        delay * jitter(JITTER_MIN, JITTER_MAX),
        MAX_RETRY_DELAY_SECONDS,
    )


async def call_gemini(
    user_prompt: str,
    response_schema: dict,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    transport: httpx.AsyncBaseTransport | None = None,
    jitter: Callable[[float, float], float] = random.uniform,
) -> tuple[dict, int]:
    """Call Gemini once, retrying only on HTTP 429.

    ``sleep``, ``transport`` and ``jitter`` are injection points so tests can
    drive the retry path without waiting, without opening a socket, and without
    depending on a random draw.
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

            await sleep(_retry_delay_seconds(response, attempt, jitter))

    # Measured after the loop so backoff delays are part of the reported
    # latency, not hidden by them.
    latency_ms = int((time.perf_counter() - start) * 1000)

    response.raise_for_status()

    data = response.json()

    return data, latency_ms
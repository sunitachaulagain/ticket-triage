import asyncio
import math
import random
import time
from collections.abc import Awaitable, Callable

import httpx

from backend.app.config import GROQ_API_KEY
from backend.app.prompts import SYSTEM_PROMPT


MODEL_NAME = "openai/gpt-oss-120b"

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Groq's Structured Outputs supports a constrained-decoding mode (strict) on
# this model, which guarantees the reply matches the schema instead of merely
# being valid JSON. Strict mode requires closed objects, so the schema is sent
# with additionalProperties disabled rather than trusting the caller to have
# written it that way.
RESPONSE_SCHEMA_NAME = "triage_result"

# This model is a reasoning model, and its reasoning tokens are billed as
# output. The triage decision does not benefit from a long chain of thought,
# and the reasoning budget is charged against the per-minute token allowance
# below, so it is held to the cheapest setting.
REASONING_EFFORT = "low"

# Groq meters this deployment at 8,000 tokens per minute. A triage request
# spends roughly 1,500 of them, and the system prompt alone is over 1,100, so
# five or six requests inside the same minute exhaust the window and every
# later ticket is rejected with a 429 that the retry budget cannot outlast.
# Requests are therefore spaced by a floor interval derived from that budget
# instead of being sent as fast as the batch concurrency allows.
TOKEN_BUDGET_PER_MINUTE = 8_000

ESTIMATED_TOKENS_PER_REQUEST = 1_500

REQUEST_SPACING_SECONDS = (
    60.0 * ESTIMATED_TOKENS_PER_REQUEST / TOKEN_BUDGET_PER_MINUTE
)

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


class _RequestPacer:
    """Holds request starts at least ``min_interval`` seconds apart.

    A batch runs several tickets at once, so without this they would share one
    minute's token allowance and starve each other. The lock makes the spacing
    hold across those concurrent callers rather than per caller.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last_started: float | None = None

    async def wait(self, min_interval: float) -> None:
        async with self._lock:
            now = time.monotonic()

            if self._last_started is not None:
                delay = min_interval - (now - self._last_started)

                if delay > 0:
                    await asyncio.sleep(delay)

            self._last_started = time.monotonic()


PACER = _RequestPacer()


def _strict_schema(response_schema: dict) -> dict:
    """The outbound copy of ``response_schema`` for Groq strict mode.

    Strict mode post-validates string lengths and rejects the whole request
    with a 400 when the model overruns one, so a length cap cannot be enforced
    by the schema. The cap is restated as a description the model can follow
    instead, and the application-side validation stays the thing that enforces
    it. The caller's schema is copied, never mutated.
    """
    properties: dict = {}

    for name, field in response_schema.get("properties", {}).items():
        limit = field.get("maxLength")

        if limit is None:
            properties[name] = field
            continue

        properties[name] = {
            key: value
            for key, value in field.items()
            if key != "maxLength"
        }
        properties[name]["description"] = f"At most {limit} characters."

    return {
        **response_schema,
        "properties": properties,
        "additionalProperties": False,
    }


def _should_retry(response: httpx.Response) -> bool:
    return response.status_code == 429


def _backoff_seconds(attempt: int) -> float:
    """Delay before the retry that follows ``attempt``, so 1s, 2s, 4s."""
    return BACKOFF_BASE_SECONDS * (2 ** attempt)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Seconds requested by a valid ``Retry-After`` header, else ``None``.

    Only the numeric form is honoured. Groq sends seconds, and resolving an
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

    The exponential backoff for the attempt is the ceiling: a valid
    ``Retry-After`` can only shorten the wait, never stretch it past the 1s,
    2s, 4s curve. In a batch, a long ``Retry-After`` would otherwise hold a
    concurrency slot for tens of seconds per ticket and turn one rate limit
    into a multi-minute stall. The result is jittered so simultaneous 429s do
    not retry at the same instant, then capped so no single sleep exceeds
    ``MAX_RETRY_DELAY_SECONDS``.
    """
    delay = _backoff_seconds(attempt)

    requested = _retry_after_seconds(response)

    if requested is not None:
        delay = min(delay, requested)

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
    min_interval: float | None = None,
) -> tuple[dict, int]:
    """Call Groq once, retrying only on HTTP 429.

    ``sleep``, ``transport`` and ``jitter`` are injection points so tests can
    drive the retry path without waiting, without opening a socket, and without
    depending on a random draw. ``min_interval`` opts into request pacing and
    defaults to none, so a single call is never delayed.
    """
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "reasoning_effort": REASONING_EFFORT,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": RESPONSE_SCHEMA_NAME,
                "strict": True,
                "schema": _strict_schema(response_schema),
            },
        },
    }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    # Paced before the clock starts, so the wait between tickets is not
    # reported as this ticket's latency.
    if min_interval is not None:
        await PACER.wait(min_interval)

    start = time.perf_counter()

    async with httpx.AsyncClient(timeout=60.0, transport=transport) as client:
        for attempt in range(MAX_RETRIES + 1):
            response = await client.post(
                GROQ_URL,
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
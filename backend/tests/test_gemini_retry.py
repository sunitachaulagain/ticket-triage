"""Gemini retry tests. None of these contact the Gemini API.

Every test drives ``call_gemini`` through an ``httpx.MockTransport`` and an
injected ``sleep``, so no socket is opened and no real time passes. The
autouse ``no_network`` fixture turns any accidental real connection into a
loud failure rather than a silent spend of API quota.

pytest-asyncio is not a dependency here, so each test drives its own event
loop with ``asyncio.run``.
"""

import asyncio
import socket
import time

import httpx
import pytest

from backend.app.services import gemini
from backend.app.services.gemini import (
    JITTER_MAX,
    JITTER_MIN,
    MAX_RETRIES,
    MAX_RETRY_DELAY_SECONDS,
    _backoff_seconds,
    _retry_after_seconds,
    _retry_delay_seconds,
    _should_retry,
    call_gemini,
)


SCHEMA = {"type": "object", "properties": {}}

OK_BODY = {"steps": [{"type": "model_output"}]}


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})


def _host_of(address) -> str:
    return str(address[0]) if isinstance(address, tuple) and address else str(
        address
    )


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail on any non-loopback socket connection.

    asyncio builds its internal self-pipe from a real loopback socketpair on
    Windows, so loopback has to stay allowed. Everything else would be an
    outbound request, and these tests must never make one.
    """
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_connect(sock, address, *args, **kwargs):
        if _host_of(address) not in LOOPBACK_HOSTS:
            raise AssertionError(
                f"a test attempted a real network connection to {address}"
            )
        return original_connect(sock, address, *args, **kwargs)

    def guarded_connect_ex(sock, address, *args, **kwargs):
        if _host_of(address) not in LOOPBACK_HOSTS:
            raise AssertionError(
                f"a test attempted a real network connection to {address}"
            )
        return original_connect_ex(sock, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)


@pytest.fixture(autouse=True)
def configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use a fake key so these tests never depend on a real .env value."""
    monkeypatch.setattr(gemini, "GEMINI_API_KEY", "test-key")


class FakeClock:
    """perf_counter replacement advanced by the injected sleep."""

    def __init__(self) -> None:
        self.now = 0.0

    def perf_counter(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def build_transport(responses: list):
    """Transport that replays ``responses`` in order, last one repeating.

    An int is a status code with an OK body; a prebuilt ``httpx.Response`` is
    returned as-is, which is how response headers such as ``Retry-After`` are
    simulated. A ``BaseException`` in the list is raised instead of returned,
    which is how timeouts, transport failures and cancellation are simulated.
    """
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)

        item = responses[min(len(requests) - 1, len(responses) - 1)]

        if isinstance(item, BaseException):
            raise item

        if isinstance(item, httpx.Response):
            return item

        return httpx.Response(item, json=OK_BODY)

    return httpx.MockTransport(handler), requests


def rate_limited(retry_after: str | None = None) -> httpx.Response:
    """A 429 response, optionally carrying a ``Retry-After`` header."""
    headers = {} if retry_after is None else {"Retry-After": retry_after}

    return httpx.Response(429, headers=headers, json=OK_BODY)


def no_jitter(low: float, high: float) -> float:
    """Jitter stub returning a neutral 1.0 multiplier.

    This leaves the selected delay exactly assertable. The production default
    is ``random.uniform``, which would make every delay assertion below
    nondeterministic.
    """
    return 1.0


def fixed_jitter(value: float):
    """Jitter stub returning a constant, to prove jitter scales the delay."""

    def jitter(low: float, high: float) -> float:
        return value

    return jitter


def recording_jitter(value: float):
    """Jitter stub recording the bounds it was called with."""
    calls: list[tuple[float, float]] = []

    def jitter(low: float, high: float) -> float:
        calls.append((low, high))
        return value

    return jitter, calls


def recording_sleep(clock: FakeClock | None = None):
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

        if clock is not None:
            clock.advance(delay)

    return sleep, delays


def test_first_attempt_success_makes_one_request() -> None:
    transport, requests = build_transport([200])
    sleep, delays = recording_sleep()

    data, latency_ms = asyncio.run(
        call_gemini("prompt", SCHEMA, sleep=sleep, transport=transport)
    )

    assert len(requests) == 1
    assert delays == []
    assert data == OK_BODY
    assert latency_ms >= 0


def test_retries_on_429_then_succeeds() -> None:
    transport, requests = build_transport([429, 429, 200])
    sleep, delays = recording_sleep()

    data, latency_ms = asyncio.run(
        call_gemini(
            "prompt", SCHEMA, sleep=sleep, transport=transport, jitter=no_jitter
        )
    )

    assert len(requests) == 3
    assert delays == [1.0, 2.0]
    assert data == OK_BODY
    assert latency_ms >= 0


def test_raises_429_after_three_retries() -> None:
    transport, requests = build_transport([429])
    sleep, delays = recording_sleep()

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        asyncio.run(
            call_gemini(
                "prompt",
                SCHEMA,
                sleep=sleep,
                transport=transport,
                jitter=no_jitter,
            )
        )

    # Initial request plus MAX_RETRIES, and no sleep after the last one.
    assert len(requests) == MAX_RETRIES + 1 == 4
    assert delays == [1.0, 2.0, 4.0]

    # The original rate limit error is what surfaces.
    assert excinfo.value.response.status_code == 429


@pytest.mark.parametrize(
    "status_code",
    [400, 401, 403, 404, 500, 502, 503],
)
def test_does_not_retry_other_status_codes(status_code: int) -> None:
    transport, requests = build_transport([status_code])
    sleep, delays = recording_sleep()

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        asyncio.run(
            call_gemini("prompt", SCHEMA, sleep=sleep, transport=transport)
        )

    assert len(requests) == 1
    assert delays == []
    assert excinfo.value.response.status_code == status_code


def test_does_not_retry_timeout() -> None:
    transport, requests = build_transport([httpx.ReadTimeout("timed out")])
    sleep, delays = recording_sleep()

    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(
            call_gemini("prompt", SCHEMA, sleep=sleep, transport=transport)
        )

    assert len(requests) == 1
    assert delays == []


def test_does_not_retry_transport_error() -> None:
    transport, requests = build_transport([httpx.ConnectError("refused")])
    sleep, delays = recording_sleep()

    with pytest.raises(httpx.ConnectError):
        asyncio.run(
            call_gemini("prompt", SCHEMA, sleep=sleep, transport=transport)
        )

    assert len(requests) == 1
    assert delays == []


def test_cancellation_propagates_without_retry() -> None:
    transport, requests = build_transport([asyncio.CancelledError()])
    sleep, delays = recording_sleep()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            call_gemini("prompt", SCHEMA, sleep=sleep, transport=transport)
        )

    assert len(requests) == 1
    assert delays == []


def test_latency_includes_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    monkeypatch.setattr(time, "perf_counter", clock.perf_counter)

    transport, _ = build_transport([429, 429, 200])
    sleep, delays = recording_sleep(clock)

    _, latency_ms = asyncio.run(
        call_gemini(
            "prompt",
            SCHEMA,
            sleep=sleep,
            transport=transport,
            jitter=no_jitter,
        )
    )

    # Backoff delays must be inside the measurement, not excluded from it.
    assert delays == [1.0, 2.0]
    assert latency_ms == 3000


def test_backoff_delays_are_exponential() -> None:
    assert [_backoff_seconds(attempt) for attempt in range(MAX_RETRIES)] == [
        1.0,
        2.0,
        4.0,
    ]


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("5", 5.0),
        ("0", 0.0),
        (" 2.5 ", 2.5),
        ("120", 120.0),
        ("", None),
        ("   ", None),
        ("soon", None),
        ("Wed, 21 Oct 2015 07:28:00 GMT", None),
        ("-5", None),
        ("nan", None),
        ("inf", None),
        ("1,5", None),
    ],
)
def test_retry_after_seconds_parsing(header: str | None, expected) -> None:
    """Only the numeric form is a usable delay; everything else is ignored."""
    response = httpx.Response(429, json=OK_BODY)

    if header is not None:
        response.headers["Retry-After"] = header

    assert _retry_after_seconds(response) == expected


def test_valid_retry_after_is_honored() -> None:
    # 0.5s asks for less than the 1s backoff, so it is honoured as-is.
    transport, requests = build_transport([rate_limited("0.5"), 200])
    sleep, delays = recording_sleep()

    data, _ = asyncio.run(
        call_gemini(
            "prompt",
            SCHEMA,
            sleep=sleep,
            transport=transport,
            jitter=no_jitter,
        )
    )

    assert len(requests) == 2
    assert delays == [0.5]
    assert data == OK_BODY


def test_retry_after_never_exceeds_exponential_on_any_retry() -> None:
    transport, requests = build_transport(
        [rate_limited("3"), rate_limited("9"), rate_limited("1"), 200]
    )
    sleep, delays = recording_sleep()

    asyncio.run(
        call_gemini(
            "prompt",
            SCHEMA,
            sleep=sleep,
            transport=transport,
            jitter=no_jitter,
        )
    )

    assert len(requests) == 4
    # The backoff (1s, 2s, 4s) is the ceiling: 3 and 9 are clamped to it,
    # while 1 shortens the final wait.
    assert delays == [1.0, 2.0, 1.0]


@pytest.mark.parametrize(
    "header", ["", "   ", "soon", "abc", "-5", "nan", "inf", "1,5"]
)
def test_invalid_retry_after_falls_back_to_exponential(header: str) -> None:
    transport, _ = build_transport([rate_limited(header), 200])
    sleep, delays = recording_sleep()

    asyncio.run(
        call_gemini(
            "prompt",
            SCHEMA,
            sleep=sleep,
            transport=transport,
            jitter=no_jitter,
        )
    )

    assert delays == [1.0]


def test_missing_retry_after_falls_back_to_exponential() -> None:
    transport, _ = build_transport([rate_limited(), 429, 200])
    sleep, delays = recording_sleep()

    asyncio.run(
        call_gemini(
            "prompt",
            SCHEMA,
            sleep=sleep,
            transport=transport,
            jitter=no_jitter,
        )
    )

    assert delays == [1.0, 2.0]


def test_large_retry_after_is_bounded_by_backoff() -> None:
    transport, _ = build_transport([rate_limited("120"), 200])
    sleep, delays = recording_sleep()

    asyncio.run(
        call_gemini(
            "prompt",
            SCHEMA,
            sleep=sleep,
            transport=transport,
            jitter=no_jitter,
        )
    )

    # A huge Retry-After can no longer stretch the wait past the 1s backoff.
    assert delays == [1.0]


def test_jitter_applies_to_the_bounded_retry_after_delay() -> None:
    transport, _ = build_transport([rate_limited("120"), 200])
    sleep, delays = recording_sleep()

    asyncio.run(
        call_gemini(
            "prompt",
            SCHEMA,
            sleep=sleep,
            transport=transport,
            jitter=fixed_jitter(1.2),
        )
    )

    # Bounded to the 1s backoff first, then jittered: 1.0 * 1.2.
    assert delays == [1.2]


def test_no_retry_sleep_ever_exceeds_the_limit() -> None:
    """Across every attempt and a Retry-After far past the cap."""
    transport, _ = build_transport([rate_limited("10000"), 200])
    sleep, delays = recording_sleep()

    asyncio.run(call_gemini("prompt", SCHEMA, sleep=sleep, transport=transport))

    assert delays
    assert max(delays) <= MAX_RETRY_DELAY_SECONDS


def test_jitter_scales_the_selected_delay() -> None:
    transport, _ = build_transport([429, 429, 429, 200])
    sleep, delays = recording_sleep()

    asyncio.run(
        call_gemini(
            "prompt",
            SCHEMA,
            sleep=sleep,
            transport=transport,
            jitter=fixed_jitter(1.2),
        )
    )

    assert delays == [1.2, 2.4, 4.8]


def test_jitter_is_called_once_per_retry_with_the_expected_bounds() -> None:
    transport, _ = build_transport([429, 429, 200])
    sleep, delays = recording_sleep()
    jitter, calls = recording_jitter(1.0)

    asyncio.run(
        call_gemini(
            "prompt",
            SCHEMA,
            sleep=sleep,
            transport=transport,
            jitter=jitter,
        )
    )

    assert delays == [1.0, 2.0]
    assert calls == [(JITTER_MIN, JITTER_MAX), (JITTER_MIN, JITTER_MAX)]
    assert (JITTER_MIN, JITTER_MAX) == (0.8, 1.2)


def test_concurrent_tickets_do_not_retry_in_lockstep() -> None:
    """Two tickets sharing one jitter source still get different delays."""
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    jitter = iter([0.8, 1.2])

    def alternating(low: float, high: float) -> float:
        return next(jitter)

    async def call() -> None:
        # A transport per call: a shared one would share its response
        # sequence, so the second ticket would see a 200 and never retry.
        transport, _ = build_transport([rate_limited(), 200])

        await call_gemini(
            "prompt",
            SCHEMA,
            sleep=sleep,
            transport=transport,
            jitter=alternating,
        )

    async def main() -> None:
        await asyncio.gather(call(), call())

    asyncio.run(main())

    assert sorted(delays) == [0.8, 1.2]


def test_retry_after_is_ignored_after_the_final_attempt() -> None:
    transport, requests = build_transport([rate_limited("5")])
    sleep, delays = recording_sleep()

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        asyncio.run(
            call_gemini(
                "prompt",
                SCHEMA,
                sleep=sleep,
                transport=transport,
                jitter=no_jitter,
            )
        )

    assert len(requests) == MAX_RETRIES + 1 == 4
    # Three sleeps, not four: Retry-After on the last 429 buys no extra wait.
    # Each is bounded by the backoff curve (1s, 2s, 4s).
    assert delays == [1.0, 2.0, 4.0]
    assert excinfo.value.response.status_code == 429


def test_latency_includes_retry_after_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    monkeypatch.setattr(time, "perf_counter", clock.perf_counter)

    transport, _ = build_transport([rate_limited("0.5"), rate_limited("1.5"), 200])
    sleep, delays = recording_sleep(clock)

    _, latency_ms = asyncio.run(
        call_gemini(
            "prompt",
            SCHEMA,
            sleep=sleep,
            transport=transport,
            jitter=no_jitter,
        )
    )

    assert delays == [0.5, 1.5]
    assert latency_ms == 2000


def test_retry_delay_never_exceeds_backoff() -> None:
    long_header = httpx.Response(
        429, headers={"Retry-After": "12"}, json=OK_BODY
    )
    short_header = httpx.Response(
        429, headers={"Retry-After": "0.5"}, json=OK_BODY
    )
    without_header = httpx.Response(429, json=OK_BODY)

    # A Retry-After longer than the curve is clamped to it.
    assert _retry_delay_seconds(long_header, 0, no_jitter) == 1.0
    # A shorter one is honoured.
    assert _retry_delay_seconds(short_header, 0, no_jitter) == 0.5
    # Attempt 0 would be 1s from the curve alone.
    assert _retry_delay_seconds(without_header, 0, no_jitter) == 1.0
    assert _retry_delay_seconds(without_header, 2, no_jitter) == 4.0


def test_only_429_is_retryable() -> None:
    request = httpx.Request("POST", gemini.GEMINI_URL)

    assert _should_retry(httpx.Response(429, request=request)) is True

    for status_code in (400, 401, 403, 404, 408, 500, 502, 503):
        response = httpx.Response(status_code, request=request)

        assert _should_retry(response) is False


def test_missing_api_key_raises_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gemini, "GEMINI_API_KEY", None)

    transport, requests = build_transport([200])
    sleep, delays = recording_sleep()

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        asyncio.run(
            call_gemini("prompt", SCHEMA, sleep=sleep, transport=transport)
        )

    assert requests == []
    assert delays == []


def test_network_guard_blocks_outbound_connections() -> None:
    """Guards the guard.

    Without this, the socket fixture could silently stop applying and the
    other tests would stop proving anything about real network access.
    """
    outbound = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    with pytest.raises(AssertionError, match="real network connection"):
        outbound.connect(("93.184.216.34", 80))
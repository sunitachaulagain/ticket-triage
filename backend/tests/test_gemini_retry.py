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
    MAX_RETRIES,
    _backoff_seconds,
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

    A ``BaseException`` in the list is raised instead of returned, which is
    how timeouts, transport failures and cancellation are simulated.
    """
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)

        item = responses[min(len(requests) - 1, len(responses) - 1)]

        if isinstance(item, BaseException):
            raise item

        return httpx.Response(item, json=OK_BODY)

    return httpx.MockTransport(handler), requests


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
        call_gemini("prompt", SCHEMA, sleep=sleep, transport=transport)
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
            call_gemini("prompt", SCHEMA, sleep=sleep, transport=transport)
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
        call_gemini("prompt", SCHEMA, sleep=sleep, transport=transport)
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
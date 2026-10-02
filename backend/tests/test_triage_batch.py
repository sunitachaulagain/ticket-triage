"""Batch triage service tests. None of these contact the Gemini API.

The autouse ``no_gemini_calls`` fixture replaces the Gemini entry point with
a function that raises, so an accidental real call fails loudly instead of
silently spending API quota.

pytest-asyncio is not a dependency here, so each test drives its own event
loop with ``asyncio.run``.
"""

import asyncio

import pytest

from backend.app.dataset import SupportTicket
from backend.app.schemas import (
    Category,
    Sentiment,
    TriageResult,
    TriageStatus,
    Urgency,
)
from backend.app.services import gemini
from backend.app.services import triage as triage_service


@pytest.fixture(autouse=True)
def no_gemini_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args, **kwargs):
        raise AssertionError("A test attempted to call the Gemini API")

    monkeypatch.setattr(triage_service, "call_gemini", blocked)
    monkeypatch.setattr(gemini, "call_gemini", blocked)


def make_result(ticket_id: int, status: TriageStatus = TriageStatus.OK) -> TriageResult:
    succeeded = status is TriageStatus.OK

    return TriageResult(
        ticket_id=ticket_id,
        urgency=Urgency.HIGH if succeeded else None,
        category=Category.TECHNICAL if succeeded else None,
        sentiment=Sentiment.ANGRY if succeeded else None,
        suggested_reply="We are on it." if succeeded else None,
        confidence=0.9 if succeeded else None,
        rationale="stub result" if succeeded else None,
        needs_human_review=not succeeded,
        tags=["stub"] if succeeded else [],
        model="stub-model",
        prompt_version="v1",
        latency_ms=5,
        status=status,
        error=None if succeeded else "RuntimeError: simulated failure",
    )


def test_batch_returns_all_20_tickets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_triage_ticket(ticket):
        return make_result(ticket.id)

    monkeypatch.setattr(triage_service, "triage_ticket", fake_triage_ticket)

    results = asyncio.run(triage_service.triage_batch())

    assert len(results) == 20
    assert [r.ticket_id for r in results] == list(range(1, 21))
    assert all(r.status is TriageStatus.OK for r in results)


def test_batch_preserves_dataset_order_when_completion_is_reversed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed: list[int] = []

    async def fake_triage_ticket(ticket):
        # Higher id sleeps less, so within each wave the highest id finishes
        # first and completion order diverges from dataset order.
        await asyncio.sleep((21 - ticket.id) * 0.001)

        completed.append(ticket.id)

        return make_result(ticket.id)

    monkeypatch.setattr(triage_service, "triage_ticket", fake_triage_ticket)

    results = asyncio.run(triage_service.triage_batch())

    assert [r.ticket_id for r in results] == list(range(1, 21))
    assert len(completed) == 20

    # The semaphore caps in-flight work at MAX_CONCURRENCY, so tickets
    # complete in reversed waves rather than fully reversed. If the batch ran
    # sequentially, this test would not be testing ordering at all.
    assert completed != list(range(1, 21)), (
        "completion order matched dataset order, so ordering was not tested"
    )
    assert completed != sorted(completed), "expected out-of-order completion"
    assert completed.index(triage_service.MAX_CONCURRENCY) < completed.index(1), (
        "expected the highest id in the first wave to finish first"
    )


def test_one_failure_does_not_abort_the_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_triage_ticket(ticket):
        if ticket.id == 7:
            raise RuntimeError("simulated Gemini failure")

        return make_result(ticket.id)

    monkeypatch.setattr(triage_service, "triage_ticket", fake_triage_ticket)

    results = asyncio.run(triage_service.triage_batch())

    assert len(results) == 20

    failed = [r for r in results if r.status is TriageStatus.FAILED]

    assert len(failed) == 1

    failure = failed[0]

    assert failure.ticket_id == 7
    assert failure.urgency is None
    assert failure.category is None
    assert failure.sentiment is None
    assert failure.suggested_reply is None
    assert failure.confidence is None
    assert failure.rationale is None
    assert failure.tags == []
    assert failure.needs_human_review is True
    assert "RuntimeError" in failure.error
    assert failure.latency_ms >= 0

    assert sum(1 for r in results if r.status is TriageStatus.OK) == 19
    assert [r.ticket_id for r in results] == list(range(1, 21))


def test_concurrency_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    in_flight = 0
    peak = 0

    async def fake_triage_ticket(ticket):
        nonlocal in_flight, peak

        in_flight += 1
        peak = max(peak, in_flight)

        try:
            # Yield control so every admitted coroutine overlaps.
            await asyncio.sleep(0.01)

            return make_result(ticket.id)
        finally:
            in_flight -= 1

    monkeypatch.setattr(triage_service, "triage_ticket", fake_triage_ticket)

    results = asyncio.run(triage_service.triage_batch())

    assert len(results) == 20
    assert peak == triage_service.MAX_CONCURRENCY
    assert peak > 1, "batch ran sequentially instead of concurrently"


def test_cancellation_propagates_instead_of_becoming_a_failed_ticket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_triage_ticket(ticket):
        if ticket.id == 5:
            raise asyncio.CancelledError()

        await asyncio.sleep(0.001)

        return make_result(ticket.id)

    monkeypatch.setattr(triage_service, "triage_ticket", fake_triage_ticket)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(triage_service.triage_batch())


def test_dataset_load_failure_is_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_load() -> list[SupportTicket]:
        raise FileNotFoundError("Dataset not found")

    monkeypatch.setattr(triage_service, "load_tickets", broken_load)

    with pytest.raises(FileNotFoundError):
        asyncio.run(triage_service.triage_batch())

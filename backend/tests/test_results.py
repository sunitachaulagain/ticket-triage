"""Statistics service tests. None of these contact the Gemini API.

The autouse ``no_gemini_calls`` fixture replaces the Gemini entry point with
a function that raises, so an accidental real call fails loudly instead of
silently spending API quota.
"""

import pytest

from backend.app.schemas import (
    Category,
    Sentiment,
    TriageResult,
    TriageStatus,
    Urgency,
)
from backend.app.services import gemini
from backend.app.services import triage as triage_service
from backend.app.services.results import calculate_statistics


@pytest.fixture(autouse=True)
def no_gemini_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args, **kwargs):
        raise AssertionError("A test attempted to call the Gemini API")

    monkeypatch.setattr(triage_service, "call_gemini", blocked)
    monkeypatch.setattr(gemini, "call_gemini", blocked)


def make_result(
    ticket_id: int,
    *,
    status: TriageStatus = TriageStatus.OK,
    urgency: Urgency | None = Urgency.HIGH,
    category: Category | None = Category.TECHNICAL,
    sentiment: Sentiment | None = Sentiment.ANGRY,
    confidence: float | None = 0.9,
    needs_human_review: bool = False,
    latency_ms: int = 100,
) -> TriageResult:
    return TriageResult(
        ticket_id=ticket_id,
        urgency=urgency,
        category=category,
        sentiment=sentiment,
        suggested_reply="We are on it." if status is TriageStatus.OK else None,
        confidence=confidence,
        rationale="stub result",
        needs_human_review=needs_human_review,
        tags=["stub"] if status is TriageStatus.OK else [],
        model="stub-model",
        prompt_version="v1",
        latency_ms=latency_ms,
        status=status,
        error=None if status is TriageStatus.OK else "RuntimeError: boom",
    )


def make_failed_result(ticket_id: int, latency_ms: int = 50) -> TriageResult:
    """A failed result carries no classification and no confidence."""
    return make_result(
        ticket_id,
        status=TriageStatus.FAILED,
        urgency=None,
        category=None,
        sentiment=None,
        confidence=None,
        needs_human_review=True,
        latency_ms=latency_ms,
    )


def test_counts_a_normal_successful_batch() -> None:
    results = [
        make_result(1, urgency=Urgency.CRITICAL, confidence=1.0),
        make_result(2, urgency=Urgency.LOW, confidence=0.8),
        make_result(3, urgency=Urgency.LOW, confidence=0.6),
    ]

    stats = calculate_statistics(results)

    assert stats.total_tickets == 3
    assert stats.successful == 3
    assert stats.failed == 0
    assert stats.needs_human_review == 0
    assert stats.urgency_breakdown == {
        Urgency.CRITICAL: 1,
        Urgency.HIGH: 0,
        Urgency.MEDIUM: 0,
        Urgency.LOW: 2,
    }
    assert stats.category_breakdown[Category.TECHNICAL] == 3
    assert stats.sentiment_breakdown[Sentiment.ANGRY] == 3


def test_counts_failed_results() -> None:
    results = [
        make_result(1),
        make_failed_result(2),
        make_failed_result(3),
    ]

    stats = calculate_statistics(results)

    assert stats.total_tickets == 3
    assert stats.successful == 1
    assert stats.failed == 2

    # A failure still counts toward the total and toward human review,
    # because needs_human_review defaults to True on a failed result.
    assert stats.needs_human_review == 2


def test_counts_needs_human_review() -> None:
    results = [
        make_result(1, needs_human_review=False),
        make_result(2, needs_human_review=True),
        make_result(3, needs_human_review=True),
        make_result(4, needs_human_review=False),
    ]

    stats = calculate_statistics(results)

    assert stats.needs_human_review == 2
    # Human review is counted independently of success.
    assert stats.successful == 4


def test_average_confidence_ignores_none_values() -> None:
    results = [
        make_result(1, confidence=1.0),
        make_result(2, confidence=0.5),
        make_failed_result(3, latency_ms=9000),
    ]

    stats = calculate_statistics(results)

    # (1.0 + 0.5) / 2. The failed result contributes no confidence.
    assert stats.average_confidence == 0.75


def test_average_confidence_value_is_rounded_to_four_places() -> None:
    results = [
        make_result(1, confidence=0.1),
        make_result(2, confidence=0.2),
        make_result(3, confidence=0.3),
    ]

    stats = calculate_statistics(results)

    assert stats.average_confidence == 0.2


def test_average_latency_includes_failed_results() -> None:
    results = [
        make_result(1, latency_ms=100),
        make_result(2, latency_ms=200),
        make_failed_result(3, latency_ms=900),
    ]

    stats = calculate_statistics(results)

    assert (100 + 200 + 900) / 3 == 400.0
    assert stats.average_latency_ms == 400.0


def test_breakdowns_ignore_none_classifications() -> None:
    results = [
        make_result(1, urgency=Urgency.HIGH),
        make_failed_result(2),
    ]

    stats = calculate_statistics(results)

    # Every allowed key is present. The failed ticket leaves no classification,
    # so its key counts are zero rather than absent.
    assert stats.urgency_breakdown == {
        Urgency.CRITICAL: 0,
        Urgency.HIGH: 1,
        Urgency.MEDIUM: 0,
        Urgency.LOW: 0,
    }
    assert stats.category_breakdown == {
        Category.BILLING: 0,
        Category.TECHNICAL: 1,
        Category.ACCOUNT: 0,
        Category.FEEDBACK: 0,
        Category.OTHER: 0,
    }
    assert stats.sentiment_breakdown == {
        Sentiment.ANGRY: 1,
        Sentiment.FRUSTRATED: 0,
        Sentiment.NEUTRAL: 0,
        Sentiment.HAPPY: 0,
    }


def test_breakdowns_use_enum_definition_order() -> None:
    stats = calculate_statistics([make_result(1)])

    assert list(stats.urgency_breakdown) == list(Urgency)
    assert list(stats.category_breakdown) == list(Category)
    assert list(stats.sentiment_breakdown) == list(Sentiment)


def test_empty_list_yields_zeroed_counts_and_none_averages() -> None:
    stats = calculate_statistics([])

    assert stats.total_tickets == 0
    assert stats.successful == 0
    assert stats.failed == 0
    assert stats.needs_human_review == 0
    assert stats.average_confidence is None
    assert stats.average_latency_ms is None
    assert stats.urgency_breakdown == dict.fromkeys(Urgency, 0)
    assert stats.category_breakdown == dict.fromkeys(Category, 0)
    assert stats.sentiment_breakdown == dict.fromkeys(Sentiment, 0)


def test_statistics_serialize_with_enum_keys_as_strings() -> None:
    stats = calculate_statistics([make_result(1)])

    payload = stats.model_dump(mode="json")

    assert payload["urgency_breakdown"] == {
        "Critical": 0,
        "High": 1,
        "Medium": 0,
        "Low": 0,
    }
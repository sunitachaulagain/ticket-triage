"""Aggregate statistics over a list of triage results.

Pure calculation over objects that already exist: no Gemini call, no network
access, and no dependency on how the results were produced.
"""

from collections import Counter
from collections.abc import Iterable

from backend.app.schemas import (
    Category,
    Sentiment,
    TriageResult,
    TriageStatistics,
    TriageStatus,
    Urgency,
)

AVERAGE_CONFIDENCE_PRECISION = 4
AVERAGE_LATENCY_PRECISION = 2


def _average(values: list[float]) -> float | None:
    """Mean of the values, or None when there is nothing to average."""
    if not values:
        return None

    return sum(values) / len(values)


def _breakdown(
    values: Iterable[Urgency | Category | Sentiment | None],
    allowed: type[Urgency] | type[Category] | type[Sentiment],
) -> dict:
    """Count non-None values, zero-filled in enum definition order.

    Zero-filling from the enum keeps the allowed values in one place and
    gives callers a fixed key set, so a missing classification shows up as an
    explicit zero rather than an absent key.
    """
    counts = Counter(value for value in values if value is not None)

    return {item: counts[item] for item in allowed}


def calculate_statistics(
    results: list[TriageResult],
) -> TriageStatistics:
    """Summarise a batch of results.

    Averages ignore None values and are reported as None for an empty list
    rather than dividing by zero. Latency is averaged across every result,
    including failures, because latency_ms is always populated.
    """
    confidence = _average(
        [r.confidence for r in results if r.confidence is not None]
    )

    latency = _average([r.latency_ms for r in results])

    return TriageStatistics(
        total_tickets=len(results),
        successful=sum(1 for r in results if r.status is TriageStatus.OK),
        failed=sum(1 for r in results if r.status is TriageStatus.FAILED),
        needs_human_review=sum(1 for r in results if r.needs_human_review),
        average_confidence=(
            None
            if confidence is None
            else round(confidence, AVERAGE_CONFIDENCE_PRECISION)
        ),
        average_latency_ms=(
            None
            if latency is None
            else round(latency, AVERAGE_LATENCY_PRECISION)
        ),
        urgency_breakdown=_breakdown(
            (r.urgency for r in results),
            Urgency,
        ),
        category_breakdown=_breakdown(
            (r.category for r in results),
            Category,
        ),
        sentiment_breakdown=_breakdown(
            (r.sentiment for r in results),
            Sentiment,
        ),
    )
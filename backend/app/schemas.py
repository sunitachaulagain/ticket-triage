from enum import Enum

from pydantic import BaseModel, Field


class Urgency(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


URGENCY_RANK = {
    Urgency.LOW: 1,
    Urgency.MEDIUM: 2,
    Urgency.HIGH: 3,
    Urgency.CRITICAL: 4,
}

class Category(str, Enum):
    BILLING = "Billing"
    TECHNICAL = "Technical"
    ACCOUNT = "Account"
    FEEDBACK = "Feedback"
    OTHER = "Other"


class Sentiment(str, Enum):
    ANGRY = "Angry"
    FRUSTRATED = "Frustrated"
    NEUTRAL = "Neutral"
    HAPPY = "Happy"


class TriageStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"
    FALLBACK = "fallback"


class TriageRequest(BaseModel):
    ticket_id: int


class TriageResult(BaseModel):
    ticket_id: int
    # Nullable so a failed ticket can be reported without inventing a
    # classification. Services guarantee these are populated when status is OK.
    urgency: Urgency | None = None
    category: Category | None = None
    sentiment: Sentiment | None = None
    suggested_reply: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    rationale: str | None = Field(default=None, max_length=240)
    needs_human_review: bool = True
    tags: list[str] = Field(default_factory=list)

    model: str
    prompt_version: str
    latency_ms: int = Field(ge=0)
    status: TriageStatus
    error: str | None = None


class TriageStatistics(BaseModel):
    """Aggregate view of a list of triage results.

    Every breakdown carries all of its allowed keys, zero-filled in enum
    definition order. A zero means no result carried that classification,
    which is different from a classification that was never produced at all.
    """

    total_tickets: int
    successful: int
    failed: int
    needs_human_review: int
    average_confidence: float | None
    average_latency_ms: float | None
    urgency_breakdown: dict[Urgency, int]
    category_breakdown: dict[Category, int]
    sentiment_breakdown: dict[Sentiment, int]


class BatchTriageResponse(BaseModel):
    """Response for the batch endpoint: an aggregate summary plus every result.

    The results are passed through unchanged and in the order triage_batch
    returned them, so one payload serves both the summary panel and the table.
    """

    summary: TriageStatistics
    results: list[TriageResult]
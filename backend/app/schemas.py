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


class TriageResult(BaseModel):
    ticket_id: int
    urgency: Urgency
    category: Category
    sentiment: Sentiment
    suggested_reply: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=240)
    needs_human_review: bool
    tags: list[str] = Field(default_factory=list)

    model: str
    prompt_version: str
    latency_ms: int = Field(ge=0)
    status: TriageStatus
    error: str | None = None
from pathlib import Path
import json

from pydantic import BaseModel, ConfigDict, field_validator


DATASET_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "support_tickets.json"
)


class SupportTicket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    message: str

    @field_validator("message")
    @classmethod
    def message_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Ticket message cannot be empty")
        return value


def load_tickets() -> list[SupportTicket]:
    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found: {DATASET_PATH}"
        )

    with DATASET_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("Dataset must contain a JSON array")

    tickets = [SupportTicket.model_validate(item) for item in data]

    if len(tickets) != 20:
        raise ValueError(
            f"Expected exactly 20 tickets, found {len(tickets)}"
        )

    ticket_ids = [ticket.id for ticket in tickets]

    if len(ticket_ids) != len(set(ticket_ids)):
        raise ValueError("Duplicate ticket IDs found")

    return tickets
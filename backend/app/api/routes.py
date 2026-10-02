"""HTTP routes for the triage application.

Route bodies stay thin: they look tickets up and delegate to the existing
services. The triage service module is imported as a module (not by name)
so tests can substitute it without touching this file.
"""

from fastapi import APIRouter, HTTPException

from backend.app.dataset import SupportTicket, load_tickets
from backend.app.schemas import TriageRequest, TriageResult
from backend.app.services import triage as triage_service


router = APIRouter(prefix="/api", tags=["triage"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/tickets", response_model=list[SupportTicket])
def list_tickets() -> list[SupportTicket]:
    return load_tickets()


@router.post("/triage", response_model=TriageResult)
async def triage_ticket(payload: TriageRequest) -> TriageResult:
    tickets = {ticket.id: ticket for ticket in load_tickets()}

    ticket = tickets.get(payload.ticket_id)

    if ticket is None:
        raise HTTPException(
            status_code=404,
            detail=f"Ticket {payload.ticket_id} not found",
        )

    # Errors are intentionally not caught here so genuine server-side
    # failures surface instead of being disguised as a failed triage.
    return await triage_service.triage_ticket(ticket)


@router.post("/triage/batch", response_model=list[TriageResult])
async def triage_all() -> list[TriageResult]:
    return await triage_service.triage_batch()
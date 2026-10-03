"""API tests. None of these contact the Gemini API.

The autouse ``no_gemini_calls`` fixture replaces the Gemini entry point with
a function that raises, so any accidental real call fails loudly instead of
silently spending API quota.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.config import GROQ_API_KEY
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


ALLOWED_ORIGIN = "http://localhost:5173"


@pytest.fixture(autouse=True)
def no_gemini_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args, **kwargs):
        raise AssertionError("A test attempted to call the Gemini API")

    monkeypatch.setattr(triage_service, "call_gemini", blocked)
    monkeypatch.setattr(gemini, "call_gemini", blocked)


def make_result(
    ticket_id: int,
    status: TriageStatus = TriageStatus.OK,
) -> TriageResult:
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
        latency_ms=12,
        status=status,
        error=None if succeeded else "RuntimeError: simulated failure",
    )


def test_health_returns_200(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_still_works(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "running" in response.json()["message"]


def test_tickets_returns_exactly_20(client: TestClient) -> None:
    response = client.get("/api/tickets")

    assert response.status_code == 200

    tickets = response.json()

    assert len(tickets) == 20
    assert [ticket["id"] for ticket in tickets] == list(range(1, 21))
    assert all(ticket["message"].strip() for ticket in tickets)


def test_triage_unknown_id_returns_404(client: TestClient) -> None:
    response = client.post("/api/triage", json={"ticket_id": 9999})

    assert response.status_code == 404
    assert "9999" in response.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"id": 1},
        {"ticket_id": None},
        {"ticket_id": "not-a-number"},
    ],
)
def test_triage_invalid_body_returns_422(
    client: TestClient,
    payload: dict,
) -> None:
    response = client.post("/api/triage", json=payload)

    assert response.status_code == 422


def test_triage_single_ticket_returns_result(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[int] = []

    async def fake_triage_ticket(ticket):
        captured.append(ticket.id)
        return make_result(ticket.id)

    monkeypatch.setattr(triage_service, "triage_ticket", fake_triage_ticket)

    response = client.post("/api/triage", json={"ticket_id": 3})

    assert response.status_code == 200

    body = response.json()

    assert captured == [3]
    assert body["ticket_id"] == 3
    assert body["status"] == "ok"
    assert body["urgency"] == "High"


def test_batch_returns_service_results(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    async def fake_triage_batch():
        calls.append(1)
        return [make_result(1), make_result(2, TriageStatus.FAILED)]

    monkeypatch.setattr(triage_service, "triage_batch", fake_triage_batch)

    response = client.post("/api/triage/batch")

    assert response.status_code == 200

    body = response.json()

    assert len(calls) == 1
    assert body["summary"]["total_tickets"] == 2
    assert body["summary"]["successful"] == 1
    assert body["summary"]["failed"] == 1
    # The failed stub is flagged for review; the successful one is not.
    assert body["summary"]["needs_human_review"] == 1
    assert len(body["results"]) == 2
    assert body["results"][0]["status"] == "ok"
    assert body["results"][1]["status"] == "failed"


def test_batch_preserves_failed_ticket_fields(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_triage_batch():
        return [make_result(7, TriageStatus.FAILED)]

    monkeypatch.setattr(triage_service, "triage_batch", fake_triage_batch)

    body = client.post("/api/triage/batch").json()

    failed = body["results"][0]

    assert failed["status"] == "failed"
    assert failed["ticket_id"] == 7
    assert failed["error"] is not None
    assert failed["urgency"] is None
    assert failed["category"] is None
    assert failed["suggested_reply"] is None
    assert failed["tags"] == []


def test_batch_summary_matches_calculate_statistics(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stubs = [make_result(1), make_result(2, TriageStatus.FAILED)]

    async def fake_triage_batch():
        return stubs

    monkeypatch.setattr(triage_service, "triage_batch", fake_triage_batch)

    body = client.post("/api/triage/batch").json()

    # The route must reuse the service rather than reimplement the maths, so
    # the payload has to be identical to what the service produces.
    assert body["summary"] == calculate_statistics(stubs).model_dump(mode="json")


def test_batch_response_preserves_result_order(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stubs = [make_result(3), make_result(1), make_result(2)]

    async def fake_triage_batch():
        return stubs

    monkeypatch.setattr(triage_service, "triage_batch", fake_triage_batch)

    body = client.post("/api/triage/batch").json()

    # Pass-through order, not re-sorted by ticket id.
    assert [r["ticket_id"] for r in body["results"]] == [3, 1, 2]


def test_batch_results_are_unchanged(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stubs = [make_result(1), make_result(2, TriageStatus.FAILED)]

    async def fake_triage_batch():
        return stubs

    monkeypatch.setattr(triage_service, "triage_batch", fake_triage_batch)

    body = client.post("/api/triage/batch").json()

    # Every field of every result survives the response model untouched.
    assert body["results"] == [
        stub.model_dump(mode="json") for stub in stubs
    ]


def test_batch_propagates_unexpected_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exploding_batch():
        raise RuntimeError("dataset unavailable")

    monkeypatch.setattr(triage_service, "triage_batch", exploding_batch)

    with pytest.raises(RuntimeError):
        client.post("/api/triage/batch")


def test_cors_preflight_allowed_origin(client: TestClient) -> None:
    response = client.options(
        "/api/health",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_cors_simple_request_sets_header(client: TestClient) -> None:
    response = client.get("/api/health", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_cors_disallowed_origin_gets_no_header(client: TestClient) -> None:
    response = client.get(
        "/api/health",
        headers={"Origin": "https://evil.example.com"},
    )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_responses_never_expose_api_key(client: TestClient) -> None:
    if not GROQ_API_KEY:
        pytest.skip("GROQ_API_KEY is not configured")

    bodies = [
        client.get("/").text,
        client.get("/api/health").text,
        client.get("/api/tickets").text,
        client.get("/openapi.json").text,
    ]

    for body in bodies:
        assert GROQ_API_KEY not in body
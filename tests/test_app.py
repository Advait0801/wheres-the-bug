import json
from pathlib import Path

from fastapi.testclient import TestClient

from faultloc.app import create_app


ROOT = Path(__file__).resolve().parents[1]
CLIENT = TestClient(create_app(ROOT))


def test_dashboard_and_health() -> None:
    response = CLIENT.get("/")
    assert response.status_code == 200
    assert "Fault localization" in response.text
    assert CLIENT.get("/healthz").json() == {"status": "ok"}


def test_results_api_serves_cached_aggregates_only() -> None:
    response = CLIENT.get("/api/results")
    assert response.status_code == 200
    payload = response.json()
    assert payload["split"] == "dev"
    assert payload["case_count"] == 187
    assert payload["candidate_count"] == 155
    assert "a6_router" in payload["localizers"]
    assert "cases" not in payload["localizers"]["a6_router"]


def test_case_explorer_api() -> None:
    summaries = CLIENT.get("/api/cases").json()
    assert len(summaries) == 187
    assert {case["split"] for case in summaries} == {"dev"}

    detail = CLIENT.get(f"/api/cases/{summaries[0]['case_id']}").json()
    assert detail["diff"]
    assert detail["traceback_text"]
    assert "target/" in detail["traceback_text"]
    assert "/Users/" not in json.dumps(detail)
    assert detail["function_qualified_name"]
    expected_localizers = set(CLIENT.get("/api/results").json()["localizers"])
    assert set(detail["localizer_results"]) == expected_localizers


def test_unknown_case_is_404() -> None:
    response = CLIENT.get("/api/cases/not-a-case")
    assert response.status_code == 404

from fastapi.testclient import TestClient

from Backend.app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_preview_endpoint_returns_quality_evidence(pune_request: dict) -> None:
    response = client.post("/api/v1/ingestions/preview", json=pune_request)
    assert response.status_code == 200
    body = response.json()
    assert body["quality"]["invalid_feature_count"] == 0
    assert body["control_network"]["outlier_ids"] == ["cp-typo"]
    assert body["projection"]["target_proj"].startswith("+proj=tmerc")


def test_api_rejects_too_few_controls(pune_request: dict) -> None:
    pune_request["control_points"] = pune_request["control_points"][:3]
    response = client.post("/api/v1/ingestions/preview", json=pune_request)
    assert response.status_code == 422
    assert "at least four control points" in response.text

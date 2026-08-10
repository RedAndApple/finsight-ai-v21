from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app


def test_health_and_demo_use_universal_pipeline():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        response = client.post("/api/documents/demo")
        assert response.status_code == 201
        record = response.json()
        assert record["status"] in {"queued", "processing"}

        source = client.get(f"/api/documents/{record['id']}/file")
        assert source.status_code == 200
        assert source.headers["content-type"].startswith("application/pdf")

def test_frontend_is_served():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "FinSight AI" in response.text

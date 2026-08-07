from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app


def test_rsbu_demo_endpoint():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        response = client.post("/api/documents/demo")
        assert response.status_code == 201
        record = response.json()
        assert record["status"] == "completed"

        result_response = client.get(f"/api/documents/{record['id']}/result")
        assert result_response.status_code == 200
        result = result_response.json()
        assert result["metadata"]["document_type"] == "ras_financial_statements"
        assert result["metadata"]["reporting_year"] == 2025
        assert result["metadata"]["demo_preverified"] is True
        assert result["financial_metrics"]["revenue"]["values"]["2025"] == 3453224535
        assert result["financial_metrics"]["net_profit"]["values"]["2025"] == 403734771
        assert len(result["ratios"]) >= 24
        assert result["analysis"]["mode"] == "verified_rsbu_demo_fallback"

        source = client.get(f"/api/documents/{record['id']}/file")
        assert source.status_code == 200
        assert source.headers["content-type"].startswith("application/pdf")

        csv_export = client.get(f"/api/documents/{record['id']}/export.csv")
        assert csv_export.status_code == 200
        assert "Выручка" in csv_export.text

        json_export = client.get(f"/api/documents/{record['id']}/export.json")
        assert json_export.status_code == 200


def test_uploading_bundled_rsbu_pdf_uses_verified_demo():
    sample = Path(__file__).resolve().parents[1] / "samples" / "lukoil_rsbu_2025.pdf"
    with TestClient(app) as client, sample.open("rb") as stream:
        response = client.post(
            "/api/documents/upload",
            files={"file": ("БФО ПАО ЛУКОЙЛ РСБУ 2025.pdf", stream, "application/pdf")},
        )
        assert response.status_code == 202
        record = response.json()
        assert record["status"] == "completed"
        assert record["stage"] == "Проверенное демо РСБУ готово"
        result = client.get(f"/api/documents/{record['id']}/result").json()
        assert result["metadata"]["demo_preverified"] is True


def test_frontend_is_served():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "FinSight AI" in response.text

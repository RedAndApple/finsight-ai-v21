from app.canonical import canonicalize_metrics
from app.validation import validate_model
from app.trends import calculate_trends


def _metric(key, values, confidence=.95, source="spreadsheet_table"):
    return {"key": key, "name": key, "unit": "тыс. руб.", "values": values,
            "source_pages": [2], "source_type": source, "confidence": confidence}


def test_balanced_model_passes_and_keeps_provenance():
    raw = {
        "noncurrent_assets": _metric("noncurrent_assets", {"2024": 60, "2025": 70}),
        "current_assets": _metric("current_assets", {"2024": 40, "2025": 50}),
        "assets": _metric("assets", {"2024": 100, "2025": 120}),
        "equity": _metric("equity", {"2024": 50, "2025": 60}),
        "longterm_liabilities": _metric("longterm_liabilities", {"2024": 20, "2025": 20}),
        "current_liabilities": _metric("current_liabilities", {"2024": 30, "2025": 40}),
    }
    model = canonicalize_metrics(raw)
    report = validate_model(model)
    assert report["status"] == "passed"
    assert report["valid_metric_count"] == 6
    assert model["assets"]["provenance"][0]["page"] == 2
    assert calculate_trends(report["valid_metrics"])[0]["to_year"] == "2025"


def test_low_confidence_ocr_is_quarantined():
    model = canonicalize_metrics({"revenue": _metric("revenue", {"2025": 999}, .40, "ras_coordinate_ocr")})
    report = validate_model(model)
    assert report["invalid_metric_count"] == 1
    assert "revenue" not in report["valid_metrics"]


def test_unbalanced_model_reports_failed_identity():
    raw = {"noncurrent_assets": _metric("noncurrent_assets", {"2025": 60}),
           "current_assets": _metric("current_assets", {"2025": 40}),
           "assets": _metric("assets", {"2025": 150})}
    report = validate_model(canonicalize_metrics(raw))
    assert report["status"] == "failed"
    assert report["issues"][0]["check"] == "assets_equals_sections"

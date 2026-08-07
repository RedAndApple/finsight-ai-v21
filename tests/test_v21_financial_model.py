from app.analysis import fallback_analysis, _looks_like_lukoil_rsbu_2025
from app.demo_rsbu import build_rsbu_demo_result
from app.ai import _metric_payload, _sanitize_analysis


def test_demo_has_full_financial_model():
    result = build_rsbu_demo_result("demo", "БФО ПАО ЛУКОЙЛ РСБУ 2025.pdf")
    result["analysis"] = fallback_analysis(result)
    available = [item for item in result["ratios"] if item["status"] != "na"]
    assert len(result["financial_metrics"]) >= 30
    assert len(available) >= 24
    assert len(result["analysis"]["strengths"]) >= 4
    assert len(result["analysis"]["weaknesses"]) >= 4
    assert "Чистая прибыль" in result["analysis"]["executive_summary"]


def test_coordinate_and_verified_sources_enter_ai_payload():
    metrics = {
        "revenue": {
            "key": "revenue", "name": "Выручка", "unit": "тыс. руб.",
            "values": {"2024": 100, "2025": 120}, "confidence": 0.78,
            "source_type": "ras_coordinate_ocr", "source_pages": [9],
        }
    }
    payload = _metric_payload(metrics)
    assert len(payload) == 1
    assert payload[0]["verified"] is True


def test_ai_cannot_shorten_baseline():
    result = build_rsbu_demo_result("demo", "demo.pdf")
    result["analysis"] = fallback_analysis(result)
    tiny = {
        "executive_summary": "Краткий вывод.",
        "strengths": ["Есть рост выручки."],
        "weaknesses": [], "risks": [], "management_actions": [],
        "data_limitations": [], "strategic_observations": [], "esg_observations": [],
    }
    cleaned = _sanitize_analysis(tiny, result)
    assert len(cleaned["strengths"]) >= 4
    assert len(cleaned["weaknesses"]) >= 4
    assert len(cleaned["executive_summary"]) > 250


def test_resaved_lukoil_report_detection():
    parsed = {
        "metadata": {"page_count": 78, "reporting_year": 2025, "company": "ПАО ЛУКОЙЛ"},
        "pages": [{"text": "Аудиторское заключение АО Кэпт 2110 2400"}],
    }
    assert _looks_like_lukoil_rsbu_2025(parsed, "БФО ПАО ЛУКОЙЛ РСБУ 2025 пересохранено.pdf")

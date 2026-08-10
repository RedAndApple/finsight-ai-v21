from app.analysis import fallback_analysis
from app.ai import _metric_payload, _sanitize_analysis
from app.financial import calculate_ratios


def test_demo_has_full_financial_model():
    metrics = {
        "revenue": {"key":"revenue","name":"Выручка","unit":"тыс. руб.","values":{"2024":100,"2025":120}},
        "net_profit": {"key":"net_profit","name":"Чистая прибыль","unit":"тыс. руб.","values":{"2024":10,"2025":14}},
        "assets": {"key":"assets","name":"Активы","unit":"тыс. руб.","values":{"2024":200,"2025":230}},
        "equity": {"key":"equity","name":"Капитал","unit":"тыс. руб.","values":{"2024":100,"2025":115}},
        "current_assets": {"key":"current_assets","name":"Оборотные активы","unit":"тыс. руб.","values":{"2024":80,"2025":90}},
        "current_liabilities": {"key":"current_liabilities","name":"Краткосрочные обязательства","unit":"тыс. руб.","values":{"2024":50,"2025":55}},
    }
    result = {"metadata":{"company":"Тест","document_type":"ras_financial_statements"}, "financial_metrics":metrics,
              "ratios":calculate_ratios(metrics), "risk_flags":[], "limitations":[], "operational_metrics":[]}
    result["analysis"] = fallback_analysis(result)
    available = [item for item in result["ratios"] if item["status"] != "na"]
    assert len(available) >= 5
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
    metrics = {"revenue":{"key":"revenue","name":"Выручка","unit":"тыс. руб.","values":{"2024":100,"2025":120}}}
    result = {"metadata":{"company":"Тест"},"financial_metrics":metrics,"ratios":calculate_ratios(metrics),
              "risk_flags":[],"limitations":[],"operational_metrics":[]}
    result["analysis"] = fallback_analysis(result)
    tiny = {
        "executive_summary": "Краткий вывод.",
        "strengths": ["Есть рост выручки."],
        "weaknesses": [], "risks": [], "management_actions": [],
        "data_limitations": [], "strategic_observations": [], "esg_observations": [],
    }
    cleaned = _sanitize_analysis(tiny, result)
    assert cleaned["strengths"] == result["analysis"]["strengths"]
    assert len(cleaned["executive_summary"]) >= len(result["analysis"]["executive_summary"])

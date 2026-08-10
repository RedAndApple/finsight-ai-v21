from app.analysis import _company_from_filename, _is_ras_result, fallback_analysis
from app.financial import calculate_ratios


def test_ras_is_recognized_by_official_row_codes_and_filename():
    metrics = {
        f"metric_{index}": {"row_code": str(1100 + index), "values": {"2025": index + 1}}
        for index in range(8)
    }
    result = {"metadata": {"filename": "БФО ПАО ЛУКОЙЛ РСБУ 2025.pdf"}, "financial_metrics": metrics}
    assert _is_ras_result(result) is True
    assert _company_from_filename(result["metadata"]["filename"]) == "ПАО «ЛУКОЙЛ»"


def test_fallback_consolidates_related_ratios_into_professional_findings():
    metrics = {
        "revenue": {"name": "Выручка", "unit": "тыс. руб.", "values": {"2024": 1000, "2025": 900}, "row_code": "2110"},
        "gross_profit": {"name": "Валовая прибыль", "unit": "тыс. руб.", "values": {"2024": 300, "2025": 250}, "row_code": "2100"},
        "operating_profit": {"name": "Прибыль от продаж", "unit": "тыс. руб.", "values": {"2024": 200, "2025": 150}, "row_code": "2200"},
        "net_profit": {"name": "Чистая прибыль", "unit": "тыс. руб.", "values": {"2024": 100, "2025": 70}, "row_code": "2400"},
        "current_assets": {"values": {"2024": 500, "2025": 450}, "row_code": "1200"},
        "current_liabilities": {"values": {"2024": 300, "2025": 300}, "row_code": "1500"},
        "assets": {"values": {"2024": 1200, "2025": 1100}, "row_code": "1600"},
        "equity": {"values": {"2024": 700, "2025": 680}, "row_code": "1300"},
    }
    result = {
        "metadata": {"filename": "Отчетность РСБУ.pdf", "company": "АО «Тест»"},
        "financial_metrics": metrics, "ratios": calculate_ratios(metrics),
        "risk_flags": [], "limitations": [], "operational_metrics": [],
    }
    report = fallback_analysis(result)
    assert report["mode"] == "deterministic_financial_model_v31"
    assert len(report["strengths"]) <= 5
    assert len(report["weaknesses"]) <= 5
    assert any("Отрицательная динамика" in item for item in report["weaknesses"])
    assert len(report["esg_observations"]) == 1

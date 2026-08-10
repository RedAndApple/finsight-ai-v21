from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from app.analysis import _reconcile_balance_identities
from app.canonical import canonicalize_metrics
from app.financial import calculate_ratios
from app.parsers import (
    _native_text_quality,
    extract_ras_metrics_from_table,
    infer_year_columns,
    parse_spreadsheet,
)
from app.validation import validate_model
from app.vision import _candidate_pages


def _metric(key: str, value: float, confidence: float = 0.95, code: str | None = None) -> dict:
    return {
        "key": key,
        "name": key,
        "values": {"2025": value},
        "unit": "тыс. руб.",
        "confidence": confidence,
        "source_type": "spreadsheet_table",
        "row_code": code,
        "source_pages": [8],
    }


def _ras_rows() -> list[list[str]]:
    return [
        ["Пояснения", "Наименование показателя", "Код", "На 31 декабря 2025 г.", "На 31 декабря 2024 г."],
        ["", "Внеоборотные активы", "1100", "400", "380"],
        ["", "Оборотные активы", "1200", "600", "520"],
        ["", "Баланс", "1600", "1000", "900"],
        ["", "Капитал и резервы", "1300", "500", "450"],
        ["", "Долгосрочные обязательства", "1400", "200", "180"],
        ["", "Краткосрочные обязательства", "1500", "300", "270"],
        ["", "Выручка", "2110", "1200", "1000"],
        ["", "Валовая прибыль", "2100", "360", "300"],
        ["", "Прибыль от продаж", "2200", "250", "210"],
        ["", "Прибыль до налогообложения", "2300", "160", "120"],
        ["", "Чистая прибыль", "2400", "120", "90"],
    ]


def test_year_columns_accept_dates_but_reject_comparison_columns():
    rows = [["Показатель", "31.12.2025", "За год, закончившийся 2024", "Изменение 2025/2024"]]
    mapping, header = infer_year_columns(rows)
    assert header == 0
    assert mapping == {1: "2025", 2: "2024"}


def test_official_ras_codes_survive_arbitrary_labels_and_layout():
    candidates = extract_ras_metrics_from_table({
        "page": 37,
        "rows": _ras_rows(),
        "context": "Единица измерения: тыс. руб.",
        "source_type": "pdf_table",
    })
    indexed = {item["key"]: item for item in candidates}
    assert len(indexed) >= 11
    assert indexed["assets"]["values"] == {"2025": 1000.0, "2024": 900.0}
    assert indexed["assets"]["row_code"] == "1600"
    assert indexed["assets"]["source_pages"] == [37]
    assert indexed["net_profit"]["values"]["2025"] == 120.0


def test_xlsx_ras_statement_is_selected_without_company_hardcode(tmp_path: Path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Формы произвольной компании"
    sheet.append(["ООО Независимый тестовый эмитент"])
    sheet.append(["Бухгалтерская отчетность по РСБУ, тыс. руб."])
    for row in _ras_rows():
        sheet.append(row)
    path = tmp_path / "неизвестная_организация.xlsx"
    workbook.save(path)

    parsed = parse_spreadsheet(path, lambda *_args: None)
    assert parsed["metadata"]["accounting_standard"] == "РСБУ"
    assert parsed["metadata"]["standard_detection"]["ras"]["core_coverage"] >= 5
    assert {item["key"] for item in parsed["candidate_branches"]["ras"]} >= {
        "assets", "equity", "current_assets", "current_liabilities", "revenue", "net_profit",
    }


def test_unusable_hidden_ocr_layer_is_not_treated_as_native_text():
    readable = "Бухгалтерский баланс. Активы 1 000. Капитал 500. Краткосрочные обязательства 300."
    garbage = "Р С Б У � � A X 1 2 3 " * 80
    assert _native_text_quality(readable) >= 40
    assert _native_text_quality(garbage) < _native_text_quality(readable)


def test_balance_reconciliation_repairs_only_the_odd_total_and_keeps_original():
    metrics = {
        "assets": _metric("assets", 10000, 0.83, "1600"),
        "noncurrent_assets": _metric("noncurrent_assets", 400, 0.97, "1100"),
        "current_assets": _metric("current_assets", 600, 0.97, "1200"),
        "equity": _metric("equity", 500, 0.97, "1300"),
        "longterm_liabilities": _metric("longterm_liabilities", 200, 0.97, "1400"),
        "current_liabilities": _metric("current_liabilities", 300, 0.97, "1500"),
    }
    repaired = _reconcile_balance_identities(metrics)
    assert repaired["assets"]["values"]["2025"] == 1000
    assert repaired["assets"]["original_extracted_values"]["2025"] == 10000
    assert repaired["assets"]["source_type"] == "reconciled_from_accounting_identity"


def test_failed_identity_warns_but_does_not_erase_all_ratios():
    metrics = {
        "assets": _metric("assets", 1000),
        "noncurrent_assets": _metric("noncurrent_assets", 400),
        "current_assets": _metric("current_assets", 500),
        "equity": _metric("equity", 500),
        "longterm_liabilities": _metric("longterm_liabilities", 200),
        "current_liabilities": _metric("current_liabilities", 300),
        "revenue": _metric("revenue", 1200),
        "net_profit": _metric("net_profit", 120),
    }
    validation = validate_model(canonicalize_metrics(metrics))
    ratios = calculate_ratios(validation["valid_metrics"])
    assert validation["status"] == "failed"
    assert len(validation["valid_metrics"]) == len(metrics)
    assert next(item for item in ratios if item["key"] == "current_ratio")["status"] != "na"
    assert next(item for item in ratios if item["key"] == "net_margin")["display"] == "10.0%"


def test_vision_candidate_search_includes_late_statement_and_neighbors():
    pages = [{"page": index, "text": "Примечания к отчетности"} for index in range(1, 101)]
    pages[86]["text"] = "ОТЧЕТ О ФИНАНСОВОМ ПОЛОЖЕНИИ\nАктивы\nОбязательства"
    selected = _candidate_pages(pages, maximum=6)
    assert 87 in selected
    assert 86 in selected and 88 in selected

import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.financial import calculate_ratios, deduplicate_operational_metrics, find_metric_key, merge_financial_candidates, parse_number
from app.parsers import RAS_CODE_LABELS, extract_metrics_from_table, extract_ocr_tables, extract_unit, infer_reporting_year, infer_year_columns, parse_spreadsheet


class ParserTests(unittest.TestCase):
    def test_year_header_ignores_change_column(self):
        rows = [["", "2023", "2024", "2025", "Изменение 2025/2024"], ["Выручка", "10", "11", "12", "+9%"]]
        mapping, header = infer_year_columns(rows)
        self.assertEqual(mapping, {1: "2023", 2: "2024", 3: "2025"})
        self.assertEqual(header, 0)

    def test_table_values_are_not_overwritten_by_change(self):
        table = {
            "page": 4,
            "rows": [["", "2023", "2024", "2025", "Изменение 2025/2024"], ["Добыча нефти, млн т", "70", "72", "74", "+2,8%"]],
            "context": "Добыча нефти, млн т",
        }
        financial, operational = extract_metrics_from_table(table)
        self.assertFalse(financial)
        self.assertEqual(operational[0]["values"], {"2023": 70.0, "2024": 72.0, "2025": 74.0})
        self.assertEqual(operational[0]["unit"], "млн т")

    def test_reporting_year_comes_from_title(self):
        self.assertEqual(infer_reporting_year("Годовой отчет ПАО Тест за 2025 год\nПланы до 2030 года", ["2025", "2030"]), 2025)

    def test_hydrocarbon_reserves_are_not_inventory(self):
        self.assertIsNone(find_metric_key("Доказанные запасы углеводородов"))
        self.assertEqual(find_metric_key("Запасы, млн руб."), "inventory")

    def test_parse_number(self):
        self.assertEqual(parse_number("13 344"), 13344.0)
        self.assertEqual(parse_number("(1 250,5)"), -1250.5)

    def test_coordinate_ocr_overrides_concatenated_text_ocr(self):
        candidates = [
            {
                "key": "revenue", "unit": "тыс. руб.",
                "values": {"2025": 34532245353046943699},
                "source_type": "pdf_text", "confidence": 0.55, "source_pages": [9],
            },
            {
                "key": "revenue", "unit": "тыс. руб.",
                "values": {"2025": 3453224535, "2024": 3046943699},
                "source_type": "ras_coordinate_ocr", "confidence": 0.97, "source_pages": [9],
            },
        ]
        merged = merge_financial_candidates(candidates)
        self.assertEqual(merged["revenue"]["values"], {"2025": 3453224535.0, "2024": 3046943699.0})

    def test_impossible_ocr_value_is_rejected(self):
        merged = merge_financial_candidates([{
            "key": "cash", "unit": "тыс. руб.",
            "values": {"2025": 1251387600638265400000000000000},
            "source_type": "pdf_text", "confidence": 0.55, "source_pages": [7],
        }])
        self.assertNotIn("cash", merged)

    def test_coordinate_table_does_not_join_row_code_with_value(self):
        pages = [{
            "page": 9, "text": "Отчет о финансовых результатах", "ocr_quality": 90,
            "ocr_lines": [
                {"top": 100, "words": [
                    {"text": "2025", "left": 700, "width": 60, "height": 30},
                    {"text": "2024", "left": 1000, "width": 60, "height": 30},
                ]},
                {"top": 160, "words": [
                    {"text": "Выручка", "left": 100, "width": 150, "height": 30},
                    {"text": "2110", "left": 520, "width": 55, "height": 30},
                    {"text": "3", "left": 690, "width": 15, "height": 30},
                    {"text": "453", "left": 715, "width": 45, "height": 30},
                    {"text": "224", "left": 770, "width": 45, "height": 30},
                    {"text": "535", "left": 825, "width": 45, "height": 30},
                    {"text": "3", "left": 990, "width": 15, "height": 30},
                    {"text": "046", "left": 1015, "width": 45, "height": 30},
                    {"text": "943", "left": 1070, "width": 45, "height": 30},
                    {"text": "699", "left": 1125, "width": 45, "height": 30},
                ]},
                {"top": 220, "words": [
                    {"text": "Валовая", "left": 100, "width": 100, "height": 30},
                    {"text": "прибыль", "left": 210, "width": 100, "height": 30},
                    {"text": "2100", "left": 520, "width": 55, "height": 30},
                    {"text": "1", "left": 690, "width": 15, "height": 30},
                    {"text": "574", "left": 715, "width": 45, "height": 30},
                    {"text": "943", "left": 770, "width": 45, "height": 30},
                    {"text": "507", "left": 825, "width": 45, "height": 30},
                    {"text": "884", "left": 1015, "width": 45, "height": 30},
                    {"text": "053", "left": 1070, "width": 45, "height": 30},
                    {"text": "894", "left": 1125, "width": 45, "height": 30},
                ]},
            ],
        }]
        tables = extract_ocr_tables(pages)
        self.assertEqual(tables[0]["rows"][1], ["Выручка", "3453224535", "3046943699"])

    def test_unit_extraction_prefers_full_scale(self):
        self.assertEqual(extract_unit("Выручка, млн руб."), "млн руб.")
        self.assertEqual(extract_unit("Экономия электрической энергии, млн кВт⋅"), "млн кВт·ч")

    def test_ras_labels_are_canonical(self):
        self.assertEqual(RAS_CODE_LABELS["2110"], "Выручка")
        self.assertEqual(RAS_CODE_LABELS["1250"], "Денежные средства и денежные эквиваленты")

    def test_noisy_ocr_operational_label_is_hidden(self):
        items = [{
            "name": "Наименование показателя 2025за 2024за",
            "values": {"2024": 10, "2025": 11},
            "source_type": "ocr_coordinate_table",
            "confidence": 0.91,
        }]
        self.assertEqual(deduplicate_operational_metrics(items), [])


class FinancialTests(unittest.TestCase):
    def test_ratios(self):
        metrics = {
            "revenue": {"values": {"2024": 1000, "2025": 1200}},
            "net_profit": {"values": {"2024": 100, "2025": 150}},
            "current_assets": {"values": {"2024": 500, "2025": 600}},
            "current_liabilities": {"values": {"2024": 300, "2025": 300}},
            "inventory": {"values": {"2024": 100, "2025": 120}},
            "cash": {"values": {"2024": 80, "2025": 100}},
            "assets": {"values": {"2024": 1200, "2025": 1400}},
            "equity": {"values": {"2024": 600, "2025": 700}},
            "liabilities": {"values": {"2024": 600, "2025": 700}},
        }
        ratios = {item["key"]: item for item in calculate_ratios(metrics)}
        self.assertAlmostEqual(ratios["current_ratio"]["value"], 2.0)
        self.assertAlmostEqual(ratios["revenue_growth"]["value"], 0.2)
        self.assertAlmostEqual(ratios["net_margin"]["value"], 0.125)

    def test_spreadsheet_financial_mapping(self):
        rows = [
            ["Показатель", "2024", "2025"],
            ["Выручка, млн руб.", 1000, 1200],
            ["Чистая прибыль, млн руб.", 100, 150],
            ["Операционный денежный поток, млн руб.", 180, 220],
            ["Капитальные затраты, млн руб.", 90, 100],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.xlsx"
            pd.DataFrame(rows).to_excel(path, index=False, header=False)
            parsed = parse_spreadsheet(path, lambda *_: None)
            merged = merge_financial_candidates(parsed["financial_candidates"])
        self.assertIn("revenue", merged)
        self.assertIn("operating_cash_flow", merged)
        ratios = {item["key"]: item for item in calculate_ratios(merged)}
        self.assertEqual(ratios["free_cash_flow"]["value"], 120000.0)


if __name__ == "__main__":
    unittest.main()

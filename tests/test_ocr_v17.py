from app.analysis import fallback_analysis
from app.ocr import remove_table_lines
from PIL import Image, ImageDraw
from app.ocr import clean_ocr_text
from app.parsers import extract_ocr_tables, extract_ras_metrics_from_ocr_lines
from app.financial import derive_financial_metrics


def _word(text, left, width=40, top=100, conf=90):
    return {"text": text, "left": left, "top": top, "width": width, "height": 28, "conf": conf}


def test_clean_ocr_text_repairs_hyphenation_and_noise():
    raw = "Компания осущест-\nвляет деятельность.\n||||||||\nРиск ликвидности контролируется."
    cleaned = clean_ocr_text(raw)
    assert "осуществляет" in cleaned
    assert "||||" not in cleaned
    assert "Риск ликвидности" in cleaned


def test_ras_coordinate_row_uses_canonical_label_and_columns():
    words = [
        _word("Чистая", 100), _word("прибыль", 170), _word("2400", 520),
        _word("403", 650), _word("734", 700), _word("771", 750),
        _word("732", 930), _word("516", 980), _word("214", 1030),
    ]
    pages = [{
        "page": 9,
        "text": "Отчет о финансовых результатах",
        "ocr_lines": [{"text": "Чистая прибыль 2400 403 734 771 732 516 214", "words": words, "confidence": 90, "ocr_method": "gray-psm4"}],
    }]
    metrics = extract_ras_metrics_from_ocr_lines(pages, 2025)
    net = next(item for item in metrics if item["key"] == "net_profit")
    assert net["name"] == "Чистая прибыль"
    assert net["values"] == {"2025": 403_734_771.0, "2024": 732_516_214.0}


def test_generic_ocr_table_assigns_values_by_year_column():
    header = {
        "text": "Показатель 2025 2024",
        "top": 100,
        "words": [_word("Показатель", 80, 110, 100), _word("2025", 600, 60, 100), _word("2024", 850, 60, 100)],
    }
    row = {
        "text": "Выручка 3 453 224 535 3 046 943 699",
        "top": 150,
        "words": [
            _word("Выручка", 80, 100, 150),
            _word("3", 565, 20, 150), _word("453", 600, 45, 150), _word("224", 650, 45, 150), _word("535", 700, 45, 150),
            _word("3", 815, 20, 150), _word("046", 850, 45, 150), _word("943", 900, 45, 150), _word("699", 950, 45, 150),
        ],
    }
    row2 = {
        "text": "Чистая прибыль 403 734 771 732 516 214",
        "top": 200,
        "words": [
            _word("Чистая", 80, 70, 200), _word("прибыль", 155, 90, 200),
            _word("403", 600, 45, 200), _word("734", 650, 45, 200), _word("771", 700, 45, 200),
            _word("732", 850, 45, 200), _word("516", 900, 45, 200), _word("214", 950, 45, 200),
        ],
    }
    tables = extract_ocr_tables([{"page": 4, "ocr_quality": 90, "ocr_lines": [header, row, row2], "text": ""}])
    assert len(tables) == 1
    assert tables[0]["rows"][1] == ["Выручка", "3453224535", "3046943699"]


def test_fallback_never_uses_raw_ocr_narrative_for_financial_summary():
    result = {
        "metadata": {"company": "АО «Тест»", "document_type": "ras_financial_statements", "reporting_year": 2025},
        "financial_metrics": {
            "revenue": {"values": {"2024": 100, "2025": 120}},
            "net_profit": {"values": {"2024": 20, "2025": 15}},
            "current_assets": {"values": {"2025": 80}},
            "current_liabilities": {"values": {"2025": 100}},
        },
        "ratios": [
            {"key": "current_ratio", "value": 0.8, "status": "bad", "display": "0,80", "name": "Current Ratio", "explanation": "test"},
            {"key": "revenue_growth", "value": 0.2, "status": "good", "display": "20,0%", "name": "Revenue Growth", "explanation": "test"},
            {"key": "net_profit_growth", "value": -0.25, "status": "bad", "display": "-25,0%", "name": "Net Profit Growth", "explanation": "test"},
        ],
        "risk_flags": [],
        "limitations": [],
        "narrative": {"strategy": [{"text": "НАИМЕНОВАНИЕ ПОКАЗАТЕЛЯ 2025ЗА 2024ЗА мусор", "page": 8}], "esg": []},
    }
    analysis = fallback_analysis(result)
    combined = " ".join([analysis["executive_summary"], *analysis["strategic_observations"]]).lower()
    assert "наименование показателя" not in combined
    assert "выручка" in combined
    assert "ликвид" in combined
def test_table_line_removal_preserves_cell_content():
    image = Image.new("L", (300, 120), 255)
    draw = ImageDraw.Draw(image)
    draw.line((0, 20, 299, 20), fill=0, width=2)
    draw.line((100, 0, 100, 119), fill=0, width=2)
    draw.rectangle((150, 50, 160, 70), fill=0)
    cleaned = remove_table_lines(image)
    assert cleaned.getpixel((50, 20)) == 255
    assert cleaned.getpixel((100, 90)) == 255
    assert cleaned.getpixel((155, 60)) == 0


def test_missing_statement_rows_are_reconciled_from_verified_subtotals():
    metrics = {
        "revenue": {"values": {"2025": 3_453_224_535}, "unit": "тыс. руб.", "confidence": .98},
        "gross_profit": {"values": {"2025": 1_574_943_507}, "unit": "тыс. руб.", "confidence": .98},
        "commercial_expenses": {"values": {"2025": -128_102_422}, "unit": "тыс. руб.", "confidence": .98},
        "operating_profit": {"values": {"2025": 1_383_144_385}, "unit": "тыс. руб.", "confidence": .98},
    }
    derived = derive_financial_metrics(metrics)
    assert derived["cogs"]["values"]["2025"] == -1_878_281_028
    assert derived["administrative_expenses"]["values"]["2025"] == -63_696_700

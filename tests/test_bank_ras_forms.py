from app.canonical import canonicalize_metrics
from app.financial import calculate_ratios, derive_financial_metrics, merge_financial_candidates
from app.parsers import extract_bank_ras_metrics_from_ocr_lines
from app.validation import validate_model


def _line(label: str, current: int, previous: int, top: int) -> dict:
    words = []
    left = 80
    for token in label.split():
        words.append({"text": token, "left": left, "top": top, "width": max(20, len(token) * 9), "height": 18, "conf": 95})
        left += max(20, len(token) * 9) + 8
    for start, value in ((1050, current), (1300, previous)):
        cursor = start
        chunks = f"{abs(value):,}".replace(",", " ").split()
        for index, chunk in enumerate(chunks):
            text = ("-" if value < 0 and index == 0 else "") + chunk
            words.append({"text": text, "left": cursor, "top": top, "width": len(text) * 12, "height": 18, "conf": 96})
            cursor += len(text) * 12 + 7
    return {"text": " ".join(word["text"] for word in words), "top": top, "confidence": 95, "words": words}


def _bank_pages() -> list[dict]:
    balance_rows = [
        _line("1 Денежные средства", 701_792_637, 660_479_380, 600),
        _line("2 Средства кредитной организации в Центральном банке", 2_172_320_782, 1_412_490_747, 650),
        _line("3 Средства в кредитных организациях", 92_516_903, 92_824_918, 700),
        _line("5 Чистая ссудная задолженность", 45_818_896_497, 41_848_301_823, 750),
        _line("14 Всего активов", 65_210_686_723, 58_073_010_907, 800),
        _line("16 Средства клиентов по амортизированной стоимости", 49_551_904_795, 46_786_515_733, 850),
        _line("24 Всего обязательств", 57_095_605_843, 51_099_358_722, 900),
        _line("37 Нераспределенная прибыль", 7_952_829_520, 7_065_090_606, 950),
        _line("38 Всего источников собственных средств", 8_115_080_880, 6_973_652_185, 1000),
    ]
    pnl_rows = [
        _line("1 Процентные доходы всего", 9_185_216_024, 7_170_733_204, 600),
        _line("2 Процентные расходы всего", 5_924_297_757, 4_412_032_690, 650),
        _line("3 Чистые процентные доходы", 3_260_918_267, 2_758_700_514, 700),
        _line("4 Изменение резервов на возможные потери", 580_590_045, 447_528_174, 750),
        _line("5 Чистые процентные доходы после резервов", 2_680_328_222, 2_311_172_340, 800),
        _line("14 Комиссионные доходы", 1_174_621_568, 1_140_962_303, 850),
        _line("15 Комиссионные расходы", 386_717_495, 341_355_331, 900),
        _line("20 Чистые доходы расходы", 3_557_267_841, 3_104_199_221, 950),
        _line("21 Операционные расходы", 1_406_165_471, 1_245_819_822, 1000),
        _line("22 Прибыль до налогообложения", 2_151_102_370, 1_858_379_399, 1050),
        _line("23 Расход по налогу на прибыль", 468_357_575, 303_450_502, 1100),
        _line("26 Прибыль за отчетный период", 1_682_744_795, 1_554_928_897, 1150),
    ]
    return [
        {"page": 6, "text": "Бухгалтерский баланс Код формы по ОКУД 0409806", "ocr_lines": balance_rows},
        {"page": 7, "text": "Отчет о финансовых результатах Код формы по ОКУД 0409807", "ocr_lines": pnl_rows},
    ]


def test_bank_of_russia_forms_build_valid_bank_model_and_ratios():
    candidates, form_codes = extract_bank_ras_metrics_from_ocr_lines(_bank_pages(), 2025)
    assert form_codes == ["0409806", "0409807"]
    metrics = derive_financial_metrics(merge_financial_candidates(candidates))
    validation = validate_model(canonicalize_metrics(metrics))
    valid = validation["valid_metrics"]

    assert validation["status"] == "passed"
    assert valid["assets"]["values"]["2025"] == 65_210_686_723
    assert valid["liabilities"]["values"]["2025"] == 57_095_605_843
    assert valid["equity"]["values"]["2025"] == 8_115_080_880
    assert valid["net_profit"]["values"]["2025"] == 1_682_744_795

    ratios = {item["key"]: item for item in calculate_ratios(valid)}
    assert set(ratios) == {
        "roa", "roe", "equity_ratio", "bank_loan_to_deposit", "bank_cost_to_income",
        "bank_credit_loss_to_loans", "bank_net_interest_income_to_assets",
        "bank_net_interest_income_growth", "bank_fee_income_growth", "net_profit_growth",
    }
    assert round(ratios["bank_loan_to_deposit"]["value"], 4) == 0.9247
    assert round(ratios["bank_cost_to_income"]["value"], 4) == 0.3953
    assert ratios["roa"]["status"] == "good"

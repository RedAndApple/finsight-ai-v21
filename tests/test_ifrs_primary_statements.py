from app.canonical import canonicalize_metrics
from app.financial import calculate_ratios, derive_financial_metrics, merge_financial_candidates
from app.parsers import (
    extract_ifrs_note_metrics,
    extract_ifrs_statement_metrics,
    extract_ras_form_metrics,
)
from app.validation import validate_model


def _page(number: int, text: str) -> dict:
    return {"page": number, "text": text, "ocr_lines": [], "ocr_quality": 96}


def test_ifrs_primary_forms_are_extracted_without_ras_codes():
    pages = [
        _page(9, """
            Консолидированный бухгалтерский баланс
            на 31 декабря 2025 года
            (в миллионах российских рублей)
            Оборотные активы
            Денежные средства и их эквиваленты 633 190 991 889
            Дебиторская задолженность и предоплата 1 241 989 1 488 185
            Запасы 1 296 508 1 305 559
            3 596 395 4 368 456
            Внеоборотные активы
            28 294 416 26 329 799
            Итого активы 31 890 811 30 698 255
            Краткосрочные обязательства
            долгосрочной задолженности по кредитам и займам 1 499 165 1 422 056
            4 631 960 4 971 895
            Долгосрочные обязательства
            Долгосрочные кредиты и займы 5 238 487 5 292 754
            8 365 162 8 065 398
            Итого обязательства 12 997 122 13 037 293
            Нераспределенная прибыль и прочие резервы 17 057 601 15 628 372
            Итого капитал 18 893 689 17 660 962
            Итого обязательства и капитал 31 890 811 30 698 255
        """),
        _page(10, """
            Консолидированный отчет о совокупном доходе
            (в миллионах российских рублей)
            Выручка от продаж 9 770 671 10 714 686
            Прибыль от продаж 1 309 766 1 456 390
            Финансовые доходы 1 072 045 1 002 183
            Финансовые расходы (472 024) (1 037 645)
            Прибыль до налогообложения 2 013 116 1 662 936
            Налог на прибыль (664 719) (344 226)
            Прибыль за год 1 348 397 1 318 710
            Совокупный доход за год 1 365 222 1 279 461
        """),
        _page(11, """
            Консолидированный отчет о движении денежных средств
            (в миллионах российских рублей)
            Чистые денежные средства от операционной деятельности 2 867 018 2 495 688
            Капитальные вложения (2 594 673) (2 292 360)
            Чистые денежные средства, использованные в инвестиционной деятельности (3 093 553) (2 212 144)
            Чистые денежные средства, использованные в финансовой деятельности (78 151) (736 094)_
            Уменьшение денежных средств и их эквивалентов (358 699) (434 891)
            Денежные средства и их эквиваленты на начало отчетного года 991 889 1 426 780
            Денежные средства и их эквиваленты на конец отчетного года 633 190 991 889
        """),
    ]
    candidates = extract_ifrs_statement_metrics(pages, 2025)
    by_key = {item["key"]: item for item in candidates}

    assert by_key["assets"]["values"]["2025"] == 31_890_811
    assert by_key["receivables"]["values"]["2025"] == 1_241_989
    assert by_key["revenue"]["values"]["2025"] == 9_770_671
    assert by_key["financing_cash_flow"]["values"]["2024"] == -736_094
    assert extract_ras_form_metrics(pages, 2025) == []

    merged = derive_financial_metrics(merge_financial_candidates(candidates))
    validation = validate_model(canonicalize_metrics(merged))
    metrics = validation.pop("valid_metrics")
    assert validation["status"] == "passed"
    assert all(check["status"] == "passed" for check in validation["checks"])
    ratios = {item["key"]: item for item in calculate_ratios(metrics)}
    assert ratios["current_ratio"]["value"] is not None
    assert ratios["roa"]["value"] is not None
    assert ratios["net_margin"]["value"] is not None


def test_ifrs_notes_supply_depreciation_and_specific_interest_expense():
    pages = [
        _page(51, """
            Примечания к консолидированной финансовой отчетности
            (в миллионах российских рублей)
            27 Операционные расходы
            Амортизация 1 433 790 1 377 774
        """),
        _page(52, """
            Примечания к консолидированной финансовой отчетности
            (в миллионах российских рублей)
            28 Финансовые доходы и расходы
            Процентный расход 307 135 269 432
        """),
    ]
    notes = {item["key"]: item for item in extract_ifrs_note_metrics(pages, 2025)}
    assert notes["depreciation_amortization"]["values"]["2025"] == 1_433_790
    assert notes["interest_expense"]["values"]["2025"] == -307_135

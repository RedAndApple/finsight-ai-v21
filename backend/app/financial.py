from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any, Iterable


FINANCIAL_SYNONYMS: dict[str, list[str]] = {
    "revenue": ["выручка", "revenue", "sales", "sales revenue"],
    "cogs": ["себестоимость продаж", "себестоимость", "cost of sales", "cost of goods sold"],
    "gross_profit": ["валовая прибыль", "gross profit"],
    "operating_profit": ["операционная прибыль", "прибыль от операционной деятельности", "operating profit", "ebit"],
    "ebitda": ["ebitda", "скорректированная ebitda"],
    "net_profit": ["чистая прибыль", "прибыль за год", "net profit", "net income", "profit for the year"],
    "cash": ["денежные средства и их эквиваленты", "денежные средства", "cash and cash equivalents", "cash"],
    "receivables": ["дебиторская задолженность", "trade receivables", "accounts receivable", "receivables"],
    "inventory": ["запасы", "inventories", "inventory"],
    "current_assets": ["оборотные активы", "current assets"],
    "noncurrent_assets": ["внеоборотные активы", "non-current assets", "noncurrent assets"],
    "assets": ["итого активы", "всего активов", "активы, всего", "total assets"],
    "current_liabilities": ["краткосрочные обязательства", "current liabilities"],
    "longterm_liabilities": ["долгосрочные обязательства", "non-current liabilities", "long-term liabilities"],
    "liabilities": ["итого обязательства", "обязательства, всего", "total liabilities"],
    "equity": ["собственный капитал", "капитал, всего", "итого капитал", "total equity", "shareholders equity"],
    "operating_cash_flow": ["операционный денежный поток", "денежный поток от операционной деятельности", "чистые денежные средства от операционной деятельности", "operating cash flow", "cash flows from operating activities"],
    "investing_cash_flow": ["инвестиционный денежный поток", "денежный поток от инвестиционной деятельности", "investing cash flow", "cash flows from investing activities"],
    "financing_cash_flow": ["финансовый денежный поток", "денежный поток от финансовой деятельности", "financing cash flow", "cash flows from financing activities"],
    "capex": ["капитальные затраты", "capital expenditures", "capital expenditure", "capex"],
    "total_debt": ["общий долг", "долговые обязательства", "total debt", "borrowings"],
    "financial_investments": ["финансовые вложения", "financial investments"],
    "retained_earnings": ["нераспределенная прибыль", "retained earnings"],
    "payables": ["кредиторская задолженность", "accounts payable", "trade payables"],
    "commercial_expenses": ["коммерческие расходы", "selling expenses"],
    "administrative_expenses": ["управленческие расходы", "administrative expenses"],
    "profit_before_tax": ["прибыль до налогообложения", "profit before tax"],
    "interest_income": ["проценты к получению", "interest income"],
    "interest_expense": ["проценты к уплате", "interest expense"],
    "other_income": ["прочие доходы", "other income"],
    "other_expenses": ["прочие расходы", "other expenses"],
    "income_tax": ["налог на прибыль", "income tax"],
    "comprehensive_income": ["совокупный финансовый результат", "comprehensive income"],
    "operating_receipts": ["поступления от текущих операций", "operating receipts"],
    "operating_payments": ["платежи по текущим операциям", "operating payments"],
    "net_cash_change": ["сальдо денежных потоков за период", "net change in cash"],
    "cash_begin": ["остаток денежных средств на начало периода", "cash at beginning"],
    "cash_end": ["остаток денежных средств на конец периода", "cash at end"],
}

DISPLAY_NAMES = {
    "revenue": "Выручка",
    "cogs": "Себестоимость",
    "gross_profit": "Валовая прибыль",
    "operating_profit": "Операционная прибыль",
    "ebitda": "EBITDA",
    "net_profit": "Чистая прибыль",
    "cash": "Денежные средства",
    "receivables": "Дебиторская задолженность",
    "inventory": "Запасы",
    "current_assets": "Оборотные активы",
    "noncurrent_assets": "Внеоборотные активы",
    "assets": "Активы",
    "current_liabilities": "Краткосрочные обязательства",
    "longterm_liabilities": "Долгосрочные обязательства",
    "liabilities": "Обязательства",
    "equity": "Собственный капитал",
    "operating_cash_flow": "Операционный денежный поток",
    "investing_cash_flow": "Инвестиционный денежный поток",
    "financing_cash_flow": "Финансовый денежный поток",
    "capex": "Капитальные затраты",
    "total_debt": "Общий долг",
    "longterm_debt_component": "Долгосрочные заемные средства",
    "shortterm_debt_component": "Краткосрочные заемные средства",
    "financial_investments": "Финансовые вложения",
    "retained_earnings": "Нераспределенная прибыль",
    "payables": "Кредиторская задолженность",
    "commercial_expenses": "Коммерческие расходы",
    "administrative_expenses": "Управленческие расходы",
    "profit_before_tax": "Прибыль до налогообложения",
    "interest_income": "Проценты к получению",
    "interest_expense": "Проценты к уплате",
    "other_income": "Прочие доходы",
    "other_expenses": "Прочие расходы",
    "income_tax": "Налог на прибыль",
    "comprehensive_income": "Совокупный финансовый результат",
    "operating_receipts": "Поступления от текущих операций",
    "operating_payments": "Платежи по текущим операциям",
    "net_cash_change": "Изменение денежных средств за период",
    "cash_begin": "Денежные средства на начало периода",
    "cash_end": "Денежные средства на конец периода",
}

OPERATIONAL_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("Добыча и запасы", ("добыч", "запас", "скваж", "бурен", "нефт", "газ", "углеводород")),
    ("Переработка и производство", ("переработ", "производств", "выпуск", "мощност", "генерац", "электроэнерг")),
    ("Продажи и сбыт", ("реализац", "продаж", "азс", "клиент", "рынок")),
    ("ESG и персонал", ("выброс", "климат", "персонал", "сотрудник", "травмат", "эколог")),
    ("Корпоративное управление", ("совет директоров", "акционер", "дивиденд", "вознагражден")),
]


def normalize_label(value: str) -> str:
    value = value.lower().replace("ё", "е")
    value = re.sub(r"[\u00ad\u2010-\u2015]", "-", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .,:;–—-\t")


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "–", "—", "н/д", "n/a", "na"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.replace("\u00a0", " ").replace("−", "-")
    text = re.sub(r"(?<=\d)\s+(?=\d)", "", text)
    text = text.replace("%", "").replace("₽", "").replace("руб.", "")
    text = re.sub(r"[^0-9,\.\-+]", "", text)
    if not text or text in {"-", "+"}:
        return None
    if text.count(",") == 1 and text.count(".") == 0:
        text = text.replace(",", ".")
    elif text.count(",") > 0 and text.count(".") > 0:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return -abs(number) if negative else number


def find_metric_key(label: str) -> str | None:
    """Map a row label to a normalized financial metric.

    The exclusions matter for annual reports: e.g. "доказанные запасы" are
    hydrocarbon reserves, not accounting inventories.
    """
    normalized = normalize_label(label)
    exclusions = {
        "inventory": ("углеводород", "нефт", "газ", "доказанн", "вероятн", "возможн", "скваж", "ресурс"),
        "cash": ("денежное вознаграждение", "денежная выплата"),
        "revenue": ("налоговая выручка",),
    }
    best: tuple[int, str] | None = None
    for key, synonyms in FINANCIAL_SYNONYMS.items():
        if any(token in normalized for token in exclusions.get(key, ())):
            continue
        for synonym in synonyms:
            candidate = normalize_label(synonym)
            if normalized == candidate or candidate in normalized:
                score = len(candidate)
                if best is None or score > best[0]:
                    best = (score, key)
    return best[1] if best else None


def classify_operational(label: str) -> str:
    normalized = normalize_label(label)
    for category, keywords in OPERATIONAL_CATEGORIES:
        if any(keyword in normalized for keyword in keywords):
            return category
    return "Прочие показатели"


def safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def average(a: float | None, b: float | None) -> float | None:
    values = [value for value in (a, b) if value is not None]
    return sum(values) / len(values) if values else None


def growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / abs(previous)


def metric_status(value: float | None, good, warn) -> str:
    if value is None:
        return "na"
    if good(value):
        return "good"
    if warn(value):
        return "warn"
    return "bad"


def calculate_ratios(financial_metrics: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    years = sorted({int(year) for item in financial_metrics.values() for year in item.get("values", {}) if str(year).isdigit()})
    if not years:
        return []
    current_year = str(max(years))
    previous_year = str(sorted(years)[-2]) if len(years) > 1 else current_year

    def get(key: str, year: str) -> float | None:
        item = financial_metrics.get(key, {})
        return parse_number(item.get("values", {}).get(year))

    c = {key: get(key, current_year) for key in FINANCIAL_SYNONYMS}
    p = {key: get(key, previous_year) for key in FINANCIAL_SYNONYMS}

    ratio_definitions: list[tuple[str, str, float | None, str, str, str]] = []

    def add(key: str, name: str, value: float | None, formula: str, status: str, explanation: str) -> None:
        ratio_definitions.append((key, name, value, formula, status, explanation))

    current_ratio = safe_divide(c["current_assets"], c["current_liabilities"])
    add("current_ratio", "Current Ratio", current_ratio, "Оборотные активы / Краткосрочные обязательства", metric_status(current_ratio, lambda x: x >= 1.5, lambda x: x >= 1), "Покрытие краткосрочных обязательств оборотными активами")
    quick_ratio = safe_divide((c["current_assets"] - c["inventory"]) if c["current_assets"] is not None and c["inventory"] is not None else None, c["current_liabilities"])
    add("quick_ratio", "Quick Ratio", quick_ratio, "(Оборотные активы − Запасы) / Краткосрочные обязательства", metric_status(quick_ratio, lambda x: x >= 1, lambda x: x >= 0.7), "Ликвидность без учета запасов")
    cash_ratio = safe_divide(c["cash"], c["current_liabilities"])
    add("cash_ratio", "Cash Ratio", cash_ratio, "Денежные средства / Краткосрочные обязательства", metric_status(cash_ratio, lambda x: x >= 0.2, lambda x: x >= 0.1), "Немедленная платежеспособность")
    debt_base = c["total_debt"] if c["total_debt"] is not None else c["liabilities"]
    debt_ratio = safe_divide(debt_base, c["assets"])
    add("debt_ratio", "Debt Ratio", debt_ratio, "Долг (или обязательства) / Активы", metric_status(debt_ratio, lambda x: x <= 0.5, lambda x: x <= 0.7), "Доля активов, профинансированная заемными источниками")
    debt_equity = safe_divide(debt_base, c["equity"])
    add("debt_equity", "Debt / Equity", debt_equity, "Долг (или обязательства) / Собственный капитал", metric_status(debt_equity, lambda x: x <= 1, lambda x: x <= 2), "Финансовый рычаг")
    equity_ratio = safe_divide(c["equity"], c["assets"])
    add("equity_ratio", "Equity Ratio", equity_ratio, "Собственный капитал / Активы", metric_status(equity_ratio, lambda x: x >= 0.5, lambda x: x >= 0.3), "Доля собственного финансирования")
    roa = safe_divide(c["net_profit"], average(c["assets"], p["assets"]))
    add("roa", "ROA", roa, "Чистая прибыль / Средние активы", metric_status(roa, lambda x: x >= 0.08, lambda x: x >= 0.03), "Рентабельность активов")
    roe = safe_divide(c["net_profit"], average(c["equity"], p["equity"]))
    add("roe", "ROE", roe, "Чистая прибыль / Средний собственный капитал", metric_status(roe, lambda x: x >= 0.15, lambda x: x >= 0.08), "Рентабельность собственного капитала")
    net_margin = safe_divide(c["net_profit"], c["revenue"])
    add("net_margin", "Net Margin", net_margin, "Чистая прибыль / Выручка", metric_status(net_margin, lambda x: x >= 0.1, lambda x: x >= 0.04), "Чистая маржинальность")
    gross_margin = safe_divide(c["gross_profit"], c["revenue"])
    add("gross_margin", "Gross Margin", gross_margin, "Валовая прибыль / Выручка", metric_status(gross_margin, lambda x: x >= 0.3, lambda x: x >= 0.15), "Валовая маржа")
    operating_margin = safe_divide(c["operating_profit"], c["revenue"])
    add("operating_margin", "Operating Margin", operating_margin, "Операционная прибыль / Выручка", metric_status(operating_margin, lambda x: x >= 0.12, lambda x: x >= 0.05), "Операционная маржа")
    ebitda_margin = safe_divide(c["ebitda"], c["revenue"])
    add("ebitda_margin", "EBITDA Margin", ebitda_margin, "EBITDA / Выручка", metric_status(ebitda_margin, lambda x: x >= 0.15, lambda x: x >= 0.08), "Маржа EBITDA")
    asset_turnover = safe_divide(c["revenue"], average(c["assets"], p["assets"]))
    add("asset_turnover", "Asset Turnover", asset_turnover, "Выручка / Средние активы", metric_status(asset_turnover, lambda x: x >= 1, lambda x: x >= 0.5), "Эффективность использования активов")
    inventory_turnover = safe_divide(abs(c["cogs"]) if c["cogs"] is not None else None, average(c["inventory"], p["inventory"]))
    add("inventory_turnover", "Inventory Turnover", inventory_turnover, "Себестоимость / Средние запасы", metric_status(inventory_turnover, lambda x: x >= 4, lambda x: x >= 2), "Скорость оборота запасов")
    receivables_turnover = safe_divide(c["revenue"], average(c["receivables"], p["receivables"]))
    add("receivables_turnover", "Receivables Turnover", receivables_turnover, "Выручка / Средняя дебиторская задолженность", metric_status(receivables_turnover, lambda x: x >= 6, lambda x: x >= 3), "Скорость инкассации дебиторской задолженности")
    ocf_ratio = safe_divide(c["operating_cash_flow"], c["current_liabilities"])
    add("ocf_ratio", "Operating Cash Flow Ratio", ocf_ratio, "Операционный денежный поток / Краткосрочные обязательства", metric_status(ocf_ratio, lambda x: x >= 0.5, lambda x: x >= 0.2), "Покрытие обязательств денежным потоком")
    fcf = (c["operating_cash_flow"] - abs(c["capex"])) if c["operating_cash_flow"] is not None and c["capex"] is not None else None
    add("free_cash_flow", "Free Cash Flow", fcf, "Операционный денежный поток − CAPEX", "na" if fcf is None else ("good" if fcf > 0 else "bad"), "Свободный денежный поток")
    working_capital = (c["current_assets"] - c["current_liabilities"]) if c["current_assets"] is not None and c["current_liabilities"] is not None else None
    add("working_capital", "Working Capital", working_capital, "Оборотные активы − Краткосрочные обязательства", "na" if working_capital is None else ("good" if working_capital >= 0 else "bad"), "Чистый оборотный капитал")
    net_debt = (debt_base - c["cash"]) if debt_base is not None and c["cash"] is not None else None
    add("net_debt", "Net Debt", net_debt, "Долг − Денежные средства", "na" if net_debt is None else ("good" if net_debt <= 0 else "warn"), "Чистая долговая позиция")
    net_debt_equity = safe_divide(net_debt, c["equity"])
    add("net_debt_equity", "Net Debt / Equity", net_debt_equity, "(Долг − Денежные средства) / Собственный капитал", metric_status(net_debt_equity, lambda x: x <= 0.5, lambda x: x <= 1.5), "Чистый финансовый рычаг")
    interest_coverage = safe_divide(c["operating_profit"], abs(c["interest_expense"]) if c["interest_expense"] is not None else None)
    add("interest_coverage", "Interest Coverage", interest_coverage, "Операционная прибыль / Проценты к уплате", metric_status(interest_coverage, lambda x: x >= 5, lambda x: x >= 2), "Запас покрытия процентных расходов")
    ocf_margin = safe_divide(c["operating_cash_flow"], c["revenue"])
    add("ocf_margin", "Operating Cash Flow Margin", ocf_margin, "Операционный денежный поток / Выручка", metric_status(ocf_margin, lambda x: x >= 0.12, lambda x: x >= 0.05), "Денежная отдача выручки")
    cash_conversion = safe_divide(c["operating_cash_flow"], c["net_profit"])
    add("cash_conversion", "Cash Conversion", cash_conversion, "Операционный денежный поток / Чистая прибыль", metric_status(cash_conversion, lambda x: x >= 1, lambda x: x >= 0.7), "Качество прибыли через денежный поток")
    revenue_growth = growth(c["revenue"], p["revenue"])
    add("revenue_growth", "Revenue Growth", revenue_growth, "(Выручка текущего года − Выручка прошлого года) / Выручка прошлого года", metric_status(revenue_growth, lambda x: x >= 0.1, lambda x: x >= 0), "Темп роста выручки")
    profit_growth = growth(c["net_profit"], p["net_profit"])
    add("net_profit_growth", "Net Profit Growth", profit_growth, "(Чистая прибыль текущего года − Чистая прибыль прошлого года) / |Чистая прибыль прошлого года|", metric_status(profit_growth, lambda x: x >= 0.1, lambda x: x >= 0), "Темп роста чистой прибыли")

    percent_keys = {"debt_ratio", "equity_ratio", "roa", "roe", "net_margin", "gross_margin", "operating_margin", "ebitda_margin", "ocf_margin", "revenue_growth", "net_profit_growth"}
    output = []
    for key, name, value, formula, status, explanation in ratio_definitions:
        output.append({
            "key": key,
            "name": name,
            "value": value,
            "display": "—" if value is None else (f"{value * 100:.1f}%" if key in percent_keys else f"{value:,.2f}".replace(",", " ")),
            "formula": formula,
            "status": status,
            "explanation": explanation,
            "current_year": current_year,
            "previous_year": previous_year,
        })
    return output


def build_risk_flags(
    financial_metrics: dict[str, dict[str, Any]],
    ratios: list[dict[str, Any]],
    text: str,
    pages: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    years = sorted({int(y) for item in financial_metrics.values() for y in item.get("values", {}) if str(y).isdigit()})
    current_year = str(max(years)) if years else None

    def current(key: str) -> float | None:
        if current_year is None:
            return None
        return parse_number(financial_metrics.get(key, {}).get("values", {}).get(current_year))

    ratio_map = {item["key"]: item.get("value") for item in ratios}
    flags: list[dict[str, Any]] = []

    def add(code: str, title: str, severity: str, reason: str, source_pages: list[int] | None = None) -> None:
        flags.append({"code": code, "title": title, "severity": severity, "reason": reason, "source_pages": source_pages or []})

    if current("equity") is not None and current("equity") < 0:
        add("negative_equity", "Отрицательный собственный капитал", "critical", "Обязательства превышают стоимость активов, относимую к собственникам.")
    if current("net_profit") is not None and current("net_profit") < 0:
        add("net_loss", "Чистый убыток", "high", "За последний доступный период зафиксирована отрицательная чистая прибыль.")
    if current("operating_cash_flow") is not None and current("operating_cash_flow") < 0:
        add("negative_ocf", "Отрицательный операционный денежный поток", "high", "Основная деятельность не сформировала положительный денежный поток.")
    if ratio_map.get("current_ratio") is not None and ratio_map["current_ratio"] < 1:
        add("low_liquidity", "Недостаточная текущая ликвидность", "high", "Current Ratio ниже 1,0.")
    if ratio_map.get("debt_equity") is not None and ratio_map["debt_equity"] > 2:
        add("high_leverage", "Высокая долговая нагрузка", "high", "Debt / Equity превышает 2,0.")
    if ratio_map.get("revenue_growth") is not None and ratio_map["revenue_growth"] < 0:
        add("revenue_decline", "Снижение выручки", "medium", "Выручка уменьшилась по сравнению с предыдущим периодом.")
    if ratio_map.get("net_profit_growth") is not None and ratio_map["net_profit_growth"] < 0:
        add("profit_decline", "Снижение чистой прибыли", "medium", "Чистая прибыль снизилась по сравнению с предыдущим периодом.")

    normalized = normalize_label(text)
    text_rules = [
        ("sanctions", "Санкционные и регуляторные ограничения", "high", ("санкц", "ограничительн")),
        ("market_price", "Ценовой риск", "medium", ("снижение цен", "волатильност", "цена нефти")),
        ("climate", "Климатические риски", "medium", ("климатическ риск", "углеродн")),
        ("cyber", "Киберриск", "medium", ("кибер", "информационн безопасност")),
        ("legal", "Правовой и комплаенс-риск", "medium", ("судебн", "комплаенс", "правов")),
    ]
    for code, title, severity, keywords in text_rules:
        if any(keyword in normalized for keyword in keywords) and not any(item["code"] == code for item in flags):
            source_pages: list[int] = []
            for page in pages or []:
                page_text = normalize_label(page.get("text", ""))
                if any(keyword in page_text for keyword in keywords):
                    source_pages.append(int(page.get("page", 0)))
                    if len(source_pages) >= 5:
                        break
            add(code, title, severity, "Риск прямо или косвенно раскрыт в тексте документа.", source_pages)
    return flags[:20]


def score_analysis(ratios: list[dict[str, Any]], risk_flags: list[dict[str, Any]], metadata: dict[str, Any], tables_count: int, operational_count: int) -> dict[str, Any]:
    available = [item for item in ratios if item.get("status") != "na"]
    if len(available) >= 5:
        weights = {"good": 100, "warn": 60, "bad": 20}
        base = sum(weights[item["status"]] for item in available) / len(available)
        penalties = sum({"critical": 10, "high": 6, "medium": 3, "low": 1}.get(flag["severity"], 0) for flag in risk_flags)
        score = max(0, min(100, round(base - penalties)))
        return {"value": score, "mode": "financial", "explanation": f"Оценка рассчитана по {len(available)} доступным финансовым коэффициентам с учетом риск-флагов."}

    components = {
        "text_layer": 20 if metadata.get("text_pages", 0) > 0 else 0,
        "multi_year_data": 20 if len(metadata.get("years", [])) >= 2 else 0,
        "tables": min(20, tables_count * 2),
        "operational_metrics": min(20, operational_count),
        "governance_and_risks": 10 if metadata.get("has_risk_section") else 0,
        "audit_or_financial_reference": 10 if metadata.get("has_audit_reference") or metadata.get("has_financial_statements_reference") else 0,
    }
    score = min(100, sum(components.values()))
    return {"value": score, "mode": "document_completeness", "components": components, "explanation": "Полный коэффициентный анализ невозможен; оценка отражает полноту и аналитическую пригодность документа."}


SOURCE_PRIORITY = {
    "ras_coordinate_ocr": 100,
    "verified_demo": 100,
    "pdf_table": 80,
    "spreadsheet_table": 80,
    "ras_ocr_form": 65,
    "pdf_text": 35,
}


def _plausible_financial_value(value: float, unit: str | None) -> bool:
    """Reject catastrophic OCR concatenations before they reach ratios/UI.

    Russian statutory forms are commonly expressed in thousand rubles. A value
    above 20 trillion *thousand* rubles is not a plausible single-company line
    item and almost always means that OCR glued several year columns together.
    The ruble ceiling is scaled accordingly.
    """
    magnitude = abs(value)
    normalized_unit = normalize_label(unit or "")
    if "тыс" in normalized_unit:
        return magnitude <= 20_000_000_000
    if "млн" in normalized_unit:
        return magnitude <= 20_000_000
    if "млрд" in normalized_unit:
        return magnitude <= 20_000
    if "руб" in normalized_unit:
        return magnitude <= 20_000_000_000_000
    return magnitude <= 20_000_000_000_000


def _candidate_quality(candidate: dict[str, Any]) -> float:
    source_bonus = {
        "ras_coordinate_ocr": 0.35,
        "ras_ocr_form": 0.15,
        "pdf_table": 0.10,
        "spreadsheet": 0.20,
    }.get(str(candidate.get("source_type") or ""), 0.0)
    return float(candidate.get("confidence", 0.5)) + source_bonus


def _normalize_monetary_values(values: dict[str, float], unit: str | None) -> tuple[dict[str, float], str | None]:
    """Normalize ruble-denominated rows to thousand rubles.

    Ratio calculations are only meaningful when rows use the same scale.
    """
    normalized_unit = normalize_label(unit or "")
    multiplier = 1.0
    target = unit
    if "млрд" in normalized_unit and ("руб" in normalized_unit or "rur" in normalized_unit):
        multiplier, target = 1_000_000.0, "тыс. руб."
    elif "млн" in normalized_unit and ("руб" in normalized_unit or "rur" in normalized_unit):
        multiplier, target = 1_000.0, "тыс. руб."
    elif normalized_unit in {"руб", "руб.", "rur", "rub"} or ("руб" in normalized_unit and "тыс" not in normalized_unit):
        multiplier, target = 0.001, "тыс. руб."
    return ({year: value * multiplier for year, value in values.items()}, target)


def _candidate_values_are_consistent(values: dict[str, float]) -> bool:
    nonzero = [abs(float(value)) for value in values.values() if value not in (None, 0)]
    if len(nonzero) < 2:
        return True
    smallest, largest = min(nonzero), max(nonzero)
    # A 50x year-on-year jump in a standard financial statement is more likely
    # to be a shifted/concatenated OCR column than a real comparable value.
    return smallest > 0 and largest / smallest <= 50


def merge_financial_candidates(candidates: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    year_quality: dict[tuple[str, str], float] = {}
    for candidate in candidates:
        key = candidate.get("key")
        if not key:
            continue
        unit = candidate.get("unit")
        source_type = str(candidate.get("source_type") or "")
        parsed_values: dict[str, float] = {}
        for year, raw in candidate.get("values", {}).items():
            parsed = parse_number(raw)
            if re.fullmatch(r"(?:19|20)\d{2}", str(year)) and parsed is not None:
                parsed_values[str(year)] = parsed
        if not parsed_values or not _candidate_values_are_consistent(parsed_values):
            continue
        parsed_values, unit = _normalize_monetary_values(parsed_values, unit)
        # A single value inferred from free OCR text is too easy to misalign.
        if source_type in {"pdf_text", "ocr_coordinate_table"} and len(parsed_values) < 2 and float(candidate.get("confidence", 0)) < 0.9:
            continue
        quality = _candidate_quality(candidate)
        current = merged.setdefault(key, {
            "key": key,
            "name": DISPLAY_NAMES.get(key, key),
            "unit": unit,
            "values": {},
            "source_pages": [],
            "confidence": 0.0,
            "source_type": candidate.get("source_type"),
        })
        accepted_any = False
        for year_text, parsed in parsed_values.items():
            if not _plausible_financial_value(parsed, unit or current.get("unit")):
                continue
            slot = (str(key), year_text)
            if quality >= year_quality.get(slot, -1):
                current["values"][year_text] = parsed
                year_quality[slot] = quality
                accepted_any = True
        if accepted_any:
            current["source_pages"] = sorted(set(current["source_pages"] + [p for p in candidate.get("source_pages", []) if isinstance(p, int) and p > 0]))
            current["confidence"] = max(current["confidence"], min(1.0, float(candidate.get("confidence", 0.5))))
            if quality >= max((year_quality.get((str(key), y), -1) for y in current["values"]), default=-1):
                current["source_type"] = candidate.get("source_type") or current.get("source_type")
                if unit:
                    current["unit"] = unit

    # Remove isolated catastrophic year values that are still numerically below
    # the global ceiling but differ by more than two orders of magnitude from
    # the same line in adjacent periods. This is a common OCR column-shift sign.
    for item in merged.values():
        values = item.get("values", {})
        if len(values) < 2:
            continue
        nonzero = [abs(float(value)) for value in values.values() if value not in (None, 0)]
        if len(nonzero) < 2:
            continue
        smallest = min(nonzero)
        largest = max(nonzero)
        if smallest > 0 and largest / smallest > 100:
            bad_years = [year for year, value in values.items() if abs(float(value)) == largest]
            for year in bad_years:
                values.pop(year, None)
            item["confidence"] = min(float(item.get("confidence", 0.5)), 0.75)
            item.setdefault("validation_warnings", []).append("Удалено значение с аномальным межгодовым отклонением более чем в 100 раз.")
    return {key: item for key, item in merged.items() if item.get("values")}


def derive_financial_metrics(metrics: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Add mechanically derivable rows without asking the language model.

    The derivations increase analytical coverage when OCR misses a subtotal but
    extracts its components. Every derived row keeps the source pages and the
    lower of the component confidence scores.
    """
    def values(key: str) -> dict[str, float]:
        return {str(y): float(v) for y, v in metrics.get(key, {}).get("values", {}).items() if parse_number(v) is not None}

    def add_metric(target: str, name: str, unit: str | None, out: dict[str, float], sources: list[str], formula: str) -> None:
        if target in metrics or not out:
            return
        pages: list[int] = []
        confidences: list[float] = []
        for source in sources:
            pages.extend(metrics.get(source, {}).get("source_pages", []))
            confidences.append(float(metrics.get(source, {}).get("confidence", 0.72)))
        metrics[target] = {
            "key": target,
            "name": name,
            "unit": unit,
            "values": out,
            "source_pages": sorted(set(p for p in pages if isinstance(p, int))),
            "confidence": min(confidences) if confidences else 0.72,
            "source_type": "derived_from_verified_rows",
            "derived": True,
            "derivation_formula": formula,
        }

    def add_sum(target: str, name: str, left: str, right: str) -> None:
        lvals, rvals = values(left), values(right)
        out = {year: lvals[year] + rvals[year] for year in sorted(set(lvals) & set(rvals))}
        add_metric(target, name, metrics.get(left, {}).get("unit") or metrics.get(right, {}).get("unit"), out, [left, right], f"{left} + {right}")

    add_sum("assets", "Активы", "noncurrent_assets", "current_assets")
    add_sum("liabilities", "Обязательства", "longterm_liabilities", "current_liabilities")
    add_sum("total_debt", "Заемные средства, всего", "longterm_debt_component", "shortterm_debt_component")

    if "equity" not in metrics:
        assets, liabilities = values("assets"), values("liabilities")
        out = {year: assets[year] - liabilities[year] for year in sorted(set(assets) & set(liabilities))}
        add_metric("equity", "Собственный капитал", metrics.get("assets", {}).get("unit"), out, ["assets", "liabilities"], "Активы − Обязательства")

    if "gross_profit" not in metrics:
        revenue, cogs = values("revenue"), values("cogs")
        out = {year: revenue[year] + cogs[year] for year in sorted(set(revenue) & set(cogs))}
        add_metric("gross_profit", "Валовая прибыль", metrics.get("revenue", {}).get("unit"), out, ["revenue", "cogs"], "Выручка + Себестоимость (со знаком минус)")

    if "operating_profit" not in metrics:
        gross = values("gross_profit")
        commercial = values("commercial_expenses")
        administrative = values("administrative_expenses")
        years = sorted(set(gross) & set(commercial) & set(administrative))
        out = {year: gross[year] - abs(commercial[year]) - abs(administrative[year]) for year in years}
        add_metric("operating_profit", "Прибыль от продаж", metrics.get("gross_profit", {}).get("unit"), out, ["gross_profit", "commercial_expenses", "administrative_expenses"], "Валовая прибыль − Коммерческие расходы − Управленческие расходы")

    # The public UI does not need component-only technical rows after total debt
    # has been derived, but the source pages remain attached to the total.
    for key in ("longterm_debt_component", "shortterm_debt_component"):
        metrics.pop(key, None)
    return metrics

def deduplicate_operational_metrics(items: Iterable[dict[str, Any]], limit: int = 250) -> list[dict[str, Any]]:
    """Keep only readable, plausible operational KPIs.

    Raw OCR labels are deliberately rejected. The system should prefer an
    honest absence of a KPI over a polished table containing corrupted words.
    """
    seen: set[tuple[str, tuple[tuple[str, float], ...]]] = set()
    output = []
    noise_terms = (
        "наименование показателя", "единица измерения", "пояснения код",
        "2025за", "2024за", "строка строк", "графа граф",
    )
    for item in items:
        name = re.sub(r"\s+", " ", str(item.get("name", ""))).strip(" .:;|-")
        normalized_name = normalize_label(name)
        if not normalized_name or any(term in normalized_name for term in noise_terms):
            continue
        words = re.findall(r"[А-Яа-яЁёA-Za-z]{3,}", name)
        cyrillic_words = [word for word in words if re.search(r"[А-Яа-яЁё]", word)]
        if len(words) < 2 or (cyrillic_words and len(cyrillic_words) / len(words) < 0.65):
            continue
        counts = defaultdict(int)
        for word in words:
            counts[word.lower()] += 1
        if counts and max(counts.values()) / len(words) > 0.25:
            continue
        confidence = float(item.get("confidence", 0.5) or 0.5)
        if str(item.get("source_type", "")).startswith("ocr") and confidence < 0.9:
            continue
        values = {str(k): parse_number(v) for k, v in item.get("values", {}).items()}
        values = {k: v for k, v in values.items() if v is not None and math.isfinite(v)}
        if len(values) < 1 or not _candidate_values_are_consistent(values):
            continue
        key = (normalized_name, tuple(sorted(values.items())))
        if key in seen:
            continue
        seen.add(key)
        clean = dict(item)
        clean["name"] = name
        clean["values"] = values
        clean["category"] = clean.get("category") or classify_operational(name)
        output.append(clean)
        if len(output) >= limit:
            break
    return output

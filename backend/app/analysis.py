from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Callable

from .ai import map_reduce_analysis
from .config import RESULT_DIR, settings
from .financial import (
    build_risk_flags,
    calculate_ratios,
    deduplicate_operational_metrics,
    derive_financial_metrics,
    merge_financial_candidates,
    normalize_label,
    score_analysis,
)
from .parsers import parse_document
from .store import store
from .canonical import canonicalize_metrics
from .validation import validate_model
from .trends import calculate_trends
from .vision import recover_statement_candidates

ProgressCallback = Callable[[int, str], None]
logger = logging.getLogger("finsight.analysis")

STATEMENT_CORE_KEYS = {
    "assets", "equity", "current_assets", "current_liabilities",
    "revenue", "net_profit", "operating_cash_flow",
}


def _reconcile_balance_identities(metrics: dict[str, dict[str, Any]], tolerance: float = 0.02) -> dict[str, dict[str, Any]]:
    """Repair one inconsistent balance aggregate only when two totals agree.

    This is not a company-specific plug.  The balance exposes the same total in
    three independent ways: reported assets, asset sections, and financing
    sections.  When two agree and the third does not, the odd aggregate (or its
    least reliable component) is identifiable.  The original OCR value remains
    in provenance and the repaired row is explicitly marked as derived.
    """
    groups = {
        "assets": ["assets"],
        "asset_sections": ["noncurrent_assets", "current_assets"],
        "financing_sections": ["equity", "longterm_liabilities", "current_liabilities"],
    }
    years = sorted({str(year) for item in metrics.values() for year in item.get("values", {})})

    def value(key: str, year: str) -> float | None:
        try:
            return float(metrics[key]["values"][year])
        except (KeyError, TypeError, ValueError):
            return None

    def total(keys: list[str], year: str) -> float | None:
        values = [value(key, year) for key in keys]
        return sum(values) if values and all(item is not None for item in values) else None

    def agrees(left: float | None, right: float | None) -> bool:
        if left is None or right is None:
            return False
        return abs(left - right) <= max(abs(left), abs(right), 1.0) * tolerance

    def reliability(key: str) -> float:
        item = metrics.get(key, {})
        score = float(item.get("confidence", 0.5) or 0.5)
        if item.get("row_code"):
            score += 0.12
        if item.get("source_type") in {"spreadsheet_table", "pdf_table", "ifrs_primary_statement"}:
            score += 0.08
        return score

    def replace(key: str, year: str, repaired: float, equation: str, source_keys: list[str]) -> None:
        if key not in metrics or (key != "equity" and repaired < 0):
            return
        item = metrics[key]
        original = value(key, year)
        if original is None or agrees(original, repaired):
            return
        item.setdefault("original_extracted_values", {})[year] = original
        item["values"][year] = repaired
        item["derived"] = True
        item["reconciled"] = True
        item["source_type"] = "reconciled_from_accounting_identity"
        item["derivation_formula"] = equation
        item["confidence"] = round(min(
            [float(metrics.get(source, {}).get("confidence", 0.72) or 0.72) for source in source_keys] or [0.72]
        ) * 0.90, 2)
        item.setdefault("validation_warnings", []).append(
            f"Значение за {year} восстановлено по балансовому равенству; исходное распознавание: {original:g}."
        )
        item.setdefault("provenance", []).append({
            "page": None, "row": equation, "row_code": item.get("row_code"),
            "extraction_method": "reconciled_from_accounting_identity",
            "confidence": item["confidence"], "source_keys": source_keys,
            "original_value": original,
        })

    for year in years:
        assets = total(groups["assets"], year)
        asset_sections = total(groups["asset_sections"], year)
        financing_sections = total(groups["financing_sections"], year)
        if agrees(asset_sections, financing_sections) and not agrees(assets, asset_sections):
            assert asset_sections is not None
            replace("assets", year, asset_sections, "Внеоборотные активы + Оборотные активы", groups["asset_sections"])
        elif agrees(assets, financing_sections) and not agrees(asset_sections, assets):
            assert assets is not None
            suspect = min(groups["asset_sections"], key=reliability)
            other = next(key for key in groups["asset_sections"] if key != suspect)
            other_value = value(other, year)
            if other_value is not None:
                replace(suspect, year, assets - other_value, f"Активы − {metrics[other].get('name', other)}", ["assets", other])
        elif agrees(assets, asset_sections) and not agrees(financing_sections, assets):
            assert assets is not None
            suspect = min(groups["financing_sections"], key=reliability)
            others = [key for key in groups["financing_sections"] if key != suspect]
            other_total = total(others, year)
            if other_total is not None:
                replace(suspect, year, assets - other_total, "Активы − прочие разделы пассива", ["assets", *others])
    return metrics


def _evaluate_financial_candidates(candidates: list[dict[str, Any]], standard: str) -> dict[str, Any]:
    """Build and score one isolated statement interpretation.

    RAS and IFRS candidates are never mixed during this pass. That prevents a
    plausible note-table value from repairing (and thereby hiding) a broken
    primary statement. The selected branch still has to pass canonical
    validation before its rows become available to ratios and AI.
    """
    merged = _reconcile_balance_identities(derive_financial_metrics(merge_financial_candidates(candidates)))
    model = canonicalize_metrics(merged)
    validation = validate_model(model)
    valid_metrics = validation.get("valid_metrics", {})
    core_coverage = len(STATEMENT_CORE_KEYS & set(valid_metrics))
    tested = [check for check in validation.get("checks", []) if check.get("status") != "not_tested"]
    passed = sum(check.get("status") == "passed" for check in tested)
    failed = sum(check.get("status") == "failed" for check in tested)
    coded_rows = sum(bool(item.get("row_code")) for item in valid_metrics.values())
    primary_rows = sum(
        str(item.get("source_type") or "").startswith(("ras_", "ifrs_primary"))
        for item in valid_metrics.values()
    )
    score = (
        len(valid_metrics) * 3
        + core_coverage * 12
        + passed * 8
        + coded_rows * (2 if standard == "ras" else 0)
        + primary_rows
        - failed * 35
    )
    reliable = len(valid_metrics) >= 8 and core_coverage >= 3 and failed == 0
    return {
        "standard": standard,
        "score": score,
        "reliable": reliable,
        "core_coverage": core_coverage,
        "valid_count": len(valid_metrics),
        "passed_checks": passed,
        "failed_checks": failed,
        "model": model,
        "validation": validation,
    }


def _select_financial_model(parsed: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any], str | None, dict[str, Any]]:
    branches = parsed.get("candidate_branches") or {}
    evaluations = [
        _evaluate_financial_candidates(list(candidates or []), standard)
        for standard, candidates in branches.items()
        if standard in {"ras", "ifrs"} and candidates
    ]
    reliable = [item for item in evaluations if item["reliable"]]
    selected = max(reliable, key=lambda item: item["score"], default=None)
    if selected is None:
        selected = _evaluate_financial_candidates(list(parsed.get("financial_candidates") or []), "generic")

    validation = dict(selected["validation"])
    financial_metrics = validation.pop("valid_metrics", {})
    diagnostics = {
        item["standard"]: {
            "score": item["score"],
            "reliable": item["reliable"],
            "valid_metric_count": item["valid_count"],
            "core_coverage": item["core_coverage"],
            "passed_checks": item["passed_checks"],
            "failed_checks": item["failed_checks"],
        }
        for item in evaluations
    }
    return financial_metrics, selected["model"], validation, (selected["standard"] if selected["standard"] in {"ras", "ifrs"} else None), diagnostics


def _top_metric_sentences(metrics: list[dict[str, Any]], limit: int = 8) -> list[str]:
    output = []
    for metric in metrics:
        years = sorted(metric.get("values", {}).keys())
        if len(years) >= 2:
            first, last = years[-2], years[-1]
            a, b = metric["values"].get(first), metric["values"].get(last)
            if a is not None and b is not None and a != 0:
                change = (b - a) / abs(a) * 100
                direction = "вырос" if change > 0 else "снизился"
                output.append(
                    f"{metric['name']}: показатель {direction} на {abs(change):.1f}% — с {a:g} в {first} году до {b:g} в {last} году"
                    + (f" {metric.get('unit')}" if metric.get("unit") else "")
                    + (f" (стр. {metric.get('source_pages', ['?'])[0]})" if metric.get("source_pages") else "")
                )
        if len(output) >= limit:
            break
    return output


def _metric_value(result: dict[str, Any], key: str, year: str | None = None) -> float | None:
    metric = (result.get("financial_metrics") or {}).get(key, {})
    values = metric.get("values", {})
    if not values:
        return None
    if year is None:
        years = sorted((str(item) for item in values if str(item).isdigit()), key=int)
        year = years[-1] if years else None
    value = values.get(str(year)) if year is not None else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / abs(previous) * 100


def _ratio_map(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("key")): item for item in result.get("ratios", []) if item.get("key")}


def _is_ras_result(result: dict[str, Any]) -> bool:
    metadata = result.get("metadata", {})
    descriptor = " ".join(str(metadata.get(key) or "") for key in (
        "document_type", "accounting_standard", "reporting_standard", "filename",
    )).lower()
    coded_rows = sum(1 for item in (result.get("financial_metrics") or {}).values() if item.get("row_code"))
    return metadata.get("document_type") in {"ras_financial_statements", "bank_ras_financial_statements"} or "рсбу" in descriptor or "рпбу" in descriptor or coded_rows >= 8


def _company_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    stem = Path(filename).stem
    match = re.search(r"\b(ПАО|АО|ООО)\s+[«\"]?([A-ZА-ЯЁ0-9][A-ZА-ЯЁa-zа-яё0-9 .&_-]{1,80})", stem)
    if not match:
        return None
    name = re.split(r"\s+(?:РСБУ|МСФО|отчетность|отчет|20\d{2})\b", match.group(2), maxsplit=1, flags=re.I)[0]
    name = name.strip(' «»"_-')
    return f"{match.group(1)} «{name}»" if name else None


def _direction_sentence(name: str, current: float | None, previous: float | None, unit: str = "") -> str | None:
    change = _pct_change(current, previous)
    if change is None:
        return None
    direction = "вырос" if change > 0 else "снизился"
    return f"{name} {direction} на {abs(change):.1f}% по сравнению с предыдущим периодом."


def _operational_direction_items(metrics: list[dict[str, Any]], limit: int = 8) -> tuple[list[str], list[str], list[str]]:
    """Turn verified multi-year operational KPIs into conservative conclusions."""
    strengths: list[str] = []
    weaknesses: list[str] = []
    observations: list[str] = []
    negative_when_higher = (
        "выброс", "травм", "пострадав", "леталь", "сжиган", "загрязнен",
        "авар", "отход", "потер", "расход воды",
    )
    positive_when_higher = (
        "добыч", "переработ", "производ", "реализац", "продаж", "запас",
        "мощност", "выработ", "экономия", "поступлен",
    )
    ranked: list[tuple[float, str, bool | None]] = []
    for metric in metrics:
        years = sorted((str(y) for y in metric.get("values", {}) if str(y).isdigit()), key=int)
        if len(years) < 2:
            continue
        prev, cur = metric["values"].get(years[-2]), metric["values"].get(years[-1])
        change = _pct_change(float(cur) if cur is not None else None, float(prev) if prev is not None else None)
        if change is None or abs(change) < 1:
            continue
        name = str(metric.get("name", "Показатель")).strip()
        normalized = name.lower().replace("ё", "е")
        direction_good: bool | None = None
        if any(token in normalized for token in negative_when_higher):
            direction_good = change < 0
        elif any(token in normalized for token in positive_when_higher):
            direction_good = change > 0
        sentence = f"{name}: {'рост' if change > 0 else 'снижение'} на {abs(change):.1f}% год к году."
        ranked.append((abs(change), sentence, direction_good))
    for _magnitude, sentence, good in sorted(ranked, key=lambda x: x[0], reverse=True)[:limit]:
        observations.append(sentence)
        if good is True:
            strengths.append(sentence)
        elif good is False:
            weaknesses.append(sentence)
    return strengths, weaknesses, observations


def _format_amount(value: float | None, unit: str | None = "тыс. руб.") -> str:
    if value is None:
        return "—"
    normalized = (unit or "").lower()
    if "тыс" in normalized and abs(value) >= 1_000_000:
        number = f"{value / 1_000_000:,.1f}".replace(",", " ").replace(".", ",")
        return f"{number} млрд руб"
    if "тыс" in normalized and abs(value) >= 1_000:
        number = f"{value / 1_000:,.1f}".replace(",", " ").replace(".", ",")
        return f"{number} млн руб"
    number = f"{value:,.0f}".replace(",", " ")
    return f"{number} {(unit or '').rstrip('.')}".strip()


def _format_percent(value: float) -> str:
    return f"{value:.1f}".replace(".", ",").replace("-", "−") + "%"


def _format_decimal(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _ratio_sentence(item: dict[str, Any]) -> str | None:
    if item.get("status") == "na" or item.get("value") is None:
        return None
    name = item.get("name", item.get("key", "Коэффициент"))
    return f"{name}: {item.get('display')} — {item.get('explanation', '').rstrip('.').lower()}."


def fallback_analysis(result: dict[str, Any]) -> dict[str, Any]:
    """Create a complete analyst-grade baseline before any LLM call.

    The baseline is deliberately substantive: the external model edits and
    prioritizes this report, but can never replace it with a shorter or weaker
    answer. Only normalized rows, code-calculated ratios and verified
    disclosures are used.
    """
    metadata = result.get("metadata", {})
    metrics = result.get("financial_metrics", {})
    ratios = result.get("ratios", [])
    ratio_map = _ratio_map(result)
    risks = result.get("risk_flags", [])
    limitations = list(result.get("limitations", []))
    operational_metrics = result.get("operational_metrics", [])
    years = sorted({str(year) for item in metrics.values() for year in item.get("values", {}) if str(year).isdigit()}, key=int)
    current_year = years[-1] if years else None
    previous_year = years[-2] if len(years) > 1 else None
    company = metadata.get("company") or "компании"
    is_ras = _is_ras_result(result)
    is_ifrs = metadata.get("document_type") == "ifrs_financial_statements" or metadata.get("accounting_standard") == "МСФО"

    def mv(key: str, year: str | None = None) -> float | None:
        return _metric_value(result, key, year)

    def rv(key: str) -> float | None:
        value = ratio_map.get(key, {}).get("value")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    is_bank_profile = metadata.get("financial_institution_profile") == "credit_organization"
    if is_bank_profile:
        assets_now, assets_prev = mv("assets", current_year), mv("assets", previous_year)
        loans_now, loans_prev = mv("bank_customer_loans", current_year), mv("bank_customer_loans", previous_year)
        funds_now, funds_prev = mv("bank_customer_funds", current_year), mv("bank_customer_funds", previous_year)
        nii_now, nii_prev = mv("bank_net_interest_income", current_year), mv("bank_net_interest_income", previous_year)
        fee_now, fee_prev = mv("bank_fee_income", current_year), mv("bank_fee_income", previous_year)
        profit_now, profit_prev = mv("net_profit", current_year), mv("net_profit", previous_year)
        assets_change = _pct_change(assets_now, assets_prev)
        loans_change = _pct_change(loans_now, loans_prev)
        funds_change = _pct_change(funds_now, funds_prev)
        nii_change = _pct_change(nii_now, nii_prev)
        fee_change = _pct_change(fee_now, fee_prev)
        profit_change = _pct_change(profit_now, profit_prev)

        summary = [f"Проведен анализ отдельной отчетности кредитной организации {company} по формам Банка России за {current_year or 'последний доступный период'} год."]
        if assets_now is not None and assets_change is not None:
            summary.append(f"Активы составили {_format_amount(assets_now, metrics.get('assets', {}).get('unit'))} и {'выросли' if assets_change >= 0 else 'снизились'} на {_format_percent(abs(assets_change))} год к году.")
        if loans_change is not None and funds_change is not None:
            summary.append(f"Чистая ссудная задолженность изменилась на {_format_percent(loans_change)}, средства клиентов — на {_format_percent(funds_change)}; Loan-to-Deposit составляет {_format_decimal(rv('bank_loan_to_deposit')) if rv('bank_loan_to_deposit') is not None else 'н/д'}.")
        if nii_change is not None and fee_change is not None:
            summary.append(f"Чистые процентные доходы изменились на {_format_percent(nii_change)}, комиссионные доходы — на {_format_percent(fee_change)}.")
        if profit_now is not None and profit_change is not None:
            summary.append(f"Чистая прибыль {'выросла' if profit_change >= 0 else 'снизилась'} на {_format_percent(abs(profit_change))} — до {_format_amount(profit_now, metrics.get('net_profit', {}).get('unit'))}.")
        if rv("roa") is not None and rv("roe") is not None:
            summary.append(f"ROA составляет {_format_percent(rv('roa') * 100)}, ROE — {_format_percent(rv('roe') * 100)}, Cost-to-Income — {_format_percent(rv('bank_cost_to_income') * 100) if rv('bank_cost_to_income') is not None else 'н/д'}.")

        available = [item for item in ratios if item.get("status") != "na"]
        strengths = [_ratio_sentence(item) for item in available if item.get("status") == "good"]
        weaknesses = [_ratio_sentence(item) for item in available if item.get("status") in {"warn", "bad"}]
        strengths = [item for item in strengths if item][:5]
        weaknesses = [item for item in weaknesses if item][:5]
        if not weaknesses:
            weaknesses = ["Критические отклонения среди рассчитанных банковских коэффициентов не выявлены; вывод ограничен публичными формами 0409806 и 0409807."]

        risk_texts = [f"{item['title']}: {item['reason']}" for item in risks[:5]]
        if not risk_texts:
            risk_texts = ["Существенные автоматические риск-флаги по проверенным банковским показателям не выявлены."]
        actions = [
            "Сопоставить динамику кредитного портфеля и клиентского фондирования с внутренними лимитами ликвидности и концентрации.",
            "Выполнить факторный анализ чистого процентного дохода: объемы активов и обязательств, ставки фондирования, доходность размещения и стоимость риска.",
            "Контролировать Cost-to-Income и комиссионные доходы в ежемесячном управленческом контуре с владельцами и порогами отклонений.",
            "Сверить балансовый Equity/Assets с регуляторными нормативами достаточности капитала формы 0409813; балансовое соотношение не заменяет Н1.0, Н1.1 и Н1.2.",
        ]
        strategic = []
        if loans_change is not None and funds_change is not None:
            strategic.append(f"Кредитный портфель изменился на {_format_percent(loans_change)} при изменении средств клиентов на {_format_percent(funds_change)}; разница темпов определяет давление на структуру фондирования.")
        if nii_change is not None and profit_change is not None:
            strategic.append(f"Чистые процентные доходы изменились на {_format_percent(nii_change)}, чистая прибыль — на {_format_percent(profit_change)}; расхождение требует анализа резервов, комиссий, операционных расходов и налога.")
        if rv("bank_credit_loss_to_loans") is not None:
            strategic.append(f"Нагрузка изменения резервов на среднюю чистую ссудную задолженность составляет {_format_percent(rv('bank_credit_loss_to_loans') * 100)}; показатель следует сопоставлять с качеством портфеля и покрытием проблемной задолженности.")
        limitations.append("Анализ выполнен по публичным формам Банка России 0409806 и 0409807 отдельной кредитной организации; он не заменяет анализ МСФО группы и регуляторных нормативов достаточности капитала и ликвидности.")
        return {
            "mode": "deterministic_bank_model_v341",
            "executive_summary": " ".join(summary[:7]),
            "strengths": strengths or ["Положительные выводы ограничены составом проверенных банковских строк."],
            "weaknesses": weaknesses,
            "risks": risk_texts,
            "management_actions": actions,
            "data_limitations": list(dict.fromkeys(limitations)),
            "strategic_observations": strategic or ["Стратегическая интерпретация ограничена составом публичных банковских форм."],
            "esg_observations": ["Формы банковской отчетности 0409806 и 0409807 не содержат достаточного набора ESG-метрик; для ESG-анализа нужен отдельный нефинансовый отчет."],
            "coverage": {"verified_metrics": len(metrics), "calculated_ratios": len(available), "years": years},
        }

    revenue_now, revenue_prev = mv("revenue", current_year), mv("revenue", previous_year)
    gross_now, gross_prev = mv("gross_profit", current_year), mv("gross_profit", previous_year)
    op_now, op_prev = mv("operating_profit", current_year), mv("operating_profit", previous_year)
    profit_now, profit_prev = mv("net_profit", current_year), mv("net_profit", previous_year)
    ocf_now, ocf_prev = mv("operating_cash_flow", current_year), mv("operating_cash_flow", previous_year)
    assets_now, assets_prev = mv("assets", current_year), mv("assets", previous_year)
    current_assets_now, current_assets_prev = mv("current_assets", current_year), mv("current_assets", previous_year)
    current_liab_now, current_liab_prev = mv("current_liabilities", current_year), mv("current_liabilities", previous_year)
    cash_now, cash_prev = mv("cash", current_year), mv("cash", previous_year)
    equity_now, equity_prev = mv("equity", current_year), mv("equity", previous_year)

    revenue_change = _pct_change(revenue_now, revenue_prev)
    gross_change = _pct_change(gross_now, gross_prev)
    op_change = _pct_change(op_now, op_prev)
    profit_change = _pct_change(profit_now, profit_prev)
    ocf_change = _pct_change(ocf_now, ocf_prev)
    assets_change = _pct_change(assets_now, assets_prev)
    current_assets_change = _pct_change(current_assets_now, current_assets_prev)
    current_liab_change = _pct_change(current_liab_now, current_liab_prev)
    cash_change = _pct_change(cash_now, cash_prev)
    equity_change = _pct_change(equity_now, equity_prev)

    scope = (
        "отдельной бухгалтерской отчетности по РСБУ" if is_ras
        else "консолидированной финансовой отчетности по МСФО" if is_ifrs
        else "загруженного корпоративного документа"
    )
    summary: list[str] = [f"Проведен анализ {scope} {company} за {current_year + ' год' if current_year else 'последний доступный период'}." ]
    if revenue_change is not None:
        summary.append(f"Выручка {'выросла' if revenue_change > 0 else 'снизилась'} на {_format_percent(abs(revenue_change))} — до {_format_amount(revenue_now, metrics.get('revenue', {}).get('unit'))}.")
    if op_change is not None:
        op_margin_value = rv("operating_margin")
        op_margin_text = f", операционная маржа составила {_format_percent(op_margin_value * 100)}" if op_margin_value is not None else ""
        summary.append(f"Прибыль от продаж {'увеличилась' if op_change > 0 else 'сократилась'} на {_format_percent(abs(op_change))}{op_margin_text}.")
    if profit_change is not None:
        summary.append(f"Чистая прибыль {'увеличилась' if profit_change > 0 else 'снизилась'} на {_format_percent(abs(profit_change))} — до {_format_amount(profit_now, metrics.get('net_profit', {}).get('unit'))}.")
    if rv("current_ratio") is not None:
        summary.append(f"Текущая ликвидность оценивается коэффициентом {_format_decimal(rv('current_ratio'))}; " + ("оборотные активы покрывают краткосрочные обязательства." if rv('current_ratio') >= 1 else "оборотные активы не покрывают краткосрочные обязательства полностью."))
    if rv("debt_equity") is not None:
        summary.append(f"Соотношение долга и капитала составляет {_format_decimal(rv('debt_equity'))}, а доля собственного капитала в активах — {_format_percent(rv('equity_ratio') * 100)}." if rv("equity_ratio") is not None else f"Соотношение долга и капитала составляет {_format_decimal(rv('debt_equity'))}.")
    if ocf_now is not None:
        summary.append(f"Операционный денежный поток остается {'положительным' if ocf_now > 0 else 'отрицательным'} и составляет {_format_amount(ocf_now, metrics.get('operating_cash_flow', {}).get('unit'))}.")
    if risks:
        summary.append(f"Ключевой контур риска: {risks[0].get('title', 'существенные финансовые риски').lower()}.")
    executive_summary = " ".join(summary[:7])

    strengths: list[str] = []
    weaknesses: list[str] = []
    strategic: list[str] = []

    # Consolidate related figures into conclusions instead of producing one
    # bullet for every metric. This is also the quality fallback shown when an
    # external model is temporarily unavailable.
    margin_parts = []
    for key, label in (("gross_margin", "валовая"), ("operating_margin", "операционная"), ("net_margin", "чистая")):
        if rv(key) is not None:
            margin_parts.append(f"{label} маржа {_format_percent(rv(key) * 100)}")
    return_parts = []
    for key, label in (("roa", "ROA"), ("roe", "ROE")):
        if rv(key) is not None:
            return_parts.append(f"{label} {_format_percent(rv(key) * 100)}")
    if margin_parts:
        text = "Бизнес сохраняет положительную маржинальность: " + ", ".join(margin_parts)
        if return_parts:
            text += "; " + ", ".join(return_parts) + " подтверждают положительную отдачу на капитал"
        strengths.append(text + ".")

    cr, qr, cash_ratio = rv("current_ratio"), rv("quick_ratio"), rv("cash_ratio")
    if cr is not None:
        liquidity = f"Текущая ликвидность { _format_decimal(cr) }"
        if qr is not None:
            liquidity += f", быстрая — {_format_decimal(qr)}"
        if cash_ratio is not None:
            liquidity += f", абсолютная — {_format_decimal(cash_ratio)}"
        liquidity += "; " + ("оборотные активы покрывают краткосрочные обязательства" if cr >= 1 else "краткосрочные обязательства не покрыты оборотными активами полностью") + "."
        (strengths if cr >= 1 and (qr is None or qr >= .8) else weaknesses).append(liquidity)

    debt_equity, equity_ratio, coverage = rv("debt_equity"), rv("equity_ratio"), rv("interest_coverage")
    if debt_equity is not None:
        capital = f"Финансовый рычаг оценивается по Debt/Equity {_format_decimal(debt_equity)}"
        if equity_ratio is not None:
            capital += f" при доле собственного капитала {_format_percent(equity_ratio * 100)}"
        if coverage is not None:
            capital += f"; покрытие процентов {_format_decimal(coverage)}"
        capital += ", что " + ("указывает на умеренную зависимость от заемного финансирования" if debt_equity <= 1.5 else "фиксирует повышенную зависимость от заемного финансирования") + "."
        (strengths if debt_equity <= 1.5 and (coverage is None or coverage >= 2) else weaknesses).append(capital)

    declining = [("выручка", revenue_change), ("валовая прибыль", gross_change), ("прибыль от продаж", op_change), ("чистая прибыль", profit_change)]
    declining = [(name, change) for name, change in declining if change is not None and change < 0]
    growing = [(name, change) for name, change in (("выручка", revenue_change), ("прибыль от продаж", op_change), ("чистая прибыль", profit_change)) if change is not None and change > 0]
    if declining:
        weaknesses.append("Отрицательная динамика затрагивает " + ", ".join(f"{name} ({_format_percent(change)})" for name, change in declining) + "; снижение прибыли опережающим темпом сигнализирует об усилении давления на финансовый результат.")
    elif growing:
        strengths.append("Положительная динамика охватывает " + ", ".join(f"{name} (+{_format_percent(change)})" for name, change in growing) + ", что подтверждает рост масштаба и конечного результата.")

    cash_conversion = rv("cash_conversion")
    if ocf_now is not None:
        cash_text = f"Операционный денежный поток {_format_amount(ocf_now, metrics.get('operating_cash_flow', {}).get('unit'))}"
        if cash_conversion is not None:
            cash_text += f" и конверсия прибыли {_format_decimal(cash_conversion)}"
        cash_text += "; " + ("учетный результат подкреплен положительным денежным потоком" if ocf_now > 0 and (cash_conversion is None or cash_conversion >= .8) else "качество денежной конверсии прибыли требует внимания") + "."
        (strengths if ocf_now > 0 and (cash_conversion is None or cash_conversion >= .8) else weaknesses).append(cash_text)
    if ocf_change is not None and ocf_change < 0:
        weaknesses.append(f"Операционный денежный поток снизился на {_format_percent(abs(ocf_change))}" + (f", а остаток денежных средств сократился на {_format_percent(abs(cash_change))}" if cash_change is not None and cash_change < 0 else "") + "; запас финансовой гибкости сужается.")

    if current_assets_change is not None and current_liab_change is not None:
        if current_assets_change < 0 < current_liab_change:
            strategic.append("Оборотные активы сокращаются одновременно с ростом краткосрочных обязательств, поэтому давление на ликвидность имеет структурный, а не только точечный характер.")
    if op_change is not None and profit_change is not None and op_change > 0 > profit_change:
        strategic.append("Рост прибыли от продаж не трансформировался в рост чистой прибыли; основной негативный эффект сформирован ниже операционной строки — в финансовых, прочих или налоговых статьях.")
    elif revenue_change is not None and profit_change is not None and revenue_change > 0 > profit_change:
        strategic.append("Рост масштаба бизнеса сопровождается снижением конечного финансового результата, что требует факторного анализа прочих расходов, финансового результата и налогообложения.")
    if ocf_change is not None and profit_change is not None:
        strategic.append(f"Операционный денежный поток изменился на {_format_percent(ocf_change)}, чистая прибыль — на {_format_percent(profit_change)}; расхождение темпов нужно анализировать через оборотный капитал, налоговые платежи и неденежные статьи.")
    if assets_change is not None and rv("asset_turnover") is not None:
        strategic.append(f"При изменении активов на {_format_percent(assets_change)} оборачиваемость активов составляет {_format_decimal(rv('asset_turnover'))}, что характеризует эффективность использования имущественной базы.")

    if not metrics and operational_metrics:
        op_strengths, op_weaknesses, op_observations = _operational_direction_items(operational_metrics, 8)
        strengths.extend(op_strengths)
        weaknesses.extend(op_weaknesses)
        strategic.extend(op_observations)

    available_ratios = [item for item in ratios if item.get("status") != "na"]
    if not strengths:
        good_ratios = [_ratio_sentence(item) for item in available_ratios if item.get("status") == "good"]
        strengths.extend([item for item in good_ratios if item][:4])
    if not weaknesses:
        bad_ratios = [_ratio_sentence(item) for item in available_ratios if item.get("status") in {"bad", "warn"}]
        weaknesses.extend([item for item in bad_ratios if item][:4])
    if not strengths:
        strengths.append("Положительные выводы ограничены набором надежно извлеченных строк; приложение не подменяет отсутствующие показатели предположениями.")
    if not weaknesses:
        weaknesses.append("Среди доступных коэффициентов критические отрицательные отклонения не выявлены; вывод требует проверки полноты распознанных форм.")

    financial_codes = {"negative_equity", "net_loss", "negative_ocf", "low_liquidity", "high_leverage", "revenue_decline", "profit_decline"}
    financial_risks = [item for item in risks if item.get("code") in financial_codes]
    disclosure_risks = [item for item in risks if item.get("code") not in financial_codes]
    risk_texts = [f"{item['title']}: {item['reason']}" for item in financial_risks[:3]]
    if disclosure_risks:
        titles = ", ".join(str(item.get("title", "риск")).lower() for item in disclosure_risks[:4])
        risk_texts.append(f"В текстовых раскрытиях затронуты {titles}; факт раскрытия не означает наступление риска, но требует оценки вероятности и финансового эффекта.")
    if not risk_texts:
        risk_texts = ["Существенные автоматические риск-флаги по проверенным финансовым данным не выявлены."]

    actions: list[str] = []
    if rv("current_ratio") is not None and rv("current_ratio") < 1:
        actions.append("Сформировать помесячный платежный календарь, определить пик краткосрочных погашений и установить минимальный резерв денежных средств.")
    if profit_change is not None and profit_change < 0:
        actions.append("Выполнить факторный мост от прибыли от продаж к чистой прибыли: проценты, прочие доходы и расходы, курсовые разницы и налог на прибыль.")
    if ocf_change is not None and ocf_change < 0:
        actions.append("Разложить снижение операционного денежного потока по изменениям оборотного капитала, налоговым платежам и расчетам с контрагентами.")
    if rv("debt_equity") is not None:
        actions.append("Провести стресс-тест долговой нагрузки и ликвидности при росте ставок, ухудшении курса и сокращении операционного денежного потока.")
    if any(item.get("severity") in {"critical", "high"} for item in risks):
        actions.append("Для риск-флагов высокой значимости определить владельцев риска, количественные лимиты, сценарии и контрольные индикаторы.")
    if len(actions) < 3:
        actions.append("Включить в ежемесячный мониторинг выручку, маржинальность, операционный денежный поток и оборотный капитал с порогами отклонений и назначенными владельцами.")

    if is_ras:
        esg = ["В формах бухгалтерской отчетности по РСБУ отсутствует достаточный набор ESG-метрик; ESG-анализ следует выполнять по годовому отчету или отчету об устойчивом развитии."]
        if "Отчетность по РСБУ отражает отдельное юридическое лицо и не заменяет консолидированные данные Группы по МСФО." not in limitations:
            limitations.append("Отчетность по РСБУ отражает отдельное юридическое лицо и не заменяет консолидированные данные Группы по МСФО.")
    else:
        esg = [item.get("text") for item in result.get("narrative", {}).get("esg", []) if item.get("text")][:5]
        if not esg:
            esg = ["Подтвержденных ESG-показателей в обработанном документе недостаточно для отдельного вывода."]

    audit = metadata.get("audit_opinion")
    if audit:
        strategic.append(f"Аудиторское мнение: {audit}. Оно подтверждает качество представления отчетности, но не устраняет бизнес-риски и неопределенность оценочных статей.")

    return {
        "mode": "deterministic_financial_model_v31",
        "executive_summary": executive_summary,
        "strengths": list(dict.fromkeys(strengths))[:5],
        "weaknesses": list(dict.fromkeys(weaknesses))[:5],
        "risks": list(dict.fromkeys(risk_texts))[:5],
        "management_actions": list(dict.fromkeys(actions))[:5],
        "data_limitations": limitations or ["Аналитика не заменяет аудит, профессиональное заключение и инвестиционную рекомендацию."],
        "strategic_observations": list(dict.fromkeys(strategic))[:4] or ["Стратегическая интерпретация ограничена составом подтвержденных финансовых форм."],
        "esg_observations": esg,
        "coverage": {
            "verified_metrics": len(metrics),
            "calculated_ratios": len(available_ratios),
            "years": years,
        },
    }


def _save_completed_result(document_id: str, result: dict[str, Any], stage: str = "Анализ завершен") -> dict[str, Any]:
    result_path = RESULT_DIR / f"{document_id}.json"
    store.write_result(result_path, result)
    store.update(
        document_id,
        status="completed",
        progress=100,
        stage=stage,
        company=result.get("metadata", {}).get("company"),
        document_type=result.get("metadata", {}).get("document_type"),
        reporting_year=result.get("metadata", {}).get("reporting_year"),
        result_path=str(result_path),
        ai_status=result.get("analysis", {}).get("mode", "deterministic_financial_model_v31"),
        error=None,
    )
    return result


def process_document(document_id: str, path: Path, progress: ProgressCallback) -> dict[str, Any]:
    parsed = parse_document(path, progress)
    record = store.get(document_id) or {}
    original_name = record.get("original_name")
    if original_name:
        parsed["metadata"]["filename"] = original_name
    if record.get("company"):
        parsed["metadata"]["company"] = record["company"]
    elif parsed["metadata"].get("document_type") == "spreadsheet_financial_data" and original_name:
        parsed["metadata"]["company"] = Path(original_name).stem

    progress(72, "Объединение, нормализация и проверка финансовой модели")
    financial_metrics, canonical_model, validation, selected_standard, branch_diagnostics = _select_financial_model(parsed)
    is_bank_profile = parsed.get("metadata", {}).get("financial_institution_profile") == "credit_organization"
    required_for_core_ratios = (
        {"assets", "liabilities", "equity", "bank_customer_loans", "bank_customer_funds", "bank_net_interest_income", "net_profit"}
        if is_bank_profile
        else {"assets", "equity", "current_assets", "current_liabilities", "revenue", "net_profit"}
    )
    needs_vision_recovery = (
        selected_standard is None
        or len(financial_metrics) < 12
        or not required_for_core_ratios.issubset(financial_metrics)
    )
    if (
        needs_vision_recovery
        and settings.enable_vision_recovery
        and settings.ai_api_key
        and path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
    ):
        progress(74, "AI ищет и перепроверяет сложные страницы основных форм")
        try:
            vision_standard, vision_candidates, vision_diagnostics = asyncio.run(
                recover_statement_candidates(path, parsed.get("pages", []), parsed["metadata"].get("reporting_year"))
            )
            parsed["metadata"]["vision_recovery"] = vision_diagnostics
            if not vision_standard and selected_standard:
                vision_standard = selected_standard
            if vision_standard and vision_candidates:
                existing = list((parsed.get("candidate_branches") or {}).get(vision_standard, []))
                parsed.setdefault("candidate_branches", {})[vision_standard] = [*existing, *vision_candidates]
                financial_metrics, canonical_model, validation, selected_standard, branch_diagnostics = _select_financial_model(parsed)
        except Exception as exc:
            logger.exception("vision recovery failed", extra={"document_id": document_id, "path": path.name})
            parsed["metadata"]["vision_recovery"] = {
                "status": "unavailable", "reason": type(exc).__name__, "message": str(exc)[:240],
            }
    parsed["metadata"].setdefault("standard_detection", {})["validated_selection"] = selected_standard
    parsed["metadata"]["standard_detection"]["validated_branches"] = branch_diagnostics
    parsed["metadata"]["financial_coverage"] = {
        "validated_metrics": len(financial_metrics),
        "core_ratio_inputs_found": sorted(required_for_core_ratios & set(financial_metrics)),
        "core_ratio_inputs_missing": sorted(required_for_core_ratios - set(financial_metrics)),
        "vision_recovery_requested": needs_vision_recovery,
    }
    filename_company = _company_from_filename(original_name)
    parsed_company = str(parsed["metadata"].get("company", "")).lower()
    if filename_company and (not record.get("company") or parsed_company in {"не определено", "ао «кэпт»"}):
        parsed["metadata"]["company"] = filename_company
    if selected_standard == "ras":
        if is_bank_profile:
            parsed["metadata"].update(
                document_type="bank_ras_financial_statements",
                accounting_standard="РПБУ / формы Банка России",
                reporting_scope="Отдельная кредитная организация",
            )
        else:
            parsed["metadata"].update(
                document_type="ras_financial_statements",
                accounting_standard="РСБУ",
                reporting_scope="Отдельное юридическое лицо",
            )
    elif selected_standard == "ifrs":
        parsed["metadata"].update(
            document_type="ifrs_financial_statements",
            accounting_standard="МСФО",
            reporting_scope="Консолидированная отчетность",
        )
    parsed["limitations"] = [
        item for item in parsed.get("limitations", [])
        if not (
            selected_standard == "ras" and "Основные формы МСФО" in item
            or selected_standard and "полного комплекта форм финансовой отчетности" in item
        )
    ]
    operational_metrics = deduplicate_operational_metrics(parsed["operational_metrics"])
    ratios = calculate_ratios(financial_metrics)
    risk_flags = build_risk_flags(financial_metrics, ratios, parsed["full_text"], parsed.get("pages"))
    score = score_analysis(ratios, risk_flags, parsed["metadata"], len(parsed["tables"]), len(operational_metrics))

    progress(82, "Формирование профессионального базового заключения")
    result = {
        "id": document_id,
        "metadata": parsed["metadata"],
        "financial_metrics": financial_metrics,
        "canonical_financial_model": canonical_model,
        "validation": validation,
        "trends": calculate_trends(financial_metrics),
        "operational_metrics": operational_metrics,
        "ratios": ratios,
        "risk_flags": risk_flags,
        "score": score,
        "limitations": parsed["limitations"],
        "headings": parsed["headings"],
        "tables": parsed["tables"][:180],
        "narrative": parsed["narrative"],
        "source": {"pages": parsed["pages"], "filename": parsed["metadata"]["filename"]},
    }
    result["analysis"] = fallback_analysis(result)

    if settings.auto_ai and settings.ai_api_key:
        progress(88, "AI формирует итоговый аналитический отчет")
        try:
            result["analysis"] = asyncio.run(map_reduce_analysis(result))
        except Exception as exc:
            # A high-quality deterministic report is kept; the user never sees
            # a blank or trivial answer when the external gateway fails.
            result["analysis"]["ai_error"] = str(exc)

    progress(97, "Сохранение результата")
    return _save_completed_result(document_id, result)


async def run_ai_for_result(document_id: str) -> dict[str, Any]:
    record = store.get(document_id)
    if not record or not record.get("result_path"):
        raise FileNotFoundError("Результат анализа не найден")
    result = store.read_result(record["result_path"])
    if not settings.ai_api_key:
        return {
            "ok": False,
            "mode": "deterministic_fallback",
            "message": "AI_API_KEY не настроен. Используется детерминированное резюме.",
            "analysis": result.get("analysis"),
        }
    store.update(document_id, ai_status="processing")
    try:
        ai_result = await map_reduce_analysis(result)
        result["analysis"] = ai_result
        store.write_result(Path(record["result_path"]), result)
        store.update(document_id, ai_status=ai_result.get("mode", "completed"))
        return {"ok": True, "analysis": ai_result}
    except Exception as exc:
        store.update(document_id, ai_status="error")
        raise RuntimeError(f"Ошибка AI API: {exc}") from exc

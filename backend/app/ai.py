from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import settings


SYSTEM_PROMPT = """Ты — ведущий финансовый аналитик уровня Big Four с практикой анализа РСБУ, ФСБУ и МСФО.

Твоя задача — превратить проверенную финансовую модель приложения в профессиональное аналитическое заключение для собственника, финансового директора или кредитного комитета.

Жесткие правила:
1. Используй только данные переданного JSON: нормализованные показатели, рассчитанные кодом коэффициенты, риск-флаги, аудиторские и иные проверенные раскрытия.
2. Не используй сырой OCR-текст, внешние знания о компании и неподтвержденные причины.
3. Не пересчитывай и не изменяй числа. Допускается объяснять экономический смысл и причинно-следственные связи между уже подтвержденными показателями.
4. Для РСБУ анализируй отдельное юридическое лицо и явно не смешивай его с консолидированной Группой по МСФО.
5. Не выдавай инвестиционных рекомендаций и не заменяй аудиторское заключение.
6. Не пиши общие фразы вроде «нужно больше данных», если в JSON есть достаточные показатели. Вместо этого подробно анализируй доступную динамику, ликвидность, рентабельность, долговую нагрузку и денежные потоки.
7. Executive summary должен содержать 5–7 законченных предложений: динамика выручки и прибыли, маржинальность, ликвидность, долговая нагрузка, денежные потоки и главный риск.
8. В каждом из разделов strengths, weaknesses, risks, management_actions и strategic_observations дай 4–7 конкретных пунктов, если данные это позволяют.
9. Каждый пункт — один аналитический вывод длиной до 45 слов. Не копируй таблицы и не повторяй один факт разными словами.
10. Верни строго JSON без Markdown:
{
  "executive_summary": "string",
  "strengths": ["string"],
  "weaknesses": ["string"],
  "risks": ["string"],
  "management_actions": ["string"],
  "data_limitations": ["string"],
  "strategic_observations": ["string"],
  "esg_observations": ["string"]
}
"""


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _chat_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def _provider_name() -> str:
    host = urlparse(settings.ai_base_url).netloc.lower()
    if "openrouter.ai" in host:
        return "OpenRouter"
    return host or "OpenAI-compatible API"


async def compatible_chat(messages: list[dict[str, str]], max_tokens: int = 1800) -> dict[str, Any]:
    if not settings.ai_api_key:
        raise RuntimeError("AI_API_KEY не настроен")

    auth_value = f"{settings.ai_auth_scheme} {settings.ai_api_key}".strip()
    headers = {settings.ai_auth_header: auth_value, "Content-Type": "application/json"}
    if "openrouter.ai" in settings.ai_base_url.lower():
        headers["HTTP-Referer"] = settings.ai_site_url
        headers["X-Title"] = settings.ai_app_name

    payload = {
        "model": settings.ai_model,
        "messages": messages,
        "temperature": 0.05,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    endpoint = _chat_endpoint(settings.ai_base_url)
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(endpoint, headers=headers, json=payload)
        if response.status_code in {400, 422} and "response_format" in response.text.lower():
            payload.pop("response_format", None)
            response = await client.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    content = data["choices"][0]["message"]["content"]
    parsed = _extract_json(content)
    parsed["model"] = data.get("model", settings.ai_model)
    parsed["provider"] = _provider_name()
    parsed["usage"] = data.get("usage", {})
    return parsed


openrouter_chat = compatible_chat


def _metric_payload(financial_metrics: Any) -> list[dict[str, Any]]:
    """Select rows that passed structural validation.

    Coordinate OCR with an official RAS line code is materially safer than
    arbitrary prose OCR, so it can enter the financial model at a lower raw
    confidence threshold. Derived rows are accepted only when both source rows
    survived validation.
    """
    values = financial_metrics.values() if isinstance(financial_metrics, dict) else financial_metrics or []
    trusted_sources = {
        "verified_demo_rsbu", "verified_demo", "ras_coordinate_ocr",
        "spreadsheet", "spreadsheet_table", "pdf_table",
        "derived_from_verified_rows",
    }
    output = []
    for item in values:
        if not isinstance(item, dict):
            continue
        confidence = float(item.get("confidence", 0) or 0)
        source_type = str(item.get("source_type") or "")
        verified = (
            bool(item.get("manually_verified"))
            or confidence >= 0.90
            or (source_type in trusted_sources and confidence >= 0.72)
        )
        if not verified or not item.get("values"):
            continue
        output.append({
            "key": item.get("key"),
            "name": item.get("name"),
            "unit": item.get("unit"),
            "values": item.get("values", {}),
            "source_pages": item.get("source_pages", []),
            "source_type": source_type,
            "confidence": confidence,
            "derived": bool(item.get("derived")),
            "verified": True,
        })
    return output


def _operational_payload(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    output = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        confidence = float(item.get("confidence", 0) or 0)
        values = item.get("values", {})
        if confidence < 0.85 or len(values) < 2:
            continue
        name = re.sub(r"\s+", " ", str(item.get("name", ""))).strip()
        words = re.findall(r"[А-Яа-яЁёA-Za-z]{3,}", name)
        if len(words) < 2:
            continue
        output.append({
            "name": name,
            "category": item.get("category"),
            "unit": item.get("unit"),
            "values": values,
            "source_pages": item.get("source_pages", []),
        })
        if len(output) >= 30:
            break
    return output


def _clean_narrative_items(items: list[dict[str, Any]] | None, max_items: int = 10) -> list[dict[str, Any]]:
    cleaned = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        text = re.sub(r"\s+", " ", str(item.get("text", ""))).strip()
        if len(text) < 30 or len(text) > 500:
            continue
        words = re.findall(r"[А-Яа-яA-Za-z]{3,}", text.lower())
        if len(words) < 6:
            continue
        counts = Counter(words)
        if counts and counts.most_common(1)[0][1] / max(len(words), 1) > 0.18:
            continue
        cleaned.append({"text": text, "page": item.get("page")})
        if len(cleaned) >= max_items:
            break
    return cleaned


def _ratio_groups(ratios: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups = {
        "liquidity": {"current_ratio", "quick_ratio", "cash_ratio", "working_capital", "ocf_ratio"},
        "profitability": {"gross_margin", "operating_margin", "net_margin", "ebitda_margin", "roa", "roe"},
        "leverage": {"debt_ratio", "debt_equity", "equity_ratio", "net_debt", "net_debt_equity", "interest_coverage"},
        "efficiency": {"asset_turnover", "inventory_turnover", "receivables_turnover"},
        "cash_flow": {"free_cash_flow", "ocf_margin", "cash_conversion"},
        "growth": {"revenue_growth", "net_profit_growth"},
    }
    output: dict[str, list[dict[str, Any]]] = {key: [] for key in groups}
    for item in ratios or []:
        if item.get("status") == "na":
            continue
        compact = {
            "key": item.get("key"), "name": item.get("name"),
            "value": item.get("value"), "display": item.get("display"),
            "status": item.get("status"), "formula": item.get("formula"),
            "explanation": item.get("explanation"),
        }
        for group, keys in groups.items():
            if item.get("key") in keys:
                output[group].append(compact)
                break
    return output


def _structured_payload(result: dict[str, Any]) -> dict[str, Any]:
    metadata = result.get("metadata", {})
    narrative = result.get("narrative", {})
    is_ras = metadata.get("document_type") == "ras_financial_statements"
    metrics = _metric_payload(result.get("financial_metrics"))
    available_ratios = [item for item in result.get("ratios", []) if item.get("status") != "na"]
    payload = {
        "analysis_scope": {
            "company": metadata.get("company"),
            "document_type": metadata.get("document_type"),
            "reporting_year": metadata.get("reporting_year"),
            "reporting_standard": metadata.get("accounting_standard") or metadata.get("reporting_standard") or ("РСБУ" if is_ras else None),
            "reporting_scope": metadata.get("reporting_scope"),
            "currency_or_unit": metadata.get("unit") or metadata.get("currency"),
            "audit_opinion": metadata.get("audit_opinion"),
            "important_rule": "Это отдельная отчетность юридического лица по РСБУ; выводы о консолидированной Группе запрещены." if is_ras else None,
        },
        "coverage": {
            "verified_metrics_count": len(metrics),
            "calculated_ratios_count": len(available_ratios),
            "periods": sorted({str(year) for item in metrics for year in item.get("values", {})}),
        },
        "verified_financial_metrics": metrics,
        "ratio_groups_calculated_by_code": _ratio_groups(result.get("ratios", [])),
        "risk_flags_calculated_by_code": result.get("risk_flags", []),
        "score_calculated_by_code": result.get("score"),
        "document_limitations": result.get("limitations", []),
        "audit_and_risk_disclosures": _clean_narrative_items(narrative.get("risks"), 10),
        "verified_strategy_disclosures": _clean_narrative_items(narrative.get("strategy"), 8),
        "verified_governance_disclosures": _clean_narrative_items(narrative.get("governance"), 6),
        "verified_esg_disclosures": [] if is_ras else _clean_narrative_items(narrative.get("esg"), 8),
        "deterministic_baseline": result.get("analysis", {}),
    }
    return payload


def _is_gibberish(text: str) -> bool:
    text = re.sub(r"\s+", " ", str(text)).strip()
    if len(text) < 8 or len(text) > 1400:
        return True
    words = re.findall(r"[А-Яа-яA-Za-z]{3,}", text.lower())
    if len(words) < 3:
        return True
    counts = Counter(words)
    if counts.most_common(1)[0][1] / len(words) > 0.20:
        return True
    table_noise = ("наименование показателя", "единица", "2025за", "2024за", "пояснения код")
    return any(token in text.lower() for token in table_noise)


def _number_tokens(value: Any) -> set[str]:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return {token.replace(",", ".") for token in re.findall(r"(?<![A-Za-zА-Яа-яЁё])\d+(?:[.,]\d+)?", text)}


def _validate_numbers(text: str, allowed: set[str]) -> bool:
    # Single-digit list numbering is ignored; all other numeric claims must be
    # traceable to the structured payload or deterministic baseline.
    for token in _number_tokens(text):
        if token in {str(i) for i in range(1, 10)}:
            continue
        if token not in allowed:
            return False
    return True


def _merge_unique(primary: list[str], baseline: list[str], limit: int = 8) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in [*primary, *baseline]:
        text = re.sub(r"\s+", " ", str(item)).strip(" •-\t")
        key = re.sub(r"[^а-яa-z0-9]+", " ", text.lower().replace("ё", "е")).strip()
        if not text or key in seen:
            continue
        seen.add(key)
        output.append(text)
        if len(output) >= limit:
            break
    return output


def _sanitize_analysis(data: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    fields = [
        "strengths", "weaknesses", "risks", "management_actions",
        "data_limitations", "strategic_observations", "esg_observations",
    ]
    baseline = result.get("analysis", {}) if isinstance(result.get("analysis"), dict) else {}
    allowed_numbers = _number_tokens(_structured_payload(result))
    summary = re.sub(r"\s+", " ", str(data.get("executive_summary", ""))).strip()
    summary_sentences = len(re.findall(r"[.!?](?:\s|$)", summary))
    if _is_gibberish(summary) or not _validate_numbers(summary, allowed_numbers) or len(summary) < 260 or summary_sentences < 4:
        summary = str(baseline.get("executive_summary", "")).strip()
    if _is_gibberish(summary):
        raise ValueError("AI и базовый движок не сформировали корректное резюме")

    cleaned: dict[str, Any] = {"executive_summary": summary}
    minimums = {
        "strengths": 4, "weaknesses": 4, "risks": 3,
        "management_actions": 4, "strategic_observations": 3,
        "data_limitations": 1, "esg_observations": 1,
    }
    for field in fields:
        raw = data.get(field, []) if isinstance(data.get(field, []), list) else []
        valid: list[str] = []
        for item in raw:
            text = re.sub(r"\s+", " ", str(item)).strip(" •-\t")
            if not _is_gibberish(text) and _validate_numbers(text, allowed_numbers):
                valid.append(text)
        merged = _merge_unique(valid, baseline.get(field, []) if isinstance(baseline.get(field), list) else [], 8)
        # Never let an external model make the report less substantial than the
        # deterministic financial model.
        if len(merged) < minimums[field]:
            merged = _merge_unique(baseline.get(field, []) if isinstance(baseline.get(field), list) else [], valid, 8)
        cleaned[field] = merged

    is_ras = result.get("metadata", {}).get("document_type") == "ras_financial_statements"
    if is_ras and not cleaned["esg_observations"]:
        cleaned["esg_observations"] = [
            "В бухгалтерской отчетности по РСБУ отсутствует достаточный набор ESG-метрик; для ESG-анализа требуется годовой отчет или отчет об устойчивом развитии."
        ]

    cleaned["model"] = data.get("model", settings.ai_model)
    cleaned["provider"] = data.get("provider", _provider_name())
    cleaned["usage"] = data.get("usage", {})
    cleaned["mode"] = "ai_financial_model_v21"
    cleaned["chunks_processed"] = 0
    cleaned["coverage"] = baseline.get("coverage", {})
    return cleaned


async def map_reduce_analysis(result: dict[str, Any]) -> dict[str, Any]:
    """Produce a full report from a verified financial model.

    The deterministic baseline remains the minimum quality floor. The model can
    improve prioritization and wording, but the sanitizer merges baseline facts
    back when an answer is too short or omits a material section.
    """
    payload = _structured_payload(result)
    prompt = {
        "task": (
            "Подготовь профессиональное финансово-аналитическое заключение. "
            "Используй deterministic_baseline как обязательный минимальный набор выводов, "
            "а ratio_groups_calculated_by_code — для углубления анализа ликвидности, рентабельности, долговой нагрузки, эффективности и денежных потоков."
        ),
        "required_logic": [
            "Сопоставь рост выручки, валовой прибыли, прибыли от продаж и чистой прибыли; объясни только наблюдаемое расхождение, не придумывая причины.",
            "Оцени ликвидность одновременно по Current Ratio, Quick Ratio, Cash Ratio, Working Capital и OCF Ratio, если они доступны.",
            "Оцени финансовую устойчивость по Debt/Equity, Debt Ratio, Equity Ratio, Net Debt и Interest Coverage.",
            "Оцени качество прибыли по операционному денежному потоку, Cash Conversion и Free Cash Flow.",
            "Сформулируй конкретные действия менеджмента, связанные с выявленными показателями и риск-флагами.",
            "Не сокращай разделы до одной общей фразы."
        ],
        "hard_constraints": [
            "Использовать только проверенные данные JSON и deterministic_baseline.",
            "Не добавлять внешние факты, новые числа или неподтвержденные причины.",
            "Не менять значения и направление динамики.",
            "Для РСБУ соблюдать периметр отдельного юридического лица.",
            "Вернуть строгий JSON по заданной схеме."
        ],
        "data": payload,
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            raw = await compatible_chat(messages, max_tokens=3600)
            return _sanitize_analysis(raw, result)
        except Exception as exc:
            last_error = exc
            messages.append({
                "role": "user",
                "content": (
                    "Ответ отклонен валидатором. Сохрани все существенные выводы deterministic_baseline, "
                    "сделай executive_summary не короче пяти предложений и заполни каждый аналитический раздел. "
                    f"Причина: {type(exc).__name__}."
                ),
            })
    raise ValueError(f"AI не прошел проверку качества: {last_error}")


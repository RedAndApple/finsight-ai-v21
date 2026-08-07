from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, Callable

import fitz
import pandas as pd
import pdfplumber

from .config import settings
from .ocr import recognize_page

from .financial import (
    classify_operational,
    find_metric_key,
    normalize_label,
    parse_number,
)

ProgressCallback = Callable[[int, str], None]


def _normalize_ocr_token(text: str) -> str:
    """Normalize common OCR confusions without changing ordinary prose."""
    return (text or "").strip().replace("O", "0").replace("О", "0").replace("I", "1").replace("l", "1").replace("|", "")


def _ocr_lines_from_image(image: Any) -> list[dict[str, Any]]:
    """Return OCR lines with word coordinates.

    RAS forms are scanned tables. Plain OCR text loses column boundaries and can
    concatenate three annual values into one huge number. Coordinates preserve
    the original columns, which lets us rebuild each value safely.
    """
    import pytesseract
    from pytesseract import Output

    data = pytesseract.image_to_data(
        image,
        lang=settings.ocr_language,
        config="--oem 1 --psm 6 -c preserve_interword_spaces=1",
        output_type=Output.DICT,
    )
    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    count = len(data.get("text", []))
    for i in range(count):
        raw = str(data["text"][i] or "").strip()
        try:
            conf = float(data["conf"][i])
        except Exception:
            conf = -1
        if not raw or conf < 18:
            continue
        key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
        grouped.setdefault(key, []).append({
            "text": raw,
            "left": int(data["left"][i]),
            "top": int(data["top"][i]),
            "width": int(data["width"][i]),
            "height": int(data["height"][i]),
            "conf": conf,
        })
    lines = []
    for words in grouped.values():
        words.sort(key=lambda w: w["left"])
        lines.append({
            "text": " ".join(w["text"] for w in words),
            "top": min(w["top"] for w in words),
            "words": words,
        })
    lines.sort(key=lambda line: line["top"])
    return lines


def _find_code_index(words: list[dict[str, Any]], code: str, label_parts: tuple[str, ...] = ()) -> int | None:
    line_text = normalize_label(" ".join(str(word.get("text", "")) for word in words))
    label_matches = not label_parts or all(part in line_text for part in label_parts)
    numeric_tokens: list[tuple[int, str]] = []
    for index, word in enumerate(words):
        token = re.sub(r"\D", "", _normalize_ocr_token(word.get("text", "")))
        if not token:
            continue
        numeric_tokens.append((index, token))
        if token == code:
            return index
    if label_matches:
        # Table borders often cause Tesseract to lose the final zero in official
        # four-digit RAS codes (e.g. 240 instead of 2400).
        fuzzy = {code[:-1], code[1:], code.lstrip("0")}
        for index, token in numeric_tokens:
            if token in fuzzy and 3 <= len(token) <= 4:
                return index
        # Last resort: the first 3–4 digit token after a recognized canonical
        # label and before long monetary values is almost certainly the row code.
        for index, token in numeric_tokens:
            if 3 <= len(token) <= 4:
                return index
    return None


def _numeric_groups_after_code(words: list[dict[str, Any]], code: str, label_parts: tuple[str, ...] = ()) -> list[float]:
    """Reconstruct annual values to the right of a RAS line code.

    Values such as ``3 453 224 535`` consist of several OCR words. A large
    horizontal gap marks the next year column. Official row labels provide a
    safe fallback when one digit of the code is obscured by a table border.
    """
    code_index = _find_code_index(words, code, label_parts)
    if code_index is None:
        return []
    tail = words[code_index + 1 :]
    numeric_words: list[dict[str, Any]] = []
    for word in tail:
        raw = _normalize_ocr_token(word["text"]).replace("−", "-")
        if re.fullmatch(r"[()\-+]?\d[\d.,()\-+]*", raw):
            numeric_words.append({**word, "norm": raw})
    if not numeric_words:
        return []

    groups: list[list[dict[str, Any]]] = [[numeric_words[0]]]
    for word in numeric_words[1:]:
        prev = groups[-1][-1]
        gap = word["left"] - (prev["left"] + prev["width"])
        if gap > max(48, int(prev["height"] * 1.8)):
            groups.append([word])
        else:
            groups[-1].append(word)

    values: list[float] = []
    for group in groups:
        combined = " ".join(item["norm"] for item in group)
        negative = "(" in combined or combined.strip().startswith("-")
        digits = "".join(re.findall(r"\d+", combined))
        if not digits:
            continue
        value = float(digits)
        if negative:
            value = -abs(value)
        values.append(value)
    return values


def extract_ras_metrics_from_ocr_lines(pages: list[dict[str, Any]], reporting_year: int | None) -> list[dict[str, Any]]:
    """Extract standard RAS rows from coordinate-aware OCR lines.

    Every result is selected by official row code. OCR is never trusted for the
    displayed label. When a page contains duplicate Tesseract lines, the best
    candidate is chosen by line confidence and numeric completeness.
    """
    if not reporting_year:
        return []
    best: dict[str, tuple[float, dict[str, Any]]] = {}
    for page in pages:
        lines = page.get("ocr_lines") or []
        page_text = normalize_label(page.get("text", ""))
        codes_on_page = {
            re.sub(r"\D", "", _normalize_ocr_token(w["text"]))
            for line in lines for w in line.get("words", [])
        }
        if "2110" in codes_on_page or "2400" in codes_on_page:
            page_kind = "pnl"
        elif any(code in codes_on_page for code in ("4100", "4200", "4300", "4400", "4500")):
            page_kind = "cashflow"
        elif any(code in codes_on_page for code in ("1100", "1200", "1300", "1400", "1500", "1600", "1700")):
            page_kind = "balance"
        elif "отчет о финансовых результатах" in page_text:
            page_kind = "pnl"
        elif "движении денежных средств" in page_text:
            page_kind = "cashflow"
        else:
            page_kind = "balance" if ("актив" in page_text or "пассив" in page_text) else None
        if not page_kind:
            continue

        for key, name, code, _label_parts, required_kind, count in RAS_FORM_SPECS:
            if required_kind != page_kind:
                continue
            for line in lines:
                words = line.get("words", [])
                exact_code = any(
                    re.sub(r"\D", "", _normalize_ocr_token(word.get("text", ""))) == code
                    for word in words
                )
                line_text = normalize_label(" ".join(str(word.get("text", "")) for word in words))
                label_match = all(part in line_text for part in _label_parts)
                if not exact_code and not label_match:
                    continue
                values = _numeric_groups_after_code(words, code, _label_parts)
                if len(values) < count:
                    continue
                values = values[:count]
                if any(abs(v) > 20_000_000_000 for v in values):
                    continue
                nonzero = [abs(v) for v in values if v != 0]
                if len(nonzero) >= 2 and max(nonzero) / max(min(nonzero), 1) > 50:
                    continue
                if key in {"cogs", "commercial_expenses", "administrative_expenses", "interest_expense", "other_expenses", "income_tax", "operating_payments", "capex"}:
                    values = [-abs(v) for v in values]
                years = [str(reporting_year - offset) for offset in range(count)]
                line_conf = float(line.get("confidence", 0) or 0)
                # Exact row code + complete columns dominate; OCR line quality
                # resolves duplicate/overlapping text boxes.
                score = (120 if exact_code else 75) + line_conf + len(values) * 10
                candidate = {
                    "key": key,
                    "name": name,
                    "unit": "тыс. руб.",
                    "values": dict(zip(years, values)),
                    "source_pages": [page["page"]],
                    "source_type": "ras_coordinate_ocr",
                    "confidence": round(min(0.99, (0.84 if exact_code else 0.74) + line_conf / 700), 2),
                }
                if key not in best or score > best[key][0]:
                    best[key] = (score, candidate)
    return [item for _score, item in best.values()]


YEAR_RE = re.compile(r"\b(20\d{2}|19\d{2})\b")
COMPANY_PATTERNS = [
    re.compile(r"(?:ПАО|АО|ООО|ОАО)\s+[«\"]([^»\"]+)[»\"]", re.I),
    re.compile(r"(?:Группа|Компания)\s+[«\"]([^»\"]+)[»\"]", re.I),
]


def extract_unit(text: str) -> str | None:
    """Extract the nearest explicit measurement unit from text.

    The nearest match is preferred because report prose can mention a ruble
    exchange rate shortly before a table whose actual unit is barrels.
    """
    raw = text.lower().replace("ё", "е").replace("\u00a0", " ")
    patterns = [
        ("млн барр. н.э.", r"млн\s+барр(?:\.|елей)?\s*(?:н\.?\s*э\.?)?"),
        ("тыс. барр. н.э./сут", r"тыс\.?\s*барр(?:\.|елей)?\s*н\.?\s*э\.?\s*/\s*сут"),
        ("долл./барр.", r"долл(?:\.|аров)?\s*/\s*барр"),
        ("млрд руб.", r"млрд\s+руб(?:\.|лей)?\b"),
        ("млн руб.", r"млн\s+руб(?:\.|лей)?\b"),
        ("тыс. руб.", r"тыс\.?\s+руб(?:\.|лей)?\b"),
        ("млрд долл.", r"млрд\s+долл(?:\.|аров)?\b"),
        ("млн долл.", r"млн\s+долл(?:\.|аров)?\b"),
        ("млрд куб. м", r"млрд\s+куб\.?\s*м\b"),
        ("млн куб. м", r"млн\s+куб\.?\s*м\b"),
        ("тыс. куб. м", r"тыс\.?\s+куб\.?\s*м\b"),
        ("млн кВт·ч", r"млн\s+квт(?:[^а-яa-z0-9]?ч)?"),
        ("тыс. кВт·ч", r"тыс\.?\s+квт(?:[^а-яa-z0-9]?ч)?"),
        ("т/сут", r"\bт\s*/\s*сут\b"),
        ("тыс. ТУТ", r"тыс\.?\s+тут\b"),
        ("га", r"\bга\b"),
        ("млн Гкал", r"млн\s+гкал"),
        ("млн т", r"млн\s+т(?:онн)?\b"),
        ("тыс. т", r"тыс\.?\s+т(?:онн)?\b"),
        ("млн барр.", r"млн\s+барр(?:\.|елей)?"),
        ("тыс. барр.", r"тыс\.?\s+барр(?:\.|елей)?"),
        ("ГВт", r"\bгвт\b"),
        ("МВт", r"\bмвт\b"),
        ("шт.", r"\bшт\.?\b"),
        ("чел.", r"\bчел(?:\.|овек)?\b"),
        ("%", r"%"),
        ("п.п.", r"п\.?\s*п\.?"),
        ("руб.", r"\bруб(?:\.|лей)?\b"),
        ("долл.", r"\bдолл(?:\.|аров)?\b"),
    ]
    candidates: list[tuple[int, int, str]] = []
    for canonical, pattern in patterns:
        for match in re.finditer(pattern, raw, re.I):
            candidates.append((match.start(), len(match.group(0)), canonical))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0] + item[1], item[1]))[2]


def identify_company(text: str, fallback: str = "Не определено") -> str:
    for pattern in COMPANY_PATTERNS:
        match = pattern.search(text)
        if match:
            prefix_match = re.search(r"(?:ПАО|АО|ООО|ОАО)", match.group(0), re.I)
            prefix = prefix_match.group(0).upper() if prefix_match else ""
            return f"{prefix} «{match.group(1).strip()}»".strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:20]:
        if any(token in line.lower() for token in ("annual report", "годовой отчет")):
            continue
        if 3 <= len(line) <= 100 and any(token in line.lower() for token in ("company", "компания", "group", "группа")):
            return line
    return fallback


def classify_document(text: str) -> str:
    normalized = normalize_label(text[:250000])
    intro = normalize_label(text[:15000])
    # A report can mention IFRS/RAS forms without containing them. The title and
    # table-of-contents structure therefore take precedence for annual reports.
    if "годовой отчет" in intro and (
        "оглавление" in intro
        or ("корпоративное управление" in normalized and "устойчивое развитие" in normalized)
    ):
        return "annual_report"
    # Full financial forms take precedence over the auditor's cover pages.
    has_balance = "бухгалтерский баланс" in normalized or "statement of financial position" in normalized
    has_profit = "отчет о финансовых результатах" in normalized or "statement of profit" in normalized
    has_cashflow = "отчет о движении денежных средств" in normalized or "statement of cash flows" in normalized
    if has_balance and has_profit:
        if "международн" in normalized or "ifrs" in normalized or "мсфо" in normalized:
            return "ifrs_financial_statements"
        return "ras_financial_statements"
    if "консолидированная финансовая отчетность" in normalized or "statement of financial position" in normalized:
        return "ifrs_financial_statements"
    if "годовой отчет" in normalized or ("корпоративное управление" in normalized and "устойчивое развитие" in normalized):
        return "annual_report"
    if "аудиторское заключение" in normalized or "independent auditor's report" in normalized:
        return "audit_report"
    if "презентация для инвесторов" in normalized or "investor presentation" in normalized:
        return "investor_presentation"
    return "corporate_document"


def detect_headings(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    headings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in pages:
        for raw_line in page["text"].splitlines():
            line = raw_line.strip()
            if not line or len(line) > 150 or len(line) < 3:
                continue
            is_numbered = bool(re.match(r"^\d+(?:\.\d+){0,3}\.?\s+\D", line))
            is_title_case = line.isupper() and len(line.split()) <= 12
            is_known = any(keyword in normalize_label(line) for keyword in (
                "финансовые результат", "разведка и добыча", "переработка", "устойчивое развитие",
                "корпоративное управление", "управление рисками", "персонал", "климат",
                "акционерный капитал", "аудиторское заключение", "денежных поток",
                "финансового положения", "бухгалтерский баланс",
            ))
            normalized = normalize_label(line)
            if (is_numbered or is_title_case or is_known) and normalized not in seen:
                headings.append({"title": line, "page": page["page"]})
                seen.add(normalized)
    return headings[:200]


def rows_from_table(table: list[list[Any]], page_number: int, table_index: int) -> dict[str, Any] | None:
    cleaned = []
    for row in table:
        cleaned_row = []
        for cell in row:
            if cell is None:
                cleaned_row.append("")
            else:
                cleaned_row.append(re.sub(r"\s+", " ", str(cell)).strip())
        if any(cleaned_row):
            cleaned.append(cleaned_row)
    if len(cleaned) < 2:
        return None
    width = max(len(row) for row in cleaned)
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]
    return {
        "page": page_number,
        "table_index": table_index,
        "rows": cleaned[:120],
        "row_count": len(cleaned),
        "column_count": width,
    }


def infer_year_columns(rows: list[list[str]]) -> tuple[dict[int, str], int | None]:
    """Find columns whose header cell is an exact year.

    A header such as "Изменение 2025/2024" must not be interpreted as the
    2024 column; otherwise the percentage-change value overwrites the actual
    2024 value.
    """
    best: tuple[int, dict[int, str]] | None = None
    for row_index, row in enumerate(rows[:10]):
        mapping: dict[int, str] = {}
        used_years: set[str] = set()
        for col_index, cell in enumerate(row):
            cell_text = re.sub(r"\s+", "", str(cell))
            match = re.fullmatch(r"(19\d{2}|20\d{2})", cell_text)
            if match and match.group(1) not in used_years:
                mapping[col_index] = match.group(1)
                used_years.add(match.group(1))
        if len(mapping) >= 1 and (best is None or len(mapping) > len(best[1])):
            best = (row_index, mapping)
    return (best[1], best[0]) if best else ({}, None)


def extract_metrics_from_table(table: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = table["rows"]
    year_columns, header_index = infer_year_columns(rows)
    if not year_columns:
        return [], []
    financial: list[dict[str, Any]] = []
    operational: list[dict[str, Any]] = []
    header_end = ((header_index if header_index is not None else 0) + 1)
    title_context = (table.get("context") or "") + " " + " ".join(
        " ".join(row) for row in rows[:header_end]
    )
    for row in rows[(header_index or 0) + 1 :]:
        label_cells = [cell for index, cell in enumerate(row) if index not in year_columns and cell]
        if not label_cells:
            continue
        label = label_cells[0]
        if len(label) > 250 or YEAR_RE.fullmatch(label.strip()):
            continue
        values = {}
        for col_index, year in year_columns.items():
            if col_index < len(row):
                value = parse_number(row[col_index])
                if value is not None:
                    values[year] = value
        if not values:
            continue
        metric_key = find_metric_key(label)
        is_ocr_table = table.get("source_type") == "ocr_coordinate_table"
        confidence = float(table.get("confidence", 0.9 if len(values) >= 2 else 0.72))
        unit = extract_unit(label)
        if unit is None:
            context_unit = extract_unit(title_context)
            # Percentage-point units are frequently present in a neighboring
            # change column and must not leak into physical production rows.
            if context_unit == "п.п." and not any(token in normalize_label(label) for token in ("доля", "изменен", "темп", "коэффициент", "индекс")):
                context_unit = None
            unit = context_unit
        base = {
            "name": label,
            "unit": unit,
            "values": values,
            "source_pages": [table["page"]],
            "source_type": table.get("source_type", "pdf_table"),
            "confidence": confidence,
        }
        if metric_key:
            financial.append({**base, "key": metric_key})
        else:
            # OCR tables from scans are not exposed as operational KPIs unless
            # a future domain-specific mapping validates the row. Showing a
            # plausible-looking but misspelled label is worse than omitting it.
            if not is_ocr_table:
                operational.append({**base, "category": classify_operational(label)})
    return financial, operational


def _narrative_sentence_is_clean(sentence: str) -> bool:
    normalized = re.sub(r"\s+", " ", sentence).strip()
    if len(normalized) < 70 or len(normalized) > 650:
        return False
    words = re.findall(r"[А-Яа-яЁёA-Za-z]{3,}", normalized)
    if len(words) < 9:
        return False
    cyrillic = sum(bool(re.search(r"[А-Яа-яЁё]", word)) for word in words)
    if cyrillic / len(words) < 0.65:
        return False
    digit_tokens = re.findall(r"\b\d+\b", normalized)
    if len(digit_tokens) > len(words) * 0.45:
        return False
    counts: dict[str, int] = {}
    for word in words:
        key = word.lower()
        counts[key] = counts.get(key, 0) + 1
    if counts and max(counts.values()) / len(words) > 0.16:
        return False
    noise = ("наименование показателя", "пояснения код", "единица измерения", "2025за", "2024за")
    return not any(token in normalized.lower() for token in noise)


def extract_narrative_facts(pages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    rules = {
        "risks": ("риск", "ограничени", "санкц", "неопределен", "волатильн"),
        "strategy": ("стратег", "приоритет", "развит", "проект", "инвестиц", "модернизац"),
        "esg": ("устойчив", "климат", "эколог", "выброс", "охрана труда"),
        "governance": ("совет директоров", "корпоративное управление", "внутренний аудит", "аудитор"),
    }
    output: dict[str, list[dict[str, Any]]] = {key: [] for key in rules}
    seen: set[str] = set()
    sentence_re = re.compile(r"(?<=[.!?])\s+")
    for page in pages:
        if page.get("ocr") and (page.get("ocr_quality") or 0) < 58:
            continue
        text = re.sub(r"[ \t]+", " ", page["text"]).strip()
        for sentence in sentence_re.split(text):
            sentence = re.sub(r"\s+", " ", sentence).strip()
            if not _narrative_sentence_is_clean(sentence):
                continue
            normalized = normalize_label(sentence)
            for category, keywords in rules.items():
                if any(keyword in normalized for keyword in keywords):
                    key = normalized[:220]
                    if key not in seen:
                        output[category].append({
                            "text": sentence,
                            "page": page["page"],
                            "confidence": round((page.get("ocr_quality") or 100) / 100, 2),
                        })
                        seen.add(key)
                    break
    return {key: values[:24] for key, values in output.items()}


def extract_text_metrics(pages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    financial: list[dict[str, Any]] = []
    operational: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?P<label>[А-ЯA-ZЁ][^\n]{3,140}?)\s+(?P<y1>20\d{2})\s+(?P<v1>[-+−]?\d[\d\s]*(?:[,.]\d+)?)\s+(?P<y2>20\d{2})\s+(?P<v2>[-+−]?\d[\d\s]*(?:[,.]\d+)?)",
        re.M,
    )
    for page in pages:
        for match in pattern.finditer(page["text"]):
            label = match.group("label").strip()
            values = {
                match.group("y1"): parse_number(match.group("v1")),
                match.group("y2"): parse_number(match.group("v2")),
            }
            values = {year: value for year, value in values.items() if value is not None}
            if not values:
                continue
            metric_key = find_metric_key(label)
            base = {
                "name": label,
                "unit": extract_unit(label),
                "values": values,
                "source_pages": [page["page"]],
                "source_type": "pdf_text",
                "confidence": 0.55,
            }
            if metric_key:
                financial.append({**base, "key": metric_key})
            else:
                operational.append({**base, "category": classify_operational(label)})
    return financial, operational


RAS_FORM_SPECS = [
    # Отчет о финансовых результатах
    ("revenue", "Выручка", "2110", ("выручка",), "pnl", 2),
    ("cogs", "Себестоимость продаж", "2120", ("себестоимость", "продаж"), "pnl", 2),
    ("gross_profit", "Валовая прибыль", "2100", ("валовая", "прибыль"), "pnl", 2),
    ("commercial_expenses", "Коммерческие расходы", "2210", ("коммерческие", "расходы"), "pnl", 2),
    ("administrative_expenses", "Управленческие расходы", "2220", ("управленческие", "расходы"), "pnl", 2),
    ("operating_profit", "Прибыль от продаж", "2200", ("прибыль", "продаж"), "pnl", 2),
    ("interest_income", "Проценты к получению", "2320", ("проценты", "получению"), "pnl", 2),
    ("interest_expense", "Проценты к уплате", "2330", ("проценты", "уплате"), "pnl", 2),
    ("other_income", "Прочие доходы", "2340", ("прочие", "доходы"), "pnl", 2),
    ("other_expenses", "Прочие расходы", "2350", ("прочие", "расходы"), "pnl", 2),
    ("profit_before_tax", "Прибыль до налогообложения", "2300", ("прибыль", "налогообложения"), "pnl", 2),
    ("income_tax", "Налог на прибыль", "2410", ("налог", "прибыль"), "pnl", 2),
    ("net_profit", "Чистая прибыль", "2400", ("чистая", "прибыль"), "pnl", 2),
    ("comprehensive_income", "Совокупный финансовый результат", "2500", ("совокупный", "результат"), "pnl", 2),

    # Бухгалтерский баланс
    ("noncurrent_assets", "Внеоборотные активы", "1100", ("итого", "разделу", "i"), "balance", 3),
    ("financial_investments", "Долгосрочные финансовые вложения", "1170", ("финансовые", "вложения"), "balance", 3),
    ("inventory", "Запасы", "1210", ("запасы",), "balance", 3),
    ("receivables", "Дебиторская задолженность", "1230", ("дебиторская", "задолженность"), "balance", 3),
    ("cash", "Денежные средства и денежные эквиваленты", "1250", ("денежные", "эквиваленты"), "balance", 3),
    ("current_assets", "Оборотные активы", "1200", ("итого", "разделу", "ii"), "balance", 3),
    ("assets", "Активы", "1600", ("баланс",), "balance", 3),
    ("retained_earnings", "Нераспределенная прибыль", "1370", ("нераспределенная", "прибыль"), "balance", 3),
    ("equity", "Капитал", "1300", ("итого", "разделу", "iii"), "balance", 3),
    ("longterm_debt_component", "Долгосрочные заемные средства", "1410", ("заемные", "средства"), "balance", 3),
    ("longterm_liabilities", "Долгосрочные обязательства", "1400", ("итого", "разделу", "iv"), "balance", 3),
    ("shortterm_debt_component", "Краткосрочные заемные средства", "1510", ("заемные", "средства"), "balance", 3),
    ("payables", "Кредиторская задолженность", "1520", ("кредиторская", "задолженность"), "balance", 3),
    ("current_liabilities", "Краткосрочные обязательства", "1500", ("итого", "разделу", "v"), "balance", 3),

    # Отчет о движении денежных средств
    ("operating_receipts", "Поступления от текущих операций", "4110", ("поступления", "всего"), "cashflow", 2),
    ("operating_payments", "Платежи по текущим операциям", "4120", ("платежи", "всего"), "cashflow", 2),
    ("operating_cash_flow", "Сальдо денежных потоков от текущих операций", "4100", ("сальдо", "текущих", "операций"), "cashflow", 2),
    ("investing_cash_flow", "Сальдо денежных потоков от инвестиционных операций", "4200", ("сальдо", "инвестиционных", "операций"), "cashflow", 2),
    ("capex", "Платежи на приобретение и создание внеоборотных активов", "4221", ("приобретением", "внеоборотных", "активов"), "cashflow", 2),
    ("financing_cash_flow", "Сальдо денежных потоков от финансовых операций", "4300", ("сальдо", "финансовых", "операций"), "cashflow", 2),
    ("net_cash_change", "Сальдо денежных потоков за период", "4400", ("сальдо", "период"), "cashflow", 2),
    ("cash_begin", "Остаток денежных средств на начало периода", "4450", ("остаток", "начало"), "cashflow", 2),
    ("cash_end", "Остаток денежных средств на конец периода", "4500", ("остаток", "конец"), "cashflow", 2),
]



# Canonical labels for the most common official RAS form rows. OCR is used to
# locate the row code and numeric columns; labels shown to the user come from
# this dictionary, not from uncertain character recognition.
RAS_CODE_LABELS: dict[str, str] = {
    "1100": "Итого внеоборотные активы",
    "1110": "Нематериальные активы",
    "1150": "Основные средства",
    "1160": "Инвестиционная недвижимость",
    "1170": "Финансовые вложения",
    "1180": "Отложенные налоговые активы",
    "1190": "Прочие внеоборотные активы",
    "1200": "Итого оборотные активы",
    "1210": "Запасы",
    "1220": "Налог на добавленную стоимость по приобретенным ценностям",
    "1230": "Дебиторская задолженность",
    "1240": "Финансовые вложения (кроме денежных эквивалентов)",
    "1250": "Денежные средства и денежные эквиваленты",
    "1260": "Прочие оборотные активы",
    "1300": "Итого капитал",
    "1370": "Нераспределенная прибыль (непокрытый убыток)",
    "1400": "Итого долгосрочные обязательства",
    "1410": "Долгосрочные заемные средства",
    "1420": "Отложенные налоговые обязательства",
    "1430": "Оценочные обязательства",
    "1450": "Прочие долгосрочные обязательства",
    "1500": "Итого краткосрочные обязательства",
    "1510": "Краткосрочные заемные средства",
    "1520": "Кредиторская задолженность",
    "1540": "Краткосрочные оценочные обязательства",
    "1550": "Прочие краткосрочные обязательства",
    "1600": "Баланс (актив)",
    "1700": "Баланс (пассив)",
    "2100": "Валовая прибыль (убыток)",
    "2110": "Выручка",
    "2120": "Себестоимость продаж",
    "2200": "Прибыль (убыток) от продаж",
    "2210": "Коммерческие расходы",
    "2220": "Управленческие расходы",
    "2300": "Прибыль (убыток) до налогообложения",
    "2320": "Проценты к получению",
    "2330": "Проценты к уплате",
    "2340": "Прочие доходы",
    "2350": "Прочие расходы",
    "2410": "Налог на прибыль организаций",
    "2400": "Чистая прибыль (убыток)",
    "2500": "Совокупный финансовый результат",
    "4100": "Сальдо денежных потоков от текущих операций",
    "4110": "Поступления от текущих операций — всего",
    "4120": "Платежи по текущим операциям — всего",
    "4200": "Сальдо денежных потоков от инвестиционных операций",
    "4210": "Поступления от инвестиционных операций — всего",
    "4220": "Платежи по инвестиционным операциям — всего",
    "4221": "Платежи на приобретение и создание внеоборотных активов",
    "4300": "Сальдо денежных потоков от финансовых операций",
    "4310": "Поступления от финансовых операций — всего",
    "4320": "Платежи по финансовым операциям — всего",
    "4400": "Сальдо денежных потоков за период",
    "4450": "Остаток денежных средств на начало периода",
    "4500": "Остаток денежных средств на конец периода",
}


def _number_tokens(text: str) -> list[float]:
    tokens = re.findall(r"\(?[−-]?\d(?:[\d \u00a0]*\d)?(?:[,.]\d+)?\)?", text)
    output: list[float] = []
    for token in tokens:
        value = parse_number(token)
        if value is not None:
            output.append(value)
    return output


def extract_ras_form_metrics(pages: list[dict[str, Any]], reporting_year: int | None) -> list[dict[str, Any]]:
    """Extract standard RAS form rows from OCR text using form line codes.

    This complements coordinate-table parsing for image-only PDFs. Values are
    assigned to the reporting year and comparative years from the form header.
    """
    if not reporting_year:
        return []
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for page in pages:
        text = page.get("text", "")
        normalized_page = normalize_label(text)
        if "отчет о финансовых результатах" in normalized_page:
            page_kind = "pnl"
        elif "отчет о движении денежных средств" in normalized_page or "денежные потоки от текущих операций" in normalized_page:
            page_kind = "cashflow"
        elif "бухгалтерский баланс" in normalized_page or "актив" in normalized_page or "пассив" in normalized_page:
            page_kind = "balance"
        else:
            # Continuation pages can omit the title.
            page_kind = "cashflow" if any(code in text for code in ("4200", "4300", "4400")) else ("balance" if any(code in text for code in ("1300", "1400", "1500", "1700")) else None)
        if not page_kind:
            continue
        lines = text.splitlines()
        for index, line in enumerate(lines):
            window = " ".join(lines[index:index + 3])
            normalized = normalize_label(window)
            for key, name, code, label_parts, required_kind, count in RAS_FORM_SPECS:
                if required_kind != page_kind or (key, page["page"]) in seen:
                    continue
                code_match = re.search(rf"(?<!\d){re.escape(code)}(?!\d)", window)
                label_match = all(part in normalized for part in label_parts)
                if not code_match and not label_match:
                    continue
                tail = window[code_match.end():] if code_match else window
                values = [value for value in _number_tokens(tail) if abs(value) >= 1000]
                if len(values) < count:
                    continue
                values = values[:count]
                years = [str(reporting_year - offset) for offset in range(count)]
                # Expense/cash outflow rows in RAS forms are commonly parenthesized.
                if key in {"cogs", "commercial_expenses", "administrative_expenses", "interest_expense", "other_expenses", "income_tax", "operating_payments", "capex"}:
                    values = [-abs(value) for value in values]
                candidate_values = {year: value for year, value in zip(years, values)}
                candidates.append({
                    "key": key,
                    "name": name,
                    "unit": "тыс. руб.",
                    "values": candidate_values,
                    "source_pages": [page["page"]],
                    "source_type": "ras_ocr_form",
                    "confidence": 0.78 if code_match else 0.62,
                })
                seen.add((key, page["page"]))
    return candidates


def infer_table_context(page_text: str, rows: list[list[str]]) -> str:
    """Return nearby text before a table to recover its title and unit."""
    labels = [row[0].strip() for row in rows[1:5] if row and row[0].strip()]
    for label in labels:
        needle = label[:80]
        position = page_text.find(needle)
        if position >= 0:
            return page_text[max(0, position - 500):position]
    return page_text[:500]


def infer_reporting_year(first_pages_text: str, years: list[str]) -> int | None:
    patterns = [
        r"(?:за|for)\s+(20\d{2})\s*(?:год|year)",
        r"(?:годовой отчет|annual report)[^\n]{0,80}?(20\d{2})",
        r"по состоянию на 31 декабря (20\d{2})",
    ]
    normalized = first_pages_text.lower().replace("ё", "е")
    for pattern in patterns:
        match = re.search(pattern, normalized, re.I)
        if match:
            return int(match.group(1))
    plausible = [int(year) for year in years if 1990 <= int(year) <= 2100]
    return max(plausible) if plausible else None



def _ocr_word_number(word: dict[str, Any]) -> str | None:
    raw = _normalize_ocr_token(str(word.get("text", ""))).replace("−", "-")
    if not re.fullmatch(r"[()\-+]?\d[\d.,()\-+]*", raw):
        return None
    return raw


def _join_ocr_number_words(words: list[dict[str, Any]]) -> float | None:
    """Join the most plausible numeric cluster inside one table cell."""
    numeric = []
    for word in sorted(words, key=lambda item: item.get("left", 0)):
        value = _ocr_word_number(word)
        if value is not None:
            numeric.append({**word, "norm": value})
    if not numeric:
        return None
    groups: list[list[dict[str, Any]]] = [[numeric[0]]]
    for word in numeric[1:]:
        prev = groups[-1][-1]
        gap = word.get("left", 0) - (prev.get("left", 0) + prev.get("width", 0))
        if gap > max(45, int(max(prev.get("height", 1), word.get("height", 1)) * 1.8)):
            groups.append([word])
        else:
            groups[-1].append(word)

    candidates: list[tuple[int, int, float]] = []
    for group in groups:
        combined = " ".join(item["norm"] for item in group)
        digits = "".join(re.findall(r"\d+", combined))
        if not digits:
            continue
        negative = "(" in combined or combined.strip().startswith("-")
        value = float(digits)
        if negative:
            value = -abs(value)
        candidates.append((len(digits), group[-1].get("left", 0), value))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def extract_ocr_tables(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recover simple multi-year tables from coordinate OCR.

    This parser is deliberately conservative: it only accepts a page after an
    explicit header containing at least two exact years. Numeric tokens are
    assigned to year columns by x-coordinate, preventing several columns from
    being concatenated into one value.
    """
    output: list[dict[str, Any]] = []
    for page in pages:
        lines = page.get("ocr_lines") or []
        if not lines or (page.get("ocr_quality") or 0) < 48:
            continue
        page_ras_codes = {
            re.sub(r"\D", "", _normalize_ocr_token(word.get("text", "")))
            for line in lines for word in line.get("words", [])
            if re.sub(r"\D", "", _normalize_ocr_token(word.get("text", ""))) in RAS_CODE_LABELS
        }
        ras_form_page = len(page_ras_codes) >= 2
        for header_index, header in enumerate(lines):
            year_words: list[tuple[str, float]] = []
            for word in header.get("words", []):
                token = re.sub(r"\D", "", _normalize_ocr_token(word.get("text", "")))
                if re.fullmatch(r"(?:19|20)\d{2}", token):
                    center = float(word["left"] + word["width"] / 2)
                    year_words.append((token, center))
            # De-duplicate OCR repetitions and keep left-to-right order.
            dedup: dict[str, float] = {}
            for year, center in year_words:
                dedup.setdefault(year, center)
            year_words = sorted(dedup.items(), key=lambda item: item[1])
            if len(year_words) < 2 or len(year_words) > 5:
                continue

            centers = [center for _, center in year_words]
            years = [year for year, _ in year_words]
            gaps = [centers[i + 1] - centers[i] for i in range(len(centers) - 1)]
            typical_gap = sorted(gaps)[len(gaps) // 2] if gaps else 260.0
            boundaries = [centers[0] - typical_gap / 2]
            boundaries.extend((centers[i] + centers[i + 1]) / 2 for i in range(len(centers) - 1))
            boundaries.append(centers[-1] + typical_gap / 2)
            first_center = centers[0]
            rows: list[list[str]] = [["Показатель", *years]]
            seen_rows: set[tuple[str, ...]] = set()

            for line in lines[header_index + 1 : header_index + 55]:
                if line.get("top", 0) - header.get("top", 0) > 1800:
                    break
                words = line.get("words", [])
                if not words:
                    continue
                # A new year header ends the current table.
                exact_years = sum(
                    bool(re.fullmatch(r"(?:19|20)\d{2}", re.sub(r"\D", "", _normalize_ocr_token(w.get("text", "")))))
                    for w in words
                )
                if exact_years >= 2:
                    break

                row_code = None
                for word in words:
                    token = re.sub(r"\D", "", _normalize_ocr_token(word.get("text", "")))
                    if token in RAS_CODE_LABELS:
                        row_code = token
                        break
                label_words = [
                    w for w in words
                    if (w["left"] + w["width"] / 2) < first_center - 24
                    and re.sub(r"\D", "", _normalize_ocr_token(w.get("text", ""))) != row_code
                    and not re.fullmatch(r"\d+", re.sub(r"\D", "", _normalize_ocr_token(w.get("text", ""))))
                ]
                raw_label = re.sub(r"\s+", " ", " ".join(str(w.get("text", "")) for w in label_words)).strip(" .:;|")
                if ras_form_page and not row_code:
                    continue
                label = RAS_CODE_LABELS.get(row_code or "", raw_label)
                label_alpha = re.findall(r"[А-Яа-яЁёA-Za-z]{3,}", label)
                if len(label_alpha) < 1 or len(label) > 220:
                    continue

                values: list[str] = []
                present = 0
                for col in range(len(years)):
                    col_words = []
                    for word in words:
                        center = word["left"] + word["width"] / 2
                        token_digits = re.sub(r"\D", "", _normalize_ocr_token(word.get("text", "")))
                        if token_digits == row_code or token_digits in RAS_CODE_LABELS:
                            continue
                        if boundaries[col] <= center < boundaries[col + 1] and _ocr_word_number(word) is not None:
                            col_words.append(word)
                    value = _join_ocr_number_words(col_words)
                    ceiling = 20_000_000_000 if ras_form_page else 20_000_000_000_000_000
                    if value is None or abs(value) > ceiling:
                        values.append("")
                    else:
                        values.append(str(int(value)) if value.is_integer() else str(value))
                        present += 1
                minimum_present = 2 if ras_form_page else 1
                row_tuple = tuple([label, *values])
                numeric_values = [float(value) for value in values if value not in {"", None}]
                consistent = True
                nonzero = [abs(value) for value in numeric_values if value != 0]
                if len(nonzero) >= 2 and max(nonzero) / max(min(nonzero), 1) > 50:
                    consistent = False
                if present >= minimum_present and consistent and row_tuple not in seen_rows:
                    rows.append(list(row_tuple))
                    seen_rows.add(row_tuple)
            if len(rows) >= 3:
                output.append({
                    "page": page["page"],
                    "table_index": len(output),
                    "rows": rows,
                    "row_count": len(rows),
                    "column_count": len(rows[0]),
                    "context": page.get("text", "")[:700],
                    "source_type": "ocr_coordinate_table",
                    "confidence": round(min(0.92, 0.55 + (page.get("ocr_quality") or 0) / 250), 2),
                })
                break
    return output

def parse_pdf(path: Path, progress: ProgressCallback) -> dict[str, Any]:
    progress(6, "Открытие PDF и проверка текстового слоя")
    doc = fitz.open(path)
    total_pages = len(doc)
    pages: list[dict[str, Any]] = []
    ocr_pages = 0
    total_images = 0
    visual_pages = 0
    ocr_qualities: list[float] = []

    scan_only_document = False
    if total_pages:
        sample_count = min(total_pages, 5)
        sample_chars = sum(len((doc[i].get_text("text", sort=True) or "").strip()) for i in range(sample_count))
        scan_only_document = sample_chars < 200

    configured_limit = settings.ocr_max_pages
    ocr_page_limit = total_pages if configured_limit <= 0 else min(total_pages, configured_limit)

    for index, page in enumerate(doc):
        text = page.get_text("text", sort=True) or ""
        image_count = len(page.get_images(full=True))
        total_images += image_count
        if image_count:
            visual_pages += 1
        used_ocr = False
        ocr_lines: list[dict[str, Any]] = []
        ocr_confidence = None
        ocr_quality = None
        ocr_method = None

        should_ocr = (
            settings.enable_ocr
            and index < ocr_page_limit
            and (len(text.strip()) < settings.ocr_min_text_chars or (settings.ocr_visuals and image_count > 0))
        )
        if should_ocr:
            try:
                from PIL import Image

                form_hint = index < settings.ocr_primary_form_pages
                scale = settings.ocr_form_dpi_scale if form_hint else settings.ocr_text_dpi_scale
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(max(scale, 2.4), max(scale, 2.4)),
                    alpha=False,
                    colorspace=fitz.csGRAY,
                )
                image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
                recognized = recognize_page(image, settings.ocr_language, form_hint=form_hint)
                if recognized.text:
                    if len(text.strip()) < settings.ocr_min_text_chars:
                        text = recognized.text
                    elif recognized.text not in text:
                        text = text.rstrip() + "\n\n[OCR визуальных элементов]\n" + recognized.text
                    ocr_lines = recognized.lines
                    ocr_confidence = recognized.confidence
                    ocr_quality = recognized.quality
                    ocr_method = recognized.method
                    ocr_qualities.append(recognized.quality)
                    used_ocr = True
                    ocr_pages += 1
            except Exception as exc:
                # The page remains available for visual inspection even if OCR fails.
                ocr_method = f"error: {type(exc).__name__}"

        pages.append({
            "page": index + 1,
            "text": text,
            "char_count": len(text),
            "ocr": used_ocr,
            "ocr_confidence": ocr_confidence,
            "ocr_quality": ocr_quality,
            "ocr_method": ocr_method,
            "image_count": image_count,
            "ocr_lines": ocr_lines,
        })
        if index % max(1, total_pages // 18) == 0:
            progress(6 + int((index + 1) / max(total_pages, 1) * 34), f"OCR и извлечение текста: страница {index + 1} из {total_pages}")
    doc.close()

    tables: list[dict[str, Any]] = extract_ocr_tables(pages) if scan_only_document else []
    # pdfplumber cannot recover table cells from image-only scans. Skipping that
    # pass makes full OCR faster and prevents empty/noisy pseudo-tables.
    if not scan_only_document:
        progress(41, "Распознавание таблиц по координатам PDF")
        with pdfplumber.open(path) as pdf:
            for page_index, page in enumerate(pdf.pages):
                try:
                    extracted = page.extract_tables(
                        table_settings={
                            "vertical_strategy": "lines",
                            "horizontal_strategy": "lines",
                            "intersection_tolerance": 5,
                            "snap_tolerance": 4,
                            "join_tolerance": 4,
                        }
                    )
                    if not extracted:
                        extracted = page.extract_tables(
                            table_settings={
                                "vertical_strategy": "text",
                                "horizontal_strategy": "text",
                                "min_words_vertical": 2,
                                "min_words_horizontal": 1,
                            }
                        )
                    for table_index, raw_table in enumerate(extracted[:12]):
                        normalized = rows_from_table(raw_table, page_index + 1, table_index)
                        if normalized:
                            normalized["context"] = infer_table_context(pages[page_index]["text"], normalized["rows"])
                            tables.append(normalized)
                except Exception:
                    continue
                if page_index % max(1, total_pages // 12) == 0:
                    progress(41 + int((page_index + 1) / max(total_pages, 1) * 15), f"Распознавание таблиц: страница {page_index + 1} из {total_pages}")

    full_text = "\n\n".join(page["text"] for page in pages)
    first_text = "\n".join(page["text"] for page in pages[:8])
    progress(58, "Классификация документа и нормализация показателей")
    financial_candidates: list[dict[str, Any]] = []
    operational_metrics: list[dict[str, Any]] = []
    for table in tables:
        financial, operational = extract_metrics_from_table(table)
        financial_candidates.extend(financial)
        operational_metrics.extend(operational)
    # Free-text regex extraction is only safe when the PDF already has a real
    # text layer. For scans, use coordinate tables and official RAS line codes;
    # otherwise OCR line wrapping can create plausible-looking but false values.
    if not scan_only_document:
        text_financial, text_operational = extract_text_metrics(pages)
        financial_candidates.extend(text_financial)
        operational_metrics.extend(text_operational)

    years = sorted(set(YEAR_RE.findall(full_text)))
    normalized_full = normalize_label(full_text)
    metadata = {
        "filename": path.name,
        "page_count": total_pages,
        "text_pages": sum(1 for page in pages if page["char_count"] > 40),
        "ocr_pages": ocr_pages,
        "ocr_average_quality": round(sum(ocr_qualities) / len(ocr_qualities), 1) if ocr_qualities else None,
        "visual_pages": visual_pages,
        "image_count": total_images,
        "years": years,
        "company": identify_company(first_text, path.stem),
        "document_type": classify_document(full_text),
        "reporting_year": infer_reporting_year(first_text, years),
        "has_risk_section": "управление рисками" in normalized_full or "risk management" in normalized_full,
        "has_audit_reference": "аудиторское заключение" in normalized_full or "auditor" in normalized_full,
        "has_financial_statements_reference": "финансовая отчетность" in normalized_full or "financial statements" in normalized_full,
        "text_layer_quality": round(sum(page["char_count"] for page in pages) / max(total_pages, 1), 1),
    }
    if metadata["document_type"] == "ras_financial_statements" or "бухгалтерский баланс" in normalized_full:
        coordinate_ras = extract_ras_metrics_from_ocr_lines(pages, metadata.get("reporting_year"))
        if coordinate_ras:
            authoritative_keys = {item["key"] for item in coordinate_ras}
            financial_candidates = [
                item for item in financial_candidates
                if item.get("key") not in authoritative_keys or item.get("source_type") == "ras_coordinate_ocr"
            ]
            financial_candidates.extend(coordinate_ras)
        else:
            financial_candidates.extend(extract_ras_form_metrics(pages, metadata.get("reporting_year")))

    limitations = []
    if ocr_pages:
        average_quality = metadata.get("ocr_average_quality") or 0
        if average_quality < settings.ocr_quality_warning:
            limitations.append(
                f"Средняя оценка качества OCR составляет {average_quality:.0f}/100. Проверяйте показатели по страницам-источникам или загрузите более четкий PDF."
            )
    if metadata["text_pages"] < total_pages * 0.7:
        if scan_only_document and ocr_page_limit < total_pages:
            limitations.append(f"OCR выполнен для первых {ocr_page_limit} страниц из {total_pages} согласно настройке OCR_MAX_PAGES.")
        elif not settings.enable_ocr:
            limitations.append("Документ не содержит качественного текстового слоя, а OCR отключен.")
    if metadata["document_type"] == "annual_report" and (
        "представлены в раскрываемой консолидированной финансовой отчетности" in normalized_full
        or len(financial_candidates) < 5
    ):
        limitations.append("Годовой отчет не содержит полного комплекта форм финансовой отчетности. Для расчета всех коэффициентов загрузите отдельную отчетность по МСФО/РСБУ.")
    if scan_only_document and not operational_metrics:
        limitations.append(
            "Непроверенные названия строк из OCR-таблиц скрыты. Для финансовых форм используются только официальные коды строк и канонические наименования."
        )
    if not tables and not scan_only_document:
        limitations.append("Таблицы не распознаны автоматически. Проверьте сложную верстку документа.")

    return {
        "metadata": metadata,
        "pages": pages,
        "headings": detect_headings(pages),
        "tables": tables,
        "financial_candidates": financial_candidates,
        "operational_metrics": operational_metrics,
        "narrative": extract_narrative_facts(pages),
        "limitations": limitations,
        "full_text": full_text,
    }


def dataframe_to_table(df: pd.DataFrame, sheet_name: str) -> dict[str, Any]:
    clean = df.fillna("").astype(str)
    rows = [list(clean.columns)] + clean.values.tolist()
    return {
        "page": None,
        "sheet": sheet_name,
        "table_index": 0,
        "rows": rows[:1000],
        "row_count": len(rows),
        "column_count": len(clean.columns),
    }


def parse_spreadsheet(path: Path, progress: ProgressCallback) -> dict[str, Any]:
    progress(12, "Чтение таблицы")
    suffix = path.suffix.lower()
    sheets: dict[str, pd.DataFrame]
    if suffix == ".csv":
        last_error = None
        df = None
        for encoding in ("utf-8-sig", "utf-8", "cp1251"):
            try:
                df = pd.read_csv(path, encoding=encoding, sep=None, engine="python")
                break
            except Exception as exc:
                last_error = exc
        if df is None:
            raise ValueError(f"Не удалось прочитать CSV: {last_error}")
        sheets = {"CSV": df}
    else:
        sheets = pd.read_excel(path, sheet_name=None, header=None)

    tables = []
    financial_candidates = []
    operational = []
    all_text = []
    for index, (sheet_name, df) in enumerate(sheets.items()):
        progress(15 + int((index + 1) / max(len(sheets), 1) * 40), f"Обработка листа «{sheet_name}»")
        df = df.dropna(how="all").dropna(axis=1, how="all")
        if df.empty:
            continue
        rows = [["" if pd.isna(value) else str(value) for value in row] for row in df.values.tolist()]
        table = {
            "page": None,
            "sheet": sheet_name,
            "table_index": index,
            "rows": rows[:1000],
            "row_count": len(rows),
            "column_count": max((len(row) for row in rows), default=0),
        }
        tables.append(table)
        financial, ops = extract_metrics_from_table(table)
        financial_candidates.extend(financial)
        operational.extend(ops)
        all_text.extend(" ".join(row) for row in rows)

    text = "\n".join(all_text)
    years = sorted(set(YEAR_RE.findall(text)))
    metadata = {
        "filename": path.name,
        "page_count": None,
        "sheet_count": len(sheets),
        "text_pages": 0,
        "ocr_pages": 0,
        "visual_pages": 0,
        "image_count": 0,
        "years": years,
        "company": path.stem,
        "document_type": "spreadsheet_financial_data",
        "reporting_year": int(max(years)) if years else None,
        "has_risk_section": False,
        "has_audit_reference": False,
        "has_financial_statements_reference": bool(financial_candidates),
        "text_layer_quality": None,
    }
    return {
        "metadata": metadata,
        "pages": [],
        "headings": [{"title": name, "page": None} for name in sheets],
        "tables": tables,
        "financial_candidates": financial_candidates,
        "operational_metrics": operational,
        "narrative": {"risks": [], "strategy": [], "esg": [], "governance": []},
        "limitations": [] if financial_candidates else ["Не удалось автоматически сопоставить финансовые строки. Проверьте структуру таблицы."],
        "full_text": text,
    }


def parse_document(path: Path, progress: ProgressCallback) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path, progress)
    if suffix in {".xlsx", ".xls", ".csv"}:
        return parse_spreadsheet(path, progress)
    raise ValueError("Поддерживаются PDF, XLSX, XLS и CSV.")

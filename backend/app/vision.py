from __future__ import annotations

import base64
import io
import math
import re
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageDraw, ImageFont

from .ai import compatible_chat
from .config import settings
from .financial import DISPLAY_NAMES, normalize_label, parse_number


VISION_SYSTEM_PROMPT = """Ты — модуль визуальной транскрипции финансовой отчетности РСБУ и МСФО.
Твоя единственная задача — переписать видимые строки основных финансовых форм и их числа.
Не рассчитывай коэффициенты, не делай выводов, не исправляй числа по памяти и не используй сведения о компании извне.
Читай заголовки столбцов, единицу измерения, знак/скобки, код строки РСБУ и физический номер страницы.
Возвращай только JSON:
{
  "document_standard": "ras" или "ifrs",
  "company": "видимое наименование или null",
  "reporting_year": 2025,
  "metrics": [
    {"key":"assets", "name":"Итого активы", "row_code":"1600 или null", "unit":"тыс. руб.",
     "values":{"2025":123,"2024":120}, "page":8, "source_row":"видимая строка"}
  ]
}
Допустимые key: %s
Если строка или цифра не видна надежно — пропусти ее. Не возвращай приблизительные значения.""" % ", ".join(sorted(DISPLAY_NAMES))


VISION_LOCATOR_PROMPT = """Ты находишь основные формы финансовой отчетности на контактных листах PDF.
Не извлекай числа и не анализируй компанию. Прочитай подписи страниц на миниатюрах и верни только JSON:
{"statement_pages":[{"page":8,"kind":"balance"},{"page":10,"kind":"pnl"},{"page":12,"kind":"cashflow"}],"standard":"ras|ifrs|null"}
kind допускает только balance, pnl, cashflow, equity_changes, notes. Указывай физический номер PDF, напечатанный над миниатюрой. Не включай оглавление, аудиторское заключение и страницы, которые только упоминают форму."""


def _page_kind(text: str) -> str | None:
    normalized = normalize_label(text)
    groups = {
        "balance": ("бухгалтерский баланс", "отчет о финансовом положении", "statement of financial position", "balance sheet"),
        "pnl": ("отчет о финансовых результатах", "отчет о прибылях и убытках", "отчет о совокупном доходе", "statement of profit", "income statement", "statement of comprehensive income"),
        "cashflow": ("отчет о движении денежных средств", "statement of cash flows", "cash flow statement"),
        "equity_changes": ("отчет об изменениях капитала", "statement of changes in equity"),
    }
    for kind, titles in groups.items():
        if any(title in normalized for title in titles):
            return kind
    return None


def _candidate_pages(pages: list[dict[str, Any]], maximum: int) -> list[int]:
    ranked: list[tuple[int, int]] = []
    for page in pages:
        text = str(page.get("text", ""))
        normalized = normalize_label(text)
        codes = len(set(re.findall(r"(?<!\d)(?:1[1-7]\d0|2[1-5]\d0|4[1-5]\d0)(?!\d)", text)))
        titles = 1 if _page_kind(text) else 0
        score = codes * 4 + titles * 30
        if score:
            ranked.append((score, int(page.get("page", 1))))
    if not ranked:
        # Do not assume that financial forms are at the beginning.  Evenly
        # spaced pages are a safer last local fallback until the visual locator
        # identifies exact forms.
        if not pages:
            return []
        indexes = sorted({round(i * (len(pages) - 1) / max(maximum - 1, 1)) for i in range(min(maximum, len(pages)))})
        return [int(pages[index].get("page", index + 1)) for index in indexes]
    output: list[int] = []
    page_numbers = {int(page.get("page", 1)) for page in pages}
    for _score, page in sorted(ranked, reverse=True):
        for candidate in (page, page + 1, page - 1):
            if candidate in page_numbers and candidate not in output:
                output.append(candidate)
                if len(output) >= maximum:
                    return output
    return output


def _contact_sheet(document: fitz.Document, page_numbers: list[int]) -> bytes:
    columns = 3
    tile_width, tile_height, label_height = 360, 470, 28
    rows = math.ceil(len(page_numbers) / columns)
    canvas = Image.new("RGB", (columns * tile_width, rows * (tile_height + label_height)), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, number in enumerate(page_numbers):
        page = document[number - 1]
        pix = page.get_pixmap(matrix=fitz.Matrix(0.72, 0.72), alpha=False, colorspace=fitz.csRGB)
        image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        image.thumbnail((tile_width - 12, tile_height - 12), Image.Resampling.LANCZOS)
        x = (index % columns) * tile_width
        y = (index // columns) * (tile_height + label_height)
        draw.rectangle((x, y, x + tile_width - 1, y + label_height - 1), fill="#0E4B4B")
        draw.text((x + 8, y + 8), f"PDF PAGE {number}", fill="white", font=font)
        canvas.paste(image, (x + (tile_width - image.width) // 2, y + label_height + 6))
    buffer = io.BytesIO()
    canvas.save(buffer, format="JPEG", quality=76, optimize=True)
    return buffer.getvalue()


async def _locate_statement_pages(path: Path, total_pages: int, reporting_year: int | None) -> tuple[list[int], dict[str, Any]]:
    maximum = max(1, settings.vision_locator_max_pages)
    if total_pages <= maximum:
        inspected = list(range(1, total_pages + 1))
    else:
        inspected = sorted({1, total_pages, *(
            round(1 + i * (total_pages - 1) / max(maximum - 1, 1)) for i in range(maximum)
        )})
    batch_size = max(4, settings.vision_contact_sheet_pages)
    document = fitz.open(path)
    content: list[dict[str, Any]] = [{
        "type": "text",
        "text": f"Отчетный год: {reporting_year or 'не определен'}. Найди физические страницы основных форм на контактных листах.",
    }]
    try:
        for start in range(0, len(inspected), batch_size):
            batch = inspected[start:start + batch_size]
            encoded = base64.b64encode(_contact_sheet(document, batch)).decode("ascii")
            content.extend([
                {"type": "text", "text": f"Контактный лист: страницы {batch[0]}-{batch[-1]}"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
            ])
    finally:
        document.close()
    response = await compatible_chat(
        [{"role": "system", "content": VISION_LOCATOR_PROMPT}, {"role": "user", "content": content}],
        max_tokens=2500,
        model=settings.vision_model,
    )
    located: list[int] = []
    kinds: dict[str, list[int]] = {}
    for item in response.get("statement_pages", []):
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("page"))
        except (TypeError, ValueError):
            continue
        kind = str(item.get("kind") or "")
        if number not in inspected or kind not in {"balance", "pnl", "cashflow", "equity_changes", "notes"}:
            continue
        if number not in located:
            located.append(number)
        kinds.setdefault(kind, []).append(number)
    return located, {
        "status": "completed", "inspected_pages": len(inspected), "located_pages": located,
        "kinds": kinds, "model": response.get("model"), "provider": response.get("provider"),
    }


async def recover_statement_candidates(path: Path, pages: list[dict[str, Any]], reporting_year: int | None) -> tuple[str | None, list[dict[str, Any]], dict[str, Any]]:
    maximum = max(1, settings.vision_max_pages)
    local_pages = _candidate_pages(pages, maximum)
    local_kinds = {_page_kind(str(page.get("text", ""))) for page in pages if int(page.get("page", 0) or 0) in local_pages}
    local_kinds.discard(None)
    locator_diagnostics: dict[str, Any] = {"status": "not_needed"}
    located_pages: list[int] = []
    if len(local_kinds & {"balance", "pnl", "cashflow"}) < 2:
        located_pages, locator_diagnostics = await _locate_statement_pages(path, len(pages), reporting_year)
    selected_pages = []
    for number in [*located_pages, *local_pages]:
        if number not in selected_pages:
            selected_pages.append(number)
        if len(selected_pages) >= maximum:
            break
    document = fitz.open(path)
    content: list[dict[str, Any]] = [{
        "type": "text",
        "text": f"Отчетный год по локальному извлечению: {reporting_year or 'не определен'}. Ниже страницы основных форм.",
    }]
    for number in selected_pages:
        if not (1 <= number <= len(document)):
            continue
        page = document[number - 1]
        pix = page.get_pixmap(matrix=fitz.Matrix(2.2, 2.2), alpha=False, colorspace=fitz.csRGB)
        encoded = base64.b64encode(pix.tobytes("jpeg", jpg_quality=86)).decode("ascii")
        content.extend([
            {"type": "text", "text": f"Физическая страница PDF: {number}"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
        ])
    document.close()
    if len(content) == 1:
        return None, [], {"pages": [], "reason": "no_renderable_pages"}
    response = await compatible_chat(
        [{"role": "system", "content": VISION_SYSTEM_PROMPT}, {"role": "user", "content": content}],
        max_tokens=12000,
        model=settings.vision_model,
    )
    standard = str(response.get("document_standard") or "").lower()
    if standard not in {"ras", "ifrs"}:
        standard = None
    candidates: list[dict[str, Any]] = []
    for raw in response.get("metrics", []):
        if not isinstance(raw, dict) or raw.get("key") not in DISPLAY_NAMES:
            continue
        values = {}
        for year, value in (raw.get("values") or {}).items():
            parsed = parse_number(value)
            if re.fullmatch(r"(?:19|20)\d{2}", str(year)) and parsed is not None:
                values[str(year)] = parsed
        page = raw.get("page")
        try:
            page = int(page)
        except (TypeError, ValueError):
            page = None
        if not values or page not in selected_pages:
            continue
        candidates.append({
            "key": raw["key"], "name": DISPLAY_NAMES[raw["key"]],
            "unit": raw.get("unit") or "тыс. руб.", "values": values,
            "source_pages": [page], "source_type": "ai_vision_recovery",
            "confidence": 0.82, "row_code": raw.get("row_code"),
            "source_row": raw.get("source_row"),
            "provenance": [{
                "page": page, "row": raw.get("source_row"), "row_code": raw.get("row_code"),
                "extraction_method": "ai_vision_recovery", "confidence": 0.82,
            }],
        })
    diagnostics = {
        "pages": selected_pages, "model": response.get("model"),
        "provider": response.get("provider"), "candidate_count": len(candidates),
        "local_candidate_pages": local_pages, "locator": locator_diagnostics,
    }
    return standard, candidates, diagnostics

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np
from PIL import Image, ImageFilter, ImageOps


@dataclass
class OCRResult:
    text: str
    lines: list[dict[str, Any]]
    confidence: float
    quality: float
    method: str


# Latin glyphs that Tesseract sometimes inserts into otherwise Cyrillic words.
_LATIN_TO_CYRILLIC = str.maketrans({
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К",
    "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х",
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
})

# Frequent accounting vocabulary used both for quality scoring and Tesseract's
# user-word list. The file is also shipped next to this module.
_FINANCIAL_WORDS = {
    "бухгалтерский", "баланс", "актив", "пассив", "оборотные", "внеоборотные",
    "активы", "обязательства", "капитал", "выручка", "себестоимость", "прибыль",
    "убыток", "дебиторская", "кредиторская", "задолженность", "денежные", "средства",
    "эквиваленты", "запасы", "инвестиции", "финансовые", "вложения", "налог",
    "операционный", "инвестиционный", "финансовый", "денежный", "поток", "платежи",
    "поступления", "заемные", "долгосрочные", "краткосрочные", "пояснения",
    "аудиторское", "заключение", "отчетность", "российским", "стандартам",
    "организация", "общество", "компания", "тысяч", "рублей", "показатель",
    "наименование", "текущих", "операций", "чистая", "валовая", "продаж",
}


def _otsu_threshold(image: Image.Image) -> Image.Image:
    """Return a clean black/white image using Otsu's threshold."""
    array = np.asarray(image.convert("L"), dtype=np.uint8)
    histogram = np.bincount(array.ravel(), minlength=256).astype(np.float64)
    total = array.size
    sum_total = float(np.dot(np.arange(256), histogram))
    sum_background = 0.0
    weight_background = 0.0
    best_variance = -1.0
    threshold = 180
    for level in range(256):
        weight_background += histogram[level]
        if weight_background == 0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break
        sum_background += level * histogram[level]
        mean_background = sum_background / weight_background
        mean_foreground = (sum_total - sum_background) / weight_foreground
        variance = weight_background * weight_foreground * (mean_background - mean_foreground) ** 2
        if variance > best_variance:
            best_variance = variance
            threshold = level
    # Slight upward bias preserves thin Cyrillic strokes on pale scans.
    threshold = min(235, threshold + 7)
    binary = np.where(array > threshold, 255, 0).astype(np.uint8)
    return Image.fromarray(binary, mode="L")


def prepare_ocr_images(image: Image.Image) -> tuple[Image.Image, Image.Image]:
    """Create grayscale and binarized variants tuned for scanned reports."""
    gray = ImageOps.exif_transpose(image)
    gray = ImageOps.grayscale(gray)
    gray = ImageOps.autocontrast(gray, cutoff=0.45)
    gray = gray.filter(ImageFilter.MedianFilter(size=3))
    gray = gray.filter(ImageFilter.UnsharpMask(radius=1.15, percent=175, threshold=2))
    binary = _otsu_threshold(gray)
    return gray, binary


def _repair_mixed_alphabet_token(token: str) -> str:
    """Repair Latin lookalikes only inside predominantly Cyrillic tokens."""
    if not re.search(r"[А-Яа-яЁё]", token):
        return token
    latin = len(re.findall(r"[A-Za-z]", token))
    cyr = len(re.findall(r"[А-Яа-яЁё]", token))
    if cyr >= latin:
        return token.translate(_LATIN_TO_CYRILLIC)
    return token


def _clean_line(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\u00a0", " ")
    text = text.replace("−", "-").replace("‐", "-")
    text = " ".join(_repair_mixed_alphabet_token(token) for token in text.split())
    text = re.sub(r"[ \t]+", " ", text).strip()
    # Remove isolated OCR border characters while keeping real punctuation.
    text = re.sub(r"^(?:[|¦Il1]\s*){2,}", "", text)
    text = re.sub(r"(?:\s*[|¦]){2,}$", "", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def clean_ocr_text(text: str) -> str:
    """Repair line breaks/hyphenation and suppress obvious OCR debris."""
    raw_lines = [_clean_line(line) for line in text.splitlines()]
    lines: list[str] = []
    for line in raw_lines:
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if re.fullmatch(r"[._=|¦~\-–—\s]{4,}", line):
            continue
        if len(line) <= 2 and not re.search(r"\d", line):
            continue
        # Drop obvious scan furniture / single-column table borders.
        if len(re.findall(r"[А-Яа-яЁёA-Za-z]", line)) == 0 and len(line) > 30:
            continue
        lines.append(line)

    output: list[str] = []
    for line in lines:
        if output and output[-1].endswith("-") and re.match(r"^[а-яёa-z]", line, re.I):
            output[-1] = output[-1][:-1] + line
        else:
            output.append(line)
    text = "\n".join(output)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _build_lines(data: dict[str, list[Any]], min_confidence: float = 15.0) -> tuple[list[dict[str, Any]], list[float]]:
    grouped: dict[tuple[int, int, int, int], list[dict[str, Any]]] = {}
    confidences: list[float] = []
    count = len(data.get("text", []))
    for index in range(count):
        raw = str(data["text"][index] or "").strip()
        try:
            confidence = float(data["conf"][index])
        except Exception:
            confidence = -1.0
        if not raw or confidence < min_confidence:
            continue
        key = (
            int(data["page_num"][index]),
            int(data["block_num"][index]),
            int(data["par_num"][index]),
            int(data["line_num"][index]),
        )
        word = {
            "text": _repair_mixed_alphabet_token(raw),
            "left": int(data["left"][index]),
            "top": int(data["top"][index]),
            "width": int(data["width"][index]),
            "height": int(data["height"][index]),
            "conf": confidence,
        }
        grouped.setdefault(key, []).append(word)
        confidences.append(confidence)

    lines: list[dict[str, Any]] = []
    for words in grouped.values():
        words.sort(key=lambda word: word["left"])
        text = _clean_line(" ".join(word["text"] for word in words))
        if not text:
            continue
        line_conf = round(mean(word["conf"] for word in words), 1)
        lines.append({
            "text": text,
            "top": min(word["top"] for word in words),
            "left": min(word["left"] for word in words),
            "words": words,
            "confidence": line_conf,
        })
    lines.sort(key=lambda line: (line["top"], line["left"]))
    return lines, confidences


def _word_plausibility(words: list[str]) -> float:
    if not words:
        return 0.0
    plausible = 0
    for word in words:
        normalized = word.lower().replace("ё", "е")
        vowels = len(re.findall(r"[аеёиоуыэюя]", normalized))
        cyr = len(re.findall(r"[а-яё]", normalized))
        if normalized in _FINANCIAL_WORDS:
            plausible += 2
        elif cyr >= 3 and vowels >= 1 and not re.search(r"(.)\1\1", normalized):
            plausible += 1
    return plausible / max(len(words), 1)


def _quality_score(text: str, confidences: list[float]) -> tuple[float, float]:
    tokens = re.findall(r"[А-Яа-яЁёA-Za-z0-9]+", text)
    alpha = [token for token in tokens if re.search(r"[А-Яа-яЁёA-Za-z]", token)]
    cyrillic = [token for token in alpha if re.search(r"[А-Яа-яЁё]", token)]
    numeric = [token for token in tokens if token.isdigit()]
    mean_confidence = mean(confidences) if confidences else 0.0
    if not tokens:
        return mean_confidence, 0.0

    alpha_ratio = len(alpha) / len(tokens)
    cyrillic_ratio = len(cyrillic) / max(len(alpha), 1)
    numeric_ratio = len(numeric) / len(tokens)
    short_noise = sum(1 for token in tokens if len(token) == 1 and not token.isdigit()) / len(tokens)
    mixed_noise = sum(
        1 for token in alpha
        if re.search(r"[А-Яа-яЁё]", token) and re.search(r"[A-Za-z]", token)
    ) / max(len(alpha), 1)
    repeated = 0.0
    if alpha:
        counts: dict[str, int] = {}
        for token in alpha:
            key = token.lower()
            counts[key] = counts.get(key, 0) + 1
        repeated = max(counts.values()) / len(alpha)
    length_bonus = min(12.0, len(tokens) / 18.0)
    plausibility = _word_plausibility(cyrillic)
    quality = (
        mean_confidence * 0.62
        + alpha_ratio * 13
        + cyrillic_ratio * 8
        + plausibility * 12
        + length_bonus
        - max(0.0, numeric_ratio - 0.70) * 12
        - short_noise * 25
        - mixed_noise * 18
        - max(0.0, repeated - 0.20) * 30
    )
    return round(mean_confidence, 1), round(max(0.0, min(100.0, quality)), 1)


def _tesseract_config(psm: int) -> str:
    user_words = Path(__file__).with_name("ocr_financial_words.txt")
    extra = f' --user-words "{user_words}"' if user_words.exists() else ""
    return f"--oem 1 --psm {psm} -c preserve_interword_spaces=1{extra}"


def run_ocr_variant(image: Image.Image, language: str, psm: int, method: str) -> OCRResult:
    import pytesseract
    from pytesseract import Output

    data = pytesseract.image_to_data(
        image,
        lang=language,
        config=_tesseract_config(psm),
        output_type=Output.DICT,
    )
    lines, confidences = _build_lines(data)
    for line in lines:
        line["ocr_method"] = method
    text = clean_ocr_text("\n".join(line["text"] for line in lines))
    confidence, quality = _quality_score(text, confidences)
    return OCRResult(text=text, lines=lines, confidence=confidence, quality=quality, method=method)


def recognize_page(image: Image.Image, language: str, form_hint: bool = False) -> OCRResult:
    """Recognize a scanned page using adaptive multi-pass OCR.

    Accounting forms are read with both automatic-layout and sparse-column
    modes. Their coordinate lines are merged, allowing the financial parser to
    select the most accurate row from either pass. Ordinary prose normally uses
    a single high-quality pass and only falls back when confidence is low.
    """
    gray, binary = prepare_ocr_images(image)
    candidates: list[OCRResult] = [run_ocr_variant(gray, language, 3, "gray-psm3")]

    if form_hint:
        candidates.append(run_ocr_variant(gray, language, 4, "gray-psm4"))
        candidates.append(run_ocr_variant(binary, language, 6, "binary-psm6"))
    elif candidates[0].quality < 63:
        candidates.append(run_ocr_variant(gray, language, 4, "gray-psm4"))
        candidates.append(run_ocr_variant(binary, language, 6, "binary-psm6"))
    elif candidates[0].quality < 74:
        candidates.append(run_ocr_variant(binary, language, 3, "binary-psm3"))

    best = max(candidates, key=lambda item: (item.quality, item.confidence, len(item.text)))

    # Merge coordinate lines from all passes. Near-identical duplicates are
    # retained only once, but alternative row segmentations remain available.
    merged_lines: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for candidate in sorted(candidates, key=lambda item: item.quality, reverse=True):
        for line in candidate.lines:
            normalized = re.sub(r"\W+", "", line.get("text", "").lower())
            key = (int(round(line.get("top", 0) / 12)), normalized)
            if not normalized or key in seen:
                continue
            seen.add(key)
            merged_lines.append(line)
    merged_lines.sort(key=lambda line: (line.get("top", 0), line.get("left", 0), -line.get("confidence", 0)))

    # Tesseract sometimes splits one visual table row into several line objects
    # (label/code at the left and annual values at the right). Recombine segments
    # with nearly identical vertical coordinates within each OCR method.
    visual_rows: list[dict[str, Any]] = []
    by_method: dict[str, list[dict[str, Any]]] = {}
    for line in merged_lines:
        by_method.setdefault(str(line.get("ocr_method", "")), []).append(line)
    for method, method_lines in by_method.items():
        clusters: list[list[dict[str, Any]]] = []
        for line in sorted(method_lines, key=lambda item: item.get("top", 0)):
            if not clusters or abs(line.get("top", 0) - clusters[-1][0].get("top", 0)) > 12:
                clusters.append([line])
            else:
                clusters[-1].append(line)
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            words = [word for line in cluster for word in line.get("words", [])]
            words.sort(key=lambda word: word.get("left", 0))
            if not words:
                continue
            text = _clean_line(" ".join(str(word.get("text", "")) for word in words))
            visual_rows.append({
                "text": text,
                "top": min(line.get("top", 0) for line in cluster),
                "left": min(line.get("left", 0) for line in cluster),
                "words": words,
                "confidence": round(mean(line.get("confidence", 0) for line in cluster), 1),
                "ocr_method": method + "-merged-row",
            })
    merged_lines.extend(visual_rows)
    merged_lines.sort(key=lambda line: (line.get("top", 0), line.get("left", 0), -line.get("confidence", 0)))

    return OCRResult(
        text=best.text,
        lines=merged_lines,
        confidence=best.confidence,
        quality=best.quality,
        method="+".join(item.method for item in candidates),
    )


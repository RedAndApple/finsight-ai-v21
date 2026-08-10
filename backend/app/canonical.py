from __future__ import annotations
from copy import deepcopy
from typing import Any

UNIT_MULTIPLIERS = {"руб.": 1.0, "тыс. руб.": 1e3, "млн руб.": 1e6, "млрд руб.": 1e9, "RUB": 1.0}

def canonicalize_metrics(candidates: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build a stable auditable model without company-specific assumptions."""
    model = {}
    for key, raw in candidates.items():
        item = deepcopy(raw)
        item["key"] = key
        item["values"] = {str(y): float(v) for y, v in item.get("values", {}).items() if v is not None}
        pages = sorted({int(p) for p in item.get("source_pages", []) if p is not None})
        code = item.get("row_code") or item.get("code")
        item["provenance"] = item.get("provenance") or [{
            "document": item.get("source_document"), "page": page,
            "sheet": item.get("source_sheet"), "row": item.get("source_row"),
            "row_code": code, "extraction_method": item.get("source_type", "unknown"),
            "confidence": float(item.get("confidence", 0) or 0),
        } for page in (pages or [None])]
        item["source_pages"] = pages
        item["canonical_unit"] = item.get("unit")
        item["unit_multiplier"] = UNIT_MULTIPLIERS.get(str(item.get("unit")), 1.0)
        item["validation"] = {"status": "pending", "issues": []}
        model[key] = item
    return model

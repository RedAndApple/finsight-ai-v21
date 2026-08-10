from __future__ import annotations
from typing import Any

TRUSTED_SOURCES = {"bank_ras_coordinate_ocr", "ras_coordinate_ocr", "ras_form", "ras_ocr_form", "ifrs_primary_statement", "ifrs_disclosure_note", "pdf_table", "spreadsheet", "spreadsheet_table", "docx_table", "ai_vision_recovery", "manual", "derived_from_verified_rows", "reconciled_from_accounting_identity"}

def _value(model, key, year):
    try: return float(model[key]["values"][year])
    except (KeyError, TypeError, ValueError): return None

def validate_model(model: dict[str, dict[str, Any]], tolerance: float = 0.02) -> dict[str, Any]:
    issues, checks = [], []
    years = sorted({y for item in model.values() for y in item.get("values", {})})
    for item in model.values():
        row_issues = []
        confidence, source = float(item.get("confidence", 0) or 0), str(item.get("source_type") or "")
        if not item.get("values"): row_issues.append("no_values")
        if source.endswith("ocr") and confidence < 0.72: row_issues.append("low_ocr_confidence")
        elif confidence < 0.55 and source not in TRUSTED_SOURCES: row_issues.append("low_confidence")
        if any(abs(float(v)) > 1e15 for v in item.get("values", {}).values()): row_issues.append("implausible_magnitude")
        item["validation"] = {"status": "invalid" if row_issues else "valid", "issues": row_issues}

    def identity(name, left_key, right_keys, year):
        left, rights = _value(model, left_key, year), [_value(model, k, year) for k in right_keys]
        if left is None or any(v is None for v in rights):
            checks.append({"name": name, "year": year, "status": "not_tested"}); return
        right = sum(rights); delta = abs(left - right)
        status = "passed" if delta <= max(abs(left), abs(right), 1.0) * tolerance else "failed"
        checks.append({"name": name, "year": year, "status": status, "left": left, "right": right, "delta": delta})
        if status == "failed":
            issues.append({"severity": "error", "check": name, "year": year, "delta": delta})
            # Keep individually plausible rows available for calculation while
            # making the failed equation explicit.  Earlier versions
            # quarantined every member of one failed identity, so a single OCR
            # digit made ROA, ROE, liquidity and margins disappear at once.
            # Identity-aware reconciliation runs before this validator; a
            # remaining failure is therefore a visible warning, not permission
            # to silently erase the complete statement.
            for key in [left_key, *right_keys]:
                if key in model:
                    if model[key]["validation"]["status"] == "valid":
                        model[key]["validation"]["status"] = "warning"
                    model[key]["validation"]["issues"].append(f"accounting_identity_failed:{name}:{year}")
    for year in years:
        identity("assets_equals_sections", "assets", ["noncurrent_assets", "current_assets"], year)
        if "liabilities" in model and not ({"longterm_liabilities", "current_liabilities"} <= set(model)):
            identity("assets_equals_equity_and_total_liabilities", "assets", ["equity", "liabilities"], year)
        else:
            identity("assets_equals_equity_and_liabilities", "assets", ["equity", "longterm_liabilities", "current_liabilities"], year)
    valid = {k: v for k, v in model.items() if v["validation"]["status"] in {"valid", "warning"}}
    tested = [c for c in checks if c["status"] != "not_tested"]
    failed = [c for c in tested if c["status"] == "failed"]
    return {"status": "failed" if failed else ("passed" if tested else "partial"), "checks": checks,
            "issues": issues, "valid_metric_count": len(valid), "invalid_metric_count": len(model)-len(valid),
            "valid_metrics": valid}

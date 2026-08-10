from __future__ import annotations
from typing import Any

def calculate_trends(metrics: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for key, item in metrics.items():
        years = sorted((str(y) for y in item.get("values", {}) if str(y).isdigit()), key=int)
        for previous, current in zip(years, years[1:]):
            old, new = float(item["values"][previous]), float(item["values"][current])
            delta = new-old
            output.append({"key": key, "name": item.get("name", key), "from_year": previous, "to_year": current,
                "from_value": old, "to_value": new, "absolute_change": delta,
                "percent_change": None if old == 0 else delta/abs(old)*100, "unit": item.get("unit"),
                "provenance": item.get("provenance", [])})
    return output

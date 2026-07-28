#!/usr/bin/env python3
"""Evaluate normalized Mechanical mesh-quality statistics."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"status": "invalid", "errors": ["usage: evaluate_mesh_quality.py MESH.json"]}))
        return 2
    try:
        data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    except Exception as exc:
        print(json.dumps({"status": "invalid", "errors": [str(exc)]}))
        return 2

    if not isinstance(data, dict):
        print(json.dumps({"status": "invalid", "errors": ["root must be an object"]}))
        return 2
    gates = data.get("quality_gates", {})
    hard: list[dict] = []
    warnings: list[dict] = []

    def hard_max(field: str, default: float) -> None:
        value = data.get(field)
        limit = gates.get(field, default)
        if value is None:
            hard.append({"check": field, "reason": "missing"})
        elif value > limit:
            hard.append({"check": field, "value": value, "limit": limit})

    hard_max("nonpositive_jacobian_count", 0)
    hard_max("zero_or_negative_volume_count", 0)
    hard_max("unmeshed_active_body_count", 0)
    hard_max("invalid_contact_scope_count", 0)

    max_skew = data.get("maximum_skewness")
    skew_limit = gates.get("maximum_skewness", 0.9)
    if max_skew is not None and max_skew > skew_limit:
        target = hard if data.get("worst_skewness_in_critical_region", True) else warnings
        target.append({"check": "maximum_skewness", "value": max_skew, "limit": skew_limit})

    low_fraction = data.get("low_quality_element_fraction")
    low_limit = gates.get("maximum_low_quality_fraction", 0.001)
    if low_fraction is not None and low_fraction > low_limit:
        target = hard if data.get("low_quality_elements_in_critical_region", False) else warnings
        target.append({"check": "low_quality_element_fraction", "value": low_fraction, "limit": low_limit})

    if hard:
        status, code = "fail", 1
    elif warnings:
        status, code = "warning", 1
    else:
        status, code = "pass", 0
    print(json.dumps({"status": status, "hard_failures": hard, "warnings": warnings}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

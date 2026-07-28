#!/usr/bin/env python3
"""Compare the final two mesh levels for configured engineering metrics."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"status": "invalid", "errors": ["usage: evaluate_mesh_convergence.py CONVERGENCE.json"]}))
        return 2
    try:
        root = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
        data = root.get("mesh_convergence_data", root)
        levels = data["levels"]
        metrics = data["metrics"]
        if not isinstance(levels, list) or len(levels) < 3:
            raise ValueError("at least three ordered mesh levels are required")
        if not isinstance(metrics, list) or not metrics:
            raise ValueError("at least one convergence metric is required")
    except Exception as exc:
        print(json.dumps({"status": "invalid", "errors": [str(exc)]}))
        return 2

    medium, fine = levels[-2], levels[-1]
    checks: list[dict] = []
    failures: list[dict] = []
    try:
        for spec in metrics:
            name = spec["name"]
            tolerance = float(spec["tolerance_percent"])
            q_medium = float(medium["metrics"][name])
            q_fine = float(fine["metrics"][name])
            denominator = max(abs(q_fine), float(spec.get("epsilon", 1e-12)))
            change = 100.0 * abs(q_fine - q_medium) / denominator
            check = {
                "metric": name,
                "medium_level": medium.get("name"),
                "fine_level": fine.get("name"),
                "medium_value": q_medium,
                "fine_value": q_fine,
                "change_percent": change,
                "limit_percent": tolerance,
                "status": "pass" if change < tolerance else "fail",
            }
            checks.append(check)
            if check["status"] == "fail":
                failures.append(check)
    except Exception as exc:
        print(json.dumps({"status": "invalid", "errors": [str(exc)]}))
        return 2

    status = "fail" if failures else "pass"
    print(json.dumps({"status": status, "checks": checks, "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

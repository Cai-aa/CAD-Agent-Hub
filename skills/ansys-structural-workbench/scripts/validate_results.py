#!/usr/bin/env python3
"""Perform solver-state and global vector force-balance checks."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def vector(value: object, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label}.vector must contain three numbers")
    return [float(item) for item in value]


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"status": "invalid", "errors": ["usage: validate_results.py RESULTS.json"]}))
        return 2
    try:
        root = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
        data = root.get("validation_data", root)
        solver = data["solver"]
        applied = data["applied_forces"]
        reactions = data["reactions"]
        tolerance = float(data.get("validation", {}).get("force_balance_tolerance_percent", 0.5))
        if not isinstance(applied, list) or not applied or not isinstance(reactions, list) or not reactions:
            raise ValueError("applied_forces and reactions must be non-empty arrays")
        unit_set = {item.get("unit") for item in applied + reactions}
        if len(unit_set) != 1 or None in unit_set:
            raise ValueError("all force vectors must use one explicit unit")
        applied_vectors = [vector(item.get("vector"), f"applied_forces[{i}]") for i, item in enumerate(applied)]
        reaction_vectors = [vector(item.get("vector"), f"reactions[{i}]") for i, item in enumerate(reactions)]
    except Exception as exc:
        print(json.dumps({"status": "invalid", "errors": [str(exc)]}))
        return 2

    failures: list[dict] = []
    if not solver.get("run_completed") or solver.get("error_count", 0) != 0 or solver.get("final_state") != "converged":
        failures.append({"check": "solver_state", "observed": solver})

    residual = [sum(v[i] for v in applied_vectors + reaction_vectors) for i in range(3)]
    denominator = sum(math.sqrt(sum(component * component for component in v)) for v in applied_vectors)
    if denominator <= 0:
        print(json.dumps({"status": "invalid", "errors": ["total applied force magnitude must be positive"]}))
        return 2
    error_percent = 100.0 * math.sqrt(sum(component * component for component in residual)) / denominator
    if error_percent > tolerance:
        failures.append({"check": "force_balance", "error_percent": error_percent, "limit_percent": tolerance})

    status = "fail" if failures else "pass"
    print(json.dumps({
        "status": status,
        "checks": {
            "solver_state": solver,
            "force_balance": {
                "residual_vector": residual,
                "unit": next(iter(unit_set)),
                "error_percent": error_percent,
                "limit_percent": tolerance,
            },
        },
        "failures": failures,
    }, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

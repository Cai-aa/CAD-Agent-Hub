# Quality gates

## Status vocabulary

- `pass`: all mandatory checks proven.
- `warning`: solve/result may be usable, but a documented limitation remains.
- `fail`: a required correctness or quality criterion is violated.
- `blocked`: required data, tool capability, or authorization is missing.
- `unsupported`: the MCP cannot perform or prove the requested operation.

## Universal hard gates

- Units are explicit and consistent.
- Every active body has a valid material/section definition.
- Required selections and connections exist with validated scopes.
- Restraints and load paths are physically coherent.
- Mesh exists on every active body with no invalid elements.
- Required contact pairs are not unexpectedly Far Open before solve.
- Solver reaches the requested final converged state with no fatal errors.
- Extracted result units, scope, coordinate system, and time/mode are known.
- Vector reaction balance meets the configured tolerance.
- No reported artifact or value is inferred from an absent file/result.

## Default tolerances

Use only when the user or case profile has not supplied stricter criteria:

| Check | Default |
|---|---:|
| Force balance | < 0.5% |
| Moment balance | < 1.0% |
| Symmetric reaction mismatch | < 2.0% |
| Contact stabilization/parasitic reaction | < 0.1% applied load |
| Displacement mesh change | < 3.0% |
| Reaction/contact-force mesh change | < 2.0% |
| Energy mesh change | < 3.0% |
| Area-average stress/pressure mesh change | < 5.0% |
| Robust path stress mesh change | < 5-8% |

Do not use these defaults as design-code allowables.

## Force balance data contract

Normalize applied loads and reactions as vectors in one global unit system:

```json
{
  "solver": {"run_completed": true, "error_count": 0, "final_state": "converged"},
  "applied_forces": [{"name": "load", "vector": [30000, 0, 0], "unit": "N"}],
  "reactions": [
    {"name": "support_a", "vector": [-15000, 0, 0], "unit": "N"},
    {"name": "support_b", "vector": [-15000, 0, 0], "unit": "N"}
  ],
  "validation": {"force_balance_tolerance_percent": 0.5}
}
```

Run `scripts/validate_results.py`.

## Singularity handling

Flag peaks at sharp re-entrant corners, ideal point loads, fixed edges, contact edges, crack tips, and discontinuous constraints. Report them, but base mesh adequacy on robust nearby/path/averaged quantities and engineering context. Do not falsely declare a finite converged peak.

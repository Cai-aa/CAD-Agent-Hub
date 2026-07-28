# Structural analysis job specification

Normalize the request into this shape. Omit unused optional fields; never invent engineering limits.

```json
{
  "schema_version": "1.0",
  "task_name": "descriptive_name",
  "analysis_profiles": ["nonlinear_static", "contact"],
  "model": {
    "source": "existing_project",
    "project_path": "D:/cases/model.wbpj",
    "overwrite": false,
    "units": {"length": "mm", "force": "N", "stress": "MPa"}
  },
  "materials": [
    {
      "name": "steel",
      "model": "linear_elastic",
      "youngs_modulus": 210000,
      "poissons_ratio": 0.3,
      "density": 7.85e-09
    }
  ],
  "connections": [],
  "supports": [],
  "loads": [],
  "solution": {},
  "mesh": {
    "profile": "solid_general",
    "element_order": "quadratic",
    "method_policy": {
      "prefer": ["sweep", "multizone"],
      "fallback": "patch_conforming_tetra"
    },
    "quality_gates": {},
    "convergence": {"enabled": true, "levels": [], "metrics": []}
  },
  "validation": {
    "force_balance_tolerance_percent": 0.5,
    "criteria": []
  },
  "outputs": ["solver_diagnostics", "analysis_report"]
}
```

## Required fields

- `schema_version`: currently `1.0`.
- `task_name`: stable filesystem-safe identifier.
- `analysis_profiles`: a non-empty array containing any compatible combination of `linear_static`, `nonlinear_static`, `contact`, `modal`, `eigenvalue_buckling`, `nonlinear_buckling`, or `submodeling`.
- `analysis_profile`: accepted as a backward-compatible single-profile alternative. Do not provide both fields.
- `model.source`: `existing_project`, `import_cad`, or `procedural_geometry`.
- `model.units`: explicit length, force, and stress units; include time, mass, temperature, or angle when used.
- `mesh.profile`: a profile from `mesh-profiles.md`.

## Model-source rules

- `existing_project`: require a project/database path or a proven live active project.
- `import_cad`: require a CAD path and import/update policy.
- `procedural_geometry`: require dimensions, coordinate convention, body construction, and validation properties.

## Profile composition

- Use `["nonlinear_static", "contact"]` for frictional, opening/closing, or other nonlinear contact work.
- Use `["linear_static", "contact"]` only when the contact behavior is intentionally linearized and supported by the solver setup.
- Treat `nonlinear_buckling` as already nonlinear; add `contact` only when contact is part of that model.
- Do not combine `modal`, `eigenvalue_buckling`, or `submodeling` casually. Represent linked Workbench systems as separate job stages when their setup and validation gates differ.

## Criteria

Express user or code limits explicitly:

```json
{
  "result": "maximum_equivalent_stress",
  "scope": "MAIN_BRACKET",
  "operator": "<=",
  "limit": 235,
  "unit": "MPa",
  "source": "user-provided allowable"
}
```

Do not infer an allowable stress merely from a material name. Record safety-factor and code assumptions separately.

## Validation script

Run `scripts/validate_job_spec.py`. Resolve errors before Workbench mutation. Warnings may proceed only when recorded and irrelevant to the selected profile.

# CATIA Agent MCP

A Windows STDIO MCP server for AI-agent control of CATIA V5 modeling and native CATIA Analysis/ELFINI simulation. It does not invoke Abaqus, ANSYS, CalculiX, or another third-party solver.

Chinese documentation: [README.zh-CN.md](README.zh-CN.md)

Safe overwrite, temporary validation and timeout recovery:
[docs/safe-export.md](docs/safe-export.md).

## Current scope

- Native CATPart sketch, pad, pocket, parameters, materials, update, save, export and inspection.
- Native GSD wireframe/surface creation: 3D points, closed/open splines, offset planes,
  G0/G1/G2 connect curves, HybridShapeLoft sections/guides/coupling/closing points,
  Join, Healing, Boundary, Close Surface and Thick Surface.
- Native CATProduct creation and component insertion.
- Native CATAnalysis creation/import, cases, solutions, sets, entities, supports, mesh parts, mesh specifications, internal compute, result images/data and HTML reports.
- 53 fixed, typed MCP tools. Arbitrary Python, CATScript, shell and raw COM execution are intentionally not exposed.
- Dedicated STA worker, serialized COM calls, request-id idempotency and bounded filesystem roots.

The local validation target is CATIA P3 V5-6R2023 B33 at `G:\Program Files\Dassault Systemes\B33`. The implementation discovers installed V5 environments instead of hard-coding that location.

## Version policy

- Targeted baseline: B28 / V5-6R2018 and newer.
- Locally validated target: B33 / V5-6R2023.
- Newer releases keep the complete MCP tool surface. Runtime type-library and object-method probes gate only the missing operation.
- Releases older than B28 are outside the support target. They can be tried explicitly with `CATIA_MCP_ALLOW_LEGACY=true`.
- Module-specific Analysis late types are passed through screened Analysis methods, so GPS/GAS/EST features do not get reduced to a lowest-common-denominator schema.

Installed DLLs do not prove that a workbench licence is available. `catia_create_analysis_document` is the first live licence test.

## Start

The checked startup wrapper selects `CATIA_MCP_PYTHON`, a local `.venv`, or the available Codex Python runtime without writing logs to STDIO:

```powershell
& '.\scripts\run_server.ps1'
```

Copy [examples/codex_config.example.toml](examples/codex_config.example.toml) into the appropriate Codex config. Adjust `CATIA_MCP_ENV_NAME` for another installed release.

CATIA and the MCP process must run as the same Windows user and at the same integrity/elevation level. Otherwise the process can see `CNEXT.exe` while `CATIA.Application` remains unavailable through the Running Object Table.

## Validation

```powershell
$env:PYTHONPATH=(Resolve-Path '.\src').Path
python -m unittest discover -s '.\tests' -v
python -m compileall -q '.\src'
python '.\scripts\stdio_smoke.py'
python '.\scripts\probe_environment.py'
python '.\scripts\probe_live.py'
```

Use `probe_live.py --start-if-missing` only when starting the selected CATIA environment is intended.

## Safe operating sequence

1. `catia_health_check`
2. `catia_connect`
3. Build in small native steps and call `catia_inspect_active` after updates.
4. Save only under `CATIA_MCP_ALLOWED_ROOTS`.
5. Export with the default `overwrite_policy="error"`. Use `versioned` or
   `replace` only when explicitly intended; exports are staged through a unique
   temporary file and STEP/IGES is re-imported by default.
6. For simulation, inspect the imported Analysis tree before creating loads, restraints or mesh definitions.
7. After `catia_compute_analysis`, verify mesh parts, result images, exported numerical data and the native report. A returned COM call alone is not proof of correct physics.

See [docs/advanced-surfaces.md](docs/advanced-surfaces.md) for the GSD tool contracts and
[docs/compatibility-and-architecture.md](docs/compatibility-and-architecture.md) for the capability model and limitations.

# Compatibility and architecture

## Why capability gating is used

CATIA V5 uses stable COM concepts but the effective surface varies with release, installed code, workbench and licence. A static lowest-common-denominator wrapper would unnecessarily remove newer Analysis functions. This server therefore separates four facts:

1. Environment discovery: parse CATEnv files and determine the B release marker.
2. Installed code: locate Automation DLLs, Analysis typelib, Generative Analysis and ELFINI components.
3. Interface contract: enumerate methods from the selected `CATAnalysisTypLib.tlb`.
4. Live licence/runtime: create or access real CATIA documents and objects only on an explicit tool call.

The server always exposes the complete typed tool surface. A missing release/module capability causes a structured error on the affected tool, not removal of unrelated functions.

## Release policy

| Release marker | Label | Policy |
|---|---|---|
| B28-B32 | V5-6R2018 to V5-6R2022 | Supported through capability gates |
| B33 | V5-6R2023 | Local validation target |
| B34 and newer | V5-6R2024 and newer | Forward capability-gated; no deliberate feature reduction |
| Older than B28 | Older than V5-6R2018 | Outside target, explicit best effort only |

This is a project support policy, not a claim that every Dassault configuration in those releases has identical licences.

## Process architecture

```text
Codex/MCP client
    -> STDIO FastMCP server
        -> request validation and allowed-root checks
            -> dedicated STA queue
                -> CATIA.Application COM Automation
                    -> CATPart / CATProduct / CATAnalysis
                        -> CATIA Analysis / ELFINI only
```

Every COM request is serialized. Reusing a mutation `request_id` returns the cached success instead of applying the same modeling operation twice.

## Analysis strategy

The B33 Analysis typelib on this machine exposes, among others:

- `AnalysisManager.Import`, `AnalysisModels`, `AnalysisSets`
- `AnalysisModel.RunTransition`, `AnalysisCases.NewCase`, `AnalysisCase.AddSolution`
- `AnalysisEntities.Add`, `AnalysisEntity.SetValue`, reference/support methods
- `AnalysisMeshParts.Add`, `AnalysisMeshPart.SetGlobalSpecification`
- `AnalysisCase.ComputeMeshOnly`, `AnalysisCase.Compute`
- `AnalysisImages.Add`, `AnalysisImage.ExportData`
- `AnalysisPostManager.BuildReport`

Set, entity, mesh and result-image types remain native CATIA late-type identifiers. That keeps advanced workbench functionality available without an arbitrary raw COM endpoint.

On the B33 live target, a static case is correctly created through
`CATGPSStressAnalysis_template`. Passing the localized/display text directly to
`AnalysisCases.NewCase` fails, so friendly case names are mapped to native
transitions while custom late types remain available.

## Safety boundaries

- No arbitrary Python, VBA, CATScript, shell or raw COM method tool.
- Open/save/export/report paths must be under `CATIA_MCP_ALLOWED_ROOTS`.
- Installed CATIA material catalogs under the selected release's `startup\materials` are additionally read-only eligible.
- Closing an unsaved document requires `save=true` or `discard_unsaved=true`.
- Starting CATIA is opt-in through `catia_connect(start_if_missing=true)`.
- A compute timeout does not kill CATIA; the STA call may still finish. Check operation status before retrying.

## Known limitations

- Sketcher remains limited to line, circle, rectangle and polyline primitives. Native
  3D HybridShapeSpline, offset planes, connect curves, lofts, joins, healing, boundaries
  and surface-to-solid operations are exposed separately through the GSD layer.
- V5 Automation does not expose queryable results for the interactive curvature-comb
  display or interactive self-intersection diagnostic. The quality tool reports this
  boundary explicitly and does not fabricate a pass.
- CATIA Analysis entity component labels and late types vary by module. Use `catia_analysis_catalog`, create the entity, inspect returned basic components and then set values.
- Selection-based support binding depends on CATIA Search syntax and stable source geometry. Publications are preferable for production models.
- `Compute` success must be followed by mesh/result/report validation; no solver result is fabricated.

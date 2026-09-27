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
| Older than B28 | Older than V5-6R2018 | Outside target; V5R21/B21 is adapted and locally validated (see below) |

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

## Legacy release notes: CATIA V5R21 (B21)

The complete tool surface was probed live on CATIA P3 V5R21 B21 (SP6+HF5) with
`CATIA_MCP_ALLOW_LEGACY=true`, and an end-to-end static analysis chain was built
and solved through pure Automation. Behaviours below differ from the B28+
baseline; the "adapted" items are implemented in the server and covered by unit
tests. Run `scripts/probe_release_capabilities.py` on any machine to re-probe,
and `scripts/validate_v5r21_analysis_chain.py` to reproduce the analysis chain.

### Adapted behaviours

- `catia_export_active`: V5R21 accepts only canonical short format names
  (`stp`, `igs`); long synonyms (`step`, `iges`) are normalized.
- `catia_create_fill`: the `AddNewFill.AdvancedTolerantMode` assignment is
  rejected; the fill is created with the native default and the rejection is
  reported in `advanced_tolerant_mode_error`.
- `catia_join_surfaces`: with `SetAngularToleranceMode(True)` the V5R21 solver
  fails on otherwise valid inputs. The join is automatically recomputed without
  the mode; the fallback is reported in `angular_tolerance_note`.
- `catia_close_active`: a CATPart still referenced by an open CATProduct cannot
  be closed; V5R21 silently ignores `Close()` and previously produced a
  fabricated success. The tool now verifies the document collection and raises
  a descriptive error (close the referencing assembly first). Closing the
  assembly cascades to the part.
- `catia_bind_analysis_mesh_support`: mesh supports require a feature-style
  reference (`Part.CreateReferenceFromObject`, for example the main body).
  The geometry-style reference is kept only as a fallback.
- `catia_bind_analysis_support` (entities): supports require a named reference
  built from the selection display name (`"Selection_RSur:(...)"` via
  `Part.CreateReferenceFromName`) and bound with `AddSupportFromProduct`. The
  legacy manager-reference combination is kept as a fallback.
- `catia_build_analysis_report`: `BuildReport` requires a CATIA `Folder`
  object (from `Application.FileSystem`), not a path string.

### Verified working on V5R21

- All hybrid-shape and part factories used by the tools are present, including
  `AddNewEdgeFilletWithConstantRadius`, `AddNewCloseSurface` and
  `AddNewThickSurface`.
- Edge fillet chain (edge search through `Topology.CGMEdge,sel`, constant
  radius fillet, property and volume read-back with exact numbers).
- GSD chain: points, splines, offset planes, connect curves, lofts, fills,
  joins, healing, boundaries, close surface, thick surface, quality checks
  (SPA measurements) - all live-verified.
- Material catalog listing and application (`ApplyMaterialOnPart`), assembly
  component insertion, BMP capture, and part exports
  (stp / igs / stl / 3dxml / cgr / model).
- Analysis: document import, all three case transitions
  (`CATGPSStressAnalysis_template`, `CATGPSModalAnalysis_template`,
  `CATGPSFreeModalAnalysis_template`), `StaticSet` solutions, LoadSet /
  RestraintSet with `SAMClamp` / `SAMMoment`, `MSHPartOctree3D` mesh parts,
  `ComputeMeshOnly`, a full static `Compute`, a deformed-mesh result image and
  the native HTML report.

### Known limitations on V5R21

- `ExportData` cannot produce pdf / dxf / dwg from a CATPart.
- Result-image type names are release specific: `Mesh_Deformed` works,
  `Disp_Symbol` is rejected.
- Saving a document that participates in multiple editors (a part referenced
  by an analysis and a product) can raise the "activate save operation on other
  documents" confirmation dialog; it must be confirmed interactively.
- Applying a material can leave the material catalog document open: it is
  referenced by the part and cannot be closed while the part stays open.
- The main body name is localized (for example Chinese "零件几何体"); tool
  inputs such as `PartBody` fall back to `MainBody` automatically.
- A `CATAnalysis` document ignores the `Name` setter at creation time and
  takes its name from the first SaveAs.
- `Compute` on a model assembled purely through Automation needs the complete
  material chain; `AnalysisManager.Import` alone does not create the material
  or 3D-property entities on V5R21.

### Building a solvable static analysis chain (validated recipe)

1. Apply a physical material (for example `Catalog.CATMaterial` / Metal /
   `Aluminium`) to the part; copy mode is recommended.
2. Create the CATAnalysis document and import the part; add a case
   (`Static Case`) and a solution (`StaticSet`).
3. Material chain: `MaterialSet` + `SAMUserMaterial` entity, apply the catalog
   material through `CATMatManagerVBExt.ApplyMaterialOnUserMaterial`, then add
   a `SAM3DSolid` entity to the `PropertySet`, bind the part body as support,
   and point its `SAMAnalysisMaterialPtr` at the user material via
   `SetReference` with a reference created by
   `AnalysisManager.CreateReferenceFromObject`.
4. Add one single-face `SAMClamp` (restraint) and one `SAMDistributedForce`
   (load), binding each face through a named `Selection_RSur:(...)` reference
   (`Part.CreateReferenceFromName(selection item Reference.DisplayName)`),
   bound with `AddSupportFromProduct`.
5. Add an `MSHPartOctree3D` mesh part, bind the part body with a feature-style
   reference, and set `SizeValue` (for example `"4.0 mm"`).
6. `ComputeMeshOnly`, then `Compute`.
7. Create a `Mesh_Deformed` image and build the HTML report with a Folder
   object. Note that over-constraining (clamping many faces at once) can
   trigger `Singularity detected (pivot too small)` - a single fully clamped
   face is sufficient.

The script `scripts/validate_v5r21_analysis_chain.py` performs all of these
steps and writes the part, the solved analysis, the report and the images into
`workspace/analysis_validation_<stamp>/`.

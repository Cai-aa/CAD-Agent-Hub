# Advanced wireframe and surface tools

The advanced surface layer is a fixed, typed wrapper over CATIA V5
`HybridShapeFactory`, `HybridShapeLoft`, `HybridShapeSpline`, `HybridShapeAssemble`,
`HybridShapeHealing`, `ShapeFactory` and `SPAWorkbench`. It does not expose arbitrary
COM, CATScript, VBA or Python execution.

## Live capability probe

Call `catia_surface_capabilities` on an active CATPart before a surface workflow. The
result reports the methods present on the installed `HybridShapeFactory` and
`ShapeFactory`, plus the continuity and quality checks that V5 Automation can return.
Installed files alone do not prove a GSD/GSO licence.

## Tool groups

Wireframe and references:

- `catia_create_geometrical_set`
- `catia_create_3d_points`
- `catia_create_spline`
- `catia_create_offset_plane`
- `catia_create_connect_curve`

Surface construction and repair:

- `catia_create_loft`
- `catia_create_fill`
- `catia_join_surfaces`
- `catia_heal_surfaces`
- `catia_create_boundary`

Solid conversion:

- `catia_close_surface`
- `catia_thick_surface`

Inspection:

- `catia_check_surface_quality`

## Loft contract

`catia_create_loft` accepts two or more ordered section names. Optional arrays of
section orientation and closing-point names must match the section count. Coupling
values map to CATIA's native `SectionCoupling` values:

| Value | CATIA coupling |
|---|---|
| `ratio` | Curvilinear-abscissa ratio |
| `tangency` | Tangency discontinuity points |
| `curvature` | Tangency and curvature discontinuity points |
| `vertices` | Explicit vertices |

Guide curves are added in the supplied order. Start/end tangent surfaces provide G1
boundary continuity. CATIA's `HybridShapeLoft` Automation interface does not expose a
G2 boundary-surface switch; build G2 constraints into section/guide splines or use
`catia_create_connect_curve` where appropriate.

`context="surface"` creates a surface. `context="volume"` requests CATIA's loft volume
context and requires the applicable GSO licence.

## Continuity

- Connect curves: G0, G1 or G2 independently at both ends.
- Spline constraints from an existing curve: G1 or G2.
- Loft boundary surfaces: G0 without a tangent surface, G1 with a tangent surface.
- Healing: G0 or G1, matching the documented V5 Automation contract.

No operation silently downgrades a requested continuity level.

## Join and healing

Join supports distance tolerance, angular tolerance, connexity enforcement, manifold
enforcement and simplification. A failed CATIA update is returned as a recoverable MCP
error.

Healing supports distance objective, merging distance, tangency angle, sharpness angle
and G0/G1 continuity.

Fill supports multiple boundary curves, optional boundary-support surfaces and G0/G1/G2
continuity. It is the normal companion operation for capping loft ends before Join and
Close Surface.

## Quality-check boundary

`catia_check_surface_quality` performs real CATIA operations:

- `Part.UpdateObject` on every named feature;
- SPAWorkbench measurements where the selected geometry supports them;
- minimum-distance checks for requested element pairs;
- Join connexity/manifold/deviation/angular-mode reporting.

The installed V5 Automation contract does not expose queryable results for the
interactive curvature-comb display or the interactive self-intersection diagnostic.
The tool reports these checks as unsupported instead of fabricating a pass. For release
acceptance, inspect the model in CATIA's interactive analysis commands in addition to
the MCP-returned update, topology and gap evidence.

## Live probe

With CATIA already open:

```powershell
$env:PYTHONPATH=(Resolve-Path '.\src').Path
python '.\scripts\probe_surfaces.py'
```

The probe creates three closed 3D splines, a native HybridShapeLoft, its boundary,
quality evidence and a saved `Surface_API_Probe.CATPart` under the configured workspace.

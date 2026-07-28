# Mesh profiles

Defaults are heuristics and must be overridden by geometry, element formulation, analysis purpose, and solver guidance.

## `solid_general`

- Prefer sweepable quadratic hex/prism layouts where sound.
- Fall back to quadratic tetrahedra for complex solids.
- Refine holes, fillets, load introduction, supports, and high-gradient regions.
- Converge displacement, strain energy, and scoped stress.

## `solid_contact`

- Use quadratic solids and comparable sizes on opposing contact faces.
- Resolve the expected patch; do not rely on only a few face elements.
- Inspect low-quality elements specifically in contact and bearing regions.
- Converge contact force, average pressure, deformation, and a robust scoped/path stress.

## `thin_solid_bending`

- Prefer sweep through thickness.
- Require enough through-thickness layers for the element order and nonlinear behavior.
- Inspect aspect ratio and bending response; consider shell conversion when appropriate.

## `shell_structure`

- Verify midsurface, thickness, offsets, normals, and shared topology/connections.
- Refine penetrations, joints, point-load distribution regions, and stiffness transitions.
- Evaluate element quality/warping/aspect ratio with shell-appropriate metrics.

## `beam_frame`

- Verify line topology, section, orientation, offsets, releases, and connectivity.
- Place nodes at joints, section changes, loads, masses, and supports.
- Converge frequencies, deflections, or internal forces rather than cosmetic line density.

## `plasticity_large_deformation`

- Avoid elements likely to invert under expected deformation.
- Refine plastic hinges, necking, folding, and contact transitions.
- Track distortion warnings, plastic strain localization, energy, and load-displacement response.

## `modal_buckling`

- Preserve mass and stiffness distribution.
- Refine regions governing curvature and local modes.
- Converge frequencies/effective mass or load multipliers/mode shapes.

## `submodel`

- Match mapped cut boundaries sufficiently for interpolation.
- Grade toward the local feature while avoiding abrupt transitions.
- Compare results away from the cut boundary and converge local quantities.

## Configurable quality defaults

These are workflow defaults, not universal industry limits:

| Check | Pass | Warning | Hard failure |
|---|---:|---:|---:|
| Nonpositive Jacobian count | 0 | - | > 0 |
| Zero/negative volume count | 0 | - | > 0 |
| Maximum skewness | < 0.75 | 0.75-0.90 | > 0.90 in a critical region |
| Element quality | most > 0.20 | small tail 0.10-0.20 | <= 0 or excessive low-quality fraction |
| Orthogonal quality | most > 0.20 | 0.10-0.20 | near 0 in a critical region |

Evaluate distributions, volume fraction, critical-region location, and solver impact. A single outlier away from critical physics is not automatically equivalent to a failed mesh.

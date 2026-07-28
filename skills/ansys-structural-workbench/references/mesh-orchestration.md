# Mesh orchestration

## State machine

```text
GEOMETRY_INSPECTION -> METHOD_SELECTION -> CONTROL_PLANNING
-> GENERATION -> QUALITY_GATE -> REPAIR -> ACCEPTED
-> SOLVE -> CONVERGENCE_GATE
```

## Geometry inspection

Classify each body by slenderness, thickness, sweepability, curvature, small features, contacts, load/support regions, material behavior, and expected gradients. Identify regions where representation should change from solid to shell or beam.

## Method selection

Use this preference only when appropriate:

1. Beam/shell representation for genuinely slender/thin structures.
2. Sweep or MultiZone for bodies with suitable source/target topology and controlled layers.
3. Quadratic patch-conforming tetrahedra for complex 3D solids.

Never force a hex method that produces distorted elements or loses critical geometry.

## Control planning

Define global size, growth/transition, curvature/proximity behavior, body/face/edge sizing, contact sizing, thickness layers, circumferential divisions, and local influence regions. Avoid incompatible stacks of mesh controls.

For contact:

- use comparable characteristic sizes on both sides;
- resolve the contact patch and expected pressure gradient;
- align axial/thickness divisions when practical;
- refine load-transfer regions without globally exploding element count.

## Quality gate

Require:

- successful mesh on all active bodies;
- no zero/negative-volume or nonpositive-Jacobian elements;
- valid surface meshes on all contact scopes;
- no lost or invalid control scopes;
- acceptable distributions for profile-relevant metrics;
- worst elements located and classified.

Use `scripts/evaluate_mesh_quality.py` on normalized metric JSON. A visually smooth mesh is insufficient.

## Repair order

Apply the smallest justified change, regenerate, and compare:

1. Correct invalid scope or method assignment.
2. Add/adjust local sizing at curvature, holes, fillets, contacts, or thin regions.
3. Slow size transition or improve source-face/edge divisions.
4. Change method within the profile fallback order.
5. Use virtual topology or defeaturing only for noncritical features and record the change.
6. Stop with worst-element locations and evidence when approved repairs fail.

Do not repeatedly shrink the global size without diagnosing the bad region.

## Convergence gate

Use at least coarse, medium, and fine levels when the task requires certified adequacy. Keep physics, element formulation, and result extraction consistent. Refine critical regions first and record nodes, elements, solve time, and every configured metric.

Preferred metrics:

1. displacement;
2. reaction/load transfer;
3. strain energy;
4. area-averaged or linearized stress;
5. path stress away from singular points;
6. contact force and average pressure;
7. frequency or buckling multiplier for those profiles.

Run `scripts/evaluate_mesh_convergence.py`. Label singular or nonconvergent peaks; never hide them by reporting only a coarser mesh.

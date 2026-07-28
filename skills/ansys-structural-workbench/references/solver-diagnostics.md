# Solver diagnostics

Diagnose in this order and change one cause class at a time.

## Rigid-body motion or singular matrix

1. Verify the correct bodies and degrees of freedom are restrained.
2. Check disconnected bodies, open contacts, joints, remote points, and shared topology.
3. Inspect load direction and coordinate systems.
4. Use weak springs only as an intentional diagnostic, never as the unreported final fix.

## Contact nonconvergence

1. Inspect initial gap/penetration and contact/target scoping.
2. Check pinball, normal direction, formulation, sliding, and friction.
3. Compare mesh sizes and resolve the contact patch.
4. Use smaller initial/minimum substeps when the state transition is physical.
5. Review penetration and chattering before changing stiffness controls.

## Element distortion

1. Locate distorted elements and correlate with deformation/plasticity/contact.
2. Improve local topology, layers, transition, or element formulation.
3. Review large-deflection and material data.
4. Do not accept a result past element inversion.

## Nonlinear cutbacks or incomplete time

1. Identify the last converged time and physical event.
2. Determine whether the issue is a load step discontinuity, limit point, contact change, plastic localization, or bad mesh.
3. Prefer displacement control for snap-through-like behavior when appropriate.
4. Never report the last unconverged attempted state as final.

## Warnings

Classify every warning as informational, accepted limitation, model-quality issue, or fatal-to-conclusion. Preserve the raw message and explain why the conclusion remains valid when proceeding.

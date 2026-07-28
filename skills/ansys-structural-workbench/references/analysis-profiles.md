# Analysis profiles

Profiles are composable. Load and enforce every applicable section. A frictional pin joint normally uses both `nonlinear_static` and `contact`; linked analyses may require separate staged Job Specs rather than one ambiguous combined profile.

## `linear_static`

Require elastic material data, adequate restraint, load/reaction balance, deformation reasonableness, scoped stress review, singularity labeling, and mesh convergence.

## `nonlinear_static`

Add load-step history, automatic time stepping, large-deflection decision, nonlinear material definitions, convergence controls, full time-history results, cutback/bisection review, and path-dependence notes.

## `contact`

Add manual or validated automatic pair scoping, Initial Contact Information, formulation and sliding choice, contact-side mesh compatibility, pressure/status/gap/penetration, contact-force balance, open/closed history, and frictional quantities when friction is nonzero.

Do not infer zero tangential force from a potentially defective probe. Cross-check the contact formulation, solver data, and field result. Some Mechanical versions or scripting paths may return duplicated total/normal/tangential contact probe values.

## `modal`

Require density, boundary-condition review, requested mode/frequency range, rigid-body-mode identification, frequencies, mode shapes, participation factors, and effective-mass coverage. Report whether prestress is included.

## `eigenvalue_buckling`

Require a valid upstream static state, system/data connection, positive load multipliers, mode-shape inspection, and a clear limitation that ideal eigenvalue buckling is not a nonlinear collapse prediction.

## `nonlinear_buckling`

Require imperfection source/amplitude, large deflection, displacement control or justified path-following method, load-displacement history, limit-point identification, and imperfection sensitivity. Treat nonconvergence near a limit point as a diagnostic signal, not automatically as model invalidity.

## `submodeling`

Require a solved global model, compatible cut-boundary mapping, coverage checks, mapped-displacement evidence, reaction consistency, and local result convergence away from singular boundaries.

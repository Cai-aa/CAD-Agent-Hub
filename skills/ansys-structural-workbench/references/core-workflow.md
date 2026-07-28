# Core structural workflow

## 1. Inspect

- Prove the active project, system, Mechanical model, analysis count, and application version.
- Inventory bodies, suppressed state, material assignments, contacts/joints, named selections, loads, supports, mesh controls, solution objects, and existing solve state.
- Establish coordinate systems and units from live properties.

## 2. Scope semantically

Use existing named selections first. Otherwise query candidates and validate:

- entity kind and expected count;
- owning body;
- centroid/bounding box;
- area, length, radius, or thickness;
- normal, axis, or tangent direction;
- surface or curve type.

Create stable named selections only after validation. Reject ambiguous matches.

## 3. Configure the model

- Assign every active body an explicit material.
- Confirm element dimensionality and section/thickness definitions.
- Remove or suppress auto-generated contacts only after inventory and authorization.
- Read back every connection, load, support, step table, and analysis option after setting it.
- Check load paths and rigid-body degrees of freedom. Do not use weak springs as a default repair.

## 4. Mesh and pre-solve

Follow `mesh-orchestration.md`. For contact analyses, generate Initial Contact Information and capture status, gap, penetration, pinball, and scoped contact pairs. Stop on unexpected Far Open contact or severe penetration.

## 5. Solve and diagnose

Retain the raw solve log. Capture:

- run-completed marker and solution status;
- warning and error counts;
- completed load steps/substeps;
- final converged time;
- bisections/cutbacks and equilibrium iterations;
- contact-status changes and element-distortion messages.

Use `solver-diagnostics.md` before changing the model.

## 6. Extract and validate

Always extract scoped results with unit, time/load step/mode, averaging convention, and coordinate system. Common checks:

- vector force and moment equilibrium;
- deformation magnitude and direction;
- strain energy and energy consistency where applicable;
- connection/contact load transfer;
- symmetry when physically expected;
- analytical or benchmark quantity;
- mesh convergence of robust engineering metrics.

## 7. Preserve evidence

Save the final project/database and export:

- normalized job spec;
- model/setup summary;
- mesh statistics and quality distributions;
- solver diagnostics;
- raw and normalized results;
- validation and convergence JSON/CSV;
- scoped mesh/result images.

Do not claim independent project snapshots for earlier mesh levels unless those files actually exist.

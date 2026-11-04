# SolidWorks COM compatibility and modeling rules

This file records host-specific behavior that must remain covered by tests.

## Revolve contract

- A solid revolve graph must declare exactly one axis strategy: `axis` for a
  named reference axis, or `axis_segment` for a construction line in the
  profile sketch.
- The canonical sphere uses a construction centerline plus two 90-degree arcs.
  Do not use the centerline as a solid profile edge, and do not collapse the
  semicircle into one diametrically opposed 180-degree COM arc.
- A sketch-segment axis is selected as `EXTSKETCHSEGMENT` with selection mark
  4. A reference axis uses mark 16 with `FeatureRevolve2`; the legacy
  `FeatureRevolve` compatibility call uses mark 4.
- Axis strategy never changes during a retry. Only the API version may fall
  back from `FeatureRevolve2` to `FeatureRevolve`.
- Step results report both `axis_strategy` and `backend`.

## Sketch isolation

- Equation-spline endpoint welding runs only when a sketch actually contains
  an `equation_spline`. Ordinary line, arc, circle, and spline sketches must
  not enter the equation-curve COM adapter.

## Save routing

- Native `.sldprt`, `.sldasm`, and `.slddrw` targets use the three-argument
  `IModelDoc2.SaveAs3` compatibility path on this host.
- STEP, IGES, STL, PDF, DXF, and DWG exports use
  `IModelDocExtension.SaveAs`. They never pass through `SaveAs3`.
- Both paths verify that the target exists and is non-empty before reporting
  success.

## Document lifecycle (0.5)

- Existing documents are never automatically closed by single-document mode.
  Feature names are not ownership evidence.
- New graph parts are validated before save. Failure cleanup closes only the
  exact new COM document when enumeration proves its title is unambiguous.
- A per-call document token binds COM identity, path, title and configuration.
  The active object is rechecked between graph steps and before saving.
- Mutations use a durable request journal. Partial incremental failures block
  subsequent writes and are not automatically retried or claimed rolled back.
- `StartRecordingUndoObject` returns void; `FinishRecordingUndoObject2` returns
  bool. `GetErrorCode2` uses an out-parameter of type BOOL, not I4. Feature
  warnings are reported separately from errors.
- COM interface casts resolve the actual host's typelib instead of hardcoding
  the SolidWorks 2025 major version.

## Why the first sphere attempts failed

1. The initial diameter line served as both profile boundary and revolve axis.
2. The initial semicircle used an ambiguous single 180-degree COM arc.
3. Gear-specific equation-spline endpoint welding leaked into an ordinary
   line-and-arc sketch.
4. The executor silently changed from reference-axis selection to a sketch
   segment, hiding the actual successful strategy.
5. Generated pywin32 type-library wrappers changed `SaveAs` argument and
   return-value marshaling, including rejection of a Python `None` ExportData
   value.

The fixes are contracts and routing rules, not additional blind retries.

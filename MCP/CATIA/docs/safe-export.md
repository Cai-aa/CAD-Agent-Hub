# Safe CATIA export

Starting with 0.2.0, `catia_export_active` never points CATIA `ExportData`
directly at an existing final file. The default policy refuses an overwrite,
preventing a modal CATIA confirmation from blocking the serialized COM worker.

## Contract

```text
catia_export_active(
    path,
    format_name=None,
    overwrite_policy="error",
    verify_reimport=True,
    request_id=None,
)
```

`overwrite_policy` accepts:

- `error` (default): fail before entering CATIA when the final target exists.
- `versioned`: preserve the existing target and choose a timestamped final path,
  such as `Engine_Turbine_Disk.__version_20260731_094400.step`.
- `replace`: export and validate a unique temporary file, then replace the final
  target through the filesystem.

`format_name` accepts the canonical short exchange names (`stp`, `igs`, `stl`,
`3dxml`, `model`, `cgr`, `pdf`, `dxf`, `dwg`). The long synonyms `step` and
`iges` are normalized to `stp` and `igs`, because older releases such as V5R21
reject the long names outright in `ExportData`.

## Fixed workflow

1. Check the final target before calling `ExportData`.
2. Allocate a unique sibling path such as
   `Engine_Turbine_Disk.__exporting_20260731_094400_a1b2c3d4.step`.
3. Set `CATIA.Application.DisplayFileAlerts=False`.
4. Call CATIA `ExportData` once, targeting only the new temporary path.
5. Verify that the temporary file exists and is non-empty.
6. Re-import STEP/IGES by default and require Part body/shape geometry or Product
   components.
7. Close the validation document and reactivate the original document.
8. Rename for `error`/`versioned`, or use filesystem replacement for `replace`.
9. Restore `DisplayFileAlerts` and release the per-document export guard in
   `finally`.

The final target is untouched until export and validation have both succeeded.

## Timeout and concurrency

- All CATIA COM calls remain serialized on one STA worker.
- A document can have only one active export.
- Calls received while the worker is busy are rejected instead of queued.
- After a timeout, call `catia_operation_status` and wait for
  `retry_allowed=true`.
- Inspect both the final target and any `.__exporting_...` artifact before
  deciding whether another export is necessary.
- Completed operations retain request-id idempotency.

Native document save and exchange export should be separate workflow stages.
Model-building functions and scripts should not call raw `ExportData` at the end
of a long modeling operation.

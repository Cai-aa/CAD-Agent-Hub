# Siemens NX MCP (current repaired entry points)

This version connects a Codex stdio MCP server to a non-blocking .NET Remoting bridge inside NX 2412. `start_bridge.py` only loads the DLL and then returns, so NX does not remain stuck in a running journal. The old Python TCP journal bridge is retained only as a legacy reference.

## Install and register with Codex

```powershell
Set-Location "C:\path\to\CAD-Agent-Hub\MCP\UG"
.\install_codex.ps1
```

The script creates `.venv`, installs the SDK pinned in `requirements.txt`, builds the non-blocking remoting DLL/client, and registers a stdio server named `siemens-nx`. It refuses to overwrite an existing server with the same name.

## Start the bridge in NX

Recommended one-time auto-start installation:

```powershell
.\install_nx_autostart.ps1
```

The script deploys the DLL under this project's `nx_user\startup` and sets the current user's `UGII_USER_DIR` only when another customization root is not already configured. After all NX sessions are closed and NX is restarted, NX calls the DLL's `Startup()` automatically; Journal playback is no longer required. `uninstall_nx_autostart.ps1` safely removes only the matching environment setting and preserves the files.

Manual fallback:

1. Start NX 2412 and create or open a work `.prt` file.
2. Use **Tools → Journal → Play** (`Alt+F8`) and select `start_bridge.py`. The journal must finish quickly. If NX remains in "Work in Progress", stop it immediately; that indicates the legacy blocking bridge.
3. "Work in Progress" should disappear quickly. The service log is `%TEMP%\nx_mcp_remoting_server.log`; the endpoint is `http://127.0.0.1:48161/NXOpenSession`.
4. Run the read-only checks externally:

```powershell
.\.venv\Scripts\python.exe .\diagnose.py
.\.venv\Scripts\python.exe .\smoke.py
```

Run the mutating block check only when desired:

```powershell
.\.venv\Scripts\python.exe .\smoke.py --create-block
```

Stop the bridge by closing NX, or explicitly unload `NXMcPRemotingServer.dll` with **File → Utilities → Unload Shared Images**.

## MCP tools

- Session and inspection: `ping`, `get_part_summary`, `inspect_work_part_geometry`, `inspect_body_topology`, `resolve_topology`, `inspect_feature`, `rebuild_work_part`, `save_work_part`. Topology readback includes stable IDs and geometry fallbacks, so callers do not need to persist NX face/edge list indices.
- Parts and parameters: `create_part`, `create_block`, `set_feature_expression`.
- Native sketches: `create_parametric_sketch`, `inspect_sketch` (lines, rectangles, circles, arcs, constraints, and driving dimensions).
- Shape features: `extrude_sketch`, `revolve_sketch`, `sweep_sketch`, `loft_sketches` (solid or sheet output).
- Detail features: `create_cylindrical_hole`, `boolean_bodies`, `linear_pattern_feature`, `mirror_feature`, `fillet_edges`, `chamfer_edges`, `shell_body`.
- Exchange: `export_exchange` and `import_exchange` for workspace-scoped STEP AP203/AP214/AP242 and Parasolid `.x_t`/`.x_b` files.
- Assemblies: `add_component`, `move_component`, `add_assembly_constraint`, `inspect_assembly`, and `inspect_assembly_constraints`; persistent fix/touch/fit/concentric/distance/parallel/perpendicular/angle/align-lock constraints include solver-status readback.
- Surfaces: `extract_face_surface`, `offset_surface`, `trim_sheet_body`, and `sew_sheet_bodies` with indexed topology input and result-body readback.
- Sheet metal: `create_sheet_metal_tab`, `create_sheet_metal_flange`, `create_sheet_metal_bend`, `create_flat_pattern`, and `export_flat_pattern_dxf`; the standalone bend tool accepts a stable target-face selector and a bend-line sketch.
- Drafting: `create_drawing_sheet`, `create_projected_view`, `create_drafting_note`, `create_drawing_linear_dimension`, and `inspect_drawing_annotations`. Linear dimensions are associative to stably selected model edges and return the measured size.
- CAM foundation: `get_cam_capabilities`, `initialize_cam_setup`, `create_cam_milling_context`, `inspect_cam_setup`, `define_cam_mcs`, `define_cam_workpiece`, `create_cam_mill_tool`, `create_cam_operation`, `set_cam_operation_geometry`, `configure_cam_milling_operation`, `generate_cam_toolpath`, `inspect_cam_operations`, `inspect_cam_operation_details`, and workspace-scoped `export_cam_clsf`. The milling context creates actual non-template program/method/MCS/workpiece parents; face milling and cavity milling accept stable geometry, explicit stock bodies, spindle speed, and feeds. Version 0.20 adds fixture/check-body assignment plus explicit cutter, shank, and multi-section holder parameters. Operation subtypes are validated against the templates reported by the live NX release instead of assuming legacy template names.
- Machine build and simulation: `inspect_machine_source_profile` inspects a locally aliased machine `.prt` without displaying it, and `inspect_machine_kinematic_plan` converts an external definition into a path-redacted NX build plan. Version 0.19 materializes the official NX Classic BC template, binds grouped OEM geometry, retargets all 25 template junctions to OEM absolute coordinates, applies six-axis limits, and verifies the controller channel and five-axis milling chain. Live NX 2412 readback proved X/Y/Z/S/B/C, 31 components, 25 junctions, `TNC_640`, and `Z-Y-X-B-C`. `export_machine_kit_from_reference` avoids the NX 2412 `MachineKitBuilder` 580055 post-generation defect by using an NX-exported reference kit as the valid container, replacing its graphics with the saved OEM model, and removing private metadata. If NX rejects a repeated reference export, overwrite mode may reuse only an already verified, complete, sanitized official container. `import_machine_kit_readback` imports only against temporary shadow library roots, verifies the global machine database is unchanged, opens the imported part non-display, and can run an OEM-defined initial-position static clearance analysis.
- Version 0.20 closes the CAM-to-machine gap. `bind_isolated_machine_kit_to_cam` imports the generated MTK into a persistent workspace shadow library, repeats NX readback/static-collision validation, and mounts it into the current CAM setup without changing the global machine database. `inspect_machine_simulation_readiness` now checks X/Y/Z/B/C limit records, generated paths, parameterized cutter/shank/holder geometry, part, stock, and optional fixture geometry. Protected simulation uses an NX-AppDomain .NET runtime so `start_machine_simulation_with_collision_stop`, `inspect_active_machine_simulation`, and `stop_active_machine_simulation` share one real NX control panel across separate MCP calls. Collision, machine-collision, axis-limit, holder, tool/part, tool/IPW, rapid-through-IPW stops, and fine material removal are forced on.
- Version 0.20.1 resolves the OEM machine-reference location into the Classic BC template machine-zero frame before retargeting junctions. MTK export can keep a classified library reference while assigning a unique `graphics_file_name`, preventing NX's loaded-part-name cache from reopening stale machine geometry. Same-libref `reload_existing` validates the isolated import and static collision pairs before unloading the current machine; `restore_machine_build_recovery_part` returns safely to the original CAM part after Machine Tool Builder work.
- Locked NC output: `postprocess_cam_program_locked` is disabled unless `NX_MCP_ENABLE_POSTPROCESS=1` is set and the caller supplies the exact verification confirmation. Its output is still explicitly marked non-certified and requires independent machine simulation, dry run, and operator approval.
- Specialized/helper: `create_involute_gear`; `run_python` for NXOpen gaps when explicitly enabled.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe .\stdio_smoke.py
.\.venv\Scripts\python.exe .\stdio_live_e2e.py
```

For the workspace-scoped mutating end-to-end test:

```powershell
.\.venv\Scripts\python.exe .\stdio_live_e2e.py --mutate
```

To create and validate the default module 2, 20-tooth, 20-degree pressure-angle
involute gear through the real stdio MCP path:

```powershell
.\.venv\Scripts\python.exe .\stdio_live_e2e.py --create-gear involute_gear_m2_z20_pa20.prt
```

For the native sketch, constraint, dimension, and extrusion stage:

```powershell
.\.venv\Scripts\python.exe .\stdio_modeling_stage1.py
```

Additional live checks are provided by `stdio_modeling_stage2.py`,
`stdio_modeling_stage3.py`, and `stdio_exchange_stage5.py`.

Offline protocol, fake-NXOpen, and real stdio initialization can be automated. A complete desktop claim still requires a live `ping → part summary → create block` run inside NX.

## Security and limitations

- Keep the bridge bound to `127.0.0.1`.
- `run_python` is arbitrary code execution inside NX. Set `NX_MCP_ALLOW_EXECUTE=0` in the Codex server environment to disable it.
- The bundled MILL E 500 U profile contains public travel/axis/controller-family data only. It contains no vendor backup, serial/license data, private paths, PLC/network configuration, or proprietary postprocessor files.
- Toolpath generation is successful only when readback reports `validation_passed=true` and every operation reports `path_exists=true`. A created CAM operation or a successful builder validation alone is not proof of a usable toolpath.
- NX 2412 may return an empty high-level generation result in the non-blocking remoting callback. `generate_cam_toolpath(backend="auto")` therefore verifies every path and uses the licensed official `UF_PARAM_generate` entry point only for operations still missing a path; the response reports `fallback_used` and the backend per operation.
- Default CAM objects loaded from the operation template can themselves be template parents. Use `create_cam_milling_context` and its returned names; `create_cam_operation` rejects template parents by default so that NX cannot silently skip the operation.
- CLSF is neutral cutter-location output, not machine-ready NC. Keep postprocessing disabled until the exact machine kinematics and production post have been independently certified.
- Run `inspect_machine_simulation_readiness(machine_query="...", required_axes=["X","Y","Z","B","C"])`, then `bind_machine_tool_from_library(..., dry_run=true)`, before committing with `dry_run=false`. Replacing an existing machine additionally requires `replace_existing=true` and the exact confirmation `REPLACE_EXISTING_MACHINE_TOOL`. Binding does not save the part automatically.
- External machine sources must be configured behind an alias in the Git-ignored `config/machine_sources.local`; copy the structure from `config/machine_sources.example.json`. The MCP accepts the alias and redacts source paths. Run `inspect_machine_source_profile` first; if the `.prt` has no kinematics, run `inspect_machine_kinematic_plan` to validate the axis tree, limits, and grouped geometry. A valid build plan is not yet an installed NX Machine Kit or production certification.
- Machine building keeps source assets read-only, restricts generated parts and kits to the MCP workspace, defaults mutations to `dry_run=true`, and uses exact confirmations. `retarget_machine_junctions_from_profile` requires `RETARGET_MACHINE_JUNCTIONS`; reference-container MTK export requires `EXPORT_MACHINE_KIT`; isolated import requires `IMPORT_MACHINE_KIT_ISOLATED`; shadow CAM binding requires `BIND_ISOLATED_MACHINE_KIT_TO_CAM`. Version 0.19 rejects metadata-only archives, sanitizes kit metadata, and never registers the generated entry in the user's installed machine library. Static collision evaluation does not move an axis or start simulation. It parses the OEM collision matrix and clearance values instead of inventing broad component pairs, and returns per-object bounds plus penetration evidence for any real interference. The current isolated MTK readback evaluates both OEM pairs at the specified 2.5 mm clearance with zero hard/soft/touching results. Version 0.20 additionally requires CAM tooling/workpiece context before protected simulation can start. None of these checks is production certification; NC output still requires independent verification, dry run, and operator approval.
- External `.mch` plus grouped `.stl` assets can drive the NX component and X/Y/Z/B/C axis build. `.ctl/.ini/.vcproject/.VcTemplate` files are third-party controller/simulation assets, while `.tcl/.def/.pce/.psc/.pui/.tbc` files form a post stack. The latter two groups are reference-only: they are not embedded, automatically registered, enabled, or represented as production-qualified.
- `start_machine_simulation_with_collision_stop` is toolpath-driven verification, not TNC 640 controller-driven NC-code verification. Machine-code simulation still requires a matched and validated postprocessor, CSE/controller model, fixtures, and tool assemblies.
- The remoting DLL remains loaded until NX exits or it is explicitly unloaded. The journal itself does not remain occupied.
- Auto-start uses NX's supported `%UGII_USER_DIR%\startup` discovery. If another `UGII_USER_DIR` already exists, the installer refuses to overwrite it; merge customization roots through `UGII_CUSTOM_DIRECTORY_FILE` instead.
- Dedicated tools now cover the validated core listed above, but they do not expose every NX command. Non-planar surface trimming and broader drafting annotation types remain follow-up modules. Prefer stable IDs or geometry selectors (`normal`, `point_on_plane`, `direction`, `length`, `near_point`, and deterministic sorting) over persisted face/edge indices; when geometry itself changes, reacquire the stable reference from `inspect_body_topology`.

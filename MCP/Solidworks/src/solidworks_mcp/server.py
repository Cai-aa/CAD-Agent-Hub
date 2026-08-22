from __future__ import annotations

import importlib
import uuid
from typing import Any

try:
    # MCP SDK 2.x promotes the high-level server to the public mcp.server API.
    from mcp.server import MCPServer as MCPApplication
except ImportError:  # pragma: no cover - exercised only with MCP SDK 1.x
    # MCP SDK 1.x exposed the same decorator-based API as FastMCP.
    from mcp.server.fastmcp import FastMCP as MCPApplication

from .contracts import ContractError
from .executor import SolidWorksExecutor
from .feature_graph import compile_feature_graph

mcp = MCPApplication("SolidWorks Agent MCP")
executor = SolidWorksExecutor()


def _request_id(request_id: str | None) -> str:
    return request_id.strip() if request_id and request_id.strip() else str(uuid.uuid4())


def _result(operation: str, fn: Any) -> dict[str, Any]:
    try:
        return {"operation": operation, "result": fn()}
    except (ContractError, RuntimeError, TimeoutError) as exc:
        return {"operation": operation, "error": {"message": str(exc), "recoverable": True}}
    except Exception as exc:
        return {
            "operation": operation,
            "error": {
                "message": f"{type(exc).__name__}: {exc}",
                "recoverable": True,
            },
        }


@mcp.tool()
def solidworks_health_check() -> dict[str, Any]:
    """Check templates and MCP executor state without launching SolidWorks."""
    return executor.health_check()


@mcp.tool()
def solidworks_operation_status() -> dict[str, Any]:
    """Return connection, busy time and queue state without entering the COM queue."""
    return executor.operation_status()


@mcp.tool()
def solidworks_connect(start_if_missing: bool = False) -> dict[str, Any]:
    """Attach to the existing SolidWorks instance; opt in to starting a new one only when needed."""
    return _result("connect", lambda: executor.connect(start_if_missing))


@mcp.tool()
def solidworks_list_documents(request_id: str | None = None) -> dict[str, Any]:
    """List open SolidWorks documents, paths, types, dirty state, and the active document."""
    return _result("list_documents", lambda: executor.list_documents(_request_id(request_id)))


@mcp.tool()
def solidworks_activate_document(
    title: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Activate one already-open SolidWorks document by its exact title."""
    return _result(
        "activate_document",
        lambda: executor.activate_document(_request_id(request_id), title),
    )


@mcp.tool()
def solidworks_get_bounding_box(
    include_hidden: bool = True,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Return the active part or assembly bounding box in millimetres."""
    return _result(
        "get_bounding_box",
        lambda: executor.get_bounding_box(_request_id(request_id), include_hidden),
    )


@mcp.tool()
def solidworks_get_mass_properties(request_id: str | None = None) -> dict[str, Any]:
    """Return mass, volume, area, density, centre of mass, and principal moments when available."""
    return _result(
        "get_mass_properties",
        lambda: executor.get_mass_properties(_request_id(request_id)),
    )


@mcp.tool()
def solidworks_rebuild_diagnostics(
    perform_rebuild: bool = False,
    full_rebuild: bool = False,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Inspect rebuild/dirty state, optionally performing a normal or full rebuild first."""
    return _result(
        "rebuild_diagnostics",
        lambda: executor.rebuild_diagnostics(
            _request_id(request_id),
            perform_rebuild,
            full_rebuild,
        ),
    )


@mcp.tool()
def solidworks_capture_view(
    output_path: str,
    width: int = 1600,
    height: int = 900,
    fit_view: bool = True,
    overwrite: bool = False,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Capture the active SolidWorks model view to a BMP evidence file."""
    return _result(
        "capture_view",
        lambda: executor.capture_view(
            _request_id(request_id),
            output_path,
            width,
            height,
            fit_view,
            overwrite,
        ),
    )


@mcp.tool()
def solidworks_list_configurations(request_id: str | None = None) -> dict[str, Any]:
    """List configurations in the active document and identify the active one."""
    return _result(
        "list_configurations",
        lambda: executor.list_configurations(_request_id(request_id)),
    )


@mcp.tool()
def solidworks_activate_configuration(
    configuration_name: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Activate an existing configuration by exact name without saving the document."""
    return _result(
        "activate_configuration",
        lambda: executor.activate_configuration(_request_id(request_id), configuration_name),
    )


@mcp.tool()
def solidworks_create_configuration(
    configuration_name: str,
    comment: str = "",
    alternate_name: str = "",
    activate: bool = True,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a non-derived configuration, optionally making it active; saving remains explicit."""
    return _result(
        "create_configuration",
        lambda: executor.create_configuration(
            _request_id(request_id),
            configuration_name,
            comment,
            alternate_name,
            activate,
        ),
    )


@mcp.tool()
def solidworks_get_custom_properties(
    configuration_name: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Read document-level properties, or one exact configuration's properties when named."""
    return _result(
        "get_custom_properties",
        lambda: executor.get_custom_properties(_request_id(request_id), configuration_name),
    )


@mcp.tool()
def solidworks_set_custom_properties(
    properties: dict[str, Any],
    configuration_name: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Upsert validated text, numeric, or boolean custom properties without saving the document."""
    return _result(
        "set_custom_properties",
        lambda: executor.set_custom_properties(
            _request_id(request_id),
            properties,
            configuration_name,
        ),
    )


@mcp.tool()
def solidworks_list_material_databases(request_id: str | None = None) -> dict[str, Any]:
    """List material database paths configured in the connected SolidWorks instance."""
    return _result(
        "list_material_databases",
        lambda: executor.list_material_databases(_request_id(request_id)),
    )


@mcp.tool()
def solidworks_get_material(
    configuration_name: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Read the material assigned to the active or named part configuration."""
    return _result(
        "get_material",
        lambda: executor.get_material(_request_id(request_id), configuration_name),
    )


@mcp.tool()
def solidworks_assign_material(
    database_path: str,
    material_name: str,
    configuration_name: str | None = None,
    rebuild: bool = True,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Assign a material from an existing .sldmat database to one part configuration."""
    return _result(
        "assign_material",
        lambda: executor.assign_material(
            _request_id(request_id),
            database_path,
            material_name,
            configuration_name,
            rebuild,
        ),
    )


@mcp.tool()
def solidworks_reload_runtime() -> dict[str, Any]:
    """Reload this installed MCP's trusted feature modules and recreate the COM executor.

    This accepts no path or source code. It exists only to shorten the live-test
    cycle after local edits to the installed editable project.
    """
    def reload_modules() -> dict[str, Any]:
        global executor, compile_feature_graph
        from . import executor as executor_module
        from . import feature_graph as feature_graph_module
        from . import gearbox as gearbox_module
        from . import involute_gear as involute_gear_module
        from . import native_features as native_features_module
        from . import output_shaft as output_shaft_module
        from . import interactive as interactive_module
        from . import part_generators as part_generators_module
        from . import primitives as primitives_module
        from . import config as config_module
        from . import com_runtime as com_runtime_module

        try:
            executor.session.close()
        except Exception:
            pass
        importlib.reload(native_features_module)
        importlib.reload(output_shaft_module)
        importlib.reload(feature_graph_module)
        importlib.reload(gearbox_module)
        importlib.reload(involute_gear_module)
        importlib.reload(primitives_module)
        importlib.reload(interactive_module)
        importlib.reload(part_generators_module)
        importlib.reload(config_module)
        importlib.reload(com_runtime_module)
        importlib.reload(executor_module)
        compile_feature_graph = feature_graph_module.compile_feature_graph
        executor = executor_module.SolidWorksExecutor()
        return {"ok": True, "reloaded": True, "version": "0.4.0"}

    return _result("reload_runtime", reload_modules)


@mcp.tool()
def solidworks_create_part(title: str = "Part", request_id: str | None = None) -> dict[str, Any]:
    """Create a part from the configured .prtdot template. Reusing request_id is safe."""
    return _result("new_part", lambda: executor.new_part(_request_id(request_id), title))


@mcp.tool()
def solidworks_open_document(path: str, request_id: str | None = None) -> dict[str, Any]:
    """Open a native document or import a STEP/STP file as a part document."""
    return _result("open_document", lambda: executor.open_document(_request_id(request_id), path))


@mcp.tool()
def solidworks_save_active(path: str | None = None, request_id: str | None = None) -> dict[str, Any]:
    """Save active document, optionally to a specified SolidWorks document path."""
    return _result("save", lambda: executor.save_active(_request_id(request_id), path))


@mcp.tool()
def solidworks_export_active(path: str, request_id: str | None = None) -> dict[str, Any]:
    """Export active document as STEP, IGES, STL, PDF, DXF, or DWG."""
    return _result("export", lambda: executor.export_active(_request_id(request_id), path))


@mcp.tool()
def solidworks_create_spur_gear(
    output_path: str,
    tooth_count: int = 20,
    module_mm: float = 2.0,
    thickness_mm: float = 10.0,
    bore_diameter_mm: float = 10.0,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create, save and report a straight-tooth conceptual spur gear with a central bore.

    This is an explicit non-involute concept model; use a verified standards-based
    gear compiler for manufactured power-transmission geometry.
    """
    return _result("create_spur_gear", lambda: executor.create_spur_gear(
        _request_id(request_id), output_path, tooth_count, module_mm, thickness_mm, bore_diameter_mm
    ))


@mcp.tool()
def solidworks_execute_feature_graph(
    feature_graph: dict[str, Any],
    output_path: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Execute a validated native SolidWorks Feature Graph and save a .sldprt.

    Supported native features include sketches with lines/circles/arcs/splines,
    boss extrusions and revolves, cut extrusions, reference axes, circular
    patterns, edge fillets and edge chamfers. Arbitrary Python, VBA and raw COM
    calls are intentionally not accepted.
    """
    return _result(
        "execute_feature_graph",
        lambda: executor.execute_feature_graph(_request_id(request_id), feature_graph, output_path),
    )


@mcp.tool()
def solidworks_create_sphere(
    output_path: str,
    diameter_mm: float = 50.0,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a native sphere using a construction centerline and 360-degree revolve."""
    return _result(
        "create_sphere",
        lambda: executor.create_sphere(_request_id(request_id), output_path, diameter_mm),
    )


@mcp.tool()
def solidworks_create_involute_spur_gear(
    output_path: str,
    tooth_count: int = 20,
    module_mm: float = 2.0,
    pressure_angle_deg: float = 20.0,
    thickness_mm: float = 10.0,
    bore_diameter_mm: float = 10.0,
    root_fillet_mm: float = 0.45,
    tip_chamfer_mm: float = 0.25,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a native, editable involute spur gear with named SolidWorks features.

    The part is built as GearBlank -> InvoluteToothSketch -> ToothBoss ->
    ToothCircularPattern -> BoreCut -> RootFillet -> TipChamfer and is saved
    directly as a native .sldprt without STEP import.
    """
    return _result(
        "create_involute_spur_gear",
        lambda: executor.create_involute_spur_gear(
            _request_id(request_id),
            output_path,
            tooth_count,
            module_mm,
            pressure_angle_deg,
            thickness_mm,
            bore_diameter_mm,
            root_fillet_mm,
            tip_chamfer_mm,
        ),
    )


@mcp.tool()
def solidworks_create_two_stage_reducer(
    output_path: str,
    module_mm: float = 2.0,
    pressure_angle_deg: float = 20.0,
    stage1_teeth: tuple[int, int] = (20, 40),
    stage2_teeth: tuple[int, int] = (20, 60),
    gear_thickness_mm: float = 10.0,
    axial_gap_mm: float = 8.0,
    bore_diameters_mm: tuple[float, float, float] = (10.0, 12.0, 14.0),
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a native two-stage parallel-shaft involute gear reducer.

    Four editable gears are arranged on three keyed shafts. The intermediate
    driven gear and pinion share one axis, with the second stage placed on an
    offset plane for a compact compound-gear layout.
    """
    return _result(
        "create_two_stage_reducer",
        lambda: executor.create_two_stage_reducer(
            _request_id(request_id),
            output_path,
            module_mm=module_mm,
            pressure_angle_deg=pressure_angle_deg,
            stage1_teeth=stage1_teeth,
            stage2_teeth=stage2_teeth,
            gear_thickness_mm=gear_thickness_mm,
            axial_gap_mm=axial_gap_mm,
            bore_diameters_mm=bore_diameters_mm,
        ),
    )


@mcp.tool()
def solidworks_create_output_shaft_from_dwg(
    output_path: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create the native output shaft defined by 输出轴零件图.DWG."""
    return _result(
        "create_output_shaft_from_dwg",
        lambda: executor.create_output_shaft_from_dwg(
            _request_id(request_id),
            output_path,
        ),
    )


@mcp.tool()
def solidworks_inspect_active(request_id: str | None = None, include_features: bool = False) -> dict[str, Any]:
    """Return active metadata; request the bounded feature tree only when it is needed."""
    return _result("inspect", lambda: executor.inspect_active(_request_id(request_id), include_features))


@mcp.tool()
def solidworks_set_dimension(
    dimension_name: str,
    value: float,
    unit: str = "mm",
    configuration: str = "this",
    configuration_names: list[str] | None = None,
    rebuild: bool = True,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Set one existing dimension in-place without recreating or saving the model.

    Use a fully qualified SolidWorks dimension name such as D1@Boss-Extrude1.
    Units: mm, cm, m, in, deg, or rad. Configuration: this, all, or specific.
    """
    return _result(
        "set_dimension",
        lambda: executor.set_dimension(
            _request_id(request_id),
            dimension_name,
            value,
            unit,
            configuration,
            configuration_names,
            rebuild,
        ),
    )


@mcp.tool()
def solidworks_set_feature_parameter(
    feature_name: str,
    parameter_name: str,
    value: float,
    unit: str = "mm",
    configuration: str = "this",
    rebuild: bool = True,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Replace one named feature parameter, for example D1 on Boss-Extrude1."""
    return _result(
        "set_feature_parameter",
        lambda: executor.set_feature_parameter(
            _request_id(request_id),
            feature_name,
            parameter_name,
            value,
            unit,
            configuration,
            rebuild,
        ),
    )


@mcp.tool()
def solidworks_edit_sketch(
    sketch_name: str,
    entities: list[dict[str, Any]],
    mode: str = "append",
    rebuild: bool = True,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Append to or replace an existing sketch with lines, circles, arcs, splines, or polylines."""
    return _result(
        "edit_sketch",
        lambda: executor.edit_sketch(
            _request_id(request_id), sketch_name, entities, mode, rebuild
        ),
    )


@mcp.tool()
def solidworks_delete_feature(
    feature_name: str,
    delete_children: bool = False,
    delete_absorbed: bool = False,
    rebuild: bool = True,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Delete one existing feature, optionally including child or absorbed features."""
    return _result(
        "delete_feature",
        lambda: executor.delete_feature(
            _request_id(request_id),
            feature_name,
            delete_children,
            delete_absorbed,
            rebuild,
        ),
    )


@mcp.tool()
def solidworks_rollback(
    location: str,
    feature_name: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Move the rollback bar to end, previous, before a feature, or after a feature."""
    return _result(
        "rollback",
        lambda: executor.rollback(_request_id(request_id), location, feature_name),
    )


@mcp.tool()
def solidworks_inspect_relations(
    include_topology: bool = True,
    include_persistent_references: bool = True,
    limit: int = 200,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Return feature parents/children, sketch segment counts, faces and edges.

    Persistent reference tokens can be passed to solidworks_select_references or
    solidworks_add_edge_feature in a later call.
    """
    return _result(
        "inspect_relations",
        lambda: executor.inspect_relations(
            _request_id(request_id),
            include_topology,
            include_persistent_references,
            limit,
        ),
    )


@mcp.tool()
def solidworks_select_references(
    reference_tokens: list[str],
    request_id: str | None = None,
) -> dict[str, Any]:
    """Select faces or edges returned by solidworks_inspect_relations."""
    return _result(
        "select_references",
        lambda: executor.select_references(_request_id(request_id), reference_tokens),
    )


@mcp.tool()
def solidworks_add_edge_feature(
    kind: str,
    feature_name: str,
    reference_tokens: list[str],
    size_mm: float,
    angle_deg: float = 45.0,
    rebuild: bool = True,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Add a fillet or chamfer to persistent edge references without rebuilding the part."""
    return _result(
        "add_edge_feature",
        lambda: executor.add_edge_feature(
            _request_id(request_id),
            kind,
            feature_name,
            reference_tokens,
            size_mm,
            angle_deg,
            rebuild,
        ),
    )


@mcp.tool()
def solidworks_add_stepped_shaft_with_keyway(
    axis_name: str = "GearAxis",
    bore_diameter_mm: float = 10.0,
    radial_clearance_mm: float = 0.1,
    gear_thickness_mm: float = 10.0,
    shoulder_diameter_mm: float = 14.0,
    shoulder_length_mm: float = 5.0,
    fit_extension_mm: float = 5.0,
    end_diameter_mm: float = 8.0,
    end_length_mm: float = 10.0,
    keyway_width_mm: float = 3.0,
    keyway_depth_mm: float = 1.6,
    rebuild: bool = True,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Add a separate coaxial stepped shaft with an axial keyway to the active gear part."""
    return _result(
        "add_stepped_shaft_with_keyway",
        lambda: executor.add_stepped_shaft_with_keyway(
            _request_id(request_id),
            axis_name=axis_name,
            bore_diameter_mm=bore_diameter_mm,
            radial_clearance_mm=radial_clearance_mm,
            gear_thickness_mm=gear_thickness_mm,
            shoulder_diameter_mm=shoulder_diameter_mm,
            shoulder_length_mm=shoulder_length_mm,
            fit_extension_mm=fit_extension_mm,
            end_diameter_mm=end_diameter_mm,
            end_length_mm=end_length_mm,
            keyway_width_mm=keyway_width_mm,
            keyway_depth_mm=keyway_depth_mm,
            rebuild=rebuild,
        ),
    )


@mcp.tool()
def solidworks_create_parametric_part(
    part_type: str,
    parameters: dict[str, Any],
    output_path: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a common native parametric part.

    Supported part types: block, cylinder, tube, flange, and stepped_shaft.
    """
    return _result(
        "create_parametric_part",
        lambda: executor.create_parametric_part(
            _request_id(request_id), part_type, parameters, output_path
        ),
    )


@mcp.tool()
def solidworks_compile_feature_graph(feature_graph: dict[str, Any]) -> dict[str, Any]:
    """Validate CAD-neutral Feature Graph IR and return a deterministic, auditable build plan."""
    return _result("compile_feature_graph", lambda: {"version": "1.0", "plan": compile_feature_graph(feature_graph)})


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import uuid
from typing import Any
from mcp.server.fastmcp.exceptions import ToolError

try:
    # MCP SDK 2.x promotes the high-level server to the public mcp.server API.
    from mcp.server import MCPServer as MCPApplication
except ImportError:  # pragma: no cover - exercised only with MCP SDK 1.x
    # MCP SDK 1.x exposed the same decorator-based API as FastMCP.
    from mcp.server.fastmcp import FastMCP as MCPApplication

from .safety import SafetyError, expected_document
from .contracts import ContractError
from .executor import SolidWorksExecutor
from .feature_graph import compile_feature_graph
from .modeling_rules import review_feature_graph

mcp = MCPApplication(
    "SolidWorks Agent MCP",
    instructions=(
        "Use Chinese display_name with stable graph IDs; use name_map for subsequent edits. "
        "Review complex intersections with solidworks_review_feature_graph; offline review is not CAD verification. "
        "Inspect the active document, then bind its exact title/path with solidworks_bind_document. "
        "Pass the returned document_token to every existing-model write. New part tools return their own token. "
        "Never retry a failed or timed-out mutation under a new ID without inspecting its outcome. "
        "Use solidworks_operation_result after a timeout. Saves refuse overwrite unless explicitly requested. "
        "Partial failures block writes until inspected and explicitly acknowledged on rebind. Runtime reload is disabled."
    ),
)
executor = SolidWorksExecutor()


def _request_id(request_id: str | None) -> str:
    return request_id.strip() if request_id and request_id.strip() else str(uuid.uuid4())


def _failure(operation: str, exc: Exception):
    raise ToolError(
        json.dumps(
            {
                "operation": operation,
                "error": {
                    "code": getattr(exc, "code", type(exc).__name__),
                    "message": str(exc),
                    "recoverable": False,
                    **getattr(exc, "details", {}),
                },
            },
            ensure_ascii=False,
        )
    ) from exc


def _result(
    operation: str, fn: Any, document_token: str | None = None
) -> dict[str, Any]:
    try:
        with expected_document(document_token):
            return {"operation": operation, "result": fn()}
    except SafetyError as exc:
        return _failure(operation, exc)
    except (ContractError, RuntimeError, TimeoutError) as exc:
        return _failure(operation, exc)
    except Exception as exc:
        return _failure(operation, exc)


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
    document_token: str | None = None,
) -> dict[str, Any]:
    """Inspect rebuild/dirty state, optionally performing a normal or full rebuild first."""
    return _result(
        "rebuild_diagnostics",
        lambda: executor.rebuild_diagnostics(
            _request_id(request_id),
            perform_rebuild,
            full_rebuild,
        ),
        document_token=document_token,
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
    document_token: str | None = None,
) -> dict[str, Any]:
    """Activate an existing configuration by exact name without saving the document."""
    return _result(
        "activate_configuration",
        lambda: executor.activate_configuration(
            _request_id(request_id), configuration_name
        ),
        document_token=document_token,
    )


@mcp.tool()
def solidworks_create_configuration(
    configuration_name: str,
    comment: str = "",
    alternate_name: str = "",
    activate: bool = True,
    request_id: str | None = None,
    document_token: str | None = None,
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
        document_token=document_token,
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
    document_token: str | None = None,
) -> dict[str, Any]:
    """Upsert validated text, numeric, or boolean custom properties without saving the document."""
    return _result(
        "set_custom_properties",
        lambda: executor.set_custom_properties(
            _request_id(request_id),
            properties,
            configuration_name,
        ),
        document_token=document_token,
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
    document_token: str | None = None,
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
        document_token=document_token,
    )


@mcp.tool()
def solidworks_reload_runtime() -> dict[str, Any]:
    """Retired endpoint: restart the idle MCP process to load new code."""
    return _failure(
        "reload_runtime",
        SafetyError(
            "RELOAD_DISABLED",
            "Runtime reload is disabled. Restart the MCP after the current operation has finished.",
        ),
    )


@mcp.tool()
def solidworks_create_part(title: str = "Part", request_id: str | None = None) -> dict[str, Any]:
    """Create a part from the configured .prtdot template. Reusing request_id is safe."""
    return _result("new_part", lambda: executor.new_part(_request_id(request_id), title))


@mcp.tool()
def solidworks_open_document(path: str, request_id: str | None = None) -> dict[str, Any]:
    """Open a native document or import a STEP/STP file as a part document."""
    return _result("open_document", lambda: executor.open_document(_request_id(request_id), path))


@mcp.tool()
def solidworks_save_active(
    path: str | None = None,
    request_id: str | None = None,
    document_token: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Save active document, optionally to a specified SolidWorks document path."""
    return _result(
        "save",
        lambda: executor.save_active(_request_id(request_id), path, overwrite),
        document_token=document_token,
    )


@mcp.tool()
def solidworks_export_active(
    path: str,
    request_id: str | None = None,
    document_token: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Export active document as STEP, IGES, STL, PDF, DXF, or DWG."""
    return _result(
        "export",
        lambda: executor.export_active(_request_id(request_id), path, overwrite),
        document_token=document_token,
    )


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
    document_token: str | None = None,
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
        document_token=document_token,
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
    document_token: str | None = None,
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
        document_token=document_token,
    )


@mcp.tool()
def solidworks_edit_sketch(
    sketch_name: str,
    entities: list[dict[str, Any]],
    mode: str = "append",
    rebuild: bool = True,
    request_id: str | None = None,
    document_token: str | None = None,
) -> dict[str, Any]:
    """Append to or replace an existing sketch with lines, circles, arcs, splines, or polylines."""
    return _result(
        "edit_sketch",
        lambda: executor.edit_sketch(
            _request_id(request_id), sketch_name, entities, mode, rebuild
        ),
        document_token=document_token,
    )


@mcp.tool()
def solidworks_delete_feature(
    feature_name: str,
    delete_children: bool = False,
    delete_absorbed: bool = False,
    rebuild: bool = True,
    request_id: str | None = None,
    document_token: str | None = None,
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
        document_token=document_token,
    )


@mcp.tool()
def solidworks_rollback(
    location: str,
    feature_name: str | None = None,
    request_id: str | None = None,
    document_token: str | None = None,
) -> dict[str, Any]:
    """Move the rollback bar to end, previous, before a feature, or after a feature."""
    return _result(
        "rollback",
        lambda: executor.rollback(_request_id(request_id), location, feature_name),
        document_token=document_token,
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
    document_token: str | None = None,
) -> dict[str, Any]:
    """Select faces or edges returned by solidworks_inspect_relations."""
    return _result(
        "select_references",
        lambda: executor.select_references(_request_id(request_id), reference_tokens),
        document_token=document_token,
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
    document_token: str | None = None,
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
        document_token=document_token,
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
    document_token: str | None = None,
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
        document_token=document_token,
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
    def compile_and_review():
        plan=compile_feature_graph(feature_graph)
        return {"version":"1.0","plan":plan,"planning_review":review_feature_graph(feature_graph,plan)}
    return _result("compile_feature_graph", compile_and_review)


@mcp.tool()
def solidworks_review_feature_graph(feature_graph: dict[str, Any]) -> dict[str, Any]:
    """Offline name/reference, plane and intersection-risk review; does not certify CAD geometry."""
    return _result("review_feature_graph",lambda:review_feature_graph(feature_graph))


def main() -> None:
    mcp.run(transport="stdio")


@mcp.tool()
def solidworks_bind_document(
    title: str,
    expected_path: str | None = None,
    acknowledge_partial_changes: bool = False,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Bind the exact active document; pass the returned token to each existing-model write."""
    return _result(
        "bind_document",
        lambda: executor.bind_document(
            _request_id(request_id), title, expected_path, acknowledge_partial_changes
        ),
    )


@mcp.tool()
def solidworks_operation_result(request_id: str) -> dict[str, Any]:
    """Read durable RUNNING/SUCCEEDED/FAILED/UNKNOWN outcome without entering COM."""
    return _result(
        "operation_result", lambda: executor.session.operation_result(request_id)
    )


if __name__ == "__main__":
    main()

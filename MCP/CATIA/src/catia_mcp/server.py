from __future__ import annotations

import uuid
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .com_runtime import CatiaUnavailable
from .contracts import ContractError
from .executor import CatiaExecutor


INSTRUCTIONS = """Drive CATIA V5 through registered Automation interfaces.

Use capability and live-session probes before modeling. All COM work is serialized.
Prefer small native modeling operations and inspect after important updates. Simulation
must stay inside CATIA Analysis/ELFINI; no third-party solver is exposed. A returned
Compute call is process completion, not proof of valid physics: inspect the model,
mesh, result images and generated report before accepting a simulation.
"""

mcp = FastMCP("CATIA Agent MCP", instructions=INSTRUCTIONS)
executor = CatiaExecutor()


def _request_id(value: str | None) -> str:
    return value.strip() if value and value.strip() else str(uuid.uuid4())


def _result(operation: str, function: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return {"operation": operation, "result": function()}
    except (ContractError, CatiaUnavailable, RuntimeError, TimeoutError) as exc:
        return {"operation": operation, "error": {"message": str(exc), "recoverable": True}}
    except Exception as exc:
        return {
            "operation": operation,
            "error": {"message": f"{type(exc).__name__}: {exc}", "recoverable": True},
        }


@mcp.tool()
def catia_health_check() -> dict[str, Any]:
    """Inspect CATIA installations, COM registration and Analysis typelib without launching CATIA."""
    return executor.health_check()


@mcp.tool()
def catia_operation_status() -> dict[str, Any]:
    """Return serialized COM worker state without entering the queue."""
    return executor.operation_status()


@mcp.tool()
def catia_connect(start_if_missing: bool = False) -> dict[str, Any]:
    """Attach to CATIA; explicitly opt in to launching the selected configured V5 environment."""
    return _result("connect", lambda: executor.connect(start_if_missing))


@mcp.tool()
def catia_list_documents(request_id: str | None = None) -> dict[str, Any]:
    """List open CATIA documents and their native document kinds."""
    return _result("list_documents", lambda: executor.list_documents(_request_id(request_id)))


@mcp.tool()
def catia_create_part(title: str = "Part", request_id: str | None = None) -> dict[str, Any]:
    """Create a new native CATPart document."""
    return _result("create_part", lambda: executor.create_part(_request_id(request_id), title))


@mcp.tool()
def catia_create_product(title: str = "Product", request_id: str | None = None) -> dict[str, Any]:
    """Create a new native CATProduct assembly document."""
    return _result("create_product", lambda: executor.create_product(_request_id(request_id), title))


@mcp.tool()
def catia_open_document(path: str, request_id: str | None = None) -> dict[str, Any]:
    """Open a CATIA/native exchange document inside configured allowed roots."""
    return _result("open_document", lambda: executor.open_document(_request_id(request_id), path))


@mcp.tool()
def catia_save_active(path: str | None = None, request_id: str | None = None) -> dict[str, Any]:
    """Save active document, optionally SaveAs to a workspace-bounded native path."""
    return _result("save_active", lambda: executor.save_active(_request_id(request_id), path))


@mcp.tool()
def catia_export_active(path: str, format_name: str | None = None, request_id: str | None = None) -> dict[str, Any]:
    """Export active document to a supported CATIA format within configured roots."""
    return _result("export_active", lambda: executor.export_active(_request_id(request_id), path, format_name))


@mcp.tool()
def catia_create_sketch(
    name: str,
    entities: list[dict[str, Any]],
    plane: str = "xy",
    body_name: str = "PartBody",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a native sketch from screened line/circle/rectangle/polyline entities."""
    return _result(
        "create_sketch",
        lambda: executor.create_sketch(_request_id(request_id), name, plane, entities, body_name),
    )


@mcp.tool()
def catia_surface_capabilities(request_id: str | None = None) -> dict[str, Any]:
    """Probe live CATIA GSD/Part Design surface factories and documented quality-check limits."""
    return _result(
        "surface_capabilities",
        lambda: executor.surface_capabilities(_request_id(request_id)),
    )


@mcp.tool()
def catia_create_geometrical_set(
    name: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create or reuse a native CATIA geometrical set (HybridBody)."""
    return _result(
        "create_geometrical_set",
        lambda: executor.create_geometrical_set(_request_id(request_id), name),
    )


@mcp.tool()
def catia_create_3d_points(
    points: list[dict[str, Any]],
    geometrical_set: str = "Wireframe",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create named native 3D coordinate points in a geometrical set; coordinates are millimetres."""
    return _result(
        "create_3d_points",
        lambda: executor.create_3d_points(_request_id(request_id), points, geometrical_set),
    )


@mcp.tool()
def catia_create_spline(
    name: str,
    point_names: list[str],
    closed: bool = False,
    constraints: list[dict[str, Any]] | None = None,
    geometrical_set: str = "Wireframe",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create an open/closed 3D spline through named points with optional G1/G2 curve constraints."""
    return _result(
        "create_spline",
        lambda: executor.create_spline(
            _request_id(request_id),
            name,
            point_names,
            closed,
            constraints,
            geometrical_set,
        ),
    )


@mcp.tool()
def catia_create_offset_plane(
    name: str,
    base_plane: str,
    offset_mm: float,
    orientation: bool = False,
    geometrical_set: str = "Reference Geometry",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a native offset plane from XY/YZ/ZX or another named plane."""
    return _result(
        "create_offset_plane",
        lambda: executor.create_offset_plane(
            _request_id(request_id),
            name,
            base_plane,
            offset_mm,
            orientation,
            geometrical_set,
        ),
    )


@mcp.tool()
def catia_create_connect_curve(
    name: str,
    curve1_name: str,
    point1_name: str,
    curve2_name: str,
    point2_name: str,
    continuity1: str = "g1",
    continuity2: str = "g1",
    tension1: float = 1.0,
    tension2: float = 1.0,
    orientation1: int = 1,
    orientation2: int = 1,
    trim: bool = False,
    geometrical_set: str = "Wireframe",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a native connect curve with independently selectable G0/G1/G2 end continuity."""
    kwargs = dict(
        name=name,
        curve1_name=curve1_name,
        point1_name=point1_name,
        curve2_name=curve2_name,
        point2_name=point2_name,
        continuity1=continuity1,
        continuity2=continuity2,
        tension1=tension1,
        tension2=tension2,
        orientation1=orientation1,
        orientation2=orientation2,
        trim=trim,
        geometrical_set=geometrical_set,
    )
    return _result(
        "create_connect_curve",
        lambda: executor.create_connect_curve(_request_id(request_id), **kwargs),
    )


@mcp.tool()
def catia_create_loft(
    name: str,
    section_names: list[str],
    guide_names: list[str] | None = None,
    closing_point_names: list[str] | None = None,
    section_orientations: list[int] | None = None,
    coupling: str = "ratio",
    context: str = "surface",
    start_tangent_name: str | None = None,
    end_tangent_name: str | None = None,
    smooth_angle_deg: float | None = None,
    smooth_deviation_mm: float | None = None,
    geometrical_set: str = "Surfaces",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create native HybridShapeLoft with ordered sections, guides, coupling and closing points."""
    kwargs = dict(
        name=name,
        section_names=section_names,
        guide_names=guide_names,
        closing_point_names=closing_point_names,
        section_orientations=section_orientations,
        coupling=coupling,
        context=context,
        start_tangent_name=start_tangent_name,
        end_tangent_name=end_tangent_name,
        smooth_angle_deg=smooth_angle_deg,
        smooth_deviation_mm=smooth_deviation_mm,
        geometrical_set=geometrical_set,
    )
    return _result("create_loft", lambda: executor.create_loft(_request_id(request_id), **kwargs))


@mcp.tool()
def catia_create_fill(
    name: str,
    boundary_names: list[str],
    support_names: list[str | None] | None = None,
    continuities: list[str] | None = None,
    constraints: list[str] | None = None,
    geometrical_set: str = "Surfaces",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a native Fill with one or more boundaries and optional G0/G1/G2 supports."""
    kwargs = dict(
        name=name,
        boundary_names=boundary_names,
        support_names=support_names,
        continuities=continuities,
        constraints=constraints,
        geometrical_set=geometrical_set,
    )
    return _result(
        "create_fill",
        lambda: executor.create_fill(_request_id(request_id), **kwargs),
    )


@mcp.tool()
def catia_join_surfaces(
    name: str,
    element_names: list[str],
    tolerance_mm: float = 0.001,
    angular_tolerance_deg: float = 0.5,
    connex: bool = True,
    manifold: bool = True,
    simplify: bool = True,
    geometrical_set: str = "Surfaces",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Join native curves/surfaces with distance, angular, connexity and manifold controls."""
    kwargs = dict(
        name=name,
        element_names=element_names,
        tolerance_mm=tolerance_mm,
        angular_tolerance_deg=angular_tolerance_deg,
        connex=connex,
        manifold=manifold,
        simplify=simplify,
        geometrical_set=geometrical_set,
    )
    return _result(
        "join_surfaces",
        lambda: executor.join_surfaces(_request_id(request_id), **kwargs),
    )


@mcp.tool()
def catia_heal_surfaces(
    name: str,
    body_names: list[str],
    continuity: str = "g1",
    distance_objective_mm: float = 0.001,
    merging_distance_mm: float = 0.001,
    tangency_angle_deg: float = 0.5,
    sharpness_angle_deg: float = 0.5,
    geometrical_set: str = "Surfaces",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Heal native surfaces with G0/G1, distance, merging and angular objectives."""
    kwargs = dict(
        name=name,
        body_names=body_names,
        continuity=continuity,
        distance_objective_mm=distance_objective_mm,
        merging_distance_mm=merging_distance_mm,
        tangency_angle_deg=tangency_angle_deg,
        sharpness_angle_deg=sharpness_angle_deg,
        geometrical_set=geometrical_set,
    )
    return _result(
        "heal_surfaces",
        lambda: executor.heal_surfaces(_request_id(request_id), **kwargs),
    )


@mcp.tool()
def catia_create_boundary(
    name: str,
    surface_name: str,
    geometrical_set: str = "Wireframe",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create the complete boundary curve of a named surface."""
    return _result(
        "create_boundary",
        lambda: executor.create_boundary(
            _request_id(request_id), name, surface_name, geometrical_set
        ),
    )


@mcp.tool()
def catia_close_surface(
    name: str,
    surface_name: str,
    body_name: str = "PartBody",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Close a named surface into a native Part Design solid feature."""
    return _result(
        "close_surface",
        lambda: executor.close_surface(
            _request_id(request_id), name, surface_name, body_name
        ),
    )


@mcp.tool()
def catia_thick_surface(
    name: str,
    surface_name: str,
    top_offset_mm: float,
    bottom_offset_mm: float = 0.0,
    reverse_direction: bool = False,
    body_name: str = "PartBody",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Thicken a named surface into a native Part Design solid feature."""
    kwargs = dict(
        name=name,
        surface_name=surface_name,
        top_offset_mm=top_offset_mm,
        bottom_offset_mm=bottom_offset_mm,
        reverse_direction=reverse_direction,
        body_name=body_name,
    )
    return _result(
        "thick_surface",
        lambda: executor.thick_surface(_request_id(request_id), **kwargs),
    )


@mcp.tool()
def catia_check_surface_quality(
    element_names: list[str],
    gap_pairs: list[list[str]] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Update and measure named surfaces, report Join topology modes and requested minimum gaps."""
    return _result(
        "check_surface_quality",
        lambda: executor.check_surface_quality(
            _request_id(request_id), element_names, gap_pairs
        ),
    )


@mcp.tool()
def catia_add_pad(
    sketch_name: str,
    length_mm: float,
    name: str = "Pad",
    body_name: str = "PartBody",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a native Part Design pad from an existing sketch."""
    return _result("add_pad", lambda: executor.add_pad(_request_id(request_id), sketch_name, length_mm, name, body_name))


@mcp.tool()
def catia_add_pocket(
    sketch_name: str,
    length_mm: float,
    name: str = "Pocket",
    body_name: str = "PartBody",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a native Part Design pocket from an existing sketch."""
    return _result("add_pocket", lambda: executor.add_pocket(_request_id(request_id), sketch_name, length_mm, name, body_name))


@mcp.tool()
def catia_create_parametric_part(
    part_type: str,
    parameters: dict[str, Any],
    output_path: str,
    title: str = "ParametricPart",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create and save a native block, cylinder or tube as CATPart."""
    return _result(
        "create_parametric_part",
        lambda: executor.create_parametric_part(_request_id(request_id), part_type, parameters, title, output_path),
    )


@mcp.tool()
def catia_add_components(paths: list[str], request_id: str | None = None) -> dict[str, Any]:
    """Insert existing component files into the active CATProduct."""
    return _result("add_components", lambda: executor.add_components(_request_id(request_id), paths))


@mcp.tool()
def catia_list_materials(
    catalog_path: str,
    family_name: str | None = None,
    limit: int = 500,
    request_id: str | None = None,
) -> dict[str, Any]:
    """List CATIA material families/materials from an allowed or installed CATMaterial catalog."""
    return _result(
        "list_materials",
        lambda: executor.list_materials(_request_id(request_id), catalog_path, family_name, limit),
    )


@mcp.tool()
def catia_apply_material(
    catalog_path: str,
    family_name: str,
    material_name: str,
    link_mode: int = 1,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Apply a native CATIA material to active CATPart/CATProduct; required for physical Analysis."""
    return _result(
        "apply_material",
        lambda: executor.apply_material(
            _request_id(request_id), catalog_path, family_name, material_name, link_mode
        ),
    )


@mcp.tool()
def catia_update_active(request_id: str | None = None) -> dict[str, Any]:
    """Update the active CATPart or CATProduct."""
    return _result("update_active", lambda: executor.update_active(_request_id(request_id)))


@mcp.tool()
def catia_inspect_active(
    include_parameters: bool = False,
    limit: int = 200,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Inspect active document metadata, native bodies/features or assembly components."""
    return _result("inspect_active", lambda: executor.inspect_active(_request_id(request_id), include_parameters, limit))


@mcp.tool()
def catia_list_parameters(limit: int = 200, request_id: str | None = None) -> dict[str, Any]:
    """List bounded native CATPart parameters."""
    return _result("list_parameters", lambda: executor.list_parameters(_request_id(request_id), limit))


@mcp.tool()
def catia_set_parameter(
    parameter_name: str,
    value: str,
    update: bool = True,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Set a named CATIA parameter using a unit-bearing expression such as '25 mm'."""
    return _result("set_parameter", lambda: executor.set_parameter(_request_id(request_id), parameter_name, value, update))


@mcp.tool()
def catia_capture_view(path: str, request_id: str | None = None) -> dict[str, Any]:
    """Fit and capture the active CATIA viewer to a workspace-bounded BMP file."""
    return _result("capture_view", lambda: executor.capture_view(_request_id(request_id), path))


@mcp.tool()
def catia_close_active(
    save: bool = False,
    discard_unsaved: bool = False,
    expected_document_name: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Close active document; optional expected name prevents closing the wrong UI document."""
    return _result(
        "close_active",
        lambda: executor.close_active(
            _request_id(request_id), save, discard_unsaved, expected_document_name
        ),
    )


@mcp.tool()
def catia_analysis_catalog() -> dict[str, Any]:
    """Return native CATIA Analysis identifiers plus methods detected in the installed typelib."""
    return executor.analysis_catalog()


@mcp.tool()
def catia_create_analysis_document(
    source_document_name: str | None = None,
    case_type: str | None = None,
    analysis_name: str = "Analysis",
    output_path: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create CATAnalysis, import an open CATPart/CATProduct and optionally create a native case."""
    return _result(
        "create_analysis_document",
        lambda: executor.create_analysis_document(
            _request_id(request_id), source_document_name, case_type, analysis_name, output_path
        ),
    )


@mcp.tool()
def catia_inspect_analysis(limit: int = 200, request_id: str | None = None) -> dict[str, Any]:
    """Inspect active CATAnalysis models, cases, sets, entities, supports, mesh parts and images."""
    return _result("inspect_analysis", lambda: executor.inspect_analysis(_request_id(request_id), limit))


@mcp.tool()
def catia_add_analysis_case(
    case_type: str,
    model_index: int = 1,
    name: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Add a native CATIA Analysis case using its installed late-type identifier."""
    return _result("add_analysis_case", lambda: executor.add_analysis_case(_request_id(request_id), case_type, model_index, name))


@mcp.tool()
def catia_run_analysis_transition(
    transition_name: str,
    model_index: int = 1,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Run a fixed-name CATIA Analysis workbench transition for installed advanced modules."""
    return _result(
        "run_analysis_transition",
        lambda: executor.run_analysis_transition(_request_id(request_id), transition_name, model_index),
    )


@mcp.tool()
def catia_add_analysis_solution(
    solution_type: str,
    model_index: int = 1,
    case_index: int = 1,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Add a native solution definition to an existing CATIA Analysis case."""
    return _result(
        "add_analysis_solution",
        lambda: executor.add_analysis_solution(_request_id(request_id), solution_type, model_index, case_index),
    )


@mcp.tool()
def catia_add_analysis_set(
    set_type: str,
    set_kind: str = "in",
    model_index: int = 1,
    case_index: int = 1,
    scope: str = "case",
    name: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Add a native Analysis set without restricting installed module-specific set types."""
    kwargs = dict(set_type=set_type, set_kind=set_kind, model_index=model_index, case_index=case_index, scope=scope, name=name)
    return _result("add_analysis_set", lambda: executor.add_analysis_set(_request_id(request_id), **kwargs))


@mcp.tool()
def catia_add_analysis_entity(
    entity_type: str,
    model_index: int = 1,
    case_index: int = 1,
    scope: str = "case",
    set_type: str | None = None,
    set_index: int | None = None,
    name: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Add a native load/restraint/property entity by CATIA late type, then return its components."""
    kwargs = dict(
        entity_type=entity_type, model_index=model_index, case_index=case_index,
        scope=scope, set_type=set_type, set_index=set_index, name=name,
    )
    return _result("add_analysis_entity", lambda: executor.add_analysis_entity(_request_id(request_id), **kwargs))


@mcp.tool()
def catia_set_analysis_entity_value(
    component: str,
    label: str,
    value: str | int | float | bool,
    model_index: int = 1,
    case_index: int = 1,
    scope: str = "case",
    set_type: str | None = None,
    set_index: int | None = None,
    entity_index: int = 1,
    line_index: int = 1,
    column_index: int = 1,
    layer_index: int = 1,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Set a native CATIA Analysis entity component value through AnalysisEntity.SetValue."""
    kwargs = dict(
        component=component, label=label, value=value, model_index=model_index,
        case_index=case_index, scope=scope, set_type=set_type, set_index=set_index,
        entity_index=entity_index, line_index=line_index, column_index=column_index,
        layer_index=layer_index,
    )
    return _result("set_analysis_entity_value", lambda: executor.set_analysis_entity_value(_request_id(request_id), **kwargs))


@mcp.tool()
def catia_add_analysis_mesh_part(
    mesh_type: str,
    model_index: int = 1,
    name: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Add a native CATIA mesh part by installed late type; module-specific types remain available."""
    kwargs = dict(mesh_type=mesh_type, model_index=model_index, name=name)
    return _result("add_analysis_mesh_part", lambda: executor.add_analysis_mesh_part(_request_id(request_id), **kwargs))


@mcp.tool()
def catia_set_analysis_mesh_specification(
    specification_name: str,
    value: str | int | float | bool,
    model_index: int = 1,
    mesh_part_index: int = 1,
    update: bool = True,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Set an installed mesh-part global specification, such as size or sag."""
    kwargs = dict(
        specification_name=specification_name, value=value, model_index=model_index,
        mesh_part_index=mesh_part_index, update=update,
    )
    return _result(
        "set_analysis_mesh_specification",
        lambda: executor.set_analysis_mesh_specification(_request_id(request_id), **kwargs),
    )


@mcp.tool()
def catia_bind_analysis_mesh_support(
    source_document_name: str,
    search_query: str,
    selection_index: int = 1,
    model_index: int = 1,
    mesh_part_index: int = 1,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Bind a native CATIA mesh part to source geometry found by Selection.Search."""
    kwargs = dict(
        source_document_name=source_document_name, search_query=search_query,
        selection_index=selection_index, model_index=model_index, mesh_part_index=mesh_part_index,
    )
    return _result(
        "bind_analysis_mesh_support",
        lambda: executor.bind_analysis_mesh_support(_request_id(request_id), **kwargs),
    )


@mcp.tool()
def catia_bind_analysis_support(
    source_document_name: str,
    search_query: str,
    selection_index: int = 1,
    model_index: int = 1,
    case_index: int = 1,
    scope: str = "case",
    set_type: str | None = None,
    set_index: int | None = None,
    entity_index: int = 1,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Bind an Analysis entity to source geometry found by CATIA Selection.Search."""
    kwargs = dict(
        source_document_name=source_document_name, search_query=search_query,
        selection_index=selection_index, model_index=model_index, case_index=case_index,
        scope=scope, set_type=set_type, set_index=set_index, entity_index=entity_index,
    )
    return _result("bind_analysis_support", lambda: executor.bind_analysis_support(_request_id(request_id), **kwargs))


@mcp.tool()
def catia_compute_analysis(
    model_index: int = 1,
    case_index: int = 1,
    mesh_only: bool = False,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Run CATIA's internal Analysis/ELFINI compute for one case; no external solver is used."""
    return _result(
        "compute_analysis",
        lambda: executor.compute_analysis(_request_id(request_id), model_index, case_index, mesh_only),
    )


@mcp.tool()
def catia_create_analysis_result_image(
    image_type: str,
    model_index: int = 1,
    case_index: int = 1,
    scope: str = "case",
    set_type: str | None = None,
    set_index: int | None = None,
    hide_existing_images: bool = True,
    show_mesh: bool = False,
    duplicate: bool = False,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create and update a CATIA-native post-processing image by installed image type."""
    kwargs = dict(
        image_type=image_type, model_index=model_index, case_index=case_index, scope=scope,
        set_type=set_type, set_index=set_index, hide_existing_images=hide_existing_images,
        show_mesh=show_mesh, duplicate=duplicate,
    )
    return _result(
        "create_analysis_result_image",
        lambda: executor.create_analysis_result_image(_request_id(request_id), **kwargs),
    )


@mcp.tool()
def catia_export_analysis_result_data(
    folder: str,
    file_name: str,
    extension_type: str,
    model_index: int = 1,
    case_index: int = 1,
    scope: str = "case",
    set_type: str | None = None,
    set_index: int | None = None,
    image_index: int = 1,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Export numerical data from a CATIA Analysis result image into a bounded folder."""
    kwargs = dict(
        file_name=file_name, extension_type=extension_type, model_index=model_index,
        case_index=case_index, scope=scope, set_type=set_type, set_index=set_index,
        image_index=image_index,
    )
    return _result(
        "export_analysis_result_data",
        lambda: executor.export_analysis_result_data(_request_id(request_id), folder, **kwargs),
    )


@mcp.tool()
def catia_build_analysis_report(
    folder: str,
    title: str,
    model_index: int = 1,
    case_index: int = 1,
    add_created_images: bool = True,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build CATIA's native HTML Analysis report and inventory produced artifacts."""
    return _result(
        "build_analysis_report",
        lambda: executor.build_analysis_report(
            _request_id(request_id), folder, title, model_index, case_index, add_created_images
        ),
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

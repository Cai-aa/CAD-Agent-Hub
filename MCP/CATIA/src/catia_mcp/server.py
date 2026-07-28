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

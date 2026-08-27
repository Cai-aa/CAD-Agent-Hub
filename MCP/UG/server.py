#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Production stdio MCP entry point for a live Siemens NX session."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

try:
    from .nx_bridge_client import NXBridgeClient
except ImportError:  # Direct script execution from the repository.
    from nx_bridge_client import NXBridgeClient

CLIENT = NXBridgeClient()
ALLOW_EXECUTE = os.environ.get("NX_MCP_ALLOW_EXECUTE", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

INSTRUCTIONS = """Drive the currently open Siemens NX work part through a local bridge.

Call ping first. NXOpen operations use NX's non-blocking .NET remoting service. Prefer
dedicated tools and use run_python only for NXOpen operations that have no
dedicated tool. NXOpen, session, workPart, and displayPart are preloaded for
run_python. Validate the returned part and feature information after mutations.
"""

mcp = FastMCP("siemens-nx", instructions=INSTRUCTIONS)


async def _bridge(
    method: str,
    params: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(CLIENT.request, method, params, timeout)


async def _simulation_runtime_bridge(
    method: str,
    params: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        CLIENT.request,
        "simulation_runtime_proxy",
        {"runtime_method": method, "runtime_params": params or {}},
        timeout,
    )


@mcp.tool()
async def ping() -> dict[str, Any]:
    """Verify the live NX bridge and report process, part, and bridge details."""
    return await _bridge("ping")


@mcp.tool()
async def get_part_summary(max_features: int = 100) -> dict[str, Any]:
    """Read the active work part, bodies, and a bounded feature list."""
    if not 1 <= max_features <= 1000:
        raise ValueError("max_features must be between 1 and 1000")
    return await _bridge("part_summary", {"max_features": max_features})


@mcp.tool()
async def inspect_work_part_geometry(max_bodies: int = 50) -> dict[str, Any]:
    """Read body topology counts and edge-derived XYZ bounds from the work part."""
    if not 1 <= max_bodies <= 500:
        raise ValueError("max_bodies must be between 1 and 500")
    return await _bridge("body_geometry", {"max_bodies": max_bodies})


@mcp.tool()
async def inspect_body_topology(
    body_index: int = 0,
    body_feature_id: str | None = None,
    body_occurrence: int = 0,
) -> dict[str, Any]:
    """Inspect faces and edges with stable geometry references and legacy indices."""
    return await _bridge(
        "body_topology",
        {
            "body_index": body_index,
            "body_feature_id": body_feature_id,
            "body_occurrence": body_occurrence,
        },
    )


@mcp.tool()
async def resolve_topology(
    kind: str,
    selector: dict[str, Any],
    body_index: int = 0,
    body_feature_id: str | None = None,
    body_occurrence: int = 0,
    unique: bool = True,
) -> dict[str, Any]:
    """Resolve a face or edge by stable ID or geometry criteria instead of list index."""
    return await _bridge(
        "resolve_topology",
        {
            "kind": kind,
            "selector": selector,
            "body_index": body_index,
            "body_feature_id": body_feature_id,
            "body_occurrence": body_occurrence,
            "unique": unique,
        },
    )


@mcp.tool()
async def inspect_feature(feature_id: str) -> dict[str, Any]:
    """Inspect a feature by name, journal identifier, or zero-based feature index."""
    return await _bridge("inspect_feature", {"feature_id": feature_id})


@mcp.tool()
async def set_feature_expression(
    feature_id: str,
    expression_id: str,
    right_hand_side: str,
) -> dict[str, Any]:
    """Edit one expression owned by a feature, rebuild, and return old/new values."""
    return await _bridge(
        "set_feature_expression",
        {"feature_id": feature_id, "expression_id": expression_id, "right_hand_side": right_hand_side},
        timeout=180.0,
    )


@mcp.tool()
async def rebuild_work_part() -> dict[str, Any]:
    """Update the active work part and return feature diagnostics."""
    return await _bridge("rebuild_work_part", {}, timeout=180.0)


@mcp.tool()
async def create_part(
    file_name: str,
    units: str = "millimeters",
) -> dict[str, Any]:
    """Create and display a new .prt inside the bridge's NX_MCP_WORKSPACE."""
    if not file_name.strip():
        raise ValueError("file_name must be a non-empty string")
    return await _bridge("create_part", {"file_name": file_name, "units": units})


@mcp.tool()
async def create_parametric_sketch(
    geometry: list[dict[str, Any]],
    name: str = "MCP_SKETCH",
    plane: str = "XY",
    origin: list[float] | None = None,
    constraints: list[dict[str, Any]] | None = None,
    dimensions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a native NX sketch with named geometry, constraints, and dimensions.

    Geometry supports line, rectangle, circle, and arc. Constraints support
    horizontal, vertical, fixed, coincident, parallel, perpendicular,
    equal_length, and concentric. Dimensions support horizontal, vertical,
    length, radius, and diameter. Rectangle edges are named `<name>_0` through
    `<name>_3` counter-clockwise from the rectangle origin.
    """
    return await _bridge(
        "create_parametric_sketch",
        {
            "name": name,
            "plane": plane,
            "origin": origin or [0.0, 0.0, 0.0],
            "geometry": geometry,
            "constraints": constraints or [],
            "dimensions": dimensions or [],
        },
        timeout=180.0,
    )


@mcp.tool()
async def inspect_sketch(sketch_id: str | None = None) -> dict[str, Any]:
    """Inspect native sketches, stable identifiers, geometry, expressions, and status."""
    return await _bridge("inspect_sketch", {"sketch_id": sketch_id})


@mcp.tool()
async def extrude_sketch(
    sketch_id: str,
    distance: float,
    direction: list[float] | None = None,
    start: float = 0.0,
    feature_name: str = "MCP_EXTRUDE",
) -> dict[str, Any]:
    """Extrude the closed loops of a native NX sketch as a new solid body."""
    if distance <= 0:
        raise ValueError("distance must be greater than zero")
    return await _bridge(
        "extrude_sketch",
        {
            "sketch_id": sketch_id,
            "distance": distance,
            "direction": direction or [0.0, 0.0, 1.0],
            "start": start,
            "feature_name": feature_name,
        },
        timeout=180.0,
    )


@mcp.tool()
async def revolve_sketch(
    sketch_id: str,
    axis_origin: list[float] | None = None,
    axis_direction: list[float] | None = None,
    start_angle_deg: float = 0.0,
    end_angle_deg: float = 360.0,
    feature_name: str = "MCP_REVOLVE",
) -> dict[str, Any]:
    """Revolve the closed loops of a native NX sketch into a new solid body."""
    return await _bridge(
        "revolve_sketch",
        {
            "sketch_id": sketch_id,
            "axis_origin": axis_origin or [0.0, 0.0, 0.0],
            "axis_direction": axis_direction or [0.0, 1.0, 0.0],
            "start_angle_deg": start_angle_deg,
            "end_angle_deg": end_angle_deg,
            "feature_name": feature_name,
        },
        timeout=180.0,
    )


@mcp.tool()
async def loft_sketches(
    sketch_ids: list[str],
    solid: bool = True,
    feature_name: str = "MCP_LOFT",
) -> dict[str, Any]:
    """Loft a solid or sheet through two or more native NX sketches."""
    if len(sketch_ids) < 2:
        raise ValueError("sketch_ids must contain at least two sketches")
    return await _bridge(
        "loft_sketches",
        {
            "sketch_ids": sketch_ids,
            "solid": solid,
            "feature_name": feature_name,
        },
        timeout=180.0,
    )


@mcp.tool()
async def sweep_sketch(
    profile_sketch_id: str,
    guide_sketch_id: str,
    solid: bool = True,
    feature_name: str = "MCP_SWEEP",
) -> dict[str, Any]:
    """Sweep one native sketch profile along another native sketch guide."""
    return await _bridge(
        "sweep_sketch",
        {
            "profile_sketch_id": profile_sketch_id,
            "guide_sketch_id": guide_sketch_id,
            "solid": solid,
            "feature_name": feature_name,
        },
        timeout=180.0,
    )


@mcp.tool()
async def boolean_bodies(
    target_body_index: int,
    tool_body_index: int,
    operation: str = "unite",
    retain_target: bool = False,
    retain_tool: bool = False,
    feature_name: str = "MCP_BOOLEAN",
) -> dict[str, Any]:
    """Unite, subtract, or intersect two solid bodies selected by body index."""
    return await _bridge(
        "boolean_bodies",
        {
            "target_body_index": target_body_index,
            "tool_body_index": tool_body_index,
            "operation": operation,
            "retain_target": retain_target,
            "retain_tool": retain_tool,
            "feature_name": feature_name,
        },
        timeout=180.0,
    )


@mcp.tool()
async def create_cylindrical_hole(
    origin: list[float],
    diameter: float,
    depth: float,
    direction: list[float] | None = None,
    target_body_index: int = 0,
    feature_name: str = "MCP_HOLE",
) -> dict[str, Any]:
    """Cut a cylindrical hole into a selected solid body."""
    return await _bridge(
        "create_cylindrical_hole",
        {
            "origin": origin,
            "diameter": diameter,
            "depth": depth,
            "direction": direction or [0.0, 0.0, -1.0],
            "target_body_index": target_body_index,
            "feature_name": feature_name,
        },
        timeout=180.0,
    )


@mcp.tool()
async def fillet_edges(
    edge_indices: list[int],
    radius: float,
    body_index: int = 0,
    feature_name: str = "MCP_FILLET",
) -> dict[str, Any]:
    """Create a constant-radius edge blend on indexed body edges."""
    return await _bridge(
        "fillet_edges",
        {"body_index": body_index, "edge_indices": edge_indices, "radius": radius, "feature_name": feature_name},
        timeout=180.0,
    )


@mcp.tool()
async def chamfer_edges(
    edge_indices: list[int],
    distance: float,
    body_index: int = 0,
    feature_name: str = "MCP_CHAMFER",
) -> dict[str, Any]:
    """Create a symmetric-offset chamfer on indexed body edges."""
    return await _bridge(
        "chamfer_edges",
        {"body_index": body_index, "edge_indices": edge_indices, "distance": distance, "feature_name": feature_name},
        timeout=180.0,
    )


@mcp.tool()
async def shell_body(
    remove_face_indices: list[int],
    thickness: float,
    body_index: int = 0,
    feature_name: str = "MCP_SHELL",
) -> dict[str, Any]:
    """Shell a solid body and remove the selected indexed faces."""
    return await _bridge(
        "shell_body",
        {"body_index": body_index, "remove_face_indices": remove_face_indices, "thickness": thickness, "feature_name": feature_name},
        timeout=180.0,
    )


@mcp.tool()
async def linear_pattern_feature(
    feature_id: str,
    count: int,
    spacing: float,
    direction: list[float] | None = None,
    feature_name: str = "MCP_PATTERN",
) -> dict[str, Any]:
    """Pattern a named or journal-identified feature along a linear direction."""
    return await _bridge(
        "linear_pattern_feature",
        {"feature_id": feature_id, "count": count, "spacing": spacing, "direction": direction or [1.0, 0.0, 0.0], "feature_name": feature_name},
        timeout=180.0,
    )


@mcp.tool()
async def mirror_feature(
    feature_id: str,
    plane_origin: list[float] | None = None,
    plane_normal: list[float] | None = None,
    feature_name: str = "MCP_MIRROR",
) -> dict[str, Any]:
    """Mirror a named or journal-identified feature about a specified plane."""
    return await _bridge(
        "mirror_feature",
        {"feature_id": feature_id, "plane_origin": plane_origin or [0.0, 0.0, 0.0], "plane_normal": plane_normal or [1.0, 0.0, 0.0], "feature_name": feature_name},
        timeout=180.0,
    )


@mcp.tool()
async def create_block(
    length: float = 100.0,
    width: float = 60.0,
    height: float = 40.0,
    origin: list[float] | None = None,
) -> dict[str, Any]:
    """Create an NX block at [x, y, z] in the active work part."""
    if length <= 0 or width <= 0 or height <= 0:
        raise ValueError("length, width, and height must all be greater than zero")
    actual_origin = origin if origin is not None else [0.0, 0.0, 0.0]
    if len(actual_origin) != 3:
        raise ValueError("origin must contain exactly three coordinates")
    return await _bridge(
        "create_block",
        {
            "length": length,
            "width": width,
            "height": height,
            "origin": actual_origin,
        },
    )


@mcp.tool()
async def create_involute_gear(
    module: float = 2.0,
    teeth: int = 20,
    pressure_angle_deg: float = 20.0,
    face_width: float = 10.0,
    bore_diameter: float = 10.0,
    flank_segments: int = 10,
    arc_segments: int = 4,
) -> dict[str, Any]:
    """Create a standard full-depth external involute spur gear in the work part."""
    return await _bridge(
        "create_involute_gear",
        {
            "module": module,
            "teeth": teeth,
            "pressure_angle_deg": pressure_angle_deg,
            "face_width": face_width,
            "bore_diameter": bore_diameter,
            "flank_segments": flank_segments,
            "arc_segments": arc_segments,
        },
        timeout=180.0,
    )


@mcp.tool()
async def save_work_part() -> dict[str, Any]:
    """Save the active NX work part and report the resulting file state."""
    return await _bridge("save_work_part")


@mcp.tool()
async def export_exchange(
    file_name: str,
    format: str = "step",
    application_protocol: str = "ap242",
    include_curves: bool = True,
    flatten_assembly: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Export the displayed NX part to STEP or Parasolid inside NX_MCP_WORKSPACE."""
    return await _bridge(
        "export_exchange",
        {
            "file_name": file_name,
            "format": format,
            "application_protocol": application_protocol,
            "include_curves": include_curves,
            "flatten_assembly": flatten_assembly,
            "overwrite": overwrite,
        },
        timeout=300.0,
    )


@mcp.tool()
async def import_exchange(
    file_name: str,
    format: str = "auto",
    application_protocol: str = "ap242",
    include_curves: bool = True,
    sew_surfaces: bool = True,
    simplify_geometry: bool = True,
    flatten_assembly: bool = False,
) -> dict[str, Any]:
    """Import a workspace STEP or Parasolid file into the active NX work part."""
    return await _bridge(
        "import_exchange",
        {
            "file_name": file_name,
            "format": format,
            "application_protocol": application_protocol,
            "include_curves": include_curves,
            "sew_surfaces": sew_surfaces,
            "simplify_geometry": simplify_geometry,
            "flatten_assembly": flatten_assembly,
        },
        timeout=300.0,
    )


@mcp.tool()
async def inspect_assembly(max_depth: int = 10) -> dict[str, Any]:
    """Read the active assembly component tree, prototypes, and transforms."""
    return await _bridge("inspect_assembly", {"max_depth": max_depth})


@mcp.tool()
async def add_component(
    file_name: str,
    component_name: str | None = None,
    origin: list[float] | None = None,
    orientation: list[float] | None = None,
    reference_set: str = "Entire Part",
    layer: int = 1,
) -> dict[str, Any]:
    """Add a workspace .prt as an assembly component with an explicit transform."""
    return await _bridge(
        "add_component",
        {
            "file_name": file_name,
            "component_name": component_name,
            "origin": origin or [0.0, 0.0, 0.0],
            "orientation": orientation
            or [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            "reference_set": reference_set,
            "layer": layer,
        },
        timeout=180.0,
    )


@mcp.tool()
async def move_component(
    component_id: str,
    translation: list[float] | None = None,
    rotation: list[float] | None = None,
) -> dict[str, Any]:
    """Move an assembly component by a delta translation and rotation matrix."""
    return await _bridge(
        "move_component",
        {
            "component_id": component_id,
            "translation": translation or [0.0, 0.0, 0.0],
            "rotation": rotation
            or [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        },
        timeout=180.0,
    )


@mcp.tool()
async def add_assembly_constraint(
    component1_id: str,
    type: str = "fix",
    component2_id: str | None = None,
    body1_index: int = 0,
    face1_index: int = 0,
    body2_index: int = 0,
    face2_index: int = 0,
    alignment: str = "infer",
    value: float = 0.0,
    fix_second: bool = True,
) -> dict[str, Any]:
    """Create a persistent fix, touch, fit, concentric, distance, or angular assembly constraint."""
    return await _bridge(
        "add_assembly_constraint",
        {
            "component1_id": component1_id,
            "component2_id": component2_id,
            "type": type,
            "body1_index": body1_index,
            "face1_index": face1_index,
            "body2_index": body2_index,
            "face2_index": face2_index,
            "alignment": alignment,
            "value": value,
            "fix_second": fix_second,
        },
        timeout=180.0,
    )


@mcp.tool()
async def inspect_assembly_constraints() -> dict[str, Any]:
    """Read persistent assembly constraints, references, expressions, and solve status."""
    return await _bridge("inspect_assembly_constraints", {}, timeout=120.0)


@mcp.tool()
async def extract_face_surface(
    face_indices: list[int],
    body_index: int = 0,
    associative: bool = True,
    feature_name: str = "MCP_EXTRACT_SURFACE",
) -> dict[str, Any]:
    """Extract indexed solid faces as an associative NX sheet surface."""
    return await _bridge(
        "extract_face_surface",
        {
            "body_index": body_index,
            "face_indices": face_indices,
            "associative": associative,
            "feature_name": feature_name,
        },
        timeout=180.0,
    )


@mcp.tool()
async def offset_surface(
    face_indices: list[int],
    distance: float,
    body_index: int = 0,
    tolerance: float = 0.01,
    approximate: bool = False,
    feature_name: str = "MCP_OFFSET_SURFACE",
) -> dict[str, Any]:
    """Create a native offset sheet surface from indexed faces."""
    return await _bridge(
        "offset_surface",
        {
            "body_index": body_index,
            "face_indices": face_indices,
            "distance": distance,
            "tolerance": tolerance,
            "approximate": approximate,
            "feature_name": feature_name,
        },
        timeout=180.0,
    )


@mcp.tool()
async def sew_sheet_bodies(
    target_body_index: int,
    tool_body_indices: list[int],
    tolerance: float = 0.01,
    keep_target: bool = False,
    keep_tools: bool = False,
    feature_name: str = "MCP_SEW",
) -> dict[str, Any]:
    """Sew a target sheet body to one or more tool sheet bodies."""
    return await _bridge(
        "sew_sheet_bodies",
        {
            "target_body_index": target_body_index,
            "tool_body_indices": tool_body_indices,
            "tolerance": tolerance,
            "keep_target": keep_target,
            "keep_tools": keep_tools,
            "feature_name": feature_name,
        },
        timeout=180.0,
    )


@mcp.tool()
async def trim_sheet_body(
    target_body_index: int,
    boundary_body_indices: list[int],
    region_point: list[float],
    method: str = "keep",
    tolerance: float = 0.01,
    apply_to_copy: bool = False,
    extend_boundary: bool = True,
    feature_name: str = "MCP_TRIM_SHEET",
) -> dict[str, Any]:
    """Trim a target sheet body with sheet-body boundaries and keep/discard a region."""
    return await _bridge(
        "trim_sheet_body",
        {
            "target_body_index": target_body_index,
            "boundary_body_indices": boundary_body_indices,
            "region_point": region_point,
            "method": method,
            "tolerance": tolerance,
            "apply_to_copy": apply_to_copy,
            "extend_boundary": extend_boundary,
            "feature_name": feature_name,
        },
        timeout=180.0,
    )


@mcp.tool()
async def create_sheet_metal_tab(
    sketch_id: str,
    thickness: float,
    feature_name: str = "MCP_SHEET_METAL_TAB",
) -> dict[str, Any]:
    """Create a native NX sheet-metal base tab from a closed sketch."""
    return await _bridge(
        "create_sheet_metal_tab",
        {
            "sketch_id": sketch_id,
            "thickness": thickness,
            "feature_name": feature_name,
        },
        timeout=180.0,
    )


@mcp.tool()
async def create_sheet_metal_flange(
    edge_index: int,
    length: float,
    angle_deg: float = 90.0,
    bend_radius: float = 1.5,
    body_index: int = 0,
    feature_name: str = "MCP_FLANGE",
) -> dict[str, Any]:
    """Create a full-edge native NX sheet-metal flange on an indexed linear edge."""
    return await _bridge(
        "create_sheet_metal_flange",
        {
            "body_index": body_index,
            "edge_index": edge_index,
            "length": length,
            "angle_deg": angle_deg,
            "bend_radius": bend_radius,
            "feature_name": feature_name,
        },
        timeout=180.0,
    )


@mcp.tool()
async def create_sheet_metal_bend(
    bend_line_sketch_id: str,
    target_face_selector: dict[str, Any],
    angle_deg: float = 90.0,
    bend_radius: float = 1.5,
    direction: str = "normal",
    fixed_side: str = "left",
    body_index: int = 0,
    body_feature_id: str | None = None,
    body_occurrence: int = 0,
    feature_name: str = "MCP_BEND",
) -> dict[str, Any]:
    """Bend a sheet-metal body along a sketch line using a stable target-face selector."""
    return await _bridge(
        "create_sheet_metal_bend",
        {
            "bend_line_sketch_id": bend_line_sketch_id,
            "target_face_selector": target_face_selector,
            "angle_deg": angle_deg,
            "bend_radius": bend_radius,
            "direction": direction,
            "fixed_side": fixed_side,
            "body_index": body_index,
            "body_feature_id": body_feature_id,
            "body_occurrence": body_occurrence,
            "feature_name": feature_name,
        },
        timeout=240.0,
    )


@mcp.tool()
async def create_flat_pattern(
    upward_face_index: int,
    x_axis_edge_index: int | None = None,
    body_index: int = 0,
    associative: bool = True,
    feature_name: str = "MCP_FLAT_PATTERN",
) -> dict[str, Any]:
    """Create an associative native NX flat-pattern feature for a sheet-metal body."""
    return await _bridge(
        "create_flat_pattern",
        {
            "body_index": body_index,
            "upward_face_index": upward_face_index,
            "x_axis_edge_index": x_axis_edge_index,
            "associative": associative,
            "feature_name": feature_name,
        },
        timeout=240.0,
    )


@mcp.tool()
async def export_flat_pattern_dxf(
    flat_pattern_id: str,
    file_name: str,
    revision: str = "r2018",
    include_bend_lines: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Export a native NX flat-pattern feature to a validated workspace DXF file."""
    return await _bridge(
        "export_flat_pattern_dxf",
        {
            "flat_pattern_id": flat_pattern_id,
            "file_name": file_name,
            "revision": revision,
            "include_bend_lines": include_bend_lines,
            "overwrite": overwrite,
        },
        timeout=300.0,
    )


@mcp.tool()
async def create_drawing_sheet(
    name: str = "MCP_SHEET_1",
    size: str = "A4",
    scale_numerator: float = 1.0,
    scale_denominator: float = 1.0,
    projection: str = "first",
    create_base_view: bool = True,
    model_view: str = "Top",
    view_position: list[float] | None = None,
) -> dict[str, Any]:
    """Create a metric drawing sheet and optionally place a native base view."""
    return await _bridge(
        "create_drawing_sheet",
        {
            "name": name,
            "size": size,
            "scale_numerator": scale_numerator,
            "scale_denominator": scale_denominator,
            "projection": projection,
            "create_base_view": create_base_view,
            "model_view": model_view,
            "view_position": view_position or [148.5, 105.0, 0.0],
        },
        timeout=180.0,
    )


@mcp.tool()
async def create_projected_view(
    view_position: list[float],
    parent_view_id: str | None = None,
    view_name: str = "MCP_PROJECTED_VIEW",
) -> dict[str, Any]:
    """Create an orthographic projected drafting view from a parent view."""
    return await _bridge(
        "create_projected_view",
        {
            "parent_view_id": parent_view_id,
            "view_position": view_position,
            "view_name": view_name,
        },
        timeout=180.0,
    )


@mcp.tool()
async def create_drafting_note(
    lines: list[str],
    position: list[float],
    note_name: str = "MCP_NOTE",
) -> dict[str, Any]:
    """Create a named drafting note on the current drawing sheet."""
    return await _bridge(
        "create_drafting_note",
        {"lines": lines, "position": position, "note_name": note_name},
        timeout=180.0,
    )


@mcp.tool()
async def create_drawing_linear_dimension(
    first_edge_selector: dict[str, Any],
    second_edge_selector: dict[str, Any],
    position: list[float],
    measurement: str = "horizontal",
    view_id: str | None = None,
    body_index: int = 0,
    body_feature_id: str | None = None,
    body_occurrence: int = 0,
    first_associativity_point: list[float] | None = None,
    second_associativity_point: list[float] | None = None,
    dimension_name: str = "MCP_LINEAR_DIMENSION",
) -> dict[str, Any]:
    """Create an associative drawing dimension between two stably selected model edges."""
    return await _bridge(
        "create_drawing_linear_dimension",
        {
            "first_edge_selector": first_edge_selector,
            "second_edge_selector": second_edge_selector,
            "position": position,
            "measurement": measurement,
            "view_id": view_id,
            "body_index": body_index,
            "body_feature_id": body_feature_id,
            "body_occurrence": body_occurrence,
            "first_associativity_point": first_associativity_point,
            "second_associativity_point": second_associativity_point,
            "dimension_name": dimension_name,
        },
        timeout=240.0,
    )


@mcp.tool()
async def inspect_drawing_annotations() -> dict[str, Any]:
    """Read all drafting notes and dimensions with text, origins, and measured sizes."""
    return await _bridge("inspect_drawing_annotations", {}, timeout=120.0)


@mcp.tool()
async def get_cam_capabilities(template_type: str | None = None) -> dict[str, Any]:
    """Inspect live NX CAM availability, templates, safety state, and supported tools."""
    return await _bridge(
        "cam_capabilities", {"template_type": template_type}, timeout=180.0
    )


@mcp.tool()
async def initialize_cam_setup(
    template_name: str = "mill_planar",
    switch_to_manufacturing: bool = False,
) -> dict[str, Any]:
    """Initialize the NX CAM session and add a native CAM setup to the work part."""
    return await _bridge(
        "initialize_cam_setup",
        {
            "template_name": template_name,
            "switch_to_manufacturing": switch_to_manufacturing,
        },
        timeout=240.0,
    )


@mcp.tool()
async def create_cam_milling_context(
    origin: list[float],
    part_body_indices: list[int],
    blank_body_indices: list[int] | None = None,
    program_name: str = "MCP_PROGRAM",
    method_name: str = "MCP_METHOD",
    mcs_name: str = "MCP_MCS",
    workpiece_name: str = "MCP_WORKPIECE",
    x_axis: list[float] | None = None,
    y_axis: list[float] | None = None,
    fixture_offset: int = 1,
    blank_offset: float = 2.0,
    blank_offsets: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Create non-template milling parents, MCS, and workpiece for real toolpath generation."""
    return await _bridge(
        "create_cam_milling_context",
        {
            "origin": origin,
            "part_body_indices": part_body_indices,
            "blank_body_indices": blank_body_indices,
            "program_name": program_name,
            "method_name": method_name,
            "mcs_name": mcs_name,
            "workpiece_name": workpiece_name,
            "x_axis": x_axis or [1.0, 0.0, 0.0],
            "y_axis": y_axis or [0.0, 1.0, 0.0],
            "fixture_offset": fixture_offset,
            "blank_offset": blank_offset,
            "blank_offsets": blank_offsets or {},
        },
        timeout=300.0,
    )


@mcp.tool()
async def inspect_cam_setup(max_depth: int = 4) -> dict[str, Any]:
    """Read the native NX CAM program, method, geometry, tool, and operation trees."""
    return await _bridge("inspect_cam_setup", {"max_depth": max_depth}, timeout=180.0)


@mcp.tool()
async def define_cam_mcs(
    origin: list[float],
    x_axis: list[float] | None = None,
    y_axis: list[float] | None = None,
    mcs_name: str = "MCS_MAIN",
    fixture_offset: int = 1,
) -> dict[str, Any]:
    """Set a native milling MCS and fixture offset using explicit coordinates."""
    return await _bridge(
        "define_cam_mcs",
        {
            "origin": origin,
            "x_axis": x_axis or [1.0, 0.0, 0.0],
            "y_axis": y_axis or [0.0, 1.0, 0.0],
            "mcs_name": mcs_name,
            "fixture_offset": fixture_offset,
        },
        timeout=180.0,
    )


@mcp.tool()
async def define_cam_workpiece(
    body_indices: list[int] | None = None,
    blank_body_indices: list[int] | None = None,
    fixture_body_indices: list[int] | None = None,
    workpiece_name: str = "WORKPIECE",
    blank_offset: float = 2.0,
    blank_offsets: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Assign part, stock, and optional fixture/check bodies for milling simulation."""
    return await _bridge(
        "define_cam_workpiece",
        {
            "body_indices": body_indices,
            "blank_body_indices": blank_body_indices,
            "fixture_body_indices": fixture_body_indices,
            "workpiece_name": workpiece_name,
            "blank_offset": blank_offset,
            "blank_offsets": blank_offsets or {},
        },
        timeout=240.0,
    )


@mcp.tool()
async def create_cam_mill_tool(
    name: str,
    diameter: float,
    flute_length: float,
    overall_length: float,
    flute_count: int = 4,
    tool_number: int = 1,
    length_offset_register: int | None = None,
    shank_diameter: float | None = None,
    holder_sections: list[dict[str, float]] | None = None,
    shank_sections: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Create/update a milling tool including parameterized cutter, shank, and holder geometry."""
    return await _bridge(
        "create_cam_mill_tool",
        {
            "name": name,
            "diameter": diameter,
            "flute_length": flute_length,
            "overall_length": overall_length,
            "flute_count": flute_count,
            "tool_number": tool_number,
            "length_offset_register": (
                tool_number if length_offset_register is None else length_offset_register
            ),
            "shank_diameter": shank_diameter,
            "holder_sections": holder_sections,
            "shank_sections": shank_sections,
        },
        timeout=180.0,
    )


@mcp.tool()
async def create_cam_operation(
    name: str,
    template_subtype: str,
    template_type: str = "mill_planar",
    program_name: str = "MCP_PROGRAM",
    method_name: str = "MCP_METHOD",
    tool_name: str = "T01_END_MILL",
    geometry_name: str = "MCP_WORKPIECE",
) -> dict[str, Any]:
    """Create a native CAM operation after validating its template against live NX."""
    return await _bridge(
        "create_cam_operation",
        {
            "name": name,
            "template_type": template_type,
            "template_subtype": template_subtype,
            "program_name": program_name,
            "method_name": method_name,
            "tool_name": tool_name,
            "geometry_name": geometry_name,
        },
        timeout=240.0,
    )


@mcp.tool()
async def set_cam_operation_geometry(
    operation_name: str,
    part_body_indices: list[int] | None = None,
    cut_area_face_selectors: list[dict[str, Any]] | None = None,
    wall_face_selectors: list[dict[str, Any]] | None = None,
    check_face_selectors: list[dict[str, Any]] | None = None,
    body_index: int = 0,
    body_feature_id: str | None = None,
    body_occurrence: int = 0,
    depth_per_cut: float | None = None,
    top_offset: float | None = None,
    safe_clearance: float | None = None,
    spindle_rpm: float | None = None,
    cut_feed: float | None = None,
    approach_feed: float | None = None,
    retract_feed: float | None = None,
) -> dict[str, Any]:
    """Assign stable face selections and core cutting depths to a CAM operation."""
    return await _bridge(
        "set_cam_operation_geometry",
        {
            "operation_name": operation_name,
            "part_body_indices": part_body_indices,
            "cut_area_face_selectors": cut_area_face_selectors,
            "wall_face_selectors": wall_face_selectors,
            "check_face_selectors": check_face_selectors,
            "body_index": body_index,
            "body_feature_id": body_feature_id,
            "body_occurrence": body_occurrence,
            "depth_per_cut": depth_per_cut,
            "top_offset": top_offset,
            "safe_clearance": safe_clearance,
            "spindle_rpm": spindle_rpm,
            "cut_feed": cut_feed,
            "approach_feed": approach_feed,
            "retract_feed": retract_feed,
        },
        timeout=240.0,
    )


@mcp.tool()
async def configure_cam_milling_operation(
    operation_name: str,
    part_body_indices: list[int] | None = None,
    cut_area_face_selectors: list[dict[str, Any]] | None = None,
    wall_face_selectors: list[dict[str, Any]] | None = None,
    check_face_selectors: list[dict[str, Any]] | None = None,
    body_index: int = 0,
    body_feature_id: str | None = None,
    body_occurrence: int = 0,
    depth_per_cut: float | None = None,
    top_offset: float | None = None,
    safe_clearance: float | None = None,
    spindle_rpm: float | None = None,
    cut_feed: float | None = None,
    approach_feed: float | None = None,
    retract_feed: float | None = None,
) -> dict[str, Any]:
    """Configure NX 2412 face/cavity milling geometry, depths, speeds, and feeds."""
    return await _bridge(
        "configure_cam_milling_operation",
        {
            "operation_name": operation_name,
            "part_body_indices": part_body_indices,
            "cut_area_face_selectors": cut_area_face_selectors,
            "wall_face_selectors": wall_face_selectors,
            "check_face_selectors": check_face_selectors,
            "body_index": body_index,
            "body_feature_id": body_feature_id,
            "body_occurrence": body_occurrence,
            "depth_per_cut": depth_per_cut,
            "top_offset": top_offset,
            "safe_clearance": safe_clearance,
            "spindle_rpm": spindle_rpm,
            "cut_feed": cut_feed,
            "approach_feed": approach_feed,
            "retract_feed": retract_feed,
        },
        timeout=300.0,
    )


@mcp.tool()
async def inspect_cam_operations(
    operation_names: list[str] | None = None,
) -> dict[str, Any]:
    """Read CAM operation status and toolpath length/time metrics."""
    return await _bridge(
        "inspect_cam_operations", {"operation_names": operation_names}, timeout=180.0
    )


@mcp.tool()
async def inspect_cam_operation_details(
    operation_names: list[str] | None = None,
) -> dict[str, Any]:
    """Read CAM parents, template flags, geometry sets, feeds, and builder validation."""
    return await _bridge(
        "inspect_cam_operation_details",
        {"operation_names": operation_names},
        timeout=240.0,
    )


@mcp.tool()
async def generate_cam_toolpath(
    operation_names: list[str] | None = None,
    set_machining_data: bool = False,
    backend: str = "auto",
) -> dict[str, Any]:
    """Generate selected CAM toolpaths and verify that each operation owns a path."""
    return await _bridge(
        "generate_cam_toolpath",
        {
            "operation_names": operation_names,
            "set_machining_data": set_machining_data,
            "backend": backend,
        },
        timeout=600.0,
    )


@mcp.tool()
async def inspect_machine_simulation_readiness(
    program_name: str = "MCP_PROGRAM",
    operation_names: list[str] | None = None,
    required_axes: list[str] | None = None,
    machine_query: str | None = None,
    max_candidates: int = 20,
    require_axis_limits: bool = True,
    require_tool_geometry: bool = True,
    require_shank_geometry: bool = False,
    require_holder_geometry: bool = False,
    require_workpiece_geometry: bool = True,
    require_fixture_geometry: bool = False,
) -> dict[str, Any]:
    """Check paths, axis limits, parameterized tooling, workpiece, stock, fixture, and machine binding."""
    return await _bridge(
        "inspect_machine_simulation_readiness",
        {
            "program_name": program_name,
            "operation_names": operation_names,
            "required_axes": required_axes or [],
            "machine_query": machine_query,
            "max_candidates": max_candidates,
            "require_axis_limits": require_axis_limits,
            "require_tool_geometry": require_tool_geometry,
            "require_shank_geometry": require_shank_geometry,
            "require_holder_geometry": require_holder_geometry,
            "require_workpiece_geometry": require_workpiece_geometry,
            "require_fixture_geometry": require_fixture_geometry,
        },
        timeout=240.0,
    )


@mcp.tool()
async def inspect_machine_source_profile(source_profile: str) -> dict[str, Any]:
    """Inspect a configured NX machine source part without displaying it or returning its path."""
    return await _bridge(
        "inspect_machine_source_profile",
        {"source_profile": source_profile},
        timeout=600.0,
    )


@mcp.tool()
async def inspect_machine_kinematic_plan(source_profile: str) -> dict[str, Any]:
    """Convert a configured external machine definition into a path-redacted NX build plan."""
    return await _bridge(
        "inspect_machine_kinematic_plan",
        {"source_profile": source_profile},
        timeout=600.0,
    )


@mcp.tool()
async def create_machine_build_workspace(
    source_profile: str,
    workspace_file_name: str,
    dry_run: bool = True,
    confirmation: str = "",
) -> dict[str, Any]:
    """Copy an aliased source .prt into an isolated machine-build workspace; dry-run is the default."""
    return await _bridge(
        "create_machine_build_workspace",
        {
            "source_profile": source_profile,
            "workspace_file_name": workspace_file_name,
            "dry_run": dry_run,
            "confirmation": confirmation,
        },
        timeout=900.0,
    )


@mcp.tool()
async def create_smart_machine_kit_workspace(
    source_profile: str,
    workspace_file_name: str,
    dry_run: bool = True,
    confirmation: str = "",
) -> dict[str, Any]:
    """Create and activate a blank NX part suitable for the Smart Machine Kit template route."""
    return await _bridge(
        "create_smart_machine_kit_workspace",
        {
            "source_profile": source_profile,
            "workspace_file_name": workspace_file_name,
            "dry_run": dry_run,
            "confirmation": confirmation,
        },
        timeout=900.0,
    )


@mcp.tool()
async def activate_machine_build_workspace(
    workspace_file_name: str,
    recovery_token: str,
    preserve_current: bool = True,
    dry_run: bool = True,
    confirmation: str = "",
) -> dict[str, Any]:
    """Activate an isolated machine-build part after checking its recovery token and current save state."""
    return await _bridge(
        "activate_machine_build_workspace",
        {
            "workspace_file_name": workspace_file_name,
            "recovery_token": recovery_token,
            "preserve_current": preserve_current,
            "dry_run": dry_run,
            "confirmation": confirmation,
        },
        timeout=600.0,
    )


@mcp.tool()
async def restore_machine_build_recovery_part(
    workspace_file_name: str,
    recovery_token: str,
    dry_run: bool = True,
    confirmation: str = "",
) -> dict[str, Any]:
    """Restore the pre-build NX part recorded in the isolated workspace manifest."""
    return await _bridge(
        "restore_machine_build_recovery_part",
        {
            "workspace_file_name": workspace_file_name,
            "recovery_token": recovery_token,
            "dry_run": dry_run,
            "confirmation": confirmation,
        },
        timeout=600.0,
    )


@mcp.tool()
async def import_machine_component_geometry(
    source_profile: str,
    workspace_file_name: str,
    component_names: list[str] | None = None,
    start_layer: int = 201,
    dry_run: bool = True,
    confirmation: str = "",
) -> dict[str, Any]:
    """Import path-redacted, component-grouped STL geometry into the active isolated build part."""
    return await _bridge(
        "import_machine_component_geometry",
        {
            "source_profile": source_profile,
            "workspace_file_name": workspace_file_name,
            "component_names": component_names,
            "start_layer": start_layer,
            "dry_run": dry_run,
            "confirmation": confirmation,
        },
        timeout=1200.0,
    )


@mcp.tool()
async def build_machine_kinematics_from_profile(
    source_profile: str,
    workspace_file_name: str,
    channel_name: str = "TNC_640",
    dry_run: bool = True,
    confirmation: str = "",
) -> dict[str, Any]:
    """Build isolated low-level or Smart Machine Kit kinematics and reject metadata-only machine archives."""
    return await _bridge(
        "build_machine_kinematics_from_profile",
        {
            "source_profile": source_profile,
            "workspace_file_name": workspace_file_name,
            "channel_name": channel_name,
            "dry_run": dry_run,
            "confirmation": confirmation,
        },
        timeout=1200.0,
    )


@mcp.tool()
async def validate_machine_kinematics(
    source_profile: str,
    workspace_file_name: str,
    require_geometry: bool = True,
) -> dict[str, Any]:
    """Read back components, classes, axes, channel bindings, junctions, chains, and geometry without motion."""
    return await _bridge(
        "validate_machine_kinematics",
        {
            "source_profile": source_profile,
            "workspace_file_name": workspace_file_name,
            "require_geometry": require_geometry,
        },
        timeout=600.0,
    )


@mcp.tool()
async def probe_machine_axis_motion(
    source_profile: str,
    workspace_file_name: str,
    axis_name: str = "X",
    delta: float = 0.01,
    dry_run: bool = True,
    confirmation: str = "",
) -> dict[str, Any]:
    """Temporarily change one non-spindle axis by at most 0.1 mm/degree, read it back, and always undo it."""
    return await _bridge(
        "probe_machine_axis_motion",
        {
            "source_profile": source_profile,
            "workspace_file_name": workspace_file_name,
            "axis_name": axis_name,
            "delta": delta,
            "dry_run": dry_run,
            "confirmation": confirmation,
        },
        timeout=600.0,
    )


@mcp.tool()
async def retarget_machine_junctions_from_profile(
    source_profile: str,
    workspace_file_name: str,
    dry_run: bool = True,
    confirmation: str = "",
) -> dict[str, Any]:
    """Retarget every imported BC-template junction to absolute OEM machine-definition coordinates."""
    return await _bridge(
        "retarget_machine_junctions_from_profile",
        {
            "source_profile": source_profile,
            "workspace_file_name": workspace_file_name,
            "dry_run": dry_run,
            "confirmation": confirmation,
        },
        timeout=600.0,
    )


@mcp.tool()
async def export_machine_kit_from_reference(
    source_profile: str,
    workspace_file_name: str,
    output_file_name: str = "mikron_mill_e500u_tnc640.mtk",
    reference_container_file_name: str = "",
    graphics_file_name: str = "",
    overwrite: bool = False,
    dry_run: bool = True,
    confirmation: str = "",
) -> dict[str, Any]:
    """Create a complete sanitized MTK using NX's official kit container and the active OEM machine model."""
    return await _bridge(
        "export_machine_kit_from_reference",
        {
            "source_profile": source_profile,
            "workspace_file_name": workspace_file_name,
            "output_file_name": output_file_name,
            "reference_container_file_name": reference_container_file_name,
            "graphics_file_name": graphics_file_name,
            "overwrite": overwrite,
            "dry_run": dry_run,
            "confirmation": confirmation,
        },
        timeout=1200.0,
    )


@mcp.tool()
async def import_machine_kit_readback(
    machine_kit_file_name: str,
    source_profile: str = "",
    keep_imported: bool = False,
    evaluate_static_collisions: bool = False,
    dry_run: bool = True,
    confirmation: str = "",
    static_collision_confirmation: str = "",
) -> dict[str, Any]:
    """Import an MTK into an isolated shadow library; source_profile enables OEM collision-pair readback."""
    return await _bridge(
        "import_machine_kit_readback",
        {
            "machine_kit_file_name": machine_kit_file_name,
            "source_profile": source_profile,
            "keep_imported": keep_imported,
            "evaluate_static_collisions": evaluate_static_collisions,
            "dry_run": dry_run,
            "confirmation": confirmation,
            "static_collision_confirmation": static_collision_confirmation,
        },
        timeout=1200.0,
    )


@mcp.tool()
async def validate_machine_static_collisions(
    source_profile: str,
    workspace_file_name: str,
    evaluate_geometry: bool = False,
    confirmation: str = "",
) -> dict[str, Any]:
    """Evaluate persisted or OEM-defined collision pairs without moving an axis or starting simulation."""
    return await _bridge(
        "validate_machine_static_collisions",
        {
            "source_profile": source_profile,
            "workspace_file_name": workspace_file_name,
            "evaluate_geometry": evaluate_geometry,
            "confirmation": confirmation,
        },
        timeout=600.0,
    )


@mcp.tool()
async def bind_machine_tool_from_library(
    machine_libref: str,
    program_name: str = "MCP_PROGRAM",
    operation_names: list[str] | None = None,
    required_axes: list[str] | None = None,
    create_spindle_objects: bool = True,
    dry_run: bool = True,
    replace_existing: bool = False,
    reload_existing: bool = False,
    confirmation: str = "",
) -> dict[str, Any]:
    """Validate or bind an exact NX machine-library entry; dry-run is the safe default."""
    return await _bridge(
        "bind_machine_tool_from_library",
        {
            "machine_libref": machine_libref,
            "program_name": program_name,
            "operation_names": operation_names,
            "required_axes": required_axes or [],
            "create_spindle_objects": create_spindle_objects,
            "dry_run": dry_run,
            "replace_existing": replace_existing,
            "reload_existing": reload_existing,
            "confirmation": confirmation,
        },
        timeout=600.0,
    )


@mcp.tool()
async def bind_isolated_machine_kit_to_cam(
    machine_kit_file_name: str,
    machine_libref: str | None = None,
    source_profile: str | None = None,
    program_name: str = "MCP_PROGRAM",
    operation_names: list[str] | None = None,
    required_axes: list[str] | None = None,
    create_spindle_objects: bool = True,
    evaluate_static_collisions: bool = True,
    dry_run: bool = True,
    replace_existing: bool = False,
    reload_existing: bool = False,
    confirmation: str = "",
    replace_confirmation: str = "",
) -> dict[str, Any]:
    """Import an MTK into a workspace shadow library and bind it to the current CAM setup without changing the global NX machine library."""
    return await _bridge(
        "bind_isolated_machine_kit_to_cam",
        {
            "machine_kit_file_name": machine_kit_file_name,
            "machine_libref": machine_libref,
            "source_profile": source_profile,
            "program_name": program_name,
            "operation_names": operation_names,
            "required_axes": required_axes or [],
            "create_spindle_objects": create_spindle_objects,
            "evaluate_static_collisions": evaluate_static_collisions,
            "dry_run": dry_run,
            "replace_existing": replace_existing,
            "reload_existing": reload_existing,
            "confirmation": confirmation,
            "replace_confirmation": replace_confirmation,
        },
        timeout=1200.0,
    )


@mcp.tool()
async def start_machine_simulation_with_collision_stop(
    program_name: str = "MCP_PROGRAM",
    operation_names: list[str] | None = None,
    required_axes: list[str] | None = None,
    speed: int = 25,
    material_removal: bool = True,
    show_toolpath: bool = True,
    show_tool_trace: bool = False,
    play_immediately: bool = True,
    require_axis_limits: bool = True,
    require_tool_geometry: bool = True,
    require_shank_geometry: bool = True,
    require_holder_geometry: bool = True,
    require_workpiece_geometry: bool = True,
    require_fixture_geometry: bool = True,
) -> dict[str, Any]:
    """Start toolpath-driven machine simulation with collision, limit, holder, and rapid-IPW stops forced on."""
    parameters = {
            "program_name": program_name,
            "operation_names": operation_names,
            "required_axes": required_axes or [],
            "speed": speed,
            "material_removal": material_removal,
            "show_toolpath": show_toolpath,
            "show_tool_trace": show_tool_trace,
            "play_immediately": play_immediately,
            "require_axis_limits": require_axis_limits,
            "require_tool_geometry": require_tool_geometry,
            "require_shank_geometry": require_shank_geometry,
            "require_holder_geometry": require_holder_geometry,
            "require_workpiece_geometry": require_workpiece_geometry,
            "require_fixture_geometry": require_fixture_geometry,
        }
    readiness = await _bridge(
        "inspect_machine_simulation_readiness", parameters, timeout=300.0
    )
    if not readiness.get("machine_simulation_ready", False):
        raise RuntimeError(
            "Machine simulation is not ready; blockers=%s"
            % ",".join(readiness.get("blockers", []))
        )
    selected_names = readiness.get("selection", {}).get("operation_names") or []
    parameters["operation_names"] = selected_names
    runtime = await _simulation_runtime_bridge(
        "start_machine_simulation_with_collision_stop", parameters, timeout=600.0
    )
    runtime["part"] = readiness.get("part")
    runtime["readiness_passed"] = True
    runtime["requirements"] = readiness.get("requirements")
    return runtime


@mcp.tool()
async def inspect_active_machine_simulation() -> dict[str, Any]:
    """Read active simulation lifecycle events, machine time, cycle time, and armed stops."""
    return await _simulation_runtime_bridge(
        "inspect_active_machine_simulation", {}, timeout=180.0
    )


@mcp.tool()
async def stop_active_machine_simulation(release: bool = True) -> dict[str, Any]:
    """Stop the active simulation and optionally release its NX control panel."""
    return await _simulation_runtime_bridge(
        "stop_active_machine_simulation", {"release": release}, timeout=180.0
    )


@mcp.tool()
async def export_cam_clsf(
    file_name: str,
    operation_names: list[str] | None = None,
    units: str = "metric",
    clsf_format: str = "CLSF_STANDARD",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Export verified NX CAM toolpaths to a workspace-scoped neutral CLSF file."""
    return await _bridge(
        "export_cam_clsf",
        {
            "file_name": file_name,
            "operation_names": operation_names,
            "units": units,
            "clsf_format": clsf_format,
            "overwrite": overwrite,
        },
        timeout=600.0,
    )


@mcp.tool()
async def postprocess_cam_program_locked(
    file_name: str,
    machine_type: str,
    confirmation: str,
    operation_names: list[str] | None = None,
    units: str = "metric",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Postprocess CAM paths only after both environment and exact safety confirmation gates."""
    return await _bridge(
        "postprocess_cam_program_locked",
        {
            "file_name": file_name,
            "machine_type": machine_type,
            "confirmation": confirmation,
            "operation_names": operation_names,
            "units": units,
            "overwrite": overwrite,
        },
        timeout=900.0,
    )


@mcp.tool()
async def run_python(code: str, timeout: float | None = None) -> dict[str, Any]:
    """Execute NXOpen Python in the live session; assign `result` to return data."""
    if not ALLOW_EXECUTE:
        raise RuntimeError(
            "run_python is disabled. Set NX_MCP_ALLOW_EXECUTE=1 and restart "
            "the MCP server to enable arbitrary NXOpen execution."
        )
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code must be a non-empty string")
    return await _bridge("execute", {"code": code}, timeout)


def main() -> None:
    """Run the stdio MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()

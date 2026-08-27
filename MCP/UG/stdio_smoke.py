#!/usr/bin/env python3
"""Start server.py over stdio and verify MCP initialization/tool discovery."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent
EXPECTED = {
    "ping",
    "get_part_summary",
    "inspect_work_part_geometry",
    "inspect_body_topology",
    "resolve_topology",
    "inspect_feature",
    "set_feature_expression",
    "rebuild_work_part",
    "create_part",
    "create_block",
    "create_parametric_sketch",
    "inspect_sketch",
    "extrude_sketch",
    "revolve_sketch",
    "loft_sketches",
    "sweep_sketch",
    "boolean_bodies",
    "create_cylindrical_hole",
    "fillet_edges",
    "chamfer_edges",
    "shell_body",
    "linear_pattern_feature",
    "mirror_feature",
    "export_exchange",
    "import_exchange",
    "inspect_assembly",
    "add_component",
    "move_component",
    "add_assembly_constraint",
    "inspect_assembly_constraints",
    "extract_face_surface",
    "offset_surface",
    "sew_sheet_bodies",
    "trim_sheet_body",
    "create_sheet_metal_tab",
    "create_sheet_metal_flange",
    "create_sheet_metal_bend",
    "create_flat_pattern",
    "export_flat_pattern_dxf",
    "create_drawing_sheet",
    "create_projected_view",
    "create_drafting_note",
    "create_drawing_linear_dimension",
    "inspect_drawing_annotations",
    "inspect_machine_source_profile",
    "inspect_machine_kinematic_plan",
    "create_machine_build_workspace",
    "create_smart_machine_kit_workspace",
    "activate_machine_build_workspace",
    "import_machine_component_geometry",
    "build_machine_kinematics_from_profile",
    "validate_machine_kinematics",
    "inspect_machine_simulation_readiness",
    "bind_machine_tool_from_library",
    "start_machine_simulation_with_collision_stop",
    "save_work_part",
    "run_python",
}


async def run() -> None:
    environment = os.environ.copy()
    environment.setdefault("PYTHONUTF8", "1")
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "server.py")],
        env=environment,
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            response = await session.list_tools()
            names = {tool.name for tool in response.tools}
            missing = EXPECTED - names
            if missing:
                raise RuntimeError("missing MCP tools: %s" % sorted(missing))
            print("MCP stdio PASS: %s" % ", ".join(sorted(names)))


if __name__ == "__main__":
    asyncio.run(run())

#!/usr/bin/env python3
"""Build and validate a NEMA17 L bracket through the Siemens NX MCP server."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parent
PART_NAME = "nema17_l_bracket_4mm_v3.prt"
STEP_NAME = "nema17_l_bracket_4mm_v3.step"


def as_json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


async def checked_call(session, name, arguments=None):
    response = await session.call_tool(name, arguments or {})
    if response.isError:
        raise RuntimeError("MCP tool %s failed: %s" % (name, response.content))
    return as_json(response)


def triangle(name, points):
    geometry = []
    for index, start in enumerate(points):
        geometry.append(
            {
                "type": "line",
                "name": "%s_%s" % (name, index),
                "start": start,
                "end": points[(index + 1) % len(points)],
            }
        )
    return {
        "name": name,
        "plane": "YZ",
        "origin": [0.0, 0.0, 0.0],
        "geometry": geometry,
        "constraints": [],
        "dimensions": [],
    }


async def run():
    environment = os.environ.copy()
    environment.setdefault("PYTHONUTF8", "1")
    environment.setdefault("NX_MCP_ALLOW_EXECUTE", "1")
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "server.py")],
        env=environment,
    )
    results = {
        "brief": {
            "units": "millimeters",
            "envelope": [60.0, 60.0, 60.0],
            "plate_thickness": 4.0,
            "motor_pattern": "31 mm square; 4 x 3.4 mm",
            "center_clearance_diameter": 22.5,
            "base_mounting": "4 x 5.5 mm",
            "reinforcement": "2 x 4 mm triangular gussets",
        }
    }

    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            results["ping"] = await checked_call(session, "ping")
            results["create_part"] = await checked_call(
                session,
                "create_part",
                {"file_name": PART_NAME, "units": "millimeters"},
            )

            results["base_plate"] = await checked_call(
                session,
                "create_block",
                {
                    "length": 60.0,
                    "width": 60.0,
                    "height": 4.0,
                    "origin": [-30.0, 0.0, 0.0],
                },
            )
            results["upright_plate"] = await checked_call(
                session,
                "create_block",
                {
                    "length": 60.0,
                    "width": 4.0,
                    "height": 60.0,
                    "origin": [-30.0, 0.0, 0.0],
                },
            )
            results["unite_plates"] = await checked_call(
                session,
                "boolean_bodies",
                {
                    "target_body_index": 0,
                    "tool_body_index": 1,
                    "operation": "unite",
                    "feature_name": "UNITE_L_BRACKET",
                },
            )

            rib_points = [[4.0, 4.0], [30.0, 4.0], [4.0, 32.0]]
            for side, start_x in (("LEFT", -26.0), ("RIGHT", 22.0)):
                sketch_name = "%s_RIB_SKETCH" % side
                results["%s_rib_sketch" % side.lower()] = await checked_call(
                    session,
                    "create_parametric_sketch",
                    triangle(sketch_name, rib_points),
                )
                results["%s_rib_extrude" % side.lower()] = await checked_call(
                    session,
                    "extrude_sketch",
                    {
                        "sketch_id": sketch_name,
                        "distance": 4.0,
                        "start": start_x,
                        "direction": [1.0, 0.0, 0.0],
                        "feature_name": "%s_GUSSET_4MM" % side,
                    },
                )
                results["unite_%s_rib" % side.lower()] = await checked_call(
                    session,
                    "boolean_bodies",
                    {
                        "target_body_index": 0,
                        "tool_body_index": 1,
                        "operation": "unite",
                        "feature_name": "UNITE_%s_GUSSET" % side,
                    },
                )

            # Keep the base holes clear of the gussets at x=+/-22..26.
            for x in (-18.0, 18.0):
                for y in (18.0, 48.0):
                    key = "base_hole_%s_%s" % ("L" if x < 0 else "R", int(y))
                    results[key] = await checked_call(
                        session,
                        "create_cylindrical_hole",
                        {
                            "origin": [x, y, 5.0],
                            "direction": [0.0, 0.0, -1.0],
                            "diameter": 5.5,
                            "depth": 6.0,
                            "target_body_index": 0,
                            "feature_name": key.upper(),
                        },
                    )

            motor_center_z = 32.0
            for x in (-15.5, 15.5):
                for z in (motor_center_z - 15.5, motor_center_z + 15.5):
                    key = "motor_hole_%s_%s" % (
                        "L" if x < 0 else "R",
                        "LOW" if z < motor_center_z else "HIGH",
                    )
                    results[key] = await checked_call(
                        session,
                        "create_cylindrical_hole",
                        {
                            "origin": [x, 5.0, z],
                            "direction": [0.0, -1.0, 0.0],
                            "diameter": 3.4,
                            "depth": 6.0,
                            "target_body_index": 0,
                            "feature_name": key.upper(),
                        },
                    )

            results["motor_center_clearance"] = await checked_call(
                session,
                "create_cylindrical_hole",
                {
                    "origin": [0.0, 5.0, motor_center_z],
                    "direction": [0.0, -1.0, 0.0],
                    "diameter": 22.5,
                    "depth": 6.0,
                    "target_body_index": 0,
                    "feature_name": "MOTOR_CENTER_CLEARANCE_D22_5",
                },
            )

            results["rebuild"] = await checked_call(session, "rebuild_work_part")
            results["save"] = await checked_call(session, "save_work_part")
            results["step_export"] = await checked_call(
                session,
                "export_exchange",
                {
                    "file_name": STEP_NAME,
                    "format": "step",
                    "application_protocol": "ap242",
                    "overwrite": True,
                },
            )
            results["summary"] = await checked_call(
                session, "get_part_summary", {"max_features": 100}
            )
            results["geometry"] = await checked_call(
                session, "inspect_work_part_geometry", {"max_bodies": 10}
            )
            results["topology"] = await checked_call(
                session, "inspect_body_topology", {"body_index": 0}
            )

    output_path = ROOT / "workspace" / "nema17_l_bracket_4mm_v3_mcp_result.json"
    output_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("MCP_BUILD_RESULT=" + str(output_path))
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(run())

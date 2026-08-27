#!/usr/bin/env python3
"""Live stdio MCP validation for native sketch, dimensions, and extrusion."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent


def as_json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


async def checked_call(session, name, arguments):
    response = await session.call_tool(name, arguments)
    if response.isError:
        raise RuntimeError("MCP tool %s failed: %s" % (name, response.content))
    return as_json(response)


async def run() -> None:
    environment = os.environ.copy()
    environment.setdefault("PYTHONUTF8", "1")
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "server.py")],
        env=environment,
    )
    results = {}
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            results["ping"] = await checked_call(session, "ping", {})
            results["create_part"] = await checked_call(
                session,
                "create_part",
                {
                    "file_name": "nx_mcp_parametric_extrude_stage1_v2.prt",
                    "units": "millimeters",
                },
            )
            results["create_parametric_sketch"] = await checked_call(
                session,
                "create_parametric_sketch",
                {
                    "name": "PLATE_PROFILE",
                    "plane": "XY",
                    "origin": [0.0, 0.0, 0.0],
                    "geometry": [
                        {
                            "type": "rectangle",
                            "name": "plate",
                            "origin": [-20.0, -12.0],
                            "width": 40.0,
                            "height": 24.0,
                        },
                        {
                            "type": "circle",
                            "name": "bore",
                            "center": [0.0, 0.0],
                            "radius": 5.0,
                        },
                    ],
                    "constraints": [],
                    "dimensions": [
                        {
                            "type": "horizontal",
                            "name": "plate_width",
                            "geometry": "plate_0",
                            "value": 40.0,
                            "origin": [0.0, -17.0],
                        },
                        {
                            "type": "vertical",
                            "name": "plate_height",
                            "geometry": "plate_1",
                            "value": 24.0,
                            "origin": [25.0, 0.0],
                        },
                        {
                            "type": "diameter",
                            "name": "bore_diameter",
                            "geometry": "bore",
                            "value": 10.0,
                            "origin": [8.0, 8.0],
                        },
                    ],
                },
            )
            results["inspect_sketch"] = await checked_call(
                session, "inspect_sketch", {"sketch_id": "PLATE_PROFILE"}
            )
            results["extrude_sketch"] = await checked_call(
                session,
                "extrude_sketch",
                {
                    "sketch_id": "PLATE_PROFILE",
                    "distance": 8.0,
                    "direction": [0.0, 0.0, 1.0],
                    "start": 0.0,
                    "feature_name": "PLATE_EXTRUDE",
                },
            )
            results["save_work_part"] = await checked_call(
                session, "save_work_part", {}
            )
            results["summary"] = await checked_call(
                session, "get_part_summary", {"max_features": 50}
            )
            results["geometry"] = await checked_call(
                session, "inspect_work_part_geometry", {"max_bodies": 10}
            )
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(run())

#!/usr/bin/env python3
"""Live stdio MCP validation for sketch-driven revolve."""

from __future__ import annotations

import argparse
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


async def run(retry_current: bool = False, inspect_only: bool = False) -> None:
    environment = os.environ.copy()
    environment.setdefault("PYTHONUTF8", "1")
    parameters = StdioServerParameters(
        command=sys.executable, args=[str(ROOT / "server.py")], env=environment
    )
    results = {}
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            results["ping"] = await checked_call(session, "ping", {})
            if not retry_current:
                results["create_part"] = await checked_call(
                    session,
                    "create_part",
                    {
                        "file_name": "nx_mcp_revolve_stage2.prt",
                        "units": "millimeters",
                    },
                )
                results["create_parametric_sketch"] = await checked_call(
                    session,
                    "create_parametric_sketch",
                    {
                    "name": "RING_SECTION",
                    "plane": "XY",
                    "origin": [0.0, 0.0, 0.0],
                    "geometry": [
                        {
                            "type": "rectangle",
                            "name": "section",
                            "origin": [10.0, -5.0],
                            "width": 10.0,
                            "height": 10.0,
                        }
                    ],
                    "dimensions": [
                        {
                            "type": "horizontal",
                            "name": "radial_width",
                            "geometry": "section_0",
                            "value": 10.0,
                        },
                        {
                            "type": "vertical",
                            "name": "axial_width",
                            "geometry": "section_1",
                            "value": 10.0,
                        },
                    ],
                    },
                )
            results["inspect_sketch"] = await checked_call(
                session, "inspect_sketch", {"sketch_id": "RING_SECTION"}
            )
            if inspect_only:
                print(json.dumps(results, indent=2, ensure_ascii=False))
                return
            results["revolve_sketch"] = await checked_call(
                session,
                "revolve_sketch",
                {
                    "sketch_id": "RING_SECTION",
                    "axis_origin": [0.0, 0.0, 0.0],
                    "axis_direction": [0.0, 1.0, 0.0],
                    "start_angle_deg": 0.0,
                    "end_angle_deg": 360.0,
                    "feature_name": "RING_REVOLVE",
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retry-current", action="store_true")
    parser.add_argument("--inspect-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.retry_current, args.inspect_only))

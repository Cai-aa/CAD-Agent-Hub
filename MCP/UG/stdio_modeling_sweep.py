#!/usr/bin/env python3
"""Live stdio MCP validation for sketch-driven sweep."""

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
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


async def call(session, name, arguments):
    response = await session.call_tool(name, arguments)
    if response.isError:
        raise RuntimeError("MCP tool %s failed: %s" % (name, response.content))
    return as_json(response)


async def run() -> None:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    params = StdioServerParameters(
        command=sys.executable, args=[str(ROOT / "server.py")], env=env
    )
    results = {}
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            results["create_part"] = await call(
                session, "create_part",
                {"file_name": "nx_mcp_sweep_stage2.prt", "units": "millimeters"},
            )
            results["profile"] = await call(
                session, "create_parametric_sketch",
                {
                    "name": "SWEEP_PROFILE", "plane": "YZ", "origin": [0, 0, 0],
                    "geometry": [{"type": "circle", "name": "profile", "center": [0, 0], "radius": 5}],
                    "dimensions": [{"type": "diameter", "name": "diameter", "geometry": "profile", "value": 10}],
                },
            )
            results["guide"] = await call(
                session, "create_parametric_sketch",
                {
                    "name": "SWEEP_GUIDE", "plane": "XY", "origin": [0, 0, 0],
                    "geometry": [{"type": "line", "name": "path", "start": [0, 0], "end": [40, 0]}],
                    "constraints": [{"type": "horizontal", "geometry": "path"}],
                    "dimensions": [{"type": "length", "name": "length", "geometry": "path", "value": 40}],
                },
            )
            results["sweep"] = await call(
                session, "sweep_sketch",
                {"profile_sketch_id": "SWEEP_PROFILE", "guide_sketch_id": "SWEEP_GUIDE", "solid": True, "feature_name": "STRAIGHT_SWEEP"},
            )
            results["save"] = await call(session, "save_work_part", {})
            results["geometry"] = await call(
                session, "inspect_work_part_geometry", {"max_bodies": 10}
            )
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(run())

#!/usr/bin/env python3
"""Live stdio MCP validation for sketch-driven loft."""

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


async def checked_call(session, name, arguments):
    response = await session.call_tool(name, arguments)
    if response.isError:
        raise RuntimeError("MCP tool %s failed: %s" % (name, response.content))
    return as_json(response)


async def run() -> None:
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
            results["create_part"] = await checked_call(
                session,
                "create_part",
                {"file_name": "nx_mcp_loft_stage2.prt", "units": "millimeters"},
            )
            for name, z_value, radius in (
                ("LOFT_BASE", 0.0, 15.0),
                ("LOFT_TOP", 30.0, 8.0),
            ):
                results[name] = await checked_call(
                    session,
                    "create_parametric_sketch",
                    {
                        "name": name,
                        "plane": "XY",
                        "origin": [0.0, 0.0, z_value],
                        "geometry": [
                            {
                                "type": "circle",
                                "name": "profile",
                                "center": [0.0, 0.0],
                                "radius": radius,
                            }
                        ],
                        "dimensions": [
                            {
                                "type": "diameter",
                                "name": "diameter",
                                "geometry": "profile",
                                "value": radius * 2.0,
                            }
                        ],
                    },
                )
            results["loft"] = await checked_call(
                session,
                "loft_sketches",
                {
                    "sketch_ids": ["LOFT_BASE", "LOFT_TOP"],
                    "solid": True,
                    "feature_name": "TAPERED_LOFT",
                },
            )
            results["save"] = await checked_call(session, "save_work_part", {})
            results["summary"] = await checked_call(
                session, "get_part_summary", {"max_features": 50}
            )
            results["geometry"] = await checked_call(
                session, "inspect_work_part_geometry", {"max_bodies": 10}
            )
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(run())

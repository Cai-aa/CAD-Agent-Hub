#!/usr/bin/env python3
"""Live stdio validation for cylindrical hole and body boolean tools."""

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
            results["part"] = await call(
                session, "create_part",
                {"file_name": "nx_mcp_detail_stage3.prt", "units": "millimeters"},
            )
            results["base"] = await call(
                session, "create_block",
                {"length": 50, "width": 40, "height": 20, "origin": [0, 0, 0]},
            )
            results["hole"] = await call(
                session, "create_cylindrical_hole",
                {"origin": [25, 20, 20], "direction": [0, 0, -1], "diameter": 10, "depth": 20, "target_body_index": 0, "feature_name": "CENTER_HOLE"},
            )
            results["lug"] = await call(
                session, "create_block",
                {"length": 20, "width": 20, "height": 20, "origin": [40, 10, 0]},
            )
            results["unite"] = await call(
                session, "boolean_bodies",
                {"target_body_index": 0, "tool_body_index": 1, "operation": "unite", "feature_name": "UNITE_LUG"},
            )
            results["save"] = await call(session, "save_work_part", {})
            results["summary"] = await call(
                session, "get_part_summary", {"max_features": 50}
            )
            results["geometry"] = await call(
                session, "inspect_work_part_geometry", {"max_bodies": 10}
            )
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(run())

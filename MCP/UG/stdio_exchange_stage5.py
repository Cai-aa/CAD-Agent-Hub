#!/usr/bin/env python3
"""Live stdio round-trip validation for STEP and Parasolid exchange tools."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
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
    stamp = time.strftime("%Y%m%d_%H%M%S")
    step_name = "nx_mcp_stage5_roundtrip_%s.stp" % stamp
    parasolid_name = "nx_mcp_stage5_roundtrip_%s.x_t" % stamp
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    params = StdioServerParameters(
        command=sys.executable, args=[str(ROOT / "server.py")], env=env
    )
    results = {}
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            results["source"] = await call(session, "get_part_summary", {})
            results["step_export"] = await call(
                session,
                "export_exchange",
                {
                    "file_name": step_name,
                    "format": "step",
                    "application_protocol": "ap242",
                    "overwrite": False,
                },
            )
            results["parasolid_export"] = await call(
                session,
                "export_exchange",
                {
                    "file_name": parasolid_name,
                    "format": "parasolid",
                    "overwrite": False,
                },
            )

            results["step_part"] = await call(
                session,
                "create_part",
                {"file_name": "nx_mcp_stage5_step_import_%s.prt" % stamp},
            )
            results["step_import"] = await call(
                session,
                "import_exchange",
                {
                    "file_name": step_name,
                    "format": "step",
                    "application_protocol": "ap242",
                },
            )
            results["step_geometry"] = await call(
                session, "inspect_work_part_geometry", {"max_bodies": 10}
            )
            results["step_save"] = await call(session, "save_work_part", {})

            results["parasolid_part"] = await call(
                session,
                "create_part",
                {"file_name": "nx_mcp_stage5_parasolid_import_%s.prt" % stamp},
            )
            results["parasolid_import"] = await call(
                session,
                "import_exchange",
                {"file_name": parasolid_name, "format": "parasolid"},
            )
            results["parasolid_geometry"] = await call(
                session, "inspect_work_part_geometry", {"max_bodies": 10}
            )
            results["parasolid_save"] = await call(session, "save_work_part", {})
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(run())

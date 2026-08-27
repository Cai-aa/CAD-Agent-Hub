#!/usr/bin/env python3
"""Call the live NX bridge through the actual stdio MCP server."""

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


async def checked_call(session: ClientSession, name: str, arguments: dict):
    response = await session.call_tool(name, arguments)
    if response.isError:
        raise RuntimeError("MCP tool %s failed: %s" % (name, response.content))
    return as_json(response)


async def run(
    mutate: bool,
    create_part_name: str | None = None,
    create_gear_name: str | None = None,
    inspect_current: bool = False,
) -> None:
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
            if create_part_name:
                results["create_part"] = await checked_call(
                    session,
                    "create_part",
                    {"file_name": create_part_name, "units": "millimeters"},
                )
                results["summary"] = await checked_call(
                    session, "get_part_summary", {"max_features": 20}
                )
            if create_gear_name:
                results["create_part"] = await checked_call(
                    session,
                    "create_part",
                    {"file_name": create_gear_name, "units": "millimeters"},
                )
                results["create_involute_gear"] = await checked_call(
                    session,
                    "create_involute_gear",
                    {
                        "module": 2.0,
                        "teeth": 20,
                        "pressure_angle_deg": 20.0,
                        "face_width": 10.0,
                        "bore_diameter": 10.0,
                        "flank_segments": 10,
                        "arc_segments": 4,
                    },
                )
                results["save_work_part"] = await checked_call(
                    session, "save_work_part", {}
                )
                results["summary"] = await checked_call(
                    session, "get_part_summary", {"max_features": 20}
                )
                results["geometry"] = await checked_call(
                    session, "inspect_work_part_geometry", {"max_bodies": 10}
                )
            if inspect_current:
                results["summary"] = await checked_call(
                    session, "get_part_summary", {"max_features": 100}
                )
                results["geometry"] = await checked_call(
                    session, "inspect_work_part_geometry", {"max_bodies": 50}
                )
            if mutate:
                results["create_part"] = await checked_call(
                    session,
                    "create_part",
                    {"file_name": "nx_mcp_tool_e2e.prt", "units": "millimeters"},
                )
                results["create_block"] = await checked_call(
                    session,
                    "create_block",
                    {
                        "length": 64.0,
                        "width": 32.0,
                        "height": 16.0,
                        "origin": [1.0, 2.0, 3.0],
                    },
                )
                results["save_work_part"] = await checked_call(
                    session, "save_work_part", {}
                )
                results["summary"] = await checked_call(
                    session, "get_part_summary", {"max_features": 20}
                )
    print(json.dumps(results, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mutate",
        action="store_true",
        help="create, block, and save nx_mcp_tool_e2e.prt in NX_MCP_WORKSPACE",
    )
    parser.add_argument(
        "--create-part",
        metavar="FILE_NAME",
        help="create and display an empty millimeter part, then read its summary",
    )
    parser.add_argument(
        "--create-gear",
        metavar="FILE_NAME",
        help="create, model, save, and summarize a standard involute spur gear",
    )
    parser.add_argument(
        "--inspect-current",
        action="store_true",
        help="read the current part summary and body geometry through stdio MCP",
    )
    args = parser.parse_args()
    selected = sum(
        bool(value)
        for value in (
            args.mutate,
            args.create_part,
            args.create_gear,
            args.inspect_current,
        )
    )
    if selected > 1:
        parser.error(
            "--mutate, --create-part, --create-gear, and --inspect-current are mutually exclusive"
        )
    asyncio.run(
        run(args.mutate, args.create_part, args.create_gear, args.inspect_current)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

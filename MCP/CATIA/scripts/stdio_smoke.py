from __future__ import annotations

import asyncio
import argparse
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(use_wrapper: bool = False) -> None:
    project = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(project / "src"), environment.get("PYTHONPATH")) if part
    )
    command = sys.executable
    arguments = ["-m", "catia_mcp.server"]
    if use_wrapper:
        command = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        arguments = [
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(project / "scripts" / "run_server.ps1"),
        ]
    params = StdioServerParameters(
        command=command,
        args=arguments,
        cwd=str(project),
        env=environment,
    )
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(tool.name for tool in tools.tools)
            print(f"tool_count={len(names)}")
            print("\n".join(names))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--wrapper", action="store_true")
    options = parser.parse_args()
    asyncio.run(run(options.wrapper))

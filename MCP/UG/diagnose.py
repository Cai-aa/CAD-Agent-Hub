#!/usr/bin/env python3
"""Read-only readiness report for the repaired Siemens NX MCP."""

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from nx_bridge_client import BridgeError, NXBridgeClient

ROOT = Path(__file__).resolve().parent


def _codex_status(name: str) -> dict:
    codex = shutil.which("codex.cmd") or shutil.which("codex")
    if not codex:
        return {"ok": False, "detail": "codex CLI was not found on PATH"}
    if codex.lower().endswith((".cmd", ".bat")):
        command = [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/c",
            codex,
            "mcp",
            "get",
            name,
            "--json",
        ]
    else:
        command = [codex, "mcp", "get", name, "--json"]
    completed = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if completed.returncode != 0:
        return {
            "ok": False,
            "detail": (completed.stderr or completed.stdout).strip()
            or "%s is not registered" % name,
        }
    try:
        config = json.loads(completed.stdout)
    except json.JSONDecodeError:
        config = {"raw": completed.stdout.strip()}
    return {"ok": True, "name": name, "config": config}


def collect(name: str = "siemens-nx") -> dict:
    try:
        mcp_version = importlib.metadata.version("mcp")
        dependency = {"ok": True, "mcp_version": mcp_version}
    except importlib.metadata.PackageNotFoundError:
        dependency = {"ok": False, "detail": "mcp package is not installed"}

    ugii_base = os.environ.get("UGII_BASE_DIR", "")
    nx_root = Path(ugii_base) if ugii_base else None
    ugraf = nx_root / "NXBIN" / "ugraf.exe" if nx_root else None
    run_journal = nx_root / "NXBIN" / "run_journal.exe" if nx_root else None
    installation = {
        "ok": bool(ugraf and ugraf.is_file() and run_journal and run_journal.is_file()),
        "ugii_base_dir": ugii_base or None,
        "ugraf": str(ugraf) if ugraf else None,
        "ugraf_exists": bool(ugraf and ugraf.is_file()),
        "run_journal_exists": bool(run_journal and run_journal.is_file()),
    }

    entries = {
        "server": ROOT / "server.py",
        "remote_operations": ROOT / "nx_remote_ops.py",
        "remoting_server": ROOT / "dotnet_bridge" / "bin" / "NXMcPRemotingServer.dll",
        "remoting_client": ROOT / "dotnet_bridge" / "bin" / "NXRemoteClient.exe",
        "start_journal": ROOT / "start_bridge.py",
    }
    files = {
        "ok": all(path.is_file() for path in entries.values()),
        "entries": {key: str(path) for key, path in entries.items()},
    }

    client = NXBridgeClient(timeout=2.0)
    try:
        ping = client.request("ping", timeout=2.0)
        bridge = {
            "ok": True,
            "endpoint": client.endpoint,
            "work_part_open": bool(ping.get("work_part")),
            "ping": ping,
        }
    except BridgeError as exc:
        bridge = {"ok": False, "endpoint": client.endpoint, "detail": str(exc)}

    registration = _codex_status(name)
    ready = all(
        item["ok"] for item in (dependency, installation, files, registration, bridge)
    ) and bridge.get("work_part_open", False)
    return {
        "ready": ready,
        "python": sys.executable,
        "dependency": dependency,
        "nx_installation": installation,
        "files": files,
        "codex_registration": registration,
        "bridge": bridge,
    }


def main() -> int:
    report = collect()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

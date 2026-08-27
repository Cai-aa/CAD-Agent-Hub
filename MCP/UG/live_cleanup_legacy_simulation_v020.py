#!/usr/bin/env python3
"""Inspect and release the legacy V2 simulation panel after an interrupted run."""

from __future__ import annotations

import json
from pathlib import Path

from nx_bridge_client import NXBridgeClient


def invoke(client: NXBridgeClient, runtime: Path, method: str, params: dict) -> dict:
    request = {"id": "legacy-v2-cleanup", "method": method, "params": params}
    code = "\n".join(
        [
            "import json",
            f"_runtime = {str(runtime)!r}",
            f"_request = {request!r}",
            "_response = session.Execute(",
            "    _runtime, 'NXSimulationRuntime', 'Handle',",
            "    [json.dumps(_request)]",
            ")",
            "result = json.loads(str(_response))",
        ]
    )
    response = client.request("execute", {"code": code}, timeout=180)
    return response.get("result", response)


def main() -> None:
    root = Path(__file__).resolve().parent
    runtime = root / "dotnet_bridge" / "bin" / "NXMcPSimulationRuntimeV2.dll"
    if not runtime.is_file():
        print(json.dumps({"legacy_runtime_present": False}, indent=2))
        return
    client = NXBridgeClient(timeout=180)
    inspected = invoke(client, runtime, "inspect_active_machine_simulation", {})
    stopped = invoke(
        client,
        runtime,
        "stop_active_machine_simulation",
        {"release": True},
    )
    print(
        json.dumps(
            {"legacy_runtime_present": True, "inspected": inspected, "stopped": stopped},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

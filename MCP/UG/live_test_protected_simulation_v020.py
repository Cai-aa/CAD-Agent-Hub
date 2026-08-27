#!/usr/bin/env python3
"""Prepare, inspect, and release one protected NX toolpath simulation."""

from __future__ import annotations

import json
import argparse
import time

from nx_bridge_client import NXBridgeClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--play", action="store_true")
    args = parser.parse_args()
    client = NXBridgeClient(timeout=600)
    def runtime(method, parameters):
        return client.request(
            "simulation_runtime_proxy",
            {"runtime_method": method, "runtime_params": parameters},
            timeout=600,
        )

    started = runtime(
        "start_machine_simulation_with_collision_stop", {
            "operation_names": ["MCP_FACE_ACTUAL"],
            "required_axes": ["X", "Y", "Z", "B", "C"],
            "speed": 100 if args.play else 10,
            "play_immediately": args.play,
            "material_removal": True,
            "require_axis_limits": True,
            "require_tool_geometry": True,
            "require_shank_geometry": True,
            "require_holder_geometry": True,
            "require_workpiece_geometry": True,
            "require_fixture_geometry": True,
        },
    )
    if args.play:
        time.sleep(2.0)
    inspected = runtime("inspect_active_machine_simulation", {})
    stopped = runtime("stop_active_machine_simulation", {"release": True})
    result = {
        "prepared": started.get("simulation_prepared"),
        "runtime": started.get("runtime"),
        "options": started.get("options"),
        "inspected": inspected,
        "collision_stop_armed": inspected.get("options", {}).get("stop_on_collision"),
        "limit_stop_armed": inspected.get("options", {}).get("stop_on_limit_violation"),
        "stopped": stopped.get("stopped"),
        "released": stopped.get("released"),
        "production_nc_certified": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

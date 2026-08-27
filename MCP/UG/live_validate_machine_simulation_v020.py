#!/usr/bin/env python3
"""Live, path-redacted regression for NX MCP machine-simulation context v0.20."""

from __future__ import annotations

import json
import argparse

from nx_bridge_client import NXBridgeClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--configure-context", action="store_true")
    args = parser.parse_args()
    client = NXBridgeClient()
    part_summary = client.request("part_summary", {}, timeout=120)
    if args.configure_context:
        if int(part_summary.get("body_count", 0)) < 3:
            client.request(
                "create_block",
                {
                    "length": 100.0,
                    "width": 80.0,
                    "height": 10.0,
                    "origin": [-50.0, -40.0, -14.0],
                },
                timeout=180,
            )
        for workpiece_name in ("WORKPIECE", "MCP_WORKPIECE"):
            client.request(
                "define_cam_workpiece",
                {
                    "workpiece_name": workpiece_name,
                    "body_indices": [0],
                    "blank_body_indices": [1],
                    "fixture_body_indices": [2],
                },
                timeout=180,
            )
        preliminary = client.request(
            "inspect_machine_simulation_readiness",
            {
                "required_axes": [],
                "require_axis_limits": False,
                "require_holder_geometry": False,
                "require_fixture_geometry": False,
            },
            timeout=180,
        )
        for tool in preliminary.get("simulation_context", {}).get("tools", []):
            client.request(
                "create_cam_mill_tool",
                {
                    "name": tool["name"],
                    "diameter": tool["diameter"],
                    "flute_length": tool["flute_length"],
                    "overall_length": tool["overall_length"],
                    "flute_count": tool["flute_count"],
                    "tool_number": tool["tool_number"],
                    "length_offset_register": tool["length_offset_register"],
                    "holder_sections": [
                        {
                            "lower_diameter": 20.0,
                            "upper_diameter": 32.0,
                            "length": 20.0,
                            "corner_radius": 0.0,
                        },
                        {
                            "lower_diameter": 32.0,
                            "upper_diameter": 40.0,
                            "length": 35.0,
                            "corner_radius": 0.0,
                        },
                    ],
                },
                timeout=180,
            )
        client.request("save_work_part", {}, timeout=180)
        part_summary = client.request("part_summary", {}, timeout=120)
    bodies = [client.request("body_geometry", {}, timeout=120)]
    operations = client.request("inspect_cam_operations", {}, timeout=120)
    setup_tree = client.request("inspect_cam_setup", {"max_depth": 6}, timeout=120)
    names = [
        item["name"]
        for item in operations.get("operations", [])
        if item.get("path_exists", False)
    ]
    readiness = client.request(
        "inspect_machine_simulation_readiness",
        {
            "operation_names": names or None,
            "required_axes": ["X", "Y", "Z", "B", "C"],
            "require_axis_limits": True,
            "require_tool_geometry": True,
            "require_shank_geometry": True,
            "require_holder_geometry": True,
            "require_workpiece_geometry": True,
            "require_fixture_geometry": True,
        },
        timeout=180,
    )
    result = {
        "part": readiness.get("part"),
        "operation_names": names,
        "bodies": bodies,
        "machine_simulation_ready": readiness.get("machine_simulation_ready"),
        "blockers": readiness.get("blockers"),
        "warnings": readiness.get("warnings"),
        "requirements": readiness.get("requirements"),
        "axes": readiness.get("machine", {}).get("kinematics", {}).get("axes", []),
        "tools": readiness.get("simulation_context", {}).get("tools", []),
        "workpieces": readiness.get("simulation_context", {}).get("workpieces", []),
        "paths_redacted": True,
        "geometry_tree": setup_tree.get("roots", {}).get("geometry"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

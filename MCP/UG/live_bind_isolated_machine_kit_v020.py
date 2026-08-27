#!/usr/bin/env python3
"""Bind the generated MTK to the CAM sandbox through a workspace shadow library."""

from __future__ import annotations

import json

from nx_bridge_client import NXBridgeClient


def main() -> None:
    client = NXBridgeClient(timeout=1200)
    params = {
        "machine_kit_file_name": "mikron_mill_e500u_tnc640.mtk",
        "machine_libref": "mikron_mill_e500u_tnc640",
        "source_profile": "mikron_mill_e_500u_tnc640",
        "program_name": "MCP_PROGRAM",
        "operation_names": [
            "MCP_FACE_ACTUAL",
            "MCP_FACE_STAGE2",
            "MCP_CAVITY_STAGE2",
        ],
        "required_axes": ["X", "Y", "Z", "B", "C"],
        "evaluate_static_collisions": True,
        "dry_run": False,
        "confirmation": "BIND_ISOLATED_MACHINE_KIT_TO_CAM",
    }
    result = client.request(
        "bind_isolated_machine_kit_to_cam", params, timeout=1200
    )
    public = {
        "ok": result.get("ok"),
        "changed": result.get("changed"),
        "machine_libref": result.get("machine_libref"),
        "import_readback_passed": result.get("import_readback_passed"),
        "static_collision_passed": result.get("static_collision_passed"),
        "global_machine_library_unchanged": result.get(
            "global_machine_library_unchanged"
        ),
        "shadow_import_kept": result.get("shadow_import_kept"),
        "binding_readiness": result.get("binding", {}).get("readiness"),
        "paths_redacted": True,
    }
    print(json.dumps(public, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

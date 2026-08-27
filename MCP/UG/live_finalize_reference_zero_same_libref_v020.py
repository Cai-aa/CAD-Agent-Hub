#!/usr/bin/env python3
"""Finalize v17 through the already classified machine libref in a shadow library."""

from __future__ import annotations

import json
from pathlib import Path

from nx_bridge_client import NXBridgeClient
from live_rebuild_reference_zero_machine_v020 import OPERATIONS, PROFILE, WORKSPACE_FILE


KIT_FILE = "mikron_mill_e500u_tnc640.mtk"
REFERENCE_BACKUP = "mikron_mill_e500u_tnc640_pre_refzero.mtk"
MACHINE_LIBREF = "mikron_mill_e500u_tnc640"
GRAPHICS_FILE = "mikron_mill_e500u_tnc640_refzero_v17.prt"


def main() -> None:
    client = NXBridgeClient(timeout=1200)
    manifest_path = (
        Path(__file__).resolve().parent
        / "workspace"
        / "machine_builds"
        / f"{WORKSPACE_FILE}.nxmcp.json"
    )
    recovery_token = json.loads(manifest_path.read_text(encoding="utf-8"))[
        "recovery_token"
    ]
    ping = client.request("ping", {}, timeout=60)
    if ping.get("work_part") != Path(WORKSPACE_FILE).stem:
        client.request(
            "activate_machine_build_workspace",
            {
                "workspace_file_name": WORKSPACE_FILE,
                "recovery_token": recovery_token,
                "preserve_current": True,
                "dry_run": False,
                "confirmation": "ACTIVATE_MACHINE_BUILD_WORKSPACE",
            },
            timeout=600,
        )
    validated = client.request(
        "validate_machine_kinematics",
        {
            "source_profile": PROFILE,
            "workspace_file_name": WORKSPACE_FILE,
            "require_geometry": True,
        },
        timeout=600,
    )
    exported = client.request(
        "export_machine_kit_from_reference",
        {
            "source_profile": PROFILE,
            "workspace_file_name": WORKSPACE_FILE,
            "output_file_name": KIT_FILE,
            "reference_container_file_name": REFERENCE_BACKUP,
            "graphics_file_name": GRAPHICS_FILE,
            "overwrite": True,
            "dry_run": False,
            "confirmation": "EXPORT_MACHINE_KIT",
        },
        timeout=1200,
    )
    client.request("save_work_part", {}, timeout=300)
    restored = client.request(
        "restore_machine_build_recovery_part",
        {
            "workspace_file_name": WORKSPACE_FILE,
            "recovery_token": recovery_token,
            "dry_run": False,
            "confirmation": "RESTORE_MACHINE_BUILD_RECOVERY_PART",
        },
        timeout=600,
    )
    binding = client.request(
        "bind_isolated_machine_kit_to_cam",
        {
            "machine_kit_file_name": KIT_FILE,
            "machine_libref": MACHINE_LIBREF,
            "source_profile": PROFILE,
            "program_name": "MCP_PROGRAM",
            "operation_names": OPERATIONS,
            "required_axes": ["X", "Y", "Z", "B", "C"],
            "evaluate_static_collisions": True,
            "replace_existing": True,
            "reload_existing": True,
            "replace_confirmation": "REPLACE_EXISTING_MACHINE_TOOL",
            "dry_run": False,
            "confirmation": "BIND_ISOLATED_MACHINE_KIT_TO_CAM",
        },
        timeout=1200,
    )
    readiness = client.request(
        "inspect_machine_simulation_readiness",
        {
            "operation_names": OPERATIONS,
            "required_axes": ["X", "Y", "Z", "B", "C"],
            "require_axis_limits": True,
            "require_tool_geometry": True,
            "require_shank_geometry": True,
            "require_holder_geometry": True,
            "require_workpiece_geometry": True,
            "require_fixture_geometry": True,
        },
        timeout=600,
    )
    saved_cam = client.request("save_work_part", {}, timeout=300)
    print(
        json.dumps(
            {
                "ok": all(
                    (
                        validated.get("structural_validation_passed"),
                        exported.get("complete_archive_verified"),
                        binding.get("import_readback_passed"),
                        binding.get("static_collision_passed") is not False,
                        restored.get("changed"),
                        binding.get("ok"),
                        readiness.get("machine_simulation_ready"),
                    )
                ),
                "machine_kit_file_name": KIT_FILE,
                "graphics_file_name": GRAPHICS_FILE,
                "rollback_container_file_name": REFERENCE_BACKUP,
                "structural_validation_passed": validated.get(
                    "structural_validation_passed"
                ),
                "complete_archive_verified": exported.get(
                    "complete_archive_verified"
                ),
                "verified_reference_container_reused": exported.get(
                    "reference_container_reused"
                ),
                "import_readback_passed": binding.get("import_readback_passed"),
                "static_collision_passed": binding.get("static_collision_passed"),
                "global_machine_library_unchanged": binding.get(
                    "global_machine_library_unchanged"
                ),
                "recovery_part_restored": restored.get("changed"),
                "binding_changed": binding.get("changed"),
                "machine_libref": readiness.get("machine", {}).get("libref"),
                "machine_simulation_ready": readiness.get(
                    "machine_simulation_ready"
                ),
                "cam_part_saved": saved_cam.get("saved"),
                "readiness_blockers": readiness.get("blockers"),
                "readiness_warnings": readiness.get("warnings"),
                "paths_redacted": True,
                "production_certified": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

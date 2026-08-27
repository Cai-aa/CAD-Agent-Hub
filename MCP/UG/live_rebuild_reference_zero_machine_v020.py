#!/usr/bin/env python3
"""Rebuild, read back, and bind the reference-zero-corrected isolated machine kit."""

from __future__ import annotations

import json

from nx_bridge_client import NXBridgeClient


PROFILE = "mikron_mill_e_500u_tnc640"
WORKSPACE_FILE = "mikron_e500u_smk_build_v17.prt"
KIT_FILE = "mikron_mill_e500u_tnc640_refzero.mtk"
MACHINE_LIBREF = "mikron_mill_e500u_tnc640_refzero"
OPERATIONS = ["MCP_FACE_ACTUAL", "MCP_FACE_STAGE2", "MCP_CAVITY_STAGE2"]


def main() -> None:
    client = NXBridgeClient(timeout=1200)
    created = client.request(
        "create_smart_machine_kit_workspace",
        {
            "source_profile": PROFILE,
            "workspace_file_name": WORKSPACE_FILE,
            "dry_run": False,
            "confirmation": "CREATE_SMART_MACHINE_KIT_WORKSPACE",
        },
        timeout=900,
    )
    recovery_token = created["recovery_token"]
    restored = None
    try:
        imported = client.request(
            "import_machine_component_geometry",
            {
                "source_profile": PROFILE,
                "workspace_file_name": WORKSPACE_FILE,
                "dry_run": False,
                "confirmation": "IMPORT_MACHINE_COMPONENT_GEOMETRY",
            },
            timeout=1200,
        )
        built = client.request(
            "build_machine_kinematics_from_profile",
            {
                "source_profile": PROFILE,
                "workspace_file_name": WORKSPACE_FILE,
                "channel_name": "TNC_640",
                "dry_run": False,
                "confirmation": "BUILD_MACHINE_KINEMATICS",
            },
            timeout=1200,
        )
        client.request("save_work_part", {}, timeout=300)
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
                "reference_container_file_name": "mikron_mill_e500u_tnc640.mtk",
                "overwrite": False,
                "dry_run": False,
                "confirmation": "EXPORT_MACHINE_KIT",
            },
            timeout=1200,
        )
        readback = client.request(
            "import_machine_kit_readback",
            {
                "machine_kit_file_name": KIT_FILE,
                "source_profile": PROFILE,
                "dry_run": False,
                "keep_imported": False,
                "evaluate_static_collisions": True,
                "confirmation": "IMPORT_MACHINE_KIT_ISOLATED",
                "static_collision_confirmation": "EVALUATE_STATIC_MACHINE_COLLISIONS",
            },
            timeout=1200,
        )
    finally:
        try:
            client.request("save_work_part", {}, timeout=300)
        except Exception:
            pass
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
    public = {
        "ok": all(
            (
                created.get("ok"),
                imported.get("ok"),
                built.get("ok"),
                validated.get("structural_validation_passed"),
                exported.get("complete_archive_verified"),
                readback.get("readback_passed"),
                readback.get("static_collision_passed") is not False,
                restored and restored.get("changed"),
                binding.get("ok"),
                readiness.get("machine_simulation_ready"),
            )
        ),
        "workspace_file_name": WORKSPACE_FILE,
        "machine_kit_file_name": KIT_FILE,
        "junction_machine_zero": built.get("build_method", {})
        .get("junction_retarget", {})
        .get("machine_zero_origin"),
        "machine_reference_consistent": built.get("build_method", {})
        .get("junction_retarget", {})
        .get("machine_reference_consistent"),
        "component_geometry_count": imported.get("imported_geometry_count"),
        "structural_validation_passed": validated.get(
            "structural_validation_passed"
        ),
        "complete_archive_verified": exported.get("complete_archive_verified"),
        "import_readback_passed": readback.get("readback_passed"),
        "static_collision_passed": readback.get("static_collision_passed"),
        "global_machine_library_unchanged": readback.get(
            "global_machine_database_unchanged"
        ),
        "recovery_part_restored": bool(restored and restored.get("changed")),
        "binding_changed": binding.get("changed"),
        "machine_simulation_ready": readiness.get("machine_simulation_ready"),
        "readiness_blockers": readiness.get("blockers"),
        "readiness_warnings": readiness.get("warnings"),
        "paths_redacted": True,
        "production_certified": False,
    }
    print(json.dumps(public, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

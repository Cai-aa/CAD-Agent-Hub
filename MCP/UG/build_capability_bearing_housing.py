#!/usr/bin/env python3
"""Build and validate a complex bearing-housing capability demonstrator in live NX."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from nx_bridge_client import NXBridgeClient


ROOT = Path(__file__).resolve().parent


def call(client: NXBridgeClient, results: dict, key: str, method: str, params=None):
    value = client.request(method, params or {}, timeout=300.0)
    results[key] = value
    print("PASS %-30s %s" % (key, value.get("name") or value.get("feature_name") or ""))
    return value


def triangle(name: str, points: list[list[float]]) -> dict:
    geometry = []
    for index, start in enumerate(points):
        geometry.append(
            {
                "type": "line",
                "name": "%s_%s" % (name, index),
                "start": start,
                "end": points[(index + 1) % len(points)],
            }
        )
    return {"name": name, "plane": "XZ", "origin": [0.0, 0.0, 0.0], "geometry": geometry}


def build(file_name: str) -> dict:
    client = NXBridgeClient()
    results: dict = {"brief": {
        "part": "MCP heavy-duty two-bolt bearing housing demonstrator",
        "units": "mm",
        "reference_envelope": {"length": 184.0, "width": 49.0, "shaft_center_height": 49.2},
        "design_values": {"base_thickness": 19.0, "base_top_z": 18.0, "housing_outer_diameter": 100.0, "bearing_bore": 62.0, "mount_hole_diameter": 17.0, "mount_hole_spacing": 137.0},
        "note": "Capability demonstrator, not a manufacturer-certified production model.",
    }}

    call(client, results, "ping", "ping")
    part = call(client, results, "create_part", "create_part", {"file_name": file_name, "units": "millimeters"})

    call(client, results, "base", "create_block", {
        "length": 184.0, "width": 49.0, "height": 19.0,
        "origin": [-92.0, -24.5, -1.0],
    })

    call(client, results, "ring_sketch", "create_parametric_sketch", {
        "name": "BEARING_RING_SECTION", "plane": "XY", "origin": [0.0, 0.0, 49.2],
        "geometry": [{"type": "rectangle", "name": "ring", "origin": [31.0, -24.5], "width": 19.0, "height": 49.0}],
        "dimensions": [
            {"type": "horizontal", "name": "radial_wall", "geometry": "ring_0", "value": 19.0},
            {"type": "vertical", "name": "housing_width", "geometry": "ring_1", "value": 49.0},
        ],
    })
    ring = call(client, results, "ring_revolve", "revolve_sketch", {
        "sketch_id": "BEARING_RING_SECTION", "axis_origin": [0.0, 0.0, 49.2],
        "axis_direction": [0.0, 1.0, 0.0], "feature_name": "BEARING_RING_REVOLVE",
    })
    call(client, results, "unite_ring", "boolean_bodies", {
        "target_body_index": 0, "tool_body_index": 1, "operation": "unite", "feature_name": "UNITE_RING_TO_BASE",
    })

    left_spec = triangle("LEFT_RIB_SKETCH", [[-66.0, 18.0], [-32.0, 18.0], [-32.0, 48.0]])
    call(client, results, "left_rib_sketch", "create_parametric_sketch", left_spec)
    left_rib = call(client, results, "left_rib_extrude", "extrude_sketch", {
        "sketch_id": "LEFT_RIB_SKETCH", "distance": 16.0, "start": -8.0,
        "direction": [0.0, 1.0, 0.0], "feature_name": "LEFT_GUSSET",
    })
    mirrored = False
    try:
        mirror = call(client, results, "mirror_rib", "mirror_feature", {
            "feature_id": left_rib["journal_id"], "plane_origin": [0.0, 0.0, 0.0],
            "plane_normal": [1.0, 0.0, 0.0], "feature_name": "RIGHT_GUSSET_MIRROR",
        })
        mirrored = bool(mirror.get("ok"))
    except Exception as exc:
        results["mirror_rib"] = {"ok": False, "error": str(exc), "fallback": "explicit right-rib sketch"}
        right_spec = triangle("RIGHT_RIB_SKETCH", [[32.0, 18.0], [66.0, 18.0], [32.0, 48.0]])
        call(client, results, "right_rib_sketch", "create_parametric_sketch", right_spec)
        call(client, results, "right_rib_extrude", "extrude_sketch", {
            "sketch_id": "RIGHT_RIB_SKETCH", "distance": 16.0, "start": -8.0,
            "direction": [0.0, 1.0, 0.0], "feature_name": "RIGHT_GUSSET",
        })
    results["mirror_rib_used"] = mirrored

    geometry = client.request("body_geometry", {"max_bodies": 20})
    results["pre_rib_unite_geometry"] = geometry
    while geometry["body_count"] > 1:
        call(client, results, "unite_rib_%s" % geometry["body_count"], "boolean_bodies", {
            "target_body_index": 0, "tool_body_index": 1, "operation": "unite",
            "feature_name": "UNITE_GUSSET_%s" % geometry["body_count"],
        })
        geometry = client.request("body_geometry", {"max_bodies": 20})

    left_hole = call(client, results, "left_mount_hole", "create_cylindrical_hole", {
        "origin": [-68.5, 0.0, 18.0], "direction": [0.0, 0.0, -1.0],
        "diameter": 17.0, "depth": 19.0, "feature_name": "MOUNT_HOLE_LEFT",
    })
    call(client, results, "mount_hole_pattern", "linear_pattern_feature", {
        "feature_id": left_hole["journal_id"], "count": 2, "spacing": 137.0,
        "direction": [1.0, 0.0, 0.0], "feature_name": "MOUNT_HOLE_PAIR",
    })

    call(client, results, "grease_boss", "create_block", {
        "length": 16.0, "width": 16.0, "height": 10.0, "origin": [-8.0, -8.0, 91.0],
    })
    boss_edges = []
    for index, point in enumerate(([-8.0, -8.0, 96.0], [8.0, -8.0, 96.0], [8.0, 8.0, 96.0], [-8.0, 8.0, 96.0])):
        resolved = call(client, results, "boss_edge_%s" % index, "resolve_topology", {
            "kind": "edge", "body_index": 1,
            "selector": {"direction": [0.0, 0.0, 1.0], "length": 10.0, "near_point": point, "max_distance": 0.2},
        })
        boss_edges.append(int(resolved["selected"]["index"]))
    call(client, results, "boss_fillet", "fillet_edges", {
        "body_index": 1, "edge_indices": boss_edges, "radius": 2.5, "feature_name": "GREASE_BOSS_FILLET",
    })
    call(client, results, "unite_boss", "boolean_bodies", {
        "target_body_index": 0, "tool_body_index": 1, "operation": "unite", "feature_name": "UNITE_GREASE_BOSS",
    })
    call(client, results, "grease_port", "create_cylindrical_hole", {
        "origin": [0.0, 0.0, 101.0], "direction": [0.0, 0.0, -1.0],
        "diameter": 6.0, "depth": 22.0, "feature_name": "GREASE_PORT",
    })

    topology = call(client, results, "final_topology", "body_topology", {"body_index": 0})
    left_edge = call(client, results, "drawing_left_edge", "resolve_topology", {
        "kind": "edge", "body_index": 0,
        "selector": {"direction": [0.0, 0.0, 1.0], "length": 19.0, "near_point": [-92.0, -24.5, 8.5], "max_distance": 0.2},
    })
    right_edge = call(client, results, "drawing_right_edge", "resolve_topology", {
        "kind": "edge", "body_index": 0,
        "selector": {"direction": [0.0, 0.0, 1.0], "length": 19.0, "near_point": [92.0, -24.5, 8.5], "max_distance": 0.2},
    })

    sheet = call(client, results, "drawing_sheet", "create_drawing_sheet", {
        "name": "CAPABILITY_DEMO", "size": "A3", "scale_numerator": 1.0,
        "scale_denominator": 1.0, "projection": "first", "create_base_view": True,
        "model_view": "Front", "view_position": [210.0, 145.0, 0.0],
    })
    call(client, results, "top_projected_view", "create_projected_view", {
        "parent_view_id": sheet["base_view_journal_id"],
        "view_position": [210.0, 235.0, 0.0], "view_name": "TOP_PROJECTED",
    })
    call(client, results, "drawing_note", "create_drafting_note", {
        "lines": ["NX MCP CAPABILITY DEMONSTRATOR", "HEAVY-DUTY TWO-BOLT BEARING HOUSING", "REFERENCE DIMENSIONS - NOT FOR PRODUCTION"],
        "position": [20.0, 270.0, 0.0], "note_name": "CAPABILITY_NOTE",
    })
    call(client, results, "overall_length_dimension", "create_drawing_linear_dimension", {
        "first_edge_selector": {"stable_id": left_edge["selected"]["stable_id"], **left_edge["selected"]["stable_ref"]},
        "second_edge_selector": {"stable_id": right_edge["selected"]["stable_id"], **right_edge["selected"]["stable_ref"]},
        "position": [210.0, 55.0, 0.0], "measurement": "horizontal",
        "view_id": sheet["base_view_journal_id"], "body_index": 0,
        "dimension_name": "OVERALL_LENGTH_184",
    })
    call(client, results, "annotations", "inspect_drawing_annotations")
    call(client, results, "save", "save_work_part")

    stem = Path(part["full_path"]).stem
    call(client, results, "step", "export_exchange", {
        "file_name": stem + ".step", "format": "step", "application_protocol": "ap242", "overwrite": True,
    })
    call(client, results, "parasolid", "export_exchange", {
        "file_name": stem + ".x_t", "format": "parasolid", "overwrite": True,
    })
    call(client, results, "summary", "part_summary", {"max_features": 200})
    call(client, results, "geometry", "body_geometry", {"max_bodies": 20})
    results["topology_counts"] = {"faces": topology["face_count"], "edges": topology["edge_count"]}
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-name")
    args = parser.parse_args()
    file_name = args.file_name or "nx_mcp_capability_bearing_housing_%s.prt" % datetime.now().strftime("%Y%m%d_%H%M%S")
    results = build(file_name)
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

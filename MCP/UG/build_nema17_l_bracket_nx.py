#!/usr/bin/env python3
"""Create a native Siemens NX NEMA17 L-bracket and export STEP AP242."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import NXOpen  # type: ignore  # Available inside NX Journal runtime.
import nx_remote_ops as ops


PART_NAME = "nema17_l_bracket_4mm.prt"
STEP_NAME = "nema17_l_bracket_4mm.step"


def call(results, key, method, params=None):
    value = ops._OPS[method](params or {})
    results[key] = value
    print("PASS %-28s %s" % (key, value.get("name") or value.get("part") or ""))
    return value


def rename_feature(journal_id, name):
    work = NXOpen.Session.GetSession().Parts.Work
    ops._find_feature(work, journal_id).SetName(name)


def triangle(name, points):
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
    return {
        "name": name,
        "plane": "YZ",
        "origin": [0.0, 0.0, 0.0],
        "geometry": geometry,
    }


def main():
    results = {
        "brief": {
            "model": "NEMA17 stepper motor L mounting bracket",
            "units": "millimeters",
            "overall_envelope": [60.0, 60.0, 60.0],
            "plate_thickness": 4.0,
            "motor_pattern": "31 mm square, four 3.4 mm M3 clearance holes",
            "motor_center_clearance": 22.5,
            "base_mounting": "four 5.5 mm M5 clearance holes",
            "reinforcement": "two 4 mm triangular gussets",
        }
    }

    call(results, "create_part", "create_part", {"file_name": PART_NAME, "units": "millimeters"})

    base = call(
        results,
        "base_plate",
        "create_block",
        {"length": 60.0, "width": 60.0, "height": 4.0, "origin": [-30.0, 0.0, 0.0]},
    )
    rename_feature(base["feature"], "BASE_PLATE_60x60x4")

    upright = call(
        results,
        "upright_plate",
        "create_block",
        {"length": 60.0, "width": 4.0, "height": 60.0, "origin": [-30.0, 0.0, 0.0]},
    )
    rename_feature(upright["feature"], "UPRIGHT_PLATE_60x60x4")
    call(
        results,
        "unite_plates",
        "boolean_bodies",
        {
            "target_body_index": 0,
            "tool_body_index": 1,
            "operation": "unite",
            "feature_name": "UNITE_L_BRACKET",
        },
    )

    rib_profile = [[4.0, 4.0], [30.0, 4.0], [4.0, 32.0]]
    call(results, "left_rib_sketch", "create_parametric_sketch", triangle("LEFT_RIB_SKETCH", rib_profile))
    call(
        results,
        "left_rib_extrude",
        "extrude_sketch",
        {
            "sketch_id": "LEFT_RIB_SKETCH",
            "distance": 4.0,
            "start": -26.0,
            "direction": [1.0, 0.0, 0.0],
            "feature_name": "LEFT_GUSSET_4MM",
        },
    )
    call(
        results,
        "unite_left_rib",
        "boolean_bodies",
        {
            "target_body_index": 0,
            "tool_body_index": 1,
            "operation": "unite",
            "feature_name": "UNITE_LEFT_GUSSET",
        },
    )

    call(results, "right_rib_sketch", "create_parametric_sketch", triangle("RIGHT_RIB_SKETCH", rib_profile))
    call(
        results,
        "right_rib_extrude",
        "extrude_sketch",
        {
            "sketch_id": "RIGHT_RIB_SKETCH",
            "distance": 4.0,
            "start": 22.0,
            "direction": [1.0, 0.0, 0.0],
            "feature_name": "RIGHT_GUSSET_4MM",
        },
    )
    call(
        results,
        "unite_right_rib",
        "boolean_bodies",
        {
            "target_body_index": 0,
            "tool_body_index": 1,
            "operation": "unite",
            "feature_name": "UNITE_RIGHT_GUSSET",
        },
    )

    for x in (-22.0, 22.0):
        for y in (18.0, 48.0):
            key = "base_hole_%s_%s" % ("L" if x < 0 else "R", int(y))
            call(
                results,
                key,
                "create_cylindrical_hole",
                {
                    "origin": [x, y, 5.0],
                    "direction": [0.0, 0.0, -1.0],
                    "diameter": 5.5,
                    "depth": 6.0,
                    "feature_name": key.upper(),
                },
            )

    motor_center_z = 32.0
    for x in (-15.5, 15.5):
        for z in (motor_center_z - 15.5, motor_center_z + 15.5):
            key = "motor_hole_%s_%s" % ("L" if x < 0 else "R", "LOW" if z < motor_center_z else "HIGH")
            call(
                results,
                key,
                "create_cylindrical_hole",
                {
                    "origin": [x, 5.0, z],
                    "direction": [0.0, -1.0, 0.0],
                    "diameter": 3.4,
                    "depth": 6.0,
                    "feature_name": key.upper(),
                },
            )

    call(
        results,
        "motor_center_clearance",
        "create_cylindrical_hole",
        {
            "origin": [0.0, 5.0, motor_center_z],
            "direction": [0.0, -1.0, 0.0],
            "diameter": 22.5,
            "depth": 6.0,
            "feature_name": "MOTOR_CENTER_CLEARANCE_D22_5",
        },
    )

    call(results, "rebuild", "rebuild_work_part")
    call(results, "save", "save_work_part")
    call(
        results,
        "step_export",
        "export_exchange",
        {
            "file_name": STEP_NAME,
            "format": "step",
            "application_protocol": "ap242",
            "overwrite": True,
        },
    )
    call(results, "summary", "part_summary", {"max_features": 100})
    call(results, "geometry", "body_geometry", {"max_bodies": 10})

    print("NX_RESULT_JSON=" + json.dumps(results, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()

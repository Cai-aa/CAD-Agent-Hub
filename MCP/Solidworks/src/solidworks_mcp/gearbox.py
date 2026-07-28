from __future__ import annotations

import math
from typing import Any

from .contracts import ContractError, require_positive
from .involute_gear import validate_gear_spec


def _structural_gear_outline(
    spec: Any,
    center: tuple[float, float],
) -> list[list[float]]:
    """Return one efficient closed outline with four vertices per tooth."""
    cx, cy = center
    pitch = 2.0 * math.pi / spec.tooth_count
    root_half = pitch * 0.46
    tip_half = pitch * 0.24
    points: list[list[float]] = []
    for index in range(spec.tooth_count):
        angle = index * pitch
        for radius, local_angle in (
            (spec.root_radius_mm, angle - root_half),
            (spec.outer_radius_mm, angle - tip_half),
            (spec.outer_radius_mm, angle + tip_half),
            (spec.root_radius_mm, angle + root_half),
        ):
            points.append(
                [
                    cx + radius * math.cos(local_angle),
                    cy + radius * math.sin(local_angle),
                ]
            )
    return points


def _gear_features(
    *,
    prefix: str,
    center: tuple[float, float],
    plane: str,
    spec: Any,
) -> list[dict[str, Any]]:
    return [
        {
            "name": f"{prefix}Sketch",
            "kind": "sketch",
            "plane": plane,
            "entities": [
                {
                    "kind": "polyline",
                    "closed": True,
                    "points": _structural_gear_outline(spec, center),
                },
                {
                    "kind": "circle",
                    "center": list(center),
                    "radius_mm": spec.bore_diameter_mm / 2.0,
                },
            ],
        },
        {
            "name": f"{prefix}",
            "kind": "boss_extrude",
            "sketch": f"{prefix}Sketch",
            "depth_mm": spec.thickness_mm,
            "merge": False,
        },
    ]


def _keyway_rectangle(
    center_x: float,
    shaft_diameter: float,
    width: float,
    depth: float,
) -> dict[str, Any]:
    radius = shaft_diameter / 2.0
    return {
        "kind": "polyline",
        "closed": True,
        "points": [
            [center_x - width / 2.0, radius - depth],
            [center_x + width / 2.0, radius - depth],
            [center_x + width / 2.0, radius],
            [center_x - width / 2.0, radius],
        ],
    }


def build_two_stage_reducer_graph(
    *,
    module_mm: float = 2.0,
    pressure_angle_deg: float = 20.0,
    stage1_teeth: tuple[int, int] = (20, 40),
    stage2_teeth: tuple[int, int] = (20, 60),
    gear_thickness_mm: float = 10.0,
    axial_gap_mm: float = 8.0,
    bore_diameters_mm: tuple[float, float, float] = (10.0, 12.0, 14.0),
    radial_clearance_mm: float = 0.1,
    shaft_extension_mm: float = 5.0,
) -> dict[str, Any]:
    module_mm = require_positive(module_mm, "module_mm")
    gear_thickness_mm = require_positive(gear_thickness_mm, "gear_thickness_mm")
    axial_gap_mm = require_positive(axial_gap_mm, "axial_gap_mm")
    radial_clearance_mm = require_positive(radial_clearance_mm, "radial_clearance_mm")
    shaft_extension_mm = require_positive(shaft_extension_mm, "shaft_extension_mm")
    if len(stage1_teeth) != 2 or len(stage2_teeth) != 2:
        raise ContractError("each stage must contain a pinion and a driven gear")
    if len(bore_diameters_mm) != 3:
        raise ContractError("bore_diameters_mm must contain input, intermediate, output")

    z1, z2 = (int(value) for value in stage1_teeth)
    z3, z4 = (int(value) for value in stage2_teeth)
    bore1, bore2, bore3 = (
        require_positive(value, "bore_diameters_mm") for value in bore_diameters_mm
    )
    common = {
        "module_mm": module_mm,
        "pressure_angle_deg": pressure_angle_deg,
        "thickness_mm": gear_thickness_mm,
        "root_fillet_mm": min(0.45, module_mm * 0.225),
        "tip_chamfer_mm": min(0.25, module_mm * 0.125),
    }
    specs = [
        validate_gear_spec(tooth_count=z1, bore_diameter_mm=bore1, **common),
        validate_gear_spec(tooth_count=z2, bore_diameter_mm=bore2, **common),
        validate_gear_spec(tooth_count=z3, bore_diameter_mm=bore2, **common),
        validate_gear_spec(tooth_count=z4, bore_diameter_mm=bore3, **common),
    ]

    stage1_center_distance = module_mm * (z1 + z2) / 2.0
    stage2_center_distance = module_mm * (z3 + z4) / 2.0
    centers = [
        (0.0, 0.0),
        (stage1_center_distance, 0.0),
        (stage1_center_distance, 0.0),
        (stage1_center_distance + stage2_center_distance, 0.0),
    ]
    stage2_offset = gear_thickness_mm + axial_gap_mm
    shaft_length = stage2_offset + gear_thickness_mm + shaft_extension_mm
    shaft_diameters = [
        bore1 - 2.0 * radial_clearance_mm,
        bore2 - 2.0 * radial_clearance_mm,
        bore3 - 2.0 * radial_clearance_mm,
    ]
    if any(value <= 0.0 for value in shaft_diameters):
        raise ContractError("radial clearance leaves a non-positive shaft diameter")

    features: list[dict[str, Any]] = [
        {"name": "TwoStageReducer", "kind": "new_part", "title": "Two Stage Reducer Gearset"},
        {
            "name": "IntermediateAxisPlane",
            "kind": "reference_plane_offset",
            "base_plane": "Right Plane",
            # The stock Right Plane normal points toward negative sketch X on
            # the Chinese GB part template, so negate the requested model-space
            # X coordinate when creating an offset plane.
            "offset_mm": -stage1_center_distance,
        },
        {
            "name": "OutputAxisPlane",
            "kind": "reference_plane_offset",
            "base_plane": "Right Plane",
            "offset_mm": -(stage1_center_distance + stage2_center_distance),
        },
        {
            "name": "Stage2Plane",
            "kind": "reference_plane_offset",
            "base_plane": "Front Plane",
            "offset_mm": -stage2_offset,
        },
    ]
    features += _gear_features(
        prefix="Stage1InputGear",
        center=centers[0],
        plane="Front Plane",
        spec=specs[0],
    )
    features += _gear_features(
        prefix="Stage1DrivenGear",
        center=centers[1],
        plane="Front Plane",
        spec=specs[1],
    )
    features += _gear_features(
        prefix="Stage2Pinion",
        center=centers[2],
        plane="Stage2Plane",
        spec=specs[2],
    )
    features += _gear_features(
        prefix="Stage2OutputGear",
        center=centers[3],
        plane="Stage2Plane",
        spec=specs[3],
    )
    features += [
        {
            "name": "ReducerShaftSketch",
            "kind": "sketch",
            "plane": "Front Plane",
            "entities": [
                {
                    "kind": "circle",
                    "center": list(center),
                    "radius_mm": diameter / 2.0,
                }
                for center, diameter in zip(
                    (centers[0], centers[1], centers[3]), shaft_diameters
                )
            ],
        },
        {
            "name": "ReducerShafts",
            "kind": "boss_extrude",
            "sketch": "ReducerShaftSketch",
            "depth_mm": shaft_length,
            "merge": False,
        },
        {
            "name": "ReducerKeywaySketch",
            "kind": "sketch",
            "plane": "Front Plane",
            "entities": [
                _keyway_rectangle(centers[0][0], shaft_diameters[0], 3.0, 1.6),
                _keyway_rectangle(centers[1][0], shaft_diameters[1], 4.0, 2.0),
                _keyway_rectangle(centers[3][0], shaft_diameters[2], 5.0, 2.5),
            ],
        },
        {
            "name": "ReducerKeywayCut",
            "kind": "cut_extrude",
            "sketch": "ReducerKeywaySketch",
            "through_all": True,
        },
    ]
    return {
        "version": "1.0",
        "metadata": {
            "generator": "solidworks-agent-mcp",
            "part_type": "two_stage_parallel_shaft_reducer",
            "module_mm": module_mm,
            "pressure_angle_deg": pressure_angle_deg,
            "stage1_teeth": [z1, z2],
            "stage2_teeth": [z3, z4],
            "stage1_ratio": z2 / z1,
            "stage2_ratio": z4 / z3,
            "total_ratio": (z2 / z1) * (z4 / z3),
            "stage1_center_distance_mm": stage1_center_distance,
            "stage2_center_distance_mm": stage2_center_distance,
            "stage2_axial_offset_mm": stage2_offset,
            "shaft_diameters_mm": shaft_diameters,
            "body_count_expected": 7,
            "tooth_geometry": "structural trapezoidal outline, four vertices per tooth",
        },
        "features": features,
    }

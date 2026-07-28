from __future__ import annotations

import math
from typing import Any


def _slot_points(
    start_x: float,
    length: float,
    width: float,
    *,
    arc_segments: int = 8,
) -> list[list[float]]:
    radius = width / 2.0
    left_center = start_x + radius
    right_center = start_x + length - radius
    points: list[list[float]] = []
    for index in range(arc_segments + 1):
        angle = math.pi / 2.0 + math.pi * index / arc_segments
        points.append(
            [
                left_center + radius * math.cos(angle),
                radius * math.sin(angle),
            ]
        )
    for index in range(arc_segments + 1):
        angle = -math.pi / 2.0 + math.pi * index / arc_segments
        points.append(
            [
                right_center + radius * math.cos(angle),
                radius * math.sin(angle),
            ]
        )
    return points


def build_output_shaft_from_dwg_graph() -> dict[str, Any]:
    """Build the output shaft dimensioned by 输出轴零件图.DWG."""
    lengths = [46.0, 61.0, 8.0, 53.0, 44.0, 57.0, 64.0]
    diameters = [55.0, 60.0, 65.0, 60.0, 55.0, 50.0, 45.0]
    stations = [0.0]
    for length in lengths:
        stations.append(stations[-1] + length)
    radii = [diameter / 2.0 for diameter in diameters]

    # Closed half-section. The 5 mm diameter, 20 mm deep axial core hole
    # represents the M6x20 threaded-hole minor diameter from the drawing.
    profile_points = [
        [20.0, 0.0],
        [20.0, 2.5],
        [0.0, 2.5],
        [0.0, radii[0] - 2.0],
        [2.0, radii[0]],
        [stations[1], radii[0]],
        [stations[1], radii[1]],
        [stations[2], radii[1]],
        [stations[2], radii[2]],
        [stations[3], radii[2]],
        [stations[3], radii[3]],
        [stations[4], radii[3]],
        [stations[4], radii[4]],
        [stations[5], radii[4]],
        [stations[5], radii[5]],
        [stations[6], radii[5]],
        [stations[6], radii[6]],
        [stations[7] - 2.0, radii[6]],
        [stations[7], radii[6] - 2.0],
        [stations[7], 0.0],
    ]

    return {
        "version": "1.0",
        "metadata": {
            "generator": "solidworks-agent-mcp",
            "source_drawing": "输出轴零件图.DWG",
            "part_type": "two_stage_reducer_output_shaft",
            "units": "mm",
            "total_length_mm": stations[-1],
            "segment_lengths_mm": lengths,
            "segment_diameters_mm": diameters,
            "keyways": [
                {"width_mm": 18.0, "length_mm": 50.0, "depth_mm": 5.5, "start_mm": 52.0},
                {"width_mm": 14.0, "length_mm": 56.0, "depth_mm": 4.5, "start_mm": 273.0},
            ],
            "end_holes": [
                {"kind": "M6_thread_core", "diameter_mm": 5.0, "depth_mm": 20.0},
                {
                    "kind": "blind_drill",
                    "diameter_mm": 3.0,
                    "depth_mm": 12.0,
                    "radial_offset_mm": 12.0,
                },
            ],
            "unspecified_chamfer_mm": 2.0,
            "unspecified_fillet_mm": 1.2,
        },
        "features": [
            {
                "name": "OutputShaftPart",
                "kind": "new_part",
                "title": "Output Shaft from DWG",
            },
            {
                "name": "OutputShaftAxis",
                "kind": "reference_axis",
                "planes": ["Front Plane", "Top Plane"],
            },
            {
                "name": "OutputShaftProfile",
                "kind": "sketch",
                "plane": "Front Plane",
                "entities": [
                    {
                        "kind": "polyline",
                        "closed": True,
                        "points": profile_points,
                    }
                ],
            },
            {
                "name": "OutputShaftRevolve",
                "kind": "boss_revolve",
                "sketch": "OutputShaftProfile",
                "axis": "OutputShaftAxis",
                "angle_deg": 360.0,
                "merge": True,
            },
            {
                "name": "Keyway18Plane",
                "kind": "reference_plane_offset",
                "base_plane": "Front Plane",
                "offset_mm": 30.0,
            },
            {
                "name": "Keyway18Sketch",
                "kind": "sketch",
                "plane": "Keyway18Plane",
                "entities": [
                    {
                        "kind": "polyline",
                        "closed": True,
                        "points": _slot_points(52.0, 50.0, 18.0),
                    }
                ],
            },
            {
                "name": "Keyway18Cut",
                "kind": "cut_extrude",
                "sketch": "Keyway18Sketch",
                "depth_mm": 5.5,
                "reverse_direction": False,
            },
            {
                "name": "Keyway14Plane",
                "kind": "reference_plane_offset",
                "base_plane": "Front Plane",
                "offset_mm": 22.5,
            },
            {
                "name": "Keyway14Sketch",
                "kind": "sketch",
                "plane": "Keyway14Plane",
                "entities": [
                    {
                        "kind": "polyline",
                        "closed": True,
                        "points": _slot_points(273.0, 56.0, 14.0),
                    }
                ],
            },
            {
                "name": "Keyway14Cut",
                "kind": "cut_extrude",
                "sketch": "Keyway14Sketch",
                "depth_mm": 4.5,
                "reverse_direction": False,
            },
            {
                "name": "EndBlindHoleSketch",
                "kind": "sketch",
                "plane": "Right Plane",
                "entities": [
                    {
                        "kind": "circle",
                        "center": [12.0, 0.0],
                        "radius_mm": 1.5,
                    }
                ],
            },
            {
                "name": "EndBlindHoleDia3Depth12",
                "kind": "cut_extrude",
                "sketch": "EndBlindHoleSketch",
                "depth_mm": 12.0,
                "reverse_direction": True,
            },
        ],
    }

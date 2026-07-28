from __future__ import annotations

from typing import Any

from .contracts import require_positive
from .involute_gear import InvoluteGearSpec, sampled_involute_gear_entities


def build_sphere_graph(diameter_mm: float = 50.0) -> dict[str, Any]:
    """Build the canonical native SolidWorks sphere graph.

    The profile deliberately uses a construction centerline and two quarter
    arcs. This avoids the ambiguous 180-degree, diametrically opposed arc that
    some late-bound COM hosts interpret inconsistently.
    """
    diameter_mm = require_positive(diameter_mm, "diameter_mm")
    radius = diameter_mm / 2.0
    return {
        "version": "1.0",
        "metadata": {
            "primitive": "sphere",
            "diameter_mm": diameter_mm,
            "modeling_method": "native sketch-segment revolve",
        },
        "features": [
            {"name": "SpherePart", "kind": "new_part", "title": f"sphere_d{diameter_mm:g}_native"},
            {
                "name": "SphereProfileSketch",
                "kind": "sketch",
                "plane": "Front Plane",
                "entities": [
                    {
                        "kind": "line",
                        "start": [0.0, -radius],
                        "end": [0.0, radius],
                        "construction": True,
                    },
                    {
                        "kind": "arc",
                        "center": [0.0, 0.0],
                        "start": [0.0, radius],
                        "end": [radius, 0.0],
                        "direction": -1,
                    },
                    {
                        "kind": "arc",
                        "center": [0.0, 0.0],
                        "start": [radius, 0.0],
                        "end": [0.0, -radius],
                        "direction": -1,
                    },
                ],
            },
            {
                "name": "SphereRevolve",
                "kind": "boss_revolve",
                "sketch": "SphereProfileSketch",
                "axis_segment": "Line1",
                "angle_deg": 360.0,
                "merge": True,
            },
        ],
    }


def build_sphere_with_gear_graph(
    gear_spec: InvoluteGearSpec,
    *,
    sphere_diameter_mm: float = 50.0,
    gear_center_x_mm: float = 60.0,
    samples_per_flank: int = 8,
) -> dict[str, Any]:
    """Build one native multibody part containing a sphere and adjacent gear."""
    sphere_diameter_mm = require_positive(sphere_diameter_mm, "sphere_diameter_mm")
    sphere_radius = sphere_diameter_mm / 2.0
    gear_center = (float(gear_center_x_mm), 0.0)
    gap_mm = gear_center_x_mm - sphere_radius - gear_spec.outer_radius_mm
    if gap_mm <= 0:
        raise ValueError("gear_center_x_mm must leave positive clearance from the sphere")

    return {
        "version": "1.0",
        "metadata": {
            "primitive": "sphere_with_involute_gear",
            "sphere_diameter_mm": sphere_diameter_mm,
            "gear_spec": gear_spec.to_dict(),
            "gear_center_mm": list(gear_center),
            "surface_gap_mm": gap_mm,
            "involute_representation": f"analytic sampling, {samples_per_flank} points per flank",
            "body_count_expected": 2,
        },
        "features": [
            {"name": "SphereGearPart", "kind": "new_part", "title": "sphere_with_gear_native"},
            {
                "name": "SphereProfileSketch",
                "kind": "sketch",
                "plane": "Front Plane",
                "entities": [
                    {
                        "kind": "line",
                        "start": [0.0, -sphere_radius],
                        "end": [0.0, sphere_radius],
                        "construction": True,
                    },
                    {
                        "kind": "arc",
                        "center": [0.0, 0.0],
                        "start": [0.0, sphere_radius],
                        "end": [sphere_radius, 0.0],
                        "direction": -1,
                    },
                    {
                        "kind": "arc",
                        "center": [0.0, 0.0],
                        "start": [sphere_radius, 0.0],
                        "end": [0.0, -sphere_radius],
                        "direction": -1,
                    },
                ],
            },
            {
                "name": "SphereRevolve",
                "kind": "boss_revolve",
                "sketch": "SphereProfileSketch",
                "axis_segment": "Line1",
                "angle_deg": 360.0,
                "merge": True,
            },
            {
                "name": "AdjacentGearBlankSketch",
                "kind": "sketch",
                "plane": "Front Plane",
                "entities": [
                    {
                        "kind": "circle",
                        "center": list(gear_center),
                        "radius_mm": gear_spec.root_radius_mm,
                    }
                ],
            },
            {
                "name": "AdjacentGearBlank",
                "kind": "boss_extrude",
                "sketch": "AdjacentGearBlankSketch",
                "depth_mm": gear_spec.thickness_mm,
                "merge": False,
            },
            {
                "name": "AdjacentGearInvoluteTeethSketch",
                "kind": "sketch",
                "plane": "Front Plane",
                "entities": sampled_involute_gear_entities(
                    gear_spec,
                    center_mm=gear_center,
                    samples_per_flank=samples_per_flank,
                ),
            },
            {
                "name": "AdjacentGearTeeth",
                "kind": "boss_extrude",
                "sketch": "AdjacentGearInvoluteTeethSketch",
                "depth_mm": gear_spec.thickness_mm,
                "merge": True,
            },
            {
                "name": "AdjacentGearBoreSketch",
                "kind": "sketch",
                "plane": "Front Plane",
                "entities": [
                    {
                        "kind": "circle",
                        "center": list(gear_center),
                        "radius_mm": gear_spec.bore_diameter_mm / 2.0,
                    }
                ],
            },
            {
                "name": "AdjacentGearBoreCut",
                "kind": "cut_extrude",
                "sketch": "AdjacentGearBoreSketch",
                "through_all": True,
            },
        ],
    }

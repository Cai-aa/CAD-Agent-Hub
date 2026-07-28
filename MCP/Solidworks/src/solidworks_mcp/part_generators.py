from __future__ import annotations

import math
from typing import Any

from .contracts import ContractError, require_positive


SUPPORTED_PART_TYPES = ("block", "cylinder", "tube", "flange", "stepped_shaft")


def _positive(parameters: dict[str, Any], name: str, default: float | None = None) -> float:
    value = parameters.get(name, default)
    return require_positive(value, name)


def _new_part(title: str) -> dict[str, Any]:
    return {"name": "Part", "kind": "new_part", "title": title}


def _circle(name: str, radius_mm: float, center: tuple[float, float] = (0.0, 0.0)) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "sketch",
        "plane": "Front Plane",
        "entities": [{"kind": "circle", "center": list(center), "radius_mm": radius_mm}],
    }


def build_parametric_part_graph(part_type: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Build a compact native-feature graph for a common mechanical part."""
    if not isinstance(parameters, dict):
        raise ContractError("parameters must be an object")
    normalized_type = str(part_type).strip().lower()
    if normalized_type not in SUPPORTED_PART_TYPES:
        raise ContractError(f"part_type must be one of: {', '.join(SUPPORTED_PART_TYPES)}")

    if normalized_type == "block":
        length = _positive(parameters, "length_mm", 100.0)
        width = _positive(parameters, "width_mm", 60.0)
        height = _positive(parameters, "height_mm", 20.0)
        x, y = length / 2.0, width / 2.0
        features = [
            _new_part("Parametric Block"),
            {
                "name": "BlockSketch",
                "kind": "sketch",
                "plane": "Front Plane",
                "entities": [{
                    "kind": "polyline",
                    "closed": True,
                    "points": [[-x, -y], [x, -y], [x, y], [-x, y]],
                }],
            },
            {"name": "BlockBoss", "kind": "boss_extrude", "sketch": "BlockSketch", "depth_mm": height},
        ]
    elif normalized_type == "cylinder":
        diameter = _positive(parameters, "diameter_mm", 50.0)
        length = _positive(parameters, "length_mm", 100.0)
        features = [
            _new_part("Parametric Cylinder"),
            _circle("CylinderSketch", diameter / 2.0),
            {"name": "CylinderBoss", "kind": "boss_extrude", "sketch": "CylinderSketch", "depth_mm": length},
        ]
    elif normalized_type == "tube":
        outer = _positive(parameters, "outer_diameter_mm", 50.0)
        inner = _positive(parameters, "inner_diameter_mm", 40.0)
        length = _positive(parameters, "length_mm", 100.0)
        if inner >= outer:
            raise ContractError("inner_diameter_mm must be smaller than outer_diameter_mm")
        features = [
            _new_part("Parametric Tube"),
            {
                "name": "TubeSketch",
                "kind": "sketch",
                "plane": "Front Plane",
                "entities": [
                    {"kind": "circle", "center": [0.0, 0.0], "radius_mm": outer / 2.0},
                    {"kind": "circle", "center": [0.0, 0.0], "radius_mm": inner / 2.0},
                ],
            },
            {"name": "TubeBoss", "kind": "boss_extrude", "sketch": "TubeSketch", "depth_mm": length},
        ]
    elif normalized_type == "flange":
        outer = _positive(parameters, "outer_diameter_mm", 120.0)
        bore = _positive(parameters, "bore_diameter_mm", 40.0)
        thickness = _positive(parameters, "thickness_mm", 12.0)
        bolt_circle = _positive(parameters, "bolt_circle_diameter_mm", 90.0)
        hole = _positive(parameters, "bolt_hole_diameter_mm", 10.0)
        count_value = parameters.get("bolt_count", 6)
        if not isinstance(count_value, int) or isinstance(count_value, bool) or count_value < 2:
            raise ContractError("bolt_count must be an integer >= 2")
        if bore >= outer or bolt_circle + hole >= outer:
            raise ContractError("flange bore and bolt holes must remain inside outer_diameter_mm")
        holes = []
        for index in range(count_value):
            angle = 2.0 * math.pi * index / count_value
            holes.append({
                "kind": "circle",
                "center": [bolt_circle * 0.5 * math.cos(angle), bolt_circle * 0.5 * math.sin(angle)],
                "radius_mm": hole / 2.0,
            })
        features = [
            _new_part("Parametric Flange"),
            _circle("FlangeBlankSketch", outer / 2.0),
            {"name": "FlangeBlank", "kind": "boss_extrude", "sketch": "FlangeBlankSketch", "depth_mm": thickness},
            {
                "name": "FlangeHoleSketch",
                "kind": "sketch",
                "plane": "Front Plane",
                "entities": [
                    {"kind": "circle", "center": [0.0, 0.0], "radius_mm": bore / 2.0},
                    *holes,
                ],
            },
            {"name": "FlangeHoles", "kind": "cut_extrude", "sketch": "FlangeHoleSketch", "through_all": True},
        ]
    else:
        raw_steps = parameters.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raw_steps = [
                {"diameter_mm": 40.0, "length_mm": 50.0},
                {"diameter_mm": 30.0, "length_mm": 40.0},
                {"diameter_mm": 20.0, "length_mm": 30.0},
            ]
        steps: list[tuple[float, float]] = []
        for index, raw in enumerate(raw_steps):
            if not isinstance(raw, dict):
                raise ContractError(f"steps[{index}] must be an object")
            steps.append((
                require_positive(raw.get("diameter_mm"), f"steps[{index}].diameter_mm"),
                require_positive(raw.get("length_mm"), f"steps[{index}].length_mm"),
            ))
        points = [[0.0, 0.0]]
        x = 0.0
        for diameter, length in steps:
            radius = diameter / 2.0
            points.append([x, radius])
            x += length
            points.append([x, radius])
        points.extend([[x, 0.0]])
        features = [
            _new_part("Parametric Stepped Shaft"),
            {
                "name": "ShaftProfileSketch",
                "kind": "sketch",
                "plane": "Front Plane",
                "entities": [
                    {"kind": "line", "start": [0.0, 0.0], "end": [x, 0.0], "construction": True},
                    {"kind": "polyline", "closed": False, "points": points},
                ],
            },
            {
                "name": "ShaftRevolve",
                "kind": "boss_revolve",
                "sketch": "ShaftProfileSketch",
                "axis_segment": "Line1",
                "angle_deg": 360.0,
            },
        ]

    return {
        "version": "1.0",
        "metadata": {"generator": "solidworks-agent-mcp", "part_type": normalized_type, "parameters": parameters},
        "features": features,
    }

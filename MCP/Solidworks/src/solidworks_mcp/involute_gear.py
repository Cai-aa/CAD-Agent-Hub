from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from .contracts import ContractError, require_positive


@dataclass(frozen=True)
class InvoluteGearSpec:
    module_mm: float
    tooth_count: int
    pressure_angle_deg: float
    thickness_mm: float
    bore_diameter_mm: float
    root_fillet_mm: float
    tip_chamfer_mm: float
    pitch_radius_mm: float
    base_radius_mm: float
    root_radius_mm: float
    outer_radius_mm: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def involute_angle(radius: float, base_radius: float) -> float:
    if radius < base_radius:
        raise ValueError("An involute is undefined below its base circle")
    phi = math.acos(base_radius / radius)
    return math.sqrt((radius / base_radius) ** 2 - 1.0) - phi


def validate_gear_spec(
    *,
    module_mm: float,
    tooth_count: int,
    pressure_angle_deg: float,
    thickness_mm: float,
    bore_diameter_mm: float,
    root_fillet_mm: float,
    tip_chamfer_mm: float,
) -> InvoluteGearSpec:
    module_mm = require_positive(module_mm, "module_mm")
    pressure_angle_deg = require_positive(pressure_angle_deg, "pressure_angle_deg")
    thickness_mm = require_positive(thickness_mm, "thickness_mm")
    bore_diameter_mm = require_positive(bore_diameter_mm, "bore_diameter_mm")
    root_fillet_mm = require_positive(root_fillet_mm, "root_fillet_mm")
    tip_chamfer_mm = require_positive(tip_chamfer_mm, "tip_chamfer_mm")
    if not isinstance(tooth_count, int) or isinstance(tooth_count, bool) or not 8 <= tooth_count <= 160:
        raise ContractError("tooth_count must be an integer from 8 to 160")
    if not 14.5 <= pressure_angle_deg <= 30.0:
        raise ContractError("pressure_angle_deg must be from 14.5 to 30 degrees")

    pitch_radius = module_mm * tooth_count / 2.0
    base_radius = pitch_radius * math.cos(math.radians(pressure_angle_deg))
    root_radius = pitch_radius - 1.25 * module_mm
    outer_radius = pitch_radius + module_mm
    if root_radius <= 0:
        raise ContractError("module/tooth_count produces a non-positive root radius")
    if bore_diameter_mm / 2.0 >= root_radius - root_fillet_mm:
        raise ContractError("bore_diameter_mm leaves insufficient material at the tooth root")
    if root_fillet_mm >= module_mm:
        raise ContractError("root_fillet_mm must be smaller than module_mm")
    if tip_chamfer_mm >= module_mm / 2.0:
        raise ContractError("tip_chamfer_mm must be smaller than half the module")
    return InvoluteGearSpec(
        module_mm=module_mm,
        tooth_count=tooth_count,
        pressure_angle_deg=pressure_angle_deg,
        thickness_mm=thickness_mm,
        bore_diameter_mm=bore_diameter_mm,
        root_fillet_mm=root_fillet_mm,
        tip_chamfer_mm=tip_chamfer_mm,
        pitch_radius_mm=pitch_radius,
        base_radius_mm=base_radius,
        root_radius_mm=root_radius,
        outer_radius_mm=outer_radius,
    )


def _polar(radius: float, angle: float) -> list[float]:
    return [radius * math.cos(angle), radius * math.sin(angle)]


def sampled_involute_tooth_points(
    spec: InvoluteGearSpec,
    *,
    center_mm: tuple[float, float] = (0.0, 0.0),
    rotation_rad: float = 0.0,
    samples_per_flank: int = 16,
    samples_across_tip: int = 5,
) -> list[list[float]]:
    """Return a closed, high-resolution involute tooth polygon in millimetres."""
    if samples_per_flank < 6:
        raise ContractError("samples_per_flank must be at least 6")
    if samples_across_tip < 2:
        raise ContractError("samples_across_tip must be at least 2")

    half_tooth_at_pitch = math.pi / (2.0 * spec.tooth_count)
    base_half_angle = half_tooth_at_pitch + involute_angle(
        spec.pitch_radius_mm, spec.base_radius_mm
    )
    roll_end = math.sqrt((spec.outer_radius_mm / spec.base_radius_mm) ** 2 - 1.0)

    upper_flank: list[list[float]] = []
    for index in range(samples_per_flank):
        t = roll_end * index / (samples_per_flank - 1)
        x = spec.base_radius_mm * (math.cos(t) + t * math.sin(t))
        y = -spec.base_radius_mm * (math.sin(t) - t * math.cos(t))
        cos_a, sin_a = math.cos(base_half_angle), math.sin(base_half_angle)
        upper_flank.append([x * cos_a - y * sin_a, x * sin_a + y * cos_a])

    lower_flank = [[point[0], -point[1]] for point in upper_flank]
    tip_half_angle = math.atan2(upper_flank[-1][1], upper_flank[-1][0])
    tip_points = [
        _polar(
            spec.outer_radius_mm,
            -tip_half_angle + 2.0 * tip_half_angle * index / (samples_across_tip - 1),
        )
        for index in range(samples_across_tip)
    ]

    local_points: list[list[float]] = [
        _polar(spec.root_radius_mm, -base_half_angle),
        *lower_flank,
        *tip_points[1:-1],
        *reversed(upper_flank),
        _polar(spec.root_radius_mm, base_half_angle),
    ]

    center_x, center_y = center_mm
    cos_r, sin_r = math.cos(rotation_rad), math.sin(rotation_rad)
    return [
        [
            center_x + point[0] * cos_r - point[1] * sin_r,
            center_y + point[0] * sin_r + point[1] * cos_r,
        ]
        for point in local_points
    ]


def sampled_involute_gear_entities(
    spec: InvoluteGearSpec,
    *,
    center_mm: tuple[float, float] = (0.0, 0.0),
    samples_per_flank: int = 16,
) -> list[dict[str, Any]]:
    """Return one closed native polyline region per involute tooth."""
    return [
        {
            "kind": "polyline",
            "closed": True,
            "points": sampled_involute_tooth_points(
                spec,
                center_mm=center_mm,
                rotation_rad=2.0 * math.pi * index / spec.tooth_count,
                samples_per_flank=samples_per_flank,
            ),
        }
        for index in range(spec.tooth_count)
    ]


def involute_tooth_entities(spec: InvoluteGearSpec, samples_per_flank: int = 12) -> list[dict[str, Any]]:
    if samples_per_flank < 6:
        raise ContractError("samples_per_flank must be at least 6")
    half_tooth_at_pitch = math.pi / (2.0 * spec.tooth_count)
    base_half_angle = half_tooth_at_pitch + involute_angle(spec.pitch_radius_mm, spec.base_radius_mm)

    left_root = _polar(spec.root_radius_mm, -base_half_angle)
    left_base = _polar(spec.base_radius_mm, -base_half_angle)
    right_base = _polar(spec.base_radius_mm, base_half_angle)
    right_root = _polar(spec.root_radius_mm, base_half_angle)

    roll_end = math.sqrt((spec.outer_radius_mm / spec.base_radius_mm) ** 2 - 1.0)
    outer_winding = involute_angle(spec.outer_radius_mm, spec.base_radius_mm)
    left_outer = _polar(spec.outer_radius_mm, -base_half_angle + outer_winding)
    right_outer = _polar(spec.outer_radius_mm, base_half_angle - outer_winding)

    # EquationSpline coordinates are evaluated in SolidWorks system units
    # (metres). Keeping the analytic involute here avoids approximation and the
    # unreliable SAFEARRAY marshaling required by CreateSpline2/3.
    rb = spec.base_radius_mm * 0.001
    cb = math.cos(base_half_angle)
    sb = math.sin(base_half_angle)
    fmt = lambda value: format(value, ".17g")
    base_x = f"({fmt(rb)})*(cos(t)+t*sin(t))"
    base_y = f"({fmt(rb)})*(sin(t)-t*cos(t))"
    upper_flank_x = f"({base_x})*({fmt(cb)})+({base_y})*({fmt(sb)})"
    upper_flank_y = f"({base_x})*({fmt(sb)})-({base_y})*({fmt(cb)})"
    equation_common = {
        "kind": "equation_spline",
        "range_start": "0",
        "range_end": fmt(roll_end),
        "lock_start": True,
        "lock_end": True,
    }

    return [
        {"kind": "line", "start": left_root, "end": left_base},
        {
            **equation_common,
            "x_expression": upper_flank_x,
            "y_expression": f"-({upper_flank_y})",
            "start": left_base,
            "end": left_outer,
        },
        {
            "kind": "arc",
            "center": [0.0, 0.0],
            "start": left_outer,
            "end": right_outer,
            "direction": 1,
        },
        {
            **equation_common,
            "x_expression": upper_flank_x,
            "y_expression": upper_flank_y,
            "start": right_base,
            "end": right_outer,
        },
        {"kind": "line", "start": right_base, "end": right_root},
        {"kind": "line", "start": right_root, "end": left_root},
    ]


def build_involute_gear_graph(
    spec: InvoluteGearSpec,
    tooth_representation: str = "sampled_polyline",
    include_finishing: bool = True,
) -> dict[str, Any]:
    """Build a native-feature graph with a single involute tooth as the pattern seed.

    The sampled native polyline is the default because it is reliable across
    late-bound and makepy-generated SolidWorks COM proxies. The analytic
    equation-spline representation remains available for hosts that expose
    stable ISketchPoint endpoint interfaces.
    """
    if tooth_representation not in {"sampled_polyline", "equation_spline"}:
        raise ContractError("tooth_representation must be sampled_polyline or equation_spline")
    tooth_entities = (
        [{
            "kind": "polyline",
            "closed": True,
            "points": sampled_involute_tooth_points(spec, samples_per_flank=16),
        }]
        if tooth_representation == "sampled_polyline"
        else involute_tooth_entities(spec)
    )
    return {
        "version": "1.0",
        "metadata": {
            "generator": "solidworks-agent-mcp",
            "part_type": "involute_spur_gear",
            "gear_spec": spec.to_dict(),
            "bore_fit": "H7",
            "tooth_representation": tooth_representation,
            "finishing_features_included": include_finishing,
        },
        "features": [
            {"name": "Part", "kind": "new_part", "title": "Involute Spur Gear"},
            {
                "name": "GearBlankSketch",
                "kind": "sketch",
                "plane": "Front Plane",
                "entities": [
                    {"kind": "circle", "center": [0.0, 0.0], "radius_mm": spec.root_radius_mm}
                ],
            },
            {
                "name": "GearBlank",
                "kind": "boss_extrude",
                "sketch": "GearBlankSketch",
                "depth_mm": spec.thickness_mm,
            },
            {
                "name": "GearAxis",
                "kind": "reference_axis",
                "planes": ["Top Plane", "Right Plane"],
            },
            {
                "name": "InvoluteToothSketch",
                "kind": "sketch",
                "plane": "Front Plane",
                "entities": tooth_entities,
            },
            {
                "name": "ToothBoss",
                "kind": "boss_extrude",
                "sketch": "InvoluteToothSketch",
                "depth_mm": spec.thickness_mm,
                "merge": True,
            },
            {
                "name": "ToothCircularPattern",
                "kind": "circular_pattern",
                "feature": "ToothBoss",
                "axis": "GearAxis",
                "count": spec.tooth_count,
                "total_angle_deg": 360.0,
                "geometry_pattern": True,
            },
            {
                "name": "BoreSketch",
                "kind": "sketch",
                "plane": "Front Plane",
                "entities": [
                    {"kind": "circle", "center": [0.0, 0.0], "radius_mm": spec.bore_diameter_mm / 2.0}
                ],
            },
            {
                "name": "BoreCut",
                "kind": "cut_extrude",
                "sketch": "BoreSketch",
                "through_all": True,
            },
            *([
                {
                    "name": "RootFillet",
                    "kind": "fillet",
                    "radius_mm": spec.root_fillet_mm,
                    "selector": {
                        "orientation": "axial",
                        "radius_mm": spec.root_radius_mm,
                        "radius_tolerance_mm": max(0.08, spec.module_mm * 0.08),
                        "expected_count": spec.tooth_count * 2,
                    },
                },
                {
                    "name": "TipChamfer",
                    "kind": "chamfer",
                    "distance_mm": spec.tip_chamfer_mm,
                    "angle_deg": 45.0,
                    "selector": {
                        "orientation": "planar",
                        "radius_mm": spec.outer_radius_mm,
                        "radius_tolerance_mm": max(0.08, spec.module_mm * 0.08),
                        "expected_count": spec.tooth_count * 2,
                    },
                },
            ] if include_finishing else []),
        ],
    }

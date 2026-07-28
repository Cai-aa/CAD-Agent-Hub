from __future__ import annotations

from copy import deepcopy
from typing import Any

from .contracts import ContractError, require_positive


SUPPORTED_KINDS = {
    "new_part",
    "sketch",
    "boss_extrude",
    "boss_revolve",
    "cut_extrude",
    "reference_plane_offset",
    "reference_axis",
    "circular_pattern",
    "fillet",
    "chamfer",
    # Backward-compatible compile-only feature from the first release.
    "extrude",
}


def _point(value: Any, name: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) not in {2, 3}:
        raise ContractError(f"{name} must contain two or three coordinates")
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{name} coordinates must be numbers") from exc


def _sketch_entities(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ContractError(f"{name} must be a non-empty array")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ContractError(f"{name}[{index}] must be an object")
        entity = deepcopy(raw)
        kind = entity.get("kind")
        prefix = f"{name}[{index}]"
        if kind == "line":
            entity["start"] = _point(entity.get("start"), f"{prefix}.start")
            entity["end"] = _point(entity.get("end"), f"{prefix}.end")
            entity["construction"] = bool(entity.get("construction", False))
        elif kind == "circle":
            entity["center"] = _point(entity.get("center", [0, 0]), f"{prefix}.center")
            entity["radius_mm"] = require_positive(entity.get("radius_mm"), f"{prefix}.radius_mm")
        elif kind == "arc":
            entity["center"] = _point(entity.get("center"), f"{prefix}.center")
            entity["start"] = _point(entity.get("start"), f"{prefix}.start")
            entity["end"] = _point(entity.get("end"), f"{prefix}.end")
            direction = entity.get("direction", 1)
            if direction not in {-1, 1}:
                raise ContractError(f"{prefix}.direction must be -1 or 1")
            entity["direction"] = direction
        elif kind in {"spline", "polyline"}:
            points = entity.get("points")
            if not isinstance(points, list) or len(points) < 2:
                raise ContractError(f"{prefix}.points must contain at least two points")
            entity["points"] = [_point(point, f"{prefix}.points") for point in points]
            entity["closed"] = bool(entity.get("closed", False))
        elif kind == "equation_spline":
            for field in ("x_expression", "y_expression", "range_start", "range_end"):
                value = entity.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise ContractError(f"{prefix}.{field} must be a non-empty string")
                entity[field] = value.strip()
            z_expression = entity.get("z_expression", "")
            if not isinstance(z_expression, str):
                raise ContractError(f"{prefix}.z_expression must be a string")
            entity["z_expression"] = z_expression.strip()
            entity["rotation_angle_deg"] = float(entity.get("rotation_angle_deg", 0.0))
            entity["x_offset_mm"] = float(entity.get("x_offset_mm", 0.0))
            entity["y_offset_mm"] = float(entity.get("y_offset_mm", 0.0))
            entity["lock_start"] = bool(entity.get("lock_start", True))
            entity["lock_end"] = bool(entity.get("lock_end", True))
            if "start" in entity:
                entity["start"] = _point(entity["start"], f"{prefix}.start")
            if "end" in entity:
                entity["end"] = _point(entity["end"], f"{prefix}.end")
        else:
            raise ContractError(f"Unsupported sketch entity kind: {kind}")
        result.append(entity)
    return result


def _reference(value: Any, seen: set[str], name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{name} must be a feature name")
    if value not in seen:
        raise ContractError(f"{name} references unknown or later feature: {value}")
    return value


def _selector(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{name} must be an object")
    selector = deepcopy(value)
    orientation = selector.get("orientation", "any")
    if orientation not in {"any", "axial", "planar"}:
        raise ContractError(f"{name}.orientation must be any, axial, or planar")
    selector["orientation"] = orientation
    if "center_mm" in selector:
        selector["center_mm"] = _point(selector["center_mm"], f"{name}.center_mm")
    if "radius_mm" in selector:
        selector["radius_mm"] = require_positive(selector["radius_mm"], f"{name}.radius_mm")
    if "radius_tolerance_mm" in selector:
        selector["radius_tolerance_mm"] = require_positive(
            selector["radius_tolerance_mm"], f"{name}.radius_tolerance_mm"
        )
    if "tolerance_mm" in selector:
        selector["tolerance_mm"] = require_positive(selector["tolerance_mm"], f"{name}.tolerance_mm")
    if "z_levels_mm" in selector:
        levels = selector["z_levels_mm"]
        if not isinstance(levels, list) or not levels:
            raise ContractError(f"{name}.z_levels_mm must be a non-empty array")
        selector["z_levels_mm"] = [float(level) for level in levels]
    if "expected_count" in selector:
        count = selector["expected_count"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ContractError(f"{name}.expected_count must be a positive integer")
    return selector


def compile_feature_graph(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate and normalize a safe, executable SolidWorks Feature Graph."""
    if not isinstance(graph, dict):
        raise ContractError("feature_graph must be an object")
    if graph.get("version") != "1.0":
        raise ContractError("feature_graph.version must be '1.0'")
    features = graph.get("features")
    if not isinstance(features, list) or not features:
        raise ContractError("feature_graph.features must be a non-empty array")

    plan: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            raise ContractError(f"features[{index}] must be an object")
        name = feature.get("name")
        kind = feature.get("kind")
        if not isinstance(name, str) or not name or name in seen:
            raise ContractError(f"features[{index}].name must be unique")
        if kind not in SUPPORTED_KINDS:
            raise ContractError(f"Unsupported feature kind: {kind}")
        if index == 0 and kind != "new_part":
            raise ContractError("The first feature must be new_part")
        step: dict[str, Any] = {"step": index + 1, "name": name, "kind": kind}

        if kind == "new_part":
            if index != 0:
                raise ContractError("new_part can only be the first feature")
            step.update(operation="new_part", title=str(feature.get("title", name)))
        elif kind == "sketch":
            plane = feature.get("plane", "Front Plane")
            if not isinstance(plane, str) or not plane:
                raise ContractError(f"features[{index}].plane must be a string")
            step.update(
                operation="create_sketch",
                plane=plane,
                entities=_sketch_entities(feature.get("entities"), f"features[{index}].entities"),
            )
        elif kind == "boss_extrude":
            step.update(
                operation="boss_extrude",
                sketch=_reference(feature.get("sketch"), seen, f"features[{index}].sketch"),
                depth_mm=require_positive(feature.get("depth_mm"), f"features[{index}].depth_mm"),
                merge=bool(feature.get("merge", True)),
            )
        elif kind == "boss_revolve":
            axis = feature.get("axis")
            axis_segment = feature.get("axis_segment")
            if (axis is None) == (axis_segment is None):
                raise ContractError(
                    f"features[{index}] boss_revolve requires exactly one of axis or axis_segment"
                )
            normalized_axis: str | None = None
            normalized_axis_segment: str | None = None
            axis_strategy: str
            if axis is not None:
                normalized_axis = _reference(axis, seen, f"features[{index}].axis")
                axis_strategy = "reference_axis"
            else:
                if not isinstance(axis_segment, str) or not axis_segment.strip():
                    raise ContractError(f"features[{index}].axis_segment must be a non-empty string")
                normalized_axis_segment = axis_segment.strip()
                axis_strategy = "sketch_segment"
            step.update(
                operation="boss_revolve",
                sketch=_reference(feature.get("sketch"), seen, f"features[{index}].sketch"),
                axis=normalized_axis,
                axis_segment=normalized_axis_segment,
                axis_strategy=axis_strategy,
                angle_deg=require_positive(feature.get("angle_deg", 360.0), f"features[{index}].angle_deg"),
                merge=bool(feature.get("merge", True)),
            )
        elif kind == "cut_extrude":
            through_all = bool(feature.get("through_all", False))
            depth = feature.get("depth_mm")
            if not through_all:
                depth = require_positive(depth, f"features[{index}].depth_mm")
            step.update(
                operation="cut_extrude",
                sketch=_reference(feature.get("sketch"), seen, f"features[{index}].sketch"),
                through_all=through_all,
                depth_mm=float(depth) if depth is not None else None,
                reverse_direction=bool(feature.get("reverse_direction", False)),
            )
        elif kind == "reference_plane_offset":
            base_plane = feature.get("base_plane", "Front Plane")
            if not isinstance(base_plane, str) or not base_plane:
                raise ContractError(f"features[{index}].base_plane must be a string")
            offset_mm = float(feature.get("offset_mm", 0.0))
            if offset_mm == 0.0:
                raise ContractError(f"features[{index}].offset_mm must be non-zero")
            step.update(
                operation="reference_plane_offset",
                base_plane=base_plane,
                offset_mm=offset_mm,
            )
        elif kind == "reference_axis":
            planes = feature.get("planes")
            if not isinstance(planes, list) or len(planes) != 2 or not all(isinstance(item, str) for item in planes):
                raise ContractError(f"features[{index}].planes must contain exactly two plane names")
            step.update(operation="reference_axis", planes=planes)
        elif kind == "circular_pattern":
            count = feature.get("count")
            if not isinstance(count, int) or isinstance(count, bool) or count < 2:
                raise ContractError(f"features[{index}].count must be an integer >= 2")
            step.update(
                operation="circular_pattern",
                feature=_reference(feature.get("feature"), seen, f"features[{index}].feature"),
                axis=_reference(feature.get("axis"), seen, f"features[{index}].axis"),
                count=count,
                total_angle_deg=require_positive(
                    feature.get("total_angle_deg", 360.0), f"features[{index}].total_angle_deg"
                ),
                geometry_pattern=bool(feature.get("geometry_pattern", True)),
            )
        elif kind == "fillet":
            step.update(
                operation="fillet",
                radius_mm=require_positive(feature.get("radius_mm"), f"features[{index}].radius_mm"),
                selector=_selector(feature.get("selector"), f"features[{index}].selector"),
            )
        elif kind == "chamfer":
            step.update(
                operation="chamfer",
                distance_mm=require_positive(feature.get("distance_mm"), f"features[{index}].distance_mm"),
                angle_deg=require_positive(feature.get("angle_deg", 45.0), f"features[{index}].angle_deg"),
                selector=_selector(feature.get("selector"), f"features[{index}].selector"),
            )
        elif kind == "extrude":
            depth_mm = require_positive(feature.get("depth_mm"), f"features[{index}].depth_mm")
            profile = feature.get("profile")
            if profile not in {"circle", "rectangle"}:
                raise ContractError("extrude.profile must be circle or rectangle")
            step.update(
                operation="create_sketch_and_extrude",
                profile=profile,
                depth_mm=depth_mm,
                status="compile_only_legacy",
            )
        plan.append(step)
        seen.add(name)
    return plan

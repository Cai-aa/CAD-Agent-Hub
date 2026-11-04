from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from .contracts import ContractError, require_positive, require_finite
from .modeling_rules import prepare_feature_graph, plane_frame


SUPPORTED_KINDS = {
    "new_part",
    "sketch",
    "boss_extrude",
    "boss_revolve",
    "cut_extrude",
    "cut_loft",
    "reference_plane_offset",
    "reference_plane_points",
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
        return [
            require_finite(float(item), name)
            if not isinstance(item, bool)
            else require_finite(item, name)
            for item in value
        ]
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{name} coordinates must be numbers") from exc


def _sketch_entities(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ContractError(f"{name} must be a non-empty array")
    if len(value) > 5000:
        raise ContractError("Sketch exceeds the 5000-entity budget")
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
            entity["radius_mm"] = require_positive(
                entity.get("radius_mm"), f"{prefix}.radius_mm"
            )
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
            if not isinstance(points, list) or not 2 <= len(points) <= 10000:
                raise ContractError(f"{prefix}.points must contain at least two points")
            entity["points"] = [_point(point, f"{prefix}.points") for point in points]
            entity["closed"] = bool(entity.get("closed", False))
        elif kind == "equation_spline":
            for field in ("x_expression", "y_expression", "range_start", "range_end"):
                value = entity.get(field)
                if not isinstance(value, str) or not value.strip() or len(value) > 4096:
                    raise ContractError(f"{prefix}.{field} must be a non-empty string")
                entity[field] = value.strip()
            z_expression = entity.get("z_expression", "")
            if not isinstance(z_expression, str):
                raise ContractError(f"{prefix}.z_expression must be a string")
            entity["z_expression"] = z_expression.strip()
            entity["rotation_angle_deg"] = require_finite(
                entity.get("rotation_angle_deg", 0.0), "rotation_angle_deg"
            )
            entity["x_offset_mm"] = require_finite(
                entity.get("x_offset_mm", 0.0), "x_offset_mm"
            )
            entity["y_offset_mm"] = require_finite(
                entity.get("y_offset_mm", 0.0), "y_offset_mm"
            )
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
        selector["radius_mm"] = require_positive(
            selector["radius_mm"], f"{name}.radius_mm"
        )
    if "radius_tolerance_mm" in selector:
        selector["radius_tolerance_mm"] = require_positive(
            selector["radius_tolerance_mm"], f"{name}.radius_tolerance_mm"
        )
    if "tolerance_mm" in selector:
        selector["tolerance_mm"] = require_positive(
            selector["tolerance_mm"], f"{name}.tolerance_mm"
        )
    if "z_levels_mm" in selector:
        levels = selector["z_levels_mm"]
        if not isinstance(levels, list) or not levels:
            raise ContractError(f"{name}.z_levels_mm must be a non-empty array")
        selector["z_levels_mm"] = [
            require_finite(level, "z_levels_mm") for level in levels
        ]
    if "expected_count" in selector:
        count = selector["expected_count"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ContractError(f"{name}.expected_count must be a positive integer")
    return selector


def compile_feature_graph(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate and normalize a safe, executable SolidWorks Feature Graph."""
    if not isinstance(graph, dict):
        raise ContractError("feature_graph must be an object")
    graph, _, _ = prepare_feature_graph(graph)
    if graph.get("version") != "1.0":
        raise ContractError("feature_graph.version must be '1.0'")
    features = graph.get("features")
    if not isinstance(features, list) or not features:
        raise ContractError("feature_graph.features must be a non-empty array")
    if len(features) > 256:
        raise ContractError("Feature Graph exceeds the 256-feature budget")
    # Reject deep or huge inputs before deepcopy and COM work.
    stack, nodes = [(graph, 0)], 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > 50000 or depth > 32:
            raise ContractError("Feature Graph exceeds the node/depth budget")
        if isinstance(value, float):
            require_finite(value, "feature_graph value")
        if isinstance(value, dict):
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, (list, tuple)):
            stack.extend((item, depth + 1) for item in value)

    plan: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            raise ContractError(f"features[{index}] must be an object")
        name = feature.get("name")
        kind = feature.get("kind")
        if not isinstance(name, str) or not name or name in seen:
            raise ContractError(f"features[{index}].name must be unique")
        if graph.get("metadata",{}).get("tree_language")=="zh-CN" and not re.search(r"[\u4e00-\u9fff]",name):
            raise ContractError("中文特征树模式下，所有新建特征名称必须包含中文")
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
                coordinate_space=feature.get("coordinate_space", "sketch"),
                entities=_sketch_entities(
                    feature.get("entities"), f"features[{index}].entities"
                ),
            )
            if step["coordinate_space"] not in {"sketch", "model"}:
                raise ContractError("coordinate_space must be sketch or model")
            if step["coordinate_space"] == "model":
                for entity in step["entities"]:
                    points = [entity[field] for field in ("center", "start", "end") if field in entity]
                    points.extend(entity.get("points", []))
                    if any(len(point) != 3 for point in points):
                        raise ContractError("Model-space sketch points require three coordinates")
        elif kind == "boss_extrude":
            step.update(
                operation="boss_extrude",
                reverse_direction=bool(feature.get("reverse_direction", True)),
                sketch=_reference(
                    feature.get("sketch"), seen, f"features[{index}].sketch"
                ),
                depth_mm=require_positive(
                    feature.get("depth_mm"), f"features[{index}].depth_mm"
                ),
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
                    raise ContractError(
                        f"features[{index}].axis_segment must be a non-empty string"
                    )
                normalized_axis_segment = axis_segment.strip()
                axis_strategy = "sketch_segment"
            step.update(
                operation="boss_revolve",
                sketch=_reference(
                    feature.get("sketch"), seen, f"features[{index}].sketch"
                ),
                axis=normalized_axis,
                axis_segment=normalized_axis_segment,
                axis_strategy=axis_strategy,
                angle_deg=require_positive(
                    feature.get("angle_deg", 360.0), f"features[{index}].angle_deg"
                ),
                merge=bool(feature.get("merge", True)),
            )
        elif kind == "cut_extrude":
            through_all = bool(feature.get("through_all", False))
            depth = feature.get("depth_mm")
            if not through_all:
                depth = require_positive(depth, f"features[{index}].depth_mm")
            step.update(
                operation="cut_extrude",
                sketch=_reference(
                    feature.get("sketch"), seen, f"features[{index}].sketch"
                ),
                through_all=through_all,
                depth_mm=float(depth) if depth is not None else None,
                reverse_direction=bool(feature.get("reverse_direction", False)),
            )
        elif kind == "cut_loft":
            profiles = feature.get("profiles")
            if not isinstance(profiles, list) or len(profiles) != 2:
                raise ContractError("cut_loft requires exactly two sketch profiles")
            refs=[_reference(value,seen,"loft profile") for value in profiles]
            if len(set(refs))!=2 or any(next(p for p in plan if p["name"]==value)["kind"]!="sketch" for value in refs):
                raise ContractError("cut_loft profiles must reference two different sketches")
            step.update(operation="cut_loft",profiles=refs)
        elif kind == "reference_plane_points":
            points = feature.get("points_mm")
            if not isinstance(points, list) or len(points) != 3:
                raise ContractError("A fixed plane needs exactly three model-space points")
            points = [_point(point, "plane point") for point in points]
            if any(len(point) != 3 for point in points):
                raise ContractError("Plane points must have three coordinates")
            a = [points[1][i] - points[0][i] for i in range(3)]
            b = [points[2][i] - points[0][i] for i in range(3)]
            cross = [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
            plane_frame(points)
            step.update(operation="reference_plane_points", points_mm=points)
        elif kind == "reference_plane_offset":
            base_plane = feature.get("base_plane", "Front Plane")
            if not isinstance(base_plane, str) or not base_plane:
                raise ContractError(f"features[{index}].base_plane must be a string")
            offset_mm = require_finite(feature.get("offset_mm", 0.0), "offset_mm")
            if offset_mm == 0.0:
                raise ContractError(f"features[{index}].offset_mm must be non-zero")
            step.update(
                operation="reference_plane_offset",
                base_plane=base_plane,
                offset_mm=offset_mm,
            )
        elif kind == "reference_axis":
            planes = feature.get("planes")
            if (
                not isinstance(planes, list)
                or len(planes) != 2
                or not all(isinstance(item, str) for item in planes)
            ):
                raise ContractError(
                    f"features[{index}].planes must contain exactly two plane names"
                )
            step.update(operation="reference_axis", planes=planes)
        elif kind == "circular_pattern":
            count = feature.get("count")
            if (
                not isinstance(count, int)
                or isinstance(count, bool)
                or not 2 <= count <= 1000
            ):
                raise ContractError(f"features[{index}].count must be an integer >= 2")
            step.update(
                operation="circular_pattern",
                feature=_reference(
                    feature.get("feature"), seen, f"features[{index}].feature"
                ),
                axis=_reference(feature.get("axis"), seen, f"features[{index}].axis"),
                count=count,
                total_angle_deg=require_positive(
                    feature.get("total_angle_deg", 360.0),
                    f"features[{index}].total_angle_deg",
                ),
                geometry_pattern=bool(feature.get("geometry_pattern", True)),
            )
        elif kind == "fillet":
            step.update(
                operation="fillet",
                radius_mm=require_positive(
                    feature.get("radius_mm"), f"features[{index}].radius_mm"
                ),
                selector=_selector(
                    feature.get("selector"), f"features[{index}].selector"
                ),
            )
        elif kind == "chamfer":
            step.update(
                operation="chamfer",
                distance_mm=require_positive(
                    feature.get("distance_mm"), f"features[{index}].distance_mm"
                ),
                angle_deg=require_positive(
                    feature.get("angle_deg", 45.0), f"features[{index}].angle_deg"
                ),
                selector=_selector(
                    feature.get("selector"), f"features[{index}].selector"
                ),
            )
        elif kind == "extrude":
            depth_mm = require_positive(
                feature.get("depth_mm"), f"features[{index}].depth_mm"
            )
            profile = feature.get("profile")
            if profile not in {"circle", "rectangle"}:
                raise ContractError("extrude.profile must be circle or rectangle")
            step.update(
                operation="create_sketch_and_extrude",
                profile=profile,
                depth_mm=depth_mm,
                status="compile_only_legacy",
            )
        prior = {item["name"]: item for item in plan}
        for field, expected_kind in (("sketch", "sketch"), ("axis", "reference_axis")):
            reference = step.get(field)
            if reference is not None and prior[reference]["kind"] != expected_kind:
                raise ContractError(f"{name}.{field} must reference a {expected_kind}")
        if kind == "circular_pattern":
            seed = prior[step["feature"]]
            if seed["kind"] in {
                "new_part",
                "sketch",
                "reference_axis",
                "reference_plane_offset",
                "reference_plane_points",
            }:
                raise ContractError(
                    "circular_pattern.feature must reference a solid feature"
                )
            step["estimated_instances"] = (
                seed.get("estimated_instances", 1) * step["count"]
            )
            if step["estimated_instances"] > 10000:
                raise ContractError("Nested patterns exceed the 10000-instance budget")
        plan.append(step)
        seen.add(name)
    return plan

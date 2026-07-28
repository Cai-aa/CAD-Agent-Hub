from __future__ import annotations

import array
import base64
import math
from typing import Any

from .contracts import ContractError, require_positive, require_text
from .feature_graph import _sketch_entities
from .native_features import (
    MM,
    _com_value,
    _create_spline,
    _point3,
    _select_by_id,
    _select_edges,
    boss_revolve,
    create_sketch,
    cut_extrude,
    rebuild as rebuild_model,
    rename_feature,
)


_UNIT_TO_SYSTEM = {
    "m": 1.0,
    "mm": 0.001,
    "cm": 0.01,
    "in": 0.0254,
    "rad": 1.0,
    "deg": math.pi / 180.0,
}
_CONFIGURATION_OPTIONS = {"this": 1, "all": 2, "specific": 3}
_ROLLBACK_LOCATIONS = {"end": 1, "previous": 2, "before": 3, "after": 4}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _feature_name(feature: Any) -> str:
    try:
        return str(feature.Name)
    except Exception:
        return str(_com_value(feature, "GetNameForSelection"))


def _related_feature_names(feature: Any, member: str) -> list[str]:
    try:
        return [_feature_name(item) for item in _as_list(_com_value(feature, member))]
    except Exception:
        return []


def _dimension(model: Any, name: str) -> Any:
    dimension = None
    for member_name in ("Parameter", "IParameter"):
        try:
            dimension = _com_value(model, member_name, name)
        except Exception:
            continue
        if dimension is not None:
            break
    if dimension is None:
        raise RuntimeError(f"Dimension not found: {name}. Use a full name such as D1@Boss-Extrude1.")
    return dimension


def _dimension_system_value(dimension: Any) -> float | None:
    for call in (("GetSystemValue3", (1, None)), ("SystemValue", ())):
        try:
            value = _com_value(dimension, call[0], *call[1])
            if isinstance(value, (list, tuple)):
                value = value[0] if value else None
            return None if value is None else float(value)
        except Exception:
            continue
    return None


def set_dimension(
    model: Any,
    dimension_name: str,
    value: float,
    unit: str = "mm",
    configuration: str = "this",
    configuration_names: list[str] | None = None,
    rebuild: bool = True,
) -> dict[str, Any]:
    dimension_name = require_text(dimension_name, "dimension_name")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ContractError("value must be a number")
    normalized_unit = str(unit).strip().lower()
    if normalized_unit not in _UNIT_TO_SYSTEM:
        raise ContractError(f"unit must be one of: {', '.join(_UNIT_TO_SYSTEM)}")
    normalized_configuration = str(configuration).strip().lower()
    if normalized_configuration not in _CONFIGURATION_OPTIONS:
        raise ContractError("configuration must be this, all, or specific")
    if normalized_configuration == "specific" and not configuration_names:
        raise ContractError("configuration_names is required when configuration= specific")

    dimension = _dimension(model, dimension_name)
    old_system = _dimension_system_value(dimension)
    new_system = float(value) * _UNIT_TO_SYSTEM[normalized_unit]
    config_argument: Any = configuration_names if normalized_configuration == "specific" else None
    status = _com_value(
        dimension,
        "SetSystemValue3",
        new_system,
        _CONFIGURATION_OPTIONS[normalized_configuration],
        config_argument,
    )
    if rebuild:
        _com_value(model, "EditRebuild3")
    return {
        "ok": True,
        "dimension": dimension_name,
        "old_system_value": old_system,
        "new_system_value": new_system,
        "input_value": float(value),
        "unit": normalized_unit,
        "configuration": normalized_configuration,
        "status": int(status) if isinstance(status, (int, bool)) else status,
        "rebuilt": rebuild,
    }


def set_feature_parameter(
    model: Any,
    feature_name: str,
    parameter_name: str,
    value: float,
    unit: str = "mm",
    configuration: str = "this",
    rebuild: bool = True,
) -> dict[str, Any]:
    feature_name = require_text(feature_name, "feature_name")
    parameter_name = require_text(parameter_name, "parameter_name")
    full_name = parameter_name if "@" in parameter_name else f"{parameter_name}@{feature_name}"
    result = set_dimension(model, full_name, value, unit, configuration, None, rebuild)
    result.update(feature=feature_name, parameter=parameter_name)
    return result


def _delete_active_sketch_segments(model: Any, manager: Any) -> int:
    sketch = _com_value(manager, "ActiveSketch")
    segments = _as_list(_com_value(sketch, "GetSketchSegments"))
    if not segments:
        return 0
    model.ClearSelection2(True)
    selected = 0
    for segment in segments:
        try:
            ok = bool(_com_value(segment, "Select4", True, None))
        except Exception:
            ok = bool(_com_value(segment, "Select", True))
        selected += int(ok)
    if selected and not bool(_com_value(model.Extension, "DeleteSelection2", 0)):
        raise RuntimeError("SolidWorks could not delete the selected sketch segments")
    return selected


def _append_entities(model: Any, manager: Any, entities: list[dict[str, Any]]) -> int:
    created = 0
    for index, entity in enumerate(entities):
        kind = entity["kind"]
        try:
            segment = None
            if kind == "line":
                segment = manager.CreateLine(*_point3(entity["start"]), *_point3(entity["end"]))
                if segment is not None and entity.get("construction", False):
                    segment.ConstructionGeometry = True
            elif kind == "circle":
                center = _point3(entity.get("center", (0.0, 0.0)))
                radius = float(entity["radius_mm"]) * MM
                segment = manager.CreateCircle(*center, center[0] + radius, center[1], center[2])
            elif kind == "arc":
                segment = manager.CreateArc(
                    *_point3(entity["center"]),
                    *_point3(entity["start"]),
                    *_point3(entity["end"]),
                    int(entity.get("direction", 1)),
                )
            elif kind == "spline":
                payload = array.array("d")
                for point in entity["points"]:
                    payload.extend(_point3(point))
                segment = _create_spline(manager, payload)
            elif kind == "equation_spline":
                segment = manager.CreateEquationSpline2(
                    entity["x_expression"],
                    entity["y_expression"],
                    entity.get("z_expression", ""),
                    entity["range_start"],
                    entity["range_end"],
                    False,
                    math.radians(float(entity.get("rotation_angle_deg", 0.0))),
                    float(entity.get("x_offset_mm", 0.0)) * MM,
                    float(entity.get("y_offset_mm", 0.0)) * MM,
                    bool(entity.get("lock_start", True)),
                    bool(entity.get("lock_end", True)),
                )
            elif kind == "polyline":
                points = [_point3(point) for point in entity["points"]]
                pairs = list(zip(points, points[1:]))
                if entity.get("closed", False):
                    pairs.append((points[-1], points[0]))
                for start, end in pairs:
                    if manager.CreateLine(*start, *end) is None:
                        raise RuntimeError("SolidWorks returned no line")
                    created += 1
                continue
            if segment is None:
                raise RuntimeError("SolidWorks returned no sketch segment")
            created += 1
        except Exception as exc:
            raise RuntimeError(f"create_entity[{index}] {kind} failed: {exc}") from exc
    return created


def edit_sketch(
    model: Any,
    sketch_name: str,
    entities: list[dict[str, Any]],
    mode: str = "append",
    rebuild: bool = True,
) -> dict[str, Any]:
    sketch_name = require_text(sketch_name, "sketch_name")
    normalized_mode = str(mode).strip().lower()
    if normalized_mode not in {"append", "replace"}:
        raise ContractError("mode must be append or replace")
    normalized_entities = _sketch_entities(entities, "entities")
    model.ClearSelection2(True)
    if not _select_by_id(model, sketch_name, "SKETCH"):
        raise RuntimeError(f"Sketch not found: {sketch_name}")
    _com_value(model, "EditSketch")
    manager = model.SketchManager
    previous: dict[str, Any] = {}
    deleted = 0
    try:
        for name in ("AutoSolve", "AddToDB", "DisplayWhenAdded"):
            try:
                previous[name] = getattr(manager, name)
            except Exception:
                pass
        try:
            manager.AutoSolve = False
            manager.AddToDB = True
            manager.DisplayWhenAdded = False
        except Exception:
            pass
        if normalized_mode == "replace":
            deleted = _delete_active_sketch_segments(model, manager)
        created = _append_entities(model, manager, normalized_entities)
    finally:
        for name, value in previous.items():
            try:
                setattr(manager, name, value)
            except Exception:
                pass
        model.InsertSketch2(True)
    if rebuild:
        _com_value(model, "EditRebuild3")
    return {
        "ok": True,
        "sketch": sketch_name,
        "mode": normalized_mode,
        "deleted_segments": deleted,
        "created_segments": created,
        "rebuilt": rebuild,
    }


def delete_feature(
    model: Any,
    feature_name: str,
    *,
    delete_children: bool = False,
    delete_absorbed: bool = False,
    rebuild: bool = True,
) -> dict[str, Any]:
    feature_name = require_text(feature_name, "feature_name")
    model.ClearSelection2(True)
    if not _select_by_id(model, feature_name, "BODYFEATURE"):
        if not _select_by_id(model, feature_name, "SKETCH"):
            raise RuntimeError(f"Feature not found: {feature_name}")
    options = (1 if delete_children else 0) | (2 if delete_absorbed else 0)
    deleted = bool(_com_value(model.Extension, "DeleteSelection2", options))
    if not deleted:
        raise RuntimeError(f"SolidWorks could not delete feature: {feature_name}")
    if rebuild:
        _com_value(model, "EditRebuild3")
    return {
        "ok": True,
        "feature": feature_name,
        "delete_children": delete_children,
        "delete_absorbed": delete_absorbed,
        "rebuilt": rebuild,
    }


def rollback(model: Any, location: str, feature_name: str | None = None) -> dict[str, Any]:
    normalized = str(location).strip().lower()
    if normalized not in _ROLLBACK_LOCATIONS:
        raise ContractError("location must be end, previous, before, or after")
    if normalized in {"before", "after"}:
        feature_name = require_text(feature_name, "feature_name")
    target = feature_name or ""
    moved = bool(model.FeatureManager.EditRollback(_ROLLBACK_LOCATIONS[normalized], target))
    if not moved:
        raise RuntimeError(f"SolidWorks could not move rollback bar to {normalized} {target}".strip())
    return {"ok": True, "location": normalized, "feature": feature_name}


def _persist_token(model: Any, entity: Any) -> str | None:
    try:
        raw = _com_value(model.Extension, "GetPersistReference3", entity)
        if isinstance(raw, bytes):
            payload = raw
        elif isinstance(raw, bytearray):
            payload = bytes(raw)
        else:
            payload = bytes(int(value) & 0xFF for value in raw)
        return base64.urlsafe_b64encode(payload).decode("ascii")
    except Exception:
        return None


def _decode_token(token: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(require_text(token, "reference_token").encode("ascii"))
    except Exception as exc:
        raise ContractError(f"Invalid persistent reference token: {exc}") from exc


def _resolve_token(model: Any, token: str) -> tuple[Any, int]:
    payload = _decode_token(token)
    extension = model.Extension
    try:
        import pythoncom  # type: ignore
        from win32com.client import VARIANT  # type: ignore
        error = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        entity = extension.GetObjectByPersistReference3(payload, error)
        return entity, int(error.value)
    except Exception:
        result = extension.GetObjectByPersistReference3(payload, 0)
        if isinstance(result, tuple):
            return result[0], int(result[1]) if len(result) > 1 else 0
        return result, 0


def select_references(model: Any, reference_tokens: list[str]) -> dict[str, Any]:
    if not isinstance(reference_tokens, list) or not reference_tokens:
        raise ContractError("reference_tokens must be a non-empty array")
    entities = []
    errors = []
    for index, token in enumerate(reference_tokens):
        entity, error = _resolve_token(model, token)
        if entity is None:
            errors.append({"index": index, "error_code": error})
        else:
            entities.append(entity)
    if errors:
        raise RuntimeError(f"Could not resolve persistent references: {errors}")
    _select_edges(model, entities)
    return {"ok": True, "selected_count": len(entities)}


def add_edge_feature(
    model: Any,
    kind: str,
    feature_name: str,
    reference_tokens: list[str],
    size_mm: float,
    angle_deg: float = 45.0,
    rebuild: bool = True,
) -> dict[str, Any]:
    normalized_kind = str(kind).strip().lower()
    if normalized_kind not in {"fillet", "chamfer"}:
        raise ContractError("kind must be fillet or chamfer")
    feature_name = require_text(feature_name, "feature_name")
    size_mm = require_positive(size_mm, "size_mm")
    select_result = select_references(model, reference_tokens)
    if normalized_kind == "fillet":
        feature = model.FeatureManager.FeatureFillet(195, size_mm * MM, 0, 0, None, None, None)
    else:
        angle_deg = require_positive(angle_deg, "angle_deg")
        feature = model.FeatureManager.InsertFeatureChamfer(
            4, 1, size_mm * MM, math.radians(angle_deg), 0.0, 0.0, 0.0, 0.0
        )
    rename_feature(feature, feature_name)
    if rebuild:
        _com_value(model, "EditRebuild3")
    return {
        "ok": True,
        "kind": normalized_kind,
        "feature": feature_name,
        "selected_count": select_result["selected_count"],
        "size_mm": size_mm,
        "angle_deg": angle_deg if normalized_kind == "chamfer" else None,
        "rebuilt": rebuild,
    }


def add_stepped_shaft_with_keyway(
    model: Any,
    *,
    axis_name: str = "GearAxis",
    bore_diameter_mm: float = 10.0,
    radial_clearance_mm: float = 0.1,
    gear_thickness_mm: float = 10.0,
    shoulder_diameter_mm: float = 14.0,
    shoulder_length_mm: float = 5.0,
    fit_extension_mm: float = 5.0,
    end_diameter_mm: float = 8.0,
    end_length_mm: float = 10.0,
    keyway_width_mm: float = 3.0,
    keyway_depth_mm: float = 1.6,
    rebuild: bool = True,
) -> dict[str, Any]:
    """Add a coaxial multibody stepped shaft and axial keyway to an active gear part."""
    axis_name = require_text(axis_name, "axis_name")
    bore = require_positive(bore_diameter_mm, "bore_diameter_mm")
    clearance = require_positive(radial_clearance_mm, "radial_clearance_mm")
    gear_thickness = require_positive(gear_thickness_mm, "gear_thickness_mm")
    shoulder_diameter = require_positive(shoulder_diameter_mm, "shoulder_diameter_mm")
    shoulder_length = require_positive(shoulder_length_mm, "shoulder_length_mm")
    fit_extension = require_positive(fit_extension_mm, "fit_extension_mm")
    end_diameter = require_positive(end_diameter_mm, "end_diameter_mm")
    end_length = require_positive(end_length_mm, "end_length_mm")
    keyway_width = require_positive(keyway_width_mm, "keyway_width_mm")
    keyway_depth = require_positive(keyway_depth_mm, "keyway_depth_mm")
    fit_diameter = bore - 2.0 * clearance
    if fit_diameter <= 0:
        raise ContractError("radial_clearance_mm is too large for bore_diameter_mm")
    if shoulder_diameter <= fit_diameter:
        raise ContractError("shoulder_diameter_mm must be larger than the bore-fit shaft diameter")
    if end_diameter >= fit_diameter:
        raise ContractError("end_diameter_mm must be smaller than the bore-fit shaft diameter")
    fit_radius = fit_diameter / 2.0
    if keyway_depth >= fit_radius or keyway_width >= fit_diameter:
        raise ContractError("keyway dimensions are too large for the bore-fit shaft diameter")

    fit_end = gear_thickness + fit_extension
    end_end = fit_end + end_length
    shoulder_radius = shoulder_diameter / 2.0
    end_radius = end_diameter / 2.0
    profile = [
        [0.0, -shoulder_length],
        [shoulder_radius, -shoulder_length],
        [shoulder_radius, 0.0],
        [fit_radius, 0.0],
        [fit_radius, fit_end],
        [end_radius, fit_end],
        [end_radius, end_end],
        [0.0, end_end],
    ]
    create_sketch(
        model,
        "SteppedShaftProfile",
        "Top Plane",
        [{"kind": "polyline", "closed": False, "points": profile}],
    )
    _, revolve_backend = boss_revolve(
        model,
        "SteppedShaft",
        "SteppedShaftProfile",
        axis_name=axis_name,
        merge=False,
    )

    half_width = keyway_width / 2.0
    keyway_floor = fit_radius - keyway_depth
    create_sketch(
        model,
        "ShaftKeywaySketch",
        "Front Plane",
        [{
            "kind": "polyline",
            "closed": True,
            "points": [
                [-half_width, keyway_floor],
                [half_width, keyway_floor],
                [half_width, fit_radius],
                [-half_width, fit_radius],
            ],
        }],
    )
    cut_extrude(
        model,
        "ShaftKeywayCut",
        "ShaftKeywaySketch",
        depth_mm=None,
        through_all=True,
    )
    if rebuild:
        rebuild_model(model, full=False, redraw=False)
    return {
        "ok": True,
        "operation": "add_stepped_shaft_with_keyway",
        "axis": axis_name,
        "shaft_fit_diameter_mm": fit_diameter,
        "radial_clearance_mm": clearance,
        "shoulder_diameter_mm": shoulder_diameter,
        "shoulder_length_mm": shoulder_length,
        "fit_length_mm": fit_end,
        "end_diameter_mm": end_diameter,
        "end_length_mm": end_length,
        "keyway_width_mm": keyway_width,
        "keyway_depth_mm": keyway_depth,
        "revolve_backend": revolve_backend,
        "features": [
            "SteppedShaftProfile",
            "SteppedShaft",
            "ShaftKeywaySketch",
            "ShaftKeywayCut",
        ],
        "rebuilt": rebuild,
    }


def inspect_relations(
    model: Any,
    *,
    include_topology: bool = True,
    include_persistent_references: bool = True,
    limit: int = 200,
) -> dict[str, Any]:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ContractError("limit must be a positive integer")
    feature_count = min(int(_com_value(model, "GetFeatureCount")), limit)
    features = []
    for position in reversed(range(feature_count)):
        feature = _com_value(model, "FeatureByPositionReverse", position)
        parents = _related_feature_names(feature, "GetParents")
        children = _related_feature_names(feature, "GetChildren")
        item: dict[str, Any] = {
            "name": _feature_name(feature),
            "type": str(_com_value(feature, "GetTypeName2")),
            "parents": parents,
            "children": children,
        }
        if item["type"] in {"ProfileFeature", "3DProfileFeature"} or "Sketch" in item["type"]:
            try:
                sketch = _com_value(feature, "GetSpecificFeature2")
                item["sketch_segment_count"] = len(_as_list(_com_value(sketch, "GetSketchSegments")))
            except Exception:
                item["sketch_segment_count"] = None
        features.append(item)

    topology: list[dict[str, Any]] = []
    if include_topology:
        bodies = _as_list(_com_value(model, "GetBodies2", 0, True))
        emitted = 0
        for body_index, body in enumerate(bodies):
            body_name = str(getattr(body, "Name", f"Body{body_index + 1}"))
            faces = _as_list(_com_value(body, "GetFaces"))
            for face_index, face in enumerate(faces):
                if emitted >= limit:
                    break
                edges = _as_list(_com_value(face, "GetEdges"))
                face_item: dict[str, Any] = {
                    "kind": "face",
                    "body": body_name,
                    "index": face_index,
                    "area_mm2": float(_com_value(face, "GetArea")) * 1_000_000.0,
                    "edge_count": len(edges),
                }
                if include_persistent_references:
                    face_item["reference_token"] = _persist_token(model, face)
                topology.append(face_item)
                emitted += 1
                for edge_index, edge in enumerate(edges):
                    if emitted >= limit:
                        break
                    edge_item: dict[str, Any] = {
                        "kind": "edge",
                        "body": body_name,
                        "face_index": face_index,
                        "index": edge_index,
                    }
                    for label, method in (("start_mm", "GetStartVertex"), ("end_mm", "GetEndVertex")):
                        try:
                            vertex = _com_value(edge, method)
                            point = _com_value(vertex, "GetPoint") if vertex is not None else None
                            edge_item[label] = None if point is None else [float(value) * 1000.0 for value in point]
                        except Exception:
                            edge_item[label] = None
                    if include_persistent_references:
                        edge_item["reference_token"] = _persist_token(model, edge)
                    topology.append(edge_item)
                    emitted += 1
            if emitted >= limit:
                break
    return {
        "ok": True,
        "features": features,
        "feature_count_returned": len(features),
        "topology": topology,
        "topology_count_returned": len(topology),
        "truncated": feature_count >= limit or len(topology) >= limit,
    }

from __future__ import annotations

import array
import math
from typing import Any, Iterable


MM = 0.001

PLANE_ALIASES = {
    "Front Plane": ("Front Plane", "前视基准面"),
    "Top Plane": ("Top Plane", "上视基准面"),
    "Right Plane": ("Right Plane", "右视基准面"),
}

SOLIDWORKS_TYPELIB = ("{83A33D31-27C5-11CE-BFD4-00400513BB57}", 0, 33, 0)


def _cast_to(obj: Any, interface_name: str) -> Any:
    from win32com.client import CastTo, gencache  # type: ignore

    gencache.GetModuleForTypelib(*SOLIDWORKS_TYPELIB)
    return CastTo(obj, interface_name)


def _com_value(obj: Any, name: str, *args: Any) -> Any:
    member = getattr(obj, name)
    return member(*args) if callable(member) else member


def _empty_callout() -> Any:
    import pythoncom  # type: ignore
    from win32com.client import VARIANT  # type: ignore

    return VARIANT(pythoncom.VT_DISPATCH, None)


def _select_by_id(
    model: Any,
    name: str,
    entity_type: str,
    *,
    append: bool = False,
    mark: int = 0,
) -> bool:
    return bool(
        model.Extension.SelectByID2(
            name, entity_type, 0.0, 0.0, 0.0, append, mark, _empty_callout(), 0
        )
    )


def select_plane(model: Any, plane_name: str) -> str:
    model.ClearSelection2(True)
    candidates = PLANE_ALIASES.get(plane_name, (plane_name,))
    for candidate in candidates:
        if _select_by_id(model, candidate, "PLANE"):
            return candidate
    raise RuntimeError(f"Could not select plane: {plane_name}")


def rename_feature(feature: Any, name: str) -> Any:
    if feature is None:
        raise RuntimeError(f"SolidWorks returned no feature for {name}")
    feature.Name = name
    return feature


def _last_feature(model: Any) -> Any:
    errors: list[str] = []
    for method_name in ("FeatureByPositionReverse", "IFeatureByPositionReverse"):
        try:
            feature = _com_value(model, method_name, 0)
            if feature is not None:
                return feature
        except Exception as exc:
            errors.append(f"{method_name}: {exc}")
    raise RuntimeError("Could not resolve final feature; " + "; ".join(errors))


def _point3(values: Iterable[float]) -> tuple[float, float, float]:
    data = tuple(float(value) for value in values)
    if len(data) == 2:
        return data[0] * MM, data[1] * MM, 0.0
    if len(data) == 3:
        return data[0] * MM, data[1] * MM, data[2] * MM
    raise RuntimeError("point must have two or three coordinates")


def _create_spline(manager: Any, payload: array.array[float]) -> Any:
    """Create a 2D spline across early and current late-bound COM bindings."""
    point_data = tuple(payload)
    errors: list[str] = []
    try:
        import pythoncom  # type: ignore
        from win32com.client import VARIANT  # type: ignore

        status = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None)
        segment = manager.CreateSpline3(point_data, None, None, False, status)
        if segment is not None:
            return segment
        errors.append("CreateSpline3 returned null")
    except Exception as exc:
        errors.append(f"CreateSpline3: {exc}")
    try:
        segment = manager.CreateSpline2(point_data, False)
        if segment is not None:
            return segment
        errors.append("CreateSpline2 returned null")
    except Exception as exc:
        errors.append(f"CreateSpline2: {exc}")
    try:
        segment = manager.CreateSpline(point_data)
        if segment is not None:
            return segment
        errors.append("CreateSpline returned null")
    except Exception as exc:
        errors.append(f"CreateSpline: {exc}")
    raise RuntimeError("; ".join(errors))


def _segment_endpoint(segment: Any, kind: str, at_start: bool) -> Any:
    if kind == "equation_spline":
        candidates: list[Any] = []
        errors: list[str] = []
        try:
            for interface_name in ("SketchSpline", "ISketchSpline"):
                try:
                    candidates.append(_cast_to(segment, interface_name))
                except Exception as exc:
                    errors.append(f"CastTo({interface_name}): {exc}")
        except Exception as exc:
            errors.append(f"CastTo import: {exc}")
        candidates.append(segment)
        for candidate in candidates:
            try:
                points = _com_value(candidate, "GetPoints2") or []
                if not points:
                    continue
                point = points[0] if at_start else points[-1]
                while isinstance(point, tuple) and len(point) == 1:
                    point = point[0]
                if not (
                    isinstance(point, tuple)
                    and len(point) == 3
                    and all(isinstance(value, (int, float)) for value in point)
                ):
                    return point
                errors.append("GetPoints2 returned coordinate tuples instead of ISketchPoint objects")
            except Exception as exc:
                errors.append(f"GetPoints2: {exc}")
        raise RuntimeError("could not resolve equation spline endpoint; " + "; ".join(errors))
    method_names = (
        ("GetStartPoint2", "IGetStartPoint2", "GetStartPoint")
        if at_start else
        ("GetEndPoint2", "IGetEndPoint2", "GetEndPoint")
    )
    errors: list[str] = []
    candidates: list[Any] = []
    try:
        interface_names = ("SketchLine", "ISketchLine") if kind == "line" else ("SketchArc", "ISketchArc")
        for interface_name in interface_names:
            try:
                candidates.append(_cast_to(segment, interface_name))
            except Exception as exc:
                errors.append(f"CastTo({interface_name}): {exc}")
    except Exception as exc:
        errors.append(f"CastTo import: {exc}")
    candidates.append(segment)
    for candidate in candidates:
        for method_name in method_names:
            try:
                point = _com_value(candidate, method_name)
                if point is not None:
                    while isinstance(point, tuple) and len(point) == 1:
                        point = point[0]
                    if (
                        isinstance(point, tuple)
                        and len(point) == 3
                        and all(isinstance(value, (int, float)) for value in point)
                    ):
                        errors.append(f"{method_name} returned coordinates instead of ISketchPoint")
                        continue
                    return point
            except Exception as exc:
                errors.append(f"{method_name}: {exc}")
    raise RuntimeError("could not resolve sketch endpoint; " + "; ".join(errors))


def _select_sketch_point(point: Any, append: bool, select_data: Any) -> bool:
    errors: list[str] = []
    candidates = [point]
    try:
        for interface_name in ("SketchPoint", "ISketchPoint"):
            try:
                candidates.append(_cast_to(point, interface_name))
            except Exception as exc:
                errors.append(f"CastTo({interface_name}): {exc}")
    except Exception as exc:
        errors.append(f"CastTo import: {exc}")
    for candidate in candidates:
        for method_name, args in (("Select4", (append, select_data)), ("Select", (append,))):
            try:
                return bool(_com_value(candidate, method_name, *args))
            except Exception as exc:
                errors.append(f"{method_name}: {exc}")
    shape = (
        f"tuple(len={len(point)}, types={[type(item).__name__ for item in point]})"
        if isinstance(point, tuple) else type(point).__name__
    )
    raise RuntimeError(f"could not select sketch point ({shape}); " + "; ".join(errors))


def _weld_equation_endpoints(model: Any, manager: Any, records: list[dict[str, Any]]) -> None:
    """Make equation-curve junctions topologically coincident when coordinates match."""
    merge_errors: list[str] = []
    try:
        active_sketch = _com_value(manager, "ActiveSketch")
        sketch_candidates = [active_sketch]
        try:
            for interface_name in ("Sketch", "ISketch"):
                try:
                    sketch_candidates.append(_cast_to(active_sketch, interface_name))
                except Exception as exc:
                    merge_errors.append(f"CastTo({interface_name}): {exc}")
        except Exception as exc:
            merge_errors.append(f"CastTo import: {exc}")
        for sketch in sketch_candidates:
            try:
                if sketch is not None and bool(sketch.MergePoints(1e-6)):
                    model.ClearSelection2(True)
                    return
                merge_errors.append("MergePoints returned false")
            except Exception as exc:
                merge_errors.append(f"MergePoints: {exc}")
    except Exception as exc:
        merge_errors.append(f"MergePoints: {exc}")
    tolerance_mm = 1e-5
    for left_index, left in enumerate(records):
        for right in records[left_index + 1:]:
            if "equation_spline" not in {left["kind"], right["kind"]}:
                continue
            dx = float(left["coord"][0]) - float(right["coord"][0])
            dy = float(left["coord"][1]) - float(right["coord"][1])
            if math.hypot(dx, dy) > tolerance_mm:
                continue
            try:
                try:
                    model.ClearSelection2(True)
                except Exception as exc:
                    raise RuntimeError(f"ClearSelection2 failed: {exc}") from exc
                # The obsolete one-argument ISketchPoint::Select path is kept
                # as a compatibility fallback because this host's late-bound
                # SelectionManager does not expose CreateSelectData.
                select_data = None
                if not _select_sketch_point(left["point"], False, select_data):
                    raise RuntimeError("could not select first endpoint")
                if not _select_sketch_point(right["point"], True, select_data):
                    raise RuntimeError("could not select second endpoint")
                try:
                    model.SketchAddConstraints("sgCOINCIDENT")
                except Exception as exc:
                    raise RuntimeError(f"SketchAddConstraints failed: {exc}") from exc
            except Exception as exc:
                raise RuntimeError(
                    f"could not weld equation endpoint at {left['coord']}: {exc}; "
                    f"bulk_merge={merge_errors}"
                ) from exc
    model.ClearSelection2(True)


def create_sketch(model: Any, name: str, plane: str, entities: list[dict[str, Any]]) -> Any:
    try:
        select_plane(model, plane)
    except Exception as exc:
        raise RuntimeError(f"select_plane failed: {exc}") from exc
    try:
        manager = model.SketchManager
    except Exception as exc:
        raise RuntimeError(f"get_sketch_manager failed: {exc}") from exc
    try:
        # InsertSketch2 is retained because it is the verified late-bound COM
        # path on this host; SketchManager.InsertSketch is not always exposed.
        model.InsertSketch2(True)
    except Exception as exc:
        raise RuntimeError(f"open_sketch failed: {exc}") from exc
    try:
        endpoint_records: list[dict[str, Any]] = []
        needs_equation_weld = any(entity.get("kind") == "equation_spline" for entity in entities)
        previous_auto_solve: bool | None = None
        previous_add_to_db: bool | None = None
        previous_display_when_added: bool | None = None
        try:
            previous_auto_solve = bool(manager.AutoSolve)
            manager.AutoSolve = False
        except Exception:
            previous_auto_solve = None
        try:
            previous_add_to_db = bool(manager.AddToDB)
            previous_display_when_added = bool(manager.DisplayWhenAdded)
            manager.AddToDB = True
            manager.DisplayWhenAdded = False
        except Exception:
            previous_add_to_db = None
            previous_display_when_added = None
        for entity_index, entity in enumerate(entities):
            kind = entity["kind"]
            try:
                if kind == "line":
                    start = _point3(entity["start"])
                    end = _point3(entity["end"])
                    segment = manager.CreateLine(*start, *end)
                    if segment is not None and entity.get("construction", False):
                        segment.ConstructionGeometry = True
                elif kind == "circle":
                    center = _point3(entity.get("center", (0.0, 0.0)))
                    radius = float(entity["radius_mm"]) * MM
                    segment = manager.CreateCircle(
                        *center,
                        center[0] + radius,
                        center[1],
                        center[2],
                    )
                elif kind == "arc":
                    center = _point3(entity["center"])
                    start = _point3(entity["start"])
                    end = _point3(entity["end"])
                    segment = manager.CreateArc(
                        *center,
                        *start,
                        *end,
                        int(entity.get("direction", 1)),
                    )
                elif kind == "spline":
                    points = entity["points"]
                    payload = array.array("d")
                    for point in points:
                        payload.extend(_point3(point))
                    if entity.get("closed", False):
                        raise RuntimeError("closed splines are not supported by the native 2D spline adapter")
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
                    segment = None
                    for start, end in pairs:
                        segment = manager.CreateLine(*start, *end)
                else:
                    raise RuntimeError(f"Unsupported sketch entity: {kind}")
                if segment is None:
                    raise RuntimeError("SolidWorks returned no sketch segment")
                if (
                    needs_equation_weld
                    and kind in {"line", "arc", "equation_spline"}
                    and "start" in entity
                    and "end" in entity
                ):
                    endpoint_records.extend([
                        {"kind": kind, "coord": entity["start"], "point": _segment_endpoint(segment, kind, True)},
                        {"kind": kind, "coord": entity["end"], "point": _segment_endpoint(segment, kind, False)},
                    ])
            except Exception as exc:
                raise RuntimeError(
                    f"create_entity[{entity_index}] {kind} failed: {exc}"
                ) from exc
        if needs_equation_weld:
            _weld_equation_endpoints(model, manager, endpoint_records)
    finally:
        if "previous_auto_solve" in locals() and previous_auto_solve is not None:
            try:
                manager.AutoSolve = previous_auto_solve
            except Exception:
                pass
        if "previous_display_when_added" in locals() and previous_display_when_added is not None:
            try:
                manager.DisplayWhenAdded = previous_display_when_added
            except Exception:
                pass
        if "previous_add_to_db" in locals() and previous_add_to_db is not None:
            try:
                manager.AddToDB = previous_add_to_db
            except Exception:
                pass
        try:
            model.InsertSketch2(True)
        except Exception as exc:
            raise RuntimeError(f"close_sketch failed: {exc}") from exc
    # Late-bound pywin32 proxies on some releases do not expose
    # ISketch::GetFeature. Once the sketch is closed it is deterministically
    # the final feature in tree order, so resolve and name it there.
    try:
        return rename_feature(_last_feature(model), name)
    except Exception as exc:
        raise RuntimeError(f"name_sketch failed: {exc}") from exc


def boss_extrude(model: Any, name: str, sketch_name: str, depth_mm: float, merge: bool = True) -> Any:
    model.ClearSelection2(True)
    if not _select_by_id(model, sketch_name, "SKETCH"):
        raise RuntimeError(f"Could not select sketch for boss extrusion: {sketch_name}")
    feature = model.FeatureManager.FeatureExtrusion3(
        True, False, True, 0, 0, depth_mm * MM, 0.0,
        False, False, False, False, 0.0, 0.0,
        False, False, False, False, merge, False, True,
        0, 0.0, False,
    )
    if feature is None:
        diagnostics = _sketch_profile_diagnostics(model, sketch_name, 3)
        raise RuntimeError(
            f"SolidWorks returned no feature for {name}; sketch_profile={diagnostics}"
        )
    return rename_feature(feature, name)


def boss_revolve(
    model: Any,
    name: str,
    sketch_name: str,
    axis_name: str | None = None,
    axis_segment: str | None = None,
    angle_deg: float = 360.0,
    merge: bool = True,
) -> tuple[Any, str]:
    if (axis_name is None) == (axis_segment is None):
        raise RuntimeError("boss_revolve requires exactly one axis strategy")

    def select_inputs(axis_mark: int) -> None:
        model.ClearSelection2(True)
        if axis_segment is not None:
            segment_name = axis_segment if "@" in axis_segment else f"{axis_segment}@{sketch_name}"
            if not _select_by_id(model, segment_name, "EXTSKETCHSEGMENT", mark=4):
                raise RuntimeError(f"Could not select sketch-segment revolve axis: {segment_name}")
            if not _select_by_id(model, sketch_name, "SKETCH", append=True, mark=0):
                raise RuntimeError(f"Could not select sketch for boss revolve: {sketch_name}")
        else:
            if not _select_by_id(model, sketch_name, "SKETCH", mark=0):
                raise RuntimeError(f"Could not select sketch for boss revolve: {sketch_name}")
            if not _select_by_id(model, axis_name, "AXIS", append=True, mark=axis_mark):
                raise RuntimeError(f"Could not select reference-axis revolve axis: {axis_name}")

    attempts: list[str] = []
    select_inputs(4 if axis_segment is not None else 16)
    try:
        feature = model.FeatureManager.FeatureRevolve2(
            True, True, False, False, False, False,
            0, 0, math.radians(angle_deg), 0.0,
            False, False, 0.0, 0.0,
            0, 0.0, 0.0,
            bool(merge), True, True,
        )
    except Exception as exc:
        feature = None
        attempts.append(f"FeatureRevolve2 raised {type(exc).__name__}: {exc}")
    if feature is not None:
        return rename_feature(feature, name), "FeatureRevolve2"
    attempts.append("FeatureRevolve2 returned no feature")

    # Keep only the API-version compatibility fallback. Axis selection is not
    # changed silently; it remains the explicit strategy declared in the graph.
    select_inputs(4)
    try:
        feature = model.FeatureManager.FeatureRevolve(
            math.radians(angle_deg), False, 0.0, 0, 0,
            bool(merge), True, True,
        )
    except Exception as exc:
        feature = None
        attempts.append(f"FeatureRevolve raised {type(exc).__name__}: {exc}")
    if feature is None:
        attempts.append("FeatureRevolve returned no feature")
        diagnostics = _sketch_profile_diagnostics(model, sketch_name, 4)
        raise RuntimeError(
            f"SolidWorks could not create {name}; axis_strategy="
            f"{'sketch_segment' if axis_segment is not None else 'reference_axis'}; "
            f"attempts={attempts}; sketch_profile={diagnostics}"
        )
    return rename_feature(feature, name), "FeatureRevolve"


def _sketch_profile_diagnostics(model: Any, sketch_name: str, feature_type: int) -> dict[str, Any]:
    """Return SolidWorks' own Check Sketch for Feature Usage result."""
    result: dict[str, Any] = {"feature_type": feature_type}
    try:
        model.ClearSelection2(True)
        result["selected"] = _select_by_id(model, sketch_name, "SKETCH")
        selected = model.SelectionManager.GetSelectedObject6(1, -1)
        candidates = [selected]
        try:
            specific = _com_value(selected, "GetSpecificFeature2")
            if specific is not None:
                candidates.insert(0, specific)
        except Exception:
            pass
        import pythoncom  # type: ignore
        from win32com.client import VARIANT  # type: ignore

        open_count = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        closed_count = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        check_errors: list[str] = []
        for candidate in candidates:
            try:
                result["status"] = int(
                    candidate.CheckFeatureUse(feature_type, open_count, closed_count)
                )
                break
            except Exception as exc:
                check_errors.append(f"{type(exc).__name__}: {exc}")
        else:
            raise RuntimeError("; ".join(check_errors))
        result["open_count"] = int(open_count.value)
        result["closed_count"] = int(closed_count.value)
    except Exception as exc:
        result["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
    return result


def cut_extrude(
    model: Any,
    name: str,
    sketch_name: str,
    *,
    depth_mm: float | None = None,
    through_all: bool = False,
    reverse_direction: bool = False,
) -> Any:
    model.ClearSelection2(True)
    if not _select_by_id(model, sketch_name, "SKETCH"):
        raise RuntimeError(f"Could not select sketch for cut extrusion: {sketch_name}")
    end_condition = 1 if through_all else 0
    depth = (depth_mm or 1.0) * MM
    feature = model.FeatureManager.FeatureCut4(
        True, False, bool(reverse_direction), end_condition, 0, depth, 0.0,
        False, False, False, False, 0.0, 0.0,
        False, False, False, False, False,
        True, True, True, True, False, 0, 0.0, False, False,
    )
    return rename_feature(feature, name)


def reference_axis(model: Any, name: str, planes: list[str]) -> Any:
    if len(planes) != 2:
        raise RuntimeError("A plane-intersection axis requires exactly two planes")
    model.ClearSelection2(True)
    selected: list[str] = []
    for index, plane in enumerate(planes):
        for candidate in PLANE_ALIASES.get(plane, (plane,)):
            if _select_by_id(model, candidate, "PLANE", append=index > 0):
                selected.append(candidate)
                break
        else:
            raise RuntimeError(f"Could not select plane for axis: {plane}")
    if not bool(model.InsertAxis2(True)):
        raise RuntimeError("SolidWorks failed to insert the reference axis")
    # InsertAxis2 returns only a success flag. The inserted reference axis is
    # the final feature in tree order and must be resolved before it can be named.
    return rename_feature(_last_feature(model), name)


def reference_plane_offset(
    model: Any,
    name: str,
    base_plane: str,
    offset_mm: float,
) -> Any:
    select_plane(model, base_plane)
    # InsertRefPlane treats distance as a magnitude. Direction is controlled by
    # the bitmask option swRefPlaneReferenceConstraint_OptionFlip (0x100).
    distance_constraint = 8 | (256 if float(offset_mm) < 0.0 else 0)
    feature = model.FeatureManager.InsertRefPlane(
        distance_constraint,
        abs(float(offset_mm)) * MM,
        0,
        0.0,
        0,
        0.0,
    )
    if feature is None:
        raise RuntimeError(
            f"SolidWorks failed to create offset plane {name} from {base_plane}"
        )
    return rename_feature(feature, name)


def circular_pattern(
    model: Any,
    name: str,
    feature_name: str,
    axis_name: str,
    count: int,
    total_angle_deg: float = 360.0,
    geometry_pattern: bool = True,
) -> Any:
    model.ClearSelection2(True)
    if not _select_by_id(model, axis_name, "AXIS", mark=1):
        raise RuntimeError(f"Could not select circular-pattern axis: {axis_name}")
    if not _select_by_id(model, feature_name, "BODYFEATURE", append=True, mark=4):
        raise RuntimeError(f"Could not select circular-pattern feature: {feature_name}")
    feature = model.FeatureManager.FeatureCircularPattern4(
        int(count), math.radians(total_angle_deg), False, "",
        bool(geometry_pattern), True, False,
    )
    return rename_feature(feature, name)


def _solid_edges(model: Any) -> list[Any]:
    bodies = _com_value(model, "GetBodies2", 0, True) or []
    edges: list[Any] = []
    seen: set[tuple[tuple[float, float, float], tuple[float, float, float]]] = set()
    for body in bodies:
        for edge in (_com_value(body, "GetEdges") or []):
            start_vertex = _com_value(edge, "GetStartVertex")
            end_vertex = _com_value(edge, "GetEndVertex")
            if start_vertex is None or end_vertex is None:
                continue
            start = tuple(float(value) for value in _com_value(start_vertex, "GetPoint"))
            end = tuple(float(value) for value in _com_value(end_vertex, "GetPoint"))
            key = tuple(sorted((tuple(round(value, 10) for value in start), tuple(round(value, 10) for value in end))))
            if key not in seen:
                seen.add(key)
                edges.append(edge)
    return edges


def select_edges_by_geometry(model: Any, selector: dict[str, Any]) -> list[Any]:
    orientation = selector.get("orientation", "any")
    tolerance = float(selector.get("tolerance_mm", 0.05)) * MM
    target_radius = selector.get("radius_mm")
    center_values = selector.get("center_mm", [0.0, 0.0])
    center_x = float(center_values[0]) * MM
    center_y = float(center_values[1]) * MM
    radius_tolerance = float(selector.get("radius_tolerance_mm", 0.1)) * MM
    z_levels = [float(level) * MM for level in selector.get("z_levels_mm", [])]
    selected: list[Any] = []

    for edge in _solid_edges(model):
        start = tuple(float(value) for value in _com_value(_com_value(edge, "GetStartVertex"), "GetPoint"))
        end = tuple(float(value) for value in _com_value(_com_value(edge, "GetEndVertex"), "GetPoint"))
        dx, dy, dz = (end[index] - start[index] for index in range(3))
        if orientation == "axial" and not (abs(dx) <= tolerance and abs(dy) <= tolerance and abs(dz) > tolerance):
            continue
        if orientation == "planar" and abs(dz) > tolerance:
            continue
        radii = [math.hypot(point[0] - center_x, point[1] - center_y) for point in (start, end)]
        if target_radius is not None:
            radius = float(target_radius) * MM
            if any(abs(value - radius) > radius_tolerance for value in radii):
                continue
        if z_levels and not any(
            abs(start[2] - level) <= tolerance and abs(end[2] - level) <= tolerance
            for level in z_levels
        ):
            continue
        selected.append(edge)

    expected_count = selector.get("expected_count")
    if expected_count is not None and len(selected) != int(expected_count):
        raise RuntimeError(
            f"Edge selector expected {expected_count} edges but found {len(selected)}: {selector}"
        )
    if not selected:
        raise RuntimeError(f"Edge selector matched no edges: {selector}")
    return selected


def _select_edges(model: Any, edges: list[Any]) -> None:
    model.ClearSelection2(True)
    select_data = model.SelectionManager.CreateSelectData()
    select_data.Mark = 0
    for edge in edges:
        if not bool(edge.Select4(True, select_data)):
            raise RuntimeError("SolidWorks failed to select an edge")


def edge_fillet(model: Any, name: str, radius_mm: float, selector: dict[str, Any]) -> Any:
    edges = select_edges_by_geometry(model, selector)
    _select_edges(model, edges)
    feature = model.FeatureManager.FeatureFillet(
        195, radius_mm * MM, 0, 0, None, None, None
    )
    return rename_feature(feature, name)


def edge_chamfer(
    model: Any,
    name: str,
    distance_mm: float,
    angle_deg: float,
    selector: dict[str, Any],
) -> Any:
    edges = select_edges_by_geometry(model, selector)
    _select_edges(model, edges)
    feature = model.FeatureManager.InsertFeatureChamfer(
        4, 1, distance_mm * MM, math.radians(angle_deg), 0.0, 0.0, 0.0, 0.0
    )
    return rename_feature(feature, name)


def feature_names(model: Any, limit: int = 500) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    count = min(int(_com_value(model, "GetFeatureCount")), limit)
    # Reverse-position 0 is the final feature. Iterate backwards to preserve
    # model-definition order in the returned audit tree.
    for position in reversed(range(count)):
        feature = _com_value(model, "FeatureByPositionReverse", position)
        result.append({
            "name": str(feature.Name),
            "type": str(_com_value(feature, "GetTypeName2")),
        })
    return result


def rebuild(model: Any, *, full: bool = False, redraw: bool = False) -> None:
    model.ClearSelection2(True)
    if full:
        _com_value(model, "ForceRebuild3", False)
    else:
        _com_value(model, "EditRebuild3")
    if redraw:
        _com_value(model, "GraphicsRedraw2")


def execute_plan(
    model: Any,
    plan: list[dict[str, Any]],
    *,
    full_rebuild: bool = False,
    redraw: bool = False,
) -> list[dict[str, Any]]:
    """Execute a normalized Feature Graph plan against one native part document."""
    results: list[dict[str, Any]] = []
    for step in plan:
        operation = step["operation"]
        name = step["name"]
        try:
            if operation == "new_part":
                results.append({"step": step["step"], "name": name, "operation": operation, "ok": True})
                continue
            if operation == "create_sketch":
                create_sketch(model, name, step["plane"], step["entities"])
            elif operation == "boss_extrude":
                boss_extrude(model, name, step["sketch"], step["depth_mm"], step["merge"])
            elif operation == "boss_revolve":
                _, revolve_backend = boss_revolve(
                    model,
                    name,
                    step["sketch"],
                    step["axis"],
                    step["axis_segment"],
                    step["angle_deg"],
                    step["merge"],
                )
            elif operation == "cut_extrude":
                cut_extrude(
                    model,
                    name,
                    step["sketch"],
                    depth_mm=step["depth_mm"],
                    through_all=step["through_all"],
                    reverse_direction=step["reverse_direction"],
                )
            elif operation == "reference_axis":
                reference_axis(model, name, step["planes"])
            elif operation == "reference_plane_offset":
                reference_plane_offset(
                    model,
                    name,
                    step["base_plane"],
                    step["offset_mm"],
                )
            elif operation == "circular_pattern":
                circular_pattern(
                    model,
                    name,
                    step["feature"],
                    step["axis"],
                    step["count"],
                    step["total_angle_deg"],
                    step["geometry_pattern"],
                )
            elif operation == "fillet":
                edge_fillet(model, name, step["radius_mm"], step["selector"])
            elif operation == "chamfer":
                edge_chamfer(
                    model,
                    name,
                    step["distance_mm"],
                    step["angle_deg"],
                    step["selector"],
                )
            elif operation == "create_sketch_and_extrude":
                raise RuntimeError("Legacy extrude plans are compile-only; use sketch + boss_extrude")
            else:
                raise RuntimeError(f"Unsupported executable operation: {operation}")
        except Exception as exc:
            raise RuntimeError(
                f"Feature step {step['step']} '{name}' ({operation}) failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        result = {"step": step["step"], "name": name, "operation": operation, "ok": True}
        if operation == "boss_revolve":
            result.update(
                axis_strategy=step["axis_strategy"],
                backend=revolve_backend,
            )
        results.append(result)
    rebuild(model, full=full_rebuild, redraw=redraw)
    return results

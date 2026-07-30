from __future__ import annotations

from typing import Any, Iterable

from .contracts import (
    ContractError,
    require_choice,
    require_finite,
    require_index,
    require_positive,
    require_safe_name,
)
from .modeling import _body, _collection_items, _safe_attr, active_part_document


_COUPLING_CODES = {
    "ratio": 1,
    "tangency": 2,
    "curvature": 3,
    "vertices": 4,
}
_CONTINUITY_CODES = {"g0": 0, "g1": 1, "g2": 2}


def _vector3(value: Any, name: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ContractError(f"{name} must be [x, y, z]")
    return (
        require_finite(value[0], f"{name}[0]"),
        require_finite(value[1], f"{name}[1]"),
        require_finite(value[2], f"{name}[2]"),
    )


def _safe_count(collection: Any) -> int:
    try:
        return int(collection.Count)
    except Exception:
        return 0


def _member(obj: Any, name: str) -> Any | None:
    try:
        return getattr(obj, name)
    except Exception:
        return None


def _items(collection: Any) -> Iterable[Any]:
    if collection is None:
        return ()
    try:
        return tuple(_collection_items(collection))
    except Exception:
        return ()


def _named_item(collection: Any, name: str) -> Any | None:
    if collection is None:
        return None
    try:
        return collection.Item(name)
    except Exception:
        pass
    for item in _items(collection):
        if str(_safe_attr(item, "Name", "")).casefold() == name.casefold():
            return item
    return None


def _hybrid_body(part: Any, name: str, *, create: bool = True) -> Any:
    safe_name = require_safe_name(name, "geometrical_set")
    hybrid_bodies = part.HybridBodies
    existing = _named_item(hybrid_bodies, safe_name)
    if existing is not None:
        return existing
    if not create:
        raise RuntimeError(f"geometrical set not found: {safe_name}")
    body = hybrid_bodies.Add()
    body.Name = safe_name
    return body


def _walk_hybrid_body(body: Any) -> Iterable[Any]:
    yield body
    for shape in _items(_member(body, "HybridShapes")):
        yield shape
    for child in _items(_member(body, "HybridBodies")):
        yield from _walk_hybrid_body(child)


def _find_named(part: Any, name: str) -> Any:
    safe_name = require_safe_name(name, "element_name")
    normalized = safe_name.casefold().replace("plane", "").replace("_", "")
    if normalized == "xy":
        return part.OriginElements.PlaneXY
    if normalized == "yz":
        return part.OriginElements.PlaneYZ
    if normalized in {"zx", "xz"}:
        return part.OriginElements.PlaneZX

    for hybrid_body in _items(_member(part, "HybridBodies")):
        for item in _walk_hybrid_body(hybrid_body):
            if str(_safe_attr(item, "Name", "")).casefold() == safe_name.casefold():
                return item

    for body in _items(_member(part, "Bodies")):
        if str(_safe_attr(body, "Name", "")).casefold() == safe_name.casefold():
            return body
        for collection_name in ("Shapes", "Sketches", "HybridShapes"):
            item = _named_item(_member(body, collection_name), safe_name)
            if item is not None:
                return item

    raise RuntimeError(f"CATIA element not found: {safe_name}")


def _reference(part: Any, name: str) -> Any:
    return part.CreateReferenceFromObject(_find_named(part, name))


def _append(part: Any, hybrid_body: Any, feature: Any, name: str) -> Any:
    feature.Name = require_safe_name(name)
    hybrid_body.AppendHybridShape(feature)
    part.InWorkObject = feature
    part.UpdateObject(feature)
    return feature


def _factory_method(factory: Any, name: str) -> Any:
    method = getattr(factory, name, None)
    if method is None:
        raise RuntimeError(f"installed CATIA release does not expose {name}")
    return method


def _continuity_code(value: str, name: str = "continuity") -> int:
    return _CONTINUITY_CODES[require_choice(value, name, _CONTINUITY_CODES)]


def _coupling_code(value: str) -> int:
    return _COUPLING_CODES[require_choice(value, "coupling", _COUPLING_CODES)]


def create_geometrical_set(app: Any, name: str) -> dict[str, Any]:
    document = active_part_document(app)
    part = document.Part
    before = _safe_count(part.HybridBodies)
    body = _hybrid_body(part, name)
    part.Update()
    return {
        "document": document.Name,
        "geometrical_set": body.Name,
        "created": _safe_count(part.HybridBodies) > before,
    }


def surface_capabilities(app: Any) -> dict[str, Any]:
    document = active_part_document(app)
    part = document.Part
    hybrid_factory = part.HybridShapeFactory
    shape_factory = part.ShapeFactory
    hybrid_methods = (
        "AddNewPointCoord",
        "AddNewSpline",
        "AddNewPlaneOffset",
        "AddNewConnect",
        "AddNewLoft",
        "AddNewFill",
        "AddNewJoin",
        "AddNewHealing",
        "AddNewBoundaryOfSurface",
    )
    solid_methods = ("AddNewCloseSurface", "AddNewThickSurface")
    return {
        "document": document.Name,
        "hybrid_shape_factory": {
            method: callable(getattr(hybrid_factory, method, None)) for method in hybrid_methods
        },
        "shape_factory": {
            method: callable(getattr(shape_factory, method, None)) for method in solid_methods
        },
        "continuity": {
            "connect_curve": ["G0", "G1", "G2"],
            "spline_curve_constraint": ["G1", "G2"],
            "loft_boundary": ["G0", "G1"],
            "healing": ["G0", "G1"],
        },
        "quality_checks": {
            "feature_update": True,
            "join_connexity_and_manifold_modes": True,
            "minimum_gap_via_spa_workbench": True,
            "curvature_comb": False,
            "self_intersection": False,
            "note": (
                "V5 Automation exposes feature update, Join topology modes and SPA distance. "
                "Interactive curvature-comb and self-intersection diagnostics are not exposed "
                "as queryable Automation results."
            ),
        },
    }


def _validate_point_records(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(points, list) or not 1 <= len(points) <= 500:
        raise ContractError("points must contain 1..500 point objects")
    result: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, item in enumerate(points):
        if not isinstance(item, dict):
            raise ContractError(f"points[{index}] must be an object")
        name = require_safe_name(item.get("name"), f"points[{index}].name")
        key = name.casefold()
        if key in names:
            raise ContractError(f"duplicate point name: {name}")
        names.add(key)
        if "coordinates" in item:
            coordinates = _vector3(item["coordinates"], f"points[{index}].coordinates")
        else:
            coordinates = _vector3(
                [item.get("x_mm"), item.get("y_mm"), item.get("z_mm")],
                f"points[{index}]",
            )
        result.append({"name": name, "coordinates": coordinates})
    return result


def create_3d_points(
    app: Any,
    points: list[dict[str, Any]],
    geometrical_set: str = "Wireframe",
) -> dict[str, Any]:
    records = _validate_point_records(points)
    document = active_part_document(app)
    part = document.Part
    hybrid_body = _hybrid_body(part, geometrical_set)
    factory = part.HybridShapeFactory
    created = []
    for record in records:
        feature = _factory_method(factory, "AddNewPointCoord")(*record["coordinates"])
        _append(part, hybrid_body, feature, record["name"])
        created.append(record["name"])
    part.Update()
    return {
        "document": document.Name,
        "geometrical_set": hybrid_body.Name,
        "points": created,
        "count": len(created),
        "units": "mm",
    }


def create_spline(
    app: Any,
    name: str,
    point_names: list[str],
    closed: bool = False,
    constraints: list[dict[str, Any]] | None = None,
    geometrical_set: str = "Wireframe",
) -> dict[str, Any]:
    if not isinstance(point_names, list) or not 2 <= len(point_names) <= 500:
        raise ContractError("point_names must contain 2..500 CATIA point names")
    names = [require_safe_name(value, f"point_names[{index}]") for index, value in enumerate(point_names)]
    if closed and len(names) < 3:
        raise ContractError("a closed spline requires at least three points")
    constraints = constraints or []
    if not isinstance(constraints, list) or len(constraints) > len(names):
        raise ContractError("constraints must be a list no longer than point_names")

    document = active_part_document(app)
    part = document.Part
    hybrid_body = _hybrid_body(part, geometrical_set)
    factory = part.HybridShapeFactory
    spline = _factory_method(factory, "AddNewSpline")()
    for point_name in names:
        spline.AddPoint(_reference(part, point_name))
    spline.SetClosing(1 if closed else 0)

    normalized_constraints = []
    for index, item in enumerate(constraints):
        if not isinstance(item, dict):
            raise ContractError(f"constraints[{index}] must be an object")
        point_index = require_index(item.get("point_index"), f"constraints[{index}].point_index")
        if point_index > len(names):
            raise ContractError(f"constraints[{index}].point_index exceeds point_names")
        curve_name = require_safe_name(item.get("curve_name"), f"constraints[{index}].curve_name")
        continuity = require_choice(
            item.get("continuity", "g1"),
            f"constraints[{index}].continuity",
            ("g1", "g2"),
        )
        tension = require_positive(item.get("tension", 1.0), f"constraints[{index}].tension")
        invert = bool(item.get("invert", False))
        spline.SetPointConstraintFromCurve(
            point_index,
            _reference(part, curve_name),
            tension,
            1 if invert else 0,
            _continuity_code(continuity),
        )
        normalized_constraints.append(
            {
                "point_index": point_index,
                "curve": curve_name,
                "continuity": continuity.upper(),
                "tension": tension,
                "invert": invert,
            }
        )

    _append(part, hybrid_body, spline, name)
    part.Update()
    return {
        "document": document.Name,
        "geometrical_set": hybrid_body.Name,
        "spline": spline.Name,
        "point_names": names,
        "closed": closed,
        "constraints": normalized_constraints,
    }


def create_offset_plane(
    app: Any,
    name: str,
    base_plane: str,
    offset_mm: float,
    orientation: bool = False,
    geometrical_set: str = "Reference Geometry",
) -> dict[str, Any]:
    offset = require_finite(offset_mm, "offset_mm")
    document = active_part_document(app)
    part = document.Part
    hybrid_body = _hybrid_body(part, geometrical_set)
    plane = _factory_method(part.HybridShapeFactory, "AddNewPlaneOffset")(
        _reference(part, base_plane),
        offset,
        bool(orientation),
    )
    _append(part, hybrid_body, plane, name)
    part.Update()
    return {
        "document": document.Name,
        "geometrical_set": hybrid_body.Name,
        "plane": plane.Name,
        "base_plane": base_plane,
        "offset_mm": offset,
        "orientation": bool(orientation),
    }


def create_connect_curve(
    app: Any,
    name: str,
    curve1_name: str,
    point1_name: str,
    curve2_name: str,
    point2_name: str,
    continuity1: str = "g1",
    continuity2: str = "g1",
    tension1: float = 1.0,
    tension2: float = 1.0,
    orientation1: int = 1,
    orientation2: int = 1,
    trim: bool = False,
    geometrical_set: str = "Wireframe",
) -> dict[str, Any]:
    if orientation1 not in (-1, 1) or orientation2 not in (-1, 1):
        raise ContractError("orientation1 and orientation2 must be -1 or 1")
    t1 = require_positive(tension1, "tension1")
    t2 = require_positive(tension2, "tension2")
    c1 = require_choice(continuity1, "continuity1", _CONTINUITY_CODES)
    c2 = require_choice(continuity2, "continuity2", _CONTINUITY_CODES)
    document = active_part_document(app)
    part = document.Part
    hybrid_body = _hybrid_body(part, geometrical_set)
    connect = _factory_method(part.HybridShapeFactory, "AddNewConnect")(
        _reference(part, curve1_name),
        _reference(part, point1_name),
        orientation1,
        _continuity_code(c1),
        t1,
        _reference(part, curve2_name),
        _reference(part, point2_name),
        orientation2,
        _continuity_code(c2),
        t2,
        bool(trim),
    )
    _append(part, hybrid_body, connect, name)
    part.Update()
    return {
        "document": document.Name,
        "geometrical_set": hybrid_body.Name,
        "connect_curve": connect.Name,
        "continuity": [c1.upper(), c2.upper()],
        "tension": [t1, t2],
        "trim": bool(trim),
    }


def create_loft(
    app: Any,
    name: str,
    section_names: list[str],
    guide_names: list[str] | None = None,
    closing_point_names: list[str] | None = None,
    section_orientations: list[int] | None = None,
    coupling: str = "ratio",
    context: str = "surface",
    start_tangent_name: str | None = None,
    end_tangent_name: str | None = None,
    smooth_angle_deg: float | None = None,
    smooth_deviation_mm: float | None = None,
    geometrical_set: str = "Surfaces",
) -> dict[str, Any]:
    if not isinstance(section_names, list) or not 2 <= len(section_names) <= 100:
        raise ContractError("section_names must contain 2..100 CATIA curve names")
    sections = [
        require_safe_name(value, f"section_names[{index}]")
        for index, value in enumerate(section_names)
    ]
    guides = guide_names or []
    if not isinstance(guides, list) or len(guides) > 20:
        raise ContractError("guide_names must contain at most 20 CATIA curve names")
    guides = [require_safe_name(value, f"guide_names[{index}]") for index, value in enumerate(guides)]

    closing_points = closing_point_names or []
    if closing_points and len(closing_points) != len(sections):
        raise ContractError("closing_point_names must be empty or match section_names")
    closing_points = [
        require_safe_name(value, f"closing_point_names[{index}]")
        for index, value in enumerate(closing_points)
    ]

    orientations = section_orientations or [1] * len(sections)
    if len(orientations) != len(sections) or any(value not in (-1, 1) for value in orientations):
        raise ContractError("section_orientations must match section_names and contain only -1 or 1")
    coupling_name = require_choice(coupling, "coupling", _COUPLING_CODES)
    context_name = require_choice(context, "context", ("surface", "volume"))

    document = active_part_document(app)
    part = document.Part
    hybrid_body = _hybrid_body(part, geometrical_set)
    loft = _factory_method(part.HybridShapeFactory, "AddNewLoft")()
    loft.SectionCoupling = _coupling_code(coupling_name)
    loft.Context = 0 if context_name == "surface" else 1
    loft.CanonicalDetection = 2

    if smooth_angle_deg is not None:
        loft.SmoothAngleThreshold = require_positive(smooth_angle_deg, "smooth_angle_deg")
        loft.SmoothAngleThresholdActivity = True
    if smooth_deviation_mm is not None:
        loft.SmoothDeviation = require_positive(smooth_deviation_mm, "smooth_deviation_mm")
        loft.SmoothDeviationActivity = True

    for index, section in enumerate(sections):
        closing_point = _reference(part, closing_points[index]) if closing_points else None
        loft.AddSectionToLoft(_reference(part, section), orientations[index], closing_point)
    for guide in guides:
        loft.AddGuide(_reference(part, guide))
    if start_tangent_name:
        loft.SetStartSectionTangent(_reference(part, start_tangent_name))
    if end_tangent_name:
        loft.SetEndSectionTangent(_reference(part, end_tangent_name))

    _append(part, hybrid_body, loft, name)
    part.Update()
    return {
        "document": document.Name,
        "geometrical_set": hybrid_body.Name,
        "loft": loft.Name,
        "context": context_name,
        "sections": sections,
        "guides": guides,
        "closing_points": closing_points,
        "section_orientations": orientations,
        "coupling": coupling_name,
        "boundary_continuity": {
            "start": "G1" if start_tangent_name else "G0",
            "end": "G1" if end_tangent_name else "G0",
            "note": "G2 curve constraints are available through spline/connect tools; HybridShapeLoft Automation exposes tangent boundary surfaces only.",
        },
    }


def create_fill(
    app: Any,
    name: str,
    boundary_names: list[str],
    support_names: list[str | None] | None = None,
    continuities: list[str] | None = None,
    constraints: list[str] | None = None,
    geometrical_set: str = "Surfaces",
) -> dict[str, Any]:
    if not isinstance(boundary_names, list) or not 1 <= len(boundary_names) <= 100:
        raise ContractError("boundary_names must contain 1..100 CATIA boundary curve names")
    boundaries = [
        require_safe_name(value, f"boundary_names[{index}]")
        for index, value in enumerate(boundary_names)
    ]
    supports = support_names or [None] * len(boundaries)
    if len(supports) != len(boundaries):
        raise ContractError("support_names must be empty or match boundary_names")
    normalized_supports = [
        require_safe_name(value, f"support_names[{index}]") if value else None
        for index, value in enumerate(supports)
    ]
    continuity_names = continuities or ["g0"] * len(boundaries)
    if len(continuity_names) != len(boundaries):
        raise ContractError("continuities must be empty or match boundary_names")
    continuity_names = [
        require_choice(value, f"continuities[{index}]", _CONTINUITY_CODES)
        for index, value in enumerate(continuity_names)
    ]
    constraint_names = constraints or []
    if not isinstance(constraint_names, list) or len(constraint_names) > 100:
        raise ContractError("constraints must contain at most 100 CATIA curve or point names")
    constraint_names = [
        require_safe_name(value, f"constraints[{index}]")
        for index, value in enumerate(constraint_names)
    ]

    document = active_part_document(app)
    part = document.Part
    hybrid_body = _hybrid_body(part, geometrical_set)
    fill = _factory_method(part.HybridShapeFactory, "AddNewFill")()
    for index, boundary_name in enumerate(boundaries):
        boundary_ref = _reference(part, boundary_name)
        fill.AddBound(boundary_ref)
        support_name = normalized_supports[index]
        if support_name:
            fill.AddSupportAtBound(boundary_ref, _reference(part, support_name))
            fill.SetBoundaryContinuity(
                _continuity_code(continuity_names[index]),
                index + 1,
            )
        elif continuity_names[index] != "g0":
            raise ContractError(
                f"continuities[{index}] requires support_names[{index}] for G1/G2"
            )
    for constraint_name in constraint_names:
        fill.AppendConstraint(_reference(part, constraint_name))
    fill.AdvancedTolerantMode = 2
    _append(part, hybrid_body, fill, name)
    part.Update()
    return {
        "document": document.Name,
        "geometrical_set": hybrid_body.Name,
        "fill": fill.Name,
        "boundaries": boundaries,
        "supports": normalized_supports,
        "continuities": [value.upper() for value in continuity_names],
        "constraints": constraint_names,
    }


def join_surfaces(
    app: Any,
    name: str,
    element_names: list[str],
    tolerance_mm: float = 0.001,
    angular_tolerance_deg: float = 0.5,
    connex: bool = True,
    manifold: bool = True,
    simplify: bool = True,
    geometrical_set: str = "Surfaces",
) -> dict[str, Any]:
    if not isinstance(element_names, list) or not 2 <= len(element_names) <= 100:
        raise ContractError("element_names must contain 2..100 CATIA surface or curve names")
    elements = [
        require_safe_name(value, f"element_names[{index}]")
        for index, value in enumerate(element_names)
    ]
    tolerance = require_positive(tolerance_mm, "tolerance_mm")
    angular = require_positive(angular_tolerance_deg, "angular_tolerance_deg")
    document = active_part_document(app)
    part = document.Part
    hybrid_body = _hybrid_body(part, geometrical_set)
    join = _factory_method(part.HybridShapeFactory, "AddNewJoin")(
        _reference(part, elements[0]),
        _reference(part, elements[1]),
    )
    for element in elements[2:]:
        join.AddElement(_reference(part, element))
    join.SetConnex(bool(connex))
    join.SetManifold(bool(manifold))
    join.SetSimplify(bool(simplify))
    join.SetDeviation(tolerance)
    join.SetAngularToleranceMode(True)
    join.SetAngularTolerance(angular)
    _append(part, hybrid_body, join, name)
    part.Update()
    return {
        "document": document.Name,
        "geometrical_set": hybrid_body.Name,
        "join": join.Name,
        "elements": elements,
        "tolerance_mm": tolerance,
        "angular_tolerance_deg": angular,
        "connex": bool(connex),
        "manifold": bool(manifold),
        "simplify": bool(simplify),
    }


def heal_surfaces(
    app: Any,
    name: str,
    body_names: list[str],
    continuity: str = "g1",
    distance_objective_mm: float = 0.001,
    merging_distance_mm: float = 0.001,
    tangency_angle_deg: float = 0.5,
    sharpness_angle_deg: float = 0.5,
    geometrical_set: str = "Surfaces",
) -> dict[str, Any]:
    if not isinstance(body_names, list) or not 1 <= len(body_names) <= 100:
        raise ContractError("body_names must contain 1..100 CATIA surface or body names")
    bodies = [require_safe_name(value, f"body_names[{index}]") for index, value in enumerate(body_names)]
    continuity_name = require_choice(continuity, "continuity", ("g0", "g1"))
    distance = require_positive(distance_objective_mm, "distance_objective_mm")
    merging = require_positive(merging_distance_mm, "merging_distance_mm")
    tangency = require_positive(tangency_angle_deg, "tangency_angle_deg")
    sharpness = require_positive(sharpness_angle_deg, "sharpness_angle_deg")
    document = active_part_document(app)
    part = document.Part
    hybrid_body = _hybrid_body(part, geometrical_set)
    healing = _factory_method(part.HybridShapeFactory, "AddNewHealing")(
        _reference(part, bodies[0])
    )
    for body_name in bodies[1:]:
        healing.AddBodyToHeal(_reference(part, body_name))
    healing.Continuity = 0 if continuity_name == "g0" else 1
    healing.SetDistanceObjective(distance)
    healing.SetMergingDistance(merging)
    healing.SetTangencyAngle(tangency)
    healing.SetSharpnessAngle(sharpness)
    _append(part, hybrid_body, healing, name)
    part.Update()
    return {
        "document": document.Name,
        "geometrical_set": hybrid_body.Name,
        "healing": healing.Name,
        "bodies": bodies,
        "continuity": continuity_name.upper(),
        "distance_objective_mm": distance,
        "merging_distance_mm": merging,
        "tangency_angle_deg": tangency,
        "sharpness_angle_deg": sharpness,
    }


def create_boundary(
    app: Any,
    name: str,
    surface_name: str,
    geometrical_set: str = "Wireframe",
) -> dict[str, Any]:
    document = active_part_document(app)
    part = document.Part
    hybrid_body = _hybrid_body(part, geometrical_set)
    boundary = _factory_method(part.HybridShapeFactory, "AddNewBoundaryOfSurface")(
        _reference(part, surface_name)
    )
    _append(part, hybrid_body, boundary, name)
    part.Update()
    return {
        "document": document.Name,
        "geometrical_set": hybrid_body.Name,
        "boundary": boundary.Name,
        "surface": surface_name,
    }


def close_surface(
    app: Any,
    name: str,
    surface_name: str,
    body_name: str = "PartBody",
) -> dict[str, Any]:
    document = active_part_document(app)
    part = document.Part
    body = _body(part, require_safe_name(body_name, "body_name"))
    part.InWorkObject = body
    feature = _factory_method(part.ShapeFactory, "AddNewCloseSurface")(
        _reference(part, surface_name)
    )
    feature.Name = require_safe_name(name)
    part.UpdateObject(feature)
    part.Update()
    return {
        "document": document.Name,
        "body": body.Name,
        "close_surface": feature.Name,
        "surface": surface_name,
    }


def thick_surface(
    app: Any,
    name: str,
    surface_name: str,
    top_offset_mm: float,
    bottom_offset_mm: float = 0.0,
    reverse_direction: bool = False,
    body_name: str = "PartBody",
) -> dict[str, Any]:
    top = require_finite(top_offset_mm, "top_offset_mm")
    bottom = require_finite(bottom_offset_mm, "bottom_offset_mm")
    if top < 0 or bottom < 0 or top + bottom <= 0:
        raise ContractError("top_offset_mm and bottom_offset_mm must be non-negative and not both zero")
    document = active_part_document(app)
    part = document.Part
    body = _body(part, require_safe_name(body_name, "body_name"))
    part.InWorkObject = body
    feature = _factory_method(part.ShapeFactory, "AddNewThickSurface")(
        _reference(part, surface_name),
        1 if reverse_direction else 0,
        top,
        bottom,
    )
    feature.Name = require_safe_name(name)
    part.UpdateObject(feature)
    part.Update()
    return {
        "document": document.Name,
        "body": body.Name,
        "thick_surface": feature.Name,
        "surface": surface_name,
        "top_offset_mm": top,
        "bottom_offset_mm": bottom,
        "reverse_direction": bool(reverse_direction),
    }


def _measurement(measurable: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for source, target in (
        ("GeometryName", "geometry_type"),
        ("Length", "length"),
        ("Area", "area"),
        ("Volume", "volume"),
        ("Perimeter", "perimeter"),
        ("Radius", "radius"),
    ):
        try:
            value = getattr(measurable, source)
            result[target] = value() if callable(value) else value
        except Exception:
            pass
    return result


def check_surface_quality(
    app: Any,
    element_names: list[str],
    gap_pairs: list[list[str]] | None = None,
) -> dict[str, Any]:
    if not isinstance(element_names, list) or not 1 <= len(element_names) <= 100:
        raise ContractError("element_names must contain 1..100 CATIA element names")
    elements = [
        require_safe_name(value, f"element_names[{index}]")
        for index, value in enumerate(element_names)
    ]
    pairs = gap_pairs or []
    if not isinstance(pairs, list) or len(pairs) > 100:
        raise ContractError("gap_pairs must contain at most 100 [element_a, element_b] pairs")
    normalized_pairs = []
    for index, pair in enumerate(pairs):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ContractError(f"gap_pairs[{index}] must be [element_a, element_b]")
        normalized_pairs.append(
            [
                require_safe_name(pair[0], f"gap_pairs[{index}][0]"),
                require_safe_name(pair[1], f"gap_pairs[{index}][1]"),
            ]
        )

    document = active_part_document(app)
    part = document.Part
    spa = document.GetWorkbench("SPAWorkbench")
    rows = []
    references: dict[str, Any] = {}
    for element_name in elements:
        obj = _find_named(part, element_name)
        reference = part.CreateReferenceFromObject(obj)
        references[element_name] = reference
        update_error = None
        try:
            part.UpdateObject(obj)
        except Exception as exc:
            update_error = f"{type(exc).__name__}: {exc}"
        row: dict[str, Any] = {
            "element": element_name,
            "update_ok": update_error is None,
        }
        if update_error:
            row["update_error"] = update_error
        try:
            row["measurement"] = _measurement(spa.GetMeasurable(reference))
        except Exception as exc:
            row["measurement_error"] = f"{type(exc).__name__}: {exc}"
        for method, key in (
            ("GetConnex", "connex_mode"),
            ("GetManifold", "manifold_mode"),
            ("GetDeviation", "deviation"),
            ("GetAngularTolerance", "angular_tolerance"),
        ):
            try:
                row[key] = getattr(obj, method)()
            except Exception:
                pass
        rows.append(row)

    gaps = []
    for first, second in normalized_pairs:
        first_ref = references[first] if first in references else _reference(part, first)
        second_ref = references[second] if second in references else _reference(part, second)
        measurable = spa.GetMeasurable(first_ref)
        gaps.append(
            {
                "elements": [first, second],
                "minimum_distance": measurable.GetMinimumDistance(second_ref),
                "unit_basis": "CATIA document length unit",
            }
        )

    return {
        "document": document.Name,
        "elements": rows,
        "gap_checks": gaps,
        "connexity_assessment": (
            "A Join configured with connex/manifold enforcement must update successfully; "
            "the returned modes report those enforced settings."
        ),
        "curvature_comb": {
            "supported": False,
            "reason": "The installed V5 Automation contract does not expose queryable curvature-comb results.",
        },
        "self_intersection": {
            "supported": False,
            "reason": "The installed V5 Automation contract does not expose a queryable self-intersection diagnostic.",
        },
    }

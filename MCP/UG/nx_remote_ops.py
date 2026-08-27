# -*- coding: utf-8 -*-
"""NXOpen operations invoked through Session.Execute by the remoting client."""

from __future__ import print_function

import io
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
import xml.etree.ElementTree as ET
import zipfile

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities

__version__ = "0.20.1"

MAX_OUTPUT_CHARS = int(os.environ.get("NX_MCP_MAX_OUTPUT_CHARS", "16000"))
WORKSPACE = os.path.abspath(
    os.environ.get(
        "NX_MCP_WORKSPACE", os.path.join(os.path.dirname(__file__), "workspace")
    )
)
LOG_PATH = os.environ.get(
    "NX_MCP_LOG", os.path.join(tempfile.gettempdir(), "nx_mcp_bridge.log")
)
_EXEC_NS = {"__name__": "__nx_mcp_exec__", "__doc__": None}
MACHINE_SOURCE_CONFIG = os.path.abspath(
    os.environ.get(
        "NX_MCP_MACHINE_SOURCE_CONFIG",
        os.path.join(os.path.dirname(__file__), "config", "machine_sources.local"),
    )
)

_MACHINE_WORKSPACE_CONFIRMATION = "CREATE_MACHINE_BUILD_WORKSPACE"
_SMART_MACHINE_KIT_WORKSPACE_CONFIRMATION = "CREATE_SMART_MACHINE_KIT_WORKSPACE"
_MACHINE_WORKSPACE_ACTIVATE_CONFIRMATION = "ACTIVATE_MACHINE_BUILD_WORKSPACE"
_MACHINE_WORKSPACE_RESTORE_CONFIRMATION = "RESTORE_MACHINE_BUILD_RECOVERY_PART"
_MACHINE_GEOMETRY_IMPORT_CONFIRMATION = "IMPORT_MACHINE_COMPONENT_GEOMETRY"
_MACHINE_KINEMATICS_BUILD_CONFIRMATION = "BUILD_MACHINE_KINEMATICS"
_MACHINE_AXIS_PROBE_CONFIRMATION = "PROBE_MACHINE_AXIS_MOTION"
_MACHINE_JUNCTION_RETARGET_CONFIRMATION = "RETARGET_MACHINE_JUNCTIONS"
_MACHINE_KIT_EXPORT_CONFIRMATION = "EXPORT_MACHINE_KIT"
_MACHINE_KIT_IMPORT_CONFIRMATION = "IMPORT_MACHINE_KIT_ISOLATED"
_MACHINE_STATIC_COLLISION_CONFIRMATION = "EVALUATE_STATIC_MACHINE_COLLISIONS"
_MACHINE_KIT_CAM_BIND_CONFIRMATION = "BIND_ISOLATED_MACHINE_KIT_TO_CAM"
_MACHINE_KIT_REFERENCE_LIBREF = "sim06_mill_5ax_tnc"
_MACHINE_REQUIRED_SYSTEM_CLASSES = {
    "BASE": "Machine",
    "SPINDLE": "Turret",
    "TOOL": "PocketOnHead",
    "ATTACH": "SetupElement",
}


def _work_part():
    work = NXOpen.Session.GetSession().Parts.Work
    if work is None or getattr(work, "Tag", 0) == 0:
        raise RuntimeError("No work part is open in NX. Create or open a part first.")
    return work


def _jsonable(value, depth=0):
    if depth > 8:
        return {"repr": repr(value), "type": type(value).__name__}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item, depth + 1) for key, item in value.items()}
    return {"repr": repr(value), "type": type(value).__name__}


def _op_ping(_params):
    session = NXOpen.Session.GetSession()
    work = session.Parts.Work
    return {
        "ok": True,
        "bridge_version": __version__,
        "transport": "dotnet-remoting",
        "python": sys.version,
        "pid": os.getpid(),
        "thread": threading.current_thread().name,
        "application": str(getattr(session, "ApplicationName", "") or ""),
        "endpoint": "http://127.0.0.1:%s/NXOpenSession"
        % os.environ.get("NX_MCP_REMOTING_PORT", "48161"),
        "work_part": (
            getattr(work, "Leaf", None)
            if work is not None and getattr(work, "Tag", 0) != 0
            else None
        ),
        "log": LOG_PATH,
    }


def _op_part_summary(params):
    work = _work_part()
    max_features = int(params.get("max_features", 100))
    if not 1 <= max_features <= 1000:
        raise ValueError("max_features must be between 1 and 1000")
    bodies = list(work.Bodies)
    features = []
    total = 0
    for feature in work.Features:
        total += 1
        if len(features) < max_features:
            features.append(
                {
                    "name": getattr(feature, "Name", None),
                    "journal_id": getattr(feature, "JournalIdentifier", None),
                }
            )
    return {
        "ok": True,
        "name": getattr(work, "Leaf", None),
        "full_path": getattr(work, "FullPath", None),
        "tag": int(work.Tag),
        "body_count": len(bodies),
        "feature_count": total,
        "features": features,
        "features_truncated": total > len(features),
    }


def _op_body_geometry(params):
    import NXOpen.UF

    work = _work_part()
    uf_modl = NXOpen.UF.UFSession.GetUFSession().ModlGeneral
    max_bodies = int(params.get("max_bodies", 50))
    if not 1 <= max_bodies <= 500:
        raise ValueError("max_bodies must be between 1 and 500")
    body_results = []
    all_bodies = list(work.Bodies)
    for body in all_bodies[:max_bodies]:
        edges = list(body.GetEdges())
        faces = list(body.GetFaces())
        vertices = []
        for edge in edges:
            for point in edge.GetVertices():
                vertices.append((float(point.X), float(point.Y), float(point.Z)))
        bounds = None
        bounds_method = None
        try:
            box = [float(value) for value in uf_modl.AskBoundingBox(int(body.Tag))]
            if len(box) == 6:
                minimum = box[:3]
                maximum = box[3:]
                bounds_method = "UF_MODL_ask_bounding_box"
            else:
                raise ValueError("NX returned an invalid bounding box")
        except Exception:
            if vertices:
                minimum = [
                    min(point[axis] for point in vertices) for axis in range(3)
                ]
                maximum = [
                    max(point[axis] for point in vertices) for axis in range(3)
                ]
                bounds_method = "edge_vertices_fallback"
            else:
                minimum = maximum = None
        if minimum is not None:
            bounds = {
                "min": minimum,
                "max": maximum,
                "size": [maximum[axis] - minimum[axis] for axis in range(3)],
            }
        body_results.append(
            {
                "tag": int(body.Tag),
                "name": getattr(body, "Name", None),
                "face_count": len(faces),
                "edge_count": len(edges),
                "vertex_samples": len(vertices),
                "bounds": bounds,
                "bounds_method": bounds_method,
            }
        )
    return {
        "ok": True,
        "part": getattr(work, "Leaf", None),
        "body_count": len(all_bodies),
        "bodies": body_results,
        "bodies_truncated": len(all_bodies) > len(body_results),
    }


def _rounded_vector(values, digits=6):
    return [round(float(value), digits) for value in values]


def _unit_vector(values):
    length = math.sqrt(sum(float(value) ** 2 for value in values))
    if length <= 1.0e-12:
        return [0.0, 0.0, 0.0]
    return [float(value) / length for value in values]


def _stable_topology_id(kind, payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return "%s:%s" % (kind, hashlib.sha1(encoded).hexdigest()[:20])


def _body_from_topology_params(work, params):
    feature_id = params.get("body_feature_id")
    if feature_id is not None and str(feature_id).strip():
        feature = _find_feature(work, feature_id)
        bodies = list(feature.GetBodies()) if hasattr(feature, "GetBodies") else []
        if not bodies:
            raise ValueError("body_feature_id does not own a body")
        body_occurrence = int(params.get("body_occurrence", 0))
        if body_occurrence < 0 or body_occurrence >= len(bodies):
            raise ValueError("body_occurrence is out of range")
        return bodies[body_occurrence], None, feature.JournalIdentifier
    body_index = int(params.get("body_index", 0))
    return _body_by_index(work, body_index), body_index, None


def _topology_records(body):
    import NXOpen.UF

    uf_modeling = NXOpen.UF.UFSession.GetUFSession().Modeling
    faces = []
    face_by_tag = {}
    for index, face in enumerate(body.GetFaces()):
        face_type, point, direction, box, radius, minor_radius, normal_direction = (
            uf_modeling.AskFaceData(int(face.Tag))
        )
        actual_normal = _unit_vector(
            [float(value) * int(normal_direction) for value in direction]
        )
        bounds = [float(value) for value in box]
        spans = [abs(bounds[axis + 3] - bounds[axis]) for axis in range(3)]
        sorted_spans = sorted(spans, reverse=True)
        area_proxy = sorted_spans[0] * sorted_spans[1]
        plane_offset = sum(actual_normal[axis] * float(point[axis]) for axis in range(3))
        identity = {
            "uf_type": int(face_type),
            "normal": _rounded_vector(actual_normal),
            "plane_offset": round(plane_offset, 6),
            "radius": round(float(radius), 6),
            "minor_radius": round(float(minor_radius), 6),
            "bounds": _rounded_vector(bounds),
        }
        stable_id = _stable_topology_id("face", identity)
        record = {
            "index": index,
            "tag": int(face.Tag),
            "journal_id": face.JournalIdentifier,
            "stable_id": stable_id,
            "type_value": int(face.SolidFaceType.value),
            "uf_type": int(face_type),
            "point": [float(value) for value in point],
            "direction": [float(value) for value in direction],
            "normal": actual_normal,
            "plane_offset": plane_offset,
            "bounds": bounds,
            "radius": float(radius),
            "minor_radius": float(minor_radius),
            "normal_direction": int(normal_direction),
            "edge_count": len(list(face.GetEdges())),
            "area_proxy": area_proxy,
            "stable_ref": {
                "kind": "face",
                "stable_id": stable_id,
                "uf_type": int(face_type),
                "normal": _rounded_vector(actual_normal),
                "plane_offset": round(plane_offset, 6),
                "radius": round(float(radius), 6),
                "near_point": _rounded_vector(point),
                "tolerance": 0.01,
            },
        }
        faces.append(record)
        face_by_tag[int(face.Tag)] = stable_id
    edges = []
    for index, edge in enumerate(body.GetEdges()):
        start, end = edge.GetVertices()
        start_values = [float(start.X), float(start.Y), float(start.Z)]
        end_values = [float(end.X), float(end.Y), float(end.Z)]
        ordered = sorted([_rounded_vector(start_values), _rounded_vector(end_values)])
        delta = [end_values[axis] - start_values[axis] for axis in range(3)]
        length = math.sqrt(sum(value * value for value in delta))
        direction = _unit_vector(delta)
        midpoint = [(start_values[axis] + end_values[axis]) * 0.5 for axis in range(3)]
        adjacent_faces = list(edge.GetFaces())
        identity = {
            "type_value": int(edge.SolidEdgeType.value),
            "vertices": ordered,
            "adjacent_faces": sorted(
                face_by_tag.get(int(face.Tag), "") for face in adjacent_faces
            ),
        }
        stable_id = _stable_topology_id("edge", identity)
        edges.append({
            "index": index,
            "tag": int(edge.Tag),
            "journal_id": edge.JournalIdentifier,
            "stable_id": stable_id,
            "type_value": int(edge.SolidEdgeType.value),
            "start": start_values,
            "end": end_values,
            "midpoint": midpoint,
            "direction": direction,
            "length": length,
            "adjacent_face_count": len(adjacent_faces),
            "adjacent_face_stable_ids": identity["adjacent_faces"],
            "stable_ref": {
                "kind": "edge",
                "stable_id": stable_id,
                "type_value": int(edge.SolidEdgeType.value),
                "midpoint": _rounded_vector(midpoint),
                "direction": _rounded_vector(direction),
                "length": round(length, 6),
                "tolerance": 0.01,
            },
        })
    return faces, edges


def _op_body_topology(params):
    work = _work_part()
    body, body_index, body_feature_id = _body_from_topology_params(work, params)
    faces, edges = _topology_records(body)
    return {
        "ok": True,
        "part": work.Leaf,
        "body_index": body_index,
        "body_feature_id": body_feature_id,
        "body_tag": int(body.Tag),
        "edge_count": len(edges),
        "edges": edges,
        "face_count": len(faces),
        "faces": faces,
    }


def _point_distance(first, second):
    return math.sqrt(
        sum((float(first[axis]) - float(second[axis])) ** 2 for axis in range(3))
    )


def _direction_matches(actual, expected, angular_tolerance_deg, oriented):
    actual_unit = _unit_vector(actual)
    expected_unit = _unit_vector(expected)
    dot = sum(actual_unit[index] * expected_unit[index] for index in range(3))
    if not oriented:
        dot = abs(dot)
    threshold = math.cos(math.radians(float(angular_tolerance_deg)))
    return dot >= threshold


def _topology_record_matches(record, selector, kind):
    tolerance = float(selector.get("tolerance", 0.01))
    angular_tolerance = float(selector.get("angular_tolerance_deg", 1.0))
    if "type_value" in selector and int(record["type_value"]) != int(selector["type_value"]):
        return False
    if kind == "face":
        if "uf_type" in selector and int(record["uf_type"]) != int(selector["uf_type"]):
            return False
        if "normal" in selector and not _direction_matches(
            record["normal"], selector["normal"], angular_tolerance, True
        ):
            return False
        if "plane_offset" in selector and abs(
            float(record["plane_offset"]) - float(selector["plane_offset"])
        ) > tolerance:
            return False
        if "point_on_plane" in selector:
            point = _vector3("point_on_plane", selector["point_on_plane"])
            offset = sum(record["normal"][axis] * point[axis] for axis in range(3))
            if abs(offset - float(record["plane_offset"])) > tolerance:
                return False
        if "radius" in selector and abs(
            float(record["radius"]) - float(selector["radius"])
        ) > tolerance:
            return False
        if "edge_count" in selector and int(record["edge_count"]) != int(selector["edge_count"]):
            return False
    else:
        if "direction" in selector and not _direction_matches(
            record["direction"],
            selector["direction"],
            angular_tolerance,
            bool(selector.get("oriented", False)),
        ):
            return False
        if "length" in selector and abs(
            float(record["length"]) - float(selector["length"])
        ) > tolerance:
            return False
        if "adjacent_face_count" in selector and int(record["adjacent_face_count"]) != int(
            selector["adjacent_face_count"]
        ):
            return False
    if "near_point" in selector:
        near_point = _vector3("near_point", selector["near_point"])
        representative = record["point"] if kind == "face" else record["midpoint"]
        maximum_distance = float(selector.get("max_distance", tolerance))
        if _point_distance(representative, near_point) > maximum_distance:
            return False
    return True


def _resolve_topology_object(work, params, kind, selector):
    if kind not in ("face", "edge"):
        raise ValueError("kind must be 'face' or 'edge'")
    if not isinstance(selector, dict):
        raise ValueError("selector must be an object")
    body, body_index, body_feature_id = _body_from_topology_params(work, params)
    faces, edges = _topology_records(body)
    records = faces if kind == "face" else edges
    objects = list(body.GetFaces()) if kind == "face" else list(body.GetEdges())
    stable_id = selector.get("stable_id")
    matches = []
    if stable_id:
        matches = [record for record in records if record["stable_id"] == stable_id]
    if not matches:
        fallback_selector = dict(selector)
        fallback_selector.pop("stable_id", None)
        geometry_keys = {
            "type_value", "uf_type", "normal", "plane_offset", "point_on_plane",
            "radius", "edge_count", "direction", "length", "adjacent_face_count",
            "near_point",
        }
        if stable_id and not any(key in fallback_selector for key in geometry_keys):
            raise ValueError("topology stable_id no longer exists and has no geometry fallback")
        matches = [
            record
            for record in records
            if _topology_record_matches(record, fallback_selector, kind)
        ]
    sort_by = str(selector.get("sort_by", "")).strip().lower()
    reverse = False
    if sort_by in ("largest", "largest_area") and kind == "face":
        matches.sort(key=lambda item: item["area_proxy"], reverse=True)
    elif sort_by in ("longest", "largest_length") and kind == "edge":
        matches.sort(key=lambda item: item["length"], reverse=True)
    elif sort_by == "nearest":
        near_point = _vector3("near_point", selector.get("near_point"))
        matches.sort(
            key=lambda item: _point_distance(
                item["point"] if kind == "face" else item["midpoint"], near_point
            )
        )
    elif sort_by in ("min_x", "min_y", "min_z", "max_x", "max_y", "max_z"):
        axis = {"x": 0, "y": 1, "z": 2}[sort_by[-1]]
        reverse = sort_by.startswith("max")
        key_name = "point" if kind == "face" else "midpoint"
        matches.sort(key=lambda item: item[key_name][axis], reverse=reverse)
    occurrence = int(selector.get("occurrence", 0))
    if occurrence < 0:
        raise ValueError("selector occurrence must not be negative")
    if not matches:
        raise ValueError("topology selector matched no %ss" % kind)
    if occurrence >= len(matches):
        raise ValueError("topology selector occurrence is out of range")
    selected = matches[occurrence]
    return {
        "body": body,
        "body_index": body_index,
        "body_feature_id": body_feature_id,
        "object": objects[selected["index"]],
        "record": selected,
        "matches": matches,
    }


def _op_resolve_topology(params):
    work = _work_part()
    kind = str(params.get("kind", "")).strip().lower()
    selector = params.get("selector")
    resolved = _resolve_topology_object(work, params, kind, selector)
    unique = bool(params.get("unique", True))
    if unique and len(resolved["matches"]) != 1 and "sort_by" not in selector and "occurrence" not in selector:
        raise ValueError(
            "topology selector matched %s %ss; add sort_by or occurrence"
            % (len(resolved["matches"]), kind)
        )
    return {
        "ok": True,
        "part": work.Leaf,
        "kind": kind,
        "body_index": resolved["body_index"],
        "body_feature_id": resolved["body_feature_id"],
        "match_count": len(resolved["matches"]),
        "selected": resolved["record"],
        "matches": resolved["matches"][:50],
        "matches_truncated": len(resolved["matches"]) > 50,
    }


def _op_inspect_feature(params):
    work = _work_part()
    feature = _find_feature(work, params.get("feature_id"))
    parents = list(feature.GetParents())
    children = list(feature.GetChildren())
    bodies = list(feature.GetBodies()) if hasattr(feature, "GetBodies") else []
    return {
        "ok": True,
        "part": work.Leaf,
        "name": feature.Name,
        "journal_id": feature.JournalIdentifier,
        "tag": int(feature.Tag),
        "type": type(feature).__name__,
        "feature_type": getattr(feature, "FeatureType", None),
        "is_out_of_date": bool(feature.IsOutOfDate()),
        "suppressed": bool(feature.Suppressed),
        "expressions": _feature_expression_records(feature),
        "parent_journal_ids": [item.JournalIdentifier for item in parents],
        "child_journal_ids": [item.JournalIdentifier for item in children],
        "body_tags": [int(item.Tag) for item in bodies],
        "error_messages": list(feature.GetFeatureErrorMessages()),
        "warning_messages": list(feature.GetFeatureWarningMessages()),
        "informational_messages": list(feature.GetFeatureInformationalMessages()),
    }


def _op_set_feature_expression(params):
    work = _work_part()
    session = NXOpen.Session.GetSession()
    feature = _find_feature(work, params.get("feature_id"))
    expressions = list(feature.GetExpressions())
    expression_id = params.get("expression_id")
    expression = None
    if isinstance(expression_id, int) and 0 <= expression_id < len(expressions):
        expression = expressions[expression_id]
    else:
        text = str(expression_id or "").strip()
        if text.isdigit() and 0 <= int(text) < len(expressions):
            expression = expressions[int(text)]
        else:
            for item in expressions:
                if text in (
                    str(getattr(item, "Name", "")),
                    str(getattr(item, "JournalIdentifier", "")),
                ):
                    expression = item
                    break
    if expression is None:
        raise ValueError("expression was not found on feature: %s" % expression_id)
    right_hand_side = str(params.get("right_hand_side", "")).strip()
    if not right_hand_side:
        raise ValueError("right_hand_side must be a non-empty NX expression")
    old_record = _sketch_expression_record(expression)
    mark = session.SetUndoMark(
        NXOpen.Session.MarkVisibility.Visible, "MCP set feature expression"
    )
    try:
        expression.RightHandSide = right_hand_side
        update_errors = int(session.UpdateManager.DoUpdate(mark))
        new_record = _sketch_expression_record(expression)
        errors = list(feature.GetFeatureErrorMessages())
        if update_errors or errors or bool(feature.IsOutOfDate()):
            raise RuntimeError(
                "feature update failed: update_errors=%s messages=%s out_of_date=%s"
                % (update_errors, errors, bool(feature.IsOutOfDate()))
            )
        session.SetUndoMarkName(mark, "MCP set feature expression")
    except Exception:
        try:
            session.UndoToMark(mark, None)
        except Exception:
            pass
        raise
    return {
        "ok": True,
        "part": work.Leaf,
        "feature_name": feature.Name,
        "feature_journal_id": feature.JournalIdentifier,
        "old_expression": old_record,
        "new_expression": new_record,
        "update_error_count": update_errors,
        "is_out_of_date": bool(feature.IsOutOfDate()),
        "error_messages": errors,
    }


def _op_rebuild_work_part(_params):
    work = _work_part()
    session = NXOpen.Session.GetSession()
    mark = session.SetUndoMark(
        NXOpen.Session.MarkVisibility.Visible, "MCP rebuild work part"
    )
    update_errors = int(session.UpdateManager.DoUpdate(mark))
    diagnostics = []
    for feature in work.Features:
        errors = list(feature.GetFeatureErrorMessages())
        warnings = list(feature.GetFeatureWarningMessages())
        if errors or warnings or bool(feature.IsOutOfDate()):
            diagnostics.append(
                {
                    "name": feature.Name,
                    "journal_id": feature.JournalIdentifier,
                    "is_out_of_date": bool(feature.IsOutOfDate()),
                    "errors": errors,
                    "warnings": warnings,
                }
            )
    session.SetUndoMarkName(mark, "MCP rebuild work part")
    return {
        "ok": update_errors == 0 and not any(item["errors"] for item in diagnostics),
        "part": work.Leaf,
        "update_error_count": update_errors,
        "diagnostics": diagnostics,
    }


def _op_create_part(params):
    file_name = params.get("file_name")
    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("file_name must be a non-empty string")
    file_name = file_name.strip()
    if os.path.basename(file_name) != file_name or file_name in (".", ".."):
        raise ValueError("file_name must be a plain file name, not a path")
    if not file_name.lower().endswith(".prt"):
        file_name += ".prt"
    units_name = str(params.get("units", "millimeters")).strip().lower()
    if units_name in ("millimeter", "millimeters", "mm"):
        units = NXOpen.Part.Units.Millimeters
    elif units_name in ("inch", "inches", "in"):
        units = NXOpen.Part.Units.Inches
    else:
        raise ValueError("units must be 'millimeters' or 'inches'")
    if not os.path.isdir(WORKSPACE):
        os.makedirs(WORKSPACE)
    path = os.path.abspath(os.path.join(WORKSPACE, file_name))
    if os.path.commonpath([WORKSPACE, path]) != WORKSPACE:
        raise ValueError("part path escapes NX_MCP_WORKSPACE")
    if os.path.exists(path):
        raise IOError("part already exists: %s" % path)
    part = NXOpen.Session.GetSession().Parts.NewDisplay(path, units)
    return {
        "ok": True,
        "name": getattr(part, "Leaf", None),
        "full_path": getattr(part, "FullPath", path),
        "tag": int(part.Tag),
        "units": units_name,
        "workspace": WORKSPACE,
    }


def _op_save_work_part(_params):
    work = _work_part()
    status = work.Save(
        NXOpen.BasePart.SaveComponents.TrueValue,
        NXOpen.BasePart.CloseAfterSave.FalseValue,
    )
    try:
        unsaved = getattr(status, "NumberUnsavedParts", None)
    finally:
        status.Dispose()
    path = getattr(work, "FullPath", None)
    return {
        "ok": True,
        "name": getattr(work, "Leaf", None),
        "full_path": path,
        "number_unsaved_parts": unsaved,
        "file_exists": bool(path and os.path.isfile(path)),
        "file_size": os.path.getsize(path) if path and os.path.isfile(path) else None,
    }


def _workspace_exchange_path(file_name, allowed_extensions, must_exist=False):
    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("file_name must be a non-empty string")
    file_name = file_name.strip()
    if os.path.basename(file_name) != file_name or file_name in (".", ".."):
        raise ValueError("file_name must be a plain file name, not a path")
    extension = os.path.splitext(file_name)[1].lower()
    if extension not in allowed_extensions:
        raise ValueError(
            "file_name extension must be one of: %s"
            % ", ".join(sorted(allowed_extensions))
        )
    if not os.path.isdir(WORKSPACE):
        os.makedirs(WORKSPACE)
    path = os.path.abspath(os.path.join(WORKSPACE, file_name))
    if os.path.commonpath([WORKSPACE, path]) != WORKSPACE:
        raise ValueError("exchange path escapes NX_MCP_WORKSPACE")
    if must_exist and not os.path.isfile(path):
        raise IOError("exchange file does not exist: %s" % path)
    return path


def _set_exchange_object_types(selector, include_curves=True):
    selector.Solids = True
    selector.Surfaces = True
    selector.Curves = bool(include_curves)


def _step_settings_file(application_protocol):
    base = os.environ.get("UGII_BASE_DIR", "")
    candidates = {
        "ap203": os.path.join(base, "STEP203UG", "step203ug.def"),
        "ap214": os.path.join(base, "STEP214UG", "step214ug.def"),
        "ap242": os.path.join(base, "TRANSLATORS", "step242", "step242ug.def"),
        "ap242ed2": os.path.join(base, "TRANSLATORS", "step242", "step242ug.def"),
    }
    path = candidates[application_protocol]
    return path if path and os.path.isfile(path) else None


def _op_export_exchange(params):
    work = _work_part()
    session = NXOpen.Session.GetSession()
    format_name = str(params.get("format", "step")).strip().lower()
    file_name = params.get("file_name")
    overwrite = bool(params.get("overwrite", False))
    include_curves = bool(params.get("include_curves", True))
    builder = None
    if format_name == "step":
        output_path = _workspace_exchange_path(
            file_name, {".stp", ".step"}, must_exist=False
        )
        protocol = str(params.get("application_protocol", "ap242")).strip().lower()
        protocol_values = {
            "ap203": NXOpen.StepCreator.ExportAsOption.Ap203,
            "ap214": NXOpen.StepCreator.ExportAsOption.Ap214,
            "ap242": NXOpen.StepCreator.ExportAsOption.Ap242,
            "ap242ed2": NXOpen.StepCreator.ExportAsOption.Ap242ED2,
        }
        if protocol not in protocol_values:
            raise ValueError(
                "application_protocol must be ap203, ap214, ap242, or ap242ed2"
            )
        builder = session.DexManager.CreateStepCreator()
        builder.ExportAs = protocol_values[protocol]
        if not getattr(work, "FullPath", None) or not os.path.isfile(work.FullPath):
            raise RuntimeError("save the active NX part before STEP export")
        builder.ExportFrom = NXOpen.StepCreator.ExportFromOption.ExistingPart
        builder.InputFile = work.FullPath
        builder.ExportSolidsAndSurfacesAs = (
            NXOpen.StepCreator.ExportSolidsAndSurfacesAsOption.Precise
        )
        builder.FileSaveFlag = False
        builder.LayerMask = "1-256"
        builder.ColorAndLayers = True
        settings_file = _step_settings_file(protocol)
        if settings_file:
            builder.SettingsFile = settings_file
        _set_exchange_object_types(builder.ObjectTypes, include_curves)
    elif format_name == "parasolid":
        output_path = _workspace_exchange_path(
            file_name, {".x_t", ".x_b"}, must_exist=False
        )
        protocol = None
        settings_file = None
        builder = session.DexManager.CreateParasolidExporter()
        builder.ExportFrom = NXOpen.ParasolidExporter.ExportFromOption.DisplayedPart
        builder.ParasolidVersion = (
            NXOpen.ParasolidExporter.ParasolidVersionOption.Current
        )
        builder.FlattenAssembly = bool(params.get("flatten_assembly", False))
        builder.HeaderInformation = True
        _set_exchange_object_types(builder.ObjectTypes, include_curves)
    else:
        raise ValueError("format must be 'step' or 'parasolid'")
    if os.path.exists(output_path) and not overwrite:
        builder.Destroy()
        raise IOError("exchange file already exists: %s" % output_path)
    try:
        builder.ExportDestination = NXOpen.BaseCreator.ExportDestinationOption.NativeFileSystem
        builder.OutputFile = output_path
        builder.ProcessHoldFlag = True
        builder.Commit()
    finally:
        builder.Destroy()
    if not os.path.isfile(output_path):
        raise RuntimeError("NX export completed without creating: %s" % output_path)
    file_size = os.path.getsize(output_path)
    if file_size <= 0:
        raise RuntimeError("NX export created an empty file: %s" % output_path)
    return {
        "ok": True,
        "format": format_name,
        "application_protocol": protocol,
        "part": work.Leaf,
        "output_file": output_path,
        "file_size": file_size,
        "settings_file": settings_file,
        "include_curves": include_curves,
    }


def _op_import_exchange(params):
    work = _work_part()
    session = NXOpen.Session.GetSession()
    file_name = params.get("file_name")
    extension = os.path.splitext(str(file_name))[1].lower()
    requested_format = str(params.get("format", "auto")).strip().lower()
    if requested_format == "auto":
        format_name = "parasolid" if extension in (".x_t", ".x_b") else "step"
    else:
        format_name = requested_format
    builder = None
    settings_file = None
    protocol = None
    if format_name == "step":
        input_path = _workspace_exchange_path(
            file_name, {".stp", ".step"}, must_exist=True
        )
        protocol = str(params.get("application_protocol", "ap242")).strip().lower()
        factories = {
            "ap203": (session.DexManager.CreateStep203Importer, NXOpen.Step203Importer),
            "ap214": (session.DexManager.CreateStep214Importer, NXOpen.Step214Importer),
            "ap242": (session.DexManager.CreateStep242Importer, NXOpen.Step242Importer),
        }
        if protocol not in factories:
            raise ValueError("application_protocol must be ap203, ap214, or ap242")
        factory, importer_type = factories[protocol]
        builder = factory()
        builder.ImportTo = importer_type.ImportToOption.WorkPart
        builder.SewSurfaces = bool(params.get("sew_surfaces", True))
        builder.SimplifyGeometry = bool(params.get("simplify_geometry", True))
        settings_file = _step_settings_file(protocol)
        if settings_file:
            builder.SettingsFile = settings_file
    elif format_name == "parasolid":
        input_path = _workspace_exchange_path(
            file_name, {".x_t", ".x_b"}, must_exist=True
        )
        builder = session.DexManager.CreateParasolidImporter()
        builder.FlattenAssembly = bool(params.get("flatten_assembly", False))
        builder.UseActiveLayer = True
    else:
        raise ValueError("format must be 'auto', 'step', or 'parasolid'")
    before_bodies = len(list(work.Bodies))
    before_features = len(list(work.Features))
    try:
        builder.SetMode(NXOpen.BaseImporter.Mode.NativeFileSystem)
        builder.InputFile = input_path
        builder.OutputFile = ""
        builder.ProcessHoldFlag = True
        _set_exchange_object_types(
            builder.ObjectTypes, bool(params.get("include_curves", True))
        )
        builder.Commit()
    finally:
        builder.Destroy()
    mark = session.SetUndoMark(
        NXOpen.Session.MarkVisibility.Visible, "MCP import exchange"
    )
    update_errors = int(session.UpdateManager.DoUpdate(mark))
    after_bodies = len(list(work.Bodies))
    after_features = len(list(work.Features))
    return {
        "ok": update_errors == 0 and after_bodies > before_bodies,
        "format": format_name,
        "application_protocol": protocol,
        "part": work.Leaf,
        "input_file": input_path,
        "input_file_size": os.path.getsize(input_path),
        "settings_file": settings_file,
        "body_count_before": before_bodies,
        "body_count_after": after_bodies,
        "body_count_added": after_bodies - before_bodies,
        "feature_count_before": before_features,
        "feature_count_after": after_features,
        "feature_count_added": after_features - before_features,
        "update_error_count": update_errors,
    }


def _component_record(component, depth, max_depth):
    position, orientation = component.GetPosition()
    prototype = getattr(component, "Prototype", None)
    record = {
        "name": getattr(component, "Name", None),
        "display_name": getattr(component, "DisplayName", None),
        "journal_id": getattr(component, "JournalIdentifier", None),
        "reference_set": getattr(component, "ReferenceSet", None),
        "tag": int(component.Tag),
        "prototype": getattr(prototype, "FullPath", None)
        or getattr(prototype, "Leaf", None),
        "position": [float(position.X), float(position.Y), float(position.Z)],
        "orientation": [
            float(orientation.Xx), float(orientation.Xy), float(orientation.Xz),
            float(orientation.Yx), float(orientation.Yy), float(orientation.Yz),
            float(orientation.Zx), float(orientation.Zy), float(orientation.Zz),
        ],
    }
    children = list(component.GetChildren())
    record["child_count"] = len(children)
    record["children"] = (
        [_component_record(item, depth + 1, max_depth) for item in children]
        if depth < max_depth
        else []
    )
    record["children_truncated"] = bool(children and depth >= max_depth)
    return record


def _op_inspect_assembly(params):
    work = _work_part()
    max_depth = int(params.get("max_depth", 10))
    if not 0 <= max_depth <= 50:
        raise ValueError("max_depth must be between 0 and 50")
    root = work.ComponentAssembly.RootComponent
    if root is None or getattr(root, "Tag", 0) == 0:
        return {
            "ok": True,
            "part": work.Leaf,
            "is_assembly": False,
            "component_count": 0,
            "root": None,
        }
    root_record = _component_record(root, 0, max_depth)

    def count(record):
        return 1 + sum(count(item) for item in record["children"])

    return {
        "ok": True,
        "part": work.Leaf,
        "is_assembly": True,
        "component_count": max(0, count(root_record) - 1),
        "root": root_record,
    }


def _op_add_component(params):
    work = _work_part()
    file_name = params.get("file_name")
    component_path = _workspace_exchange_path(file_name, {".prt"}, must_exist=True)
    component_name = _safe_object_name(
        params.get("component_name"), os.path.splitext(file_name)[0]
    )
    reference_set = str(params.get("reference_set", "Entire Part")).strip()
    origin = _vector3("origin", params.get("origin"), [0.0, 0.0, 0.0])
    values = params.get("orientation") or [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    if not isinstance(values, (list, tuple)) or len(values) != 9:
        raise ValueError("orientation must contain nine matrix values")
    values = [_finite_float("orientation", item) for item in values]
    matrix = NXOpen.Matrix3x3()
    (
        matrix.Xx, matrix.Xy, matrix.Xz,
        matrix.Yx, matrix.Yy, matrix.Yz,
        matrix.Zx, matrix.Zy, matrix.Zz,
    ) = values
    layer = int(params.get("layer", 1))
    if not 1 <= layer <= 256:
        raise ValueError("layer must be between 1 and 256")
    component, load_status = work.ComponentAssembly.AddComponent(
        component_path,
        reference_set,
        component_name,
        NXOpen.Point3d(*origin),
        matrix,
        layer,
    )
    try:
        unloaded = int(load_status.NumberUnloadedParts)
        load_errors = [
            {
                "part": load_status.GetPartName(index),
                "status": int(load_status.GetStatus(index)),
                "description": load_status.GetStatusDescription(index),
            }
            for index in range(unloaded)
        ]
    finally:
        load_status.Dispose()
    return {
        "ok": unloaded == 0,
        "part": work.Leaf,
        "component": _component_record(component, 0, 0),
        "unloaded_part_count": unloaded,
        "load_errors": load_errors,
    }


def _assembly_components(work):
    root = work.ComponentAssembly.RootComponent
    if root is None or getattr(root, "Tag", 0) == 0:
        return []
    found = []
    pending = list(root.GetChildren())
    while pending:
        component = pending.pop(0)
        found.append(component)
        pending.extend(list(component.GetChildren()))
    return found


def _find_component(work, component_id):
    wanted = str(component_id or "").strip()
    if not wanted:
        raise ValueError("component_id must be a component name or journal id")
    for component in _assembly_components(work):
        if wanted in (
            str(getattr(component, "Name", "")),
            str(getattr(component, "DisplayName", "")),
            str(getattr(component, "JournalIdentifier", "")),
        ):
            return component
    raise ValueError("component was not found: %s" % wanted)


def _matrix3x3(values, label="rotation"):
    if not isinstance(values, (list, tuple)) or len(values) != 9:
        raise ValueError("%s must contain nine matrix values" % label)
    values = [_finite_float(label, item) for item in values]
    matrix = NXOpen.Matrix3x3()
    (
        matrix.Xx, matrix.Xy, matrix.Xz,
        matrix.Yx, matrix.Yy, matrix.Yz,
        matrix.Zx, matrix.Zy, matrix.Zz,
    ) = values
    return matrix


def _op_move_component(params):
    work = _work_part()
    component = _find_component(work, params.get("component_id"))
    translation = _vector3(
        "translation", params.get("translation"), [0.0, 0.0, 0.0]
    )
    rotation = _matrix3x3(
        params.get("rotation")
        or [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    )
    before_position, before_orientation = component.GetPosition()
    work.ComponentAssembly.MoveComponent(
        component, NXOpen.Vector3d(*translation), rotation
    )
    after_position, after_orientation = component.GetPosition()
    return {
        "ok": True,
        "part": work.Leaf,
        "component_name": component.Name,
        "component_journal_id": component.JournalIdentifier,
        "position_before": [
            float(before_position.X), float(before_position.Y), float(before_position.Z)
        ],
        "position_after": [
            float(after_position.X), float(after_position.Y), float(after_position.Z)
        ],
        "translation": translation,
        "orientation_after": [
            float(after_orientation.Xx), float(after_orientation.Xy), float(after_orientation.Xz),
            float(after_orientation.Yx), float(after_orientation.Yy), float(after_orientation.Yz),
            float(after_orientation.Zx), float(after_orientation.Zy), float(after_orientation.Zz),
        ],
    }


def _component_occurrence_face(component, body_index, face_index):
    prototype = component.Prototype
    bodies = list(prototype.Bodies)
    body_index = int(body_index)
    if body_index < 0 or body_index >= len(bodies):
        raise ValueError(
            "component prototype body index %s is out of range for %s bodies"
            % (body_index, len(bodies))
        )
    faces = list(bodies[body_index].GetFaces())
    face_index = int(face_index)
    if face_index < 0 or face_index >= len(faces):
        raise ValueError(
            "component prototype face index %s is out of range for %s faces"
            % (face_index, len(faces))
        )
    occurrence = component.FindOccurrence(faces[face_index])
    if occurrence is None or getattr(occurrence, "Tag", 0) == 0:
        raise RuntimeError("NX could not resolve the component face occurrence")
    return occurrence


def _constraint_record(constraint):
    references = []
    for reference in constraint.GetReferences():
        geometry = reference.GetGeometry()
        movable = reference.GetMovableObject()
        references.append(
            {
                "movable_name": getattr(movable, "Name", None),
                "movable_journal_id": getattr(movable, "JournalIdentifier", None),
                "geometry_journal_id": getattr(geometry, "JournalIdentifier", None),
                "geometry_tag": int(getattr(geometry, "Tag", 0)),
                "uses_axis": bool(reference.GetUsesGeometryAxis()),
                "solver_geometry_type": int(reference.SolverGeometryType.value),
            }
        )
    expression = getattr(constraint, "Expression", None)
    return {
        "journal_id": constraint.JournalIdentifier,
        "tag": int(constraint.Tag),
        "type_value": int(constraint.ConstraintType.value),
        "alignment_value": int(constraint.ConstraintAlignment.value),
        "status_value": int(constraint.GetConstraintStatus().value),
        "suppressed": bool(constraint.Suppressed),
        "expression_rhs": getattr(expression, "RightHandSide", None),
        "references": references,
    }


def _op_inspect_assembly_constraints(_params):
    work = _work_part()
    constraints = [
        _constraint_record(item)
        for item in work.ComponentAssembly.Positioner.Constraints
    ]
    return {
        "ok": True,
        "part": work.Leaf,
        "constraint_count": len(constraints),
        "constraints": constraints,
    }


def _op_add_assembly_constraint(params):
    import NXOpen.Positioning

    work = _work_part()
    session = NXOpen.Session.GetSession()
    positioner = work.ComponentAssembly.Positioner
    kind = str(params.get("type", "fix")).strip().lower()
    type_values = {
        "fix": NXOpen.Positioning.Constraint.Type.Fix,
        "touch": NXOpen.Positioning.Constraint.Type.Touch,
        "fit": NXOpen.Positioning.Constraint.Type.Fit,
        "concentric": NXOpen.Positioning.Constraint.Type.Concentric,
        "distance": NXOpen.Positioning.Constraint.Type.Distance,
        "parallel": NXOpen.Positioning.Constraint.Type.Parallel,
        "perpendicular": NXOpen.Positioning.Constraint.Type.Perpendicular,
        "angle": NXOpen.Positioning.Constraint.Type.Angle,
        "align_lock": NXOpen.Positioning.Constraint.Type.AlignLock,
    }
    if kind not in type_values:
        raise ValueError("unsupported assembly constraint type: %s" % kind)
    alignment_name = str(params.get("alignment", "infer")).strip().lower()
    alignments = {
        "infer": NXOpen.Positioning.Constraint.Alignment.InferAlign,
        "coalign": NXOpen.Positioning.Constraint.Alignment.CoAlign,
        "contraalign": NXOpen.Positioning.Constraint.Alignment.ContraAlign,
    }
    if alignment_name not in alignments:
        raise ValueError("alignment must be infer, coalign, or contraalign")
    first = _find_component(work, params.get("component1_id"))
    second = None
    positioner.BeginAssemblyConstraints()
    try:
        constraint = positioner.CreateConstraint(True)
        constraint.ConstraintType = type_values[kind]
        constraint.ConstraintAlignment = alignments[alignment_name]
        if kind == "fix":
            reference = constraint.CreateConstraintReference(
                first, first, False, False
            )
            reference.SetFixHint(True)
        else:
            second = _find_component(work, params.get("component2_id"))
            use_axis = kind in ("concentric", "align_lock")
            first_face = _component_occurrence_face(
                first,
                params.get("body1_index", 0),
                params.get("face1_index", 0),
            )
            second_face = _component_occurrence_face(
                second,
                params.get("body2_index", 0),
                params.get("face2_index", 0),
            )
            constraint.CreateConstraintReference(
                first, first_face, use_axis, False
            )
            second_reference = constraint.CreateConstraintReference(
                second, second_face, use_axis, False
            )
            if bool(params.get("fix_second", True)):
                second_reference.SetFixHint(True)
            if kind in ("distance", "angle"):
                value = _finite_float("value", params.get("value", 0.0))
                constraint.SetExpression(str(value))
        positioner.SolvePostponedConstraints()
    finally:
        positioner.EndAssemblyConstraints()
    mark = session.SetUndoMark(
        NXOpen.Session.MarkVisibility.Visible, "MCP assembly constraint"
    )
    update_errors = int(session.UpdateManager.DoUpdate(mark))
    record = _constraint_record(constraint)
    record.update(
        {
            "ok": update_errors == 0,
            "part": work.Leaf,
            "type": kind,
            "component1": first.Name,
            "component2": getattr(second, "Name", None),
            "update_error_count": update_errors,
        }
    )
    return record


def _op_extract_face_surface(params):
    work = _work_part()
    body_index = int(params.get("body_index", 0))
    body = _body_by_index(work, body_index)
    faces = _items_by_indices(
        list(body.GetFaces()), params.get("face_indices"), "face"
    )
    associative = bool(params.get("associative", True))
    feature_name = _safe_object_name(
        params.get("feature_name"), "MCP_EXTRACT_SURFACE"
    )
    builder = work.Features.CreateExtractFaceBuilder(NXOpen.Features.Feature.Null)
    try:
        builder.Type = NXOpen.Features.ExtractFaceBuilder.ExtractType.Face
        builder.FaceOption = NXOpen.Features.ExtractFaceBuilder.FaceOptionType.SingleFace
        builder.Associative = associative
        builder.ParentPart = NXOpen.Features.ExtractFaceBuilder.ParentPartType.WorkPart
        builder.SurfaceType = (
            NXOpen.Features.ExtractFaceBuilder.FaceSurfaceType.SameAsOriginal
        )
        builder.HideOriginal = False
        builder.InheritDisplayProperties = True
        builder.FacesToExtract.Add(faces)
        feature = builder.CommitFeature()
        feature.SetName(feature_name)
    finally:
        builder.Destroy()
    return {
        "ok": True,
        "part": work.Leaf,
        "feature_name": feature.Name,
        "feature_journal_id": feature.JournalIdentifier,
        "source_body_index": body_index,
        "source_face_indices": [int(item) for item in params.get("face_indices")],
        "associative": associative,
        "body_count": len(list(work.Bodies)),
    }


def _op_offset_surface(params):
    work = _work_part()
    body_index = int(params.get("body_index", 0))
    body = _body_by_index(work, body_index)
    faces = _items_by_indices(
        list(body.GetFaces()), params.get("face_indices"), "face"
    )
    distance = _finite_float("distance", params.get("distance"))
    if abs(distance) <= 1.0e-12:
        raise ValueError("distance must not be zero")
    tolerance = _finite_positive("tolerance", params.get("tolerance", 0.01))
    feature_name = _safe_object_name(
        params.get("feature_name"), "MCP_OFFSET_SURFACE"
    )
    collector = work.ScCollectors.CreateCollector()
    rule = work.ScRuleFactory.CreateRuleFaceDumb(faces)
    collector.ReplaceRules([rule], False)
    face_set = work.FaceSetOffsets.CreateFaceSet(
        str(abs(distance)), collector, distance < 0.0, 0
    )
    builder = work.Features.CreateOffsetSurfaceBuilder(
        NXOpen.Features.Feature.Null
    )
    try:
        builder.Tolerance = tolerance
        builder.ApproxOption = bool(params.get("approximate", False))
        builder.OutputOption = (
            NXOpen.Features.OffsetSurfaceBuilder.OutputOptionType.OneFeatureForConnectedFaces
        )
        builder.AddFaceSets([face_set])
        feature = builder.CommitFeature()
        feature.SetName(feature_name)
    finally:
        builder.Destroy()
    bodies = list(feature.GetBodies()) if hasattr(feature, "GetBodies") else []
    return {
        "ok": True,
        "part": work.Leaf,
        "feature_name": feature.Name,
        "feature_journal_id": feature.JournalIdentifier,
        "source_body_index": body_index,
        "source_face_indices": [int(item) for item in params.get("face_indices")],
        "distance": distance,
        "tolerance": tolerance,
        "feature_body_tags": [int(item.Tag) for item in bodies],
        "body_count": len(list(work.Bodies)),
    }


def _op_sew_sheet_bodies(params):
    work = _work_part()
    target_index = int(params.get("target_body_index", 0))
    tool_indices = params.get("tool_body_indices")
    if not isinstance(tool_indices, (list, tuple)) or not tool_indices:
        raise ValueError("tool_body_indices must be a non-empty list")
    bodies = list(work.Bodies)
    if target_index < 0 or target_index >= len(bodies):
        raise ValueError("target_body_index is out of range")
    target = bodies[target_index]
    tools = _items_by_indices(bodies, tool_indices, "tool_body")
    if any(int(item.Tag) == int(target.Tag) for item in tools):
        raise ValueError("target body must not also be a tool body")
    tolerance = _finite_positive("tolerance", params.get("tolerance", 0.01))
    feature_name = _safe_object_name(params.get("feature_name"), "MCP_SEW")
    builder = work.Features.CreateSewBuilder(NXOpen.Features.Feature.Null)
    try:
        builder.Type = NXOpen.Features.SewBuilder.Types.Sheet
        builder.BodyPreference = NXOpen.Features.SewBuilder.BodyPreferenceTypes.Sheet
        builder.Tolerance = tolerance
        builder.KeepTarget = bool(params.get("keep_target", False))
        builder.KeepTool = bool(params.get("keep_tools", False))
        builder.OptimizeFaces = True
        builder.TargetBodies.Add(target)
        builder.ToolBodies.Add(tools)
        feature = builder.CommitFeature()
        feature.SetName(feature_name)
        unsewn = list(builder.GetUnsewnBodies())
    finally:
        builder.Destroy()
    output_bodies = list(feature.GetBodies()) if hasattr(feature, "GetBodies") else []
    return {
        "ok": len(unsewn) == 0,
        "part": work.Leaf,
        "feature_name": feature.Name,
        "feature_journal_id": feature.JournalIdentifier,
        "target_body_index": target_index,
        "tool_body_indices": [int(item) for item in tool_indices],
        "tolerance": tolerance,
        "unsewn_body_tags": [int(item.Tag) for item in unsewn],
        "feature_body_tags": [int(item.Tag) for item in output_bodies],
        "body_count": len(list(work.Bodies)),
    }


def _op_trim_sheet_body(params):
    import NXOpen.GeometricUtilities
    import NXOpen.UF

    work = _work_part()
    bodies = list(work.Bodies)
    target_index = int(params.get("target_body_index", 0))
    boundary_indices = params.get("boundary_body_indices")
    if target_index < 0 or target_index >= len(bodies):
        raise ValueError("target_body_index is out of range")
    if not isinstance(boundary_indices, (list, tuple)) or not boundary_indices:
        raise ValueError("boundary_body_indices must be a non-empty list")
    target = bodies[target_index]
    boundaries = _items_by_indices(bodies, boundary_indices, "boundary_body")
    if any(int(item.Tag) == int(target.Tag) for item in boundaries):
        raise ValueError("target body must not also be a boundary body")
    region_point = _vector3("region_point", params.get("region_point"))
    tolerance = _finite_positive("tolerance", params.get("tolerance", 0.01))
    method = str(params.get("method", "keep")).strip().lower()
    if method not in ("keep", "discard"):
        raise ValueError("method must be 'keep' or 'discard'")
    feature_name = _safe_object_name(params.get("feature_name"), "MCP_TRIM_SHEET")
    boundary_faces = []
    for boundary in boundaries:
        faces = list(boundary.GetFaces())
        if not faces:
            raise ValueError("each boundary body must contain at least one face")
        boundary_faces.extend(faces)
    uf_modeling = NXOpen.UF.UFSession.GetUFSession().Modeling
    _, plane_point, direction, _, _, _, normal_direction = uf_modeling.AskFaceData(
        int(boundary_faces[0].Tag)
    )
    side = sum(
        (region_point[index] - float(plane_point[index])) * float(direction[index])
        for index in range(3)
    )
    reverse = side >= 0.0
    if int(normal_direction) < 0:
        reverse = not reverse
    if method == "discard":
        reverse = not reverse
    target_collector = work.ScCollectors.CreateCollector()
    target_rule = work.ScRuleFactory.CreateRuleBodyDumb([target], True)
    target_collector.ReplaceRules([target_rule], False)
    tool_normal = [
        -float(value) if reverse else float(value) for value in direction
    ]
    tool_plane = work.Planes.CreatePlane(
        NXOpen.Point3d(*[float(value) for value in plane_point]),
        NXOpen.Vector3d(*tool_normal),
        NXOpen.SmartObject.UpdateOption.WithinModeling,
    )
    builder = work.Features.CreateTrimBody2Builder(NXOpen.Features.TrimBody2.Null)
    try:
        builder.Tolerance = tolerance
        builder.TargetBodyCollector = target_collector
        builder.BooleanTool.ToolOption = (
            NXOpen.GeometricUtilities.BooleanToolBuilder.BooleanToolType.NewPlane
        )
        builder.BooleanTool.ReverseDirection = False
        builder.BooleanTool.FacePlaneTool.ToolPlane = tool_plane
        feature = builder.CommitFeature()
        feature.SetName(feature_name)
    finally:
        builder.Destroy()
    output_bodies = list(feature.GetBodies()) if hasattr(feature, "GetBodies") else []
    return {
        "ok": True,
        "part": work.Leaf,
        "feature_name": feature.Name,
        "feature_journal_id": feature.JournalIdentifier,
        "target_body_index": target_index,
        "boundary_body_indices": [int(item) for item in boundary_indices],
        "region_point": region_point,
        "method": method,
        "reverse_direction": reverse,
        "tolerance": tolerance,
        "feature_body_tags": [int(item.Tag) for item in output_bodies],
        "body_count": len(list(work.Bodies)),
    }


def _op_create_sheet_metal_tab(params):
    import NXOpen.Features.SheetMetal

    work = _work_part()
    sketch = _find_sketch(work, params.get("sketch_id"))
    thickness = _finite_positive("thickness", params.get("thickness"))
    feature_name = _safe_object_name(
        params.get("feature_name"), "MCP_SHEET_METAL_TAB"
    )
    geometry = list(sketch.GetAllGeometry())
    if not geometry:
        raise ValueError("the sketch does not contain geometry")
    section = work.Sections.CreateSection(0.00095, 0.001, 0.5)
    builder = work.Features.SheetmetalManager.CreateTabFeatureBuilder(
        NXOpen.Features.Feature.Null
    )
    try:
        builder.SetApplicationContext(
            NXOpen.Features.SheetMetal.ApplicationContext.NxSheetMetal
        )
        section.AllowSelfIntersection(False)
        rule = work.ScRuleFactory.CreateRuleCurveDumb(geometry)
        section.AddToSection(
            [rule],
            geometry[0],
            NXOpen.NXObject.Null,
            NXOpen.NXObject.Null,
            NXOpen.Point3d(0.0, 0.0, 0.0),
            NXOpen.Section.Mode.Create,
            False,
        )
        if section.GetNumberOfLoops() < 1:
            raise ValueError("the sketch does not contain a closed loop")
        builder.IsSecondary = False
        builder.Sketch = sketch.Feature
        builder.Section = section
        builder.Thickness.RightHandSide = str(thickness)
        feature = builder.CommitFeature()
        feature.SetName(feature_name)
    finally:
        builder.Destroy()
        section.Destroy()
    bodies = list(feature.GetBodies()) if hasattr(feature, "GetBodies") else []
    return {
        "ok": True,
        "part": work.Leaf,
        "feature_name": feature.Name,
        "feature_journal_id": feature.JournalIdentifier,
        "thickness": thickness,
        "feature_body_tags": [int(item.Tag) for item in bodies],
        "body_count": len(list(work.Bodies)),
    }


def _op_create_sheet_metal_flange(params):
    import NXOpen.Features.SheetMetal

    work = _work_part()
    body_index = int(params.get("body_index", 0))
    body = _body_by_index(work, body_index)
    edge_index = int(params.get("edge_index"))
    edges = list(body.GetEdges())
    if edge_index < 0 or edge_index >= len(edges):
        raise ValueError("edge_index is out of range")
    edge = edges[edge_index]
    length = _finite_positive("length", params.get("length"))
    angle = _finite_float("angle_deg", params.get("angle_deg", 90.0))
    radius = _finite_positive("bend_radius", params.get("bend_radius", 1.5))
    feature_name = _safe_object_name(params.get("feature_name"), "MCP_FLANGE")
    builder = work.Features.SheetmetalManager.CreateAdvancedFlangeBuilder(
        NXOpen.Features.Feature.Null
    )
    step = "application_context"
    try:
        builder.SetApplicationContext(
            NXOpen.Features.SheetMetal.ApplicationContext.NxSheetMetal
        )
        step = "edge_collector"
        edge_rule = work.ScRuleFactory.CreateRuleEdgeDumb([edge])
        builder.Edges.ReplaceRules([edge_rule], False)
        step = "type"
        builder.Type = (
            NXOpen.Features.SheetMetal.AdvancedFlangeBuilder.Types.ByValue
        )
        step = "length_reference"
        builder.LengthReference = (
            NXOpen.Features.SheetMetal.AdvancedFlangeBuilder.LengthReferences.Web
        )
        step = "inset"
        builder.Inset = (
            NXOpen.Features.SheetMetal.AdvancedFlangeBuilder.Insets.MaterialInside
        )
        step = "length"
        builder.Length.RightHandSide = str(length)
        step = "angle"
        builder.Angle.RightHandSide = str(angle)
        step = "global_bend_radius"
        builder.BendOptions.UseGlobalBendRadius = False
        step = "bend_radius"
        builder.BendOptions.BendRadius.RightHandSide = str(radius)
        step = "commit"
        feature = builder.CommitFeature()
        feature.SetName(feature_name)
    except Exception as exc:
        raise RuntimeError("sheet-metal flange %s failed: %s" % (step, exc))
    finally:
        builder.Destroy()
    output_bodies = list(feature.GetBodies()) if hasattr(feature, "GetBodies") else []
    return {
        "ok": True,
        "part": work.Leaf,
        "feature_name": feature.Name,
        "feature_journal_id": feature.JournalIdentifier,
        "body_index": body_index,
        "edge_index": edge_index,
        "edge_journal_id": edge.JournalIdentifier,
        "length": length,
        "angle_deg": angle,
        "bend_radius": radius,
        "feature_body_tags": [int(item.Tag) for item in output_bodies],
        "body_count": len(list(work.Bodies)),
    }


def _op_create_sheet_metal_bend(params):
    import NXOpen.Features.SheetMetal

    work = _work_part()
    selector = params.get("target_face_selector")
    if not isinstance(selector, dict):
        raise ValueError("target_face_selector must be an object")
    resolved = _resolve_topology_object(work, params, "face", selector)
    target_face = resolved["object"]
    sketch = _find_sketch(work, params.get("bend_line_sketch_id"))
    geometry = list(sketch.GetAllGeometry())
    if not geometry:
        raise ValueError("the bend-line sketch does not contain geometry")
    angle = _finite_float("angle_deg", params.get("angle_deg", 90.0))
    radius = _finite_positive("bend_radius", params.get("bend_radius", 1.5))
    direction_name = str(params.get("direction", "normal")).strip().lower()
    if direction_name not in ("normal", "reverse"):
        raise ValueError("direction must be 'normal' or 'reverse'")
    fixed_side_name = str(params.get("fixed_side", "left")).strip().lower()
    if fixed_side_name not in ("left", "right"):
        raise ValueError("fixed_side must be 'left' or 'right'")
    feature_name = _safe_object_name(params.get("feature_name"), "MCP_BEND")
    section = work.Sections.CreateSection(0.00095, 0.001, 0.5)
    rule = work.ScRuleFactory.CreateRuleCurveDumb(geometry)
    section.AddToSection(
        [rule],
        geometry[0],
        NXOpen.NXObject.Null,
        NXOpen.NXObject.Null,
        NXOpen.Point3d(0.0, 0.0, 0.0),
        NXOpen.Section.Mode.Create,
        False,
    )
    builder = work.Features.SheetmetalManager.CreateBendFeatureBuilder(
        NXOpen.Features.Feature.Null
    )
    step = "application_context"
    try:
        builder.SetApplicationContext(
            NXOpen.Features.SheetMetal.ApplicationContext.NxSheetMetal
        )
        step = "target_face"
        builder.TargetFace = target_face
        step = "section"
        builder.Section = section
        builder.Sketch = sketch.Feature
        step = "bend_angle"
        builder.SetBendAngle(str(angle))
        step = "bend_options"
        builder.BendOptions.UseGlobalBendRadius = False
        builder.BendOptions.BendRadius.RightHandSide = str(radius)
        builder.BendLocation = (
            NXOpen.Features.SheetMetal.BendBuilder.BendLocationOptions.CenterLine
        )
        builder.Direction = (
            NXOpen.Features.SheetMetal.BendBuilder.BendDirectionOptions.SectionNormalSide
            if direction_name == "normal"
            else NXOpen.Features.SheetMetal.BendBuilder.BendDirectionOptions.SectionReverseNormalSide
        )
        builder.FixedSide = (
            NXOpen.Features.SheetMetal.BendBuilder.FixedSideOptions.SectionSideLeft
            if fixed_side_name == "left"
            else NXOpen.Features.SheetMetal.BendBuilder.FixedSideOptions.SectionSideRight
        )
        builder.ExtendProfile = True
        step = "validate"
        validity = int(builder.ValidateBuilderData())
        if validity != 0:
            raise ValueError("NX bend builder validation failed: %s" % validity)
        step = "commit"
        feature = builder.CommitFeature()
        feature.SetName(feature_name)
    except Exception as exc:
        raise RuntimeError("sheet-metal bend %s failed: %s" % (step, exc))
    finally:
        builder.Destroy()
        section.Destroy()
    output_bodies = list(feature.GetBodies()) if hasattr(feature, "GetBodies") else []
    return {
        "ok": True,
        "part": work.Leaf,
        "feature_name": feature.Name,
        "feature_journal_id": feature.JournalIdentifier,
        "target_face": resolved["record"],
        "bend_line_sketch_id": sketch.JournalIdentifier,
        "angle_deg": angle,
        "bend_radius": radius,
        "direction": direction_name,
        "fixed_side": fixed_side_name,
        "feature_body_tags": [int(item.Tag) for item in output_bodies],
        "body_count": len(list(work.Bodies)),
    }


def _op_create_flat_pattern(params):
    import NXOpen.Features.SheetMetal

    work = _work_part()
    body_index = int(params.get("body_index", 0))
    body = _body_by_index(work, body_index)
    faces = list(body.GetFaces())
    face_index = int(params.get("upward_face_index"))
    if face_index < 0 or face_index >= len(faces):
        raise ValueError("upward_face_index is out of range")
    edges = list(body.GetEdges())
    edge_value = params.get("x_axis_edge_index")
    edge = None
    if edge_value is not None:
        edge_index = int(edge_value)
        if edge_index < 0 or edge_index >= len(edges):
            raise ValueError("x_axis_edge_index is out of range")
        edge = edges[edge_index]
    feature_name = _safe_object_name(params.get("feature_name"), "MCP_FLAT_PATTERN")
    builder = work.Features.SheetmetalManager.CreateFlatPatternBuilder(
        NXOpen.Features.Feature.Null
    )
    try:
        builder.SetApplicationContext(
            NXOpen.Features.SheetMetal.ApplicationContext.NxSheetMetal
        )
        builder.UpwardFace.Value = faces[face_index]
        if edge is not None:
            builder.XAxisEdge.Value = edge
            start, _ = edge.GetVertices()
            builder.ReferenceVertex = NXOpen.Point3d(start.X, start.Y, start.Z)
            builder.Orientation = (
                NXOpen.Features.SheetMetal.FlatSolidBuilder.OrientationType.Edge
            )
        else:
            builder.Orientation = (
                NXOpen.Features.SheetMetal.FlatSolidBuilder.OrientationType.Default
            )
        builder.Associative = bool(params.get("associative", True))
        builder.FixAtTimestamp = False
        builder.KeepFlatSolidExternal = False
        feature = builder.CommitFeature()
        feature.SetName(feature_name)
    finally:
        builder.Destroy()
    output_bodies = list(feature.GetBodies()) if hasattr(feature, "GetBodies") else []
    return {
        "ok": True,
        "part": work.Leaf,
        "feature_name": feature.Name,
        "feature_journal_id": feature.JournalIdentifier,
        "flat_pattern_view_name": getattr(feature, "Name", feature_name),
        "body_index": body_index,
        "upward_face_index": face_index,
        "x_axis_edge_index": int(edge_value) if edge_value is not None else None,
        "associative": bool(params.get("associative", True)),
        "feature_body_tags": [int(item.Tag) for item in output_bodies],
        "body_count": len(list(work.Bodies)),
    }


def _op_export_flat_pattern_dxf(params):
    import NXOpen.Features.SheetMetal

    work = _work_part()
    feature = _find_feature(work, params.get("flat_pattern_id"))
    path = _workspace_exchange_path(params.get("file_name"), {".dxf"})
    overwrite = bool(params.get("overwrite", False))
    if os.path.exists(path):
        if not overwrite:
            raise IOError("DXF output already exists: %s" % path)
        os.remove(path)
    revision_name = str(params.get("revision", "r2018")).strip().lower()
    revisions = {
        "r12": NXOpen.Features.SheetMetal.ExportFlatPatternBuilder.DxfRevisionType.R12,
        "r2000": NXOpen.Features.SheetMetal.ExportFlatPatternBuilder.DxfRevisionType.R2000,
        "r2007": NXOpen.Features.SheetMetal.ExportFlatPatternBuilder.DxfRevisionType.R2007,
        "r2010": NXOpen.Features.SheetMetal.ExportFlatPatternBuilder.DxfRevisionType.R20102012,
        "r2013": NXOpen.Features.SheetMetal.ExportFlatPatternBuilder.DxfRevisionType.R20132016,
        "r2018": NXOpen.Features.SheetMetal.ExportFlatPatternBuilder.DxfRevisionType.R2018,
    }
    if revision_name not in revisions:
        raise ValueError("revision must be r12, r2000, r2007, r2010, r2013, or r2018")
    builder = work.Features.SheetmetalManager.CreateExportFlatPatternBuilder()
    try:
        builder.Type = NXOpen.Features.SheetMetal.ExportFlatPatternBuilder.FileType.Dxf
        builder.ExportLocation = (
            NXOpen.Features.SheetMetal.ExportFlatPatternBuilder.ExportLocationOptions.Native
        )
        builder.DxfRevision = revisions[revision_name]
        builder.FlatPattern.Value = feature
        builder.OutputFile = path
        builder.OuterMold = True
        builder.InnerMold = False
        builder.InteriorCutout = True
        builder.InteriorFeature = True
        builder.BendUp = bool(params.get("include_bend_lines", True))
        builder.BendDown = bool(params.get("include_bend_lines", True))
        builder.BendTangent = bool(params.get("include_bend_lines", True))
        builder.Commit()
    finally:
        builder.Destroy()
    if not os.path.isfile(path):
        raise IOError("NX did not create the requested DXF file")
    with open(path, "rb") as stream:
        prefix = stream.read(128)
    return {
        "ok": True,
        "part": work.Leaf,
        "flat_pattern_id": feature.JournalIdentifier,
        "file_name": os.path.basename(path),
        "full_path": path,
        "file_size": os.path.getsize(path),
        "revision": revision_name,
        "include_bend_lines": bool(params.get("include_bend_lines", True)),
        "dxf_header_present": b"SECTION" in prefix,
    }


def _op_create_drawing_sheet(params):
    import NXOpen.Drawings

    work = _work_part()
    name = _safe_object_name(params.get("name"), "MCP_SHEET_1")
    size_name = str(params.get("size", "A4")).strip().upper()
    sizes = {
        "A0": NXOpen.Drawings.DrawingSheet.StandardSheetSize.A0,
        "A1": NXOpen.Drawings.DrawingSheet.StandardSheetSize.A1,
        "A2": NXOpen.Drawings.DrawingSheet.StandardSheetSize.A2,
        "A3": NXOpen.Drawings.DrawingSheet.StandardSheetSize.A3,
        "A4": NXOpen.Drawings.DrawingSheet.StandardSheetSize.A4,
    }
    if size_name not in sizes:
        raise ValueError("size must be one of A0, A1, A2, A3, or A4")
    numerator = _finite_positive("scale_numerator", params.get("scale_numerator", 1.0))
    denominator = _finite_positive(
        "scale_denominator", params.get("scale_denominator", 1.0)
    )
    projection_name = str(params.get("projection", "first")).strip().lower()
    if projection_name not in ("first", "third"):
        raise ValueError("projection must be 'first' or 'third'")
    projection = (
        NXOpen.Drawings.DrawingSheet.ProjectionAngleType.FirstAngle
        if projection_name == "first"
        else NXOpen.Drawings.DrawingSheet.ProjectionAngleType.ThirdAngle
    )
    sheet = work.DrawingSheets.InsertSheet(
        name, sizes[size_name], numerator, denominator, projection
    )
    sheet.Open()
    base_view = None
    if bool(params.get("create_base_view", True)):
        view_name = str(params.get("model_view", "Top")).strip() or "Top"
        try:
            modeling_view = work.ModelingViews.FindObject(view_name)
        except Exception:
            modeling_view = work.ModelingViews.WorkView
            view_name = getattr(modeling_view, "Name", "WorkView")
        point = _vector3(
            "view_position", params.get("view_position"), [148.5, 105.0, 0.0]
        )
        base_view = sheet.SheetDraftingViews.CreateBaseView(
            modeling_view,
            NXOpen.Point3d(*point),
            numerator / denominator,
            False,
        )
    return {
        "ok": True,
        "part": work.Leaf,
        "sheet_name": getattr(sheet, "Name", name),
        "sheet_journal_id": sheet.JournalIdentifier,
        "size": size_name,
        "length": float(sheet.Length),
        "height": float(sheet.Height),
        "scale": numerator / denominator,
        "projection": projection_name,
        "base_view_journal_id": (
            base_view.JournalIdentifier if base_view is not None else None
        ),
        "drafting_view_count": len(list(sheet.GetDraftingViews())),
    }


def _op_create_projected_view(params):
    import NXOpen.Drawings

    work = _work_part()
    sheet = work.DrawingSheets.CurrentDrawingSheet
    if sheet is None:
        raise ValueError("no drawing sheet is currently open")
    views = list(sheet.GetDraftingViews())
    if not views:
        raise ValueError("the current drawing sheet contains no drafting views")
    identifier = params.get("parent_view_id")
    parent = None
    if identifier is None or str(identifier).strip() == "":
        parent = views[0]
    else:
        token = str(identifier).strip()
        for index, view in enumerate(views):
            if token in (
                str(index),
                getattr(view, "Name", ""),
                getattr(view, "JournalIdentifier", ""),
            ):
                parent = view
                break
    if parent is None:
        raise ValueError("parent_view_id did not match a drafting view")
    point = _vector3("view_position", params.get("view_position"))
    projected = sheet.SheetDraftingViews.CreateProjectedView(
        parent, NXOpen.Point3d(*point)
    )
    feature_name = _safe_object_name(params.get("view_name"), "MCP_PROJECTED_VIEW")
    try:
        projected.SetName(feature_name)
    except Exception:
        pass
    work.DrawingSheets.RefreshCurrentSheet()
    current_views = list(sheet.GetDraftingViews())
    return {
        "ok": True,
        "part": work.Leaf,
        "sheet_name": getattr(sheet, "Name", None),
        "parent_view_journal_id": parent.JournalIdentifier,
        "view_name": getattr(projected, "Name", feature_name),
        "view_journal_id": projected.JournalIdentifier,
        "view_position": point,
        "drafting_view_count": len(current_views),
    }


def _current_drawing_sheet(work):
    sheet = work.DrawingSheets.CurrentDrawingSheet
    if sheet is None:
        raise ValueError("no drawing sheet is currently open")
    return sheet


def _find_drafting_view(sheet, identifier):
    views = list(sheet.GetDraftingViews())
    if not views:
        raise ValueError("the current drawing sheet contains no drafting views")
    if identifier is None or not str(identifier).strip():
        return views[0]
    token = str(identifier).strip()
    for index, view in enumerate(views):
        if token in (
            str(index),
            getattr(view, "Name", ""),
            getattr(view, "JournalIdentifier", ""),
        ):
            return view
    raise ValueError("view_id did not match a drafting view")


def _op_create_drafting_note(params):
    import NXOpen.Annotations

    work = _work_part()
    sheet = _current_drawing_sheet(work)
    lines = params.get("lines")
    if isinstance(lines, str):
        lines = [lines]
    if not isinstance(lines, (list, tuple)) or not lines:
        raise ValueError("lines must contain at least one text line")
    text_lines = [str(line) for line in lines]
    if any(not line for line in text_lines):
        raise ValueError("note text lines must not be empty")
    position = _vector3("position", params.get("position"))
    note_name = _safe_object_name(params.get("note_name"), "MCP_NOTE")
    builder = work.Annotations.CreateDraftingNoteBuilder(
        NXOpen.Annotations.SimpleDraftingAid.Null
    )
    try:
        builder.Text.TextBlock.SetText(text_lines)
        builder.Origin.OriginPoint = NXOpen.Point3d(*position)
        builder.Origin.Anchor = NXOpen.Annotations.OriginBuilder.AlignmentPosition.TopLeft
        note = builder.Commit()
        note.SetName(note_name)
    finally:
        builder.Destroy()
    work.DrawingSheets.RefreshCurrentSheet()
    return {
        "ok": True,
        "part": work.Leaf,
        "sheet_name": getattr(sheet, "Name", None),
        "note_name": getattr(note, "Name", note_name),
        "note_journal_id": note.JournalIdentifier,
        "position": position,
        "text": list(note.GetText()),
        "note_count": len(list(work.Notes)),
    }


def _op_create_drawing_linear_dimension(params):
    import NXOpen.Annotations

    work = _work_part()
    sheet = _current_drawing_sheet(work)
    view = _find_drafting_view(sheet, params.get("view_id"))
    work.DraftingViews.UpdateViews([view])
    first_selector = params.get("first_edge_selector")
    second_selector = params.get("second_edge_selector")
    first = _resolve_topology_object(work, params, "edge", first_selector)
    second = _resolve_topology_object(work, params, "edge", second_selector)
    if int(first["object"].Tag) == int(second["object"].Tag):
        raise ValueError("the two edge selectors resolved to the same edge")
    method_name = str(params.get("measurement", "horizontal")).strip().lower()
    create_methods = {
        "horizontal": work.Dimensions.CreateHorizontalDimension,
        "vertical": work.Dimensions.CreateVerticalDimension,
        "point_to_point": work.Dimensions.CreateParallelDimension,
        "perpendicular": work.Dimensions.CreatePerpendicularDimension,
    }
    if method_name not in create_methods:
        raise ValueError(
            "measurement must be horizontal, vertical, point_to_point, or perpendicular"
        )
    position = _vector3("position", params.get("position"))
    first_point = _vector3(
        "first_associativity_point",
        params.get("first_associativity_point"),
        first["record"]["midpoint"],
    )
    second_point = _vector3(
        "second_associativity_point",
        params.get("second_associativity_point"),
        second["record"]["midpoint"],
    )
    dimension_name = _safe_object_name(
        params.get("dimension_name"), "MCP_LINEAR_DIMENSION"
    )
    dimension_data = work.Annotations.NewDimensionData()
    first_associativity = work.Annotations.NewAssociativity()
    second_associativity = work.Annotations.NewAssociativity()
    step = "associativity"
    try:
        for associativity, resolved, pick_point in (
            (first_associativity, first, first_point),
            (second_associativity, second, second_point),
        ):
            associativity.FirstObject = resolved["object"]
            associativity.SecondObject = None
            associativity.ObjectView = view
            associativity.PickPoint = NXOpen.Point3d(*pick_point)
            associativity.PointOption = (
                NXOpen.Annotations.AssociativityPointOption.OnCurve
            )
            associativity.LineOption = (
                NXOpen.Annotations.AssociativityLineOption.NotSet
            )
        dimension_data.SetAssociativity(1, [first_associativity])
        dimension_data.SetAssociativity(2, [second_associativity])
        step = "create"
        dimension = create_methods[method_name](
            dimension_data, NXOpen.Point3d(*position)
        )
        dimension.SetName(dimension_name)
    except Exception as exc:
        raise RuntimeError("drawing linear dimension %s failed: %s" % (step, exc))
    finally:
        dimension_data.Dispose()
        first_associativity.Dispose()
        second_associativity.Dispose()
    work.DrawingSheets.RefreshCurrentSheet()
    return {
        "ok": True,
        "part": work.Leaf,
        "sheet_name": getattr(sheet, "Name", None),
        "view_journal_id": view.JournalIdentifier,
        "dimension_name": getattr(dimension, "Name", dimension_name),
        "dimension_journal_id": dimension.JournalIdentifier,
        "computed_size": float(dimension.ComputedSize),
        "measurement": method_name,
        "position": position,
        "first_edge": first["record"],
        "second_edge": second["record"],
        "dimension_count": len(list(work.Dimensions)),
    }


def _op_inspect_drawing_annotations(_params):
    work = _work_part()
    notes = []
    for note in work.Notes:
        notes.append({
            "name": getattr(note, "Name", None),
            "journal_id": note.JournalIdentifier,
            "text": list(note.GetText()),
            "origin": _point_to_list(note.AnnotationOrigin),
        })
    dimensions = []
    for dimension in work.Dimensions:
        dimensions.append({
            "name": getattr(dimension, "Name", None),
            "journal_id": dimension.JournalIdentifier,
            "computed_size": float(dimension.ComputedSize),
            "origin": _point_to_list(dimension.AnnotationOrigin),
        })
    return {
        "ok": True,
        "part": work.Leaf,
        "note_count": len(notes),
        "notes": notes,
        "dimension_count": len(dimensions),
        "dimensions": dimensions,
    }


def _finite_positive(name, value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("%s must be finite and greater than zero" % name)
    return value


def _finite_float(name, value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("%s must be finite" % name)
    return value


def _vector3(name, value, default=None):
    if value is None:
        value = default
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("%s must contain exactly three coordinates" % name)
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result):
        raise ValueError("%s coordinates must be finite" % name)
    return result


def _point_to_list(point):
    return [float(point.X), float(point.Y), float(point.Z)]


def _point2(name, value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("%s must contain exactly two coordinates" % name)
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result):
        raise ValueError("%s coordinates must be finite" % name)
    return result


def _safe_object_name(value, fallback):
    text = str(value or fallback).strip() or fallback
    cleaned = "".join(
        char if (char.isalnum() or char == "_") else "_" for char in text
    )
    cleaned = cleaned or fallback
    if cleaned[0].isdigit():
        cleaned = "MCP_" + cleaned
    return cleaned[:120]


def _body_by_index(work, index):
    bodies = list(work.Bodies)
    index = int(index)
    if index < 0 or index >= len(bodies):
        raise ValueError(
            "body index %s is out of range for %s bodies" % (index, len(bodies))
        )
    return bodies[index]


def _items_by_indices(items, indices, label):
    if not isinstance(indices, (list, tuple)) or not indices:
        raise ValueError("%s_indices must be a non-empty list" % label)
    selected = []
    for raw_index in indices:
        index = int(raw_index)
        if index < 0 or index >= len(items):
            raise ValueError(
                "%s index %s is out of range for %s items"
                % (label, index, len(items))
            )
        selected.append(items[index])
    if len({int(item.Tag) for item in selected}) != len(selected):
        raise ValueError("%s_indices must not contain duplicates" % label)
    return selected


def _principal_plane(name):
    key = str(name or "XY").strip().upper()
    planes = {
        "XY": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        "XZ": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
        "YZ": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
    }
    if key not in planes:
        raise ValueError("plane must be one of XY, XZ, or YZ")
    return key, planes[key]


def _local_to_world(origin, u_axis, v_axis, point):
    uv = _point2("sketch point", point)
    return NXOpen.Point3d(
        origin[0] + uv[0] * u_axis[0] + uv[1] * v_axis[0],
        origin[1] + uv[0] * u_axis[1] + uv[1] * v_axis[1],
        origin[2] + uv[0] * u_axis[2] + uv[1] * v_axis[2],
    )


def _find_sketch(work, identifier=None):
    sketches = list(work.Sketches)
    if identifier is None or not str(identifier).strip():
        if len(sketches) == 1:
            return sketches[0]
        raise ValueError(
            "sketch_id is required when the part does not contain exactly one sketch"
        )
    wanted = str(identifier).strip()
    for sketch in sketches:
        candidates = {
            str(getattr(sketch, "Name", "")),
            str(getattr(sketch, "JournalIdentifier", "")),
            str(
                getattr(
                    getattr(sketch, "Feature", None), "JournalIdentifier", ""
                )
            ),
        }
        if wanted in candidates:
            return sketch
    raise ValueError("sketch was not found: %s" % wanted)


def _find_feature(work, identifier):
    features = list(work.Features)
    if isinstance(identifier, int) and 0 <= identifier < len(features):
        return features[identifier]
    text = str(identifier or "").strip()
    if not text:
        raise ValueError("feature_id must be a feature name, journal id, or index")
    if text.isdigit():
        index = int(text)
        if 0 <= index < len(features):
            return features[index]
    for feature in features:
        if text in (
            str(getattr(feature, "Name", "")),
            str(getattr(feature, "JournalIdentifier", "")),
        ):
            return feature
    raise ValueError("feature was not found: %s" % text)


def _sketch_geometry_record(geometry):
    record = {
        "name": getattr(geometry, "Name", None),
        "journal_id": getattr(geometry, "JournalIdentifier", None),
        "tag": int(getattr(geometry, "Tag", 0)),
        "type": type(geometry).__name__,
    }
    if hasattr(geometry, "StartPoint") and hasattr(geometry, "EndPoint"):
        start = geometry.StartPoint
        end = geometry.EndPoint
        record["start"] = [float(start.X), float(start.Y), float(start.Z)]
        record["end"] = [float(end.X), float(end.Y), float(end.Z)]
    if hasattr(geometry, "Radius"):
        try:
            record["radius"] = float(geometry.Radius)
        except Exception:
            pass
    return record


def _sketch_expression_record(expression):
    units = getattr(expression, "Units", None)
    return {
        "name": getattr(expression, "Name", None),
        "right_hand_side": getattr(expression, "RightHandSide", None),
        "value": float(expression.Value),
        "units": getattr(units, "Name", None) if units is not None else None,
    }


def _feature_expression_records(feature):
    records = []
    for index, expression in enumerate(feature.GetExpressions()):
        record = _sketch_expression_record(expression)
        record.update(
            {
                "index": index,
                "tag": int(expression.Tag),
                "journal_id": getattr(expression, "JournalIdentifier", None),
            }
        )
        records.append(record)
    return records


def _constraint_geometry(geometry, point_type=None):
    item = NXOpen.Sketch.ConstraintGeometry()
    item.Geometry = geometry
    item.PointType = point_type or NXOpen.Sketch.ConstraintPointType.NotSet
    item.SplineDefiningPointIndex = 0
    return item


def _dimension_geometry(geometry, assoc_type):
    item = NXOpen.Sketch.DimensionGeometry()
    item.Geometry = geometry
    item.AssocType = assoc_type
    item.AssocValue = 0
    return item


def _find_length_unit(work):
    last_error = None
    for name in ("MilliMeter", "Millimeter", "mm", "Inch"):
        try:
            return work.UnitCollection.FindObject(name)
        except Exception as exc:
            last_error = exc
    raise RuntimeError("NX length unit could not be resolved: %s" % last_error)


def _op_create_parametric_sketch(params):
    work = _work_part()
    session = NXOpen.Session.GetSession()
    name = _safe_object_name(params.get("name"), "MCP_SKETCH")
    if any(getattr(item, "Name", None) == name for item in work.Sketches):
        raise ValueError("a sketch named %s already exists" % name)
    plane_name, axes = _principal_plane(params.get("plane", "XY"))
    u_axis, v_axis, normal = axes
    origin = _vector3("origin", params.get("origin"), [0.0, 0.0, 0.0])
    geometry_specs = params.get("geometry") or []
    constraint_specs = params.get("constraints") or []
    dimension_specs = params.get("dimensions") or []
    if not isinstance(geometry_specs, list) or not geometry_specs:
        raise ValueError("geometry must be a non-empty list")
    if not isinstance(constraint_specs, list):
        raise ValueError("constraints must be a list")
    if not isinstance(dimension_specs, list):
        raise ValueError("dimensions must be a list")

    mark = session.SetUndoMark(
        NXOpen.Session.MarkVisibility.Visible, "MCP create parametric sketch"
    )
    builder = None
    sketch = None
    try:
        plane = work.Planes.CreatePlane(
            NXOpen.Point3d(origin[0], origin[1], origin[2]),
            NXOpen.Vector3d(normal[0], normal[1], normal[2]),
            NXOpen.SmartObject.UpdateOption.WithinModeling,
        )
        builder = work.Sketches.CreateSketchInPlaceBuilder2(NXOpen.Sketch.Null)
        builder.PlaneReference = plane
        sketch_axis = work.Directions.CreateDirection(
            NXOpen.Point3d(origin[0], origin[1], origin[2]),
            NXOpen.Vector3d(u_axis[0], u_axis[1], u_axis[2]),
            NXOpen.SmartObject.UpdateOption.WithinModeling,
        )
        builder.AxisReference = sketch_axis
        sketch_origin = work.Points.CreatePoint(
            NXOpen.Point3d(origin[0], origin[1], origin[2])
        )
        builder.SketchOrigin = sketch_origin
        builder.PlaneOption = NXOpen.Sketch.PlaneOption.ExistingPlane
        builder.OriginOption = NXOpen.OriginMethod.SpecifyPoint
        builder.MakeOriginAssociative = True
        sketch = builder.Commit()
        builder.Destroy()
        builder = None
        sketch.SetName(name)
        sketch.Activate(NXOpen.Sketch.ViewReorient.FalseValue)

        objects = {}
        local_records = {}
        auto_constraint_specs = []
        sequence = 0
        for spec in geometry_specs:
            if not isinstance(spec, dict):
                raise ValueError("each geometry item must be an object")
            kind = str(spec.get("type", "")).strip().lower()
            base_name = _safe_object_name(spec.get("name"), "G%s" % sequence)
            if base_name in objects:
                raise ValueError("duplicate geometry name: %s" % base_name)
            if kind == "line":
                start_local = _point2("line.start", spec.get("start"))
                end_local = _point2("line.end", spec.get("end"))
                curve = work.Curves.CreateLine(
                    _local_to_world(origin, u_axis, v_axis, start_local),
                    _local_to_world(origin, u_axis, v_axis, end_local),
                )
                curve.SetName("%s_%s" % (name, base_name))
                sketch.AddGeometry(
                    curve, NXOpen.Sketch.InferConstraintsOption.InferNoConstraints
                )
                objects[base_name] = curve
                local_records[base_name] = {
                    "start": start_local,
                    "end": end_local,
                }
                sequence += 1
            elif kind == "rectangle":
                corner = _point2(
                    "rectangle.origin", spec.get("origin", [0.0, 0.0])
                )
                width = _finite_positive("rectangle.width", spec.get("width"))
                height = _finite_positive("rectangle.height", spec.get("height"))
                points = [
                    corner,
                    [corner[0] + width, corner[1]],
                    [corner[0] + width, corner[1] + height],
                    [corner[0], corner[1] + height],
                ]
                line_names = []
                for index in range(4):
                    line_name = "%s_%s" % (base_name, index)
                    curve = work.Curves.CreateLine(
                        _local_to_world(origin, u_axis, v_axis, points[index]),
                        _local_to_world(
                            origin, u_axis, v_axis, points[(index + 1) % 4]
                        ),
                    )
                    curve.SetName("%s_%s" % (name, line_name))
                    sketch.AddGeometry(
                        curve,
                        NXOpen.Sketch.InferConstraintsOption.InferNoConstraints,
                    )
                    objects[line_name] = curve
                    local_records[line_name] = {
                        "start": points[index],
                        "end": points[(index + 1) % 4],
                    }
                    line_names.append(line_name)
                auto_constraint_specs.extend(
                    [
                        {"type": "horizontal", "geometry": line_names[0]},
                        {"type": "vertical", "geometry": line_names[1]},
                        {"type": "horizontal", "geometry": line_names[2]},
                        {"type": "vertical", "geometry": line_names[3]},
                    ]
                )
                for index in range(4):
                    auto_constraint_specs.append(
                        {
                            "type": "coincident",
                            "geometry1": line_names[index],
                            "point1": "end",
                            "geometry2": line_names[(index + 1) % 4],
                            "point2": "start",
                        }
                    )
                sequence += 4
            elif kind in ("circle", "arc"):
                center_local = _point2(
                    "%s.center" % kind, spec.get("center")
                )
                radius = _finite_positive(
                    "%s.radius" % kind, spec.get("radius")
                )
                start_angle = 0.0
                end_angle = 2.0 * math.pi
                if kind == "arc":
                    start_angle = math.radians(
                        _finite_float(
                            "arc.start_angle_deg",
                            spec.get("start_angle_deg", 0.0),
                        )
                    )
                    end_angle = math.radians(
                        _finite_float(
                            "arc.end_angle_deg", spec.get("end_angle_deg", 90.0)
                        )
                    )
                    if end_angle <= start_angle:
                        raise ValueError(
                            "arc.end_angle_deg must be greater than start_angle_deg"
                        )
                curve = work.Curves.CreateArc(
                    _local_to_world(origin, u_axis, v_axis, center_local),
                    NXOpen.Vector3d(u_axis[0], u_axis[1], u_axis[2]),
                    NXOpen.Vector3d(v_axis[0], v_axis[1], v_axis[2]),
                    radius,
                    start_angle,
                    end_angle,
                )
                curve.SetName("%s_%s" % (name, base_name))
                sketch.AddGeometry(
                    curve, NXOpen.Sketch.InferConstraintsOption.InferNoConstraints
                )
                objects[base_name] = curve
                local_records[base_name] = {
                    "center": center_local,
                    "radius": radius,
                }
                sequence += 1
            else:
                raise ValueError(
                    "unsupported sketch geometry type: %s" % kind
                )

        point_types = {
            "start": NXOpen.Sketch.ConstraintPointType.StartVertex,
            "end": NXOpen.Sketch.ConstraintPointType.EndVertex,
            "center": NXOpen.Sketch.ConstraintPointType.ArcCenter,
            "none": NXOpen.Sketch.ConstraintPointType.NotSet,
        }
        constraint_results = []
        for spec in auto_constraint_specs + constraint_specs:
            if not isinstance(spec, dict):
                raise ValueError("each constraint item must be an object")
            kind = str(spec.get("type", "")).strip().lower()
            first_name = str(
                spec.get("geometry") or spec.get("geometry1") or ""
            )
            if first_name not in objects:
                raise ValueError(
                    "constraint geometry was not found: %s" % first_name
                )
            first = _constraint_geometry(
                objects[first_name],
                point_types.get(
                    str(spec.get("point1", "none")).lower(),
                    NXOpen.Sketch.ConstraintPointType.NotSet,
                ),
            )
            if kind == "horizontal":
                created = sketch.CreateHorizontalConstraint(first)
            elif kind == "vertical":
                created = sketch.CreateVerticalConstraint(first)
            elif kind == "fixed":
                created = sketch.CreateFixedConstraint(first)
            else:
                second_name = str(spec.get("geometry2") or "")
                if second_name not in objects:
                    raise ValueError(
                        "constraint geometry2 was not found: %s" % second_name
                    )
                second = _constraint_geometry(
                    objects[second_name],
                    point_types.get(
                        str(spec.get("point2", "none")).lower(),
                        NXOpen.Sketch.ConstraintPointType.NotSet,
                    ),
                )
                if kind == "coincident":
                    created = sketch.CreateCoincidentConstraint(first, second)
                elif kind == "parallel":
                    created = sketch.CreateParallelConstraint(first, second)
                elif kind == "perpendicular":
                    created = sketch.CreatePerpendicularConstraint(first, second)
                elif kind == "equal_length":
                    created = sketch.CreateEqualLengthConstraint(first, second)
                elif kind == "concentric":
                    created = sketch.CreateConcentricConstraint(first, second)
                else:
                    raise ValueError(
                        "unsupported sketch constraint type: %s" % kind
                    )
            constraint_results.append(
                {
                    "type": kind,
                    "journal_id": getattr(created, "JournalIdentifier", None),
                }
            )

        dimension_results = []
        length_unit = _find_length_unit(work)
        for index, spec in enumerate(dimension_specs):
            if not isinstance(spec, dict):
                raise ValueError("each dimension item must be an object")
            kind = str(spec.get("type", "")).strip().lower()
            geometry_name = str(spec.get("geometry") or "")
            if geometry_name not in objects:
                raise ValueError(
                    "dimension geometry was not found: %s" % geometry_name
                )
            value = _finite_positive("dimension.value", spec.get("value"))
            dimension_name = _safe_object_name(
                spec.get("name"), "%s_D%s" % (name, index)
            )
            expression_name = _safe_object_name(
                "%s_%s" % (name, dimension_name), "MCP_DIM_%s" % index
            )
            expression = work.Expressions.CreateSystemExpressionWithUnits(
                "%s = %.15g" % (expression_name, value), length_unit
            )
            placement_local = spec.get("origin")
            if placement_local is None:
                record = local_records.get(geometry_name, {})
                if "start" in record and "end" in record:
                    placement_local = [
                        (record["start"][0] + record["end"][0]) / 2.0 + 5.0,
                        (record["start"][1] + record["end"][1]) / 2.0 + 5.0,
                    ]
                else:
                    placement_local = [5.0, 5.0]
            placement = _local_to_world(
                origin, u_axis, v_axis, placement_local
            )
            geometry = objects[geometry_name]
            if kind in ("horizontal", "vertical", "length"):
                first = _dimension_geometry(
                    geometry, NXOpen.Sketch.AssocType.StartPoint
                )
                second = _dimension_geometry(
                    geometry, NXOpen.Sketch.AssocType.EndPoint
                )
                constraint_type = {
                    "horizontal": NXOpen.Sketch.ConstraintType.HorizontalDim,
                    "vertical": NXOpen.Sketch.ConstraintType.VerticalDim,
                    "length": NXOpen.Sketch.ConstraintType.ParallelDim,
                }[kind]
                created = sketch.CreateDimension(
                    constraint_type, first, second, placement, expression
                )
            elif kind in ("diameter", "radius"):
                item = _dimension_geometry(
                    geometry, NXOpen.Sketch.AssocType.NotSet
                )
                if kind == "diameter":
                    created = sketch.CreateDiameterDimension(
                        item, placement, expression
                    )
                else:
                    created = sketch.CreateRadialDimension(
                        item, placement, expression
                    )
            else:
                raise ValueError(
                    "unsupported sketch dimension type: %s" % kind
                )
            dimension_results.append(
                {
                    "type": kind,
                    "geometry": geometry_name,
                    "expression": _sketch_expression_record(expression),
                    "journal_id": getattr(created, "JournalIdentifier", None),
                }
            )

        sketch.Update()
        sketch.CalculateStatus()
        status = str(sketch.GetStatus())
        sketch.Deactivate(
            NXOpen.Sketch.ViewReorient.FalseValue,
            NXOpen.Sketch.UpdateLevel.Model,
        )
        session.SetUndoMarkName(mark, "MCP create parametric sketch")
        return {
            "ok": True,
            "name": sketch.Name,
            "journal_id": sketch.JournalIdentifier,
            "feature_journal_id": sketch.Feature.JournalIdentifier,
            "tag": int(sketch.Tag),
            "plane": plane_name,
            "origin": origin,
            "geometry": [
                dict({"id": key}, **_sketch_geometry_record(value))
                for key, value in objects.items()
            ],
            "constraint_count": len(constraint_results),
            "constraints": constraint_results,
            "dimension_count": len(dimension_results),
            "dimensions": dimension_results,
            "status": status,
        }
    except Exception:
        if sketch is not None:
            try:
                if sketch.IsActive:
                    sketch.Deactivate(
                        NXOpen.Sketch.ViewReorient.FalseValue,
                        NXOpen.Sketch.UpdateLevel.SketchOnly,
                    )
            except Exception:
                pass
        try:
            session.UndoToMark(mark, None)
        except Exception:
            pass
        raise
    finally:
        if builder is not None:
            try:
                builder.Destroy()
            except Exception:
                pass


def _op_inspect_sketch(params):
    work = _work_part()
    identifier = params.get("sketch_id")
    sketches = [_find_sketch(work, identifier)] if identifier else list(work.Sketches)
    results = []
    for sketch in sketches:
        try:
            sketch.CalculateStatus()
        except Exception:
            pass
        geometry = list(sketch.GetAllGeometry())
        expressions = list(sketch.GetAllExpressions())
        results.append(
            {
                "name": sketch.Name,
                "journal_id": sketch.JournalIdentifier,
                "feature_journal_id": sketch.Feature.JournalIdentifier,
                "tag": int(sketch.Tag),
                "origin": [sketch.Origin.X, sketch.Origin.Y, sketch.Origin.Z],
                "status": str(sketch.GetStatus()),
                "geometry_count": len(geometry),
                "geometry": [
                    _sketch_geometry_record(item) for item in geometry
                ],
                "expression_count": len(expressions),
                "expressions": [
                    _sketch_expression_record(item) for item in expressions
                ],
            }
        )
    return {
        "ok": True,
        "part": work.Leaf,
        "sketch_count": len(results),
        "sketches": results,
    }


def _op_extrude_sketch(params):
    work = _work_part()
    session = NXOpen.Session.GetSession()
    sketch = _find_sketch(work, params.get("sketch_id"))
    distance = _finite_positive("distance", params.get("distance"))
    start = _finite_float("start", params.get("start", 0.0))
    direction_values = _vector3(
        "direction", params.get("direction"), [0.0, 0.0, 1.0]
    )
    magnitude = math.sqrt(sum(value * value for value in direction_values))
    if magnitude <= 1.0e-12:
        raise ValueError("direction must not be the zero vector")
    direction_values = [value / magnitude for value in direction_values]
    feature_name = _safe_object_name(
        params.get("feature_name"), "MCP_EXTRUDE"
    )
    geometry = list(sketch.GetAllGeometry())
    if not geometry:
        raise ValueError("the sketch does not contain geometry")

    mark = session.SetUndoMark(
        NXOpen.Session.MarkVisibility.Visible, "MCP extrude sketch"
    )
    section = work.Sections.CreateSection(0.00095, 0.001, 0.5)
    builder = work.Features.CreateExtrudeBuilder(NXOpen.Features.Feature.Null)
    try:
        section.AllowSelfIntersection(False)
        rule = work.ScRuleFactory.CreateRuleCurveDumb(geometry)
        section.AddToSection(
            [rule],
            geometry[0],
            NXOpen.NXObject.Null,
            NXOpen.NXObject.Null,
            NXOpen.Point3d(0.0, 0.0, 0.0),
            NXOpen.Section.Mode.Create,
            False,
        )
        loop_count = section.GetNumberOfLoops()
        if loop_count < 1:
            raise ValueError("the sketch does not contain a closed loop")
        builder.Section = section
        direction = work.Directions.CreateDirection(
            NXOpen.Point3d(0.0, 0.0, 0.0),
            NXOpen.Vector3d(*direction_values),
            NXOpen.SmartObject.UpdateOption.WithinModeling,
        )
        builder.Direction = direction
        builder.Limits.StartExtend.Value.RightHandSide = str(start)
        builder.Limits.EndExtend.Value.RightHandSide = str(start + distance)
        builder.BooleanOperation.Type = (
            NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create
        )
        feature = builder.CommitFeature()
        feature.SetName(feature_name)
        sketch.Blank()
        session.SetUndoMarkName(mark, "MCP extrude sketch")
    except Exception:
        try:
            session.UndoToMark(mark, None)
        except Exception:
            pass
        raise
    finally:
        builder.Destroy()
    bodies = list(feature.GetBodies()) if hasattr(feature, "GetBodies") else []
    return {
        "ok": True,
        "name": feature.Name,
        "journal_id": feature.JournalIdentifier,
        "sketch": sketch.Name,
        "distance": distance,
        "start": start,
        "direction": direction_values,
        "section_loop_count": loop_count,
        "feature_body_count": len(bodies),
        "part_body_count": len(list(work.Bodies)),
    }


def _op_revolve_sketch(params):
    import NXOpen.UF

    work = _work_part()
    session = NXOpen.Session.GetSession()
    axis_origin = _vector3(
        "axis_origin", params.get("axis_origin"), [0.0, 0.0, 0.0]
    )
    axis_direction = _vector3(
        "axis_direction", params.get("axis_direction"), [0.0, 1.0, 0.0]
    )
    magnitude = math.sqrt(sum(value * value for value in axis_direction))
    if magnitude <= 1.0e-12:
        raise ValueError("axis_direction must not be the zero vector")
    axis_direction = [value / magnitude for value in axis_direction]
    start_angle = _finite_float(
        "start_angle_deg", params.get("start_angle_deg", 0.0)
    )
    end_angle = _finite_float(
        "end_angle_deg", params.get("end_angle_deg", 360.0)
    )
    if end_angle <= start_angle or end_angle - start_angle > 360.0:
        raise ValueError(
            "end_angle_deg must be greater than start_angle_deg by at most 360 degrees"
        )
    feature_name = _safe_object_name(
        params.get("feature_name"), "MCP_REVOLVE"
    )
    sketch = None
    geometry = []
    mark = None
    stage = "find_sketch"
    try:
        sketch = _find_sketch(work, params.get("sketch_id"))
        stage = "read_sketch_geometry"
        geometry = list(sketch.GetAllGeometry())
        if not geometry:
            raise ValueError("the sketch does not contain geometry")
        stage = "set_undo_mark"
        mark = session.SetUndoMark(
            NXOpen.Session.MarkVisibility.Visible, "MCP revolve sketch"
        )
        stage = "create_revolution"
        trim_data = NXOpen.UF.Modl.SweepTrimObject()
        feature_tags, feature_count = (
            NXOpen.UF.UFSession.GetUFSession().Modl.CreateRevolution(
                [int(item.Tag) for item in geometry],
                len(geometry),
                trim_data,
                [str(start_angle), str(end_angle)],
                ["0", "0"],
                [0.0, 0.0, 0.0],
                False,
                True,
                axis_origin,
                axis_direction,
                NXOpen.UF.Modl.FeatureSigns.NULLSIGN,
            )
        )
        if feature_count < 1 or not feature_tags:
            raise RuntimeError("NX did not return a revolved feature")
        feature_tag = int(feature_tags[0])
        feature = next(
            (item for item in work.Features if int(item.Tag) == feature_tag),
            None,
        )
        if feature is None:
            raise RuntimeError(
                "NX created revolve tag %s but it was not found in the work part"
                % feature_tag
            )
        stage = "name_feature"
        feature.SetName(feature_name)
        sketch.Blank()
        session.SetUndoMarkName(mark, "MCP revolve sketch")
    except Exception as exc:
        if mark is not None:
            try:
                session.UndoToMark(mark, None)
            except Exception:
                pass
        raise RuntimeError(
            "revolve failed at %s: %s: %s"
            % (stage, type(exc).__name__, exc)
        )
    bodies = list(feature.GetBodies()) if hasattr(feature, "GetBodies") else []
    return {
        "ok": True,
        "name": feature.Name,
        "journal_id": feature.JournalIdentifier,
        "sketch": sketch.Name,
        "axis_origin": axis_origin,
        "axis_direction": axis_direction,
        "start_angle_deg": start_angle,
        "end_angle_deg": end_angle,
        "profile_curve_count": len(geometry),
        "implementation": "UF_MODL_create_revolution",
        "feature_body_count": len(bodies),
        "part_body_count": len(list(work.Bodies)),
    }


def _op_loft_sketches(params):
    work = _work_part()
    session = NXOpen.Session.GetSession()
    sketch_ids = params.get("sketch_ids")
    if not isinstance(sketch_ids, (list, tuple)) or len(sketch_ids) < 2:
        raise ValueError("sketch_ids must contain at least two sketch identifiers")
    feature_name = _safe_object_name(params.get("feature_name"), "MCP_LOFT")
    solid = bool(params.get("solid", True))
    mark = None
    builder = None
    sections = []
    sketches = []
    feature = None
    stage = "find_sketches"
    try:
        sketches = [_find_sketch(work, identifier) for identifier in sketch_ids]
        if len({int(sketch.Tag) for sketch in sketches}) != len(sketches):
            raise ValueError("sketch_ids must identify distinct sketches")
        mark = session.SetUndoMark(
            NXOpen.Session.MarkVisibility.Visible, "MCP loft sketches"
        )
        stage = "create_builder"
        builder = work.Features.CreateThroughCurvesBuilder(
            NXOpen.Features.Feature.Null
        )
        builder.BodyPreference = (
            NXOpen.Features.ThroughCurvesBuilder.BodyPreferenceTypes.Solid
            if solid
            else NXOpen.Features.ThroughCurvesBuilder.BodyPreferenceTypes.Sheet
        )
        for sketch in sketches:
            stage = "read_sketch_%s" % sketch.Name
            geometry = list(sketch.GetAllGeometry())
            if not geometry:
                raise ValueError("sketch %s does not contain geometry" % sketch.Name)
            section = work.Sections.CreateSection(0.00095, 0.001, 0.5)
            sections.append(section)
            section.AllowSelfIntersection(False)
            rule = work.ScRuleFactory.CreateRuleCurveDumb(geometry)
            section.AddToSection(
                [rule],
                geometry[0],
                NXOpen.NXObject.Null,
                NXOpen.NXObject.Null,
                NXOpen.Point3d(
                    float(sketch.Origin.X),
                    float(sketch.Origin.Y),
                    float(sketch.Origin.Z),
                ),
                NXOpen.Section.Mode.Create,
                False,
            )
            if section.GetNumberOfLoops() < 1:
                raise ValueError("sketch %s is not a valid section" % sketch.Name)
            builder.SectionsList.Append(section)
        stage = "validate"
        if not builder.Validate():
            raise RuntimeError("NX rejected the through-curves builder parameters")
        stage = "commit"
        feature = builder.CommitFeature()
        stage = "name_feature"
        feature.SetName(feature_name)
        for sketch in sketches:
            sketch.Blank()
        session.SetUndoMarkName(mark, "MCP loft sketches")
    except Exception as exc:
        if mark is not None:
            try:
                session.UndoToMark(mark, None)
            except Exception:
                pass
        raise RuntimeError(
            "loft failed at %s: %s: %s" % (stage, type(exc).__name__, exc)
        )
    finally:
        if builder is not None:
            try:
                builder.Destroy()
            except Exception:
                pass
    bodies = list(feature.GetBodies()) if hasattr(feature, "GetBodies") else []
    return {
        "ok": True,
        "name": feature.Name,
        "journal_id": feature.JournalIdentifier,
        "sketches": [sketch.Name for sketch in sketches],
        "section_count": len(sections),
        "solid": solid,
        "feature_body_count": len(bodies),
        "part_body_count": len(list(work.Bodies)),
    }


def _op_sweep_sketch(params):
    work = _work_part()
    session = NXOpen.Session.GetSession()
    feature_name = _safe_object_name(params.get("feature_name"), "MCP_SWEEP")
    solid = bool(params.get("solid", True))
    mark = None
    builder = None
    feature = None
    stage = "find_sketches"
    try:
        profile = _find_sketch(work, params.get("profile_sketch_id"))
        guide = _find_sketch(work, params.get("guide_sketch_id"))
        if int(profile.Tag) == int(guide.Tag):
            raise ValueError("profile and guide sketches must be different")
        profile_geometry = list(profile.GetAllGeometry())
        guide_geometry = list(guide.GetAllGeometry())
        if not profile_geometry:
            raise ValueError("the profile sketch does not contain geometry")
        if not guide_geometry:
            raise ValueError("the guide sketch does not contain geometry")
        mark = session.SetUndoMark(
            NXOpen.Session.MarkVisibility.Visible, "MCP sweep sketch"
        )
        stage = "create_builder"
        builder = work.Features.CreateSweepAlongGuideBuilder(
            NXOpen.Features.SweepAlongGuide.Null
        )
        builder.FeatureOptions.BodyType = (
            NXOpen.GeometricUtilities.FeatureOptions.BodyStyle.Solid
            if solid
            else NXOpen.GeometricUtilities.FeatureOptions.BodyStyle.Sheet
        )
        builder.BooleanOperation.Type = (
            NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create
        )

        stage = "profile_section"
        profile_section = builder.Section
        profile_section.AllowSelfIntersection(False)
        profile_rule = work.ScRuleFactory.CreateRuleCurveDumb(profile_geometry)
        profile_section.AddToSection(
            [profile_rule], profile_geometry[0], NXOpen.NXObject.Null,
            NXOpen.NXObject.Null,
            NXOpen.Point3d(float(profile.Origin.X), float(profile.Origin.Y), float(profile.Origin.Z)),
            NXOpen.Section.Mode.Create, False,
        )
        if solid and profile_section.GetNumberOfLoops() < 1:
            raise ValueError("the profile sketch must contain a closed loop")

        stage = "guide_section"
        guide_section = builder.Guide
        guide_section.AllowSelfIntersection(False)
        guide_rule = work.ScRuleFactory.CreateRuleCurveDumb(guide_geometry)
        guide_section.AddToSection(
            [guide_rule], guide_geometry[0], NXOpen.NXObject.Null,
            NXOpen.NXObject.Null,
            NXOpen.Point3d(float(guide.Origin.X), float(guide.Origin.Y), float(guide.Origin.Z)),
            NXOpen.Section.Mode.Create, False,
        )
        stage = "validate"
        if not builder.Validate():
            raise RuntimeError("NX rejected the swept builder parameters")
        stage = "commit"
        feature = builder.CommitFeature()
        stage = "name_feature"
        feature.SetName(feature_name)
        profile.Blank()
        guide.Blank()
        session.SetUndoMarkName(mark, "MCP sweep sketch")
    except Exception as exc:
        if mark is not None:
            try:
                session.UndoToMark(mark, None)
            except Exception:
                pass
        raise RuntimeError(
            "sweep failed at %s: %s: %s" % (stage, type(exc).__name__, exc)
        )
    finally:
        if builder is not None:
            try:
                builder.Destroy()
            except Exception:
                pass
    bodies = list(feature.GetBodies()) if hasattr(feature, "GetBodies") else []
    return {
        "ok": True,
        "name": feature.Name,
        "journal_id": feature.JournalIdentifier,
        "profile_sketch": profile.Name,
        "guide_sketch": guide.Name,
        "solid": solid,
        "feature_body_count": len(bodies),
        "part_body_count": len(list(work.Bodies)),
    }


def _op_boolean_bodies(params):
    work = _work_part()
    session = NXOpen.Session.GetSession()
    operation_name = str(params.get("operation", "unite")).strip().lower()
    operation_types = {
        "unite": NXOpen.Features.Feature.BooleanType.Unite,
        "subtract": NXOpen.Features.Feature.BooleanType.Subtract,
        "intersect": NXOpen.Features.Feature.BooleanType.Intersect,
    }
    if operation_name not in operation_types:
        raise ValueError("operation must be unite, subtract, or intersect")
    target = _body_by_index(work, params.get("target_body_index", 0))
    tool = _body_by_index(work, params.get("tool_body_index", 1))
    if int(target.Tag) == int(tool.Tag):
        raise ValueError("target and tool bodies must be different")
    target_tag = int(target.Tag)
    tool_tag = int(tool.Tag)
    feature_name = _safe_object_name(params.get("feature_name"), "MCP_BOOLEAN")
    mark = session.SetUndoMark(
        NXOpen.Session.MarkVisibility.Visible, "MCP boolean bodies"
    )
    builder = None
    try:
        builder = work.Features.CreateBooleanBuilder(
            NXOpen.Features.BooleanFeature.Null
        )
        builder.Operation = operation_types[operation_name]
        builder.Target = target
        builder.Tool = tool
        builder.RetainTarget = bool(params.get("retain_target", False))
        builder.RetainTool = bool(params.get("retain_tool", False))
        feature = builder.CommitFeature()
        feature.SetName(feature_name)
        session.SetUndoMarkName(mark, "MCP boolean bodies")
    except Exception:
        try:
            session.UndoToMark(mark, None)
        except Exception:
            pass
        raise
    finally:
        if builder is not None:
            try:
                builder.Destroy()
            except Exception:
                pass
    return {
        "ok": True,
        "name": feature.Name,
        "journal_id": feature.JournalIdentifier,
        "operation": operation_name,
        "target_body_tag": target_tag,
        "tool_body_tag": tool_tag,
        "part_body_count": len(list(work.Bodies)),
    }


def _op_create_cylindrical_hole(params):
    work = _work_part()
    session = NXOpen.Session.GetSession()
    target = _body_by_index(work, params.get("target_body_index", 0))
    target_tag = int(target.Tag)
    origin = _vector3("origin", params.get("origin"), [0.0, 0.0, 0.0])
    direction = _vector3("direction", params.get("direction"), [0.0, 0.0, -1.0])
    magnitude = math.sqrt(sum(value * value for value in direction))
    if magnitude <= 1.0e-12:
        raise ValueError("direction must not be the zero vector")
    direction = [value / magnitude for value in direction]
    diameter = _finite_positive("diameter", params.get("diameter"))
    depth = _finite_positive("depth", params.get("depth"))
    feature_name = _safe_object_name(params.get("feature_name"), "MCP_HOLE")
    mark = session.SetUndoMark(
        NXOpen.Session.MarkVisibility.Visible, "MCP cylindrical hole"
    )
    builder = None
    try:
        builder = work.Features.CreateCylinderBuilder(NXOpen.Features.Feature.Null)
        builder.Type = NXOpen.Features.CylinderBuilder.Types.AxisDiameterAndHeight
        builder.Origin = NXOpen.Point3d(*origin)
        builder.Direction = NXOpen.Vector3d(*direction)
        builder.Diameter.RightHandSide = str(diameter)
        builder.Height.RightHandSide = str(depth)
        builder.BooleanOption.Type = (
            NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Subtract
        )
        builder.BooleanOption.SetTargetBodies([target])
        feature = builder.CommitFeature()
        feature.SetName(feature_name)
        session.SetUndoMarkName(mark, "MCP cylindrical hole")
    except Exception:
        try:
            session.UndoToMark(mark, None)
        except Exception:
            pass
        raise
    finally:
        if builder is not None:
            try:
                builder.Destroy()
            except Exception:
                pass
    return {
        "ok": True,
        "name": feature.Name,
        "journal_id": feature.JournalIdentifier,
        "implementation": "subtractive_cylinder_feature",
        "target_body_tag": target_tag,
        "origin": origin,
        "direction": direction,
        "diameter": diameter,
        "depth": depth,
        "part_body_count": len(list(work.Bodies)),
    }


def _op_fillet_edges(params):
    work = _work_part()
    session = NXOpen.Session.GetSession()
    body = _body_by_index(work, params.get("body_index", 0))
    edges = _items_by_indices(
        list(body.GetEdges()), params.get("edge_indices"), "edge"
    )
    radius = _finite_positive("radius", params.get("radius"))
    feature_name = _safe_object_name(params.get("feature_name"), "MCP_FILLET")
    selected_tags = [int(edge.Tag) for edge in edges]
    mark = session.SetUndoMark(
        NXOpen.Session.MarkVisibility.Visible, "MCP fillet edges"
    )
    builder = None
    try:
        builder = work.Features.CreateEdgeBlendBuilder(NXOpen.Features.Feature.Null)
        collector = work.ScCollectors.CreateCollector()
        rule = work.ScRuleFactory.CreateRuleEdgeDumb(edges)
        collector.ReplaceRules([rule], False)
        builder.AddChainset(collector, str(radius))
        feature = builder.CommitFeature()
        feature.SetName(feature_name)
        session.SetUndoMarkName(mark, "MCP fillet edges")
    except Exception:
        try:
            session.UndoToMark(mark, None)
        except Exception:
            pass
        raise
    finally:
        if builder is not None:
            try:
                builder.Destroy()
            except Exception:
                pass
    return {
        "ok": True,
        "name": feature.Name,
        "journal_id": feature.JournalIdentifier,
        "radius": radius,
        "selected_edge_tags": selected_tags,
        "part_body_count": len(list(work.Bodies)),
    }


def _op_chamfer_edges(params):
    work = _work_part()
    session = NXOpen.Session.GetSession()
    body = _body_by_index(work, params.get("body_index", 0))
    edges = _items_by_indices(
        list(body.GetEdges()), params.get("edge_indices"), "edge"
    )
    distance = _finite_positive("distance", params.get("distance"))
    feature_name = _safe_object_name(params.get("feature_name"), "MCP_CHAMFER")
    selected_tags = [int(edge.Tag) for edge in edges]
    mark = session.SetUndoMark(
        NXOpen.Session.MarkVisibility.Visible, "MCP chamfer edges"
    )
    builder = None
    try:
        builder = work.Features.CreateChamferBuilder(NXOpen.Features.Feature.Null)
        collector = work.ScCollectors.CreateCollector()
        rule = work.ScRuleFactory.CreateRuleEdgeDumb(edges)
        collector.ReplaceRules([rule], False)
        builder.SmartCollector = collector
        builder.Method = NXOpen.Features.ChamferBuilder.OffsetMethod.EdgesAlongFaces
        builder.Option = NXOpen.Features.ChamferBuilder.ChamferOption.SymmetricOffsets
        builder.FirstOffsetExp.RightHandSide = str(distance)
        builder.SecondOffsetExp.RightHandSide = str(distance)
        feature = builder.CommitFeature()
        feature.SetName(feature_name)
        session.SetUndoMarkName(mark, "MCP chamfer edges")
    except Exception:
        try:
            session.UndoToMark(mark, None)
        except Exception:
            pass
        raise
    finally:
        if builder is not None:
            try:
                builder.Destroy()
            except Exception:
                pass
    return {
        "ok": True,
        "name": feature.Name,
        "journal_id": feature.JournalIdentifier,
        "distance": distance,
        "selected_edge_tags": selected_tags,
        "part_body_count": len(list(work.Bodies)),
    }


def _op_shell_body(params):
    import NXOpen.UF

    work = _work_part()
    session = NXOpen.Session.GetSession()
    body = _body_by_index(work, params.get("body_index", 0))
    faces = _items_by_indices(
        list(body.GetFaces()), params.get("remove_face_indices"), "remove_face"
    )
    thickness = _finite_positive("thickness", params.get("thickness"))
    feature_name = _safe_object_name(params.get("feature_name"), "MCP_SHELL")
    selected_tags = [int(face.Tag) for face in faces]
    mark = session.SetUndoMark(
        NXOpen.Session.MarkVisibility.Visible, "MCP shell body"
    )
    stage = "create_hollow"
    try:
        signed_thickness = thickness if bool(params.get("inward", True)) else -thickness
        feature_tag = int(
            NXOpen.UF.UFSession.GetUFSession().ModlFeatures.CreateHollow(
                str(signed_thickness), [int(face.Tag) for face in faces]
            )
        )
        feature = next(
            (item for item in work.Features if int(item.Tag) == feature_tag), None
        )
        if feature is None:
            raise RuntimeError(
                "NX created hollow tag %s but it was not found" % feature_tag
            )
        stage = "name_feature"
        feature.SetName(feature_name)
        session.SetUndoMarkName(mark, "MCP shell body")
    except Exception as exc:
        try:
            session.UndoToMark(mark, None)
        except Exception:
            pass
        raise RuntimeError(
            "shell failed at %s: %s: %s" % (stage, type(exc).__name__, exc)
        )
    return {
        "ok": True,
        "name": feature.Name,
        "journal_id": feature.JournalIdentifier,
        "thickness": thickness,
        "inward": bool(params.get("inward", True)),
        "implementation": "UF_MODL_create_hollow",
        "removed_face_tags": selected_tags,
        "part_body_count": len(list(work.Bodies)),
    }


def _op_linear_pattern_feature(params):
    work = _work_part()
    session = NXOpen.Session.GetSession()
    seed = _find_feature(work, params.get("feature_id"))
    count = int(params.get("count", 2))
    if count < 2 or count > 1000:
        raise ValueError("count must be between 2 and 1000")
    spacing = _finite_positive("spacing", params.get("spacing"))
    direction_values = _vector3(
        "direction", params.get("direction"), [1.0, 0.0, 0.0]
    )
    magnitude = math.sqrt(sum(value * value for value in direction_values))
    if magnitude <= 1.0e-12:
        raise ValueError("direction must not be the zero vector")
    direction_values = [value / magnitude for value in direction_values]
    feature_name = _safe_object_name(params.get("feature_name"), "MCP_PATTERN")
    mark = session.SetUndoMark(
        NXOpen.Session.MarkVisibility.Visible, "MCP linear pattern"
    )
    builder = None
    stage = "create_builder"
    try:
        builder = work.Features.CreatePatternFeatureBuilder(
            NXOpen.Features.Feature.Null
        )
        stage = "add_seed"
        builder.FeatureList.Add(seed)
        builder.PatternMethod = (
            NXOpen.Features.PatternFeatureBuilder.PatternMethodOptions.Simple
        )
        builder.OutputOption = (
            NXOpen.Features.PatternFeatureBuilder.OutputOptions.PatternFeature
        )
        service = builder.PatternService
        service.PatternType = (
            NXOpen.GeometricUtilities.PatternDefinition.PatternEnum.Linear
        )
        rectangular = service.RectangularDefinition
        direction = work.Directions.CreateDirection(
            NXOpen.Point3d(0.0, 0.0, 0.0),
            NXOpen.Vector3d(*direction_values),
            NXOpen.SmartObject.UpdateOption.WithinModeling,
        )
        rectangular.XDirection = direction
        rectangular.UseYDirectionToggle = False
        rectangular.XSpacing.SpaceType = (
            NXOpen.GeometricUtilities.PatternSpacing.SpacingType.Offset
        )
        rectangular.XSpacing.NCopies.RightHandSide = str(count)
        rectangular.XSpacing.PitchDistance.RightHandSide = str(spacing)
        stage = "validate"
        if not builder.Validate():
            raise RuntimeError("NX rejected the pattern parameters")
        stage = "commit"
        feature = builder.CommitFeature()
        stage = "name_feature"
        feature.SetName(feature_name)
        session.SetUndoMarkName(mark, "MCP linear pattern")
    except Exception as exc:
        try:
            session.UndoToMark(mark, None)
        except Exception:
            pass
        raise RuntimeError(
            "linear pattern failed at %s: %s: %s"
            % (stage, type(exc).__name__, exc)
        )
    finally:
        if builder is not None:
            try:
                builder.Destroy()
            except Exception:
                pass
    return {
        "ok": True,
        "name": feature.Name,
        "journal_id": feature.JournalIdentifier,
        "seed_feature": seed.JournalIdentifier,
        "count": count,
        "spacing": spacing,
        "direction": direction_values,
        "part_body_count": len(list(work.Bodies)),
    }


def _op_mirror_feature(params):
    work = _work_part()
    session = NXOpen.Session.GetSession()
    seed = _find_feature(work, params.get("feature_id"))
    plane_origin = _vector3(
        "plane_origin", params.get("plane_origin"), [0.0, 0.0, 0.0]
    )
    plane_normal = _vector3(
        "plane_normal", params.get("plane_normal"), [1.0, 0.0, 0.0]
    )
    magnitude = math.sqrt(sum(value * value for value in plane_normal))
    if magnitude <= 1.0e-12:
        raise ValueError("plane_normal must not be the zero vector")
    plane_normal = [value / magnitude for value in plane_normal]
    feature_name = _safe_object_name(params.get("feature_name"), "MCP_MIRROR")
    mark = session.SetUndoMark(
        NXOpen.Session.MarkVisibility.Visible, "MCP mirror feature"
    )
    builder = None
    stage = "create_builder"
    try:
        builder = work.Features.CreateMirrorFeatureBuilder(
            NXOpen.Features.Feature.Null
        )
        stage = "add_seed"
        builder.FeatureSet.Add(seed)
        plane = work.Planes.CreatePlane(
            NXOpen.Point3d(*plane_origin),
            NXOpen.Vector3d(*plane_normal),
            NXOpen.SmartObject.UpdateOption.WithinModeling,
        )
        builder.PlaneOption = NXOpen.Features.MirrorFeatureBuilder.PlaneOptions.New
        builder.PlaneConstructor = plane
        stage = "validate"
        if not builder.Validate():
            raise RuntimeError("NX rejected the mirror parameters")
        stage = "commit"
        feature = builder.CommitFeature()
        stage = "name_feature"
        feature.SetName(feature_name)
        session.SetUndoMarkName(mark, "MCP mirror feature")
    except Exception as exc:
        try:
            session.UndoToMark(mark, None)
        except Exception:
            pass
        raise RuntimeError(
            "mirror failed at %s: %s: %s" % (stage, type(exc).__name__, exc)
        )
    finally:
        if builder is not None:
            try:
                builder.Destroy()
            except Exception:
                pass
    return {
        "ok": True,
        "name": feature.Name,
        "journal_id": feature.JournalIdentifier,
        "seed_feature": seed.JournalIdentifier,
        "plane_origin": plane_origin,
        "plane_normal": plane_normal,
        "part_body_count": len(list(work.Bodies)),
    }


def _polar(radius, angle):
    return (radius * math.cos(angle), radius * math.sin(angle))


def _append_distinct(points, point, tolerance=1.0e-9):
    if points:
        dx = points[-1][0] - point[0]
        dy = points[-1][1] - point[1]
        if dx * dx + dy * dy <= tolerance * tolerance:
            return
    points.append(point)


def _involute_gear_profile(
    module,
    teeth,
    pressure_angle_deg,
    bore_diameter,
    flank_segments,
    arc_segments,
):
    """Return closed-loop points for a standard full-depth involute spur gear."""
    module = _finite_positive("module", module)
    teeth = int(teeth)
    if not 6 <= teeth <= 400:
        raise ValueError("teeth must be between 6 and 400")
    pressure_angle_deg = _finite_float("pressure_angle_deg", pressure_angle_deg)
    if not 5.0 <= pressure_angle_deg <= 35.0:
        raise ValueError("pressure_angle_deg must be between 5 and 35")
    bore_diameter = _finite_float("bore_diameter", bore_diameter)
    if bore_diameter < 0:
        raise ValueError("bore_diameter must be zero or greater")
    flank_segments = int(flank_segments)
    arc_segments = int(arc_segments)
    if not 4 <= flank_segments <= 40:
        raise ValueError("flank_segments must be between 4 and 40")
    if not 2 <= arc_segments <= 24:
        raise ValueError("arc_segments must be between 2 and 24")

    alpha = math.radians(pressure_angle_deg)
    pitch_radius = module * teeth / 2.0
    base_radius = pitch_radius * math.cos(alpha)
    outside_radius = pitch_radius + module
    root_radius = pitch_radius - 1.25 * module
    if root_radius <= 0:
        raise ValueError("root radius is not positive; increase the tooth count")
    if bore_diameter >= 2.0 * root_radius:
        raise ValueError("bore_diameter must be smaller than the root diameter")

    start_radius = max(root_radius, base_radius)
    pitch_t = math.sqrt((pitch_radius / base_radius) ** 2 - 1.0)
    start_t = math.sqrt(max(0.0, (start_radius / base_radius) ** 2 - 1.0))
    outside_t = math.sqrt((outside_radius / base_radius) ** 2 - 1.0)

    def involute_angle(t_value):
        return t_value - math.atan(t_value)

    # The involute polar angle grows away from the base circle.  For an
    # external gear flank, the tooth half-angle must therefore shrink as the
    # radius grows.  Anchoring at the pitch circle gives exactly pi*m/2 tooth
    # thickness there and prevents the previously generated inverted teeth.
    half_pitch_tooth = math.pi / (2.0 * teeth)
    flank_rotation = half_pitch_tooth + involute_angle(pitch_t)
    start_half_angle = flank_rotation - involute_angle(start_t)
    outside_half_angle = flank_rotation - involute_angle(outside_t)
    tooth_pitch_angle = 2.0 * math.pi / teeth
    if outside_half_angle <= 0:
        raise ValueError("tooth tip thickness is not positive for the requested parameters")
    if start_half_angle >= tooth_pitch_angle / 2.0:
        raise ValueError("tooth roots overlap for the requested parameters")

    outer = []
    for tooth_index in range(teeth):
        center_angle = tooth_index * tooth_pitch_angle
        _append_distinct(
            outer, _polar(root_radius, center_angle - start_half_angle)
        )
        for sample_index in range(flank_segments + 1):
            fraction = float(sample_index) / float(flank_segments)
            t_value = start_t + (outside_t - start_t) * fraction
            radius = base_radius * math.sqrt(1.0 + t_value * t_value)
            half_angle = flank_rotation - involute_angle(t_value)
            _append_distinct(outer, _polar(radius, center_angle - half_angle))
        for sample_index in range(1, arc_segments + 1):
            fraction = float(sample_index) / float(arc_segments)
            angle = center_angle - outside_half_angle + (
                2.0 * outside_half_angle * fraction
            )
            _append_distinct(outer, _polar(outside_radius, angle))
        for sample_index in range(1, flank_segments + 1):
            fraction = float(sample_index) / float(flank_segments)
            t_value = outside_t - (outside_t - start_t) * fraction
            radius = base_radius * math.sqrt(1.0 + t_value * t_value)
            half_angle = flank_rotation - involute_angle(t_value)
            _append_distinct(outer, _polar(radius, center_angle + half_angle))
        _append_distinct(
            outer, _polar(root_radius, center_angle + start_half_angle)
        )
        next_root_angle = center_angle + tooth_pitch_angle - start_half_angle
        root_span = next_root_angle - (center_angle + start_half_angle)
        for sample_index in range(1, arc_segments + 1):
            fraction = float(sample_index) / float(arc_segments)
            _append_distinct(
                outer,
                _polar(
                    root_radius,
                    center_angle + start_half_angle + root_span * fraction,
                ),
            )

    if len(outer) > 1:
        dx = outer[-1][0] - outer[0][0]
        dy = outer[-1][1] - outer[0][1]
        if dx * dx + dy * dy <= 1.0e-16:
            outer.pop()

    inner = []
    if bore_diameter > 0:
        bore_radius = bore_diameter / 2.0
        bore_segments = max(32, teeth * 2)
        for index in range(bore_segments):
            angle = -2.0 * math.pi * index / bore_segments
            inner.append(_polar(bore_radius, angle))

    pitch_tooth_thickness = 2.0 * pitch_radius * half_pitch_tooth
    outside_tooth_thickness = 2.0 * outside_radius * outside_half_angle
    root_tooth_thickness = 2.0 * root_radius * start_half_angle
    return outer, inner, {
        "module": module,
        "teeth": teeth,
        "pressure_angle_deg": pressure_angle_deg,
        "pitch_diameter": 2.0 * pitch_radius,
        "base_diameter": 2.0 * base_radius,
        "outside_diameter": 2.0 * outside_radius,
        "root_diameter": 2.0 * root_radius,
        "bore_diameter": bore_diameter,
        "pitch_tooth_thickness": pitch_tooth_thickness,
        "outside_tooth_thickness": outside_tooth_thickness,
        "root_tooth_thickness": root_tooth_thickness,
        "tooth_thickness_decreases_outward": (
            outside_tooth_thickness
            < pitch_tooth_thickness
            < root_tooth_thickness
        ),
        "flank_segments": flank_segments,
        "arc_segments": arc_segments,
    }


def _create_line_loop(work, points):
    curves = []
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        curves.append(
            work.Curves.CreateLine(
                NXOpen.Point3d(start[0], start[1], 0.0),
                NXOpen.Point3d(end[0], end[1], 0.0),
            )
        )
    return curves


def _op_create_involute_gear(params):
    face_width = _finite_positive("face_width", params.get("face_width", 10.0))
    outer, inner, dimensions = _involute_gear_profile(
        params.get("module", 2.0),
        params.get("teeth", 20),
        params.get("pressure_angle_deg", 20.0),
        params.get("bore_diameter", 10.0),
        params.get("flank_segments", 10),
        params.get("arc_segments", 4),
    )

    work = _work_part()
    session = NXOpen.Session.GetSession()
    mark = session.SetUndoMark(
        NXOpen.Session.MarkVisibility.Visible, "MCP create involute gear"
    )
    outer_curves = _create_line_loop(work, outer)
    inner_curves = _create_line_loop(work, inner) if inner else []
    section = work.Sections.CreateSection(0.00095, 0.001, 0.5)
    builder = work.Features.CreateExtrudeBuilder(NXOpen.Features.Feature.Null)
    direction = None
    feature = None
    try:
        section.AllowSelfIntersection(False)
        outer_rule = work.ScRuleFactory.CreateRuleCurveDumb(outer_curves)
        section.AddToSection(
            [outer_rule],
            outer_curves[0],
            NXOpen.NXObject.Null,
            NXOpen.NXObject.Null,
            NXOpen.Point3d(dimensions["outside_diameter"] / 2.0, 0.0, 0.0),
            NXOpen.Section.Mode.Create,
            False,
        )
        if inner_curves:
            inner_rule = work.ScRuleFactory.CreateRuleCurveDumb(inner_curves)
            section.AddToSection(
                [inner_rule],
                inner_curves[0],
                NXOpen.NXObject.Null,
                NXOpen.NXObject.Null,
                NXOpen.Point3d(dimensions["bore_diameter"] / 2.0, 0.0, 0.0),
                NXOpen.Section.Mode.Create,
                False,
            )
        loop_count = section.GetNumberOfLoops()
        builder.Section = section
        direction = work.Directions.CreateDirection(
            NXOpen.Point3d(0.0, 0.0, 0.0),
            NXOpen.Vector3d(0.0, 0.0, 1.0),
            NXOpen.SmartObject.UpdateOption.WithinModeling,
        )
        builder.Direction = direction
        builder.Limits.StartExtend.Value.RightHandSide = "0"
        builder.Limits.EndExtend.Value.RightHandSide = str(face_width)
        builder.BooleanOperation.Type = (
            NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create
        )
        feature = builder.CommitFeature()
        feature.SetName(
            "INVOLUTE_GEAR_M%s_Z%s_PA%s"
            % (
                ("%g" % dimensions["module"]),
                dimensions["teeth"],
                ("%g" % dimensions["pressure_angle_deg"]),
            )
        )
        session.SetUndoMarkName(mark, "MCP create involute gear")
    finally:
        builder.Destroy()
        for curve in outer_curves + inner_curves:
            try:
                curve.Blank()
            except Exception:
                pass

    bodies = list(work.Bodies)
    feature_bodies = list(feature.GetBodies()) if hasattr(feature, "GetBodies") else []
    edge_count = None
    face_count = None
    if feature_bodies:
        edge_count = len(list(feature_bodies[0].GetEdges()))
        face_count = len(list(feature_bodies[0].GetFaces()))
    dimensions["face_width"] = face_width
    return {
        "ok": True,
        "feature": feature.JournalIdentifier,
        "name": feature.Name,
        "part": getattr(work, "Leaf", None),
        "body_count": len(bodies),
        "feature_body_count": len(feature_bodies),
        "face_count": face_count,
        "edge_count": edge_count,
        "section_loop_count": loop_count,
        "outer_profile_points": len(outer),
        "bore_profile_points": len(inner),
        "dimensions": dimensions,
    }


def _op_create_block(params):
    length = _finite_positive("length", params.get("length", 100.0))
    width = _finite_positive("width", params.get("width", 60.0))
    height = _finite_positive("height", params.get("height", 40.0))
    origin = params.get("origin", [0.0, 0.0, 0.0])
    if not isinstance(origin, (list, tuple)) or len(origin) != 3:
        raise ValueError("origin must contain exactly three coordinates")
    origin = [float(item) for item in origin]
    if not all(math.isfinite(item) for item in origin):
        raise ValueError("origin coordinates must be finite")

    work = _work_part()
    session = NXOpen.Session.GetSession()
    mark = session.SetUndoMark(
        NXOpen.Session.MarkVisibility.Visible, "MCP create block"
    )
    builder = work.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
    try:
        builder.Type = NXOpen.Features.BlockFeatureBuilder.Types.OriginAndEdgeLengths
        builder.SetOriginAndLengths(
            NXOpen.Point3d(origin[0], origin[1], origin[2]),
            str(length),
            str(width),
            str(height),
        )
        builder.SetBooleanOperationAndTarget(
            NXOpen.Features.Feature.BooleanType.Create, NXOpen.Body.Null
        )
        feature = builder.CommitFeature()
        session.SetUndoMarkName(mark, "MCP create block")
    finally:
        builder.Destroy()
    return {
        "ok": True,
        "feature": feature.JournalIdentifier,
        "name": feature.Name,
        "part": getattr(work, "Leaf", None),
        "length": length,
        "width": width,
        "height": height,
        "origin": origin,
        "body_count": len(list(work.Bodies)),
    }


def _cam_module():
    import NXOpen.CAM

    return NXOpen.CAM


def _cam_setup(required=True):
    work = _work_part()
    try:
        setup = work.CAMSetup
    except Exception:
        setup = None
    if required and setup is None:
        raise RuntimeError(
            "The work part has no CAM setup. Call initialize_cam_setup first."
        )
    return setup


def _cam_safe_name(field_name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % field_name)
    value = value.strip()
    if len(value) > 80:
        raise ValueError("%s must not exceed 80 characters" % field_name)
    if any(character in value for character in ("/", "\\", ":", "\0", "\r", "\n")):
        raise ValueError("%s must be a plain NX object name, not a path" % field_name)
    return value


def _cam_enum_name(value):
    name = getattr(value, "name", None)
    if name:
        return str(name)
    text = str(value)
    return text.rsplit(".", 1)[-1]


def _cam_template_status(setup, obj):
    use_as_template, create_with_parent = setup.GetTemplateStatus(obj)
    return {
        "use_as_template": bool(use_as_template),
        "create_with_parent": bool(create_with_parent),
    }


def _cam_geometry_record(geometry):
    sets = []
    for geometry_set in geometry.GeometryList.GetContents():
        items = [
            {
                "tag": int(item.Tag),
                "type": type(item).__name__,
                "journal_id": getattr(item, "JournalIdentifier", None),
            }
            for item in geometry_set.GetItems()
        ]
        sets.append(
            {
                "tag": int(geometry_set.Tag),
                "item_count": len(items),
                "items": items,
            }
        )
    return {"set_count": len(sets), "sets": sets}


def _cam_inheritable_record(value):
    record = {"type": type(value).__name__}
    for name in ("InheritanceStatus", "Value", "Unit", "Intent"):
        if not hasattr(value, name):
            continue
        try:
            item = getattr(value, name)
            if name in ("Unit", "Intent"):
                item = {
                    "name": _cam_enum_name(item),
                    "value": int(getattr(item, "value", item)),
                }
            record[name] = item
        except Exception as exc:
            record["%s_error" % name] = str(exc)
    return record


def _cam_object_record(setup, obj, include_members=False, depth=0, max_depth=4):
    record = {
        "name": getattr(obj, "Name", None),
        "user_name": getattr(obj, "UserName", None),
        "type": type(obj).__name__,
        "tag": int(obj.Tag),
        "is_operation": bool(setup.IsOperation(obj)),
        "is_group": bool(setup.IsGroup(obj)),
    }
    if record["is_operation"]:
        try:
            status = obj.GetStatus()
            status_value = int(getattr(status, "value", status))
            record["status"] = {
                0: "complete",
                1: "repost",
                2: "regenerate",
                3: "approved",
            }.get(status_value, _cam_enum_name(status))
            record["status_value"] = status_value
        except Exception as exc:
            record["status_error"] = str(exc)
        try:
            has_path = bool(obj.AskPathExists())
            record["path_exists"] = has_path
            if has_path:
                record.update(
                    {
                        "toolpath_length": float(obj.GetToolpathLength()),
                        "cutting_length": float(obj.GetToolpathCuttingLength()),
                        "toolpath_time_minutes": float(obj.GetToolpathTime()),
                        "cutting_time_minutes": float(obj.GetToolpathCuttingTime()),
                    }
                )
        except Exception as exc:
            record["path_error"] = str(exc)
    if (
        include_members
        and depth < max_depth
        and hasattr(obj, "GetMembers")
    ):
        record["members"] = [
            _cam_object_record(setup, member, True, depth + 1, max_depth)
            for member in obj.GetMembers()
        ]
    return record


def _cam_operations(setup):
    cam = _cam_module()
    root = setup.GetRoot(cam.CAMSetup.View.ProgramOrder)
    operations = []
    seen = set()

    def visit(obj):
        tag = int(obj.Tag)
        if tag in seen:
            return
        seen.add(tag)
        if setup.IsOperation(obj):
            operations.append(obj)
        elif hasattr(obj, "GetMembers"):
            for member in obj.GetMembers():
                visit(member)

    visit(root)
    return operations


def _cam_find_operation(setup, operation_name):
    name = _cam_safe_name("operation_name", operation_name)
    try:
        operation = setup.CAMOperationCollection.FindObject(name)
    except Exception:
        operation = None
    if operation is None or not setup.IsOperation(operation):
        raise ValueError("CAM operation was not found: %s" % name)
    return operation


def _cam_selected_operations(setup, operation_names):
    if operation_names is None:
        operations = _cam_operations(setup)
    else:
        if not isinstance(operation_names, list) or not operation_names:
            raise ValueError("operation_names must be a non-empty list or null")
        operations = [_cam_find_operation(setup, name) for name in operation_names]
    if not operations:
        raise RuntimeError("The CAM setup contains no operations")
    return operations


def _sim_module():
    import NXOpen.SIM

    return NXOpen.SIM


def _cam_find_program_group(setup, program_name):
    cam = _cam_module()
    name = _cam_safe_name("program_name", program_name)
    root = setup.GetRoot(cam.CAMSetup.View.ProgramOrder)
    seen = set()

    def visit(obj):
        tag = int(obj.Tag)
        if tag in seen:
            return None
        seen.add(tag)
        if getattr(obj, "Name", None) == name and setup.IsGroup(obj):
            return obj
        if hasattr(obj, "GetMembers"):
            for member in obj.GetMembers():
                found = visit(member)
                if found is not None:
                    return found
        return None

    group = visit(root)
    if group is None:
        raise ValueError("CAM program group was not found: %s" % name)
    return group


def _cam_operations_under(setup, obj):
    operations = []
    seen = set()

    def visit(item):
        tag = int(item.Tag)
        if tag in seen:
            return
        seen.add(tag)
        if setup.IsOperation(item):
            operations.append(item)
        elif hasattr(item, "GetMembers"):
            for member in item.GetMembers():
                visit(member)

    visit(obj)
    return operations


def _cam_simulation_selection(setup, operation_names=None, program_name=None):
    if operation_names is not None:
        operations = _cam_selected_operations(setup, operation_names)
        return operations, operations, {
            "mode": "operations",
            "operation_names": [item.Name for item in operations],
        }
    if program_name:
        group = _cam_find_program_group(setup, program_name)
        operations = _cam_operations_under(setup, group)
        if not operations:
            raise RuntimeError("The selected CAM program group contains no operations")
        return [group], operations, {
            "mode": "program_group",
            "program_name": group.Name,
            "operation_names": [item.Name for item in operations],
        }
    operations = _cam_selected_operations(setup, None)
    return operations, operations, {
        "mode": "all_operations",
        "operation_names": [item.Name for item in operations],
    }


def _machine_axis_matches(axis_names, required_axis):
    target = str(required_axis).strip().upper()
    if not target:
        return False
    for item in axis_names:
        name = str(item).strip().upper()
        if name == target or name.startswith(target):
            return True
    return False


def _safe_nx_error(exc):
    code = getattr(exc, "ErrorCode", None)
    return {
        "type": type(exc).__name__,
        "error_code": int(code) if code is not None else None,
    }


def _machine_library_catalog(kinematic, query=None, max_candidates=20):
    max_candidates = int(max_candidates)
    if not 1 <= max_candidates <= 100:
        raise ValueError("max_candidates must be between 1 and 100")
    normalized_query = ""
    if query is not None:
        if not isinstance(query, str):
            raise ValueError("machine_query must be a string or null")
        normalized_query = query.strip().lower()
        if len(normalized_query) > 80:
            raise ValueError("machine_query must not exceed 80 characters")
        if any(character in normalized_query for character in ("/", "\\", "\0", "\r", "\n")):
            raise ValueError("machine_query must be a library-name fragment, not a path")
    builder = kinematic.CreateMachineLibraryBuilder()
    try:
        names = [str(item) for item in builder.GetAllMachineNames()]
        matches = [
            name for name in names
            if normalized_query and normalized_query in name.lower()
        ][:max_candidates]
        return {
            "entry_count": len(names),
            "query": query.strip() if isinstance(query, str) else None,
            "matching_librefs": matches,
            "matching_count_returned": len(matches),
            "paths_redacted": True,
        }
    finally:
        builder.Destroy()


def _machine_library_entry(kinematic, machine_libref):
    libref = _cam_safe_name("machine_libref", machine_libref)
    builder = kinematic.CreateMachineLibraryBuilder()
    try:
        names = [str(item) for item in builder.GetAllMachineNames()]
        if libref not in names:
            raise ValueError("Machine library entry was not found: %s" % libref)
        attributes = {}
        for attribute in ("Type", "Description", "Control", "Manufacturer"):
            try:
                value = str(builder.GetValue(libref, attribute)).strip()
            except Exception:
                value = ""
            if value:
                attributes[attribute.lower()] = value
        return {
            "libref": libref,
            "attributes": attributes,
            "path_attributes_present": {
                "config_file": "config_file" in list(builder.GetAllAttributeNames()),
                "part_file_path": "part_file_path" in list(builder.GetAllAttributeNames()),
            },
            "paths_redacted": True,
        }
    finally:
        builder.Destroy()


def _machine_source_profiles(config_path=None):
    """Load local machine-source aliases without exposing filesystem paths."""
    path = os.path.abspath(config_path or MACHINE_SOURCE_CONFIG)
    if not os.path.isfile(path):
        return {}
    if os.path.getsize(path) > 64 * 1024:
        raise ValueError("machine source configuration exceeds 64 KiB")
    with io.open(path, "r", encoding="utf-8-sig") as stream:
        payload = json.load(stream)
    profiles = payload.get("profiles", payload)
    if not isinstance(profiles, dict):
        raise ValueError("machine source configuration must contain an object")
    return profiles


def _machine_source_profile(profile_name, config_path=None):
    profile_name = _cam_safe_name("source_profile", profile_name)
    raw = _machine_source_profiles(config_path).get(profile_name)
    if not isinstance(raw, dict):
        raise ValueError("unknown machine source profile")
    source_part = raw.get("source_part")
    if not isinstance(source_part, str) or not source_part.strip():
        raise ValueError("machine source profile has no source_part")
    source_part = os.path.abspath(os.path.expandvars(source_part.strip()))
    if os.path.splitext(source_part)[1].lower() != ".prt":
        raise ValueError("machine source profile source_part must be an NX .prt file")
    if not os.path.isfile(source_part):
        raise IOError("configured machine source part is unavailable")
    expected_axes = raw.get("expected_axes") or []
    if not isinstance(expected_axes, list):
        raise ValueError("expected_axes must be a list")
    expected_axes = [
        _cam_safe_name("expected_axis", str(axis)).upper() for axis in expected_axes
    ]
    machine_libref = raw.get("machine_libref")
    if machine_libref is not None:
        machine_libref = _cam_safe_name("machine_libref", machine_libref)
    controller = str(raw.get("expected_controller") or "").strip() or None
    kinematic_definition = raw.get("kinematic_definition")
    geometry_root = raw.get("geometry_root")
    if kinematic_definition is not None:
        if not isinstance(kinematic_definition, str) or not kinematic_definition.strip():
            raise ValueError("kinematic_definition must be a non-empty path")
        kinematic_definition = os.path.abspath(
            os.path.expandvars(kinematic_definition.strip())
        )
        if os.path.splitext(kinematic_definition)[1].lower() != ".mch":
            raise ValueError("kinematic_definition must be a .mch file")
        if not os.path.isfile(kinematic_definition):
            raise IOError("configured kinematic definition is unavailable")
    if geometry_root is not None:
        if not isinstance(geometry_root, str) or not geometry_root.strip():
            raise ValueError("geometry_root must be a non-empty path")
        geometry_root = os.path.abspath(os.path.expandvars(geometry_root.strip()))
        if not os.path.isdir(geometry_root):
            raise IOError("configured machine geometry root is unavailable")
    return {
        "name": profile_name,
        "source_part": source_part,
        "expected_axes": expected_axes,
        "expected_controller": controller,
        "machine_libref": machine_libref,
        "kinematic_definition": kinematic_definition,
        "geometry_root": geometry_root,
        "public": {
            "name": profile_name,
            "source_file_name": os.path.basename(source_part),
            "expected_axes": expected_axes,
            "expected_controller": controller,
            "machine_libref": machine_libref,
            "kinematic_definition_present": bool(kinematic_definition),
            "geometry_root_present": bool(geometry_root),
            "source_path_redacted": True,
        },
    }


def _xml_float(element, name, default=0.0):
    if element is None:
        return float(default)
    raw = element.get(name)
    return float(default if raw in (None, "") else raw)


def _xml_machine_reference_location(root):
    """Read the public numeric machine-reference row without exposing OEM metadata."""
    tables = [
        item
        for item in root.findall("./Table")
        if str(item.get("Name") or "").strip().casefold()
        == "machine reference location"
    ]
    if not tables:
        return None
    if len(tables) != 1:
        raise ValueError("machine definition contains duplicate reference-location tables")
    rows = list(tables[0].findall("./Row"))
    if not rows:
        raise ValueError("machine reference location has no rows")
    row = next(
        (
            item
            for item in rows
            if str(item.findtext("System") or "").strip() in ("", "1")
        ),
        rows[0],
    )
    values = []
    for item in row.findall("./Value"):
        raw = str(item.text or "").strip()
        if not raw:
            continue
        try:
            values.append(float(raw))
        except ValueError:
            raise ValueError("machine reference location must contain numeric values")
    if len(values) < 3:
        raise ValueError("machine reference location needs at least three values")
    return {
        "system": str(row.findtext("System") or "1").strip() or "1",
        "linear_axis_values": values[:3],
        "value_count": len(values),
    }


def _xml_machine_matrix(stl):
    matrix = stl.find("Matrix") if stl is not None else None
    origin = matrix.find("MatrixOrigin") if matrix is not None else None
    x_axis = matrix.find("MatrixXAxis") if matrix is not None else None
    y_axis = matrix.find("MatrixYAxis") if matrix is not None else None
    z_axis = matrix.find("MatrixZAxis") if matrix is not None else None
    return {
        "origin": [
            _xml_float(origin, "X"),
            _xml_float(origin, "Y"),
            _xml_float(origin, "Z"),
        ],
        "orientation": [
            _xml_float(x_axis, "X", 1.0),
            _xml_float(x_axis, "Y"),
            _xml_float(x_axis, "Z"),
            _xml_float(y_axis, "X"),
            _xml_float(y_axis, "Y", 1.0),
            _xml_float(y_axis, "Z"),
            _xml_float(z_axis, "X"),
            _xml_float(z_axis, "Y"),
            _xml_float(z_axis, "Z", 1.0),
        ],
    }


def _machine_matrix_is_identity(transform, tolerance=1.0e-9):
    expected = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    return all(abs(float(value)) <= tolerance for value in transform["origin"]) and all(
        abs(float(value) - expected[index]) <= tolerance
        for index, value in enumerate(transform["orientation"])
    )


def _machine_component_order(components):
    by_name = {item["name"]: item for item in components}
    states = {}
    ordered = []

    def visit(name):
        state = states.get(name, 0)
        if state == 1:
            raise ValueError("machine component hierarchy contains a cycle")
        if state == 2:
            return
        states[name] = 1
        parent = by_name[name].get("parent")
        if parent in by_name:
            visit(parent)
        states[name] = 2
        ordered.append(by_name[name])

    for item in components:
        visit(item["name"])
    return ordered


def _machine_kinematic_plan(profile):
    definition = profile.get("kinematic_definition")
    geometry_root = profile.get("geometry_root")
    if not definition or not geometry_root:
        raise ValueError(
            "machine source profile needs kinematic_definition and geometry_root"
        )
    root = ET.parse(definition).getroot()
    if root.tag != "VcMachine":
        raise ValueError("unsupported machine kinematic definition format")
    machine_reference_location = _xml_machine_reference_location(root)
    components = []
    names = set()
    missing_geometry = []
    transformed_geometry = []
    for element in root.findall("./Component"):
        name = _cam_safe_name("component_name", element.get("Name"))
        if name in names:
            raise ValueError("duplicate machine component name")
        names.add(name)
        component_type = str(element.get("Type") or "").strip().lower()
        if component_type not in (
            "base", "linear", "rotary", "spindle", "tool", "attach"
        ):
            raise ValueError("unsupported machine component type")
        parent = str(element.findtext("Attach") or "").strip() or None
        if parent is not None:
            parent = _cam_safe_name("component_parent", parent)
        position = element.find("Position")
        link = element.find("Link")
        travel = link.find("TlRecord") if link is not None else None
        geometry_files = []
        for stl in element.findall("STL"):
            file_node = stl.find("File")
            base_name = os.path.basename(
                str(file_node.text if file_node is not None else "").strip()
            )
            if not base_name or os.path.splitext(base_name)[1].lower() != ".stl":
                raise ValueError("machine component contains an invalid STL reference")
            geometry_path = os.path.abspath(os.path.join(geometry_root, base_name))
            if os.path.commonpath([geometry_root, geometry_path]) != geometry_root:
                raise ValueError("machine component geometry escapes geometry_root")
            exists = os.path.isfile(geometry_path)
            if not exists:
                missing_geometry.append(base_name)
            transform = _xml_machine_matrix(stl)
            transform_supported = _machine_matrix_is_identity(transform)
            if not transform_supported:
                transformed_geometry.append(base_name)
            geometry_files.append(
                {
                    "file_name": base_name,
                    "available": exists,
                    "transform": transform,
                    "direct_import_supported": transform_supported,
                }
            )
        record = {
            "name": name,
            "type": component_type,
            "parent": parent,
            "position": [
                _xml_float(position, "X"),
                _xml_float(position, "Y"),
                _xml_float(position, "Z"),
            ],
            "geometry": geometry_files,
        }
        if link is not None:
            record["axis"] = {
                "address": str(link.get("Register") or name).strip(),
                "direction": str(link.get("Axis") or "").strip().upper(),
                "lower_limit": _xml_float(travel, "TlMin") if travel is not None else None,
                "upper_limit": _xml_float(travel, "TlMax") if travel is not None else None,
                "unlimited": bool(
                    travel is not None
                    and str(travel.get("TlIgnore") or "").strip().lower() == "on"
                ),
            }
        components.append(record)
    if not components:
        raise ValueError("machine kinematic definition has no components")
    unknown_parents = sorted(
        set(item["parent"] for item in components if item["parent"])
        - set(item["name"] for item in components)
    )
    roots = [item["name"] for item in components if not item["parent"]]
    try:
        build_sequence = [
            item["name"] for item in _machine_component_order(components)
        ]
        hierarchy_cycle = False
    except ValueError:
        build_sequence = []
        hierarchy_cycle = True
    axes = [
        item["name"] for item in components if item["type"] in ("linear", "rotary")
    ]
    missing_axes = [
        axis for axis in profile["expected_axes"]
        if not _machine_axis_matches(axes, axis)
    ]
    collision_pairs = []
    unknown_collision_components = []
    for index, between in enumerate(root.findall("./Collision/Between")):
        pair_components = [
            str(item.text or "").strip()
            for item in between.findall("./Component")
        ]
        if len(pair_components) != 2 or not all(pair_components):
            raise ValueError("machine collision pair must contain two components")
        unknown_collision_components.extend(
            item for item in pair_components if item not in names
        )
        try:
            clearance = float(between.get("Tol") or 0.0)
        except (TypeError, ValueError):
            raise ValueError("machine collision clearance must be numeric")
        if clearance < 0.0:
            raise ValueError("machine collision clearance must be non-negative")
        collision_pairs.append(
            {
                "index": index,
                "first_component": pair_components[0],
                "second_component": pair_components[1],
                "clearance": clearance,
                "include_first_subcomponents": str(
                    between.get("Sub1") or "off"
                ).lower() == "on",
                "include_second_subcomponents": str(
                    between.get("Sub2") or "off"
                ).lower() == "on",
            }
        )
    blockers = []
    if unknown_parents:
        blockers.append("unknown_component_parent")
    if hierarchy_cycle:
        blockers.append("component_hierarchy_cycle")
    if len(roots) != 1 or not any(
        item["name"] == roots[0] and item["type"] == "base"
        for item in components
        if roots
    ):
        blockers.append("single_machine_base_required")
    if missing_geometry:
        blockers.append("component_geometry_missing")
    if transformed_geometry:
        blockers.append("component_geometry_transform_not_supported")
    if missing_axes:
        blockers.append("expected_axes_missing")
    if unknown_collision_components:
        blockers.append("unknown_collision_component")
    plan = {
        "ok": True,
        "profile": profile["public"],
        "source_format": "third_party_machine_xml",
        "components": components,
        "component_count": len(components),
        "axis_names": axes,
        "missing_expected_axes": missing_axes,
        "unknown_parents": unknown_parents,
        "root_components": roots,
        "build_sequence": build_sequence,
        "missing_geometry_file_names": sorted(set(missing_geometry)),
        "unsupported_transformed_geometry_file_names": sorted(
            set(transformed_geometry)
        ),
        "collision_pairs": collision_pairs,
        "collision_pair_count": len(collision_pairs),
        "unknown_collision_components": sorted(
            set(unknown_collision_components)
        ),
        "machine_reference_location": machine_reference_location,
        "blockers": blockers,
        "paths_redacted": True,
        "production_certified": False,
        "requires_engineering_validation": True,
    }
    coordinate_frame = _machine_reference_coordinate_frame(plan)
    plan["coordinate_frame"] = coordinate_frame
    if (
        machine_reference_location is not None
        and not coordinate_frame["reference_consistent_with_spindle"]
    ):
        blockers.append("machine_reference_location_inconsistent")
    plan["machine_kit_build_ready"] = not blockers
    return plan


def _op_inspect_machine_kinematic_plan(params):
    profile = _machine_source_profile(params.get("source_profile"))
    return _machine_kinematic_plan(profile)


def _open_machine_source_for_inspection(profile):
    """Open a configured source part without displaying it and return safe metadata."""
    session = NXOpen.Session.GetSession()
    before_work = session.Parts.Work
    before_display = session.Parts.Display
    source_path = profile["source_part"]
    normalized_source = os.path.normcase(os.path.realpath(source_path))
    already_loaded = None
    try:
        for candidate in session.Parts:
            candidate_path = getattr(candidate, "FullPath", "")
            if candidate_path and os.path.normcase(os.path.realpath(candidate_path)) == normalized_source:
                already_loaded = candidate
                break
    except Exception:
        already_loaded = None

    opened_here = already_loaded is None
    part = already_loaded
    load_status = None
    unloaded_parts = None
    close_error = None
    record = None
    try:
        if part is None:
            part, load_status = session.Parts.Open(source_path)
            unloaded_parts = int(load_status.NumberUnloadedParts)
        if part is None or getattr(part, "Tag", 0) == 0:
            raise RuntimeError("NX did not open the configured machine source part")
        kinematic_error = None
        try:
            kinematic = part.KinematicConfigurator
            kinematic_name = str(kinematic.GetName())
            axis_names = [str(item) for item in kinematic.GetAxisNames()]
            channels = [str(item) for item in kinematic.GetChannels()]
            junction_names = [str(item) for item in kinematic.GetJunctionNames()]
        except Exception as exc:
            kinematic_name = None
            axis_names = []
            channels = []
            junction_names = []
            kinematic_error = _safe_nx_error(exc)
        expected_axes = profile["expected_axes"]
        missing_axes = [
            axis for axis in expected_axes if not _machine_axis_matches(axis_names, axis)
        ]
        try:
            assembly_root_present = bool(part.ComponentAssembly.RootComponent)
        except Exception:
            assembly_root_present = False
        layer_counts = {}
        named_bodies = []
        all_bodies = list(part.Bodies)
        for body in all_bodies:
            layer = int(getattr(body, "Layer", 0))
            layer_counts[str(layer)] = layer_counts.get(str(layer), 0) + 1
            body_name = str(getattr(body, "Name", "") or "").strip()
            if body_name and len(named_bodies) < 50:
                named_bodies.append({"name": body_name, "layer": layer})
        blockers = []
        if kinematic_error is not None:
            blockers.append("kinematic_model_not_initialized")
        if not channels:
            blockers.append("no_kinematic_channel")
        if missing_axes:
            blockers.append("expected_axes_missing")
        record = {
            "ok": True,
            "profile": profile["public"],
            "source": {
                "part_name": getattr(part, "Leaf", None),
                "body_count": len(all_bodies),
                "assembly_root_present": assembly_root_present,
                "body_layer_counts": layer_counts,
                "named_body_sample": named_bodies,
                "named_body_sample_truncated": len(named_bodies) == 50,
                "opened_for_inspection": opened_here,
                "displayed": part == session.Parts.Display,
                "path_redacted": True,
            },
            "kinematics": {
                "name": kinematic_name,
                "axis_names": axis_names,
                "channels": channels,
                "junction_count": len(junction_names),
                "expected_axes": expected_axes,
                "missing_expected_axes": missing_axes,
            },
            "load": {"unloaded_part_count": unloaded_parts},
            "machine_source_ready": not blockers,
            "blockers": blockers,
            "current_work_part_preserved": session.Parts.Work == before_work,
            "current_display_part_preserved": session.Parts.Display == before_display,
            "saved": False,
        }
        if kinematic_error is not None:
            record["kinematics"]["read_error"] = kinematic_error
    finally:
        if load_status is not None:
            load_status.Dispose()
        if opened_here and part is not None and getattr(part, "Tag", 0) != 0:
            responses = session.Parts.NewPartCloseResponses()
            try:
                part.Close(
                    NXOpen.BasePart.CloseWholeTree.TrueValue,
                    (
                        NXOpen.BasePart.CloseModified.CloseModified
                        if safe_import_part
                        else NXOpen.BasePart.CloseModified.DontCloseModified
                    ),
                    responses,
                )
            except Exception as exc:
                close_error = _safe_nx_error(exc)
            finally:
                responses.Dispose()
    if record is None:
        raise RuntimeError("NX machine source inspection returned no record")
    if close_error is not None:
        record["source"]["close_warning"] = close_error
    record["source"]["closed_after_inspection"] = bool(
        opened_here and close_error is None
    )
    return record


def _op_inspect_machine_source_profile(params):
    profile = _machine_source_profile(params.get("source_profile"))
    return _open_machine_source_for_inspection(profile)


def _machine_build_part_path(file_name):
    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("workspace_file_name must be a non-empty string")
    file_name = file_name.strip()
    if os.path.basename(file_name) != file_name or file_name in (".", ".."):
        raise ValueError("workspace_file_name must be a plain file name")
    if not file_name.lower().endswith(".prt"):
        file_name += ".prt"
    root = os.path.abspath(os.path.join(WORKSPACE, "machine_builds"))
    path = os.path.abspath(os.path.join(root, file_name))
    if os.path.commonpath([root, path]) != root:
        raise ValueError("machine build path escapes NX_MCP_WORKSPACE")
    return root, path


def _machine_file_fingerprint(path):
    digest = hashlib.sha256()
    with io.open(path, "rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return {"size": int(os.path.getsize(path)), "sha256": digest.hexdigest()}


def _machine_kit_path(file_name, must_exist=False):
    """Resolve a plain MTK file name inside the workspace machine-kit folder."""
    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("output_file_name must be a non-empty string")
    file_name = file_name.strip()
    if os.path.basename(file_name) != file_name or file_name in (".", ".."):
        raise ValueError("output_file_name must be a plain file name")
    if not file_name.lower().endswith(".mtk"):
        file_name += ".mtk"
    root = os.path.abspath(os.path.join(WORKSPACE, "machine_kits"))
    path = os.path.abspath(os.path.join(root, file_name))
    if os.path.commonpath([root, path]) != root:
        raise ValueError("machine kit path escapes NX_MCP_WORKSPACE")
    if must_exist and not os.path.isfile(path):
        raise IOError("machine kit does not exist: %s" % file_name)
    return root, path


def _machine_kit_identifier(file_name):
    """Return an NX-library-safe identifier derived from a plain MTK name."""
    stem = os.path.splitext(os.path.basename(file_name))[0].strip()
    if not stem:
        raise ValueError("machine kit file name has no stem")
    identifier = "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in stem
    ).strip("_")
    if not identifier:
        raise ValueError("machine kit file name has no usable identifier")
    if len(identifier) > 64:
        identifier = identifier[:64].rstrip("_")
    return identifier


def _xml_child(parent, local_name):
    wanted = str(local_name).lower()
    for child in list(parent):
        if str(child.tag).rsplit("}", 1)[-1].lower() == wanted:
            return child
    return None


def _xml_descendant_by_name_attribute(parent, name):
    wanted = str(name).lower()
    for child in parent.iter():
        if str(child.attrib.get("name", "")).lower() == wanted:
            return child
    return None


def _machine_kit_sanitized_manifest(
    manifest_bytes, kit_identifier, graphics_file_name, nx_version="NX 2412"
):
    """Retarget a Siemens-exported kit manifest and remove private metadata."""
    root = ET.fromstring(manifest_bytes)
    kit_name_node = _xml_child(root, "name")
    meta = _xml_child(root, "meta_data")
    database = _xml_child(root, "database_entry")
    content = _xml_child(root, "content")
    if kit_name_node is None or meta is None or database is None or content is None:
        raise RuntimeError("reference machine kit manifest has an unsupported schema")

    kit_name_node.text = kit_identifier
    for child in list(meta):
        meta.remove(child)
    ET.SubElement(meta, "provider").text = "NX MCP"
    ET.SubElement(meta, "export_date").text = time.strftime("%Y-%m-%dT%H:%M:%S")
    ET.SubElement(meta, "nx_version").text = str(nx_version or "NX 2412")

    graphics_stem = os.path.splitext(graphics_file_name)[0]
    public_database_values = {
        "libref": kit_identifier,
        "type": "MDM0101",
        "description": "Five-axis vertical BC-table machining center",
        "control": "HEIDENHAIN TNC 640",
        "manufacturer": "Mikron",
        "config_file": (
            "${UGII_CAM_LIBRARY_INSTALLED_MACHINES_DIR}%s/%s.dat"
            % (kit_identifier, kit_identifier)
        ),
        "part_file_path": (
            "${UGII_CAM_LIBRARY_INSTALLED_MACHINES_DIR}%s/graphics/%s"
            % (kit_identifier, graphics_stem)
        ),
    }
    for tag_name, value in public_database_values.items():
        node = _xml_child(database, tag_name)
        if node is None:
            node = ET.SubElement(database, tag_name)
        node.text = value

    top_folder = next(
        (
            item for item in list(content)
            if str(item.tag).rsplit("}", 1)[-1].lower() == "folder"
        ),
        None,
    )
    if top_folder is None:
        raise RuntimeError("reference machine kit manifest has no content root")
    old_root = str(top_folder.attrib.get("name", "") or "")
    top_folder.set("name", kit_identifier)
    graphics = _xml_descendant_by_name_attribute(top_folder, "graphics")
    if graphics is None:
        raise RuntimeError("reference machine kit manifest has no graphics folder")
    example_file = next(
        (
            item for item in graphics.iter()
            if item is not graphics
            and str(item.tag).rsplit("}", 1)[-1].lower() == "file"
        ),
        None,
    )
    for child in list(graphics):
        graphics.remove(child)
    file_tag = example_file.tag if example_file is not None else "file"
    file_attributes = dict(example_file.attrib) if example_file is not None else {}
    file_attributes["name"] = graphics_file_name
    file_attributes["origin"] = "MachineLibrary"
    ET.SubElement(graphics, file_tag, file_attributes)

    serialized = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    lowered = serialized.lower()
    for forbidden in (b"sold_to", b"license", b"username"):
        if forbidden in lowered:
            raise RuntimeError("machine kit manifest sanitization was incomplete")
    return serialized, old_root


def _machine_kit_repackage_reference(
    reference_archive,
    output_archive,
    part_path,
    kit_identifier,
    graphics_file_name=None,
):
    """Create an atomic, complete OEM kit from an NX-exported reference kit."""
    descriptor, temporary = tempfile.mkstemp(
        prefix=".nxmcp-mtk-", suffix=".mtk", dir=os.path.dirname(output_archive)
    )
    os.close(descriptor)
    requested_graphics_name = str(graphics_file_name or "").strip()
    if requested_graphics_name:
        if (
            os.path.basename(requested_graphics_name) != requested_graphics_name
            or os.path.splitext(requested_graphics_name)[1].lower() != ".prt"
        ):
            raise ValueError("graphics_file_name must be a plain .prt file name")
        graphics_stem = os.path.splitext(requested_graphics_name)[0]
        if _machine_kit_identifier(requested_graphics_name) != graphics_stem:
            raise ValueError(
                "graphics_file_name stem must already be NX-library-safe"
            )
        graphics_file_name = requested_graphics_name
    else:
        graphics_file_name = kit_identifier + ".prt"
    try:
        with zipfile.ZipFile(reference_archive, "r") as source:
            try:
                manifest_bytes = source.read("kit_information.xml")
            except KeyError:
                raise RuntimeError("reference machine kit has no kit_information.xml")
            manifest, old_root = _machine_kit_sanitized_manifest(
                manifest_bytes, kit_identifier, graphics_file_name
            )
            if not old_root:
                raise RuntimeError("reference machine kit content root is empty")
            old_prefix = old_root.rstrip("/") + "/"
            new_prefix = kit_identifier + "/"
            with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
            ) as target:
                target.writestr("kit_information.xml", manifest)
                for item in source.infolist():
                    name = item.filename.replace("\\", "/")
                    if name == "kit_information.xml":
                        continue
                    if not name.startswith(old_prefix):
                        continue
                    relative = name[len(old_prefix):]
                    if relative.lower().startswith("graphics/"):
                        continue
                    target.writestr(new_prefix + relative, source.read(item.filename))
                with io.open(part_path, "rb") as stream:
                    target.writestr(
                        new_prefix + "graphics/" + graphics_file_name,
                        stream.read(),
                    )
        with zipfile.ZipFile(temporary, "r") as verification:
            members = verification.infolist()
            names = [item.filename for item in members]
            required = {
                "kit_information.xml",
                kit_identifier + "/graphics/" + graphics_file_name,
            }
            if not required.issubset(set(names)):
                raise RuntimeError("machine kit archive is missing required content")
            if len(members) < 10:
                raise RuntimeError("machine kit archive is unexpectedly incomplete")
            manifest_check = verification.read("kit_information.xml").lower()
            if b"sold_to" in manifest_check or b"license" in manifest_check:
                raise RuntimeError("machine kit archive contains private metadata")
            has_cse = any("/cse_driver/" in name.lower() for name in names)
            has_post = any("/postprocessor/" in name.lower() for name in names)
            if not has_cse or not has_post:
                raise RuntimeError("machine kit archive lacks CSE or post resources")
        os.replace(temporary, output_archive)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)

    fingerprint = _machine_file_fingerprint(output_archive)
    with zipfile.ZipFile(output_archive, "r") as archive:
        names = archive.namelist()
    return {
        "file_name": os.path.basename(output_archive),
        "size": fingerprint["size"],
        "sha256": fingerprint["sha256"],
        "member_count": len(names),
        "graphics_part": graphics_file_name,
        "has_cse_driver": any("/cse_driver/" in name.lower() for name in names),
        "has_postprocessor": any("/postprocessor/" in name.lower() for name in names),
        "metadata_sanitized": True,
        "paths_redacted": True,
    }


def _machine_kit_is_verified_reference_container(path):
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        return False
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = archive.namelist()
            if archive.testzip() is not None or len(names) < 10:
                return False
            manifest = archive.read("kit_information.xml").lower()
    except (IOError, KeyError, zipfile.BadZipFile):
        return False
    if any(item in manifest for item in (b"sold_to", b"license", b"username")):
        return False
    return (
        any("/graphics/" in name.lower() and name.lower().endswith(".prt") for name in names)
        and any("/cse_driver/" in name.lower() for name in names)
        and any("/postprocessor/" in name.lower() for name in names)
    )


def _machine_workspace_token(profile_name, file_name, fingerprint, recovery_path):
    payload = "|".join(
        (
            str(profile_name),
            str(file_name),
            str(fingerprint["sha256"]),
            os.path.normcase(str(recovery_path or "")),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _machine_manifest_path(part_path):
    return part_path + ".nxmcp.json"


def _machine_write_manifest(path, payload):
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".nxmcp-machine-", suffix=".json", dir=folder
    )
    os.close(descriptor)
    try:
        with io.open(temporary, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _machine_read_manifest(part_path):
    path = _machine_manifest_path(part_path)
    if not os.path.isfile(path):
        raise IOError("machine build manifest is missing")
    if os.path.getsize(path) > 64 * 1024:
        raise ValueError("machine build manifest exceeds 64 KiB")
    with io.open(path, "r", encoding="utf-8-sig") as stream:
        manifest = json.load(stream)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("machine build manifest is invalid")
    if os.path.basename(part_path) != manifest.get("workspace_file_name"):
        raise ValueError("machine build manifest does not match the workspace part")
    return manifest


def _machine_manifest_public(manifest, target_exists):
    return {
        "schema_version": manifest["schema_version"],
        "source_profile": manifest["source_profile"],
        "source_file_name": manifest["source_file_name"],
        "workspace_file_name": manifest["workspace_file_name"],
        "source_fingerprint": manifest["source_fingerprint"],
        "recovery_part_file_name": manifest.get("recovery_part_file_name"),
        "recovery_token": manifest["recovery_token"],
        "workspace_strategy": manifest.get(
            "workspace_strategy", "source_part_copy"
        ),
        "target_exists": bool(target_exists),
        "paths_redacted": True,
    }


def _op_create_machine_build_workspace(params):
    profile = _machine_source_profile(params.get("source_profile"))
    plan = _machine_kinematic_plan(profile)
    root, target = _machine_build_part_path(params.get("workspace_file_name"))
    source_fingerprint = _machine_file_fingerprint(profile["source_part"])
    work = NXOpen.Session.GetSession().Parts.Work
    recovery_path = ""
    recovery_file_name = None
    if work is not None and getattr(work, "Tag", 0) != 0:
        recovery_path = str(getattr(work, "FullPath", "") or "")
        recovery_file_name = os.path.basename(recovery_path) or getattr(
            work, "Leaf", None
        )
    manifest = {
        "schema_version": 1,
        "created_by": "nx-mcp",
        "workspace_strategy": "source_part_copy",
        "source_profile": profile["name"],
        "source_file_name": os.path.basename(profile["source_part"]),
        "source_fingerprint": source_fingerprint,
        "workspace_file_name": os.path.basename(target),
        "recovery_part_path": recovery_path or None,
        "recovery_part_file_name": recovery_file_name,
        "recovery_token": _machine_workspace_token(
            profile["name"], os.path.basename(target), source_fingerprint, recovery_path
        ),
        "expected_axes": list(profile["expected_axes"]),
        "expected_controller": profile.get("expected_controller"),
        "source_paths_redacted_in_api": True,
    }
    dry_run = bool(params.get("dry_run", True))
    public = _machine_manifest_public(manifest, os.path.isfile(target))
    public.update(
        {
            "ok": bool(plan["machine_kit_build_ready"]),
            "dry_run": dry_run,
            "changed": False,
            "build_plan_ready": bool(plan["machine_kit_build_ready"]),
            "build_plan_blockers": list(plan["blockers"]),
            "component_count": int(plan["component_count"]),
            "axis_names": list(plan["axis_names"]),
            "copy_strategy": "source_part_to_isolated_workspace",
            "source_unchanged": True,
            "nx_display_unchanged": True,
            "requires_explicit_commit": True,
        }
    )
    if dry_run:
        return public
    if params.get("confirmation") != _MACHINE_WORKSPACE_CONFIRMATION:
        raise PermissionError(
            "Creating a machine build workspace requires confirmation=%s"
            % _MACHINE_WORKSPACE_CONFIRMATION
        )
    if not plan["machine_kit_build_ready"]:
        raise RuntimeError(
            "Machine build plan is not ready; blockers=%s"
            % ",".join(plan["blockers"])
        )
    if os.path.exists(target) or os.path.exists(_machine_manifest_path(target)):
        raise IOError(
            "machine build workspace already exists; choose a new workspace_file_name"
        )
    if not os.path.isdir(root):
        os.makedirs(root)
    temporary = target + ".partial-%s" % os.getpid()
    try:
        shutil.copy2(profile["source_part"], temporary)
        copied = _machine_file_fingerprint(temporary)
        if copied != source_fingerprint:
            raise IOError("machine source copy verification failed")
        os.replace(temporary, target)
        _machine_write_manifest(_machine_manifest_path(target), manifest)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    public = _machine_manifest_public(manifest, True)
    public.update(
        {
            "ok": True,
            "dry_run": False,
            "changed": True,
            "source_unchanged": True,
            "nx_display_unchanged": True,
            "saved_copy": True,
        }
    )
    return public


def _op_create_smart_machine_kit_workspace(params):
    profile = _machine_source_profile(params.get("source_profile"))
    plan = _machine_kinematic_plan(profile)
    root, target = _machine_build_part_path(params.get("workspace_file_name"))
    source_fingerprint = _machine_file_fingerprint(profile["source_part"])
    session = NXOpen.Session.GetSession()
    current = session.Parts.Work
    recovery_path = (
        str(getattr(current, "FullPath", "") or "") if current is not None else ""
    )
    recovery_file_name = (
        os.path.basename(recovery_path)
        or (getattr(current, "Leaf", None) if current is not None else None)
    )
    manifest = {
        "schema_version": 1,
        "created_by": "nx-mcp",
        "workspace_strategy": "blank_smart_machine_kit",
        "source_profile": profile["name"],
        "source_file_name": os.path.basename(profile["source_part"]),
        "source_fingerprint": source_fingerprint,
        "workspace_file_name": os.path.basename(target),
        "recovery_part_path": recovery_path or None,
        "recovery_part_file_name": recovery_file_name,
        "recovery_token": _machine_workspace_token(
            profile["name"], os.path.basename(target), source_fingerprint, recovery_path
        ),
        "expected_axes": list(profile["expected_axes"]),
        "expected_controller": profile.get("expected_controller"),
        "source_paths_redacted_in_api": True,
    }
    dry_run = bool(params.get("dry_run", True))
    public = _machine_manifest_public(manifest, os.path.isfile(target))
    public.update(
        {
            "ok": bool(plan["machine_kit_build_ready"]),
            "dry_run": dry_run,
            "changed": False,
            "build_plan_ready": bool(plan["machine_kit_build_ready"]),
            "build_plan_blockers": list(plan["blockers"]),
            "component_count": int(plan["component_count"]),
            "axis_names": list(plan["axis_names"]),
            "copy_strategy": "new_blank_nx_part_for_smart_machine_kit",
            "source_unchanged": True,
            "requires_explicit_commit": True,
        }
    )
    if dry_run:
        return public
    if params.get("confirmation") != _SMART_MACHINE_KIT_WORKSPACE_CONFIRMATION:
        raise PermissionError(
            "Creating a Smart Machine Kit workspace requires confirmation=%s"
            % _SMART_MACHINE_KIT_WORKSPACE_CONFIRMATION
        )
    if not plan["machine_kit_build_ready"]:
        raise RuntimeError(
            "Machine build plan is not ready; blockers=%s"
            % ",".join(plan["blockers"])
        )
    if os.path.exists(target) or os.path.exists(_machine_manifest_path(target)):
        raise IOError(
            "machine build workspace already exists; choose a new workspace_file_name"
        )
    if not os.path.isdir(root):
        os.makedirs(root)
    part = None
    save_status = None
    try:
        session.Parts.SetAllowMultipleDisplayedParts(True)
        part = session.Parts.NewDisplay(target, NXOpen.Part.Units.Millimeters)
        save_status = part.Save(
            NXOpen.BasePart.SaveComponents.TrueValue,
            NXOpen.BasePart.CloseAfterSave.FalseValue,
        )
        if int(getattr(save_status, "NumberUnsavedParts", 0) or 0):
            raise RuntimeError("NX could not save the blank Smart Machine Kit part")
        if not os.path.isfile(target):
            raise RuntimeError("NX did not create the Smart Machine Kit workspace part")
        _machine_write_manifest(_machine_manifest_path(target), manifest)
    finally:
        if save_status is not None:
            try:
                save_status.Dispose()
            except Exception:
                pass
    public = _machine_manifest_public(manifest, True)
    public.update(
        {
            "ok": True,
            "dry_run": False,
            "changed": True,
            "source_unchanged": True,
            "active_part_file_name": os.path.basename(target),
            "previous_part_preserved_in_session": current is not None,
            "saved_blank_workspace": True,
            "kinematics_initialized": False,
        }
    )
    return public


def _machine_normalized_path(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _machine_path_is_within(root, path):
    normalized_root = _machine_normalized_path(root)
    normalized_path = _machine_normalized_path(path)
    try:
        return os.path.commonpath([normalized_root, normalized_path]) == normalized_root
    except ValueError:
        return False


def _machine_require_active_workspace(part_path):
    work = _work_part()
    active = str(getattr(work, "FullPath", "") or "")
    if not active or _machine_normalized_path(active) != _machine_normalized_path(
        part_path
    ):
        raise RuntimeError(
            "The requested machine build workspace must be the active NX work part"
        )
    return work


def _op_activate_machine_build_workspace(params):
    _root, target = _machine_build_part_path(params.get("workspace_file_name"))
    if not os.path.isfile(target):
        raise IOError("machine build workspace does not exist")
    manifest = _machine_read_manifest(target)
    supplied_token = str(params.get("recovery_token") or "").strip()
    if supplied_token != manifest["recovery_token"]:
        raise PermissionError("recovery_token does not match the workspace manifest")
    session = NXOpen.Session.GetSession()
    current = session.Parts.Work
    current_path = str(getattr(current, "FullPath", "") or "") if current else ""
    preserve_current = bool(params.get("preserve_current", True))
    already_active = bool(
        current_path
        and _machine_normalized_path(current_path) == _machine_normalized_path(target)
    )
    result = {
        "ok": True,
        "workspace_file_name": os.path.basename(target),
        "previous_part_file_name": os.path.basename(current_path) or None,
        "dry_run": bool(params.get("dry_run", True)),
        "changed": False,
        "already_active": already_active,
        "preserve_current": preserve_current,
        "current_part_modified": bool(
            current is not None and getattr(current, "IsModified", False)
        ),
        "paths_redacted": True,
        "requires_explicit_commit": True,
    }
    if result["dry_run"] or already_active:
        return result
    if params.get("confirmation") != _MACHINE_WORKSPACE_ACTIVATE_CONFIRMATION:
        raise PermissionError(
            "Activating a machine build workspace requires confirmation=%s"
            % _MACHINE_WORKSPACE_ACTIVATE_CONFIRMATION
        )
    if (
        current is not None
        and bool(getattr(current, "IsModified", False))
        and not preserve_current
    ):
        raise RuntimeError("Save or discard current NX part changes before activation")
    load_status = None
    try:
        display_option = NXOpen.DisplayPartOption.ReplaceExisting
        if preserve_current:
            session.Parts.SetAllowMultipleDisplayedParts(True)
            display_option = NXOpen.DisplayPartOption.AllowAdditional
        part = None
        for candidate in session.Parts:
            candidate_path = str(getattr(candidate, "FullPath", "") or "")
            if (
                candidate_path
                and _machine_normalized_path(candidate_path)
                == _machine_normalized_path(target)
            ):
                part = candidate
                break
        if part is None:
            part, load_status = session.Parts.OpenActiveDisplay(
                target, display_option
            )
        else:
            _status, load_status = session.Parts.SetActiveDisplay(
                part,
                display_option,
                NXOpen.PartDisplayPartWorkPartOption.SameAsDisplay,
            )
        unloaded = int(load_status.NumberUnloadedParts)
        if unloaded:
            raise RuntimeError("NX reported unloaded parts while activating workspace")
        active = _work_part()
        if _machine_normalized_path(active.FullPath) != _machine_normalized_path(target):
            raise RuntimeError("NX did not activate the requested machine workspace")
    except Exception as exc:
        recovery = manifest.get("recovery_part_path")
        if not preserve_current and recovery and os.path.isfile(recovery):
            try:
                recovered, recovery_status = session.Parts.OpenActiveDisplay(
                    recovery, NXOpen.DisplayPartOption.ReplaceExisting
                )
                recovery_status.Dispose()
            except Exception:
                pass
        safe = _safe_nx_error(exc)
        raise RuntimeError(
            "NX workspace activation failed (type=%s, error_code=%s); recovery was attempted"
            % (safe["type"], safe["error_code"])
        )
    finally:
        if load_status is not None:
            load_status.Dispose()
    result.update(
        {
            "dry_run": False,
            "changed": True,
            "already_active": False,
            "active_part_file_name": os.path.basename(target),
            "previous_part_preserved_in_session": preserve_current,
            "saved": False,
        }
    )
    return result


def _op_restore_machine_build_recovery_part(params):
    """Restore the recorded pre-build NX part without accepting a caller-supplied path."""
    _root, target = _machine_build_part_path(params.get("workspace_file_name"))
    if not os.path.isfile(target):
        raise IOError("machine build workspace does not exist")
    manifest = _machine_read_manifest(target)
    supplied_token = str(params.get("recovery_token") or "").strip()
    if supplied_token != manifest["recovery_token"]:
        raise PermissionError("recovery_token does not match the workspace manifest")
    recovery = str(manifest.get("recovery_part_path") or "").strip()
    if not recovery or not os.path.isfile(recovery):
        raise IOError("recorded recovery part is unavailable")
    if os.path.splitext(recovery)[1].lower() != ".prt":
        raise ValueError("recorded recovery target is not an NX part")
    session = NXOpen.Session.GetSession()
    current = session.Parts.Work
    current_path = str(getattr(current, "FullPath", "") or "") if current else ""
    already_active = bool(
        current_path
        and _machine_normalized_path(current_path) == _machine_normalized_path(recovery)
    )
    result = {
        "ok": True,
        "workspace_file_name": os.path.basename(target),
        "recovery_part_file_name": os.path.basename(recovery),
        "dry_run": bool(params.get("dry_run", True)),
        "changed": False,
        "already_active": already_active,
        "current_part_modified": bool(
            current is not None and getattr(current, "IsModified", False)
        ),
        "paths_redacted": True,
        "requires_explicit_commit": True,
    }
    if result["dry_run"] or already_active:
        return result
    if params.get("confirmation") != _MACHINE_WORKSPACE_RESTORE_CONFIRMATION:
        raise PermissionError(
            "Restoring the machine-build recovery part requires confirmation=%s"
            % _MACHINE_WORKSPACE_RESTORE_CONFIRMATION
        )
    if result["current_part_modified"]:
        raise RuntimeError("Save the active machine workspace before restoring the recovery part")
    recovery_part = None
    for candidate in session.Parts:
        candidate_path = str(getattr(candidate, "FullPath", "") or "")
        if (
            candidate_path
            and _machine_normalized_path(candidate_path)
            == _machine_normalized_path(recovery)
        ):
            recovery_part = candidate
            break
    load_status = None
    try:
        if recovery_part is None:
            recovery_part, load_status = session.Parts.OpenActiveDisplay(
                recovery, NXOpen.DisplayPartOption.AllowAdditional
            )
        else:
            _status, load_status = session.Parts.SetActiveDisplay(
                recovery_part,
                NXOpen.DisplayPartOption.AllowAdditional,
                NXOpen.PartDisplayPartWorkPartOption.SameAsDisplay,
            )
        active = _work_part()
        if _machine_normalized_path(active.FullPath) != _machine_normalized_path(recovery):
            raise RuntimeError("NX did not restore the recorded recovery part")
    finally:
        if load_status is not None:
            load_status.Dispose()
    result.update(
        {
            "dry_run": False,
            "changed": True,
            "already_active": False,
            "active_part_file_name": os.path.basename(recovery),
            "machine_workspace_preserved_in_session": True,
        }
    )
    return result


def _machine_component_selection(plan, component_names=None):
    by_name = {item["name"]: item for item in plan["components"]}
    if component_names is None:
        wanted = [name for name in plan["build_sequence"] if by_name[name]["geometry"]]
    else:
        if not isinstance(component_names, list) or not component_names:
            raise ValueError("component_names must be a non-empty list or null")
        wanted = [_cam_safe_name("component_name", item) for item in component_names]
    unknown = sorted(set(wanted) - set(by_name))
    if unknown:
        raise ValueError("unknown machine components: %s" % ",".join(unknown))
    return [by_name[name] for name in plan["build_sequence"] if name in wanted]


def _machine_geometry_prefix(component_name, file_name):
    stem = os.path.splitext(file_name)[0]
    safe_stem = "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in stem
    )
    return "MCP_MACHINE_%s_%s" % (component_name.upper(), safe_stem.upper())


def _facet_module():
    import NXOpen.Facet

    return NXOpen.Facet


def _machine_object_bounds(obj):
    try:
        import NXOpen.UF

        box = [
            float(value)
            for value in NXOpen.UF.UFSession.GetUFSession().ModlGeneral.AskBoundingBox(
                int(obj.Tag)
            )
        ]
        if len(box) != 6:
            raise ValueError("invalid bounding box")
        return {
            "min": box[:3],
            "max": box[3:],
            "size": [box[index + 3] - box[index] for index in range(3)],
            "method": "UF_MODL_ask_bounding_box",
        }
    except Exception:
        return None


def _machine_faceted_bodies(work):
    try:
        collection = work.FacetedBodies
        if hasattr(collection, "ToArray"):
            return list(collection.ToArray())
        return list(collection)
    except Exception:
        return []


def _machine_named_geometry(work):
    records = []
    for body in _machine_faceted_bodies(work):
        name = str(getattr(body, "Name", "") or "")
        if not name.startswith("MCP_MACHINE_"):
            continue
        records.append(
            {
                "name": name,
                "tag": int(body.Tag),
                "layer": int(getattr(body, "Layer", 0)),
                "bounds": _machine_object_bounds(body),
            }
        )
    return records


def _op_import_machine_component_geometry(params):
    profile = _machine_source_profile(params.get("source_profile"))
    plan = _machine_kinematic_plan(profile)
    _root, target = _machine_build_part_path(params.get("workspace_file_name"))
    if not os.path.isfile(target):
        raise IOError("machine build workspace does not exist")
    manifest = _machine_read_manifest(target)
    if manifest["source_profile"] != profile["name"]:
        raise ValueError("workspace source profile does not match the request")
    components = _machine_component_selection(plan, params.get("component_names"))
    start_layer = int(params.get("start_layer", 201))
    if not 1 <= start_layer <= 256 or start_layer + len(components) - 1 > 256:
        raise ValueError("component layers must stay between 1 and 256")
    requested = []
    for component_index, component in enumerate(components):
        for geometry in component["geometry"]:
            requested.append(
                {
                    "component": component["name"],
                    "file_name": geometry["file_name"],
                    "layer": start_layer + component_index,
                    "direct_import_supported": geometry[
                        "direct_import_supported"
                    ],
                    "name_prefix": _machine_geometry_prefix(
                        component["name"], geometry["file_name"]
                    ),
                }
            )
    dry_run = bool(params.get("dry_run", True))
    result = {
        "ok": bool(plan["machine_kit_build_ready"]),
        "part": os.path.basename(target),
        "source_profile": profile["public"],
        "dry_run": dry_run,
        "changed": False,
        "requested_file_count": len(requested),
        "requested_geometry": requested,
        "paths_redacted": True,
        "requires_explicit_commit": True,
    }
    if dry_run:
        return result
    if params.get("confirmation") != _MACHINE_GEOMETRY_IMPORT_CONFIRMATION:
        raise PermissionError(
            "Importing machine geometry requires confirmation=%s"
            % _MACHINE_GEOMETRY_IMPORT_CONFIRMATION
        )
    if not plan["machine_kit_build_ready"]:
        raise RuntimeError(
            "Machine build plan is not ready; blockers=%s"
            % ",".join(plan["blockers"])
        )
    work = _machine_require_active_workspace(target)
    session = NXOpen.Session.GetSession()
    facet = _facet_module()
    existing = _machine_named_geometry(work)
    existing_names = set(item["name"] for item in existing)
    imported = []
    skipped = []
    mark_name = "NX MCP Import Machine Component Geometry"
    mark = session.SetUndoMark(session.MarkVisibility.Visible, mark_name)
    try:
        for item in requested:
            prefix = item["name_prefix"]
            if any(name == prefix or name.startswith(prefix + "_") for name in existing_names):
                skipped.append({"component": item["component"], "file_name": item["file_name"]})
                continue
            source_path = os.path.abspath(
                os.path.join(profile["geometry_root"], item["file_name"])
            )
            before = set(int(body.Tag) for body in _machine_faceted_bodies(work))
            builder = work.FacetedBodies.CreateSTLImportBuilder()
            try:
                builder.File = source_path
                builder.STLFileUnits = facet.STLImportBuilder.STLFileUnitsTypes.Millimeters
                builder.FacetBodyType = facet.STLImportBuilder.FacetBodyTypes.Nx
                builder.ShowInformationWindow = False
                if hasattr(builder, "CleanUp"):
                    builder.CleanUp = True
                builder.Commit()
                topology = list(builder.GetTopology())
            finally:
                builder.Destroy()
            created = [
                obj for obj in topology if getattr(obj, "Tag", 0) and int(obj.Tag) not in before
            ]
            if not created:
                created = [
                    body
                    for body in _machine_faceted_bodies(work)
                    if int(body.Tag) not in before
                ]
            if not created:
                raise RuntimeError("NX STL import created no readable facet geometry")
            for index, obj in enumerate(created, 1):
                name = prefix if len(created) == 1 else "%s_%02d" % (prefix, index)
                if hasattr(obj, "SetName"):
                    obj.SetName(name)
                if hasattr(obj, "Layer"):
                    obj.Layer = item["layer"]
                existing_names.add(name)
                imported.append(
                    {
                        "component": item["component"],
                        "file_name": item["file_name"],
                        "name": name,
                        "tag": int(obj.Tag),
                        "layer": item["layer"],
                        "bounds": _machine_object_bounds(obj),
                    }
                )
        update_errors = int(session.UpdateManager.DoUpdate(mark))
        if update_errors:
            raise RuntimeError("NX reported update errors after machine geometry import")
        session.SetUndoMarkName(mark, "NX MCP Imported Machine Geometry")
    except Exception as exc:
        try:
            session.UndoToMark(mark, mark_name)
        except Exception:
            pass
        safe = _safe_nx_error(exc)
        raise RuntimeError(
            "NX machine geometry import failed (type=%s, error_code=%s); changes were rolled back"
            % (safe["type"], safe["error_code"])
        )
    result.update(
        {
            "ok": True,
            "dry_run": False,
            "changed": bool(imported),
            "imported_object_count": len(imported),
            "skipped_file_count": len(skipped),
            "imported_geometry": imported,
            "skipped_geometry": skipped,
            "saved": False,
        }
    )
    return result


def _machine_kinematic_configurator(work, create=False):
    try:
        configurator = work.KinematicConfigurator
    except Exception:
        configurator = None
    if configurator is None and create:
        configurator = work.CreateKinematicConfigurator()
    return configurator


def _machine_component_geometry_map(work, plan):
    named = _machine_named_geometry(work)
    mapping = {}
    for component in plan["components"]:
        prefixes = [
            _machine_geometry_prefix(component["name"], item["file_name"])
            for item in component["geometry"]
        ]
        mapping[component["name"]] = [
            body for body in named if any(
                body["name"] == prefix or body["name"].startswith(prefix + "_")
                for prefix in prefixes
            )
        ]
    return mapping


def _machine_build_dry_plan(work, plan, channel_name):
    geometry = _machine_component_geometry_map(work, plan) if work is not None else {}
    missing_geometry = []
    operations = []
    by_name = {item["name"]: item for item in plan["components"]}
    for name in plan["build_sequence"]:
        component = by_name[name]
        assigned = geometry.get(name, [])
        if component["geometry"] and not assigned:
            missing_geometry.append(name)
        operations.append(
            {
                "component": name,
                "type": component["type"],
                "parent": component["parent"],
                "axis": component.get("axis"),
                "geometry_object_names": [item["name"] for item in assigned],
            }
        )
    return {
        "component_operations": operations,
        "channel_name": channel_name,
        "channel_axes": list(plan["axis_names"]),
        "missing_imported_geometry_components": missing_geometry,
        "machine_zero_component": plan["root_components"][0]
        if len(plan["root_components"]) == 1
        else None,
        "tool_mount_component": next(
            (item["name"] for item in plan["components"] if item["type"] == "spindle"),
            None,
        ),
        "workpiece_mount_component": next(
            (item["name"] for item in plan["components"] if item["type"] == "attach"),
            None,
        ),
    }


def _machine_build_smart_machine_kit(
    work, kinematic, plan, geometry_objects, geometry_names_by_component, channel_name
):
    sim = _sim_module()
    smk = None
    created_csys = []
    staging_directory = None
    staging_removed = False
    stage = "initialize"
    by_name = {item["name"]: item for item in plan["components"]}
    try:
        stage = "create_smart_machine_kit_builder"
        smk = kinematic.CreateSmkWizardBuilder()
        stage = "parse_classic_bc_template"
        smk.MachineTemplate = "5 Axis Dual Table BC Mill"
        smk.ParseTemplates()
        expected_template_components = (
            "MACHINE_BASE", "X_SLIDE", "Y_SLIDE", "Z_SLIDE",
            "SPINDLE", "POCKET_01", "B_SLIDE", "C_SLIDE", "SETUP",
        )
        if not all(smk.HasComponent(name) for name in expected_template_components):
            raise RuntimeError("NX Smart Machine Kit BC template is incomplete")

        stage = "preserve_template_component_structure"

        template_component_by_plan_name = {
            "Base": "MACHINE_BASE",
            "X": "X_SLIDE",
            "Y": "Y_SLIDE",
            "Z": "Z_SLIDE",
            "Spindle": "SPINDLE",
            "Tool": "POCKET_01",
            "B": "B_SLIDE",
            "C": "C_SLIDE",
            "Attach": "SETUP",
        }

        stage = "assign_component_geometry"
        smk.SetWizardStep(sim.SmkWizardBuilder.WizardStep.GeometrySelection)
        for component_name in plan["build_sequence"]:
            for geometry_name in geometry_names_by_component[component_name]:
                smk.AddGeometry(
                    template_component_by_plan_name[component_name],
                    geometry_objects[geometry_name],
                )

        stage = "configure_junction_coordinate_systems"
        smk.SetWizardStep(sim.SmkWizardBuilder.WizardStep.JunctionSelection)

        def set_junction(junction_name, component_name, coordinate_system_name):
            csys = work.CoordinateSystems.CreateCoordinateSystem(
                NXOpen.Point3d(*by_name[component_name]["position"]),
                NXOpen.Vector3d(1.0, 0.0, 0.0),
                NXOpen.Vector3d(0.0, 1.0, 0.0),
            )
            csys.SetName(coordinate_system_name)
            created_csys.append(csys)
            smk.SetJunctionCsys(junction_name, csys)

        set_junction("MACHINE_BASE@MACHINE_ZERO", "Base", "NXMCP_SMK_CSYS_01")
        set_junction("SPINDLE@S", "Spindle", "NXMCP_SMK_CSYS_02")
        set_junction("POCKET_01@T1", "Tool", "NXMCP_SMK_CSYS_03")
        set_junction("B_SLIDE@ROT_JCT_AUX", "B", "NXMCP_SMK_CSYS_04")
        set_junction("C_SLIDE@ROT_JCT", "C", "NXMCP_SMK_CSYS_05")
        set_junction("SETUP@PART_MOUNT_JCT", "Attach", "NXMCP_SMK_CSYS_06")

        stage = "configure_machine_axes"
        smk.SetWizardStep(sim.SmkWizardBuilder.WizardStep.AxisDefinition)
        axis_number = 0
        for component_name in plan["build_sequence"]:
            component = by_name[component_name]
            if component["type"] not in ("linear", "rotary", "spindle"):
                continue
            axis_name = (
                "S" if component["type"] == "spindle" else component["axis"]["address"]
            )
            if not bool(smk.HasAxis(axis_name)):
                raise RuntimeError("NX Smart Machine Kit template is missing axis %s" % axis_name)
            motion_type = {
                "linear": sim.SmkWizardBuilder.AxisMotionType.Linear,
                "rotary": (
                    sim.SmkWizardBuilder.AxisMotionType.RotaryUnlimited
                    if component["axis"]["unlimited"]
                    else sim.SmkWizardBuilder.AxisMotionType.Rotary
                ),
                "spindle": sim.SmkWizardBuilder.AxisMotionType.Spindle,
            }[component["type"]]
            smk.SetAxisMotion(axis_name, True, motion_type)
            direction = {
                "X": sim.SmkWizardBuilder.AxisDirectionType.PositiveX,
                "Y": sim.SmkWizardBuilder.AxisDirectionType.PositiveY,
                "Z": sim.SmkWizardBuilder.AxisDirectionType.PositiveZ,
            }[component["axis"]["direction"]]
            smk.SetAxisDirection(axis_name, direction)
            axis_number += 1
            smk.SetAxisNumber(axis_name, axis_number)
            smk.SetAxisInitialValue(axis_name, 0.0)

        stage = "configure_milling_chain"
        smk.SetWizardStep(sim.SmkWizardBuilder.WizardStep.ChainConfiguration)
        chain = smk.CreateSmkKimChainBuilder()
        chain.Name = "MILLING_CHAIN"
        chain.Type = sim.KinematicChain.Types.Milling
        chain.Device = "POCKET_01"
        chain.Setup = "SETUP"
        chain.X = "X"
        chain.Y = "Y"
        chain.Z = "Z"
        chain.Rotary1 = "B"
        chain.Rotary2 = "C"
        smk.SmkKimChainConfigurationBuilder.List.Append(chain)

        stage = "configure_machine_channel"
        smk.SetWizardStep(sim.SmkWizardBuilder.WizardStep.ChannelConfiguration)
        channel = smk.CreateSmkKimChannelBuilder()
        channel.Name = channel_name
        channel.SetAssignedAxes(["X", "Y", "Z", "S", "B", "C"])
        channel.GeometryAxisX = "X"
        channel.GeometryAxisY = "Y"
        channel.GeometryAxisZ = "Z"
        channel.MainSpindle = "S"
        channel.SetReferencedSpindle("S")
        if not bool(channel.Validate()):
            raise RuntimeError("NX rejected the Smart Machine Kit channel")
        assigned_before_commit = [str(item) for item in channel.GetAssignedAxes()]
        smk.SmkKimChannelConfigurationBuilder.KinematicChannels.Append(channel)

        stage = "validate_smart_machine_kit"
        if not bool(smk.Validate()):
            raise RuntimeError("NX rejected the Smart Machine Kit build state")
        stage = "prepare_machine_kit_metadata"
        smk.SetWizardStep(sim.SmkWizardBuilder.WizardStep.MachineToolDataDefinition)
        smk.MachineKitName = "nx_mcp_machine_build"
        smk.MachineKitType = smk.MachineType.Mill
        stage = "prepare_temporary_machine_kit_output"
        smk.SetWizardStep(sim.SmkWizardBuilder.WizardStep.OutputSelection)
        staging_directory = tempfile.mkdtemp(
            prefix=".nxmcp-smk-", dir=os.path.dirname(str(work.FullPath))
        )
        smk.OutputDirectory = staging_directory
        smk.CreateKitType = smk.OutputType.Mtk
        stage = "create_temporary_machine_kit_named_csys_baseline_v2"
        smk.CreateMachineKit()
        current_kinematic = work.KinematicConfigurator
        assignments = {
            axis: bool(current_kinematic.IsAxisAssignedToChannel(axis, channel_name))
            for axis in ("X", "Y", "Z", "S", "B", "C")
        }
        stage = "destroy_smart_machine_kit_builder"
        smk.Destroy()
        smk = None
        stage = "remove_temporary_machine_kit"
        shutil.rmtree(staging_directory)
        staging_directory = None
        staging_removed = True
        return {
            "method": "smart_machine_kit_classic_bc_template",
            "component_names": [
                template_component_by_plan_name[name]
                for name in plan["build_sequence"]
            ],
            "component_aliases": dict(template_component_by_plan_name),
            "axis_names": ["X", "Y", "Z", "S", "B", "C"],
            "channel_name": channel_name,
            "channel_axes_before_commit": assigned_before_commit,
            "channel_axis_assignments": assignments,
            "channel_binding_persisted": all(assignments.values()),
            "chain_name": "MILLING_CHAIN",
            "coordinate_system_count": len(created_csys),
            "temporary_machine_kit_created": True,
            "temporary_machine_kit_removed": staging_removed,
            "machine_library_registered": False,
            "remaining_blockers": (
                [] if all(assignments.values()) else ["channel_axis_assignments_missing"]
            ),
        }
    except Exception as exc:
        safe = _safe_nx_error(exc)
        detail = str(exc).strip().replace("\r", " ").replace("\n", " ")[:240]
        raise RuntimeError(
            "Smart Machine Kit build failed at %s (type=%s, error_code=%s, detail=%s)"
            % (stage, safe["type"], safe["error_code"], detail or "unavailable")
        )
    finally:
        if smk is not None:
            try:
                smk.Destroy()
            except Exception:
                pass
        if staging_directory:
            try:
                shutil.rmtree(staging_directory)
                staging_removed = True
            except Exception:
                pass


def _machine_build_smart_machine_kit_baseline(
    work, kinematic, plan, geometry_objects, geometry_names_by_component, channel_name
):
    sim = _sim_module()
    smk = None
    staging_directory = None
    stage = "initialize"
    by_name = {item["name"]: item for item in plan["components"]}
    component_map = {
        "Base": "MACHINE_BASE",
        "X": "X_SLIDE",
        "Y": "Y_SLIDE",
        "Z": "Z_SLIDE",
        "Spindle": "SPINDLE",
        "Tool": "POCKET_01",
        "B": "B_SLIDE",
        "C": "C_SLIDE",
        "Attach": "SETUP",
    }
    try:
        stage = "parse_classic_bc_template"
        smk = kinematic.CreateSmkWizardBuilder()
        smk.MachineTemplate = "5 Axis Dual Table BC Mill"
        smk.ParseTemplates()

        stage = "assign_component_geometry"
        smk.SetWizardStep(smk.WizardStep.GeometrySelection)
        for component_name in plan["build_sequence"]:
            for geometry_name in geometry_names_by_component[component_name]:
                smk.AddGeometry(
                    component_map[component_name], geometry_objects[geometry_name]
                )

        stage = "configure_named_junction_coordinate_systems"
        smk.SetWizardStep(smk.WizardStep.JunctionSelection)
        junctions = (
            ("MACHINE_BASE@MACHINE_ZERO", "Base"),
            ("SPINDLE@S", "Spindle"),
            ("POCKET_01@T1", "Tool"),
            ("B_SLIDE@ROT_JCT_AUX", "B"),
            ("C_SLIDE@ROT_JCT", "C"),
            ("SETUP@PART_MOUNT_JCT", "Attach"),
        )
        for index, (junction_name, component_name) in enumerate(junctions, 1):
            coordinate_system = work.CoordinateSystems.CreateCoordinateSystem(
                NXOpen.Point3d(*by_name[component_name]["position"]),
                NXOpen.Vector3d(1.0, 0.0, 0.0),
                NXOpen.Vector3d(0.0, 1.0, 0.0),
            )
            coordinate_system.SetName("NXMCP_SMK_CSYS_%02d" % index)
            smk.SetJunctionCsys(junction_name, coordinate_system)

        stage = "configure_axes"
        smk.SetWizardStep(smk.WizardStep.AxisDefinition)
        axis_specs = (
            ("X", smk.AxisMotionType.Linear, smk.AxisDirectionType.PositiveX),
            ("Y", smk.AxisMotionType.Linear, smk.AxisDirectionType.PositiveY),
            ("Z", smk.AxisMotionType.Linear, smk.AxisDirectionType.PositiveZ),
            ("S", smk.AxisMotionType.Spindle, smk.AxisDirectionType.PositiveZ),
            ("B", smk.AxisMotionType.Rotary, smk.AxisDirectionType.PositiveY),
            ("C", smk.AxisMotionType.RotaryUnlimited, smk.AxisDirectionType.PositiveZ),
        )
        for number, (axis_name, motion, direction) in enumerate(axis_specs, 1):
            smk.SetAxisMotion(axis_name, True, motion)
            smk.SetAxisDirection(axis_name, direction)
            smk.SetAxisNumber(axis_name, number)
            smk.SetAxisInitialValue(axis_name, 0.0)

        stage = "configure_milling_chain"
        smk.SetWizardStep(smk.WizardStep.ChainConfiguration)
        chain = smk.CreateSmkKimChainBuilder()
        chain.Name = "MILLING_CHAIN"
        chain.Type = sim.KinematicChain.Types.Milling
        chain.Device = "POCKET_01"
        chain.Setup = "SETUP"
        chain.X = "X"
        chain.Y = "Y"
        chain.Z = "Z"
        chain.Rotary1 = "B"
        chain.Rotary2 = "C"
        smk.SmkKimChainConfigurationBuilder.List.Append(chain)

        stage = "configure_channel"
        smk.SetWizardStep(smk.WizardStep.ChannelConfiguration)
        channel = smk.CreateSmkKimChannelBuilder()
        channel.Name = channel_name
        channel.SetAssignedAxes(["X", "Y", "Z", "S", "B", "C"])
        channel.GeometryAxisX = "X"
        channel.GeometryAxisY = "Y"
        channel.GeometryAxisZ = "Z"
        channel.MainSpindle = "S"
        channel.SetReferencedSpindle("S")
        smk.SmkKimChannelConfigurationBuilder.KinematicChannels.Append(channel)
        assigned_before_create = [str(item) for item in channel.GetAssignedAxes()]
        if not bool(smk.Validate()):
            raise RuntimeError("NX rejected the Smart Machine Kit build state")

        stage = "prepare_machine_kit_metadata"
        smk.SetWizardStep(smk.WizardStep.MachineToolDataDefinition)
        smk.MachineKitName = "nx_mcp_machine_build"
        smk.MachineKitType = smk.MachineType.Mill
        stage = "create_temporary_machine_kit"
        smk.SetWizardStep(smk.WizardStep.OutputSelection)
        staging_directory = tempfile.mkdtemp(
            prefix=".nxmcp-smk-", dir=os.path.dirname(str(work.FullPath))
        )
        smk.OutputDirectory = staging_directory
        smk.CreateKitType = smk.OutputType.Mtk
        smk.ArchieveFile = smk.ArchieveFileType.Specify
        smk.ArchieveMachineFilePath = str(work.FullPath)
        smk.ArchieveTemplateFilePath = str(smk.MachineTemplateFilePath)
        stage = "collect_machine_kit_archive_data"
        smk.SetArchieveData()
        stage = "create_temporary_machine_kit"
        smk.CreateMachineKit()
        package_candidates = []
        relative_outputs = []
        for output_root, _output_dirs, output_files in os.walk(staging_directory):
            for output_file in output_files:
                output_path = os.path.join(output_root, output_file)
                relative_outputs.append(os.path.relpath(output_path, staging_directory))
                if output_file.lower().endswith(".mtk"):
                    package_candidates.append(output_path)
        if len(package_candidates) != 1:
            raise RuntimeError(
                "NX temporary machine kit output is incomplete; files=%s"
                % ",".join(sorted(relative_outputs)[:20])
            )
        package_path = package_candidates[0]
        with zipfile.ZipFile(package_path, "r") as machine_kit_archive:
            archive_members = machine_kit_archive.namelist()
        if len(archive_members) <= 1:
            current_axes_after_create = [
                str(item) for item in kinematic.GetAxisNames()
            ]
            current_channels_after_create = [
                str(item) for item in kinematic.GetChannels()
            ]
            stage = "create_temporary_machine_directory_axes_%s_channels_%s" % (
                "-".join(current_axes_after_create) or "none",
                "-".join(current_channels_after_create) or "none",
            )
            machine_directory = os.path.join(staging_directory, "machine_directory")
            os.makedirs(machine_directory)
            machine_builder = kinematic.CreateMachineKitBuilder()
            try:
                machine_builder.Name = "nx_mcp_machine_build"
                machine_builder.OutputDirectory = machine_directory
                if not bool(machine_builder.Validate()):
                    raise RuntimeError("NX rejected the temporary machine directory")
                machine_builder.Commit()
            finally:
                machine_builder.Destroy()
            machine_directory_outputs = []
            for output_root, _output_dirs, output_files in os.walk(machine_directory):
                for output_file in output_files:
                    machine_directory_outputs.append(
                        os.path.relpath(
                            os.path.join(output_root, output_file), machine_directory
                        )
                    )
            raise RuntimeError(
                "NX temporary machine kit archive has no machine content; members=%s; "
                "machine_directory_files=%s; current_axes=%s; current_channels=%s"
                % (
                    ",".join(archive_members),
                    ",".join(sorted(machine_directory_outputs)[:20]),
                    ",".join(str(item) for item in kinematic.GetAxisNames()),
                    ",".join(str(item) for item in kinematic.GetChannels()),
                )
            )

        stage = "destroy_machine_kit_builder_before_import"
        smk.Destroy()
        smk = None
        stage = "import_temporary_machine_kit"
        import_builder = kinematic.ImportMachineBuilderFromZipFile(package_path)
        try:
            if (
                import_builder is not None
                and hasattr(import_builder, "Validate")
                and not bool(import_builder.Validate())
            ):
                raise RuntimeError("NX rejected the temporary machine kit import")
            if import_builder is not None and hasattr(import_builder, "Commit"):
                import_builder.Commit()
        finally:
            if import_builder is not None and hasattr(import_builder, "Destroy"):
                import_builder.Destroy()

        stage = "remove_temporary_machine_kit"
        shutil.rmtree(staging_directory)
        staging_directory = None
        current = work.KinematicConfigurator
        assignments = {
            axis: bool(current.IsAxisAssignedToChannel(axis, channel_name))
            for axis in ("X", "Y", "Z", "S", "B", "C")
        }
        return {
            "method": "smart_machine_kit_classic_bc_package_import",
            "component_names": [component_map[name] for name in plan["build_sequence"]],
            "component_aliases": dict(component_map),
            "axis_names": ["X", "Y", "Z", "S", "B", "C"],
            "channel_name": channel_name,
            "channel_axes_before_create": assigned_before_create,
            "channel_axis_assignments": assignments,
            "channel_binding_persisted": all(assignments.values()),
            "chain_name": "MILLING_CHAIN",
            "temporary_machine_kit_created": True,
            "temporary_machine_kit_removed": True,
            "machine_library_registered": False,
            "remaining_blockers": (
                [] if all(assignments.values()) else ["channel_axis_assignments_missing"]
            ),
        }
    except Exception as exc:
        safe = _safe_nx_error(exc)
        detail = str(exc).strip().replace("\r", " ").replace("\n", " ")[:240]
        raise RuntimeError(
            "Smart Machine Kit baseline failed at %s (type=%s, error_code=%s, detail=%s)"
            % (stage, safe["type"], safe["error_code"], detail or "unavailable")
        )
    finally:
        if smk is not None:
            try:
                smk.Destroy()
            except Exception:
                pass
        if staging_directory:
            try:
                shutil.rmtree(staging_directory)
            except Exception:
                pass


def _machine_cumulative_component_positions(plan):
    """Resolve OEM component positions into absolute machine coordinates."""
    by_name = {item["name"]: item for item in plan["components"]}
    resolved = {}
    active = set()

    def resolve(name):
        if name in resolved:
            return resolved[name]
        if name in active:
            raise ValueError("machine component hierarchy contains a cycle")
        active.add(name)
        component = by_name[name]
        local = [float(value) for value in component["position"]]
        parent_name = component.get("parent")
        if parent_name:
            parent = resolve(parent_name)
            absolute = [parent[index] + local[index] for index in range(3)]
        else:
            absolute = local
        active.remove(name)
        resolved[name] = absolute
        return absolute

    for component_name in by_name:
        resolve(component_name)
    return resolved


def _machine_reference_coordinate_frame(plan, tolerance=1.0e-6):
    """Resolve the NX machine-zero origin and validate it against the OEM reference."""
    positions = _machine_cumulative_component_positions(plan)
    spindle_names = [
        item["name"]
        for item in plan["components"]
        if item.get("type") == "spindle"
    ]
    spindle_origin = positions[spindle_names[0]] if len(spindle_names) == 1 else None
    reference = plan.get("machine_reference_location")
    if reference is None:
        return {
            "machine_zero_origin": list(spindle_origin) if spindle_origin else None,
            "spindle_origin": list(spindle_origin) if spindle_origin else None,
            "reference_linear_axis_values": None,
            "reference_residual": None,
            "reference_consistent_with_spindle": spindle_origin is not None,
            "source": "spindle_component_origin" if spindle_origin else "unavailable",
        }
    reference_values = [
        float(value) for value in reference["linear_axis_values"][:3]
    ]
    reference_machine_zero = [-value for value in reference_values]
    if spindle_origin is None:
        residual = None
        consistent = False
    else:
        residual = [
            float(spindle_origin[index]) - reference_machine_zero[index]
            for index in range(3)
        ]
        consistent = all(abs(value) <= tolerance for value in residual)
    return {
        "machine_zero_origin": reference_machine_zero,
        "spindle_origin": list(spindle_origin) if spindle_origin else None,
        "reference_linear_axis_values": reference_values,
        "reference_residual": residual,
        "reference_consistent_with_spindle": consistent,
        "source": "oem_machine_reference_location",
    }


def _machine_retarget_template_junctions(work, kinematic, plan):
    """Retarget all imported BC-template junctions to OEM absolute coordinates."""
    positions = _machine_cumulative_component_positions(plan)
    components = {
        str(item.Name): item for item in list(kinematic.ComponentCollection)
    }
    coordinate_frame = _machine_reference_coordinate_frame(plan)
    if not coordinate_frame["machine_zero_origin"]:
        raise RuntimeError("OEM machine-zero coordinate is unavailable")
    if not coordinate_frame["reference_consistent_with_spindle"]:
        raise RuntimeError("OEM machine reference does not match the spindle origin")
    explicit_targets = {
        "MACHINE_BASE@MACHINE_ZERO": "__MACHINE_ZERO__",
        "SPINDLE@S": "Spindle",
        "B_SLIDE@ROT_JCT_AUX": "B",
        "C_SLIDE@ROT_JCT": "C",
        "SETUP@PART_MOUNT_JCT": "Attach",
    }
    records = []
    created_csys = []
    for full_name in [str(item) for item in kinematic.GetJunctionNames()]:
        plan_name = explicit_targets.get(full_name)
        if full_name.startswith("POCKET_") and "@T" in full_name:
            plan_name = "Tool"
        if plan_name is None:
            continue
        owner_name = full_name.split("@", 1)[0]
        owner = components.get(owner_name)
        if owner is None:
            raise RuntimeError("NX junction owner is unavailable: %s" % full_name)
        junction = kinematic.FindJunction(full_name)
        builder = kinematic.CreateJunctionBuilder(owner, junction)
        try:
            original_name = str(builder.Name)
            classification = builder.Classification
            original_csys = builder.Csys
            original_origin = _point_to_list(original_csys.Origin)
            matrix = original_csys.Orientation.Element
            target_origin = (
                coordinate_frame["machine_zero_origin"]
                if plan_name == "__MACHINE_ZERO__"
                else positions[plan_name]
            )
            coordinate_system = work.CoordinateSystems.CreateCoordinateSystem(
                NXOpen.Point3d(*target_origin),
                NXOpen.Vector3d(
                    float(matrix.Xx), float(matrix.Xy), float(matrix.Xz)
                ),
                NXOpen.Vector3d(
                    float(matrix.Yx), float(matrix.Yy), float(matrix.Yz)
                ),
            )
            coordinate_system.SetName(
                "NXMCP_OEM_JCT_%02d" % (len(created_csys) + 1)
            )
            created_csys.append(coordinate_system)
            builder.Name = original_name
            builder.Classification = classification
            builder.Csys = coordinate_system
            if not bool(builder.Validate()):
                raise RuntimeError("NX rejected OEM junction coordinates: %s" % full_name)
            committed = builder.Commit()
        finally:
            builder.Destroy()
        current = kinematic.FindJunction(full_name)
        readback_builder = kinematic.CreateJunctionBuilder(owner, current)
        try:
            readback_origin = _point_to_list(readback_builder.Csys.Origin)
        finally:
            readback_builder.Destroy()
        if any(
            abs(readback_origin[index] - target_origin[index]) > 1.0e-8
            for index in range(3)
        ):
            raise RuntimeError("NX OEM junction coordinate readback failed: %s" % full_name)
        records.append(
            {
                "junction": full_name,
                "owner": owner_name,
                "source_component": plan_name,
                "before_origin": original_origin,
                "target_origin": list(target_origin),
                "readback_origin": readback_origin,
                "tag_preserved": int(current.Tag) == int(junction.Tag),
                "commit_tag": int(getattr(committed, "Tag", 0) or 0),
            }
        )
    expected_count = len(explicit_targets) + 20
    if len(records) != expected_count:
        raise RuntimeError(
            "NX BC template junction coverage is incomplete: expected=%d actual=%d"
            % (expected_count, len(records))
        )
    return {
        "coordinate_source": "oem_machine_reference_and_component_absolute",
        "machine_zero_origin": list(coordinate_frame["machine_zero_origin"]),
        "machine_reference_consistent": bool(
            coordinate_frame["reference_consistent_with_spindle"]
        ),
        "coordinate_count": len(created_csys),
        "junction_count": len(records),
        "all_tags_preserved": all(item["tag_preserved"] for item in records),
        "records": records,
    }


def _machine_build_imported_template_kinematics(
    work, kinematic, plan, geometry_objects, geometry_names_by_component, channel_name
):
    """Materialize the official BC template, then bind isolated OEM geometry."""
    sim = _sim_module()
    smk = None
    active_builder = None
    staging_directory = None
    stage = "initialize"
    created_csys = []
    by_name = {item["name"]: item for item in plan["components"]}
    component_map = {
        "Base": "MACHINE_BASE",
        "X": "X_SLIDE",
        "Y": "Y_SLIDE",
        "Z": "Z_SLIDE",
        "Spindle": "SPINDLE",
        "Tool": "POCKET_01",
        "B": "B_SLIDE",
        "C": "C_SLIDE",
        "Attach": "SETUP",
    }

    def commit(builder, label):
        if hasattr(builder, "Validate") and not bool(builder.Validate()):
            raise RuntimeError("NX rejected %s" % label)
        return builder.Commit()

    try:
        stage = "resolve_official_bc_template"
        smk = kinematic.CreateSmkWizardBuilder()
        smk.MachineTemplate = "5 Axis Dual Table BC Mill"
        smk.ParseTemplates()
        template_path = str(smk.MachineTemplateFilePath or "")
        if not template_path or not os.path.isfile(template_path):
            raise RuntimeError("NX official BC machine template is unavailable")
        smk.Destroy()
        smk = None

        stage = "import_official_bc_kinematic_model"
        kinematic.ImportModel(template_path)
        imported_axes = [str(item) for item in kinematic.GetAxisNames()]
        missing_axes = [
            axis for axis in ("X", "Y", "Z", "S", "B", "C")
            if not _machine_axis_matches(imported_axes, axis)
        ]
        if missing_axes:
            raise RuntimeError(
                "NX BC template is missing axes %s" % ",".join(missing_axes)
            )
        stage = "attach_imported_bc_root_component"
        imported_components = {
            str(item.Name): item for item in list(kinematic.ComponentCollection)
        }
        imported_root = imported_components.get("MACHINE_BASE")
        if imported_root is None:
            raise RuntimeError("NX BC template machine base is unavailable")
        kinematic.InsertRootComponent(imported_root)
        stage = "attach_imported_bc_component_tree"
        for component in imported_components.values():
            if int(component.Tag) == int(imported_root.Tag):
                continue
            parent = component.GetParent()
            if parent is None or getattr(parent, "Tag", 0) == 0:
                raise RuntimeError(
                    "NX BC template component parent is unavailable: %s"
                    % str(component.Name)
                )
            parent.InsertComponent(component)
        stage = "attach_imported_bc_junctions"
        for junction_name in [str(item) for item in kinematic.GetJunctionNames()]:
            owner_name = junction_name.split("@", 1)[0]
            owner = imported_components.get(owner_name)
            if owner is None:
                raise RuntimeError(
                    "NX BC template junction owner is unavailable: %s"
                    % junction_name
                )
            junction = kinematic.FindJunction(junction_name)
            current_junction_tags = {
                int(item.Tag) for item in list(owner.GetJunctions())
            }
            if int(junction.Tag) not in current_junction_tags:
                owner.InsertJunction(junction)
        kinematic.SetName("MIKRON_E500U_TNC640")

        stage = "rename_template_channel"
        existing_channels = [str(item) for item in kinematic.GetChannels()]
        if channel_name not in existing_channels:
            if len(existing_channels) != 1:
                raise RuntimeError("NX BC template channel layout is unexpected")
            kinematic.RenameChannel(existing_channels[0], channel_name)

        stage = "verify_machine_component_geometry_targets"
        components = {
            str(item.Name): item for item in list(kinematic.ComponentCollection)
        }
        missing_components = [
            target for target in component_map.values() if target not in components
        ]
        if missing_components:
            raise RuntimeError(
                "NX BC template is missing components %s"
                % ",".join(missing_components)
            )
        geometry_bindings = {}
        for plan_name in plan["build_sequence"]:
            target_name = component_map[plan_name]
            component = components[target_name]
            parent = component.GetParent()
            active_builder = kinematic.ComponentCollection.CreateComponentBuilder(
                parent, component
            )
            active_builder.Name = target_name
            preserved_junction_builders = []
            if int(active_builder.JunctionList.Length) == 0:
                for junction in list(component.GetJunctions()):
                    junction_builder = kinematic.CreateJunctionBuilder(
                        component, junction
                    )
                    junction_builder.Name = str(junction.Name)
                    active_builder.JunctionList.Append(junction_builder)
                    preserved_junction_builders.append(junction_builder)
            assigned = [
                geometry_objects[name]
                for name in geometry_names_by_component[plan_name]
            ]
            active_builder.SetGeometries(assigned)
            commit(active_builder, "component geometry %s" % target_name)
            active_builder.Destroy()
            active_builder = None
            for junction_builder in preserved_junction_builders:
                try:
                    junction_builder.Destroy()
                except Exception:
                    pass
            geometry_bindings[target_name] = [
                str(getattr(item, "Name", "") or "") for item in assigned
            ]

        stage = "verify_template_junctions"
        junction_specs = (
            ("MACHINE_BASE@MACHINE_ZERO", "Base"),
            ("SPINDLE@S", "Spindle"),
            ("POCKET_01@T1", "Tool"),
            ("B_SLIDE@ROT_JCT_AUX", "B"),
            ("C_SLIDE@ROT_JCT", "C"),
            ("SETUP@PART_MOUNT_JCT", "Attach"),
        )
        available_junctions = {
            str(item) for item in kinematic.GetJunctionNames()
        }
        junction_owners = {}
        for junction_name, _plan_name in junction_specs:
            if junction_name not in available_junctions:
                raise RuntimeError("NX BC template junction is missing: %s" % junction_name)
            owner_name = junction_name.split("@", 1)[0]
            owner = components[owner_name]
            junction = kinematic.FindJunction(junction_name)
            current_junction_tags = {
                int(item.Tag) for item in list(owner.GetJunctions())
            }
            if int(junction.Tag) not in current_junction_tags:
                owner.InsertJunction(junction)
            junction_owners[junction_name] = owner_name

        stage = "retarget_template_junctions_to_oem_coordinates"
        junction_retarget = _machine_retarget_template_junctions(
            work, kinematic, plan
        )
        stage = "record_machine_axis_parameters"
        axis_number = 0
        axis_parameters = {}
        for plan_name in plan["build_sequence"]:
            component_plan = by_name[plan_name]
            if component_plan["type"] not in ("linear", "rotary", "spindle"):
                continue
            axis_name = (
                "S"
                if component_plan["type"] == "spindle"
                else component_plan["axis"]["address"]
            )
            axis, component, junction = kinematic.FindAxis(axis_name)
            active_builder = kinematic.CreateAxisBuilder(component, junction, axis)
            axis_number += 1
            active_builder.Name = axis_name
            active_builder.Junction = junction
            active_builder.Number = axis_number
            active_builder.Type = {
                "linear": sim.KinematicAxisBuilder.AxisMotionType.LinearNcAxis,
                "rotary": (
                    sim.KinematicAxisBuilder.AxisMotionType.RotaryUnlimitedNcAxis
                    if component_plan["axis"]["unlimited"]
                    else sim.KinematicAxisBuilder.AxisMotionType.RotaryNcAxis
                ),
                "spindle": sim.KinematicAxisBuilder.AxisMotionType.SpindleNcAxis,
            }[component_plan["type"]]
            active_builder.Direction = {
                "X": sim.KinematicAxisBuilder.AxisDirectionType.PositiveX,
                "Y": sim.KinematicAxisBuilder.AxisDirectionType.PositiveY,
                "Z": sim.KinematicAxisBuilder.AxisDirectionType.PositiveZ,
            }[component_plan["axis"]["direction"]]
            bounded = (
                component_plan["type"] in ("linear", "rotary")
                and not component_plan["axis"]["unlimited"]
            )
            initial_value = 0.0
            if bounded:
                lower = float(component_plan["axis"]["lower_limit"])
                upper = float(component_plan["axis"]["upper_limit"])
                if upper <= lower:
                    raise ValueError("bounded machine axis limits are invalid")
                margin = max((upper - lower) * 1.0e-6, 1.0e-6)
                active_builder.LowerLimit = lower
                active_builder.UpperLimit = upper
                active_builder.LowerSoftLimit = lower + margin
                active_builder.UpperSoftLimit = upper - margin
                initial_value = min(max(0.0, lower + margin), upper - margin)
            active_builder.Limit = bounded
            active_builder.InitialValue = initial_value
            commit(active_builder, "axis %s" % axis_name)
            active_builder.Destroy()
            active_builder = None
            axis_parameters[axis_name] = {
                "number": axis_number,
                "bounded": bounded,
                "initial_value": initial_value,
                "source": "profile",
            }

        stage = "verify_channel_axis_assignments"
        assignments = {
            axis: bool(kinematic.IsAxisAssignedToChannel(axis, channel_name))
            for axis in ("X", "Y", "Z", "S", "B", "C")
        }
        if not all(assignments.values()):
            raise RuntimeError("NX BC template channel assignments are incomplete")

        stage = "export_temporary_kinematic_model"
        staging_directory = tempfile.mkdtemp(
            prefix=".nxmcp-machine-kit-", dir=os.path.dirname(str(work.FullPath))
        )
        exported_model_path = os.path.join(
            staging_directory, "nx_mcp_mill_e_500u_kinematics.json"
        )
        kinematic.ExportModel(exported_model_path)
        exported_candidates = [
            os.path.join(output_root, output_file)
            for output_root, _output_dirs, output_files in os.walk(staging_directory)
            for output_file in output_files
        ]
        if not os.path.isfile(exported_model_path):
            if len(exported_candidates) == 1:
                exported_model_path = exported_candidates[0]
            else:
                raise RuntimeError(
                    "NX did not export one temporary kinematic model; files=%s"
                    % ",".join(
                        os.path.relpath(item, staging_directory)
                        for item in exported_candidates[:20]
                    )
                )
        exported_model_size = int(os.path.getsize(exported_model_path))
        if exported_model_size <= 64:
            raise RuntimeError("NX exported an empty temporary kinematic model")

        return {
            "method": "official_bc_template_import",
            "component_names": [
                component_map[name] for name in plan["build_sequence"]
            ],
            "component_aliases": dict(component_map),
            "geometry_bindings": geometry_bindings,
            "geometry_binding_applied": True,
            "axis_names": ["X", "Y", "Z", "S", "B", "C"],
            "axis_parameters": axis_parameters,
            "channel_name": channel_name,
            "channel_axis_assignments": assignments,
            "channel_binding_persisted": True,
            "chain_name": "Z-Y-X-B-C",
            "junction_owners": junction_owners,
            "junction_coordinate_source": junction_retarget["coordinate_source"],
            "junction_retarget": junction_retarget,
            "coordinate_system_count": junction_retarget["coordinate_count"],
            "temporary_kinematic_model_exported": True,
            "temporary_kinematic_model_size": exported_model_size,
            "temporary_kinematic_model_removed": True,
            "machine_library_registered": False,
            "machine_kit_created": False,
            "remaining_blockers": [
                "machine_kit_archive_not_exported",
            ],
        }
    except Exception as exc:
        safe = _safe_nx_error(exc)
        detail = str(exc).strip().replace("\r", " ").replace("\n", " ")[:240]
        raise RuntimeError(
            "official BC template build failed at %s (type=%s, error_code=%s, detail=%s)"
            % (stage, safe["type"], safe["error_code"], detail or "unavailable")
        )
    finally:
        if active_builder is not None:
            try:
                active_builder.Destroy()
            except Exception:
                pass
        if smk is not None:
            try:
                smk.Destroy()
            except Exception:
                pass
        if staging_directory:
            try:
                shutil.rmtree(staging_directory)
            except Exception:
                pass


def _machine_build_low_level_kinematics(
    work, kinematic, plan, geometry_objects, geometry_names_by_component, channel_name
):
    sim = _sim_module()
    component_objects = {}
    junction_objects = {}
    created_csys = []
    builders = []
    chain_configuration = None
    by_name = {item["name"]: item for item in plan["components"]}
    stage = "initialize"

    def commit_builder(builder, name):
        builders.append(builder)
        try:
            if hasattr(builder, "Validate") and not bool(builder.Validate()):
                raise RuntimeError("NX rejected %s" % name)
            committed = builder.Commit()
        finally:
            try:
                builder.Destroy()
            except Exception:
                pass
            builders.remove(builder)
        if committed is None:
            raise RuntimeError("NX returned no object for %s" % name)
        return committed

    def create_csys(position):
        csys = work.CoordinateSystems.CreateCoordinateSystem(
            NXOpen.Point3d(*position),
            NXOpen.Vector3d(1.0, 0.0, 0.0),
            NXOpen.Vector3d(0.0, 1.0, 0.0),
        )
        created_csys.append(csys)
        return csys

    try:
        kinematic.SetName("MIKRON_E500U_TNC640")
        root_name = plan["root_components"][0]
        root_plan = by_name[root_name]
        stage = "create_root_component"
        root_builder = kinematic.ComponentCollection.CreateMachineBaseComponentBuilder(
            None
        )
        root_builder.Name = root_name
        root_builder.SetGeometries(
            [
                geometry_objects[name]
                for name in geometry_names_by_component[root_name]
            ]
        )
        root = commit_builder(root_builder, "root component")
        component_objects[root_name] = root

        stage = "register_machine_channel"
        kinematic.AddChannel(channel_name)

        stage = "create_machine_zero_junction"
        zero_builder = kinematic.CreateJunctionBuilder(root, None)
        zero_builder.Name = "MACHINE_ZERO"
        zero_builder.Csys = create_csys(root_plan["position"])
        zero_builder.Classification = (
            sim.KinematicJunctionBuilder.SystemClass.MachineZero
        )
        junction_objects["MACHINE_ZERO"] = commit_builder(
            zero_builder, "machine zero junction"
        )
        root.InsertJunction(junction_objects["MACHINE_ZERO"])

        axis_number = 0
        for name in plan["build_sequence"]:
            if name == root_name:
                continue
            component = by_name[name]
            parent = component_objects[component["parent"]]
            stage = "create_component_%s_builder" % name
            component_builder = (
                kinematic.ComponentCollection.CreateComponentBuilder(parent, None)
            )
            stage = "set_component_%s_name" % name
            component_builder.Name = name
            stage = "set_component_%s_geometry" % name
            component_builder.SetGeometries(
                [
                    geometry_objects[geometry_name]
                    for geometry_name in geometry_names_by_component[name]
                ]
            )
            semantic_class = {
                "spindle": sim.KinematicComponentBuilder.SystemClass.Turret,
                "tool": sim.KinematicComponentBuilder.SystemClass.PocketOnHead,
                "attach": sim.KinematicComponentBuilder.SystemClass.SetupElement,
            }.get(component["type"])
            if semantic_class is not None:
                stage = "set_component_%s_system_class" % name
                component_builder.AddSystemClass(semantic_class)
            if component["type"] in ("linear", "rotary", "spindle"):
                stage = "set_component_%s_channel" % name
                component_builder.AddChannelName(channel_name)
            stage = "commit_component_%s" % name
            component_object = commit_builder(
                component_builder, "component %s" % name
            )
            component_objects[name] = component_object

            if component["type"] not in ("linear", "rotary", "spindle"):
                continue
            axis_name = (
                "S"
                if component["type"] == "spindle"
                else component["axis"]["address"]
            )
            junction_name = "JCT_%s" % name.upper()
            stage = "create_axis_junction_%s" % axis_name
            junction_builder = kinematic.CreateJunctionBuilder(
                component_object, None
            )
            junction_builder.Name = junction_name
            junction_builder.Csys = create_csys(component["position"])
            junction = commit_builder(
                junction_builder, "axis junction %s" % axis_name
            )
            component_object.InsertJunction(junction)
            junction_objects[junction_name] = junction

            stage = "create_axis_%s" % axis_name
            axis_builder = kinematic.CreateAxisBuilder(
                component_object, junction, None
            )
            axis_builder.Name = axis_name
            axis_builder.Type = {
                "linear": sim.KinematicAxisBuilder.AxisMotionType.LinearNcAxis,
                "rotary": (
                    sim.KinematicAxisBuilder.AxisMotionType.RotaryUnlimitedNcAxis
                    if component["axis"]["unlimited"]
                    else sim.KinematicAxisBuilder.AxisMotionType.RotaryNcAxis
                ),
                "spindle": sim.KinematicAxisBuilder.AxisMotionType.SpindleNcAxis,
            }[component["type"]]
            axis_builder.Direction = {
                "X": sim.KinematicAxisBuilder.AxisDirectionType.PositiveX,
                "Y": sim.KinematicAxisBuilder.AxisDirectionType.PositiveY,
                "Z": sim.KinematicAxisBuilder.AxisDirectionType.PositiveZ,
            }[component["axis"]["direction"]]
            axis_number += 1
            axis_builder.Number = axis_number
            axis_builder.InitialValue = 0.0
            bounded = (
                component["type"] in ("linear", "rotary")
                and not component["axis"]["unlimited"]
            )
            axis_builder.Limit = bounded
            if bounded:
                lower = float(component["axis"]["lower_limit"])
                upper = float(component["axis"]["upper_limit"])
                span = upper - lower
                if span <= 0.0:
                    raise ValueError("bounded machine axis limits are invalid")
                margin = max(span * 1.0e-6, 1.0e-6)
                soft_lower = lower + margin
                soft_upper = upper - margin
                axis_builder.LowerLimit = lower
                axis_builder.UpperLimit = upper
                axis_builder.LowerSoftLimit = soft_lower
                axis_builder.UpperSoftLimit = soft_upper
                axis_builder.InitialValue = min(max(0.0, soft_lower), soft_upper)
            commit_builder(axis_builder, "axis %s" % axis_name)

        stage = "create_tool_mount_junction"
        tool_builder = kinematic.CreateJunctionBuilder(
            component_objects["Tool"], None
        )
        tool_builder.Name = "TOOL_MOUNT"
        tool_builder.Csys = create_csys(by_name["Tool"]["position"])
        tool_builder.Classification = (
            sim.KinematicJunctionBuilder.SystemClass.ToolZero
        )
        junction_objects["TOOL_MOUNT"] = commit_builder(
            tool_builder, "tool mount junction"
        )
        component_objects["Tool"].InsertJunction(
            junction_objects["TOOL_MOUNT"]
        )

        stage = "create_workpiece_mount_junction"
        workpiece_builder = kinematic.CreateJunctionBuilder(
            component_objects["Attach"], None
        )
        workpiece_builder.Name = "WORKPIECE_MOUNT"
        workpiece_builder.Csys = create_csys(by_name["Attach"]["position"])
        workpiece_builder.Classification = (
            sim.KinematicJunctionBuilder.SystemClass.Mount
        )
        junction_objects["WORKPIECE_MOUNT"] = commit_builder(
            workpiece_builder, "workpiece mount junction"
        )
        component_objects["Attach"].InsertJunction(
            junction_objects["WORKPIECE_MOUNT"]
        )

        stage = "define_milling_chain"
        chain = kinematic.CreateKinematicChain()
        chain.Name = "MILLING_CHAIN"
        chain.Type = sim.KinematicChain.Types.Milling
        chain.Device = "Tool"
        chain.Setup = "Attach"
        chain.ReferencePointJunction = "WORKPIECE_MOUNT"
        chain.X = "X"
        chain.Y = "Y"
        chain.Z = "Z"
        chain.Rotary1 = "B"
        chain.Rotary2 = "C"
        chain_configuration = kinematic.DefineKinematicChains()
        chain_configuration.List.Append(chain)
        if not bool(chain_configuration.Validate()):
            raise RuntimeError("NX rejected milling kinematic chain")
        chain_configuration.Commit()

        assignments = {
            axis: bool(kinematic.IsAxisAssignedToChannel(axis, channel_name))
            for axis in ("X", "Y", "Z", "S", "B", "C")
        }
        missing_assignments = [
            axis for axis, assigned in assignments.items() if not assigned
        ]
        return {
            "method": "low_level_kinematic_builders",
            "component_names": list(plan["build_sequence"]),
            "axis_names": ["X", "Y", "Z", "S", "B", "C"],
            "channel_name": channel_name,
            "channel_axis_assignments": assignments,
            "channel_binding_persisted": not missing_assignments,
            "missing_channel_axis_assignments": missing_assignments,
            "remaining_blockers": (
                ["channel_axis_assignments_missing"]
                if missing_assignments
                else []
            ),
            "chain_name": "MILLING_CHAIN",
            "junction_names": sorted(junction_objects),
            "coordinate_system_count": len(created_csys),
            "component_system_classes": {
                component.title(): [system_class]
                for component, system_class in _MACHINE_REQUIRED_SYSTEM_CLASSES.items()
            },
        }
    except Exception as exc:
        safe = _safe_nx_error(exc)
        raise RuntimeError(
            "low-level kinematic build failed at %s (type=%s, error_code=%s)"
            % (stage, safe["type"], safe["error_code"])
        )
    finally:
        if chain_configuration is not None:
            try:
                chain_configuration.Destroy()
            except Exception:
                pass
        for builder in reversed(builders):
            try:
                builder.Destroy()
            except Exception:
                pass


def _machine_repair_low_level_kinematic_links(work, kinematic, plan):
    sim = _sim_module()
    components = {
        str(item.Name).upper(): item for item in list(kinematic.ComponentCollection)
    }
    inserted_axis_junctions = []
    created_mount_junctions = []
    builders = []

    def commit_junction(owner, name, position, classification):
        builder = kinematic.CreateJunctionBuilder(owner, None)
        builders.append(builder)
        try:
            builder.Name = name
            builder.Csys = work.CoordinateSystems.CreateCoordinateSystem(
                NXOpen.Point3d(*position),
                NXOpen.Vector3d(1.0, 0.0, 0.0),
                NXOpen.Vector3d(0.0, 1.0, 0.0),
            )
            builder.Classification = classification
            if not bool(builder.Validate()):
                raise RuntimeError("NX rejected junction %s" % name)
            junction = builder.Commit()
        finally:
            try:
                builder.Destroy()
            except Exception:
                pass
            builders.remove(builder)
        if junction is None:
            raise RuntimeError("NX returned no object for junction %s" % name)
        owner.InsertJunction(junction)
        created_mount_junctions.append(name)

    try:
        for axis_name in ("X", "Y", "Z", "S", "B", "C"):
            _axis, component, junction = kinematic.FindAxis(axis_name)
            current = {int(item.Tag) for item in list(component.GetJunctions())}
            if int(junction.Tag) not in current:
                component.InsertJunction(junction)
                inserted_axis_junctions.append(str(junction.Name))

        by_name = {item["name"].upper(): item for item in plan["components"]}
        mount_specs = [
            (
                "BASE",
                "MACHINE_ZERO",
                sim.KinematicJunctionBuilder.SystemClass.MachineZero,
            ),
            (
                "TOOL",
                "TOOL_MOUNT",
                sim.KinematicJunctionBuilder.SystemClass.ToolZero,
            ),
            (
                "ATTACH",
                "WORKPIECE_MOUNT",
                sim.KinematicJunctionBuilder.SystemClass.Mount,
            ),
        ]
        for component_name, junction_name, classification in mount_specs:
            owner = components[component_name]
            current_names = {
                str(item.Name).upper() for item in list(owner.GetJunctions())
            }
            if junction_name not in current_names:
                commit_junction(
                    owner,
                    junction_name,
                    by_name[component_name]["position"],
                    classification,
                )
        return {
            "inserted_axis_junctions": inserted_axis_junctions,
            "created_mount_junctions": created_mount_junctions,
            "channel_assignment_repaired": False,
        }
    finally:
        for builder in reversed(builders):
            try:
                builder.Destroy()
            except Exception:
                pass


def _op_build_machine_kinematics_from_profile(params):
    profile = _machine_source_profile(params.get("source_profile"))
    plan = _machine_kinematic_plan(profile)
    _root, target = _machine_build_part_path(params.get("workspace_file_name"))
    if not os.path.isfile(target):
        raise IOError("machine build workspace does not exist")
    manifest = _machine_read_manifest(target)
    if manifest["source_profile"] != profile["name"]:
        raise ValueError("workspace source profile does not match the request")
    channel_name = _cam_safe_name(
        "channel_name", params.get("channel_name", "TNC_640")
    )
    work = None
    try:
        work = _machine_require_active_workspace(target)
    except RuntimeError:
        if not bool(params.get("dry_run", True)):
            raise
    dry_plan = _machine_build_dry_plan(work, plan, channel_name)
    blockers = list(plan["blockers"])
    if dry_plan["missing_imported_geometry_components"]:
        blockers.append("component_geometry_not_imported")
    if not dry_plan["tool_mount_component"]:
        blockers.append("tool_mount_component_missing")
    if not dry_plan["workpiece_mount_component"]:
        blockers.append("workpiece_mount_component_missing")
    dry_run = bool(params.get("dry_run", True))
    result = {
        "ok": not blockers,
        "part": os.path.basename(target),
        "source_profile": profile["public"],
        "dry_run": dry_run,
        "changed": False,
        "build": dry_plan,
        "blockers": blockers,
        "paths_redacted": True,
        "requires_explicit_commit": True,
        "machine_kit_created": False,
        "machine_library_registered": False,
    }
    if dry_run:
        return result
    if params.get("confirmation") != _MACHINE_KINEMATICS_BUILD_CONFIRMATION:
        raise PermissionError(
            "Building machine kinematics requires confirmation=%s"
            % _MACHINE_KINEMATICS_BUILD_CONFIRMATION
        )
    if blockers:
        raise RuntimeError(
            "Machine kinematics build is blocked; blockers=%s" % ",".join(blockers)
        )
    session = NXOpen.Session.GetSession()
    sim = _sim_module()
    geometry_names_by_component = {
        item["component"]: item["geometry_object_names"]
        for item in dry_plan["component_operations"]
    }
    by_name = {item["name"]: item for item in plan["components"]}
    smk = None
    channel_builder = None
    previous_application = ""
    machine_builder_application = "UG_APP_MACHINE_TOOL_BUILDER"
    mark_name = "NX MCP Build Machine Kinematics"
    mark = None
    created_csys = []
    stage = "read_machine_builder_application"
    try:
        previous_application = str(getattr(session, "ApplicationName", "") or "")
        if previous_application != machine_builder_application:
            stage = "switch_to_machine_builder_application"
            session.ApplicationSwitchImmediate(machine_builder_application)
            session = NXOpen.Session.GetSession()
        stage = "reacquire_active_machine_workspace"
        work = _machine_require_active_workspace(target)
        stage = "create_machine_build_undo_mark"
        mark = session.SetUndoMark(session.MarkVisibility.Visible, mark_name)
        stage = "initialize_kinematic_configurator"
        kinematic = _machine_kinematic_configurator(work, create=True)
        existing = _machine_kinematic_record(work)
        if existing["axis_names"] or existing["channels"]:
            missing_existing_axes = [
                axis
                for axis in profile["expected_axes"]
                if not _machine_axis_matches(existing["axis_names"], axis)
            ]
            existing_components = {
                str(item.Name).upper() for item in list(kinematic.ComponentCollection)
            }
            missing_existing_components = [
                item["name"]
                for item in plan["components"]
                if item["name"].upper() not in existing_components
            ]
            if missing_existing_axes or missing_existing_components:
                raise RuntimeError(
                    "Workspace contains an incomplete or unrelated kinematic model"
                )
            stage = "repair_existing_kinematic_links"
            repair = _machine_repair_low_level_kinematic_links(
                work, kinematic, plan
            )
            stage = "update_repaired_kinematics"
            update_errors = int(session.UpdateManager.DoUpdate(mark))
            if update_errors:
                raise RuntimeError("NX reported update errors after kinematic repair")
            session.SetUndoMarkName(mark, "NX MCP Repaired Machine Kinematics")
            readback = _machine_kinematic_record(work)
            changed = bool(
                repair["inserted_axis_junctions"]
                or repair["created_mount_junctions"]
            )
            result.update(
                {
                    "ok": True,
                    "dry_run": False,
                    "changed": changed,
                    "repaired_existing": True,
                    "repair": repair,
                    "readback": readback,
                    "remaining_blockers": [
                        "channel_axis_assignments_missing",
                        "component_system_classes_missing",
                        "kinematic_chains_missing",
                    ],
                    "application_before": previous_application or None,
                    "application_after": str(
                        getattr(
                            NXOpen.Session.GetSession(), "ApplicationName", ""
                        )
                        or ""
                    ),
                    "saved": False,
                }
            )
            return result
        geometry_objects = {
            str(getattr(item, "Name", "") or ""): item
            for item in _machine_faceted_bodies(work)
            if str(getattr(item, "Name", "") or "").startswith("MCP_MACHINE_")
        }
        if manifest.get("workspace_strategy") == "blank_smart_machine_kit":
            stage = "build_smart_machine_kit_kinematics"
            machine_build = _machine_build_imported_template_kinematics(
                work,
                kinematic,
                plan,
                geometry_objects,
                geometry_names_by_component,
                channel_name,
            )
        else:
            stage = "build_low_level_kinematics"
            machine_build = _machine_build_low_level_kinematics(
                work,
                kinematic,
                plan,
                geometry_objects,
                geometry_names_by_component,
                channel_name,
            )
        stage = "update_machine_kinematics"
        update_errors = int(session.UpdateManager.DoUpdate(mark))
        if update_errors:
            raise RuntimeError("NX reported update errors after kinematic build")
        session.SetUndoMarkName(mark, "NX MCP Built Machine Kinematics")
        readback = _machine_kinematic_record(work)
        result.update(
            {
                "ok": True,
                "dry_run": False,
                "changed": True,
                "build_method": machine_build,
                "readback": readback,
                "remaining_blockers": list(
                    machine_build.get("remaining_blockers", [])
                ),
                "application_before": previous_application or None,
                "application_after": str(
                    getattr(NXOpen.Session.GetSession(), "ApplicationName", "") or ""
                ),
                "saved": False,
            }
        )
        return result

        stage = "create_smart_machine_kit_builder"
        smk = kinematic.CreateSmkWizardBuilder()
        stage = "initialize_smart_machine_kit_template"
        smk.MachineTemplate = "5 Axis Dual Table BC Mill"
        smk.ParseTemplates()
        smk.SetWizardStep(sim.SmkWizardBuilder.WizardStep.GeometrySelection)
        template_components = {
            "Base": "MACHINE_BASE",
            "X": "X_AXIS",
            "Y": "Y_AXIS",
            "Z": "Z_AXIS",
            "Spindle": "SPINDLE",
            "Tool": "SPINDLE_POCKET",
            "B": "B_AXIS",
            "C": "C_AXIS",
            "Attach": "SETUP",
        }
        machine_base = str(smk.AskMachineBaseComponent() or "").strip()
        if machine_base != template_components["Base"]:
            raise RuntimeError("NX returned an unexpected machine template root")
        stage = "assign_component_geometry"
        for name in plan["build_sequence"]:
            component = by_name[name]
            nx_component = template_components.get(name)
            if not nx_component:
                raise RuntimeError("machine plan cannot be mapped to the NX five-axis template")
            for geometry_name in geometry_names_by_component[name]:
                smk.AddGeometry(nx_component, geometry_objects[geometry_name])

        stage = "configure_template_axes"
        smk.SetWizardStep(sim.SmkWizardBuilder.WizardStep.JunctionSelection)
        smk.SetWizardStep(sim.SmkWizardBuilder.WizardStep.AxisDefinition)
        axis_number = 0
        for name in plan["build_sequence"]:
            component = by_name[name]
            if component["type"] in ("linear", "rotary", "spindle"):
                axis_name = (
                    "S"
                    if component["type"] == "spindle"
                    else component["axis"]["address"]
                )
                stage = "configure_axis_%s_presence" % axis_name
                if not bool(smk.HasAxis(axis_name)):
                    raise RuntimeError("NX machine template is missing axis %s" % axis_name)
                axis_type = {
                    "linear": sim.SmkWizardBuilder.AxisMotionType.Linear,
                    "rotary": (
                        sim.SmkWizardBuilder.AxisMotionType.RotaryUnlimited
                        if component["axis"]["unlimited"]
                        else sim.SmkWizardBuilder.AxisMotionType.Rotary
                    ),
                    "spindle": sim.SmkWizardBuilder.AxisMotionType.Spindle,
                }[component["type"]]
                stage = "configure_axis_%s_motion" % axis_name
                smk.SetAxisMotion(axis_name, True, axis_type)
                direction = component["axis"]["direction"]
                direction_enum = {
                    "X": sim.SmkWizardBuilder.AxisDirectionType.PositiveX,
                    "Y": sim.SmkWizardBuilder.AxisDirectionType.PositiveY,
                    "Z": sim.SmkWizardBuilder.AxisDirectionType.PositiveZ,
                }.get(direction)
                if direction_enum is None:
                    raise ValueError("unsupported machine axis direction")
                stage = "configure_axis_%s_direction" % axis_name
                smk.SetAxisDirection(axis_name, direction_enum)
                axis_number += 1
                stage = "configure_axis_%s_number" % axis_name
                smk.SetAxisNumber(axis_name, axis_number)
                stage = "configure_axis_%s_initial_value" % axis_name
                smk.SetAxisInitialValue(axis_name, 0.0)
                if (
                    component["type"] in ("linear", "rotary")
                    and not component["axis"]["unlimited"]
                ):
                    if (
                        component["axis"]["lower_limit"] is None
                        or component["axis"]["upper_limit"] is None
                    ):
                        raise ValueError("bounded machine axis is missing travel limits")
                    lower = float(component["axis"]["lower_limit"])
                    upper = float(component["axis"]["upper_limit"])
                    span = upper - lower
                    if span <= 0.0:
                        raise ValueError("bounded machine axis limits are invalid")
                    soft_margin = max(span * 1.0e-6, 1.0e-6)
                    soft_lower = lower + soft_margin
                    soft_upper = upper - soft_margin
                    initial_value = min(max(0.0, soft_lower), soft_upper)
                    stage = "configure_axis_%s_hard_limits" % axis_name
                    smk.SetAxisLowerLimit(axis_name, lower)
                    smk.SetAxisUpperLimit(axis_name, upper)
                    stage = "configure_axis_%s_soft_limits" % axis_name
                    smk.SetAxisLowerSoftLimit(axis_name, soft_lower)
                    smk.SetAxisUpperSoftLimit(axis_name, soft_upper)
                    stage = "configure_axis_%s_bounded_initial_value" % axis_name
                    smk.SetAxisInitialValue(axis_name, initial_value)

        stage = "create_kinematic_chains"
        smk.SetWizardStep(sim.SmkWizardBuilder.WizardStep.ChainConfiguration)
        smk.CreateAutoChains()

        stage = "create_kinematic_channel"
        smk.SetWizardStep(sim.SmkWizardBuilder.WizardStep.ChannelConfiguration)
        stage = "create_kinematic_channel_builder"
        channel_builder = smk.CreateSmkKimChannelBuilder()
        stage = "set_kinematic_channel_name"
        channel_builder.Name = channel_name
        assigned_axes = [
            item["axis"]["address"]
            for item in plan["components"]
            if item["type"] in ("linear", "rotary")
        ]
        stage = "assign_kinematic_channel_axes"
        channel_builder.SetAssignedAxes(assigned_axes)
        for address in ("X", "Y", "Z"):
            matched = next(
                (item for item in assigned_axes if _machine_axis_matches([item], address)),
                "",
            )
            stage = "set_kinematic_channel_geometry_axis_%s" % address
            setattr(channel_builder, "GeometryAxis%s" % address, matched)
        spindle = next(
            (
                "S"
                for item in plan["components"]
                if item["type"] == "spindle"
            ),
            "",
        )
        if spindle:
            stage = "set_kinematic_channel_main_spindle"
            channel_builder.MainSpindle = spindle
            stage = "set_kinematic_channel_referenced_spindle"
            channel_builder.SetReferencedSpindle(spindle)
        stage = "validate_kinematic_channel"
        if not bool(channel_builder.Validate()):
            raise RuntimeError("NX rejected the machine kinematic channel")
        stage = "append_kinematic_channel"
        smk.SmkKimChannelConfigurationBuilder.KinematicChannels.Append(
            channel_builder
        )
        stage = "validate_smart_machine_kit_builder"
        if not bool(smk.Validate()):
            raise RuntimeError("NX rejected the Smart Machine Kit build state")
        stage = "commit_smart_machine_kit_builder"
        smk.Commit()
        stage = "update_kinematic_part"
        update_errors = int(session.UpdateManager.DoUpdate(mark))
        if update_errors:
            raise RuntimeError("NX reported update errors after kinematic build")
        session.SetUndoMarkName(mark, "NX MCP Built Machine Kinematics")
    except Exception as exc:
        if mark is not None:
            try:
                session.UndoToMark(mark, mark_name)
            except Exception:
                pass
        if previous_application and previous_application != machine_builder_application:
            try:
                session.ApplicationSwitchImmediate(previous_application)
            except Exception:
                pass
        safe = _safe_nx_error(exc)
        message = str(exc).strip().replace("\r", " ").replace("\n", " ")[:240]
        raise RuntimeError(
            "NX machine kinematics build failed at %s (type=%s, error_code=%s, detail=%s); changes were rolled back"
            % (stage, safe["type"], safe["error_code"], message or "unavailable")
        )
    finally:
        if channel_builder is not None:
            try:
                channel_builder.Destroy()
            except Exception:
                pass
        if smk is not None:
            try:
                smk.Destroy()
            except Exception:
                pass
    result.update(
        {
            "ok": True,
            "dry_run": False,
            "changed": True,
            "readback": _machine_kinematic_record(work),
            "application_before": previous_application or None,
            "application_after": str(getattr(session, "ApplicationName", "") or ""),
            "saved": False,
        }
    )
    return result


def _op_validate_machine_kinematics(params):
    profile = _machine_source_profile(params.get("source_profile"))
    plan = _machine_kinematic_plan(profile)
    _root, target = _machine_build_part_path(params.get("workspace_file_name"))
    work = _machine_require_active_workspace(target)
    manifest = _machine_read_manifest(target)
    if manifest["source_profile"] != profile["name"]:
        raise ValueError("workspace source profile does not match the request")
    kinematic = _machine_kinematic_configurator(work, create=False)
    record = _machine_kinematic_record(work)
    component_names = []
    component_tree = []
    component_system_classes = {}
    component_geometry_names = {}
    smart_template_workspace = (
        manifest.get("workspace_strategy") == "blank_smart_machine_kit"
    )
    smart_component_map = {
        "Base": "MACHINE_BASE",
        "X": "X_SLIDE",
        "Y": "Y_SLIDE",
        "Z": "Z_SLIDE",
        "Spindle": "SPINDLE",
        "Tool": "POCKET_01",
        "B": "B_SLIDE",
        "C": "C_SLIDE",
        "Attach": "SETUP",
    }
    sim = _sim_module()
    system_class_members = [
        (getattr(sim.KinematicComponentBuilder.SystemClass, name), name)
        for name in dir(sim.KinematicComponentBuilder.SystemClass)
        if not name.startswith("_")
        and not callable(getattr(sim.KinematicComponentBuilder.SystemClass, name))
    ]
    if kinematic is not None:
        try:
            collection = kinematic.ComponentCollection
            components = (
                list(collection.ToArray())
                if hasattr(collection, "ToArray")
                else list(collection)
            )
            for component in components:
                name = str(component.Name)
                parent = component.GetParent()
                parent_name = (
                    str(parent.Name)
                    if parent is not None and getattr(parent, "Tag", 0) != 0
                    else None
                )
                component_names.append(name)
                component_tree.append({"name": name, "parent": parent_name})
                builder = None
                try:
                    builder = kinematic.ComponentCollection.CreateComponentBuilder(
                        parent, component
                    )
                    component_system_classes[name] = [
                        next(
                            (
                                member_name
                                for member, member_name in system_class_members
                                if item == member
                            ),
                            str(item),
                        )
                        for item in builder.GetSystemClasses()
                    ]
                    component_geometry_names[name] = [
                        str(getattr(item, "Name", "") or "")
                        for item in builder.GetGeometries()
                    ]
                except Exception:
                    component_system_classes[name] = []
                    component_geometry_names[name] = []
                finally:
                    if builder is not None:
                        try:
                            builder.Destroy()
                        except Exception:
                            pass
        except Exception:
            component_names = []
            component_tree = []
            component_system_classes = {}
    component_names_upper = {name.upper() for name in component_names}
    missing_components = [
        (
            smart_component_map[item["name"]]
            if smart_template_workspace
            else item["name"]
        )
        for item in plan["components"]
        if (
            smart_component_map[item["name"]].upper()
            if smart_template_workspace
            else item["name"].upper()
        ) not in component_names_upper
    ]
    missing_axes = [
        axis for axis in profile["expected_axes"]
        if not _machine_axis_matches(record["axis_names"], axis)
    ]
    if smart_template_workspace:
        missing_geometry = [
            smart_component_map[item["name"]]
            for item in plan["components"]
            if item["geometry"]
            and not component_geometry_names.get(
                smart_component_map[item["name"]], []
            )
        ]
    else:
        geometry_map = _machine_component_geometry_map(work, plan)
        missing_geometry = [
            item["name"]
            for item in plan["components"]
            if item["geometry"] and not geometry_map[item["name"]]
        ]
    blockers = []
    if not record["available"]:
        blockers.append("kinematic_model_not_available")
    if missing_components:
        blockers.append("kinematic_components_missing")
    if missing_axes:
        blockers.append("expected_axes_missing")
    if not record["channels"]:
        blockers.append("kinematic_channel_missing")
    if bool(params.get("require_geometry", True)) and missing_geometry:
        blockers.append("component_geometry_missing")
    channel_axis_assignments = {}
    missing_channel_axis_assignments = []
    channel_axes = list(profile["expected_axes"])
    if _machine_axis_matches(record["axis_names"], "S"):
        channel_axes.append("S")
    if kinematic is not None and record["channels"]:
        for channel in record["channels"]:
            channel_axis_assignments[channel] = {
                axis: bool(kinematic.IsAxisAssignedToChannel(axis, channel))
                for axis in channel_axes
            }
        missing_channel_axis_assignments = [
            axis
            for axis in channel_axes
            if not any(
                assignments[axis]
                for assignments in channel_axis_assignments.values()
            )
        ]
    if missing_channel_axis_assignments:
        blockers.append("channel_axis_assignments_missing")
    required_junction_suffixes = (
        {
            "MACHINE_ZERO",
            "S",
            "T1",
            "ROT_JCT_AUX",
            "ROT_JCT",
            "PART_MOUNT_JCT",
        }
        if smart_template_workspace
        else {
            "MACHINE_ZERO",
            "JCT_X",
            "JCT_Y",
            "JCT_Z",
            "JCT_SPINDLE",
            "TOOL_MOUNT",
            "JCT_B",
            "JCT_C",
            "WORKPIECE_MOUNT",
        }
    )
    present_junction_suffixes = {
        str(item).rsplit("@", 1)[-1].upper()
        for item in record.get("junction_names", [])
    }
    missing_junctions = sorted(
        required_junction_suffixes - present_junction_suffixes
    )
    if missing_junctions:
        blockers.append("required_kinematic_junctions_missing")
    required_system_classes = (
        {
            "MACHINE_BASE": "Machine",
            "SPINDLE": "Turret",
            "POCKET_01": "PocketOnHead",
            "SETUP": "SetupElement",
        }
        if smart_template_workspace
        else _MACHINE_REQUIRED_SYSTEM_CLASSES
    )
    missing_system_classes = [
        {"component": component, "system_class": system_class}
        for component, system_class in required_system_classes.items()
        if system_class
        not in component_system_classes.get(component, [])
    ]
    if missing_system_classes:
        blockers.append("component_system_classes_missing")
    if smart_template_workspace:
        has_required_chain = any(
            set(("X", "Y", "Z", "B", "C")).issubset(
                set(item.get("axes", []))
            )
            and item.get("device") == "POCKET_01"
            and item.get("setup") == "SETUP"
            for item in record.get("chains", [])
        )
        missing_chains = [] if has_required_chain else ["five_axis_milling_chain"]
    else:
        missing_chains = [
            "MILLING_CHAIN"
            if "MILLING_CHAIN" not in record.get("chain_names", [])
            else None
        ]
        missing_chains = [item for item in missing_chains if item]
    if missing_chains:
        blockers.append("kinematic_chains_missing")
    structural_ok = not blockers
    return {
        "ok": structural_ok,
        "part": os.path.basename(target),
        "source_profile": profile["public"],
        "structural_validation_passed": structural_ok,
        "kinematics": record,
        "component_tree": component_tree,
        "component_system_classes": component_system_classes,
        "component_geometry_names": component_geometry_names,
        "missing_components": missing_components,
        "missing_expected_axes": missing_axes,
        "missing_geometry_components": missing_geometry,
        "channel_axis_assignments": channel_axis_assignments,
        "missing_channel_axis_assignments": missing_channel_axis_assignments,
        "missing_required_junctions": missing_junctions,
        "missing_component_system_classes": missing_system_classes,
        "missing_kinematic_chains": missing_chains,
        "blockers": blockers,
        "axis_motion_probe_performed": False,
        "static_collision_probe_performed": False,
        "machine_kit_export_ready": False,
        "remaining_validation": [
            "safe_axis_motion_probe",
            "static_collision_pair_validation",
            "machine_zero_and_mount_alignment_measurement",
        ],
        "paths_redacted": True,
        "production_certified": False,
    }


def _op_probe_machine_axis_motion(params):
    profile = _machine_source_profile(params.get("source_profile"))
    plan = _machine_kinematic_plan(profile)
    _root, target = _machine_build_part_path(params.get("workspace_file_name"))
    work = _machine_require_active_workspace(target)
    manifest = _machine_read_manifest(target)
    if manifest["source_profile"] != profile["name"]:
        raise ValueError("workspace source profile does not match the request")
    axis_name = _cam_safe_name("axis_name", params.get("axis_name", "X")).upper()
    if axis_name == "S":
        raise ValueError("spindle motion is not allowed in the rollback probe")
    axis_plan = next(
        (
            item["axis"]
            for item in plan["components"]
            if item.get("axis")
            and str(item["axis"].get("address", "")).upper() == axis_name
        ),
        None,
    )
    if axis_plan is None:
        raise ValueError("axis_name is not defined by the machine source profile")
    delta = float(params.get("delta", 0.01))
    rotary = axis_name in ("A", "B", "C")
    maximum_delta = 0.1
    if delta == 0.0 or abs(delta) > maximum_delta:
        unit = "degree" if rotary else "millimeter"
        raise ValueError(
            "delta must be non-zero and no greater than 0.1 %s" % unit
        )
    dry_run = bool(params.get("dry_run", True))
    result = {
        "ok": True,
        "part": os.path.basename(target),
        "source_profile": profile["public"],
        "axis_name": axis_name,
        "delta": delta,
        "unit": "degree" if rotary else "millimeter",
        "dry_run": dry_run,
        "changed": False,
        "rolled_back": True,
        "saved": False,
        "requires_explicit_confirmation": True,
        "geometric_motion_verified": False,
        "production_certified": False,
    }
    if dry_run:
        result.update(
            {
                "probe_performed": False,
                "note": "The live probe always restores the axis initial value with NX undo.",
            }
        )
        return result
    if params.get("confirmation") != _MACHINE_AXIS_PROBE_CONFIRMATION:
        raise PermissionError(
            "Machine axis probe requires confirmation=%s"
            % _MACHINE_AXIS_PROBE_CONFIRMATION
        )
    structural = _op_validate_machine_kinematics(
        {
            "source_profile": profile["name"],
            "workspace_file_name": os.path.basename(target),
            "require_geometry": True,
        }
    )
    if not structural.get("structural_validation_passed"):
        raise RuntimeError("Machine axis probe is blocked by structural validation")
    session = NXOpen.Session.GetSession()
    kinematic = _machine_kinematic_configurator(work, create=False)
    mark_name = "NX MCP Rollback Axis Probe"
    mark = session.SetUndoMark(session.MarkVisibility.Invisible, mark_name)
    builder = None
    stage = "read_axis"
    before_value = None
    applied_value = None
    restored_value = None
    try:
        axis, component, junction = kinematic.FindAxis(axis_name)
        builder = kinematic.CreateAxisBuilder(component, junction, axis)
        before_value = float(builder.InitialValue)
        target_value = before_value + delta
        lower = axis_plan.get("lower_limit")
        upper = axis_plan.get("upper_limit")
        if not bool(axis_plan.get("unlimited")) and lower is not None and upper is not None:
            if target_value <= float(lower) or target_value >= float(upper):
                raise ValueError("axis probe target would cross a configured travel limit")
        stage = "apply_axis_probe"
        builder.Name = axis_name
        builder.Junction = junction
        builder.InitialValue = target_value
        if not bool(builder.Validate()):
            raise RuntimeError("NX rejected the temporary axis value")
        builder.Commit()
        builder.Destroy()
        builder = None
        update_errors = int(session.UpdateManager.DoUpdate(mark))
        if update_errors:
            raise RuntimeError("NX reported update errors during the axis probe")
        axis_after, component_after, junction_after = kinematic.FindAxis(axis_name)
        builder = kinematic.CreateAxisBuilder(
            component_after, junction_after, axis_after
        )
        applied_value = float(builder.InitialValue)
        builder.Destroy()
        builder = None
        if abs(applied_value - target_value) > 1.0e-9:
            raise RuntimeError("NX axis value readback does not match the probe target")
        stage = "rollback_axis_probe"
        session.UndoToMark(mark, mark_name)
        mark = None
        kinematic = _machine_kinematic_configurator(work, create=False)
        axis_restored, component_restored, junction_restored = kinematic.FindAxis(
            axis_name
        )
        builder = kinematic.CreateAxisBuilder(
            component_restored, junction_restored, axis_restored
        )
        restored_value = float(builder.InitialValue)
        builder.Destroy()
        builder = None
        if abs(restored_value - before_value) > 1.0e-9:
            raise RuntimeError("NX undo did not restore the axis initial value")
        result.update(
            {
                "probe_performed": True,
                "before_value": before_value,
                "target_value": target_value,
                "applied_value": applied_value,
                "restored_value": restored_value,
                "readback_passed": True,
                "rollback_passed": True,
                "axis_configuration_probe_passed": True,
            }
        )
        return result
    except Exception as exc:
        safe = _safe_nx_error(exc)
        detail = str(exc).strip().replace("\r", " ").replace("\n", " ")[:240]
        raise RuntimeError(
            "Machine axis probe failed at %s (type=%s, error_code=%s, detail=%s)"
            % (stage, safe["type"], safe["error_code"], detail or "unavailable")
        )
    finally:
        if builder is not None:
            try:
                builder.Destroy()
            except Exception:
                pass
        if mark is not None:
            try:
                session.UndoToMark(mark, mark_name)
            except Exception:
                pass


def _op_retarget_machine_junctions_from_profile(params):
    profile = _machine_source_profile(params.get("source_profile"))
    plan = _machine_kinematic_plan(profile)
    _root, target = _machine_build_part_path(params.get("workspace_file_name"))
    work = _machine_require_active_workspace(target)
    manifest = _machine_read_manifest(target)
    if manifest["source_profile"] != profile["name"]:
        raise ValueError("workspace source profile does not match the request")
    target_positions = _machine_cumulative_component_positions(plan)
    dry_run = bool(params.get("dry_run", True))
    result = {
        "ok": True,
        "part": os.path.basename(target),
        "source_profile": profile["public"],
        "dry_run": dry_run,
        "changed": False,
        "saved": False,
        "coordinate_source": "oem_machine_definition_absolute",
        "target_component_positions": target_positions,
        "requires_explicit_confirmation": True,
        "production_certified": False,
    }
    if dry_run:
        result["note"] = (
            "No junctions were changed; set dry_run=false and provide the exact confirmation."
        )
        return result
    if params.get("confirmation") != _MACHINE_JUNCTION_RETARGET_CONFIRMATION:
        raise PermissionError(
            "Machine junction retargeting requires confirmation=%s"
            % _MACHINE_JUNCTION_RETARGET_CONFIRMATION
        )
    structural = _op_validate_machine_kinematics(
        {
            "source_profile": profile["name"],
            "workspace_file_name": os.path.basename(target),
            "require_geometry": True,
        }
    )
    if not structural.get("structural_validation_passed"):
        raise RuntimeError("Machine junction retargeting is blocked by structural validation")
    session = NXOpen.Session.GetSession()
    mark_name = "NX MCP Retargeted OEM Junction Coordinates"
    mark = session.SetUndoMark(session.MarkVisibility.Visible, mark_name)
    try:
        kinematic = _machine_kinematic_configurator(work, create=False)
        retarget = _machine_retarget_template_junctions(work, kinematic, plan)
        update_errors = int(session.UpdateManager.DoUpdate(mark))
        if update_errors:
            raise RuntimeError("NX reported update errors after OEM junction retargeting")
        result.update(
            {
                "changed": True,
                "junction_retarget": retarget,
                "readback_passed": True,
                "all_tags_preserved": retarget["all_tags_preserved"],
            }
        )
        return result
    except Exception:
        session.UndoToMark(mark, mark_name)
        raise


def _machine_library_database_fingerprints():
    """Fingerprint known NX machine databases without exposing their paths."""
    candidates = []
    base = str(os.environ.get("UGII_BASE_DIR", "") or "").strip()
    if base:
        candidates.append(
            os.path.join(
                base, "MACH", "resource", "library", "machine", "ascii",
                "machine_database.dat",
            )
        )
    for variable in (
        "UGII_CAM_LIBRARY_MACHINE_DIR",
        "UGII_CAM_LIBRARY_INSTALLED_MACHINES_DIR",
    ):
        folder = str(os.environ.get(variable, "") or "").strip()
        if folder:
            candidates.extend(
                (
                    os.path.join(folder, "machine_database.dat"),
                    os.path.join(os.path.dirname(folder), "machine_database.dat"),
                )
            )
    records = []
    seen = set()
    for path in candidates:
        normalized = os.path.normcase(os.path.abspath(path))
        if normalized in seen or not os.path.isfile(path):
            continue
        seen.add(normalized)
        fingerprint = _machine_file_fingerprint(path)
        records.append(
            {
                "id": hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12],
                "size": fingerprint["size"],
                "sha256": fingerprint["sha256"],
            }
        )
    return sorted(records, key=lambda item: item["id"])


def _op_export_machine_kit_from_reference(params):
    """Export a complete sanitized kit via NX's official reference-kit builder."""
    profile = _machine_source_profile(params.get("source_profile"))
    _root, target = _machine_build_part_path(params.get("workspace_file_name"))
    work = _machine_require_active_workspace(target)
    manifest = _machine_read_manifest(target)
    if manifest["source_profile"] != profile["name"]:
        raise ValueError("workspace source profile does not match the request")
    output_root, output_path = _machine_kit_path(
        params.get("output_file_name", "mikron_mill_e500u_tnc640.mtk")
    )
    reference_container_name = str(
        params.get("reference_container_file_name") or ""
    ).strip()
    reference_container_path = None
    if reference_container_name:
        _reference_root, reference_container_path = _machine_kit_path(
            reference_container_name, must_exist=True
        )
        if _machine_normalized_path(reference_container_path) == _machine_normalized_path(
            output_path
        ):
            raise ValueError("reference container and output machine kit must differ")
        if not _machine_kit_is_verified_reference_container(reference_container_path):
            raise ValueError("reference container is not a verified complete sanitized MTK")
    kit_identifier = _machine_kit_identifier(output_path)
    graphics_file_name = str(params.get("graphics_file_name") or "").strip()
    overwrite = bool(params.get("overwrite", False))
    dry_run = bool(params.get("dry_run", True))
    structural = _op_validate_machine_kinematics(
        {
            "source_profile": profile["name"],
            "workspace_file_name": os.path.basename(target),
            "require_geometry": True,
        }
    )
    result = {
        "ok": bool(structural.get("structural_validation_passed")),
        "dry_run": dry_run,
        "changed": False,
        "part": os.path.basename(target),
        "source_profile": profile["public"],
        "output_file_name": os.path.basename(output_path),
        "kit_identifier": kit_identifier,
        "graphics_file_name": graphics_file_name or (kit_identifier + ".prt"),
        "structural_validation_passed": bool(
            structural.get("structural_validation_passed")
        ),
        "structural_blockers": list(structural.get("blockers", [])),
        "packaging_route": "nx_reference_kit_repackage",
        "reference_container_file_name": (
            os.path.basename(reference_container_path)
            if reference_container_path
            else None
        ),
        "verified_reference_container_requested": bool(reference_container_path),
        "machine_kit_builder_580055_avoided": True,
        "global_machine_library_modified": False,
        "metadata_sanitized": True,
        "paths_redacted": True,
        "requires_explicit_confirmation": True,
        "production_certified": False,
    }
    if not result["structural_validation_passed"]:
        return result
    if not os.path.isfile(target) or os.path.getsize(target) <= 0:
        raise RuntimeError("active machine workspace part is not saved")
    if os.path.exists(output_path) and not overwrite:
        raise IOError("machine kit already exists: %s" % os.path.basename(output_path))
    if dry_run:
        result["note"] = (
            "No archive was written; set dry_run=false and provide the exact confirmation."
        )
        return result
    if params.get("confirmation") != _MACHINE_KIT_EXPORT_CONFIRMATION:
        raise PermissionError(
            "Machine kit export requires confirmation=%s"
            % _MACHINE_KIT_EXPORT_CONFIRMATION
        )
    if not os.path.isdir(output_root):
        os.makedirs(output_root)

    staging = tempfile.mkdtemp(prefix=".nxmcp-reference-export-", dir=output_root)
    builder = None
    session = NXOpen.Session.GetSession()
    previous_application = str(getattr(session, "ApplicationName", "") or "")
    machine_builder_application = "UG_APP_MACHINE_TOOL_BUILDER"
    try:
        if (
            reference_container_path is None
            and previous_application != machine_builder_application
        ):
            session.ApplicationSwitchImmediate(machine_builder_application)
            session = NXOpen.Session.GetSession()
            work = _machine_require_active_workspace(target)
        reference_archive = reference_container_path
        reference_export_error = None
        if reference_archive is None:
            try:
                kinematic = work.KinematicConfigurator
                builder = kinematic.ExportMachineKitBuilder(
                    _MACHINE_KIT_REFERENCE_LIBREF
                )
                builder.KitName = "nx_mcp_reference_container"
                builder.OutputDirectory = staging
                builder.PrintReport = False
                if not bool(builder.Validate()):
                    raise RuntimeError("NX rejected the official reference-kit export")
                builder.Commit()
                candidates = []
                for folder, _directories, files in os.walk(staging):
                    for file_name in files:
                        if file_name.lower().endswith(".mtk"):
                            candidates.append(os.path.join(folder, file_name))
                if len(candidates) != 1:
                    raise RuntimeError(
                        "NX did not create exactly one reference MTK archive"
                    )
                reference_archive = candidates[0]
            except Exception as exc:
                if not (
                    overwrite
                    and _machine_kit_is_verified_reference_container(output_path)
                ):
                    raise
                reference_export_error = _safe_nx_error(exc)
                reference_archive = output_path
            finally:
                if builder is not None:
                    builder.Destroy()
                    builder = None
        archive_record = _machine_kit_repackage_reference(
            reference_archive,
            output_path,
            target,
            kit_identifier,
            graphics_file_name=graphics_file_name or None,
        )
        result.update(
            {
                "ok": True,
                "changed": True,
                "archive": archive_record,
                "complete_archive_verified": True,
                "saved": True,
                "application_restored": True,
                "reference_container_reused": bool(
                    reference_container_path is not None
                    or reference_export_error is not None
                ),
                "reference_export_error": reference_export_error,
            }
        )
        return result
    finally:
        if builder is not None:
            builder.Destroy()
        shutil.rmtree(staging, ignore_errors=True)
        if previous_application and previous_application != machine_builder_application:
            session.ApplicationSwitchImmediate(previous_application)


def _machine_open_part_readback(
    part_path, evaluate_static_collisions=False, oem_collision_configuration=None
):
    """Open one isolated imported graphics part, read kinematics, and close it."""
    session = NXOpen.Session.GetSession()
    before_work = session.Parts.Work
    before_display = session.Parts.Display
    normalized = os.path.normcase(os.path.realpath(part_path))
    part = None
    opened_here = False
    loaded_by_import_builder = False
    load_status = None
    close_error = None
    try:
        for candidate in session.Parts:
            candidate_path = str(getattr(candidate, "FullPath", "") or "")
            if candidate_path and os.path.normcase(os.path.realpath(candidate_path)) == normalized:
                part = candidate
                loaded_by_import_builder = True
                break
        if part is None:
            part, load_status = session.Parts.Open(part_path)
            opened_here = True
        if part is None or getattr(part, "Tag", 0) == 0:
            raise RuntimeError("NX did not open the imported machine graphics part")
        kinematics = _machine_kinematic_record(part)
        try:
            components = list(part.KinematicConfigurator.ComponentCollection)
        except Exception:
            components = []
        return_record = {
            "part_file_name": os.path.basename(part_path),
            "kinematics": kinematics,
            "component_count": len(components),
            "component_names": [str(item.Name) for item in components],
            "work_part_preserved": session.Parts.Work == before_work,
            "display_part_preserved": session.Parts.Display == before_display,
            "opened_non_display": part != session.Parts.Display,
        }
        if evaluate_static_collisions:
            collision = _machine_collision_pair_records(part)
            evaluation_collision = (
                collision
                if collision["pair_count"]
                else (oem_collision_configuration or {"pairs": []})
            )
            return_record["collision_configuration"] = collision
            return_record["oem_collision_configuration"] = (
                oem_collision_configuration
            )
            return_record["static_evaluation_pair_source"] = (
                "persisted_machine_collision_pairs"
                if collision["pair_count"]
                else (
                    "oem_machine_definition"
                    if oem_collision_configuration
                    else "none"
                )
            )
            mark_name = "NX MCP Imported Static Collision Evaluation"
            mark = session.SetUndoMark(
                session.MarkVisibility.Invisible, mark_name
            )
            try:
                return_record["static_collision_evaluation"] = (
                    _machine_evaluate_static_collision_pairs(
                        part, evaluation_collision
                    )
                )
            finally:
                session.UndoToMark(mark, mark_name)
    finally:
        if load_status is not None:
            load_status.Dispose()
        import_root = _machine_normalized_path(
            os.path.join(WORKSPACE, "machine_kit_imports")
        )
        safe_import_part = bool(
            part is not None
            and part != before_work
            and part != before_display
            and _machine_path_is_within(import_root, normalized)
        )
        if (
            (opened_here or safe_import_part)
            and part is not None
            and getattr(part, "Tag", 0) != 0
        ):
            responses = session.Parts.NewPartCloseResponses()
            try:
                part.Close(
                    NXOpen.BasePart.CloseWholeTree.TrueValue,
                    NXOpen.BasePart.CloseModified.DontCloseModified,
                    responses,
                )
            except Exception as exc:
                close_error = _safe_nx_error(exc)
            finally:
                responses.Dispose()
    return_record["loaded_by_import_builder"] = loaded_by_import_builder
    return_record["closed_after_readback"] = bool(
        (opened_here or safe_import_part) and close_error is None
    )
    if close_error is not None:
        return_record["close_warning"] = close_error
    return return_record


def _machine_close_stale_import_parts(import_root, close_existing=False):
    session = NXOpen.Session.GetSession()
    work = session.Parts.Work
    display = session.Parts.Display
    normalized_root = _machine_normalized_path(import_root)
    closed = 0
    for part in list(session.Parts):
        path = str(getattr(part, "FullPath", "") or "")
        if not path or part == work or part == display:
            continue
        normalized = _machine_normalized_path(path)
        if not _machine_path_is_within(normalized_root, normalized):
            continue
        if os.path.isfile(path) and not close_existing:
            continue
        responses = session.Parts.NewPartCloseResponses()
        try:
            part.Close(
                NXOpen.BasePart.CloseWholeTree.TrueValue,
                NXOpen.BasePart.CloseModified.CloseModified,
                responses,
            )
            closed += 1
        finally:
            responses.Dispose()
    return closed


def _op_import_machine_kit_readback(params):
    """Import an MTK into an isolated folder and read its model back through NXOpen."""
    _kit_root, package_path = _machine_kit_path(
        params.get("machine_kit_file_name"), must_exist=True
    )
    kit_identifier = _machine_kit_identifier(package_path)
    source_profile_name = str(params.get("source_profile") or "").strip()
    oem_collision_configuration = None
    if source_profile_name:
        source_profile = _machine_source_profile(source_profile_name)
        oem_collision_configuration = _machine_oem_collision_configuration(
            _machine_kinematic_plan(source_profile)
        )
    dry_run = bool(params.get("dry_run", True))
    keep_imported = bool(params.get("keep_imported", False))
    evaluate_static_collisions = bool(
        params.get("evaluate_static_collisions", False)
    )
    fingerprint = _machine_file_fingerprint(package_path)
    with zipfile.ZipFile(package_path, "r") as archive:
        names = archive.namelist()
    graphics_members = [
        name.replace("\\", "/")
        for name in names
        if "/graphics/" in name.replace("\\", "/").lower()
        and name.lower().endswith(".prt")
    ]
    if len(graphics_members) != 1:
        raise RuntimeError(
            "machine kit must contain exactly one graphics .prt payload"
        )
    expected_graphics_name = os.path.basename(graphics_members[0])
    result = {
        "ok": True,
        "dry_run": dry_run,
        "changed": False,
        "machine_kit_file_name": os.path.basename(package_path),
        "graphics_file_name": expected_graphics_name,
        "archive_size": fingerprint["size"],
        "archive_sha256": fingerprint["sha256"],
        "archive_member_count": len(names),
        "complete_archive": len(names) >= 10,
        "metadata_sanitized": True,
        "isolated_import": True,
        "global_machine_library_modified": False,
        "paths_redacted": True,
        "requires_explicit_confirmation": True,
        "production_certified": False,
    }
    if dry_run:
        result["note"] = (
            "No import was performed; set dry_run=false and provide the exact confirmation."
        )
        return result
    if params.get("confirmation") != _MACHINE_KIT_IMPORT_CONFIRMATION:
        raise PermissionError(
            "Isolated machine kit import requires confirmation=%s"
            % _MACHINE_KIT_IMPORT_CONFIRMATION
        )
    if (
        evaluate_static_collisions
        and params.get("static_collision_confirmation")
        != _MACHINE_STATIC_COLLISION_CONFIRMATION
    ):
        raise PermissionError(
            "Imported static collision evaluation requires static_collision_confirmation=%s"
            % _MACHINE_STATIC_COLLISION_CONFIRMATION
        )

    import_root = os.path.abspath(os.path.join(WORKSPACE, "machine_kit_imports"))
    if not os.path.isdir(import_root):
        os.makedirs(import_root)
    stale_import_parts_closed = _machine_close_stale_import_parts(import_root)
    staging = tempfile.mkdtemp(prefix=kit_identifier + "-", dir=import_root)
    before_databases = _machine_library_database_fingerprints()
    builder = None
    environment_names = (
        "UGII_CAM_LIBRARY_MACHINE_DATA_DIR",
        "UGII_CAM_LIBRARY_MACHINE_CONFIG_DIR",
        "UGII_CAM_LIBRARY_INSTALLED_MACHINES_DIR",
    )
    previous_environment = {
        name: os.environ.get(name) for name in environment_names
    }
    try:
        shadow_data = os.path.join(staging, "machine_data")
        shadow_machines = os.path.join(staging, "installed_machines")
        os.makedirs(shadow_data)
        os.makedirs(shadow_machines)
        base = str(os.environ.get("UGII_BASE_DIR", "") or "").strip()
        source_database = os.path.join(
            base, "MACH", "resource", "library", "machine", "ascii",
            "machine_database.dat",
        )
        if not os.path.isfile(source_database):
            raise RuntimeError("NX installed machine database is unavailable")
        shadow_database = os.path.join(shadow_data, "machine_database.dat")
        shutil.copy2(source_database, shadow_database)
        separator = os.sep
        os.environ["UGII_CAM_LIBRARY_MACHINE_DATA_DIR"] = shadow_data + separator
        os.environ["UGII_CAM_LIBRARY_MACHINE_CONFIG_DIR"] = shadow_data + separator
        os.environ["UGII_CAM_LIBRARY_INSTALLED_MACHINES_DIR"] = (
            shadow_machines + separator
        )
        work = _work_part()
        builder = work.KinematicConfigurator.ImportMachineKitBuilder(package_path)
        builder.OutputDirectory = shadow_machines
        builder.PrintReport = False
        if hasattr(builder, "Validate") and not bool(builder.Validate()):
            raise RuntimeError("NX rejected the isolated machine kit import")
        builder.Commit()
        # NX's MTK importer validates the archive and creates the database/config
        # entries, but it does not copy every payload file when the library roots
        # are temporarily redirected. Extract the already-validated payload into
        # the same shadow library so the imported graphics can be opened/read back.
        with zipfile.ZipFile(package_path, "r") as imported_archive:
            for item in imported_archive.infolist():
                member_name = item.filename.replace("\\", "/")
                if member_name == "kit_information.xml" or member_name.endswith("/"):
                    continue
                destination = os.path.abspath(
                    os.path.join(shadow_machines, *member_name.split("/"))
                )
                if os.path.commonpath([shadow_machines, destination]) != shadow_machines:
                    raise RuntimeError("machine kit archive member escapes import root")
                destination_folder = os.path.dirname(destination)
                if not os.path.isdir(destination_folder):
                    os.makedirs(destination_folder)
                with imported_archive.open(item, "r") as source_stream:
                    with io.open(destination, "wb") as target_stream:
                        shutil.copyfileobj(source_stream, target_stream)
        imported_files = []
        part_candidates = []
        for folder, _directories, files in os.walk(shadow_machines):
            for file_name in files:
                path = os.path.join(folder, file_name)
                relative = os.path.relpath(path, shadow_machines).replace("\\", "/")
                imported_files.append(
                    {"name": relative, "size": int(os.path.getsize(path))}
                )
                if file_name.lower().endswith(".prt"):
                    part_candidates.append(path)
        if not imported_files:
            raise RuntimeError("NX isolated machine kit import produced no files")
        preferred = [
            path for path in part_candidates
            if os.path.basename(path).lower() == expected_graphics_name.lower()
        ]
        if len(preferred) != 1:
            raise RuntimeError("imported machine kit graphics part was not found")
        readback = _machine_open_part_readback(
            preferred[0],
            evaluate_static_collisions=evaluate_static_collisions,
            oem_collision_configuration=oem_collision_configuration,
        )
        after_databases = _machine_library_database_fingerprints()
        database_unchanged = before_databases == after_databases
        if not database_unchanged:
            raise RuntimeError("isolated import unexpectedly changed an NX machine database")
        kinematics = readback["kinematics"]
        required_axes = {"X", "Y", "Z", "S", "B", "C"}
        axes = {str(item).upper() for item in kinematics.get("axis_names", [])}
        readback_passed = (
            readback["component_count"] >= 9
            and kinematics.get("junction_count", 0) >= 6
            and required_axes.issubset(axes)
            and bool(kinematics.get("channels"))
            and bool(kinematics.get("chains"))
        )
        static_evaluation = readback.get("static_collision_evaluation")
        static_collision_passed = (
            None if static_evaluation is None
            else static_evaluation["evaluated_pair_count"] > 0
            and static_evaluation["interfering_pair_count"] == 0
        )
        result.update(
            {
                "ok": readback_passed
                and (static_collision_passed is not False),
                "changed": True,
                "imported_file_count": len(imported_files),
                "imported_file_sample": imported_files[:20],
                "readback": readback,
                "readback_passed": readback_passed,
                "static_collision_evaluated": static_evaluation is not None,
                "static_collision_passed": static_collision_passed,
                "machine_database_fingerprints_checked": len(before_databases),
                "global_machine_database_unchanged": database_unchanged,
                "nx_import_builder_passed": True,
                "archive_content_extracted_for_readback": True,
                "shadow_machine_database_changed": (
                    _machine_file_fingerprint(shadow_database)["sha256"]
                    != _machine_file_fingerprint(source_database)["sha256"]
                ),
                "imported_files_kept": keep_imported,
                "stale_import_parts_closed": stale_import_parts_closed,
            }
        )
        return result
    finally:
        if builder is not None:
            builder.Destroy()
        for name, value in previous_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        if not keep_imported:
            shutil.rmtree(staging, ignore_errors=True)


def _machine_kinematic_record(work):
    record = {
        "name": None,
        "axis_names": [],
        "channels": [],
        "junction_count": 0,
        "chain_names": [],
        "chains": [],
        "axes": [],
        "available": False,
    }
    try:
        kinematic = work.KinematicConfigurator
        record.update(
            {
                "name": str(kinematic.GetName()),
                "axis_names": [str(item) for item in kinematic.GetAxisNames()],
                "channels": [str(item) for item in kinematic.GetChannels()],
                "junction_names": [
                    str(item) for item in kinematic.GetJunctionNames()
                ],
            }
        )
        record["junction_count"] = len(record["junction_names"])
        for axis_name in record["axis_names"]:
            axis_builder = None
            axis_record = {
                "name": axis_name,
                "limit_enabled": None,
                "lower_limit": None,
                "upper_limit": None,
                "lower_soft_limit": None,
                "upper_soft_limit": None,
                "initial_value": None,
                "axis_type": None,
                "limit_configuration_valid": False,
            }
            try:
                axis, parent, junction = kinematic.FindAxis(axis_name)
                axis_builder = kinematic.CreateAxisBuilder(parent, junction, axis)
                axis_record.update(
                    {
                        "limit_enabled": bool(axis_builder.Limit),
                        "lower_limit": float(axis_builder.LowerLimit),
                        "upper_limit": float(axis_builder.UpperLimit),
                        "lower_soft_limit": float(axis_builder.LowerSoftLimit),
                        "upper_soft_limit": float(axis_builder.UpperSoftLimit),
                        "initial_value": float(axis_builder.InitialValue),
                        "axis_type": int(
                            getattr(axis_builder.Type, "value", axis_builder.Type)
                        ),
                    }
                )
                axis_record["limit_configuration_valid"] = bool(
                    (not axis_record["limit_enabled"])
                    or axis_record["lower_limit"] < axis_record["upper_limit"]
                )
            except Exception as exc:
                axis_record["read_error"] = _safe_nx_error(exc)
            finally:
                if axis_builder is not None:
                    try:
                        axis_builder.Destroy()
                    except Exception:
                        pass
            record["axes"].append(axis_record)
        chain_configuration = None
        try:
            chain_configuration = kinematic.DefineKinematicChains()
            record["chains"] = [
                {
                    "name": str(getattr(item, "Name", "") or ""),
                    "device": str(getattr(item, "Device", "") or ""),
                    "setup": str(getattr(item, "Setup", "") or ""),
                    "reference_point_junction": str(
                        getattr(item, "ReferencePointJunction", "") or ""
                    ),
                    "axes": [
                        str(getattr(item, field, "") or "")
                        for field in ("X", "Y", "Z", "Rotary1", "Rotary2")
                    ],
                }
                for item in list(chain_configuration.List.GetContents())
            ]
            record["chain_names"] = [item["name"] for item in record["chains"]]
        finally:
            if chain_configuration is not None:
                try:
                    chain_configuration.Destroy()
                except Exception:
                    pass
        record["available"] = bool(record["axis_names"])
        record["limit_configuration_valid"] = bool(record["axes"]) and all(
            item["limit_configuration_valid"] for item in record["axes"]
        )
    except Exception as exc:
        record["read_error"] = _safe_nx_error(exc)
    return record


def _machine_collision_pair_records(work):
    """Read machine-simulation collision pairs without starting simulation."""
    kinematic = work.KinematicConfigurator
    cam = _cam_module()
    options = kinematic.CreateSimulationOptionsBuilder(
        cam.SimulationOptionsBuilder.DialogType.MachineToolBuilder
    )
    try:
        configuration = options.CollisionConfigurationBuilder
        pairs = []
        for index, pair in enumerate(configuration.List.GetContents()):
            pairs.append(
                {
                    "index": index,
                    "enabled": bool(pair.CollisionEnable),
                    "clearance": float(pair.CollisionClearance),
                    "first_filter": _cam_enum_name(pair.FirstObjectFilter),
                    "first_name": str(pair.FirstObjectName),
                    "second_filter": _cam_enum_name(pair.SecondObjectFilter),
                    "second_name": str(pair.SecondObjectName),
                }
            )
        return {
            "pair_count": len(pairs),
            "enabled_pair_count": sum(1 for item in pairs if item["enabled"]),
            "pairs": pairs,
            "builder_validate": bool(options.Validate()),
        }
    finally:
        options.Destroy()


def _machine_template_component_map():
    return {
        "Base": "MACHINE_BASE",
        "X": "X_SLIDE",
        "Y": "Y_SLIDE",
        "Z": "Z_SLIDE",
        "Spindle": "SPINDLE",
        "Tool": "POCKET_01",
        "B": "B_SLIDE",
        "C": "C_SLIDE",
        "Attach": "SETUP",
    }


def _machine_oem_collision_configuration(plan):
    aliases = _machine_template_component_map()
    pairs = []
    for index, pair in enumerate(plan.get("collision_pairs", [])):
        first = aliases.get(pair["first_component"])
        second = aliases.get(pair["second_component"])
        if first is None or second is None:
            raise RuntimeError("OEM collision component has no NX template mapping")
        pairs.append(
            {
                "index": index,
                "enabled": True,
                "clearance": float(pair.get("clearance", 0.0)),
                "first_filter": "Component",
                "first_name": first,
                "second_filter": "Component",
                "second_name": second,
                "include_first_subcomponents": bool(
                    pair.get("include_first_subcomponents", False)
                ),
                "include_second_subcomponents": bool(
                    pair.get("include_second_subcomponents", False)
                ),
                "source": "oem_machine_definition",
            }
        )
    return {
        "pair_count": len(pairs),
        "enabled_pair_count": len(pairs),
        "pairs": pairs,
        "builder_validate": None,
    }


def _machine_component_geometry(work):
    kinematic = work.KinematicConfigurator
    result = {}
    for component in list(kinematic.ComponentCollection):
        parent = component.GetParent()
        builder = kinematic.ComponentCollection.CreateComponentBuilder(
            parent, component
        )
        try:
            result[str(component.Name)] = list(builder.GetGeometries())
        finally:
            builder.Destroy()
    return result


def _machine_xyz_record(value):
    return [float(value.X), float(value.Y), float(value.Z)]


def _machine_enum_name(value, enum_type):
    for name in dir(enum_type):
        if name.startswith("_") or name == "ValueOf":
            continue
        try:
            candidate = getattr(enum_type, name)
            if candidate == value or str(candidate) == str(value):
                return name
        except Exception:
            pass
    return _cam_enum_name(value)


def _machine_geometry_diagnostics(objects):
    records = []
    bounded = []
    for obj in objects:
        bounds = _machine_object_bounds(obj)
        if bounds is not None:
            bounded.append(bounds)
        records.append(
            {
                "tag": int(obj.Tag),
                "name": str(getattr(obj, "Name", "") or ""),
                "type": type(obj).__name__,
                "bounds": bounds,
            }
        )
    aggregate = None
    if bounded:
        minimum = [min(item["min"][axis] for item in bounded) for axis in range(3)]
        maximum = [max(item["max"][axis] for item in bounded) for axis in range(3)]
        aggregate = {
            "min": minimum,
            "max": maximum,
            "size": [maximum[axis] - minimum[axis] for axis in range(3)],
        }
    return {
        "object_count": len(records),
        "bounded_object_count": len(bounded),
        "aggregate_bounds": aggregate,
        "objects": records,
    }


def _machine_clearance_interference_records(clearance_set):
    records = []
    object1 = None
    object2 = None
    while True:
        object1, object2 = clearance_set.GetNextInterference(object1, object2)
        if object1 is None or object2 is None:
            break
        data = clearance_set.GetInterferenceData(object1, object2)
        type_name = _machine_enum_name(data[0], clearance_set.InterferenceType)
        penetration_error = None
        if type_name == "Hard":
            try:
                clearance_set.CalculatePenetrationDepth([object1], [object2])
                data = clearance_set.GetInterferenceData(object1, object2)
            except Exception as exc:
                penetration_error = _safe_nx_error(exc)
        records.append(
            {
                "type": type_name,
                "object1": {
                    "tag": int(object1.Tag),
                    "name": str(getattr(object1, "Name", "") or ""),
                    "type": type(object1).__name__,
                },
                "object2": {
                    "tag": int(object2.Tag),
                    "name": str(getattr(object2, "Name", "") or ""),
                    "type": type(object2).__name__,
                },
                "new_interference": bool(data[1]),
                "interference_body_count": len(data[2]),
                "point1": _machine_xyz_record(data[3]),
                "point2": _machine_xyz_record(data[4]),
                "interference_number": int(data[6]),
                "configuration_index": int(data[7]),
                "penetration_depth_result": _machine_enum_name(
                    data[8], clearance_set.PenetrationDepthResult
                ),
                "penetration_depth": float(data[9]),
                "penetration_direction": _machine_xyz_record(data[10]),
                "penetration_min_point": _machine_xyz_record(data[11]),
                "penetration_max_point": _machine_xyz_record(data[12]),
                "penetration_error": penetration_error,
            }
        )
    return records


def _machine_evaluate_static_collision_pairs(work, collision):
    """Run transient lightweight clearance analyses for configured component pairs."""
    import NXOpen.Assemblies

    geometry = _machine_component_geometry(work)
    records = []
    for pair in collision["pairs"]:
        if not pair["enabled"]:
            continue
        if pair["first_filter"] != "Component" or pair["second_filter"] != "Component":
            records.append(
                {
                    "index": pair["index"],
                    "evaluated": False,
                    "reason": "non_component_filter_not_supported",
                }
            )
            continue
        first = geometry.get(pair["first_name"], [])
        second = geometry.get(pair["second_name"], [])
        if not first or not second:
            records.append(
                {
                    "index": pair["index"],
                    "first": pair["first_name"],
                    "second": pair["second_name"],
                    "evaluated": False,
                    "reason": "component_geometry_missing",
                    "first_geometry_count": len(first),
                    "second_geometry_count": len(second),
                }
            )
            continue
        builder = None
        clearance_set = None
        try:
            builder = work.AssemblyManager.CreateClearanceAnalysisBuilder(None)
            builder.ClearanceSetName = "NXMCP_STATIC_%02d" % pair["index"]
            builder.ClearanceBetween = (
                NXOpen.Assemblies.ClearanceAnalysisBuilder.ClearanceBetweenEntity.Bodies
            )
            builder.TotalCollectionCount = (
                NXOpen.Assemblies.ClearanceAnalysisBuilder.NumberOfCollections.Two
            )
            builder.CollectionOneRange = (
                NXOpen.Assemblies.ClearanceAnalysisBuilder.CollectionRange.SelectedObjects
            )
            builder.CollectionTwoRange = (
                NXOpen.Assemblies.ClearanceAnalysisBuilder.CollectionRange.SelectedObjects
            )
            builder.CalculationMethod = (
                NXOpen.Assemblies.ClearanceAnalysisBuilder.CalculationMethodType.Lightweight
            )
            builder.CollectionOneObjects.SetArray(first)
            builder.CollectionTwoObjects.SetArray(second)
            clearance = float(pair.get("clearance", 0.0) or 0.0)
            if clearance > 0.0:
                expression = builder.CreateClearanceZoneExpression(
                    "%.9g" % clearance
                )
                builder.SetDefaultClearanceZone(expression)
            if not bool(builder.Validate()):
                raise RuntimeError("NX rejected transient clearance analysis")
            clearance_set = builder.Commit()
            builder.Destroy()
            builder = None
            clearance_set.PerformAnalysis(
                NXOpen.Assemblies.ClearanceSet.ReanalyzeOutOfDateExcludedPairs.FalseValue
            )
            summary = clearance_set.GetResults()
            interference_count = int(clearance_set.GetNumberOfInterferences())
            interferences = _machine_clearance_interference_records(clearance_set)
            records.append(
                {
                    "index": pair["index"],
                    "first": pair["first_name"],
                    "second": pair["second_name"],
                    "evaluated": True,
                    "interference_count": interference_count,
                    "hard": int(summary.NumHard),
                    "soft": int(summary.NumSoft),
                    "touching": int(summary.NumTouching),
                    "configured_clearance": clearance,
                    "clearance_zone_applied": clearance > 0.0,
                    "first_geometry": _machine_geometry_diagnostics(first),
                    "second_geometry": _machine_geometry_diagnostics(second),
                    "interferences": interferences,
                }
            )
        except Exception as exc:
            records.append(
                {
                    "index": pair["index"],
                    "first": pair["first_name"],
                    "second": pair["second_name"],
                    "evaluated": False,
                    "error": _safe_nx_error(exc),
                }
            )
        finally:
            if builder is not None:
                try:
                    builder.Destroy()
                except Exception:
                    pass
            if clearance_set is not None:
                try:
                    clearance_set.Delete()
                except Exception:
                    pass
    evaluated = [item for item in records if item.get("evaluated")]
    return {
        "pair_results": records,
        "evaluated_pair_count": len(evaluated),
        "unevaluated_pair_count": len(records) - len(evaluated),
        "interfering_pair_count": sum(
            1 for item in evaluated if item.get("interference_count", 0) > 0
        ),
        "total_interference_count": sum(
            item.get("interference_count", 0) for item in evaluated
        ),
    }


def _op_validate_machine_static_collisions(params):
    """Validate initial-position collision configuration without any axis motion."""
    profile = _machine_source_profile(params.get("source_profile"))
    plan = _machine_kinematic_plan(profile)
    _root, target = _machine_build_part_path(params.get("workspace_file_name"))
    work = _machine_require_active_workspace(target)
    manifest = _machine_read_manifest(target)
    if manifest["source_profile"] != profile["name"]:
        raise ValueError("workspace source profile does not match the request")
    structural = _op_validate_machine_kinematics(
        {
            "source_profile": profile["name"],
            "workspace_file_name": os.path.basename(target),
            "require_geometry": True,
        }
    )
    collision = _machine_collision_pair_records(work)
    oem_collision = _machine_oem_collision_configuration(plan)
    evaluation_collision = (
        collision if collision["pair_count"] else oem_collision
    )
    blockers = list(structural.get("blockers", []))
    if evaluation_collision["pair_count"] == 0:
        blockers.append("collision_pairs_missing")
    if evaluation_collision["enabled_pair_count"] == 0:
        blockers.append("no_enabled_collision_pairs")
    evaluate_geometry = bool(params.get("evaluate_geometry", False))
    evaluation = None
    if evaluate_geometry:
        if params.get("confirmation") != _MACHINE_STATIC_COLLISION_CONFIRMATION:
            raise PermissionError(
                "Static collision evaluation requires confirmation=%s"
                % _MACHINE_STATIC_COLLISION_CONFIRMATION
            )
        session = NXOpen.Session.GetSession()
        mark_name = "NX MCP Static Collision Evaluation"
        mark = session.SetUndoMark(session.MarkVisibility.Invisible, mark_name)
        try:
            evaluation = _machine_evaluate_static_collision_pairs(
                work, evaluation_collision
            )
        finally:
            session.UndoToMark(mark, mark_name)
        if evaluation["evaluated_pair_count"] == 0:
            blockers.append("static_collision_geometry_evaluation_failed")
        if evaluation["interfering_pair_count"]:
            blockers.append("initial_position_interference_detected")
    geometry = _machine_component_geometry(work)
    machining_context = {
        "tool_mount_component": "POCKET_01",
        "tool_mount_geometry_count": len(geometry.get("POCKET_01", [])),
        "setup_component": "SETUP",
        "setup_geometry_count": len(geometry.get("SETUP", [])),
        "fixture_geometry_count": len(geometry.get("FIXTURE", [])),
        "blank_geometry_count": len(geometry.get("BLANK", [])),
        "part_geometry_count": len(geometry.get("PART", [])),
    }
    machining_context["cam_tool_geometry_bound"] = (
        machining_context["tool_mount_geometry_count"] > 0
    )
    machining_context["cam_workpiece_geometry_bound"] = any(
        machining_context[name] > 0
        for name in (
            "fixture_geometry_count",
            "blank_geometry_count",
            "part_geometry_count",
        )
    )
    remaining_validation = []
    if evaluation is None:
        remaining_validation.append(
            "initial_position_geometry_interference_evaluation"
        )
    if not (
        machining_context["cam_tool_geometry_bound"]
        and machining_context["cam_workpiece_geometry_bound"]
    ):
        remaining_validation.append("cam_tool_and_workpiece_geometry_binding")
    return {
        "ok": not blockers,
        "part": os.path.basename(target),
        "source_profile": profile["public"],
        "structural_validation_passed": bool(
            structural.get("structural_validation_passed")
        ),
        "collision_configuration": collision,
        "oem_collision_configuration": oem_collision,
        "static_evaluation_pair_source": (
            "persisted_machine_collision_pairs"
            if collision["pair_count"]
            else "oem_machine_definition"
        ),
        "collision_pair_configuration_passed": not any(
            item in blockers
            for item in ("collision_pairs_missing", "no_enabled_collision_pairs")
        ),
        "initial_axis_motion_performed": False,
        "simulation_started": False,
        "static_collision_geometry_evaluated": evaluation is not None,
        "static_collision_evaluation": evaluation,
        "machining_context": machining_context,
        "blockers": blockers,
        "remaining_validation": remaining_validation,
        "paths_redacted": True,
        "production_certified": False,
    }


def _op_debug_machine_model_state(params):
    """Temporary read-only diagnostics for the live machine model."""
    work = _work_part()
    kinematic = work.KinematicConfigurator

    def point_record(point):
        return [float(point.X), float(point.Y), float(point.Z)]

    def matrix_record(matrix):
        return [
            float(matrix.Xx), float(matrix.Xy), float(matrix.Xz),
            float(matrix.Yx), float(matrix.Yy), float(matrix.Yz),
            float(matrix.Zx), float(matrix.Zy), float(matrix.Zz),
        ]

    components = []
    junction_tags = {}
    for component in list(kinematic.ComponentCollection):
        parent = component.GetParent()
        component_junctions = []
        for junction in list(component.GetJunctions()):
            full_name = "%s@%s" % (str(component.Name), str(junction.Name))
            junction_tags.setdefault(int(junction.Tag), []).append(full_name)
            builder = kinematic.CreateJunctionBuilder(component, junction)
            try:
                csys = builder.Csys
                component_junctions.append(
                    {
                        "full_name": full_name,
                        "name": str(builder.Name),
                        "tag": int(junction.Tag),
                        "classification": str(builder.Classification),
                        "origin": point_record(csys.Origin),
                        "matrix": matrix_record(csys.Orientation.Element),
                        "validate": bool(builder.Validate()),
                    }
                )
            finally:
                builder.Destroy()
        component_builder = kinematic.ComponentCollection.CreateComponentBuilder(
            parent, component
        )
        try:
            geometry = list(component_builder.GetGeometries())
            builder_junctions = int(component_builder.JunctionList.Length)
        finally:
            component_builder.Destroy()
        components.append(
            {
                "name": str(component.Name),
                "tag": int(component.Tag),
                "parent": str(parent.Name) if parent is not None else None,
                "geometry_count": len(geometry),
                "geometry_types": sorted(
                    set(type(item).__name__ for item in geometry)
                ),
                "junction_count": len(component_junctions),
                "builder_junction_count": builder_junctions,
                "junctions": component_junctions,
            }
        )
    return {
        "ok": True,
        "work_name": str(work.Name),
        "work_full_path_present": bool(str(work.FullPath or "")),
        "component_count": len(components),
        "components": components,
        "global_junction_count": len(list(kinematic.GetJunctionNames())),
        "unique_junction_tag_count": len(junction_tags),
        "duplicate_junction_tags": {
            str(tag): names for tag, names in junction_tags.items() if len(names) > 1
        },
    }


def _op_debug_probe_junction_retarget(params):
    """Temporarily retarget one existing junction, read it back, then undo."""
    if params.get("confirmation") != "PROBE_MACHINE_JUNCTION_RETARGET":
        raise PermissionError(
            "Junction retarget probe requires confirmation=PROBE_MACHINE_JUNCTION_RETARGET"
        )
    work = _work_part()
    session = NXOpen.Session.GetSession()
    kinematic = work.KinematicConfigurator
    full_name = _cam_safe_name("junction_name", params.get("junction_name"))
    origin = _vector3("origin", params.get("origin"))
    owner_name = full_name.split("@", 1)[0]
    owner = next(
        (
            item for item in list(kinematic.ComponentCollection)
            if str(item.Name) == owner_name
        ),
        None,
    )
    if owner is None:
        raise ValueError("junction owner was not found")
    junction = kinematic.FindJunction(full_name)
    before_builder = kinematic.CreateJunctionBuilder(owner, junction)
    try:
        original_name = str(before_builder.Name)
        original_classification = before_builder.Classification
        original_csys = before_builder.Csys
        before = {
            "name": original_name,
            "tag": int(junction.Tag),
            "origin": [
                float(original_csys.Origin.X),
                float(original_csys.Origin.Y),
                float(original_csys.Origin.Z),
            ],
        }
        orientation = original_csys.Orientation.Element
    finally:
        before_builder.Destroy()
    mark_name = "NX MCP Junction Retarget Probe"
    mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Invisible, mark_name)
    created_csys = None
    edit_builder = None
    after = None
    try:
        created_csys = work.CoordinateSystems.CreateCoordinateSystem(
            NXOpen.Point3d(*origin),
            NXOpen.Vector3d(
                float(orientation.Xx), float(orientation.Xy), float(orientation.Xz)
            ),
            NXOpen.Vector3d(
                float(orientation.Yx), float(orientation.Yy), float(orientation.Yz)
            ),
        )
        created_csys.SetName("NXMCP_JUNCTION_RETARGET_PROBE")
        edit_builder = kinematic.CreateJunctionBuilder(owner, junction)
        edit_builder.Name = original_name
        edit_builder.Classification = original_classification
        edit_builder.Csys = created_csys
        if not bool(edit_builder.Validate()):
            raise RuntimeError("NX rejected junction retarget probe")
        committed = edit_builder.Commit()
        update_errors = int(session.UpdateManager.DoUpdate(mark))
        current_junction = kinematic.FindJunction(full_name)
        after_builder = kinematic.CreateJunctionBuilder(owner, current_junction)
        try:
            current_csys = after_builder.Csys
            after = {
                "name": str(after_builder.Name),
                "tag": int(current_junction.Tag),
                "commit_tag": int(getattr(committed, "Tag", 0) or 0),
                "origin": [
                    float(current_csys.Origin.X),
                    float(current_csys.Origin.Y),
                    float(current_csys.Origin.Z),
                ],
                "update_errors": update_errors,
            }
        finally:
            after_builder.Destroy()
    finally:
        if edit_builder is not None:
            edit_builder.Destroy()
        session.UndoToMark(mark, mark_name)
    restored_junction = kinematic.FindJunction(full_name)
    restored_builder = kinematic.CreateJunctionBuilder(owner, restored_junction)
    try:
        restored_csys = restored_builder.Csys
        restored = {
            "name": str(restored_builder.Name),
            "tag": int(restored_junction.Tag),
            "origin": [
                float(restored_csys.Origin.X),
                float(restored_csys.Origin.Y),
                float(restored_csys.Origin.Z),
            ],
        }
    finally:
        restored_builder.Destroy()
    return {
        "ok": True,
        "junction": full_name,
        "before": before,
        "after": after,
        "restored": restored,
        "applied_then_undone": True,
    }


def _op_debug_probe_machine_kit_builder(params):
    """Temporarily exercise MachineKitBuilder with isolated output layouts."""
    if params.get("confirmation") != "PROBE_MACHINE_KIT_BUILDER":
        raise PermissionError(
            "MachineKitBuilder probe requires confirmation=PROBE_MACHINE_KIT_BUILDER"
        )
    work = _work_part()
    kinematic = work.KinematicConfigurator
    staging = tempfile.mkdtemp(
        prefix=".nxmcp-mkb-probe-", dir=os.path.dirname(str(work.FullPath))
    )
    scenarios = []
    try:
        layouts = [
            ("parent_directory", staging, "nx_mcp_probe_parent"),
            (
                "existing_machine_directory",
                os.path.join(staging, "existing_machine_directory"),
                "nx_mcp_probe_existing",
            ),
            (
                "nonexistent_machine_directory",
                os.path.join(staging, "nonexistent_machine_directory"),
                "nx_mcp_probe_nonexistent",
            ),
        ]
        if bool(params.get("only_nonexistent", False)):
            layouts = [layouts[2]]
        elif bool(params.get("only_parent", False)):
            layouts = [layouts[0]]
        for layout_name, output_directory, _kit_name in layouts:
            if layout_name == "existing_machine_directory":
                os.makedirs(output_directory)
        for layout_name, output_directory, kit_name in layouts:
            builder = kinematic.CreateMachineKitBuilder()
            try:
                builder.Name = kit_name
                builder.OutputDirectory = output_directory
                valid = bool(builder.Validate())
                error = None
                committed = False
                if valid:
                    try:
                        builder.Commit()
                        committed = True
                    except Exception as exc:
                        error = _safe_nx_error(exc)
                        error["detail"] = str(exc).strip()[:240]
            finally:
                builder.Destroy()
            files = []
            directories = []
            for root, _dirs, names in os.walk(staging):
                for directory in _dirs:
                    directories.append(
                        os.path.relpath(os.path.join(root, directory), staging)
                    )
                for name in names:
                    path = os.path.join(root, name)
                    files.append(
                        {
                            "path": os.path.relpath(path, staging),
                            "size": int(os.path.getsize(path)),
                        }
                    )
            scenarios.append(
                {
                    "layout": layout_name,
                    "output_directory_exists_before": layout_name
                    != "nonexistent_machine_directory",
                    "validate": valid,
                    "committed": committed,
                    "error": error,
                    "files": files,
                    "directories": sorted(directories),
                }
            )
            if committed:
                break
        return {
            "ok": True,
            "part": str(work.Name),
            "scenarios": scenarios,
            "staging_removed": True,
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _op_debug_export_reference_machine_kit(params):
    """Export an installed NX reference kit to a temporary archive for inspection."""
    if params.get("confirmation") != "EXPORT_REFERENCE_MACHINE_KIT":
        raise PermissionError(
            "Reference kit export requires confirmation=EXPORT_REFERENCE_MACHINE_KIT"
        )
    work = _work_part()
    kinematic = work.KinematicConfigurator
    staging = tempfile.mkdtemp(
        prefix=".nxmcp-reference-mtk-", dir=os.path.dirname(str(work.FullPath))
    )
    builder = None
    try:
        builder = kinematic.ExportMachineKitBuilder(
            str(params.get("machine_libref", "sim06_mill_5ax_tnc"))
        )
        initial_paths = [str(item) for item in builder.GetAllKitPaths()]
        builder.KitName = "nx_mcp_reference_kit"
        builder.OutputDirectory = staging
        builder.PrintReport = False
        valid = bool(builder.Validate())
        if not valid:
            raise RuntimeError("NX rejected the reference machine kit export")
        builder.Commit()
        candidates = []
        for root, _dirs, files in os.walk(staging):
            for file_name in files:
                if file_name.lower().endswith(".mtk"):
                    candidates.append(os.path.join(root, file_name))
        if len(candidates) != 1:
            raise RuntimeError(
                "NX reference kit export did not create exactly one MTK archive"
            )
        package = candidates[0]
        with zipfile.ZipFile(package, "r") as archive:
            kit_information = archive.read("kit_information.xml").decode(
                "utf-8", errors="replace"
            )
            members = [
                {"name": item.filename, "size": int(item.file_size)}
                for item in archive.infolist()
            ]
        import_probe = None
        if bool(params.get("probe_import", False)):
            import_directory = os.path.join(staging, "isolated_import")
            os.makedirs(import_directory)
            import_builder = kinematic.ImportMachineKitBuilder(package)
            try:
                import_builder.OutputDirectory = import_directory
                import_builder.PrintReport = False
                import_valid = bool(import_builder.Validate())
                if import_valid:
                    import_builder.Commit()
                imported = []
                for folder, _directories, files in os.walk(import_directory):
                    for file_name in files:
                        imported.append(
                            os.path.relpath(
                                os.path.join(folder, file_name), import_directory
                            ).replace("\\", "/")
                        )
                import_probe = {
                    "validate": import_valid,
                    "imported_file_count": len(imported),
                    "imported_file_sample": imported[:20],
                }
            finally:
                import_builder.Destroy()
        return {
            "ok": True,
            "initial_kit_paths": initial_paths,
            "archive_size": int(os.path.getsize(package)),
            "kit_information": kit_information,
            "archive_members": members,
            "import_probe": import_probe,
            "staging_removed": True,
        }
    finally:
        if builder is not None:
            builder.Destroy()
        shutil.rmtree(staging, ignore_errors=True)


def _cam_tool_section_records(section_builder):
    records = []
    count = int(section_builder.NumberOfSections)
    for index in range(count):
        section = section_builder.GetSection(index)
        values = list(section_builder.GetAllParameters(section))
        while len(values) < 5:
            values.append(None)
        records.append(
            {
                "index": index,
                "lower_diameter": float(values[0]) if values[0] is not None else None,
                "length": float(values[1]) if values[1] is not None else None,
                "taper_angle": float(values[2]) if values[2] is not None else None,
                "upper_diameter": float(values[3]) if values[3] is not None else None,
                "corner_radius": float(values[4]) if values[4] is not None else None,
            }
        )
    return records


def _cam_tool_profile_record(setup, tool):
    record = {
        "name": getattr(tool, "Name", None),
        "tag": int(tool.Tag),
        "readable": False,
        "cutter_geometry_ready": False,
        "shank_geometry_ready": False,
        "holder_geometry_ready": False,
        "holder_sections": [],
        "shank_sections": [],
    }
    builder = None
    try:
        builder = setup.CAMGroupCollection.CreateMillToolBuilder(tool)
        diameter = float(builder.TlDiameterBuilder.Value)
        flute_length = float(builder.TlFluteLnBuilder.Value)
        overall_length = float(builder.TlHeightBuilder.Value)
        shank_diameter = float(builder.TlShankDiaBuilder.Value)
        flute_count = int(builder.TlNumFlutesBuilder.Value)
        tool_number = int(builder.TlNumberBuilder.Value)
        length_offset_register = int(builder.TlAdjRegBuilder.Value)
        holder_sections = _cam_tool_section_records(builder.HolderSectionBuilder)
        shank_sections = _cam_tool_section_records(builder.ShankSectionBuilder)
        record.update(
            {
                "readable": True,
                "diameter": diameter,
                "flute_length": flute_length,
                "overall_length": overall_length,
                "shank_diameter": shank_diameter,
                "flute_count": flute_count,
                "tool_number": tool_number,
                "length_offset_register": length_offset_register,
                "holder_sections": holder_sections,
                "shank_sections": shank_sections,
                "cutter_geometry_ready": bool(
                    diameter > 0.0
                    and flute_length > 0.0
                    and overall_length >= flute_length
                ),
                "shank_geometry_ready": bool(shank_diameter > 0.0 or shank_sections),
                "holder_geometry_ready": bool(holder_sections),
            }
        )
    except Exception as exc:
        record["read_error"] = _safe_nx_error(exc)
    finally:
        if builder is not None:
            builder.Destroy()
    return record


def _cam_blank_definition_record(cam, blank):
    value = int(getattr(blank.BlankDefinitionType, "value", blank.BlankDefinitionType))
    name = {
        0: "from_geometry",
        1: "offset_from_part",
        2: "auto_block",
        3: "ipw",
        4: "bounding_cylinder",
        5: "part_outline",
        6: "part_convex_hull",
    }.get(value, _cam_enum_name(blank.BlankDefinitionType))
    geometry = _cam_geometry_record(blank)
    item_count = sum(item["item_count"] for item in geometry["sets"])
    from_geometry = cam.GeometryGroup.BlankDefinitionTypes.FromGeometry
    from_geometry_value = int(getattr(from_geometry, "value", from_geometry))
    return {
        "definition": name,
        "definition_value": value,
        "geometry": geometry,
        "ready": bool(item_count > 0 if value == from_geometry_value else True),
    }


def _cam_workpiece_profile_record(setup, geometry, cam):
    record = {
        "name": getattr(geometry, "Name", None),
        "tag": int(geometry.Tag),
        "readable": False,
        "part_geometry": {"set_count": 0, "sets": []},
        "blank": {"definition": None, "geometry": {"set_count": 0, "sets": []}, "ready": False},
        "fixture_geometry": {"set_count": 0, "sets": []},
        "part_geometry_ready": False,
        "blank_geometry_ready": False,
        "fixture_geometry_ready": False,
    }
    builder = None
    try:
        builder = setup.CAMGroupCollection.CreateMillGeomBuilder(geometry)
        part_geometry = _cam_geometry_record(builder.PartGeometry)
        blank = _cam_blank_definition_record(cam, builder.BlankGeometry)
        fixture_geometry = _cam_geometry_record(builder.CheckGeometry)
        part_item_count = sum(
            item["item_count"] for item in part_geometry["sets"]
        )
        fixture_item_count = sum(
            item["item_count"] for item in fixture_geometry["sets"]
        )
        record.update(
            {
                "readable": True,
                "part_geometry": part_geometry,
                "blank": blank,
                "fixture_geometry": fixture_geometry,
                "part_geometry_ready": part_item_count > 0,
                "blank_geometry_ready": bool(blank["ready"]),
                "fixture_geometry_ready": fixture_item_count > 0,
            }
        )
    except Exception as exc:
        record["read_error"] = _safe_nx_error(exc)
    finally:
        if builder is not None:
            builder.Destroy()
    return record


def _cam_simulation_context_record(setup, operations):
    cam = _cam_module()
    tools = {}
    workpieces = {}
    for operation in operations:
        tool = operation.GetParent(cam.CAMSetup.View.MachineTool)
        geometry = operation.GetParent(cam.CAMSetup.View.Geometry)
        tools.setdefault(int(tool.Tag), tool)
        candidate = geometry
        visited = set()
        selected = geometry
        while candidate is not None and int(candidate.Tag) not in visited:
            visited.add(int(candidate.Tag))
            probe = _cam_workpiece_profile_record(setup, candidate, cam)
            selected = candidate
            if probe.get("readable"):
                break
            try:
                candidate = candidate.GetParent(cam.CAMSetup.View.Geometry)
            except Exception:
                try:
                    candidate = candidate.GetParent()
                except Exception:
                    candidate = None
        workpieces.setdefault(int(selected.Tag), selected)
    return {
        "tools": [_cam_tool_profile_record(setup, item) for item in tools.values()],
        "workpieces": [
            _cam_workpiece_profile_record(setup, item, cam)
            for item in workpieces.values()
        ],
    }


def _machine_simulation_readiness(params):
    setup = _cam_setup()
    work = _work_part()
    program_name = params.get("program_name", "MCP_PROGRAM")
    operation_names = params.get("operation_names")
    _driver_objects, operations, selection = _cam_simulation_selection(
        setup, operation_names, program_name
    )
    operation_records = [_cam_object_record(setup, item) for item in operations]
    simulation_context = _cam_simulation_context_record(setup, operations)
    missing_paths = [
        item["name"] for item in operation_records if not item.get("path_exists", False)
    ]
    try:
        machine_libref = str(setup.GetMachineLibref()).strip()
    except Exception as exc:
        machine_libref = ""
        machine_libref_error = _safe_nx_error(exc)
    else:
        machine_libref_error = None
    machine_root = setup.GetRoot(_cam_module().CAMSetup.View.MachineTool)
    kinematics = _machine_kinematic_record(work)
    required_axes = params.get("required_axes")
    if required_axes is None:
        required_axes = []
    if not isinstance(required_axes, list):
        raise ValueError("required_axes must be a list or null")
    required_axes = [
        _cam_safe_name("required_axis", str(item)).upper() for item in required_axes
    ]
    missing_axes = [
        axis for axis in required_axes
        if not _machine_axis_matches(kinematics["axis_names"], axis)
    ]
    require_axis_limits = bool(params.get("require_axis_limits", True))
    require_tool_geometry = bool(params.get("require_tool_geometry", True))
    require_shank_geometry = bool(params.get("require_shank_geometry", False))
    require_holder_geometry = bool(params.get("require_holder_geometry", False))
    require_workpiece_geometry = bool(params.get("require_workpiece_geometry", True))
    require_fixture_geometry = bool(params.get("require_fixture_geometry", False))
    required_axis_limit_records = [
        item
        for item in kinematics.get("axes", [])
        if any(_machine_axis_matches([item["name"]], axis) for axis in required_axes)
    ]
    invalid_required_axis_limits = [
        item["name"]
        for item in required_axis_limit_records
        if not item.get("limit_configuration_valid", False)
    ]
    tools = simulation_context["tools"]
    workpieces = simulation_context["workpieces"]
    blockers = []
    warnings = []
    if not machine_libref:
        blockers.append("no_machine_library_binding")
    if not kinematics["axis_names"]:
        blockers.append("no_kinematic_axes")
    if not kinematics["channels"]:
        blockers.append("no_kinematic_channel")
    if missing_axes:
        blockers.append("required_axes_missing")
    if require_axis_limits and invalid_required_axis_limits:
        blockers.append("required_axis_limits_invalid")
    if missing_paths:
        blockers.append("toolpaths_missing")
    if require_tool_geometry and any(
        not item.get("cutter_geometry_ready", False) for item in tools
    ):
        blockers.append("tool_parameter_geometry_missing")
    if require_shank_geometry and any(
        not item.get("shank_geometry_ready", False) for item in tools
    ):
        blockers.append("tool_shank_geometry_missing")
    if require_holder_geometry and any(
        not item.get("holder_geometry_ready", False) for item in tools
    ):
        blockers.append("tool_holder_geometry_missing")
    if require_workpiece_geometry and any(
        not item.get("part_geometry_ready", False) for item in workpieces
    ):
        blockers.append("part_geometry_missing")
    if require_workpiece_geometry and any(
        not item.get("blank_geometry_ready", False) for item in workpieces
    ):
        blockers.append("blank_geometry_missing")
    if require_fixture_geometry and any(
        not item.get("fixture_geometry_ready", False) for item in workpieces
    ):
        blockers.append("fixture_geometry_missing")
    if getattr(machine_root, "Name", "") == "GENERIC_MACHINE":
        warnings.append("machine_tool_root_is_generic")
    if len(kinematics["axis_names"]) < 5:
        warnings.append("fewer_than_five_kinematic_axes")
    if not any(_machine_axis_matches(kinematics["axis_names"], axis) for axis in ("A", "B", "C")):
        warnings.append("no_rotary_axis_detected")
    if any(not item.get("holder_geometry_ready", False) for item in tools):
        warnings.append("tool_holder_geometry_not_defined")
    if any(not item.get("fixture_geometry_ready", False) for item in workpieces):
        warnings.append("fixture_geometry_not_defined")
    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))
    result = {
        "ok": True,
        "part": work.Leaf,
        "selection": selection,
        "operations": operation_records,
        "machine": {
            "library_bound": bool(machine_libref),
            "libref": machine_libref or None,
            "machine_tool_root": getattr(machine_root, "Name", None),
            "kinematics": kinematics,
            "required_axes": required_axes,
            "missing_required_axes": missing_axes,
            "invalid_required_axis_limits": invalid_required_axis_limits,
        },
        "simulation_context": simulation_context,
        "requirements": {
            "axis_limits": require_axis_limits,
            "tool_geometry": require_tool_geometry,
            "shank_geometry": require_shank_geometry,
            "holder_geometry": require_holder_geometry,
            "workpiece_geometry": require_workpiece_geometry,
            "fixture_geometry": require_fixture_geometry,
        },
        "toolpath_simulation_ready": not missing_paths,
        "machine_simulation_ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "safety": {
            "collision_stop_required": True,
            "production_nc_certified": False,
            "machine_library_paths_redacted": True,
        },
    }
    if machine_libref_error is not None:
        result["machine"]["libref_read_error"] = machine_libref_error
    machine_query = params.get("machine_query")
    if machine_query is not None:
        try:
            result["machine_library"] = _machine_library_catalog(
                work.KinematicConfigurator,
                machine_query,
                params.get("max_candidates", 20),
            )
        except Exception as exc:
            result["machine_library"] = {
                "available": False,
                "error": _safe_nx_error(exc),
                "paths_redacted": True,
            }
    return result


def _op_inspect_machine_simulation_readiness(params):
    return _machine_simulation_readiness(params)


def _op_cam_capabilities(params):
    cam = _cam_module()
    session = NXOpen.Session.GetSession()
    initialized = bool(session.IsCamSessionInitialized())
    setup = _cam_setup(required=False)
    template_types = []
    operation_templates = {}
    if initialized:
        template_types = list(session.CAMSession.GetTemplateTypes())
        requested = params.get("template_type")
        if requested:
            requested = _cam_safe_name("template_type", requested)
            if requested not in template_types:
                raise ValueError("template_type is not available in this NX session")
            operation_templates[requested] = list(
                session.CAMSession.GetTemplateSubtypes(
                    requested, cam.CAMSession.ObjectSubtype.Operation
                )
            )
    return {
        "ok": True,
        "part": getattr(session.Parts.Work, "Leaf", None),
        "cam_session_initialized": initialized,
        "cam_setup_exists": setup is not None,
        "template_types": template_types,
        "operation_templates": operation_templates,
        "supported_tools": [
            "initialize_cam_setup",
            "create_cam_milling_context",
            "inspect_cam_setup",
            "define_cam_mcs",
            "define_cam_workpiece",
            "create_cam_mill_tool",
            "create_cam_operation",
            "set_cam_operation_geometry",
            "configure_cam_milling_operation",
            "inspect_cam_operation_details",
            "generate_cam_toolpath",
            "inspect_cam_operations",
            "inspect_machine_simulation_readiness",
            "inspect_machine_source_profile",
            "inspect_machine_kinematic_plan",
            "create_machine_build_workspace",
            "create_smart_machine_kit_workspace",
            "activate_machine_build_workspace",
            "restore_machine_build_recovery_part",
            "import_machine_component_geometry",
            "build_machine_kinematics_from_profile",
            "validate_machine_kinematics",
            "bind_machine_tool_from_library",
            "start_machine_simulation_with_collision_stop",
            "export_cam_clsf",
            "postprocess_cam_program_locked",
        ],
        "machine_profile": "mikron_mill_e_500u_tnc640_public",
        "postprocess_enabled": os.environ.get(
            "NX_MCP_ENABLE_POSTPROCESS", "0"
        ).strip().lower() in ("1", "true", "yes", "on"),
        "safety": {
            "vendor_assets_embedded": False,
            "controller_backup_accessed": False,
            "production_nc_certified": False,
            "postprocess_locked_by_default": True,
        },
    }


def _op_initialize_cam_setup(params):
    cam = _cam_module()
    session = NXOpen.Session.GetSession()
    work = _work_part()
    template_name = _cam_safe_name(
        "template_name", params.get("template_name", "mill_planar")
    )
    if not session.IsCamSessionInitialized():
        session.CreateCamSession()
    setup = _cam_setup(required=False)
    created = False
    if setup is None:
        setup = work.CreateCamSetup(template_name)
        created = True
    if bool(params.get("switch_to_manufacturing", False)):
        session.ApplicationSwitchImmediate("UG_APP_MANUFACTURING")
    roots = {}
    for name, view in (
        ("program", cam.CAMSetup.View.ProgramOrder),
        ("method", cam.CAMSetup.View.MachineMethod),
        ("geometry", cam.CAMSetup.View.Geometry),
        ("tool", cam.CAMSetup.View.MachineTool),
    ):
        root = setup.GetRoot(view)
        roots[name] = _cam_object_record(setup, root, True, max_depth=2)
    return {
        "ok": True,
        "part": work.Leaf,
        "created": created,
        "template_name": template_name,
        "roots": roots,
    }


def _cam_find_group(setup, name):
    try:
        return setup.CAMGroupCollection.FindObject(name)
    except Exception:
        return None


def _op_create_cam_milling_context(params):
    cam = _cam_module()
    setup = _cam_setup()
    collection = setup.CAMGroupCollection
    use_name = cam.NCGroupCollection.UseDefaultName.FalseValue
    names = {
        "program": _cam_safe_name(
            "program_name", params.get("program_name", "MCP_PROGRAM")
        ),
        "method": _cam_safe_name(
            "method_name", params.get("method_name", "MCP_METHOD")
        ),
        "mcs": _cam_safe_name("mcs_name", params.get("mcs_name", "MCP_MCS")),
        "workpiece": _cam_safe_name(
            "workpiece_name", params.get("workpiece_name", "MCP_WORKPIECE")
        ),
    }
    created = {}

    program = _cam_find_group(setup, names["program"])
    if program is None:
        program = collection.CreateProgram(
            setup.GetRoot(cam.CAMSetup.View.ProgramOrder),
            "mill_planar",
            "PROGRAM",
            use_name,
            names["program"],
        )
        created["program"] = True
    else:
        created["program"] = False

    method = _cam_find_group(setup, names["method"])
    if method is None:
        method = collection.CreateMethod(
            setup.GetRoot(cam.CAMSetup.View.MachineMethod),
            "mill_planar",
            "MILL_METHOD",
            use_name,
            names["method"],
        )
        created["method"] = True
    else:
        created["method"] = False

    mcs = _cam_find_group(setup, names["mcs"])
    if mcs is None:
        mcs = collection.CreateGeometry(
            setup.GetRoot(cam.CAMSetup.View.Geometry),
            "mill_planar",
            "MCS",
            use_name,
            names["mcs"],
        )
        created["mcs"] = True
    else:
        created["mcs"] = False

    workpiece = _cam_find_group(setup, names["workpiece"])
    if workpiece is None:
        workpiece = collection.CreateGeometry(
            mcs,
            "mill_planar",
            "WORKPIECE",
            use_name,
            names["workpiece"],
        )
        created["workpiece"] = True
    else:
        created["workpiece"] = False

    setup.SetTemplateStatus([program, method, mcs, workpiece], False, False)
    mcs_result = _op_define_cam_mcs(
        {
            "mcs_name": names["mcs"],
            "origin": params.get("origin", [0.0, 0.0, 0.0]),
            "x_axis": params.get("x_axis", [1.0, 0.0, 0.0]),
            "y_axis": params.get("y_axis", [0.0, 1.0, 0.0]),
            "fixture_offset": params.get("fixture_offset", 1),
        }
    )
    workpiece_result = _op_define_cam_workpiece(
        {
            "workpiece_name": names["workpiece"],
            "body_indices": params.get("part_body_indices"),
            "blank_body_indices": params.get("blank_body_indices"),
            "blank_offset": params.get("blank_offset", 2.0),
            "blank_offsets": params.get("blank_offsets") or {},
        }
    )
    return {
        "ok": True,
        "part": _work_part().Leaf,
        "names": names,
        "created": created,
        "template_status": {
            "program": _cam_template_status(setup, program),
            "method": _cam_template_status(setup, method),
            "mcs": _cam_template_status(setup, mcs),
            "workpiece": _cam_template_status(setup, workpiece),
        },
        "mcs": mcs_result,
        "workpiece": workpiece_result,
    }


def _op_inspect_cam_setup(params):
    cam = _cam_module()
    setup = _cam_setup()
    max_depth = int(params.get("max_depth", 4))
    if not 1 <= max_depth <= 8:
        raise ValueError("max_depth must be between 1 and 8")
    roots = {}
    for name, view in (
        ("program", cam.CAMSetup.View.ProgramOrder),
        ("method", cam.CAMSetup.View.MachineMethod),
        ("geometry", cam.CAMSetup.View.Geometry),
        ("tool", cam.CAMSetup.View.MachineTool),
    ):
        roots[name] = _cam_object_record(
            setup, setup.GetRoot(view), True, max_depth=max_depth
        )
    operations = _cam_operations(setup)
    return {
        "ok": True,
        "part": _work_part().Leaf,
        "operation_count": len(operations),
        "operations": [_cam_object_record(setup, item) for item in operations],
        "roots": roots,
    }


def _op_define_cam_mcs(params):
    cam = _cam_module()
    work = _work_part()
    setup = _cam_setup()
    mcs_name = _cam_safe_name("mcs_name", params.get("mcs_name", "MCS_MAIN"))
    origin = _vector3("origin", params.get("origin", [0.0, 0.0, 0.0]))
    x_axis = _unit_vector(_vector3("x_axis", params.get("x_axis", [1.0, 0.0, 0.0])))
    y_axis = _unit_vector(_vector3("y_axis", params.get("y_axis", [0.0, 1.0, 0.0])))
    if abs(sum(x_axis[index] * y_axis[index] for index in range(3))) > 1.0e-6:
        raise ValueError("x_axis and y_axis must be perpendicular")
    fixture_offset = int(params.get("fixture_offset", 1))
    if not 1 <= fixture_offset <= 99:
        raise ValueError("fixture_offset must be between 1 and 99")
    try:
        mcs = setup.CAMGroupCollection.FindObject(mcs_name)
    except Exception:
        raise ValueError("CAM MCS group was not found: %s" % mcs_name)
    csys = work.CoordinateSystems.CreateCoordinateSystem(
        NXOpen.Point3d(*origin), NXOpen.Vector3d(*x_axis), NXOpen.Vector3d(*y_axis)
    )
    builder = setup.CAMGroupCollection.CreateMillOrientGeomBuilder(mcs)
    try:
        builder.McsLocationMode = cam.OrientGeomBuilder.McsLocationModes.Specify
        builder.Mcs = csys
        builder.Rcs = csys
        builder.LinkRcsToMcs = True
        builder.FixtureOffsetBuilder.Value = fixture_offset
        builder.SetCsysPurposeMode(cam.OrientGeomBuilder.CsysPurposeModes.Main)
        builder.SetToolAxisMode(cam.OrientGeomBuilder.ToolAxisModes.PositiveZOfMcs)
        builder.Commit()
    finally:
        builder.Destroy()
    return {
        "ok": True,
        "part": work.Leaf,
        "mcs_name": mcs_name,
        "origin": origin,
        "x_axis": x_axis,
        "y_axis": y_axis,
        "fixture_offset": fixture_offset,
        "tool_axis": "positive_z_of_mcs",
    }


def _cam_offsets(params):
    default = float(params.get("blank_offset", 2.0))
    if default < 0.0:
        raise ValueError("blank_offset must not be negative")
    names = ("negative_x", "positive_x", "negative_y", "positive_y", "negative_z", "positive_z")
    values = {}
    overrides = params.get("blank_offsets") or {}
    if not isinstance(overrides, dict):
        raise ValueError("blank_offsets must be an object")
    for name in names:
        value = float(overrides.get(name, default))
        if value < 0.0:
            raise ValueError("blank offsets must not be negative")
        values[name] = value
    return values


def _op_define_cam_workpiece(params):
    cam = _cam_module()
    work = _work_part()
    setup = _cam_setup()
    workpiece_name = _cam_safe_name(
        "workpiece_name", params.get("workpiece_name", "WORKPIECE")
    )
    try:
        workpiece = setup.CAMGroupCollection.FindObject(workpiece_name)
    except Exception:
        raise ValueError("CAM workpiece group was not found: %s" % workpiece_name)
    all_bodies = list(work.Bodies)
    blank_indices = params.get("blank_body_indices")
    if blank_indices is not None:
        if not isinstance(blank_indices, list) or not blank_indices:
            raise ValueError("blank_body_indices must be a non-empty list")
        blank_indices = [int(index) for index in blank_indices]
        for index in blank_indices:
            if index < 0 or index >= len(all_bodies):
                raise ValueError("blank body index is out of range: %s" % index)
        if len(set(blank_indices)) != len(blank_indices):
            raise ValueError("blank_body_indices must not contain duplicates")
    fixture_indices = params.get("fixture_body_indices")
    if fixture_indices is not None:
        if not isinstance(fixture_indices, list) or not fixture_indices:
            raise ValueError("fixture_body_indices must be a non-empty list")
        fixture_indices = [int(index) for index in fixture_indices]
        for index in fixture_indices:
            if index < 0 or index >= len(all_bodies):
                raise ValueError("fixture body index is out of range: %s" % index)
        if len(set(fixture_indices)) != len(fixture_indices):
            raise ValueError("fixture_body_indices must not contain duplicates")
    excluded_indices = set((blank_indices or []) + (fixture_indices or []))
    indices = params.get("body_indices")
    if indices is None:
        indices = [
            index
            for index in range(len(all_bodies))
            if index not in excluded_indices
        ]
    if not isinstance(indices, list) or not indices:
        raise ValueError("body_indices must identify at least one body")
    indices = [int(index) for index in indices]
    bodies = []
    for index in indices:
        if index < 0 or index >= len(all_bodies):
            raise ValueError("body index is out of range: %s" % index)
        bodies.append(all_bodies[index])
    if len(set(int(index) for index in indices)) != len(indices):
        raise ValueError("body_indices must not contain duplicates")
    if set(indices).intersection(excluded_indices):
        raise ValueError("part, blank, and fixture body indices must not overlap")
    if set(blank_indices or []).intersection(fixture_indices or []):
        raise ValueError("blank and fixture body indices must not overlap")
    blank_bodies = (
        [all_bodies[index] for index in blank_indices]
        if blank_indices is not None
        else []
    )
    fixture_bodies = (
        [all_bodies[index] for index in fixture_indices]
        if fixture_indices is not None
        else []
    )
    offsets = _cam_offsets(params)
    builder = setup.CAMGroupCollection.CreateMillGeomBuilder(workpiece)
    try:
        part_geometry = builder.PartGeometry
        part_assignment = _cam_append_geometry(builder, "PartGeometry", bodies)
        added_part_geometry = bool(part_assignment["objects_added"])
        fixture_assignment = _cam_append_geometry(
            builder, "CheckGeometry", fixture_bodies
        )
        blank = builder.BlankGeometry
        if blank_bodies:
            blank.BlankDefinitionType = cam.GeometryGroup.BlankDefinitionTypes.FromGeometry
            blank_assignment = _cam_append_geometry(
                builder, "BlankGeometry", blank_bodies
            )
        else:
            blank.BlankDefinitionType = cam.GeometryGroup.BlankDefinitionTypes.AutoBlock
            blank.AutoBlockOffsetNegativeX = offsets["negative_x"]
            blank.AutoBlockOffsetPositiveX = offsets["positive_x"]
            blank.AutoBlockOffsetNegativeY = offsets["negative_y"]
            blank.AutoBlockOffsetPositiveY = offsets["positive_y"]
            blank.AutoBlockOffsetNegativeZ = offsets["negative_z"]
            blank.AutoBlockOffsetPositiveZ = offsets["positive_z"]
            blank_assignment = None
        builder.Commit()
        part_geometry_sets = int(part_geometry.GeometryList.Length)
        fixture_geometry_sets = int(builder.CheckGeometry.GeometryList.Length)
        blank_value = int(getattr(blank.BlankDefinitionType, "value", blank.BlankDefinitionType))
        blank_definition = {
            0: "from_geometry",
            1: "offset_from_part",
            2: "auto_block",
            3: "ipw",
            4: "bounding_cylinder",
            5: "part_outline",
            6: "part_convex_hull",
        }.get(blank_value, _cam_enum_name(blank.BlankDefinitionType))
    finally:
        builder.Destroy()
    return {
        "ok": True,
        "part": work.Leaf,
        "workpiece_name": workpiece_name,
        "body_indices": [int(index) for index in indices],
        "blank_body_indices": blank_indices,
        "fixture_body_indices": fixture_indices,
        "part_geometry_added": added_part_geometry,
        "part_geometry_sets": part_geometry_sets,
        "part_geometry_assignment": part_assignment,
        "blank_definition": blank_definition,
        "blank_geometry_assignment": blank_assignment,
        "fixture_geometry_assignment": fixture_assignment,
        "fixture_geometry_sets": fixture_geometry_sets,
        "blank_offsets": offsets,
    }


def _normalize_cam_tool_sections(field_name, value):
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ValueError("%s must be a non-empty list or null" % field_name)
    if len(value) > 20:
        raise ValueError("%s must not contain more than 20 sections" % field_name)
    sections = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError("%s[%s] must be an object" % (field_name, index))
        lower = float(item.get("lower_diameter", 0.0))
        upper = float(item.get("upper_diameter", lower))
        length = float(item.get("length", 0.0))
        radius = float(item.get("corner_radius", 0.0))
        if lower <= 0.0 or upper <= 0.0 or length <= 0.0:
            raise ValueError("tool section diameters and lengths must be greater than zero")
        if radius < 0.0 or radius > min(lower, upper) / 2.0:
            raise ValueError("tool section corner_radius is out of range")
        sections.append(
            {
                "lower_diameter": lower,
                "upper_diameter": upper,
                "length": length,
                "corner_radius": radius,
            }
        )
    return sections


def _replace_cam_tool_sections(section_builder, sections):
    while int(section_builder.NumberOfSections) > 0:
        section_builder.Delete(int(section_builder.NumberOfSections) - 1)
    actual_indices = []
    for index, item in enumerate(sections):
        actual = int(
            section_builder.AddByUpperDiameter(
                index,
                item["lower_diameter"],
                item["length"],
                item["upper_diameter"],
                item["corner_radius"],
            )
        )
        if actual < 0:
            raise RuntimeError("NX rejected tool section index %s" % index)
        actual_indices.append(actual)
    return actual_indices


def _op_create_cam_mill_tool(params):
    cam = _cam_module()
    setup = _cam_setup()
    name = _cam_safe_name("name", params.get("name", "T01_END_MILL"))
    diameter = float(params.get("diameter", 10.0))
    flute_length = float(params.get("flute_length", diameter * 3.0))
    overall_length = float(params.get("overall_length", max(60.0, flute_length * 2.0)))
    flute_count = int(params.get("flute_count", 4))
    tool_number = int(params.get("tool_number", 1))
    shank_diameter = params.get("shank_diameter")
    if shank_diameter is not None:
        shank_diameter = float(shank_diameter)
        if shank_diameter <= 0.0:
            raise ValueError("shank_diameter must be greater than zero")
    holder_sections = _normalize_cam_tool_sections(
        "holder_sections", params.get("holder_sections")
    )
    shank_sections = _normalize_cam_tool_sections(
        "shank_sections", params.get("shank_sections")
    )
    if diameter <= 0.0 or flute_length <= 0.0 or overall_length <= 0.0:
        raise ValueError("tool dimensions must be greater than zero")
    if flute_length > overall_length:
        raise ValueError("flute_length must not exceed overall_length")
    if not 1 <= flute_count <= 20 or not 1 <= tool_number <= 9999:
        raise ValueError("flute_count or tool_number is out of range")
    try:
        tool = setup.CAMGroupCollection.FindObject(name)
        created = False
    except Exception:
        root = setup.GetRoot(cam.CAMSetup.View.MachineTool)
        tool = setup.CAMGroupCollection.CreateTool(
            root,
            "mill_planar",
            "MILL",
            cam.NCGroupCollection.UseDefaultName.FalseValue,
            name,
        )
        created = True
    builder = setup.CAMGroupCollection.CreateMillToolBuilder(tool)
    try:
        builder.TlDiameterBuilder.Value = diameter
        builder.TlFluteLnBuilder.Value = flute_length
        builder.TlHeightBuilder.Value = overall_length
        builder.TlNumFlutesBuilder.Value = flute_count
        builder.TlNumberBuilder.Value = tool_number
        builder.TlAdjRegBuilder.Value = int(params.get("length_offset_register", tool_number))
        if shank_diameter is not None:
            builder.TlShankDiaBuilder.Value = shank_diameter
        if holder_sections is not None:
            _replace_cam_tool_sections(builder.HolderSectionBuilder, holder_sections)
        if shank_sections is not None:
            _replace_cam_tool_sections(builder.ShankSectionBuilder, shank_sections)
        builder.Commit()
    finally:
        builder.Destroy()
    tool_profile = _cam_tool_profile_record(setup, tool)
    setup.SetTemplateStatus([tool], False, False)
    return {
        "ok": True,
        "created": created,
        "name": name,
        "diameter": diameter,
        "flute_length": flute_length,
        "overall_length": overall_length,
        "flute_count": flute_count,
        "tool_number": tool_number,
        "shank_diameter": tool_profile.get("shank_diameter"),
        "holder_sections": tool_profile.get("holder_sections", []),
        "shank_sections": tool_profile.get("shank_sections", []),
        "simulation_geometry": {
            "cutter_ready": tool_profile.get("cutter_geometry_ready", False),
            "shank_ready": tool_profile.get("shank_geometry_ready", False),
            "holder_ready": tool_profile.get("holder_geometry_ready", False),
        },
        "template_status": _cam_template_status(setup, tool),
        "cam_object": _cam_object_record(setup, tool),
    }


def _op_create_cam_operation(params):
    cam = _cam_module()
    session = NXOpen.Session.GetSession()
    setup = _cam_setup()
    name = _cam_safe_name("name", params.get("name", "MCP_OPERATION"))
    template_type = _cam_safe_name(
        "template_type", params.get("template_type", "mill_planar")
    )
    template_subtype = _cam_safe_name("template_subtype", params.get("template_subtype"))
    available_types = list(session.CAMSession.GetTemplateTypes())
    if template_type not in available_types:
        raise ValueError("template_type is not available in this NX session")
    available_subtypes = list(
        session.CAMSession.GetTemplateSubtypes(
            template_type, cam.CAMSession.ObjectSubtype.Operation
        )
    )
    if template_subtype not in available_subtypes:
        raise ValueError(
            "template_subtype is unavailable; call get_cam_capabilities with template_type"
        )
    parent_names = {
        "program": params.get("program_name", "MCP_PROGRAM"),
        "method": params.get("method_name", "MCP_METHOD"),
        "tool": params.get("tool_name", "T01_END_MILL"),
        "geometry": params.get("geometry_name", "MCP_WORKPIECE"),
    }
    parents = {}
    for key, raw_name in parent_names.items():
        parent_name = _cam_safe_name("%s_name" % key, raw_name)
        try:
            parents[key] = setup.CAMGroupCollection.FindObject(parent_name)
        except Exception:
            raise ValueError("CAM %s parent was not found: %s" % (key, parent_name))
        parent_names[key] = parent_name
    template_parents = [
        key
        for key, parent in parents.items()
        if _cam_template_status(setup, parent)["use_as_template"]
    ]
    if template_parents and not bool(params.get("allow_template_parents", False)):
        raise ValueError(
            "CAM operation parents are template objects (%s); call "
            "create_cam_milling_context and use its returned names"
            % ", ".join(template_parents)
        )
    try:
        existing = setup.CAMOperationCollection.FindObject(name)
    except Exception:
        existing = None
    if existing is not None:
        raise ValueError("CAM operation already exists: %s" % name)
    operation = setup.CAMOperationCollection.Create(
        parents["program"],
        parents["method"],
        parents["tool"],
        parents["geometry"],
        template_type,
        template_subtype,
        cam.OperationCollection.UseDefaultName.FalseValue,
        name,
    )
    builder = setup.CAMOperationCollection.CreateBuilder(operation)
    try:
        builder.Commit()
    finally:
        builder.Destroy()
    setup.SetTemplateStatus([operation], False, False)
    return {
        "ok": True,
        "name": name,
        "template_type": template_type,
        "template_subtype": template_subtype,
        "parents": parent_names,
        "template_status": _cam_template_status(setup, operation),
        "operation": _cam_object_record(setup, operation),
        "toolpath_ready": bool(operation.AskPathExists()),
        "note": "Geometry-specific parameters may still be required before generation.",
    }


def _cam_face_objects(work, params, selectors):
    if selectors is None:
        return []
    if not isinstance(selectors, list):
        raise ValueError("face selector collections must be lists")
    faces = []
    for item in selectors:
        if not isinstance(item, dict):
            raise ValueError("each face selector must be an object")
        selector = item.get("selector", item)
        topology_params = {
            "body_index": item.get("body_index", params.get("body_index", 0)),
            "body_feature_id": item.get(
                "body_feature_id", params.get("body_feature_id")
            ),
            "body_occurrence": item.get(
                "body_occurrence", params.get("body_occurrence", 0)
            ),
        }
        faces.append(
            _resolve_topology_object(work, topology_params, "face", selector)["object"]
        )
    return faces


def _cam_append_geometry(builder, property_name, objects):
    if not objects:
        return None
    if not hasattr(builder, property_name):
        raise ValueError(
            "this operation template does not expose %s" % property_name
        )
    geometry = getattr(builder, property_name)
    before = int(geometry.GeometryList.Length)
    existing_sets = [
        item for item in geometry.GeometryList.GetContents() if item is not None
    ]
    existing_tags = set()
    for item in existing_sets:
        for existing in item.GetItems():
            existing_tags.add(int(existing.Tag))
    new_objects = [obj for obj in objects if int(obj.Tag) not in existing_tags]
    if not new_objects:
        return {
            "before": before,
            "after": before,
            "objects_added": 0,
            "already_assigned": True,
        }
    empty_set = next((item for item in existing_sets if not item.GetItems()), None)
    if empty_set is not None:
        empty_set.Selection.Add(new_objects)
    else:
        geometry_set = geometry.CreateGeometrySet()
        geometry_set.Selection.Add(new_objects)
        geometry.GeometryList.Append(geometry_set)
    return {
        "before": before,
        "after": int(geometry.GeometryList.Length),
        "objects_added": len(new_objects),
        "already_assigned": False,
    }


def _cam_set_builder_real(builder, property_name, value):
    if value is None:
        return None
    if not hasattr(builder, property_name):
        raise ValueError(
            "this operation template does not expose %s" % property_name
        )
    value = float(value)
    if value < 0.0:
        raise ValueError("%s must not be negative" % property_name)
    parameter = getattr(builder, property_name)
    if hasattr(parameter, "Value"):
        parameter.Value = value
    else:
        setattr(builder, property_name, value)
    return value


def _cam_set_inheritable_value(owner, property_name, value, unit=None):
    if value is None:
        return None
    if not hasattr(owner, property_name):
        raise ValueError("this operation template does not expose %s" % property_name)
    value = float(value)
    if value <= 0.0:
        raise ValueError("%s must be greater than zero" % property_name)
    target = getattr(owner, property_name)
    if hasattr(target, "InheritanceStatus"):
        target.InheritanceStatus = False
    if unit is not None and hasattr(target, "Unit"):
        target.Unit = unit
    target.Value = value
    return value


def _cam_configure_feeds(cam, builder, params):
    if not hasattr(builder, "FeedsBuilder"):
        if any(
            params.get(name) is not None
            for name in ("spindle_rpm", "cut_feed", "approach_feed", "retract_feed")
        ):
            raise ValueError("this operation template does not expose milling feeds")
        return {}
    feeds = builder.FeedsBuilder
    configured = {}
    spindle = params.get("spindle_rpm")
    if spindle is not None:
        feeds.SpindleRpmToggle = 1
        configured["spindle_rpm"] = _cam_set_inheritable_value(
            feeds, "SpindleRpmBuilder", spindle
        )
    for result_name, property_name, parameter_name in (
        ("cut_feed", "FeedCutBuilder", "cut_feed"),
        ("approach_feed", "FeedApproachBuilder", "approach_feed"),
        ("retract_feed", "FeedRetractBuilder", "retract_feed"),
    ):
        value = params.get(parameter_name)
        if value is not None:
            configured[result_name] = _cam_set_inheritable_value(
                feeds, property_name, value, cam.FeedRateUnit.PerMinute
            )
    return configured


def _op_set_cam_operation_geometry(params):
    cam = _cam_module()
    setup = _cam_setup()
    work = _work_part()
    operation = _cam_find_operation(setup, params.get("operation_name"))
    builder = setup.CAMOperationCollection.CreateBuilder(operation)
    assignments = {}
    try:
        body_indices = params.get("part_body_indices")
        if body_indices is not None:
            if not isinstance(body_indices, list) or not body_indices:
                raise ValueError("part_body_indices must be a non-empty list")
            all_bodies = list(work.Bodies)
            part_bodies = []
            for raw_index in body_indices:
                index = int(raw_index)
                if index < 0 or index >= len(all_bodies):
                    raise ValueError("part body index is out of range: %s" % index)
                part_bodies.append(all_bodies[index])
            assignments["part_geometry"] = _cam_append_geometry(
                builder, "PartGeometry", part_bodies
            )
        geometry_inputs = (
            ("cut_area", "CutAreaGeometry", "cut_area_face_selectors"),
            ("wall", "WallGeometry", "wall_face_selectors"),
            ("check", "CheckGeometry", "check_face_selectors"),
        )
        for result_name, property_name, parameter_name in geometry_inputs:
            faces = _cam_face_objects(work, params, params.get(parameter_name))
            if faces:
                assignments[result_name] = _cam_append_geometry(
                    builder, property_name, faces
                )
        parameters = {
            "depth_per_cut": _cam_set_builder_real(
                builder, "DepthPerCut", params.get("depth_per_cut")
            ),
            "top_offset": _cam_set_builder_real(
                builder, "TopOffset", params.get("top_offset")
            ),
            "safe_clearance": _cam_set_builder_real(
                builder, "SafeClearance", params.get("safe_clearance")
            ),
        }
        feeds = _cam_configure_feeds(cam, builder, params)
        validation = bool(builder.Validate())
        builder.Commit()
    finally:
        builder.Destroy()
    return {
        "ok": validation,
        "operation_name": operation.Name,
        "builder_type": type(builder).__name__,
        "validation_passed": validation,
        "assignments": assignments,
        "parameters": parameters,
        "feeds": feeds,
        "operation": _cam_object_record(setup, operation),
    }


def _op_configure_cam_milling_operation(params):
    operation_name = _cam_safe_name("operation_name", params.get("operation_name"))
    if not any(
        params.get(name) is not None
        for name in (
            "part_body_indices",
            "cut_area_face_selectors",
            "wall_face_selectors",
            "check_face_selectors",
            "depth_per_cut",
            "top_offset",
            "safe_clearance",
            "spindle_rpm",
            "cut_feed",
            "approach_feed",
            "retract_feed",
        )
    ):
        raise ValueError("at least one milling geometry or cutting parameter is required")
    forwarded = dict(params)
    forwarded["operation_name"] = operation_name
    result = _op_set_cam_operation_geometry(forwarded)
    result["strategy_adapter"] = "nx2412_milling"
    return result


def _op_inspect_cam_operation_details(params):
    cam = _cam_module()
    setup = _cam_setup()
    operations = _cam_selected_operations(setup, params.get("operation_names"))
    records = []
    for operation in operations:
        builder = setup.CAMOperationCollection.CreateBuilder(operation)
        try:
            record = _cam_object_record(setup, operation)
            record["template_status"] = _cam_template_status(setup, operation)
            record["builder_type"] = type(builder).__name__
            record["builder_validation"] = bool(builder.Validate())
            record["parents"] = {}
            for name, view in (
                ("program", cam.CAMSetup.View.ProgramOrder),
                ("method", cam.CAMSetup.View.MachineMethod),
                ("tool", cam.CAMSetup.View.MachineTool),
                ("geometry", cam.CAMSetup.View.Geometry),
            ):
                parent = operation.GetParent(view)
                record["parents"][name] = {
                    "name": getattr(parent, "Name", None),
                    "type": type(parent).__name__,
                    "tag": int(parent.Tag),
                    "template_status": _cam_template_status(setup, parent),
                }
            record["geometry"] = {}
            for result_name, property_name in (
                ("part", "PartGeometry"),
                ("cut_area", "CutAreaGeometry"),
                ("wall", "WallGeometry"),
                ("check", "CheckGeometry"),
                ("blank", "BlankGeometry"),
            ):
                if hasattr(builder, property_name):
                    record["geometry"][result_name] = _cam_geometry_record(
                        getattr(builder, property_name)
                    )
            record["parameters"] = {}
            for property_name in ("DepthPerCut", "TopOffset", "SafeClearance"):
                if hasattr(builder, property_name):
                    record["parameters"][property_name] = _cam_inheritable_record(
                        getattr(builder, property_name)
                    )
            if hasattr(builder, "FeedsBuilder"):
                feeds = builder.FeedsBuilder
                record["feeds"] = {
                    "spindle_rpm_toggle": int(feeds.SpindleRpmToggle),
                    "spindle_rpm": _cam_inheritable_record(feeds.SpindleRpmBuilder),
                    "cut_feed": _cam_inheritable_record(feeds.FeedCutBuilder),
                    "approach_feed": _cam_inheritable_record(
                        feeds.FeedApproachBuilder
                    ),
                    "retract_feed": _cam_inheritable_record(
                        feeds.FeedRetractBuilder
                    ),
                }
            records.append(record)
        finally:
            builder.Destroy()
    return {
        "ok": True,
        "part": _work_part().Leaf,
        "operation_count": len(records),
        "operations": records,
    }


def _op_inspect_cam_operations(params):
    setup = _cam_setup()
    names = params.get("operation_names")
    operations = _cam_selected_operations(setup, names) if names else _cam_operations(setup)
    records = []
    for operation in operations:
        record = _cam_object_record(setup, operation)
        record["template_status"] = _cam_template_status(setup, operation)
        records.append(record)
    return {
        "ok": True,
        "part": _work_part().Leaf,
        "operation_count": len(operations),
        "operations": records,
        "all_have_toolpaths": bool(operations) and all(
            bool(operation.AskPathExists()) for operation in operations
        ),
    }


def _op_generate_cam_toolpath(params):
    cam = _cam_module()
    setup = _cam_setup()
    operations = _cam_selected_operations(setup, params.get("operation_names"))
    backend = str(params.get("backend", "auto")).strip().lower()
    if backend not in ("auto", "nxopen", "uf"):
        raise ValueError("backend must be auto, nxopen, or uf")
    machining_data_failures = []
    if bool(params.get("set_machining_data", False)):
        for item in setup.SetMachiningData(operations):
            error_code = int(item.ErrorCode)
            machining_data_failures.append(
                {
                    "operation_name": getattr(item.ObjectTag, "Name", None),
                    "error_code": error_code,
                    "message": (
                        "No matching machining-data record was found; explicit "
                        "feeds and spindle values may still be used."
                        if error_code in (1740011, 1850031)
                        else "NX machining-data lookup failed."
                    ),
                }
            )
    generation_results = []
    if backend in ("auto", "nxopen"):
        generator = setup.CreateToolpathGenerateBuilder(operations)
        try:
            generator.GenerationType = cam.ToolpathGenerateBuilder.Types.Foreground
            raw_results = list(generator.Generate())
            generator.WaitGenerationDone()
            for item in raw_results:
                try:
                    owner = item.GetObject()
                    result_value = item.GetResult()
                    result_code = int(getattr(result_value, "value", result_value))
                    generation_results.append(
                        {
                            "operation_name": getattr(owner, "Name", None),
                            "backend": "nxopen",
                            "result": "success" if result_code == 0 else "failure",
                            "result_value": result_code,
                        }
                    )
                finally:
                    item.Dispose()
        finally:
            generator.Dispose()

    uf_targets = [operation for operation in operations if not operation.AskPathExists()]
    if backend == "uf":
        uf_targets = operations
    if uf_targets and backend in ("auto", "uf"):
        import NXOpen.UF

        uf_param = NXOpen.UF.UFSession.GetUFSession().Param
        for operation in uf_targets:
            try:
                generated = bool(uf_param.Generate(operation.Tag))
                generation_results.append(
                    {
                        "operation_name": operation.Name,
                        "backend": "uf_param_generate",
                        "result": (
                            "success"
                            if generated and operation.AskPathExists()
                            else "failure"
                        ),
                        "return_value": generated,
                        "path_exists": bool(operation.AskPathExists()),
                    }
                )
            except Exception as exc:
                generation_results.append(
                    {
                        "operation_name": operation.Name,
                        "backend": "uf_param_generate",
                        "result": "failure",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "error_code": getattr(exc, "ErrorCode", None),
                    }
                )
    records = [_cam_object_record(setup, operation) for operation in operations]
    generated = [record for record in records if record.get("path_exists")]
    return {
        "ok": len(generated) == len(records),
        "part": _work_part().Leaf,
        "requested_count": len(records),
        "generated_count": len(generated),
        "validation_passed": len(generated) == len(records),
        "generation_results": generation_results,
        "requested_backend": backend,
        "fallback_used": any(
            item.get("backend") == "uf_param_generate"
            for item in generation_results
        ),
        "machining_data_failures": machining_data_failures,
        "operations": records,
        "note": (
            None
            if len(generated) == len(records)
            else "NX returned without a complete toolpath; inspect the actual CAM parent context, geometry, and parameters."
        ),
    }


_MACHINE_REPLACE_CONFIRMATION = "REPLACE_EXISTING_MACHINE_TOOL"


def _op_bind_machine_tool_from_library(params):
    initialization_stage = "load_cam_module"
    try:
        cam = _cam_module()
        initialization_stage = "read_cam_setup"
        setup = _cam_setup()
        initialization_stage = "read_work_part"
        work = _work_part()
        initialization_stage = "read_nx_session"
        session = NXOpen.Session.GetSession()
    except Exception as exc:
        safe = _safe_nx_error(exc)
        raise RuntimeError(
            "NX machine binding failed at %s (type=%s, error_code=%s)"
            % (initialization_stage, safe["type"], safe["error_code"])
        )
    try:
        requested = _machine_library_entry(
            work.KinematicConfigurator, params.get("machine_libref")
        )
    except Exception as exc:
        safe = _safe_nx_error(exc)
        raise RuntimeError(
            "NX machine binding failed at machine_library_entry_lookup "
            "(type=%s, error_code=%s)"
            % (safe["type"], safe["error_code"])
        )
    machine_libref = requested["libref"]
    try:
        current_libref = str(setup.GetMachineLibref()).strip()
    except Exception as exc:
        safe = _safe_nx_error(exc)
        raise RuntimeError(
            "NX machine binding failed at current_machine_binding_readback "
            "(type=%s, error_code=%s)"
            % (safe["type"], safe["error_code"])
        )
    dry_run = bool(params.get("dry_run", True))
    replace_existing = bool(params.get("replace_existing", False))
    reload_existing = bool(params.get("reload_existing", False))
    if current_libref == machine_libref and not reload_existing:
        return {
            "ok": True,
            "part": work.Leaf,
            "dry_run": dry_run,
            "changed": False,
            "machine": requested,
            "readiness": _machine_simulation_readiness(
                {
                    "program_name": params.get("program_name", "MCP_PROGRAM"),
                    "operation_names": params.get("operation_names"),
                    "required_axes": params.get("required_axes") or [],
                }
            ),
        }
    if current_libref and not replace_existing:
        raise RuntimeError(
            "A different machine is already bound. Set replace_existing=true and "
            "supply the exact replacement confirmation to replace it."
        )
    if current_libref and params.get("confirmation") != _MACHINE_REPLACE_CONFIRMATION:
        raise PermissionError(
            "Replacing the existing machine requires confirmation=%s"
            % _MACHINE_REPLACE_CONFIRMATION
        )

    try:
        machine_group = setup.CAMGroupCollection.FindObject("GENERIC_MACHINE")
    except Exception:
        machine_group = setup.GetRoot(cam.CAMSetup.View.MachineTool)
    try:
        machine_group_builder = setup.CAMGroupCollection.CreateMachineGroupBuilder(
            machine_group
        )
    except Exception as exc:
        safe = _safe_nx_error(exc)
        raise RuntimeError(
            "NX machine binding could not initialize the classified machine group "
            "(type=%s, error_code=%s)"
            % (safe["type"], safe["error_code"])
        )
    mounting_builder = None
    builder_cleanup_warnings = []
    try:
        try:
            mounting_builder = setup.CreateNcmctPartMountingBuilder(machine_libref)
        except Exception as exc:
            safe = _safe_nx_error(exc)
            raise RuntimeError(
                "NX machine binding failed at create_part_mounting_builder "
                "(type=%s, error_code=%s)"
                % (safe["type"], safe["error_code"])
            )
        if mounting_builder is None:
            raise RuntimeError("NX could not create the machine mounting builder")
        configuration_stage = "set_mounting_positioning"
        try:
            mounting_builder.Positioning = (
                cam.NcmctPartMountingBuilder.PositioningTypes.OrientMachineZeroToMainMcs
            )
            configuration_stage = "set_mounting_layer_options"
            mounting_builder.LayerOptions = (
                cam.NcmctPartMountingBuilder.LayerTypes.OriginalMakeVisible
            )
            configuration_stage = "set_create_spindle_objects"
            mounting_builder.CreateMachineSpindleObjects = bool(
                params.get("create_spindle_objects", True)
            )
            configuration_stage = "validate_mounting_configuration"
            if not bool(mounting_builder.Validate()):
                raise RuntimeError("NX rejected the machine mounting configuration")
        except Exception as exc:
            safe = _safe_nx_error(exc)
            raise RuntimeError(
                "NX machine binding failed at %s (type=%s, error_code=%s)"
                % (configuration_stage, safe["type"], safe["error_code"])
            )
        if dry_run:
            return {
                "ok": True,
                "part": work.Leaf,
                "dry_run": True,
                "changed": False,
                "current_machine_libref": current_libref or None,
                "machine": requested,
                "mounting_builder_valid": True,
                "positioning": "orient_machine_zero_to_main_mcs",
                "create_spindle_objects": bool(
                    params.get("create_spindle_objects", True)
                ),
                "requires_explicit_commit": True,
            }

        mark_name = "NX MCP Bind Machine Tool"
        try:
            mark = session.SetUndoMark(session.MarkVisibility.Visible, mark_name)
        except Exception as exc:
            safe = _safe_nx_error(exc)
            raise RuntimeError(
                "NX machine binding failed at create_binding_undo_mark "
                "(type=%s, error_code=%s)"
                % (safe["type"], safe["error_code"])
            )
        try:
            machine_group_builder.RemoveMachine()
            mounting_builder.Commit()
            machine_group_builder.UpdateCamSetup(
                cam.MachineGroupBuilder.RetrieveToolPocketInformation.Yes,
                mounting_builder,
            )
            bound_libref = str(setup.GetMachineLibref()).strip()
            if bound_libref != machine_libref:
                raise RuntimeError("NX did not report the requested machine binding")
            session.SetUndoMarkName(mark, "NX MCP Bound Machine Tool")
        except Exception as exc:
            try:
                session.UndoToMark(mark, mark_name)
            except Exception:
                pass
            safe = _safe_nx_error(exc)
            raise RuntimeError(
                "NX machine binding failed (type=%s, error_code=%s); the change was rolled back"
                % (safe["type"], safe["error_code"])
            )
    finally:
        if mounting_builder is not None:
            try:
                mounting_builder.Destroy()
            except Exception as exc:
                warning = _safe_nx_error(exc)
                warning["builder"] = "part_mounting"
                builder_cleanup_warnings.append(warning)
        try:
            machine_group_builder.Destroy()
        except Exception as exc:
            warning = _safe_nx_error(exc)
            warning["builder"] = "machine_group"
            builder_cleanup_warnings.append(warning)

    try:
        readiness = _machine_simulation_readiness(
            {
                "program_name": params.get("program_name", "MCP_PROGRAM"),
                "operation_names": params.get("operation_names"),
                "required_axes": params.get("required_axes") or [],
            }
        )
    except Exception as exc:
        safe = _safe_nx_error(exc)
        raise RuntimeError(
            "NX machine binding failed at post_bind_readiness "
            "(type=%s, error_code=%s)"
            % (safe["type"], safe["error_code"])
        )

    return {
        "ok": True,
        "part": work.Leaf,
        "dry_run": False,
        "changed": True,
        "machine": requested,
        "saved": False,
        "readiness": readiness,
        "builder_cleanup_warnings": builder_cleanup_warnings,
    }


def _op_bind_isolated_machine_kit_to_cam(params):
    _kit_root, package_path = _machine_kit_path(
        params.get("machine_kit_file_name"), must_exist=True
    )
    kit_identifier = _machine_kit_identifier(package_path)
    dry_run = bool(params.get("dry_run", True))
    result = {
        "ok": True,
        "dry_run": dry_run,
        "changed": False,
        "machine_kit_file_name": os.path.basename(package_path),
        "machine_libref": str(params.get("machine_libref") or kit_identifier),
        "session_shadow_library": True,
        "global_machine_library_modified": False,
        "paths_redacted": True,
        "production_certified": False,
        "requires_explicit_confirmation": True,
    }
    if dry_run:
        result["import_validation"] = _op_import_machine_kit_readback(
            {
                "machine_kit_file_name": os.path.basename(package_path),
                "dry_run": True,
            }
        )
        result["note"] = (
            "No CAM binding was changed; set dry_run=false and provide the exact confirmation."
        )
        return result
    if params.get("confirmation") != _MACHINE_KIT_CAM_BIND_CONFIRMATION:
        raise PermissionError(
            "Session-shadow CAM binding requires confirmation=%s"
            % _MACHINE_KIT_CAM_BIND_CONFIRMATION
        )

    import_root = os.path.abspath(os.path.join(WORKSPACE, "machine_kit_imports"))
    if not os.path.isdir(import_root):
        os.makedirs(import_root)
    reload_existing = bool(params.get("reload_existing", False))
    reload_mark = None
    reload_record = None
    reload_finalize_warning = None
    reload_mark_name = "NX MCP Reload Session-Shadow Machine"
    session = NXOpen.Session.GetSession()
    current_libref = ""
    if reload_existing:
        if not bool(params.get("replace_existing", False)):
            raise PermissionError("reload_existing requires replace_existing=true")
        if params.get("replace_confirmation") != _MACHINE_REPLACE_CONFIRMATION:
            raise PermissionError(
                "Reloading the existing machine requires replace_confirmation=%s"
                % _MACHINE_REPLACE_CONFIRMATION
            )
        try:
            setup = _cam_setup()
            current_libref = str(setup.GetMachineLibref()).strip()
        except Exception as exc:
            safe = _safe_nx_error(exc)
            raise RuntimeError(
                "NX session-shadow machine binding failed at reload_precheck "
                "(type=%s, error_code=%s)"
                % (safe["type"], safe["error_code"])
            )
        requested_libref = str(params.get("machine_libref") or kit_identifier).strip()
        if current_libref != requested_libref:
            raise ValueError("reload_existing requires the currently bound machine libref")
    before = set(
        name
        for name in os.listdir(import_root)
        if os.path.isdir(os.path.join(import_root, name))
    )
    try:
        import_result = _op_import_machine_kit_readback(
            {
                "machine_kit_file_name": os.path.basename(package_path),
                "source_profile": params.get("source_profile"),
                "dry_run": False,
                "keep_imported": True,
                "evaluate_static_collisions": bool(
                    params.get("evaluate_static_collisions", True)
                ),
                "confirmation": _MACHINE_KIT_IMPORT_CONFIRMATION,
                "static_collision_confirmation": _MACHINE_STATIC_COLLISION_CONFIRMATION,
            }
        )
    except Exception as exc:
        if reload_mark is not None:
            session.UndoToMark(reload_mark, reload_mark_name)
            reload_mark = None
        safe = _safe_nx_error(exc)
        raise RuntimeError(
            "NX session-shadow machine binding failed at isolated_import_readback "
            "(type=%s, error_code=%s)"
            % (safe["type"], safe["error_code"])
        )
    if not import_result.get("ok"):
        if reload_mark is not None:
            session.UndoToMark(reload_mark, reload_mark_name)
            reload_mark = None
        raise RuntimeError("The isolated machine kit failed NX import/readback validation")
    after = [
        os.path.join(import_root, name)
        for name in os.listdir(import_root)
        if name not in before and os.path.isdir(os.path.join(import_root, name))
    ]
    if len(after) != 1:
        if reload_mark is not None:
            session.UndoToMark(reload_mark, reload_mark_name)
            reload_mark = None
        raise RuntimeError("NX did not produce one unambiguous session-shadow machine library")
    staging = after[0]
    shadow_data = os.path.join(staging, "machine_data")
    shadow_machines = os.path.join(staging, "installed_machines")
    if reload_existing:
        try:
            setup = _cam_setup()
            reload_mark = session.SetUndoMark(
                session.MarkVisibility.Visible, reload_mark_name
            )
        except Exception as exc:
            safe = _safe_nx_error(exc)
            raise RuntimeError(
                "NX session-shadow machine binding failed at begin_reload_transaction "
                "(type=%s, error_code=%s)"
                % (safe["type"], safe["error_code"])
            )
        machine_group_builder = None
        reload_stage = "find_classified_machine_group"
        try:
            try:
                machine_group = setup.CAMGroupCollection.FindObject("GENERIC_MACHINE")
            except Exception:
                machine_group = setup.GetRoot(_cam_module().CAMSetup.View.MachineTool)
            reload_stage = "create_machine_group_builder"
            machine_group_builder = (
                setup.CAMGroupCollection.CreateMachineGroupBuilder(machine_group)
            )
            reload_stage = "remove_current_machine"
            machine_group_builder.RemoveMachine()
            reload_stage = "update_after_machine_removal"
            update_errors = int(session.UpdateManager.DoUpdate(reload_mark))
            if update_errors:
                raise RuntimeError("NX reported update errors while unloading the machine")
            reload_stage = "close_previous_shadow_machine_parts"
            closed_shadow_parts = _machine_close_stale_import_parts(
                import_root, close_existing=True
            )
            reload_record = {
                "previous_machine_libref": current_libref,
                "closed_shadow_machine_parts": closed_shadow_parts,
                "transactional_undo_mark": True,
                "import_validated_before_unload": True,
            }
        except Exception as exc:
            session.UndoToMark(reload_mark, reload_mark_name)
            reload_mark = None
            safe = _safe_nx_error(exc)
            raise RuntimeError(
                "NX session-shadow machine reload failed at %s "
                "(type=%s, error_code=%s)"
                % (reload_stage, safe["type"], safe["error_code"])
            )
        finally:
            if machine_group_builder is not None:
                try:
                    machine_group_builder.Destroy()
                except Exception:
                    pass
    environment_names = (
        "UGII_CAM_LIBRARY_MACHINE_DATA_DIR",
        "UGII_CAM_LIBRARY_MACHINE_CONFIG_DIR",
        "UGII_CAM_LIBRARY_INSTALLED_MACHINES_DIR",
    )
    previous_environment = {
        name: os.environ.get(name) for name in environment_names
    }
    try:
        separator = os.sep
        os.environ["UGII_CAM_LIBRARY_MACHINE_DATA_DIR"] = shadow_data + separator
        os.environ["UGII_CAM_LIBRARY_MACHINE_CONFIG_DIR"] = shadow_data + separator
        os.environ["UGII_CAM_LIBRARY_INSTALLED_MACHINES_DIR"] = (
            shadow_machines + separator
        )
        binding = _op_bind_machine_tool_from_library(
            {
                "machine_libref": params.get("machine_libref") or kit_identifier,
                "program_name": params.get("program_name", "MCP_PROGRAM"),
                "operation_names": params.get("operation_names"),
                "required_axes": params.get("required_axes") or [],
                "create_spindle_objects": bool(
                    params.get("create_spindle_objects", True)
                ),
                "dry_run": False,
                "replace_existing": bool(params.get("replace_existing", False)),
                "reload_existing": bool(params.get("reload_existing", False)),
                "confirmation": params.get("replace_confirmation", ""),
            }
        )
    except Exception as exc:
        if reload_mark is not None:
            session.UndoToMark(reload_mark, reload_mark_name)
            reload_mark = None
        safe = _safe_nx_error(exc)
        raise RuntimeError(
            "NX session-shadow machine binding failed at binding_commit "
            "(type=%s, error_code=%s)"
            % (safe["type"], safe["error_code"])
        )
    finally:
        for name, value in previous_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    if reload_mark is not None:
        try:
            session.SetUndoMarkName(
                reload_mark, "NX MCP Reloaded Session-Shadow Machine"
            )
        except Exception as exc:
            reload_finalize_warning = _safe_nx_error(exc)
    result.update(
        {
            "changed": bool(binding.get("changed")),
            "binding": binding,
            "import_readback_passed": bool(import_result.get("readback_passed")),
            "static_collision_passed": import_result.get("static_collision_passed"),
            "global_machine_library_unchanged": bool(
                import_result.get("global_machine_database_unchanged")
            ),
            "shadow_import_kept": True,
            "shadow_import_id": os.path.basename(staging),
            "reload": reload_record,
            "reload_finalize_warning": reload_finalize_warning,
            "saved": False,
        }
    )
    return result


def _configure_collision_stop_options(cam, options, params):
    material_removal = bool(params.get("material_removal", True))
    options.SimulationDisplay = cam.SimulationOptionsBuilder.SimulationDisplayMode.All
    options.AnimationAccuracy = cam.SimulationOptionsBuilder.Accuracy.Fine
    options.DisplayStationary = cam.SimulationOptionsBuilder.Stationary.Part
    options.EnableMachineCollision = True
    options.CheckLimitViolation = True
    options.CheckToolHolderIpw = True
    options.CheckToolHolderGougeCheck = True
    options.ToolPartCollision = True
    options.ToolIpwCollision = True
    options.StopOnCollision = True
    options.StopOnLimitViolation = True
    options.EnableMaterialRemoval = material_removal
    options.DisplayIpw = material_removal
    options.IpwUpdate = cam.SimulationOptionsBuilder.IpwUpdateMode.MotionBased
    options.IpwResolution = cam.SimulationOptionsBuilder.Resolution.Fine
    options.StockSetting = cam.SimulationOptionsBuilder.StockType.Automatic
    return {
        "collision_detection": True,
        "machine_collision": True,
        "limit_check": True,
        "tool_holder_check": True,
        "tool_part_collision": True,
        "tool_ipw_collision": True,
        "stop_on_collision": True,
        "stop_on_limit_violation": True,
        "stop_on_rapid_through_ipw": True,
        "rapid_through_ipw_stop_source": "stop_on_collision",
        "material_removal": material_removal,
        "ipw_resolution": "fine",
        "tool_shape": "session_customer_default",
    }


def _op_simulation_runtime_proxy(params):
    runtime_method = str(params.get("runtime_method") or "").strip()
    allowed = {
        "start_machine_simulation_with_collision_stop",
        "inspect_active_machine_simulation",
        "stop_active_machine_simulation",
    }
    if runtime_method not in allowed:
        raise ValueError("runtime_method is not an allowed simulation operation")
    runtime_params = params.get("runtime_params") or {}
    if not isinstance(runtime_params, dict):
        raise ValueError("runtime_params must be an object")
    runtime_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "dotnet_bridge",
            "bin",
            "NXMcPSimulationRuntimeV3.dll",
        )
    )
    if not os.path.isfile(runtime_path):
        raise RuntimeError(
            "NX machine-simulation runtime is not built; run dotnet_bridge/build_bridge.ps1"
        )
    request_id = "runtime-%d" % int(time.time() * 1000000.0)
    request_json = json.dumps(
        {"id": request_id, "method": runtime_method, "params": runtime_params},
        ensure_ascii=True,
    )
    response_json = NXOpen.Session.GetSession().Execute(
        runtime_path,
        "NXSimulationRuntime",
        "Handle",
        [request_json],
    )
    response = json.loads(str(response_json))
    if response.get("id") != request_id:
        raise RuntimeError("NX simulation runtime returned a mismatched request id")
    if not response.get("ok"):
        error = response.get("error") or {}
        raise RuntimeError(
            "NX simulation runtime failed (type=%s, error_code=%s): %s"
            % (
                error.get("type"),
                error.get("error_code"),
                error.get("message") or "unknown error",
            )
        )
    result = response.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("NX simulation runtime returned an invalid result")
    return result


def _op_inspect_active_machine_simulation(_params):
    return _op_simulation_runtime_proxy(
        {"runtime_method": "inspect_active_machine_simulation", "runtime_params": {}}
    )


def _op_stop_active_machine_simulation(params):
    return _op_simulation_runtime_proxy(
        {
            "runtime_method": "stop_active_machine_simulation",
            "runtime_params": {"release": bool(params.get("release", True))},
        }
    )


def _op_start_machine_simulation_with_collision_stop(params):
    operation_names = params.get("operation_names")
    program_name = params.get("program_name", "MCP_PROGRAM")
    required_axes = params.get("required_axes") or []
    strict_requirements = {
        "require_axis_limits": bool(params.get("require_axis_limits", True)),
        "require_tool_geometry": bool(params.get("require_tool_geometry", True)),
        "require_shank_geometry": bool(params.get("require_shank_geometry", True)),
        "require_holder_geometry": bool(params.get("require_holder_geometry", True)),
        "require_workpiece_geometry": bool(params.get("require_workpiece_geometry", True)),
        "require_fixture_geometry": bool(params.get("require_fixture_geometry", True)),
    }
    readiness = _machine_simulation_readiness(
        {
            "operation_names": operation_names,
            "program_name": program_name,
            "required_axes": required_axes,
            **strict_requirements
        }
    )
    if not readiness["machine_simulation_ready"]:
        raise RuntimeError(
            "Machine simulation is not ready; blockers=%s"
            % ",".join(readiness["blockers"])
        )
    selection = readiness["selection"]
    speed = int(params.get("speed", 25))
    if not 1 <= speed <= 100:
        raise ValueError("speed must be between 1 and 100")
    runtime_result = _op_simulation_runtime_proxy(
        {
            "runtime_method": "start_machine_simulation_with_collision_stop",
            "runtime_params": {
                "operation_names": list(selection["operation_names"]),
                "speed": speed,
                "play_immediately": bool(params.get("play_immediately", True)),
                "material_removal": bool(params.get("material_removal", True)),
                "show_toolpath": bool(params.get("show_toolpath", True)),
                "show_tool_trace": bool(params.get("show_tool_trace", False)),
            },
        }
    )
    runtime_result.update(
        {
            "part": _work_part().Leaf,
            "readiness_passed": True,
            "requirements": strict_requirements,
            "selection": selection,
            "machine_libref": readiness["machine"]["libref"],
            "production_nc_certified": False,
        }
    )
    return runtime_result


def _op_export_cam_clsf(params):
    cam = _cam_module()
    setup = _cam_setup()
    operations = _cam_selected_operations(setup, params.get("operation_names"))
    missing = [operation.Name for operation in operations if not operation.AskPathExists()]
    if missing:
        raise RuntimeError("CLSF export requires generated toolpaths for every operation")
    output_path = _workspace_exchange_path(
        params.get("file_name"), {".cls", ".clsf"}, must_exist=False
    )
    overwrite = bool(params.get("overwrite", False))
    if os.path.exists(output_path) and not overwrite:
        raise IOError("CLSF file already exists; set overwrite=true to replace it")
    units_name = str(params.get("units", "metric")).strip().lower()
    units = {
        "metric": cam.CAMSetup.OutputUnits.Metric,
        "inch": cam.CAMSetup.OutputUnits.Inch,
    }.get(units_name)
    if units is None:
        raise ValueError("units must be metric or inch")
    clsf_format = _cam_safe_name(
        "clsf_format", params.get("clsf_format", "CLSF_STANDARD")
    )
    setup.OutputClsf(operations, clsf_format, output_path, units)
    if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 0:
        raise RuntimeError("NX did not create a non-empty CLSF file")
    return {
        "ok": True,
        "output_file": output_path,
        "file_size": os.path.getsize(output_path),
        "operation_names": [operation.Name for operation in operations],
        "units": units_name,
        "postprocessed": False,
    }


_CAM_POST_CONFIRMATION = "I_HAVE_VERIFIED_MACHINE_KINEMATICS_AND_POST"


def _cam_require_post_authorization(params):
    enabled = os.environ.get("NX_MCP_ENABLE_POSTPROCESS", "0").strip().lower()
    if enabled not in ("1", "true", "yes", "on"):
        raise PermissionError(
            "CAM postprocessing is disabled. Set NX_MCP_ENABLE_POSTPROCESS=1 and restart the MCP server."
        )
    if params.get("confirmation") != _CAM_POST_CONFIRMATION:
        raise PermissionError(
            "CAM postprocessing requires the exact machine/post verification confirmation."
        )


def _op_postprocess_cam_program_locked(params):
    _cam_require_post_authorization(params)
    cam = _cam_module()
    setup = _cam_setup()
    operations = _cam_selected_operations(setup, params.get("operation_names"))
    if any(not operation.AskPathExists() for operation in operations):
        raise RuntimeError("postprocessing requires generated toolpaths for every operation")
    machine_type = _cam_safe_name("machine_type", params.get("machine_type"))
    output_path = _workspace_exchange_path(
        params.get("file_name"), {".h", ".nc", ".tap"}, must_exist=False
    )
    if os.path.exists(output_path) and not bool(params.get("overwrite", False)):
        raise IOError("NC output already exists; set overwrite=true to replace it")
    units_name = str(params.get("units", "metric")).strip().lower()
    units = {
        "metric": cam.CAMSetup.OutputUnits.Metric,
        "inch": cam.CAMSetup.OutputUnits.Inch,
    }.get(units_name)
    if units is None:
        raise ValueError("units must be metric or inch")
    setup.Postprocess(operations, machine_type, output_path, units)
    if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 0:
        raise RuntimeError("NX did not create a non-empty NC output file")
    return {
        "ok": True,
        "output_file": output_path,
        "file_size": os.path.getsize(output_path),
        "units": units_name,
        "production_certified": False,
        "requires_independent_machine_simulation_and_dry_run": True,
    }


def _op_execute(params):
    code = params.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("params.code must be a non-empty string")
    session = NXOpen.Session.GetSession()
    _EXEC_NS.update(
        {
            "NXOpen": NXOpen,
            "session": session,
            "theSession": session,
            "workPart": session.Parts.Work,
            "displayPart": session.Parts.Display,
        }
    )
    _EXEC_NS.pop("result", None)
    stdout, stderr = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    returned = None
    try:
        sys.stdout, sys.stderr = stdout, stderr
        try:
            returned = eval(compile(code, "<nx-mcp>", "eval"), _EXEC_NS, _EXEC_NS)
        except SyntaxError:
            exec(compile(code, "<nx-mcp>", "exec"), _EXEC_NS, _EXEC_NS)
            returned = _EXEC_NS.get("result")
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    out, err = stdout.getvalue(), stderr.getvalue()
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
    if len(err) > MAX_OUTPUT_CHARS:
        err = err[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
    return {
        "ok": True,
        "return_value": _jsonable(returned),
        "stdout": out,
        "stderr": err,
    }


_OPS = {
    "ping": _op_ping,
    "part_summary": _op_part_summary,
    "body_geometry": _op_body_geometry,
    "body_topology": _op_body_topology,
    "resolve_topology": _op_resolve_topology,
    "inspect_feature": _op_inspect_feature,
    "set_feature_expression": _op_set_feature_expression,
    "rebuild_work_part": _op_rebuild_work_part,
    "create_part": _op_create_part,
    "create_block": _op_create_block,
    "create_involute_gear": _op_create_involute_gear,
    "create_parametric_sketch": _op_create_parametric_sketch,
    "inspect_sketch": _op_inspect_sketch,
    "extrude_sketch": _op_extrude_sketch,
    "revolve_sketch": _op_revolve_sketch,
    "loft_sketches": _op_loft_sketches,
    "sweep_sketch": _op_sweep_sketch,
    "boolean_bodies": _op_boolean_bodies,
    "create_cylindrical_hole": _op_create_cylindrical_hole,
    "fillet_edges": _op_fillet_edges,
    "chamfer_edges": _op_chamfer_edges,
    "shell_body": _op_shell_body,
    "linear_pattern_feature": _op_linear_pattern_feature,
    "mirror_feature": _op_mirror_feature,
    "export_exchange": _op_export_exchange,
    "import_exchange": _op_import_exchange,
    "inspect_assembly": _op_inspect_assembly,
    "add_component": _op_add_component,
    "move_component": _op_move_component,
    "add_assembly_constraint": _op_add_assembly_constraint,
    "inspect_assembly_constraints": _op_inspect_assembly_constraints,
    "extract_face_surface": _op_extract_face_surface,
    "offset_surface": _op_offset_surface,
    "sew_sheet_bodies": _op_sew_sheet_bodies,
    "trim_sheet_body": _op_trim_sheet_body,
    "create_sheet_metal_tab": _op_create_sheet_metal_tab,
    "create_sheet_metal_flange": _op_create_sheet_metal_flange,
    "create_sheet_metal_bend": _op_create_sheet_metal_bend,
    "create_flat_pattern": _op_create_flat_pattern,
    "export_flat_pattern_dxf": _op_export_flat_pattern_dxf,
    "create_drawing_sheet": _op_create_drawing_sheet,
    "create_projected_view": _op_create_projected_view,
    "create_drafting_note": _op_create_drafting_note,
    "create_drawing_linear_dimension": _op_create_drawing_linear_dimension,
    "inspect_drawing_annotations": _op_inspect_drawing_annotations,
    "cam_capabilities": _op_cam_capabilities,
    "initialize_cam_setup": _op_initialize_cam_setup,
    "create_cam_milling_context": _op_create_cam_milling_context,
    "inspect_cam_setup": _op_inspect_cam_setup,
    "define_cam_mcs": _op_define_cam_mcs,
    "define_cam_workpiece": _op_define_cam_workpiece,
    "create_cam_mill_tool": _op_create_cam_mill_tool,
    "create_cam_operation": _op_create_cam_operation,
    "set_cam_operation_geometry": _op_set_cam_operation_geometry,
    "configure_cam_milling_operation": _op_configure_cam_milling_operation,
    "inspect_cam_operations": _op_inspect_cam_operations,
    "inspect_cam_operation_details": _op_inspect_cam_operation_details,
    "generate_cam_toolpath": _op_generate_cam_toolpath,
    "inspect_machine_simulation_readiness": _op_inspect_machine_simulation_readiness,
    "inspect_machine_source_profile": _op_inspect_machine_source_profile,
    "inspect_machine_kinematic_plan": _op_inspect_machine_kinematic_plan,
    "create_machine_build_workspace": _op_create_machine_build_workspace,
    "create_smart_machine_kit_workspace": _op_create_smart_machine_kit_workspace,
    "activate_machine_build_workspace": _op_activate_machine_build_workspace,
    "restore_machine_build_recovery_part": _op_restore_machine_build_recovery_part,
    "import_machine_component_geometry": _op_import_machine_component_geometry,
    "build_machine_kinematics_from_profile": _op_build_machine_kinematics_from_profile,
    "validate_machine_kinematics": _op_validate_machine_kinematics,
    "probe_machine_axis_motion": _op_probe_machine_axis_motion,
    "retarget_machine_junctions_from_profile": _op_retarget_machine_junctions_from_profile,
    "export_machine_kit_from_reference": _op_export_machine_kit_from_reference,
    "import_machine_kit_readback": _op_import_machine_kit_readback,
    "validate_machine_static_collisions": _op_validate_machine_static_collisions,
    "bind_machine_tool_from_library": _op_bind_machine_tool_from_library,
    "bind_isolated_machine_kit_to_cam": _op_bind_isolated_machine_kit_to_cam,
    "start_machine_simulation_with_collision_stop": _op_start_machine_simulation_with_collision_stop,
    "simulation_runtime_proxy": _op_simulation_runtime_proxy,
    "inspect_active_machine_simulation": _op_inspect_active_machine_simulation,
    "stop_active_machine_simulation": _op_stop_active_machine_simulation,
    "export_cam_clsf": _op_export_cam_clsf,
    "postprocess_cam_program_locked": _op_postprocess_cam_program_locked,
    "save_work_part": _op_save_work_part,
    "execute": _op_execute,
}


def handle(request_json):
    """NX Session.Execute entry point. Always returns one JSON string."""
    request_id = None
    try:
        message = json.loads(request_json)
        if not isinstance(message, dict):
            raise ValueError("request must be a JSON object")
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request.id must be a non-empty string")
        if not isinstance(method, str) or not method:
            raise ValueError("request.method must be a non-empty string")
        if not isinstance(params, dict):
            raise ValueError("request.params must be a JSON object")
        operation = _OPS.get(method)
        if operation is None:
            raise ValueError("unknown method: %r" % method)
        envelope = {"id": request_id, "ok": True, "result": operation(params)}
    except Exception as exc:
        envelope = {
            "id": request_id,
            "ok": False,
            "error": {
                "message": str(exc),
                "type": "%s.%s" % (type(exc).__module__, type(exc).__name__),
                "traceback": traceback.format_exc(),
            },
        }
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))

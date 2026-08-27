#!/usr/bin/env python3
"""Read-only NXOpen API introspection through the live bridge."""

from __future__ import annotations

import json

from nx_bridge_client import NXBridgeClient

CODE = r'''
import NXOpen.GeometricUtilities
import NXOpen.UF
builder = session.Parts.FileNew()
extrude_builder = None
section = None
if workPart is not None:
    extrude_builder = workPart.Features.CreateExtrudeBuilder(NXOpen.Features.Feature.Null)
    section = workPart.Sections.CreateSection(0.00095, 0.001, 0.5)
body = list(workPart.Bodies)[0] if workPart is not None and list(workPart.Bodies) else None
body_edge = list(body.GetEdges())[0] if body and list(body.GetEdges()) else None
uf_session = NXOpen.UF.UFSession.GetUFSession()
result = {
    "part_collection_candidates": [
        name for name in dir(session.Parts)
        if any(word in name.lower() for word in ("new", "open", "file"))
    ],
    "nxopen_file_new_candidates": [
        name for name in dir(NXOpen)
        if "file" in name.lower() or "template" in name.lower()
    ],
    "part_candidates": [
        name for name in dir(NXOpen.Part)
        if "unit" in name.lower() or "save" in name.lower()
    ],
    "new_display_doc": getattr(session.Parts.NewDisplay, "__doc__", None),
    "new_base_display_doc": getattr(session.Parts.NewBaseDisplay, "__doc__", None),
    "file_new_doc": getattr(session.Parts.FileNew, "__doc__", None),
    "file_new_builder_properties": [
        name for name in dir(builder) if not name.startswith("_")
    ],
    "part_units": [
        name for name in dir(NXOpen.Part.Units) if not name.startswith("_")
    ],
    "save_as_doc": getattr(session.Parts.Work.SaveAs, "__doc__", None) if session.Parts.Work else None,
    "save_doc": getattr(session.Parts.Work.Save, "__doc__", None) if session.Parts.Work else None,
    "save_components_members": [
        name for name in dir(NXOpen.BasePart.SaveComponents) if not name.startswith("_")
    ],
    "close_after_save_members": [
        name for name in dir(NXOpen.BasePart.CloseAfterSave) if not name.startswith("_")
    ],
    "curve_collection_candidates": [
        name for name in dir(workPart.Curves)
        if any(word in name.lower() for word in ("line", "arc", "spline"))
    ] if workPart is not None else [],
    "create_line_doc": getattr(workPart.Curves.CreateLine, "__doc__", None) if workPart is not None else None,
    "section_members": [name for name in dir(section) if not name.startswith("_")] if section else [],
    "add_to_section_doc": getattr(section.AddToSection, "__doc__", None) if section else None,
    "rule_factory_candidates": [
        name for name in dir(workPart.ScRuleFactory)
        if "curve" in name.lower()
    ] if workPart is not None else [],
    "curve_dumb_rule_doc": getattr(workPart.ScRuleFactory.CreateRuleCurveDumb, "__doc__", None) if workPart is not None else None,
    "extrude_members": [name for name in dir(extrude_builder) if not name.startswith("_")] if extrude_builder else [],
    "extrude_commit_doc": getattr(extrude_builder.CommitFeature, "__doc__", None) if extrude_builder else None,
    "direction_create_doc": getattr(workPart.Directions.CreateDirection, "__doc__", None) if workPart is not None else None,
    "boolean_members": [name for name in dir(extrude_builder.BooleanOperation) if not name.startswith("_")] if extrude_builder else [],
    "boolean_types": [name for name in dir(NXOpen.GeometricUtilities.BooleanOperation.BooleanType) if not name.startswith("_")],
    "limit_members": [name for name in dir(extrude_builder.Limits) if not name.startswith("_")] if extrude_builder else [],
    "start_extend_members": [name for name in dir(extrude_builder.Limits.StartExtend) if not name.startswith("_")] if extrude_builder else [],
    "end_extend_members": [name for name in dir(extrude_builder.Limits.EndExtend) if not name.startswith("_")] if extrude_builder else [],
    "section_modes": [name for name in dir(NXOpen.Section.Mode) if not name.startswith("_")],
    "update_options": [name for name in dir(NXOpen.SmartObject.UpdateOption) if not name.startswith("_")],
    "body_geometry_candidates": [
        name for name in dir(body)
        if any(word in name.lower() for word in ("bound", "face", "edge", "mass"))
    ] if body else [],
    "body_get_bounding_box_doc": getattr(body.GetBoundingBox, "__doc__", None) if body and hasattr(body, "GetBoundingBox") else None,
    "uf_bounding_candidates": [
        name for name in dir(uf_session.Modl) if "bound" in name.lower()
    ],
    "uf_ask_bounding_box_doc": getattr(uf_session.Modl.AskBoundingBox, "__doc__", None) if hasattr(uf_session.Modl, "AskBoundingBox") else None,
    "uf_ask_bounding_box_exact_doc": getattr(uf_session.Modl.AskBoundingBoxExact, "__doc__", None) if hasattr(uf_session.Modl, "AskBoundingBoxExact") else None,
    "edge_get_vertices_doc": getattr(body_edge.GetVertices, "__doc__", None) if body_edge else None,
    "edge_vertices_repr": repr(body_edge.GetVertices()) if body_edge else None,
    "vertex_members": [name for name in dir(body_edge.GetVertices()[0]) if not name.startswith("_")] if body_edge and body_edge.GetVertices() else [],
}
if extrude_builder:
    extrude_builder.Destroy()
if section:
    section.Destroy()
builder.Destroy()
'''


if __name__ == "__main__":
    response = NXBridgeClient().request("execute", {"code": CODE}, timeout=30)
    print(json.dumps(response, indent=2, ensure_ascii=False))

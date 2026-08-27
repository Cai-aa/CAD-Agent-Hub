#!/usr/bin/env python3
"""Read-only live introspection for NX sketch and constraint APIs."""

from __future__ import annotations

import argparse
import json

from nx_bridge_client import NXBridgeClient

CODE = r'''
sketches = workPart.Sketches
create_names = [name for name in dir(sketches) if "create" in name.lower()]
builder = None
builder_error = None
for method_name in ("CreateSketchInPlaceBuilder2", "CreateSketchInPlaceBuilder"):
    if hasattr(sketches, method_name):
        try:
            builder = getattr(sketches, method_name)(NXOpen.Sketch.Null)
            break
        except Exception as exc:
            builder_error = "%s: %s" % (type(exc).__name__, exc)
result = {
    "sketch_collection_create_members": create_names,
    "create_sketch_in_place_builder2_doc": getattr(sketches.CreateSketchInPlaceBuilder2, "__doc__", None) if hasattr(sketches, "CreateSketchInPlaceBuilder2") else None,
    "create_sketch_in_place_builder_doc": getattr(sketches.CreateSketchInPlaceBuilder, "__doc__", None) if hasattr(sketches, "CreateSketchInPlaceBuilder") else None,
    "builder_error": builder_error,
    "builder_members": [name for name in dir(builder) if not name.startswith("_")] if builder else [],
    "builder_origin_option": repr(builder.OriginOption) if builder else None,
    "builder_plane_option": repr(builder.PlaneOption) if builder else None,
    "builder_make_origin_associative": repr(builder.MakeOriginAssociative) if builder else None,
    "builder_project_work_part_origin": repr(builder.ProjectWorkPartOrigin) if builder else None,
    "builder_sketch_origin": repr(builder.SketchOrigin) if builder else None,
    "origin_option_members": [name for name in dir(type(builder.OriginOption)) if not name.startswith("_")] if builder else [],
    "plane_option_members": [name for name in dir(type(builder.PlaneOption)) if not name.startswith("_")] if builder else [],
    "plane_collection_create_members": [name for name in dir(workPart.Planes) if "create" in name.lower()],
    "create_plane_doc": getattr(workPart.Planes.CreatePlane, "__doc__", None),
    "sketch_members": [name for name in dir(NXOpen.Sketch) if not name.startswith("_")],
    "constraint_members": [name for name in dir(NXOpen.Sketch.Constraint) if not name.startswith("_")] if hasattr(NXOpen.Sketch, "Constraint") else [],
    "dimension_members": [name for name in dir(NXOpen.Sketch.Dimension) if not name.startswith("_")] if hasattr(NXOpen.Sketch, "Dimension") else [],
    "constraint_type_members": [name for name in dir(NXOpen.Sketch.ConstraintType) if not name.startswith("_")] if hasattr(NXOpen.Sketch, "ConstraintType") else [],
    "infer_constraint_members": [name for name in dir(NXOpen.Sketch.InferConstraintsOption) if not name.startswith("_")] if hasattr(NXOpen.Sketch, "InferConstraintsOption") else [],
    "view_reorient_members": [name for name in dir(NXOpen.Sketch.ViewReorient) if not name.startswith("_")],
    "update_level_members": [name for name in dir(NXOpen.Sketch.UpdateLevel) if not name.startswith("_")],
}
if builder:
    builder.Destroy()
'''

CREATE_CODE = r'''
plane = workPart.Planes.CreatePlane(
    NXOpen.Point3d(0.0, 0.0, 0.0),
    NXOpen.Vector3d(0.0, 0.0, 1.0),
    NXOpen.SmartObject.UpdateOption.WithinModeling,
)
builder = workPart.Sketches.CreateSketchInPlaceBuilder2(NXOpen.Sketch.Null)
builder.PlaneReference = plane
sketch = builder.Commit()
builder.Destroy()
sketch.SetName("MCP_SKETCH_API_PROBE_%d" % len(list(workPart.Sketches)))
result = {
    "sketch_name": sketch.Name,
    "journal_id": sketch.JournalIdentifier,
    "feature_journal_id": sketch.Feature.JournalIdentifier,
    "origin": [sketch.Origin.X, sketch.Origin.Y, sketch.Origin.Z],
    "orientation": repr(sketch.Orientation),
    "add_geometry_doc": getattr(sketch.AddGeometry, "__doc__", None),
    "activate_doc": getattr(sketch.Activate, "__doc__", None),
    "deactivate_doc": getattr(sketch.Deactivate, "__doc__", None),
    "view_reorient_members": [name for name in dir(NXOpen.Sketch.ViewReorient) if not name.startswith("_")],
    "update_doc": getattr(sketch.Update, "__doc__", None),
    "create_horizontal_doc": getattr(sketch.CreateHorizontalConstraint, "__doc__", None),
    "create_vertical_doc": getattr(sketch.CreateVerticalConstraint, "__doc__", None),
    "create_coincident_doc": getattr(sketch.CreateCoincidentConstraint, "__doc__", None),
    "create_dimension_doc": getattr(sketch.CreateDimension, "__doc__", None),
    "create_diameter_dimension_doc": getattr(sketch.CreateDiameterDimension, "__doc__", None),
    "constraint_geometry_doc": getattr(NXOpen.Sketch.ConstraintGeometry, "__doc__", None),
    "dimension_geometry_doc": getattr(NXOpen.Sketch.DimensionGeometry, "__doc__", None),
    "dimension_option_members": [name for name in dir(NXOpen.Sketch.DimensionOption) if not name.startswith("_")],
    "constraint_point_type_members": [name for name in dir(NXOpen.Sketch.ConstraintPointType) if not name.startswith("_")],
    "assoc_type_members": [name for name in dir(NXOpen.Sketch.AssocType) if not name.startswith("_")],
    "create_parallel_doc": getattr(sketch.CreateParallelConstraint, "__doc__", None),
    "create_perpendicular_doc": getattr(sketch.CreatePerpendicularConstraint, "__doc__", None),
    "create_equal_length_doc": getattr(sketch.CreateEqualLengthConstraint, "__doc__", None),
    "create_tangent_doc": getattr(sketch.CreateTangentConstraint, "__doc__", None),
    "expression_create_members": [name for name in dir(workPart.Expressions) if "create" in name.lower()],
    "create_expression_doc": getattr(workPart.Expressions.CreateExpression, "__doc__", None) if hasattr(workPart.Expressions, "CreateExpression") else None,
    "create_system_expression_with_units_doc": getattr(workPart.Expressions.CreateSystemExpressionWithUnits, "__doc__", None) if hasattr(workPart.Expressions, "CreateSystemExpressionWithUnits") else None,
    "unit_collection_members": [name for name in dir(workPart.UnitCollection) if not name.startswith("_")],
    "find_unit_doc": getattr(workPart.UnitCollection.FindObject, "__doc__", None) if hasattr(workPart.UnitCollection, "FindObject") else None,
    "get_all_expressions_doc": getattr(sketch.GetAllExpressions, "__doc__", None),
    "view_members": [name for name in dir(NXOpen.Sketch.View) if not name.startswith("_")],
}
'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create-test", action="store_true")
    args = parser.parse_args()
    response = NXBridgeClient().request(
        "execute", {"code": CREATE_CODE if args.create_test else CODE}, timeout=30
    )
    print(json.dumps(response, indent=2, ensure_ascii=False))

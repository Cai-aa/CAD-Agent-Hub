#!/usr/bin/env python3
"""Read-only live introspection for NX forming feature builders."""

from __future__ import annotations

import json

from nx_bridge_client import NXBridgeClient

CODE = r'''
import NXOpen.Features
import NXOpen.UF
features = workPart.Features
uf_session = NXOpen.UF.UFSession.GetUFSession()
uf_bounding = {}
uf_face_data = {}
uf_hollow = {}
for service_name in dir(uf_session):
    if service_name.startswith("_"):
        continue
    try:
        service = getattr(uf_session, service_name)
        members = [name for name in dir(service) if "bound" in name.lower()]
        if members:
            uf_bounding[service_name] = members
        face_members = [name for name in dir(service) if "facedata" in name.lower()]
        if face_members:
            uf_face_data[service_name] = face_members
        hollow_members = [name for name in dir(service) if "hollow" in name.lower()]
        if hollow_members:
            uf_hollow[service_name] = hollow_members
    except Exception:
        pass
create_members = [
    name for name in dir(features)
    if any(word in name.lower() for word in ("revolve", "sweep", "through", "loft"))
]
builders = {}
errors = {}
for key, method_name in (
    ("revolve", "CreateRevolveBuilder"),
    ("swept", "CreateSweptBuilder"),
    ("through_curves", "CreateThroughCurvesBuilder"),
):
    if hasattr(features, method_name):
        try:
            builders[key] = getattr(features, method_name)(NXOpen.Features.Feature.Null)
        except Exception as exc:
            errors[key] = "%s: %s" % (type(exc).__name__, exc)
result = {
    "feature_create_members": create_members,
    "builder_errors": errors,
    "uf_bounding": uf_bounding,
    "uf_face_data": uf_face_data,
    "uf_hollow": uf_hollow,
    "uf_create_hollow_doc": getattr(
        uf_session.ModlFeatures.CreateHollow, "__doc__", None
    ),
    "uf_ask_face_data_doc": getattr(
        uf_session.Modeling.AskFaceData, "__doc__", None
    ),
    "uf_ask_model_bounds_tag_doc": getattr(
        uf_session.Disp.AskModelBoundsTag, "__doc__", None
    ),
    "uf_compute_model_bounds_doc": getattr(
        uf_session.Disp.ComputeModelBounds, "__doc__", None
    ),
    "uf_ask_bounding_box_doc": getattr(
        uf_session.ModlGeneral.AskBoundingBox, "__doc__", None
    ),
    "uf_ask_bounding_box_exact_doc": getattr(
        uf_session.ModlGeneral.AskBoundingBoxExact, "__doc__", None
    ),
    "revolve_null_members": [
        name for name in dir(NXOpen.Features.Revolve)
        if not name.startswith("_")
    ],
    "uf_revolve_members": [
        name for name in dir(NXOpen.UF.UFSession.GetUFSession().Modl)
        if "revol" in name.lower()
    ],
    "uf_create_revolved_doc": getattr(
        NXOpen.UF.UFSession.GetUFSession().Modl.CreateRevolved, "__doc__", None
    ),
    "uf_create_revolution_doc": getattr(
        NXOpen.UF.UFSession.GetUFSession().Modl.CreateRevolution, "__doc__", None
    ),
    "uf_list_members": [
        name for name in dir(NXOpen.UF.UFSession.GetUFSession().Uf)
        if "list" in name.lower()
    ],
    "uf_feature_signs": [
        name for name in dir(NXOpen.UF.Modl.FeatureSigns)
        if not name.startswith("_")
    ],
    "uf_sweep_trim_members": [
        name for name in dir(NXOpen.UF.Modl.SweepTrimObject())
        if not name.startswith("_")
    ],
    "through_body_preference_types": [
        name for name in dir(NXOpen.Features.ThroughCurvesBuilder.BodyPreferenceTypes)
        if not name.startswith("_")
    ],
}
for key, builder in builders.items():
    result[key + "_members"] = [name for name in dir(builder) if not name.startswith("_")]
    for member in ("Axis", "Limits", "Section", "Spine", "Sections", "SectionsList", "GuideList", "BooleanOperation"):
        if hasattr(builder, member):
            value = getattr(builder, member)
            result[key + "_" + member.lower() + "_members"] = [
                name for name in dir(value) if not name.startswith("_")
            ]
    result[key + "_commit_doc"] = getattr(builder.CommitFeature, "__doc__", None)
    result[key + "_commit_object_doc"] = getattr(builder.Commit, "__doc__", None)
    result[key + "_type"] = str(type(builder))
for builder in builders.values():
    builder.Destroy()
'''


if __name__ == "__main__":
    response = NXBridgeClient().request("execute", {"code": CODE}, timeout=30)
    print(json.dumps(response, indent=2, ensure_ascii=False))

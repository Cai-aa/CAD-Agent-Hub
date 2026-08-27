#!/usr/bin/env python3
"""Read-only live introspection for the NX sheet-metal tab builder."""

from __future__ import annotations

import json

from nx_bridge_client import NXBridgeClient

CODE = r'''
import NXOpen.Features.SheetMetal
builder = workPart.Features.SheetmetalManager.CreateTabFeatureBuilder(NXOpen.Features.Feature.Null)
sketch = list(workPart.Sketches)[0] if list(workPart.Sketches) else None
result = {
    "members": [name for name in dir(builder) if not name.startswith("_")],
    "sketch_type": str(type(sketch)) if sketch else None,
    "sketch_feature_type": str(type(sketch.Feature)) if sketch else None,
    "sketch_feature_members": [name for name in dir(sketch.Feature) if not name.startswith("_")] if sketch else [],
}
for key, getter in (
    ("application_context", lambda: str(builder.GetApplicationContext())),
    ("thickness_rhs", lambda: builder.Thickness.RightHandSide),
    ("is_secondary", lambda: builder.IsSecondary),
    ("thickness_side", lambda: str(builder.ThicknessSide)),
    ("material_side", lambda: str(builder.MaterialSide)),
    ("validate_initial", lambda: int(builder.ValidateBuilderData())),
    ("preference_members", lambda: [name for name in dir(workPart.Preferences.SheetMetalPreferences) if not name.startswith("_")]),
    ("preference_thickness", lambda: workPart.Preferences.SheetMetalPreferences.GetMaterialThickness().RightHandSide),
):
    try:
        result[key] = getter()
    except Exception as exc:
        result[key + "_error"] = "%s: %s" % (type(exc).__name__, exc)
builder.Destroy()
'''


if __name__ == "__main__":
    response = NXBridgeClient().request("execute", {"code": CODE}, timeout=60)
    print(json.dumps(response, indent=2, ensure_ascii=False))

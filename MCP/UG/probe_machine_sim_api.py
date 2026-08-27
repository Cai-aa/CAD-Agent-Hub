#!/usr/bin/env python3
"""Read-only NXOpen reflection for machine-simulation development."""

from __future__ import annotations

import json

from nx_bridge_client import NXBridgeClient


CODE = r'''
import NXOpen.CAM
import NXOpen.SIM

work = session.Parts.Work
result = {"part": getattr(work, "Leaf", None)}
result["session_execute_doc"] = getattr(session.Execute, "__doc__", None)
if work is not None:
    kinematic = work.KinematicConfigurator
    result["kinematic_methods"] = [
        name for name in dir(kinematic)
        if any(word in name.lower() for word in ("axis", "limit", "position", "simulation"))
    ]
    result["kinematic_docs"] = {
        name: getattr(getattr(kinematic, name), "__doc__", None)
        for name in result["kinematic_methods"]
        if hasattr(kinematic, name)
    }
    result["create_panel_doc"] = getattr(
        kinematic.CreateIsvControlPanelBuilder, "__doc__", None
    )
    axis_records = []
    for axis_name in list(kinematic.GetAxisNames()):
        axis = None
        parent = None
        junction = None
        found_shape = None
        builder_error = None
        for finder in ("FindAxis", "GetAxis"):
            if hasattr(kinematic, finder):
                try:
                    found = getattr(kinematic, finder)(axis_name)
                    found_shape = {
                        "type": type(found).__name__,
                        "length": len(found) if isinstance(found, tuple) else None,
                        "item_types": [type(item).__name__ for item in found] if isinstance(found, tuple) else [],
                    }
                    if isinstance(found, tuple):
                        axis, parent, junction = found
                    else:
                        axis = found
                    break
                except Exception:
                    pass
        axis_builder = None
        try:
            if axis is not None:
                try:
                    axis_builder = kinematic.CreateAxisBuilder(parent, junction, axis)
                except Exception as exc:
                    builder_error = {"type": type(exc).__name__, "message": str(exc)[:300]}
            axis_builder_members = [
                name for name in dir(axis_builder)
                if any(word in name.lower() for word in ("limit", "position", "range", "value", "name", "type"))
            ] if axis_builder is not None else []
            axis_builder_values = {}
            for member in axis_builder_members:
                try:
                    value = getattr(axis_builder, member)
                    if not callable(value):
                        axis_builder_values[member] = str(value)
                except Exception:
                    pass
        finally:
            if axis_builder is not None:
                axis_builder.Destroy()
        axis_records.append({
            "name": str(axis_name),
            "object_type": type(axis).__name__ if axis is not None else None,
            "members": [
                name for name in dir(axis)
                if any(word in name.lower() for word in ("limit", "position", "range", "value"))
            ] if axis is not None else [],
            "builder_members": axis_builder_members,
            "builder_values": axis_builder_values,
            "found_shape": found_shape,
            "builder_error": builder_error,
        })
    result["axes"] = axis_records

result["panel_type_members"] = [
    name for name in dir(NXOpen.SIM.IsvControlPanelBuilder)
    if name.startswith("Add") or any(word in name.lower() for word in ("play", "stop", "status", "collision", "limit", "time", "move", "reset", "position"))
]
result["panel_type_docs"] = {
    name: getattr(getattr(NXOpen.SIM.IsvControlPanelBuilder, name), "__doc__", None)
    for name in result["panel_type_members"]
    if hasattr(NXOpen.SIM.IsvControlPanelBuilder, name)
}
'''


def main() -> None:
    response = NXBridgeClient().request("execute", {"code": CODE}, timeout=30)
    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Open the workspace CAM sandbox as an additional display and reflect tool APIs."""

from __future__ import annotations

import json
from pathlib import Path

from nx_bridge_client import NXBridgeClient


def main() -> None:
    path = Path(__file__).resolve().parent / "workspace" / "nx_mcp_cam_sandbox.prt"
    code = r'''
import NXOpen.CAM
target = %s
current = session.Parts.Work
if not current or str(getattr(current, "FullPath", "")).lower() != target.lower():
    session.Parts.SetAllowMultipleDisplayedParts(True)
    opened, load_status = session.Parts.OpenActiveDisplay(target, NXOpen.DisplayPartOption.AllowAdditional)
    try:
        if int(load_status.NumberUnloadedParts):
            raise RuntimeError("NX reported unloaded parts")
    finally:
        load_status.Dispose()
work = session.Parts.Work
if not session.IsCamSessionInitialized():
    session.CreateCamSession()
setup = work.CAMSetup
root = setup.GetRoot(NXOpen.CAM.CAMSetup.View.MachineTool)
tools = [item for item in root.GetMembers() if type(item).__name__.lower().find("tool") >= 0]
tool = tools[0]
builder = setup.CAMGroupCollection.CreateMillToolBuilder(tool)
try:
    holder = builder.HolderSectionBuilder
    shank = builder.ShankSectionBuilder
    result = {
        "part": work.Leaf,
        "tool": tool.Name,
        "holder_count": int(holder.NumberOfSections),
        "shank_count": int(shank.NumberOfSections),
        "holder_docs": {
            name: getattr(getattr(holder, name), "__doc__", None)
            for name in ("AddByUpperDiameter", "GetSection", "GetAllParameters", "Delete")
        },
        "shank_diameter": float(builder.TlShankDiaBuilder.Value),
    }
finally:
    builder.Destroy()
''' % json.dumps(str(path))
    response = NXBridgeClient().request("execute", {"code": code}, timeout=60)
    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

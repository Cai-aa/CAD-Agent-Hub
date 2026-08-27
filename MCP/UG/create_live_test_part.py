#!/usr/bin/env python3
"""Create a workspace-scoped live NX test part through the repaired bridge."""

from __future__ import annotations

import json
from pathlib import Path

from nx_bridge_client import NXBridgeClient

ROOT = Path(__file__).resolve().parent
PART_PATH = (ROOT / "artifacts" / "nx_mcp_e2e.prt").resolve()


def main() -> int:
    client = NXBridgeClient()
    code = "\n".join(
        [
            "import os",
            "path = %r" % str(PART_PATH),
            "os.makedirs(os.path.dirname(path), exist_ok=True)",
            "part = session.Parts.NewDisplay(path, NXOpen.Part.Units.Millimeters)",
            "workPart = session.Parts.Work",
            "displayPart = session.Parts.Display",
            "result = {'leaf': part.Leaf, 'full_path': part.FullPath, 'tag': int(part.Tag)}",
        ]
    )
    created = client.request("execute", {"code": code}, timeout=60)
    block = client.request(
        "create_block",
        {
            "length": 80.0,
            "width": 50.0,
            "height": 20.0,
            "origin": [0.0, 0.0, 0.0],
        },
        timeout=60,
    )
    summary = client.request("part_summary", {"max_features": 20}, timeout=30)
    print(
        json.dumps(
            {"part_path": str(PART_PATH), "created": created, "block": block, "summary": summary},
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

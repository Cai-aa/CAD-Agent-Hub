#!/usr/bin/env python3
"""Persist the workspace-scoped live NX test part and verify the artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nx_bridge_client import NXBridgeClient

ROOT = Path(__file__).resolve().parent
PART_PATH = (ROOT / "artifacts" / "nx_mcp_e2e.prt").resolve()


def main() -> int:
    code = "\n".join(
        [
            "path = %r" % str(PART_PATH),
            "status = workPart.Save(",
            "  NXOpen.BasePart.SaveComponents.TrueValue,",
            "  NXOpen.BasePart.CloseAfterSave.FalseValue,",
            ")",
            "result = {",
            "  'status_type': type(status).__name__,",
            "  'number_unsaved_parts': getattr(status, 'NumberUnsavedParts', None),",
            "  'path': workPart.FullPath,",
            "}",
            "status.Dispose()",
        ]
    )
    response = NXBridgeClient().request("execute", {"code": code}, timeout=120)
    if not PART_PATH.is_file():
        raise RuntimeError("NX reported SaveAs completion but the .prt file is missing")
    digest = hashlib.sha256(PART_PATH.read_bytes()).hexdigest()
    print(
        json.dumps(
            {
                "save": response,
                "artifact": {
                    "path": str(PART_PATH),
                    "size": PART_PATH.stat().st_size,
                    "sha256": digest,
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

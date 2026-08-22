from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path

import pythoncom
import win32com.client


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from catia_mcp import modeling  # noqa: E402


def main() -> int:
    workspace = PROJECT_ROOT / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    part_path = workspace / f"issue_fixes_{stamp}.CATPart"
    capture_path = workspace / f"issue_fixes_{stamp}.bmp"

    pythoncom.CoInitialize()
    try:
        app = win32com.client.GetActiveObject("CATIA.Application")
        modeling.create_part(app, f"IssueFixes{stamp}")
        modeling.create_sketch(
            app,
            "BaseSketch",
            "xy",
            [{"kind": "rectangle", "origin": [0, 0], "width": 60, "height": 40}],
        )
        modeling.add_pad(app, "BaseSketch", 20, "BlockPad")
        modeling.create_sketch(
            app,
            "PocketSketch",
            "xy",
            [{"kind": "circle", "center": [30, 20], "radius": 10}],
        )
        pocket = modeling.add_pocket(
            app,
            "PocketSketch",
            10,
            "ReversePocket",
            reverse=True,
        )

        expected_after_mm3 = 48_000.0 - math.pi * 10.0**2 * 10.0
        if (
            pocket["direction_orientation"] not in (0, 1)
            or pocket["direction_orientation"]
            == pocket["direction_orientation_before"]
        ):
            raise RuntimeError(f"pocket direction was not reversed: {pocket}")
        if pocket["material_removed"] is not True:
            raise RuntimeError(f"pocket did not remove material: {pocket}")
        if not math.isclose(
            pocket["volume_after_mm3"], expected_after_mm3, rel_tol=0.0, abs_tol=0.01
        ):
            raise RuntimeError(
                f"unexpected volume {pocket['volume_after_mm3']}; expected {expected_after_mm3}"
            )

        saved = modeling.save_active(app, part_path)
        capture = modeling.capture_view(app, capture_path)
        result = {
            "status": "passed",
            "pocket": pocket,
            "expected_volume_after_mm3": expected_after_mm3,
            "saved": saved,
            "capture": capture,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())

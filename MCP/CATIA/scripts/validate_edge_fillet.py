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
    part_path = workspace / f"edge_fillet_validation_{stamp}.CATPart"
    capture_path = workspace / f"edge_fillet_validation_{stamp}.bmp"

    pythoncom.CoInitialize()
    try:
        app = win32com.client.GetActiveObject("CATIA.Application")
        modeling.create_part(app, f"EdgeFilletValidation{stamp}")
        modeling.create_sketch(
            app,
            "BaseSketch",
            "xy",
            [{"kind": "rectangle", "origin": [0, 0], "width": 60, "height": 40}],
        )
        modeling.add_pad(app, "BaseSketch", 20, "BlockPad")

        before = modeling.inspect_edges(
            app,
            source_feature_name="BlockPad",
            limit=100,
        )
        if before["matched_edge_count"] < 1:
            raise RuntimeError(f"no block edges were returned: {before}")
        vertical_edges = [
            edge
            for edge in before["edges"]
            if math.isclose(
                float(edge.get("measurement", {}).get("length", -1.0)),
                20.0,
                rel_tol=0.0,
                abs_tol=1e-9,
            )
        ]
        if not vertical_edges:
            raise RuntimeError(f"no 20 mm vertical block edge was returned: {before}")
        edge_index = int(vertical_edges[0]["index"])

        fillet = modeling.add_edge_fillet(
            app,
            [edge_index],
            5.0,
            "MCP_EdgeFillet",
            source_feature_name="BlockPad",
            propagation="tangency",
        )
        validation = fillet["validation"]
        required_checks = (
            validation["part_update_succeeded"],
            validation["radius_matches_request"],
            validation["propagation_matches_request"],
            validation["objects_to_fillet_matches_request"],
            validation["body_volume_changed"],
        )
        if not all(value is True for value in required_checks):
            raise RuntimeError(f"edge fillet validation did not pass: {fillet}")

        inspection = modeling.inspect_active(app, include_parameters=False)
        body_shape_names = [
            str(shape.get("name", ""))
            for body in inspection.get("bodies", [])
            for shape in body.get("shapes", [])
        ]
        if "MCP_EdgeFillet" not in body_shape_names:
            raise RuntimeError(f"native fillet is missing from the feature tree: {inspection}")

        saved = modeling.save_active(app, part_path)
        capture = modeling.capture_view(app, capture_path)
        result = {
            "status": "passed",
            "edge_snapshot": before,
            "fillet": fillet,
            "feature_tree_contains_fillet": True,
            "saved": saved,
            "capture": capture,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())

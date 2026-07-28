from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from catia_mcp.executor import CatiaExecutor


def attempt(summary: dict[str, Any], name: str, function: Callable[[], Any]) -> Any:
    try:
        result = function()
        summary[name] = {"ok": True, "result": result}
        return result
    except Exception as exc:
        summary[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe native CATIA material, case and mesh APIs")
    parser.add_argument("part", type=Path)
    parser.add_argument("analysis", type=Path)
    args = parser.parse_args()
    executor = CatiaExecutor()
    summary: dict[str, Any] = {}
    original_name = None
    opened_names: list[str] = []
    try:
        connection = executor.connect(start_if_missing=False)
        summary["connection"] = connection
        original_name = connection.get("active_document")

        part_result = attempt(summary, "open_part", lambda: executor.open_document("probe-open-part", str(args.part)))
        if part_result:
            opened_names.append(part_result["document"])
            attempt(
                summary,
                "apply_steel",
                lambda: executor.apply_material(
                    "probe-apply-steel",
                    r"G:\Program Files\Dassault Systemes\B33\win_b64\startup\materials\Catalog.CATMaterial",
                    "Metal",
                    "Steel",
                    1,
                ),
            )
            attempt(summary, "save_part", lambda: executor.save_active("probe-save-part", None))
            attempt(
                summary, "close_part",
                lambda: executor.close_active("probe-close-part", True, False, part_result["document"]),
            )
            opened_names.clear()

        analysis_result = attempt(
            summary,
            "open_analysis",
            lambda: executor.open_document("probe-open-analysis", str(args.analysis)),
        )
        if analysis_result:
            opened_names.append(analysis_result["document"])
            attempt(
                summary,
                "add_static_case",
                lambda: executor.add_analysis_case("probe-add-static", "Static Case", 1, "Static Case MCP"),
            )
            attempt(
                summary,
                "add_octree_mesh_part",
                lambda: executor.add_analysis_mesh_part(
                    "probe-add-mesh", mesh_type="MSHPartOctree3D", model_index=1, name="Octree Mesh MCP"
                ),
            )
            attempt(summary, "inspect_analysis", lambda: executor.inspect_analysis("probe-inspect-analysis", 200))
            attempt(summary, "save_analysis", lambda: executor.save_active("probe-save-analysis", None))
            attempt(
                summary, "close_analysis",
                lambda: executor.close_active("probe-close-analysis", True, False, analysis_result["document"]),
            )
            opened_names.clear()
    finally:
        for name in opened_names:
            try:
                executor.session.run(
                    f"probe-cleanup-activate-{name}",
                    lambda app, document_name=name: (app.Documents.Item(document_name).Activate() or {"activated": document_name}),
                )
                executor.close_active(f"probe-cleanup-close-{name}", False, True, name)
            except Exception:
                pass
        if original_name:
            try:
                executor.session.run(
                    "probe-restore-original",
                    lambda app: (app.Documents.Item(original_name).Activate() or {"activated": original_name}),
                )
            except Exception:
                pass
        executor.session.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from catia_mcp.config import Settings
from catia_mcp.executor import CatiaExecutor


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a bounded native CATIA smoke model")
    parser.add_argument("--analysis", action="store_true", help="also create/import a CATAnalysis document")
    args = parser.parse_args()
    settings = Settings.from_env()
    workspace = settings.workspace.resolve(strict=False)
    workspace.mkdir(parents=True, exist_ok=True)
    executor = CatiaExecutor(settings)
    summary = {}
    original_name = None
    part_name = None
    analysis_name = None
    try:
        summary["connection"] = executor.connect(start_if_missing=False)
        documents = executor.list_documents("smoke-list-before")
        if documents["documents"]:
            original_name = documents["documents"][0]["name"]
            for row in documents["documents"]:
                if row["name"] == summary["connection"].get("active_document"):
                    original_name = row["name"]
                    break
        suffix = ""
        if (workspace / "catia_mcp_live_smoke.CATPart").exists():
            suffix = "_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        part_path = workspace / f"catia_mcp_live_smoke{suffix}.CATPart"
        summary["model"] = executor.create_parametric_part(
            "smoke-create-block",
            "block",
            {"length_mm": 40.0, "width_mm": 20.0, "height_mm": 10.0},
            "CATIA_MCP_LiveSmoke",
            str(part_path),
        )
        part_name = summary["model"]["saved"]["document"]
        summary["inspection"] = executor.inspect_active("smoke-inspect-part", False, 100)
        if args.analysis:
            analysis_path = workspace / f"catia_mcp_live_smoke{suffix}.CATAnalysis"
            summary["analysis"] = executor.create_analysis_document(
                "smoke-create-analysis",
                part_name,
                None,
                "CATIA_MCP_LiveSmoke_Analysis",
                str(analysis_path),
            )
            analysis_name = summary["analysis"]["document"]
            summary["analysis_inspection"] = executor.inspect_analysis("smoke-inspect-analysis", 100)
            executor.close_active(
                "smoke-close-analysis", save=True, discard_unsaved=False,
                expected_document_name=summary["analysis"]["saved"]["document"],
            )
        if part_name:
            executor.session.run("smoke-activate-part", lambda app: (app.Documents.Item(part_name).Activate() or {"activated": part_name}))
            executor.close_active(
                "smoke-close-part", save=True, discard_unsaved=False,
                expected_document_name=part_name,
            )
        if original_name:
            def _reactivate_original(app: Any) -> dict[str, Any]:
                # On older releases such as V5R21 the originally open document can
                # leave the Documents collection while the smoke model is built.
                # Verify it is still open before reactivating it.
                for index in range(1, int(app.Documents.Count) + 1):
                    if str(app.Documents.Item(index).Name) == original_name:
                        app.Documents.Item(original_name).Activate()
                        return {"activated": original_name}
                return {"skipped": original_name, "reason": "document no longer open"}

            summary["reactivate_original"] = executor.session.run(
                "smoke-reactivate-original", _reactivate_original
            )
        summary["artifacts"] = [str(path) for path in workspace.glob("catia_mcp_live_smoke*")]
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        executor.session.close()


if __name__ == "__main__":
    main()

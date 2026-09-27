"""Build and solve a complete static analysis chain on the live CATIA release.

This script reproduces, through pure Automation, the end-to-end static
analysis chain that was validated on CATIA V5R21 B21:

1. create a 100 x 20 x 5 mm plate CATPart and apply the "Aluminium" material
   from the installation material catalog in copy mode,
2. create a CATAnalysis document importing the plate,
3. add a Static Case (CATGPSStressAnalysis_template) and a "StaticSet" solution,
4. build the material chain: MaterialSet + SAMUserMaterial (with the catalog
   material applied through CATMatManagerVBExt) and a SAM3DSolid property whose
   SAMAnalysisMaterialPtr references the user material,
5. add a single-face SAMClamp restraint and a single-face SAMDistributedForce
   load, both bound through named "Selection_RSur:(...)" references,
6. add an Octree tetrahedron mesh part bound to the main body, set SizeValue,
7. run ComputeMeshOnly and the full Compute,
8. create a "Mesh_Deformed" result image and build the native HTML report,
9. save the solved CATAnalysis document into the workspace.

All artifacts are written under workspace/analysis_validation_<stamp>/.
The documents created by this script are closed at the end unless
--keep-open is given. Attach-only: CATIA must already be running, and the
CATIA_MCP_ALLOW_LEGACY / CATIA_MCP_ENV_NAME environment used by the MCP
registration should also be set for this script.

Exit code 0 means the chain completed (mesh compute and full solve returned).
Note that `Compute` returning is not by itself proof of physical validity;
inspect the saved document, the deformed-mesh image and the HTML report.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pythoncom
import win32com.client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from catia_mcp import modeling, simulation  # noqa: E402
from catia_mcp.compatibility import environment_report  # noqa: E402
from catia_mcp.config import Settings  # noqa: E402


def find_material_catalog(settings: Settings) -> Path:
    report = environment_report(settings)
    selected = report.get("selected_installation") or {}
    install_path = selected.get("install_path")
    if not install_path:
        raise RuntimeError("no CATIA installation was detected; run catia_health_check first")
    candidates = sorted((Path(install_path) / "startup" / "materials").glob("*.CATMaterial"))
    preferred = [path for path in candidates if path.name.casefold() == "catalog.catmaterial"]
    if not preferred and not candidates:
        raise RuntimeError(f"no material catalog found under {install_path}")
    return (preferred or candidates)[0]


def face_reference(part_document, part, index: int):
    """Create a named part reference to the n-th planar face of the live solid."""
    selection = part_document.Selection
    selection.Clear()
    try:
        selection.Search("Topology.CGMFace,all")
        count = int(selection.Count2)
        if index > count:
            raise RuntimeError(f"requested face index {index} exceeds the {count} faces found")
        item = selection.Item2(index)
        display_name = str(item.Reference.DisplayName)
    finally:
        selection.Clear()
    return part.CreateReferenceFromName(display_name)


def close_documents(app, names: list[str], summary: dict) -> None:
    previous_alerts = None
    try:
        previous_alerts = bool(app.DisplayFileAlerts)
    except Exception:
        pass
    try:
        for name in reversed(names):
            for index in range(1, int(app.Documents.Count) + 1):
                if str(app.Documents.Item(index).Name) != name:
                    continue
                try:
                    app.DisplayFileAlerts = False
                    app.Documents.Item(index).Activate()
                    app.Documents.Item(index).Close()
                    summary.setdefault("closed", []).append(name)
                except Exception as exc:
                    summary.setdefault("close_errors", []).append(f"{name}: {type(exc).__name__}: {exc}")
                break
    finally:
        if previous_alerts is not None:
            try:
                app.DisplayFileAlerts = previous_alerts
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and solve a static analysis chain on live CATIA")
    parser.add_argument("--keep-open", action="store_true", help="keep created documents open for inspection")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    workspace = PROJECT_ROOT / "workspace" / f"analysis_validation_{stamp}"
    workspace.mkdir(parents=True, exist_ok=True)
    summary: dict = {"workspace": str(workspace)}
    created: list[str] = []
    app = None

    pythoncom.CoInitialize()
    try:
        app = win32com.client.GetActiveObject("CATIA.Application")
        summary["attached"] = str(app.Caption)
        catalog = find_material_catalog(Settings.from_env())
        summary["material_catalog"] = str(catalog)

        # 1. plate + material (copy mode so the material data travels with the part)
        modeling.create_part(app, f"AnalysisPlate_{stamp}")
        modeling.create_sketch(
            app,
            "Base",
            "xy",
            [{"kind": "rectangle", "origin": [0, 0], "width": 100, "height": 20}],
            "PartBody",
        )
        modeling.add_pad(app, "Base", 5, "Pad1", "PartBody")
        modeling.apply_material(app, catalog, "Metal", "Aluminium", 0)
        part_path = workspace / f"analysis_plate_{stamp}.CATPart"
        modeling.save_active(app, part_path)
        part_document = app.ActiveDocument
        created.append(str(part_document.Name))
        summary["part"] = str(part_path)
        part = part_document.Part
        product = part_document.Product

        # 2. analysis document + case + solution
        simulation.create_analysis_document(app, str(part_document.Name), None, f"Analysis_{stamp}")
        analysis_document = app.ActiveDocument
        created.append(str(analysis_document.Name))
        manager = analysis_document.Analysis
        model = manager.AnalysisModels.Item(1)
        case_info = simulation.add_case(app, "Static Case", 1, None)
        simulation.add_solution(app, "StaticSet", 1, 1)
        case = model.AnalysisCases.Item(model.AnalysisCases.Count)
        summary["case"] = case_info["case"]

        # 3. material chain: user material + 3D property with material pointer
        material_set = model.AnalysisSets.ItemByType("MaterialSet")
        user_material = material_set.AnalysisEntities.Add("SAMUserMaterial")
        catalog_document = app.Documents.Open(str(catalog))
        try:
            material = catalog_document.Families.Item("Metal").Materials.Item("Aluminium")
            manager.GetItem("CATMatManagerVBExt").ApplyMaterialOnUserMaterial(user_material, material, 0)
        finally:
            catalog_document.Close()
        property_set = model.AnalysisSets.ItemByType("PropertySet")
        solid_property = property_set.AnalysisEntities.Add("SAM3DSolid")
        solid_property.AddSupportFromProduct(product, part.CreateReferenceFromObject(part.MainBody))
        solid_property.SetReference(
            "SAMAnalysisMaterialPtr", "", 1, 1, 1, manager.CreateReferenceFromObject(user_material)
        )
        summary["material"] = "SAMUserMaterial applied; SAM3DSolid material pointer wired"

        # 4. single-face restraint and load
        restraint_set = case.AnalysisSets.ItemByType("RestraintSet")
        clamp = restraint_set.AnalysisEntities.Add("SAMClamp")
        clamp.AddSupportFromProduct(product, face_reference(part_document, part, 1))
        load_set = case.AnalysisSets.ItemByType("LoadSet")
        force = load_set.AnalysisEntities.Add("SAMDistributedForce")
        force.AddSupportFromProduct(product, face_reference(part_document, part, 3))
        summary["restraint"] = f"SAMClamp on face 1 (supports: {int(clamp.AnalysisSupports.Count)})"
        summary["load"] = f"SAMDistributedForce on face 3 (supports: {int(force.AnalysisSupports.Count)})"

        # 5. Octree mesh bound to the main body
        mesh_part = model.MeshManager.AnalysisMeshParts.Add("MSHPartOctree3D")
        mesh_part.AddSupportFromReference(product, part.CreateReferenceFromObject(part.MainBody))
        mesh_part.SetGlobalSpecification("SizeValue", "4.0 mm")

        # 6. compute
        previous_alerts = bool(app.DisplayFileAlerts)
        app.DisplayFileAlerts = False
        try:
            case.ComputeMeshOnly()
            summary["mesh_compute"] = "ok"
            case.Compute()
            summary["solve"] = "ok"
        finally:
            app.DisplayFileAlerts = previous_alerts

        # 7. result image + native HTML report
        try:
            image = simulation.create_result_image(app, "Mesh_Deformed", model_index=1, case_index=1)
            summary["result_image"] = str(image["image"])
        except Exception as exc:
            summary["result_image_error"] = f"{type(exc).__name__}: {exc}"
        report_dir = workspace / "report"
        post = model.PostManager
        post.AddExistingCaseForReport(case)
        file_system = app.FileSystem
        report_folder = (
            file_system.GetFolder(str(report_dir))
            if file_system.FolderExists(str(report_dir))
            else file_system.CreateFolder(str(report_dir))
        )
        post.BuildReport(report_folder, f"Analysis report {stamp}", True)
        summary["report"] = str(report_dir / "index.html")

        # 8. save the solved analysis document
        saved = modeling.save_active(app, workspace / f"analysis_{stamp}.CATAnalysis")
        summary["analysis"] = saved["full_name"]
        summary["status"] = "passed"
    except Exception as exc:
        summary["status"] = "failed"
        summary["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if app is not None and not args.keep_open:
            close_documents(app, created, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        pythoncom.CoUninitialize()
    return 0 if summary.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

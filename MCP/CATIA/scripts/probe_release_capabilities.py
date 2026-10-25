"""Probe the installed CATIA release for live Automation capabilities.

Attaches to a running CATIA session (or starts one explicitly with
--start-if-missing), creates isolated probe documents inside the configured
workspace, and records which capabilities used by this MCP server are
available on this machine's release. Pre-existing user documents are never
closed or modified; probe documents are saved into a probe folder and closed
at the end unless --keep-open is given.

The machine-readable report is written as JSON and a summary is printed on
stdout. Exit codes: 0 = probe completed, 1 = CATIA attachment failed,
2 = unexpected failure while writing the report.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from catia_mcp import simulation
from catia_mcp.config import Settings
from catia_mcp.executor import CatiaExecutor


_PROBE_COUNTER = itertools.count(1)

# Factory methods consumed by the server's typed tools. Presence is checked
# with getattr so that a missing method is reported instead of crashing.
FACTORY_METHODS: dict[str, tuple[str, ...]] = {
    "shape_factory": (
        "AddNewPad",
        "AddNewPocket",
        "AddNewEdgeFilletWithConstantRadius",
        "AddNewCloseSurface",
        "AddNewThickSurface",
    ),
    "hybrid_shape_factory": (
        "AddNewPointCoord",
        "AddNewSpline",
        "AddNewPlaneOffset",
        "AddNewConnect",
        "AddNewLoft",
        "AddNewFill",
        "AddNewJoin",
        "AddNewHealing",
        "AddNewBoundaryOfSurface",
    ),
}

# Native Analysis case templates used by the typed transition/case tools.
ANALYSIS_TRANSITIONS: tuple[tuple[str, str], ...] = (
    ("static", "CATGPSStressAnalysis_template"),
    ("modal", "CATGPSModalAnalysis_template"),
    ("free_modal", "CATGPSFreeModalAnalysis_template"),
)

# Candidate late types for the solution set; the first accepted one is
# reported. The V5R21 automation documentation uses "StaticSet".
SOLUTION_CANDIDATES: tuple[str, ...] = (
    "StaticSet",
    "ModalSet",
    "FrequencySet",
)

# Supplemental export formats that were not yet verified on this release.
SUPPLEMENTAL_EXPORTS: tuple[tuple[str, str], ...] = (
    (".step", "STEP long-name alias"),
    (".model", "V4 model"),
    (".pdf", "PDF"),
    (".dxf", "DXF"),
    (".dwg", "DWG"),
)


def rid(label: str) -> str:
    return f"probe-{label}-{next(_PROBE_COUNTER)}"


def section(report: dict[str, Any], name: str) -> dict[str, Any]:
    value = report.setdefault(name, {})
    assert isinstance(value, dict)
    return value


def run_step(container: dict[str, Any], key: str, fn: Callable[[], Any]) -> Any | None:
    """Run one probe step and record a compact status row; never raises."""
    try:
        value = fn()
    except Exception as exc:
        container[key] = {"probe_status": "error", "error": f"{type(exc).__name__}: {exc}"}
        return None
    if isinstance(value, dict):
        row: dict[str, Any] = {"probe_status": "ok"}
        row.update(value)
        container[key] = row
    else:
        container[key] = {"probe_status": "ok", "value": value}
    return value


def skip_step(container: dict[str, Any], key: str, reason: str) -> None:
    container[key] = {"probe_status": "skipped", "reason": reason}


def is_ok(container: dict[str, Any], key: str) -> bool:
    row = container.get(key)
    return isinstance(row, dict) and row.get("probe_status") == "ok"


def activate_document(executor: CatiaExecutor, name: str, label: str) -> None:
    def action(app: Any) -> dict[str, Any]:
        for index in range(1, int(app.Documents.Count) + 1):
            document = app.Documents.Item(index)
            if str(document.Name) == name:
                document.Activate()
                return {"activated": name}
        raise RuntimeError(f"document no longer open: {name}")

    executor.session.run(rid(label), action)


def _section_points(prefix: str, z_mm: float, chord_mm: float, width_mm: float) -> list[dict[str, Any]]:
    points = []
    for index in range(12):
        angle = 2.0 * math.pi * index / 12.0
        x = 0.5 * chord_mm * math.cos(angle)
        y = 0.5 * width_mm * math.sin(angle)
        points.append({"name": f"{prefix}_P{index + 1:02d}", "coordinates": [x, y, z_mm]})
    return points


def probe_environment(executor: CatiaExecutor, report: dict[str, Any]) -> None:
    health = executor.health_check()
    environment = health["environment"]
    selected = environment.get("selected_installation") or {}
    report["environment"] = {
        "server_version": health["server_version"],
        "minimum_supported_release_index": environment.get("minimum_supported_release_index"),
        "release_policy": environment.get("release_policy"),
        "selected_installation": selected,
        "installations": environment.get("installations"),
        "analysis_typelib": environment.get("analysis_typelib"),
        "solver_policy": health["solver_policy"],
    }


def probe_application(executor: CatiaExecutor, report: dict[str, Any]) -> None:
    application = section(report, "application")

    def action(app: Any) -> dict[str, Any]:
        info: dict[str, Any] = {}
        for attr in ("Version", "SystemConfiguration", "OperatingSystem"):
            try:
                value = getattr(app, attr)
                info[f"attr_{attr}"] = value if not callable(value) else "<callable>"
            except Exception as exc:
                info[f"attr_{attr}"] = f"<unavailable: {type(exc).__name__}>"
        # Best-effort inventory of ExportData format names this release accepts.
        try:
            formats = app.FileFormats
            count = int(formats.Count)
            names: list[str] = []
            for index in range(1, min(count, 400) + 1):
                item = formats.Item(index)
                for attr in ("Name", "Extension", "DisplayName", "Description"):
                    try:
                        candidate = getattr(item, attr)
                    except Exception:
                        continue
                    if isinstance(candidate, str) and candidate:
                        names.append(candidate)
                        break
                else:
                    names.append(f"<item {index}>")
            info["file_formats"] = {"count": count, "names": names}
        except Exception as exc:
            info["file_formats"] = {"error": f"{type(exc).__name__}: {exc}"}
        return info

    run_step(application, "application_surface", lambda: executor.session.run(rid("application"), action, mutating=False))


def probe_factories(executor: CatiaExecutor, report: dict[str, Any], part_document: str) -> None:
    factories = section(report, "factories")

    def action(app: Any) -> dict[str, Any]:
        document = app.Documents.Item(part_document)
        part = document.Part
        result: dict[str, Any] = {}
        attribute = {"shape_factory": "ShapeFactory", "hybrid_shape_factory": "HybridShapeFactory"}
        for factory_name, methods in FACTORY_METHODS.items():
            try:
                factory = getattr(part, attribute[factory_name])
            except Exception as exc:
                result[factory_name] = {"factory": f"<unavailable: {type(exc).__name__}>"}
                continue
            result[factory_name] = {
                method: bool(callable(getattr(factory, method, None))) for method in methods
            }
        return result

    run_step(factories, "methods", lambda: executor.session.run(rid("factories"), action, mutating=False))


def probe_modeling_and_fillet(
    executor: CatiaExecutor,
    report: dict[str, Any],
    state: dict[str, Any],
) -> None:
    modeling = section(report, "modeling")
    fillet = section(report, "fillet")

    part = run_step(
        modeling,
        "create_part",
        lambda: executor.create_part(rid("create-part"), state["probe_title"]),
    )
    if part is None:
        return
    state["part_document"] = part["document"]

    run_step(
        modeling,
        "create_sketch",
        lambda: executor.create_sketch(
            rid("create-sketch"),
            "ProbeSketch",
            "xy",
            [{"kind": "rectangle", "origin": [0, 0], "width": 60, "height": 40}],
            "PartBody",
        ),
    )
    if not is_ok(modeling, "create_sketch"):
        return

    run_step(
        modeling,
        "add_pad",
        lambda: executor.add_pad(rid("add-pad"), "ProbeSketch", 20, "BlockPad", "PartBody"),
    )
    if not is_ok(modeling, "add_pad"):
        return

    edges = run_step(
        fillet,
        "inspect_edges",
        lambda: executor.inspect_edges(rid("inspect-edges"), "PartBody", "BlockPad", 100),
    )
    if edges is None or not edges.get("matched_edge_count"):
        skip_step(fillet, "add_edge_fillet", "edge inspection returned no matchable edges")
        return

    vertical = [
        edge
        for edge in edges.get("edges", [])
        if math.isclose(
            float(edge.get("measurement", {}).get("length", -1.0)),
            20.0,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    ]
    if not vertical:
        skip_step(fillet, "add_edge_fillet", "no 20 mm vertical block edge found in inspection result")
        return
    state["vertical_edge_index"] = int(vertical[0]["index"])

    run_step(
        fillet,
        "add_edge_fillet",
        lambda: executor.add_edge_fillet(
            rid("add-edge-fillet"),
            [state["vertical_edge_index"]],
            5.0,
            "ProbeFillet",
            "PartBody",
            "BlockPad",
            "tangency",
        ),
    )


def probe_gsd_chain(executor: CatiaExecutor, report: dict[str, Any], state: dict[str, Any]) -> None:
    gsd = section(report, "gsd")

    run_step(
        gsd,
        "geometrical_set_wireframe",
        lambda: executor.create_geometrical_set(rid("gsd-set-wire"), "ProbeWireframe"),
    )
    run_step(
        gsd,
        "geometrical_set_surfaces",
        lambda: executor.create_geometrical_set(rid("gsd-set-surf"), "ProbeSurfaces"),
    )
    if not (is_ok(gsd, "geometrical_set_wireframe") and is_ok(gsd, "geometrical_set_surfaces")):
        skip_step(gsd, "section_chain", "geometrical sets were not created")
        return

    section_specs = (("S1", 0.0, 40.0, 12.0), ("S2", 25.0, 34.0, 9.0), ("S3", 50.0, 28.0, 6.0))
    for prefix, z_mm, chord_mm, width_mm in section_specs:
        points = _section_points(prefix, z_mm, chord_mm, width_mm)
        run_step(
            gsd,
            f"points_{prefix}",
            lambda p=points: executor.create_3d_points(rid(f"gsd-points-{p[0]['name'][:2]}"), p, "ProbeWireframe"),
        )
        if not is_ok(gsd, f"points_{prefix}"):
            skip_step(gsd, f"spline_{prefix}", f"points_{prefix} failed")
            continue
        point_names = [record["name"] for record in points]
        run_step(
            gsd,
            f"spline_{prefix}",
            lambda names=point_names, nm=f"{prefix}_ClosedSpline": executor.create_spline(
                rid(f"gsd-spline-{nm[:2]}"), nm, names, True, None, "ProbeWireframe"
            ),
        )

    run_step(
        gsd,
        "offset_plane_25",
        lambda: executor.create_offset_plane(rid("gsd-plane-25"), "Probe_Plane_25", "xy", 25.0, False, "ProbeWireframe"),
    )

    if all(is_ok(gsd, f"spline_{prefix}") for prefix in ("S1", "S2", "S3")):
        run_step(
            gsd,
            "guide_te",
            lambda: executor.create_spline(
                rid("gsd-guide-te"), "Guide_TE", ["S1_P01", "S2_P01", "S3_P01"], False, None, "ProbeWireframe"
            ),
        )
        run_step(
            gsd,
            "guide_le",
            lambda: executor.create_spline(
                rid("gsd-guide-le"), "Guide_LE", ["S1_P07", "S2_P07", "S3_P07"], False, None, "ProbeWireframe"
            ),
        )
        run_step(
            gsd,
            "connect",
            lambda: executor.create_connect_curve(
                rid("gsd-connect"),
                name="Probe_Connect",
                curve1_name="Guide_TE",
                point1_name="S3_P01",
                curve2_name="Guide_LE",
                point2_name="S3_P07",
                continuity1="g1",
                continuity2="g1",
                tension1=1.0,
                tension2=1.0,
                orientation1=1,
                orientation2=1,
                trim=False,
                geometrical_set="ProbeWireframe",
            ),
        )
        run_step(
            gsd,
            "loft",
            lambda: executor.create_loft(
                rid("gsd-loft"),
                name="Probe_Loft",
                section_names=["S1_ClosedSpline", "S2_ClosedSpline", "S3_ClosedSpline"],
                guide_names=["Guide_TE", "Guide_LE"],
                closing_point_names=["S1_P01", "S2_P01", "S3_P01"],
                section_orientations=[1, 1, 1],
                coupling="ratio",
                context="surface",
                start_tangent_name=None,
                end_tangent_name=None,
                smooth_angle_deg=0.5,
                smooth_deviation_mm=0.001,
                geometrical_set="ProbeSurfaces",
            ),
        )
    else:
        skip_step(gsd, "guide_te", "section splines were not all created")
        skip_step(gsd, "guide_le", "section splines were not all created")
        skip_step(gsd, "connect", "section splines were not all created")
        skip_step(gsd, "loft", "section splines were not all created")

    for prefix, z_mm in (("S1", 0.0), ("S3", 50.0)):
        run_step(
            gsd,
            f"fill_{prefix}",
            lambda nm=f"{prefix}_ClosedSpline", key=prefix: executor.create_fill(
                rid(f"gsd-fill-{key}"),
                name=f"Probe_Fill_{key}",
                boundary_names=[nm],
                support_names=None,
                continuities=["g0"],
                constraints=None,
                geometrical_set="ProbeSurfaces",
            ),
        )

    if is_ok(gsd, "loft"):
        run_step(
            gsd,
            "boundary",
            lambda: executor.create_boundary(rid("gsd-boundary"), "Probe_Boundary", "Probe_Loft", "ProbeWireframe"),
        )
    else:
        skip_step(gsd, "boundary", "loft was not created")

    join_inputs = [
        name
        for name, key in (("Probe_Loft", "loft"), ("Probe_Fill_S1", "fill_S1"), ("Probe_Fill_S3", "fill_S3"))
        if is_ok(gsd, key)
    ]
    if len(join_inputs) >= 2:
        run_step(
            gsd,
            "join",
            lambda: executor.join_surfaces(
                rid("gsd-join"),
                name="Probe_ClosedShell",
                element_names=join_inputs,
                tolerance_mm=0.1,
                angular_tolerance_deg=0.5,
                connex=False,
                manifold=False,
                simplify=False,
                geometrical_set="ProbeSurfaces",
            ),
        )
    else:
        skip_step(gsd, "join", "fewer than two joinable surfaces were created")

    if is_ok(gsd, "join"):
        run_step(
            gsd,
            "healing",
            lambda: executor.heal_surfaces(
                rid("gsd-heal"),
                name="Probe_HealedShell",
                body_names=["Probe_ClosedShell"],
                continuity="g1",
                distance_objective_mm=0.001,
                merging_distance_mm=0.001,
                tangency_angle_deg=0.5,
                sharpness_angle_deg=0.5,
                geometrical_set="ProbeSurfaces",
            ),
        )
    else:
        skip_step(gsd, "healing", "join was not created")

    close_target = "Probe_HealedShell" if is_ok(gsd, "healing") else ("Probe_ClosedShell" if is_ok(gsd, "join") else None)
    if close_target:
        run_step(
            gsd,
            "close_surface",
            lambda: executor.close_surface(rid("gsd-close"), "Probe_Solid", close_target, "PartBody"),
        )
    else:
        skip_step(gsd, "close_surface", "no joined/healed shell available")

    thick_target = "Probe_Fill_S1" if is_ok(gsd, "fill_S1") else ("Probe_Loft" if is_ok(gsd, "loft") else None)
    if thick_target:
        run_step(
            gsd,
            "thick_surface",
            lambda: executor.thick_surface(
                rid("gsd-thick"),
                name="Probe_Thick",
                surface_name=thick_target,
                top_offset_mm=1.0,
                bottom_offset_mm=0.0,
                reverse_direction=False,
                body_name="PartBody",
            ),
        )
    else:
        skip_step(gsd, "thick_surface", "no standalone surface available for thickening")

    quality_elements = [
        name
        for name, key in (
            ("Probe_Loft", "loft"),
            ("Probe_Fill_S1", "fill_S1"),
            ("Probe_Fill_S3", "fill_S3"),
            ("Probe_ClosedShell", "join"),
            ("Probe_HealedShell", "healing"),
        )
        if is_ok(gsd, key)
    ]
    if quality_elements:
        run_step(
            gsd,
            "quality_check",
            lambda: executor.check_surface_quality(
                rid("gsd-quality"),
                quality_elements,
                [["Probe_Fill_S1", "Probe_Loft"]] if {"Probe_Fill_S1", "Probe_Loft"} <= set(quality_elements) else None,
            ),
        )
    else:
        skip_step(gsd, "quality_check", "no surface features available for the quality probe")


def support_search_candidates(executor: CatiaExecutor, part_document: str) -> list[str]:
    """Search expressions for binding Analysis supports, most specific first.

    The documented form is "Name=<pattern>,all": ",sel" restricts the search
    to the current selection and returns nothing when nothing was added first.
    The body name is read live because localized releases do not name the main
    body "PartBody".
    """
    candidates: list[str] = []
    try:
        info = executor.session.run(
            rid("analysis-body-name"),
            lambda app: {"body_name": str(app.Documents.Item(part_document).Part.MainBody.Name)},
        )
        body_name = str(info.get("body_name") or "")
        if body_name:
            candidates.append(f"Name={body_name},all")
    except Exception:
        pass
    candidates.extend(["Name=PartBody,all", "Name=*,all"])
    return candidates


def locate_material_catalogs(report: dict[str, Any]) -> list[Path]:
    install = (report.get("environment", {}).get("selected_installation") or {}).get("install_path")
    if not install:
        return []
    directory = Path(install) / "startup" / "materials"
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.CATMaterial"))


def probe_materials(executor: CatiaExecutor, report: dict[str, Any], state: dict[str, Any]) -> None:
    materials = section(report, "materials")
    catalogs = locate_material_catalogs(report)
    materials["catalogs_found"] = [str(path) for path in catalogs]
    if not catalogs:
        skip_step(materials, "list", "no .CATMaterial catalog found under the selected installation")
        return
    catalog = catalogs[0]
    listing = run_step(
        materials,
        "list",
        lambda: executor.list_materials(rid("materials-list"), str(catalog), None, 50),
    )
    if listing is None:
        return
    selected_family = None
    selected_material = None
    for family in listing.get("families", []):
        if family.get("materials"):
            selected_family = family["name"]
            selected_material = family["materials"][0]
            break
    materials["selected"] = {"catalog": str(catalog), "family": selected_family, "material": selected_material}
    if not (selected_family and selected_material):
        skip_step(materials, "apply", "no material found in the first catalog")
        return
    if state.get("part_document"):
        try:
            activate_document(executor, state["part_document"], "activate-part-materials")
        except Exception as exc:
            skip_step(materials, "apply", f"could not activate probe part: {exc}")
            return
    run_step(
        materials,
        "apply",
        lambda: executor.apply_material(rid("materials-apply"), str(catalog), selected_family, selected_material, 1),
    )


def probe_analysis(
    executor: CatiaExecutor,
    report: dict[str, Any],
    state: dict[str, Any],
    probe_dir: Path,
    with_compute: bool,
) -> None:
    analysis = section(report, "analysis")
    part_document = state.get("part_document")
    if not part_document:
        skip_step(analysis, "document", "probe part was not created")
        return

    analysis_path = probe_dir / f"{state['probe_title']}.CATAnalysis"
    document = run_step(
        analysis,
        "document",
        lambda: executor.create_analysis_document(
            rid("analysis-document"), part_document, None, f"{state['probe_title']}_Analysis", str(analysis_path)
        ),
    )
    if document is None:
        return
    state["analysis_document"] = document["document"]
    if isinstance(document.get("saved"), dict) and document["saved"].get("document"):
        state["analysis_document"] = str(document["saved"]["document"])

    run_step(analysis, "inspect_initial", lambda: executor.inspect_analysis(rid("analysis-inspect"), 200))

    for label, template in ANALYSIS_TRANSITIONS:
        run_step(
            analysis,
            f"transition_{label}",
            lambda t=template, l=label: executor.run_analysis_transition(rid(f"analysis-transition-{l}"), t, 1),
        )

    run_step(
        analysis,
        "add_case_static",
        lambda: executor.add_analysis_case(rid("analysis-case-static"), "Static Case", 1, None),
    )

    solution_added = False
    for candidate in SOLUTION_CANDIDATES:
        result = run_step(
            analysis,
            f"solution_{candidate.replace(' ', '_')}",
            lambda c=candidate: executor.add_analysis_solution(rid("analysis-solution"), c, 1, 1),
        )
        if result is not None:
            solution_added = True
            analysis["solution_accepted"] = candidate
            break
    if not solution_added:
        analysis["solution_accepted"] = None

    run_step(
        analysis,
        "add_set_load",
        lambda: executor.add_analysis_set(
            rid("analysis-set-load"),
            set_type="LoadSet",
            set_kind="in",
            model_index=1,
            case_index=1,
            scope="case",
            name=None,
        ),
    )
    run_step(
        analysis,
        "add_set_restraint",
        lambda: executor.add_analysis_set(
            rid("analysis-set-restraint"),
            set_type="RestraintSet",
            set_kind="in",
            model_index=1,
            case_index=1,
            scope="case",
            name=None,
        ),
    )
    if is_ok(analysis, "add_set_restraint"):
        run_step(
            analysis,
            "add_entity_clamp",
            lambda: executor.add_analysis_entity(
                rid("analysis-entity-clamp"),
                entity_type="SAMClamp",
                model_index=1,
                case_index=1,
                scope="case",
                set_type="RestraintSet",
                set_index=None,
                name=None,
            ),
        )
    else:
        skip_step(analysis, "add_entity_clamp", "RestraintSet was not created")
    if is_ok(analysis, "add_set_load"):
        run_step(
            analysis,
            "add_entity_moment",
            lambda: executor.add_analysis_entity(
                rid("analysis-entity-moment"),
                entity_type="SAMMoment",
                model_index=1,
                case_index=1,
                scope="case",
                set_type="LoadSet",
                set_index=None,
                name=None,
            ),
        )
    else:
        skip_step(analysis, "add_entity_moment", "LoadSet was not created")

    run_step(
        analysis,
        "add_mesh_part",
        lambda: executor.add_analysis_mesh_part(rid("analysis-mesh"), mesh_type="MSHPartOctree3D", model_index=1, name=None),
    )
    if is_ok(analysis, "add_mesh_part"):
        attempts: list[dict[str, Any]] = []
        accepted_query: str | None = None
        for candidate in support_search_candidates(executor, part_document):
            try:
                executor.bind_analysis_mesh_support(
                    rid("analysis-bind"),
                    source_document_name=part_document,
                    search_query=candidate,
                    selection_index=1,
                    model_index=1,
                    mesh_part_index=1,
                )
                attempts.append({"query": candidate, "probe_status": "ok"})
                accepted_query = candidate
                break
            except Exception as exc:
                attempts.append(
                    {"query": candidate, "probe_status": "error", "error": f"{type(exc).__name__}: {exc}"}
                )
        analysis["bind_attempts"] = attempts
        analysis["bind_accepted_query"] = accepted_query
        analysis["bind_mesh_support"] = {
            "probe_status": "ok" if accepted_query else "error",
            "accepted_query": accepted_query,
            "error": None if accepted_query else "no candidate search expression returned a usable support",
        }
        run_step(
            analysis,
            "mesh_specification",
            lambda: executor.set_analysis_mesh_specification(
                rid("analysis-mesh-spec"),
                specification_name="SizeValue",
                value="5.0 mm",
                model_index=1,
                mesh_part_index=1,
                update=True,
            ),
        )
    else:
        skip_step(analysis, "mesh_specification", "mesh part was not created")
        analysis["bind_accepted_query"] = None

    if with_compute:
        if analysis.get("bind_accepted_query"):

            def compute_mesh() -> dict[str, Any]:
                def action(app: Any) -> dict[str, Any]:
                    previous = True
                    try:
                        previous = bool(app.DisplayFileAlerts)
                    except Exception:
                        pass
                    try:
                        app.DisplayFileAlerts = False
                        result = simulation.compute_case(app, model_index=1, case_index=1, mesh_only=True)
                        result["display_file_alerts_suppressed"] = True
                        return result
                    finally:
                        app.DisplayFileAlerts = previous

                return executor.session.run(rid("analysis-compute-mesh"), action)

            run_step(analysis, "compute_mesh_only", compute_mesh)
        else:
            skip_step(analysis, "compute_mesh_only", "no mesh support was bound; mesh compute would be meaningless")
    else:
        skip_step(analysis, "compute_mesh_only", "disabled (enable with --with-compute)")


def probe_assembly(executor: CatiaExecutor, report: dict[str, Any], state: dict[str, Any], probe_dir: Path) -> None:
    assembly = section(report, "assembly")
    part_path = state.get("part_saved_path")
    if not part_path:
        skip_step(assembly, "create_product", "probe part was not saved, cannot be inserted")
        return

    product = run_step(
        assembly,
        "create_product",
        lambda: executor.create_product(rid("assembly-product"), f"{state['probe_title']}_Product"),
    )
    if product is None:
        return
    state["product_document"] = product["document"]

    run_step(
        assembly,
        "add_components",
        lambda: executor.add_components(rid("assembly-components"), [part_path]),
    )
    run_step(
        assembly,
        "inspect",
        lambda: executor.inspect_active(rid("assembly-inspect"), False, 100),
    )
    product_path = probe_dir / f"{state['probe_title']}_Product.CATProduct"
    run_step(assembly, "save", lambda: executor.save_active(rid("assembly-save"), str(product_path)))


def probe_exports(executor: CatiaExecutor, report: dict[str, Any], state: dict[str, Any], probe_dir: Path) -> None:
    exports = section(report, "exports")
    part_document = state.get("part_document")
    if not part_document:
        skip_step(exports, "formats", "probe part was not created")
        return
    try:
        activate_document(executor, part_document, "activate-part-exports")
    except Exception as exc:
        skip_step(exports, "formats", f"could not activate probe part: {exc}")
        return
    export_dir = probe_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    for extension, note in SUPPLEMENTAL_EXPORTS:
        target = export_dir / f"{state['probe_title']}{extension}"
        run_step(
            exports,
            extension.lstrip("."),
            lambda t=target, n=note: {
                **executor.export_active(rid(f"export-{n}"), str(t), None, "error", False),
                "note": n,
            },
        )


def cleanup(
    executor: CatiaExecutor,
    report: dict[str, Any],
    state: dict[str, Any],
    keep_open: bool,
) -> None:
    cleanup_section = section(report, "cleanup")
    if keep_open:
        cleanup_section["documents"] = {"probe_status": "skipped", "reason": "--keep-open set"}
        return
    prefix = str(state.get("probe_title", ""))
    known = {
        str(state.get("product_document") or ""),
        str(state.get("analysis_document") or ""),
        str(state.get("part_document") or ""),
    }

    def list_probe_documents(app: Any) -> dict[str, Any]:
        names = []
        for index in range(1, int(app.Documents.Count) + 1):
            name = str(app.Documents.Item(index).Name)
            if (prefix and name.startswith(prefix)) or name in known:
                names.append(name)
        return {"documents": names}

    def activate(app: Any, target: str) -> dict[str, Any]:
        for index in range(1, int(app.Documents.Count) + 1):
            document = app.Documents.Item(index)
            if str(document.Name) == target:
                document.Activate()
                return {"activated": target}
        return {"skipped": target, "reason": "document no longer open"}

    results: dict[str, Any] = {}
    try:
        listed = executor.session.run(rid("cleanup-list"), list_probe_documents)
        remaining = [str(item) for item in listed.get("documents", [])]
    except Exception as exc:
        cleanup_section["documents"] = {"probe_status": "error", "error": f"{type(exc).__name__}: {exc}"}
        remaining = []

    # Close assemblies first: on V5R21 a part referenced by an open product
    # cannot be closed before its assembly (the close is silently ignored),
    # and closing the assembly cascades to the referenced part.
    for suffix in (".catproduct", ".catanalysis", ".catpart"):
        for name in [item for item in remaining if item.casefold().endswith(suffix)]:
            try:
                activation = executor.session.run(
                    rid("cleanup-activate"), lambda app, t=name: activate(app, t)
                )
            except Exception as exc:
                results[name] = {"probe_status": "error", "error": f"{type(exc).__name__}: {exc}"}
                continue
            if activation.get("skipped"):
                results[name] = {"probe_status": "skipped", "reason": "document disappeared before cleanup"}
                continue
            try:
                executor.close_active(
                    rid("cleanup-close"), save=True, discard_unsaved=False, expected_document_name=name
                )
                results[name] = {"probe_status": "ok", "closed": True, "saved_before_close": True}
            except Exception as first_exc:
                try:
                    executor.close_active(
                        rid("cleanup-discard"), save=False, discard_unsaved=True, expected_document_name=name
                    )
                    results[name] = {
                        "probe_status": "ok",
                        "closed": True,
                        "saved_before_close": False,
                        "first_attempt": f"{type(first_exc).__name__}: {first_exc}",
                    }
                except Exception as exc:
                    results[name] = {"probe_status": "error", "error": f"{type(exc).__name__}: {exc}"}
    cleanup_section["documents"] = results

    try:
        cleanup_section["leftover_probe_documents"] = executor.session.run(
            rid("cleanup-verify"), list_probe_documents
        )
    except Exception as exc:
        cleanup_section["leftover_probe_documents"] = {
            "probe_status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }

    original = state.get("original_active_document")
    if original:

        def reactivate(app: Any) -> dict[str, Any]:
            for index in range(1, int(app.Documents.Count) + 1):
                document = app.Documents.Item(index)
                if str(document.Name) == original:
                    document.Activate()
                    return {"activated": original}
            return {"skipped": original, "reason": "document no longer open"}

        try:
            cleanup_section["reactivate_original"] = executor.session.run(rid("cleanup-reactivate"), reactivate)
        except Exception as exc:
            cleanup_section["reactivate_original"] = {"error": f"{type(exc).__name__}: {exc}"}


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    counts = {"ok": 0, "error": 0, "skipped": 0}
    failures: list[str] = []

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, dict):
            return
        status = node.get("probe_status")
        if status in counts:
            counts[status] += 1
            if status == "error":
                failures.append(f"{path}: {node.get('error')}")
            return
        for key, value in node.items():
            walk(value, f"{path}.{key}" if path else key)

    walk(report, "")
    return {"counts": counts, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the installed CATIA release for live Automation capabilities")
    parser.add_argument("--start-if-missing", action="store_true", help="launch CATIA if no session is running")
    parser.add_argument("--keep-open", action="store_true", help="leave probe documents open for manual inspection")
    parser.add_argument("--with-compute", action="store_true", help="include the mesh-only compute probe")
    args = parser.parse_args()

    settings = Settings.from_env()
    workspace = settings.workspace.resolve(strict=False)
    workspace.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    probe_dir = workspace / f"probe_release_{stamp}"
    probe_dir.mkdir(parents=True, exist_ok=True)

    executor = CatiaExecutor(settings)
    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "probe_directory": str(probe_dir),
        "release_probe_version": 1,
    }
    state: dict[str, Any] = {
        "probe_title": f"ReleaseProbe_{stamp}",
        "probe_dir": str(probe_dir),
    }
    exit_code = 0
    try:
        probe_environment(executor, report)
        try:
            connection = executor.connect(start_if_missing=args.start_if_missing)
            report["connection"] = connection
        except Exception as exc:
            report["connection"] = {"probe_status": "error", "error": f"{type(exc).__name__}: {exc}"}
            exit_code = 1
            raise SystemExit

        try:
            documents = executor.list_documents(rid("list-before"))
            state["original_active_document"] = connection.get("active_document")
            report["documents_before"] = documents
        except Exception as exc:
            report["documents_before"] = {"probe_status": "error", "error": f"{type(exc).__name__}: {exc}"}

        probe_application(executor, report)

        probe_modeling_and_fillet(executor, report, state)
        part_document = state.get("part_document")
        if part_document:
            probe_factories(executor, report, part_document)

        if state.get("part_document"):
            part_path = probe_dir / f"{state['probe_title']}.CATPart"
            saved = run_step(
                section(report, "modeling"),
                "save_part",
                lambda: executor.save_active(rid("save-part"), str(part_path)),
            )
            if saved is not None:
                state["part_saved_path"] = str(part_path)
        else:
            skip_step(section(report, "modeling"), "save_part", "probe part was not created")

        probe_gsd_chain(executor, report, state)
        if state.get("part_document") and is_ok(section(report, "gsd"), "quality_check"):
            run_step(
                section(report, "gsd"),
                "save_after_gsd",
                lambda: executor.save_active(rid("save-after-gsd"), None),
            )

        probe_materials(executor, report, state)
        if state.get("part_saved_path"):
            run_step(
                section(report, "modeling"),
                "save_final_part",
                lambda: executor.save_active(rid("save-final-part"), None),
            )

        probe_analysis(executor, report, state, probe_dir, args.with_compute)
        probe_assembly(executor, report, state, probe_dir)
        probe_exports(executor, report, state, probe_dir)
    except SystemExit:
        pass
    except Exception as exc:  # pragma: no cover - safety net
        report["unexpected_error"] = f"{type(exc).__name__}: {exc}"
        report["unexpected_traceback"] = traceback.format_exc()
        exit_code = 2
    finally:
        try:
            cleanup(executor, report, state, args.keep_open)
        except Exception as exc:
            section(report, "cleanup")["error"] = f"{type(exc).__name__}: {exc}"
        report["summary"] = summarize(report)
        report_path = probe_dir / f"probe_release_{stamp}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        executor.session.close()

    print(json.dumps({"report_path": str(report_path), "summary": report["summary"]}, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

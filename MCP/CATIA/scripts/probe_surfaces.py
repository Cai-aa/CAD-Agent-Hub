from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from catia_mcp.executor import CatiaExecutor


def _available_output(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate a probe output beside {path}")


def _section_points(prefix: str, z_mm: float, chord_mm: float, width_mm: float) -> list[dict]:
    points = []
    for index in range(12):
        angle = 2.0 * math.pi * index / 12.0
        x = 0.5 * chord_mm * math.cos(angle)
        y = 0.5 * width_mm * math.sin(angle)
        points.append(
            {
                "name": f"{prefix}_P{index + 1:02d}",
                "coordinates": [x, y, z_mm],
            }
        )
    return points


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a native GSD loft with the typed surface MCP layer")
    parser.add_argument("--start-if-missing", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    executor = CatiaExecutor()
    created_document = None
    results: dict[str, object] = {}
    try:
        results["connect"] = executor.connect(start_if_missing=args.start_if_missing)
        results["create_part"] = executor.create_part("surface-probe-create", "Surface_API_Probe")
        created_document = results["create_part"]["document"]
        results["capabilities"] = executor.surface_capabilities("surface-probe-capabilities")
        results["wireframe"] = executor.create_geometrical_set(
            "surface-probe-wireframe", "Probe Wireframe"
        )
        results["surfaces"] = executor.create_geometrical_set(
            "surface-probe-surfaces", "Probe Surfaces"
        )

        section_specs = (
            ("S1", 0.0, 40.0, 12.0),
            ("S2", 25.0, 34.0, 9.0),
            ("S3", 50.0, 28.0, 6.0),
        )
        section_names = []
        closing_names = []
        for prefix, z_mm, chord_mm, width_mm in section_specs:
            point_records = _section_points(prefix, z_mm, chord_mm, width_mm)
            results[f"points_{prefix}"] = executor.create_3d_points(
                f"surface-probe-points-{prefix}",
                point_records,
                "Probe Wireframe",
            )
            point_names = [record["name"] for record in point_records]
            spline_name = f"{prefix}_ClosedSpline"
            results[f"spline_{prefix}"] = executor.create_spline(
                f"surface-probe-spline-{prefix}",
                spline_name,
                point_names,
                True,
                None,
                "Probe Wireframe",
            )
            section_names.append(spline_name)
            closing_names.append(point_names[0])

        results["plane_25"] = executor.create_offset_plane(
            "surface-probe-plane-25",
            "Probe_Plane_25",
            "xy",
            25.0,
            False,
            "Probe Wireframe",
        )
        results["plane_50"] = executor.create_offset_plane(
            "surface-probe-plane-50",
            "Probe_Plane_50",
            "xy",
            50.0,
            False,
            "Probe Wireframe",
        )
        results["guide_te"] = executor.create_spline(
            "surface-probe-guide-te",
            "Guide_TE",
            ["S1_P01", "S2_P01", "S3_P01"],
            False,
            None,
            "Probe Wireframe",
        )
        results["guide_le"] = executor.create_spline(
            "surface-probe-guide-le",
            "Guide_LE",
            ["S1_P07", "S2_P07", "S3_P07"],
            False,
            None,
            "Probe Wireframe",
        )
        results["loft"] = executor.create_loft(
            "surface-probe-loft",
            name="Probe_Loft",
            section_names=section_names,
            guide_names=["Guide_TE", "Guide_LE"],
            closing_point_names=closing_names,
            section_orientations=[1, 1, 1],
            coupling="ratio",
            context="surface",
            start_tangent_name=None,
            end_tangent_name=None,
            smooth_angle_deg=0.5,
            smooth_deviation_mm=0.001,
            geometrical_set="Probe Surfaces",
        )
        results["fill_root"] = executor.create_fill(
            "surface-probe-fill-root",
            name="Probe_Fill_Root",
            boundary_names=["S1_ClosedSpline"],
            support_names=None,
            continuities=["g0"],
            constraints=None,
            geometrical_set="Probe Surfaces",
        )
        results["fill_tip"] = executor.create_fill(
            "surface-probe-fill-tip",
            name="Probe_Fill_Tip",
            boundary_names=["S3_ClosedSpline"],
            support_names=None,
            continuities=["g0"],
            constraints=None,
            geometrical_set="Probe Surfaces",
        )
        results["pre_join_quality"] = executor.check_surface_quality(
            "surface-probe-pre-join-quality",
            ["Probe_Loft", "Probe_Fill_Root", "Probe_Fill_Tip"],
            [["Probe_Fill_Root", "Probe_Loft"], ["Probe_Fill_Tip", "Probe_Loft"]],
        )
        results["boundary"] = executor.create_boundary(
            "surface-probe-boundary",
            "Probe_Boundary",
            "Probe_Loft",
            "Probe Wireframe",
        )
        results["quality"] = executor.check_surface_quality(
            "surface-probe-quality",
            ["Probe_Loft", "Probe_Fill_Root", "Probe_Fill_Tip", "Probe_Boundary"],
            [["Probe_Fill_Root", "Probe_Loft"], ["Probe_Fill_Tip", "Probe_Loft"]],
        )

        output = args.output or (executor.settings.workspace / "Surface_API_Probe.CATPart")
        output = _available_output(output.resolve(strict=False))
        results["save_before_join"] = executor.save_active("surface-probe-save-before-join", str(output))
        created_document = output.name
        results["output"] = str(output)

        join_ok = False
        try:
            results["join"] = executor.join_surfaces(
                "surface-probe-join",
                name="Probe_ClosedShell",
                element_names=["Probe_Loft", "Probe_Fill_Root", "Probe_Fill_Tip"],
                tolerance_mm=0.1,
                angular_tolerance_deg=0.5,
                connex=False,
                manifold=False,
                simplify=False,
                geometrical_set="Probe Surfaces",
            )
            join_ok = True
        except Exception as exc:
            results["join_error"] = f"{type(exc).__name__}: {exc}"
        if join_ok:
            close_target = "Probe_ClosedShell"
            try:
                results["healing"] = executor.heal_surfaces(
                    "surface-probe-healing",
                    name="Probe_HealedShell",
                    body_names=["Probe_ClosedShell"],
                    continuity="g1",
                    distance_objective_mm=0.001,
                    merging_distance_mm=0.001,
                    tangency_angle_deg=0.5,
                    sharpness_angle_deg=0.5,
                    geometrical_set="Probe Surfaces",
                )
                close_target = "Probe_HealedShell"
            except Exception as exc:
                results["healing_error"] = f"{type(exc).__name__}: {exc}"
            try:
                results["close_surface"] = executor.close_surface(
                    "surface-probe-close-surface",
                    "Probe_Solid",
                    close_target,
                    "PartBody",
                )
            except Exception as exc:
                results["close_surface_error"] = f"{type(exc).__name__}: {exc}"
        if join_ok:
            results["save_after_join"] = executor.save_active("surface-probe-save-after-join")
        print(json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        if created_document:
            try:
                executor.close_active(
                    "surface-probe-close",
                    save=False,
                    discard_unsaved=True,
                    expected_document_name=str(created_document),
                )
            except Exception:
                pass
        executor.session.close()


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from pathlib import Path

from catia_mcp.executor import CatiaExecutor


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Join, Healing and Thick Surface on two adjacent planar fills"
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    executor = CatiaExecutor()
    created_document = None
    results: dict[str, object] = {}
    try:
        results["connect"] = executor.connect()
        results["create_part"] = executor.create_part("join-thick-create", "Join_Thick_Probe")
        created_document = results["create_part"]["document"]
        results["wireframe"] = executor.create_geometrical_set("join-thick-wireframe", "Wireframe")
        results["surfaces"] = executor.create_geometrical_set("join-thick-surfaces", "Surfaces")
        results["points"] = executor.create_3d_points(
            "join-thick-points",
            [
                {"name": "P_A", "coordinates": [0.0, 0.0, 0.0]},
                {"name": "P_B", "coordinates": [20.0, 0.0, 0.0]},
                {"name": "P_C", "coordinates": [20.0, 20.0, 0.0]},
                {"name": "P_D", "coordinates": [0.0, 20.0, 0.0]},
                {"name": "P_E", "coordinates": [40.0, 0.0, 0.0]},
                {"name": "P_F", "coordinates": [40.0, 20.0, 0.0]},
            ],
            "Wireframe",
        )
        edge_points = {
            "Edge_AB": ["P_A", "P_B"],
            "Edge_BC": ["P_B", "P_C"],
            "Edge_CD": ["P_C", "P_D"],
            "Edge_DA": ["P_D", "P_A"],
            "Edge_BE": ["P_B", "P_E"],
            "Edge_EF": ["P_E", "P_F"],
            "Edge_FC": ["P_F", "P_C"],
        }
        for edge_name, point_names in edge_points.items():
            results[edge_name] = executor.create_spline(
                f"join-thick-{edge_name.casefold()}",
                edge_name,
                point_names,
                False,
                None,
                "Wireframe",
            )
        results["fill_left"] = executor.create_fill(
            "join-thick-fill-left",
            name="Fill_Left",
            boundary_names=["Edge_AB", "Edge_BC", "Edge_CD", "Edge_DA"],
            support_names=None,
            continuities=["g0", "g0", "g0", "g0"],
            constraints=None,
            geometrical_set="Surfaces",
        )
        results["fill_right"] = executor.create_fill(
            "join-thick-fill-right",
            name="Fill_Right",
            boundary_names=["Edge_BE", "Edge_EF", "Edge_FC", "Edge_BC"],
            support_names=None,
            continuities=["g0", "g0", "g0", "g0"],
            constraints=None,
            geometrical_set="Surfaces",
        )
        results["join"] = executor.join_surfaces(
            "join-thick-join",
            name="Joined_Plane",
            element_names=["Fill_Left", "Fill_Right"],
            tolerance_mm=0.001,
            angular_tolerance_deg=0.5,
            connex=True,
            manifold=True,
            simplify=True,
            geometrical_set="Surfaces",
        )
        results["healing"] = executor.heal_surfaces(
            "join-thick-healing",
            name="Healed_Plane",
            body_names=["Joined_Plane"],
            continuity="g1",
            distance_objective_mm=0.001,
            merging_distance_mm=0.001,
            tangency_angle_deg=0.5,
            sharpness_angle_deg=0.5,
            geometrical_set="Surfaces",
        )
        results["quality"] = executor.check_surface_quality(
            "join-thick-quality",
            ["Fill_Left", "Fill_Right", "Joined_Plane", "Healed_Plane"],
            [["Fill_Left", "Fill_Right"]],
        )
        results["thick_surface"] = executor.thick_surface(
            "join-thick-solid",
            name="Thickened_Plane",
            surface_name="Healed_Plane",
            top_offset_mm=2.0,
            bottom_offset_mm=0.0,
            reverse_direction=False,
            body_name="PartBody",
        )
        output = args.output.resolve(strict=False)
        results["save"] = executor.save_active("join-thick-save", str(output))
        created_document = output.name
        results["output"] = str(output)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        if created_document:
            try:
                executor.close_active(
                    "join-thick-close",
                    save=False,
                    discard_unsaved=True,
                    expected_document_name=str(created_document),
                )
            except Exception:
                pass
        executor.session.close()


if __name__ == "__main__":
    main()

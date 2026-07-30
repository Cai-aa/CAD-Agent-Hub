from __future__ import annotations

import argparse
import json
from pathlib import Path

from catia_mcp.executor import CatiaExecutor


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Join and Close Surface on a six-face shell")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    executor = CatiaExecutor()
    created_document = None
    results: dict[str, object] = {}
    try:
        results["connect"] = executor.connect()
        results["create_part"] = executor.create_part("close-probe-create", "Close_Surface_Probe")
        created_document = results["create_part"]["document"]
        executor.create_geometrical_set("close-probe-wireframe", "Wireframe")
        executor.create_geometrical_set("close-probe-surfaces", "Surfaces")
        coordinates = {
            "P000": [0.0, 0.0, 0.0],
            "P100": [20.0, 0.0, 0.0],
            "P110": [20.0, 20.0, 0.0],
            "P010": [0.0, 20.0, 0.0],
            "P001": [0.0, 0.0, 20.0],
            "P101": [20.0, 0.0, 20.0],
            "P111": [20.0, 20.0, 20.0],
            "P011": [0.0, 20.0, 20.0],
        }
        results["points"] = executor.create_3d_points(
            "close-probe-points",
            [{"name": name, "coordinates": xyz} for name, xyz in coordinates.items()],
            "Wireframe",
        )
        edges = {
            "E000_100": ["P000", "P100"],
            "E100_110": ["P100", "P110"],
            "E110_010": ["P110", "P010"],
            "E010_000": ["P010", "P000"],
            "E001_101": ["P001", "P101"],
            "E101_111": ["P101", "P111"],
            "E111_011": ["P111", "P011"],
            "E011_001": ["P011", "P001"],
            "E000_001": ["P000", "P001"],
            "E100_101": ["P100", "P101"],
            "E110_111": ["P110", "P111"],
            "E010_011": ["P010", "P011"],
        }
        for edge_name, point_names in edges.items():
            executor.create_spline(
                f"close-probe-{edge_name.casefold()}",
                edge_name,
                point_names,
                False,
                None,
                "Wireframe",
            )
        faces = {
            "Face_Bottom": ["E000_100", "E100_110", "E110_010", "E010_000"],
            "Face_Top": ["E001_101", "E101_111", "E111_011", "E011_001"],
            "Face_Front": ["E000_100", "E100_101", "E001_101", "E000_001"],
            "Face_Right": ["E100_110", "E110_111", "E101_111", "E100_101"],
            "Face_Back": ["E110_010", "E010_011", "E111_011", "E110_111"],
            "Face_Left": ["E010_000", "E000_001", "E011_001", "E010_011"],
        }
        for face_name, boundary_names in faces.items():
            results[face_name] = executor.create_fill(
                f"close-probe-{face_name.casefold()}",
                name=face_name,
                boundary_names=boundary_names,
                support_names=None,
                continuities=["g0"] * 4,
                constraints=None,
                geometrical_set="Surfaces",
            )
        results["join"] = executor.join_surfaces(
            "close-probe-join",
            name="Closed_Shell",
            element_names=list(faces),
            tolerance_mm=0.001,
            angular_tolerance_deg=0.5,
            connex=True,
            manifold=True,
            simplify=True,
            geometrical_set="Surfaces",
        )
        results["close_surface"] = executor.close_surface(
            "close-probe-solid",
            "Closed_Solid",
            "Closed_Shell",
            "PartBody",
        )
        results["quality"] = executor.check_surface_quality(
            "close-probe-quality",
            ["Closed_Shell"],
            None,
        )
        output = args.output.resolve(strict=False)
        results["save"] = executor.save_active("close-probe-save", str(output))
        created_document = output.name
        results["output"] = str(output)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        if created_document:
            try:
                executor.close_active(
                    "close-probe-close",
                    save=False,
                    discard_unsaved=True,
                    expected_document_name=str(created_document),
                )
            except Exception:
                pass
        executor.session.close()


if __name__ == "__main__":
    main()

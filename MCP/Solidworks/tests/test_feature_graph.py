import unittest

from solidworks_mcp.contracts import ContractError
from solidworks_mcp.feature_graph import compile_feature_graph


class FeatureGraphTests(unittest.TestCase):
    def test_compiles_a_small_feature_graph(self) -> None:
        plan = compile_feature_graph({
            "version": "1.0",
            "features": [
                {"name": "part", "kind": "new_part"},
                {"name": "boss", "kind": "extrude", "profile": "circle", "depth_mm": 10},
            ],
        })
        self.assertEqual(
            [step["operation"] for step in plan],
            ["new_part", "create_sketch_and_extrude"],
        )

    def test_compiles_native_feature_pipeline(self) -> None:
        plan = compile_feature_graph({
            "version": "1.0",
            "features": [
                {"name": "part", "kind": "new_part"},
                {
                    "name": "blank_sketch",
                    "kind": "sketch",
                    "plane": "Front Plane",
                    "entities": [{"kind": "circle", "radius_mm": 20}],
                },
                {
                    "name": "blank",
                    "kind": "boss_extrude",
                    "sketch": "blank_sketch",
                    "depth_mm": 10,
                },
                {
                    "name": "axis",
                    "kind": "reference_axis",
                    "planes": ["Top Plane", "Right Plane"],
                },
                {
                    "name": "pattern",
                    "kind": "circular_pattern",
                    "feature": "blank",
                    "axis": "axis",
                    "count": 20,
                },
                {
                    "name": "fillet",
                    "kind": "fillet",
                    "radius_mm": 0.5,
                    "selector": {"orientation": "axial", "radius_mm": 17.5},
                },
                {
                    "name": "chamfer",
                    "kind": "chamfer",
                    "distance_mm": 0.25,
                    "selector": {
                        "orientation": "planar",
                        "radius_mm": 22,
                        "z_levels_mm": [0, 10],
                    },
                },
            ],
        })
        self.assertEqual(
            [step["operation"] for step in plan],
            [
                "new_part",
                "create_sketch",
                "boss_extrude",
                "reference_axis",
                "circular_pattern",
                "fillet",
                "chamfer",
            ],
        )

    def test_rejects_forward_feature_reference(self) -> None:
        with self.assertRaisesRegex(ContractError, "unknown or later feature"):
            compile_feature_graph({
                "version": "1.0",
                "features": [
                    {"name": "part", "kind": "new_part"},
                    {"name": "boss", "kind": "boss_extrude", "sketch": "later", "depth_mm": 5},
                    {
                        "name": "later",
                        "kind": "sketch",
                        "entities": [{"kind": "circle", "radius_mm": 2}],
                    },
                ],
            })

    def test_compiles_native_revolve(self) -> None:
        plan = compile_feature_graph({
            "version": "1.0",
            "features": [
                {"name": "Part", "kind": "new_part"},
                {
                    "name": "Axis",
                    "kind": "reference_axis",
                    "planes": ["Front Plane", "Right Plane"],
                },
                {
                    "name": "Profile",
                    "kind": "sketch",
                    "plane": "Front Plane",
                    "entities": [
                        {"kind": "line", "start": [0, -25], "end": [0, 25], "construction": True},
                        {
                            "kind": "arc",
                            "center": [0, 0],
                            "start": [0, 25],
                            "end": [0, -25],
                            "direction": 1,
                        },
                    ],
                },
                {
                    "name": "SphereRevolve",
                    "kind": "boss_revolve",
                    "sketch": "Profile",
                    "axis": "Axis",
                    "angle_deg": 360,
                },
            ],
        })
        self.assertEqual(plan[-1]["operation"], "boss_revolve")
        self.assertEqual(plan[-1]["angle_deg"], 360)
        self.assertEqual(plan[-1]["axis_strategy"], "reference_axis")

    def test_compiles_sketch_segment_revolve(self) -> None:
        plan = compile_feature_graph({
            "version": "1.0",
            "features": [
                {"name": "Part", "kind": "new_part"},
                {
                    "name": "Profile",
                    "kind": "sketch",
                    "entities": [
                        {"kind": "line", "start": [0, -5], "end": [0, 5], "construction": True},
                        {"kind": "arc", "center": [0, 0], "start": [0, 5], "end": [5, 0]},
                        {"kind": "arc", "center": [0, 0], "start": [5, 0], "end": [0, -5]},
                    ],
                },
                {
                    "name": "Revolve",
                    "kind": "boss_revolve",
                    "sketch": "Profile",
                    "axis_segment": "Line1",
                },
            ],
        })
        self.assertEqual(plan[-1]["axis_strategy"], "sketch_segment")
        self.assertEqual(plan[-1]["axis_segment"], "Line1")

    def test_revolve_rejects_ambiguous_axis_strategy(self) -> None:
        with self.assertRaisesRegex(ContractError, "exactly one of axis or axis_segment"):
            compile_feature_graph({
                "version": "1.0",
                "features": [
                    {"name": "Part", "kind": "new_part"},
                    {
                        "name": "Profile",
                        "kind": "sketch",
                        "entities": [{"kind": "circle", "radius_mm": 5}],
                    },
                    {
                        "name": "Revolve",
                        "kind": "boss_revolve",
                        "sketch": "Profile",
                        "axis": "Profile",
                        "axis_segment": "Line1",
                    },
                ],
            })


if __name__ == "__main__":
    unittest.main()

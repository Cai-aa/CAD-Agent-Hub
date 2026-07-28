import unittest

from solidworks_mcp.feature_graph import compile_feature_graph
from solidworks_mcp.involute_gear import validate_gear_spec
from solidworks_mcp.primitives import build_sphere_graph, build_sphere_with_gear_graph


class PrimitiveTests(unittest.TestCase):
    def test_sphere_uses_deterministic_native_revolve(self) -> None:
        graph = build_sphere_graph(50)
        plan = compile_feature_graph(graph)
        profile = plan[1]
        revolve = plan[2]

        self.assertEqual(len(profile["entities"]), 3)
        self.assertTrue(profile["entities"][0]["construction"])
        self.assertEqual([entity["kind"] for entity in profile["entities"]], ["line", "arc", "arc"])
        self.assertEqual(revolve["axis_strategy"], "sketch_segment")
        self.assertEqual(revolve["axis_segment"], "Line1")
        self.assertEqual(graph["metadata"]["diameter_mm"], 50.0)

    def test_sphere_with_gear_compiles_as_one_multibody_part(self) -> None:
        spec = validate_gear_spec(
            module_mm=2,
            tooth_count=20,
            pressure_angle_deg=20,
            thickness_mm=10,
            bore_diameter_mm=10,
            root_fillet_mm=0.45,
            tip_chamfer_mm=0.25,
        )
        graph = build_sphere_with_gear_graph(spec)
        plan = compile_feature_graph(graph)
        self.assertEqual(plan[0]["operation"], "new_part")
        self.assertEqual(plan[-1]["name"], "AdjacentGearBoreCut")
        self.assertEqual(graph["metadata"]["body_count_expected"], 2)
        self.assertEqual(graph["metadata"]["surface_gap_mm"], 13.0)


if __name__ == "__main__":
    unittest.main()

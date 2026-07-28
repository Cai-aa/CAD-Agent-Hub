import math
import unittest

from solidworks_mcp.feature_graph import compile_feature_graph
from solidworks_mcp.involute_gear import (
    build_involute_gear_graph,
    involute_angle,
    involute_tooth_entities,
    sampled_involute_gear_entities,
    sampled_involute_tooth_points,
    validate_gear_spec,
)


def standard_spec():
    return validate_gear_spec(
        module_mm=2,
        tooth_count=20,
        pressure_angle_deg=20,
        thickness_mm=10,
        bore_diameter_mm=10,
        root_fillet_mm=0.45,
        tip_chamfer_mm=0.25,
    )


class InvoluteGearTests(unittest.TestCase):
    def test_standard_gear_reference_diameters(self) -> None:
        spec = standard_spec()
        self.assertEqual(spec.pitch_radius_mm, 20)
        self.assertEqual(spec.outer_radius_mm, 22)
        self.assertEqual(spec.root_radius_mm, 17.5)
        self.assertAlmostEqual(spec.base_radius_mm, 20 * math.cos(math.radians(20)))

    def test_involute_flanks_end_on_outer_circle(self) -> None:
        spec = standard_spec()
        entities = involute_tooth_entities(spec)
        self.assertEqual(entities[1]["kind"], "equation_spline")
        self.assertEqual(entities[3]["kind"], "equation_spline")
        for point in (entities[2]["start"], entities[2]["end"]):
            self.assertAlmostEqual(math.hypot(*point), spec.outer_radius_mm)
        self.assertGreater(involute_angle(spec.pitch_radius_mm, spec.base_radius_mm), 0)

    def test_sampled_tooth_narrows_toward_tip(self) -> None:
        spec = standard_spec()
        points = sampled_involute_tooth_points(spec, samples_per_flank=16)
        root_half_angle = abs(math.atan2(points[0][1], points[0][0]))
        minimum_outer_half_angle = min(abs(math.atan2(point[1], point[0])) for point in points)
        self.assertLess(minimum_outer_half_angle, root_half_angle)
        self.assertTrue(all(math.isfinite(value) for point in points for value in point))

    def test_sampled_full_gear_is_offset_and_has_one_region_per_tooth(self) -> None:
        spec = standard_spec()
        entities = sampled_involute_gear_entities(spec, center_mm=(60.0, 0.0))
        self.assertEqual(len(entities), spec.tooth_count)
        self.assertTrue(all(entity["closed"] for entity in entities))
        all_x = [point[0] for entity in entities for point in entity["points"]]
        self.assertAlmostEqual((min(all_x) + max(all_x)) / 2.0, 60.0, places=6)

    def test_standard_gear_graph_has_native_feature_tree(self) -> None:
        graph = build_involute_gear_graph(standard_spec())
        plan = compile_feature_graph(graph)
        tooth_sketch = next(item for item in graph["features"] if item["name"] == "InvoluteToothSketch")
        self.assertEqual(tooth_sketch["entities"][0]["kind"], "polyline")
        self.assertEqual(graph["metadata"]["tooth_representation"], "sampled_polyline")
        self.assertEqual(
            [step["name"] for step in plan],
            [
                "Part",
                "GearBlankSketch",
                "GearBlank",
                "GearAxis",
                "InvoluteToothSketch",
                "ToothBoss",
                "ToothCircularPattern",
                "BoreSketch",
                "BoreCut",
                "RootFillet",
                "TipChamfer",
            ],
        )

    def test_finishing_features_can_be_omitted_for_late_bound_hosts(self) -> None:
        graph = build_involute_gear_graph(standard_spec(), include_finishing=False)
        names = [item["name"] for item in graph["features"]]
        self.assertNotIn("RootFillet", names)
        self.assertNotIn("TipChamfer", names)
        self.assertIn("BoreCut", names)
        self.assertFalse(graph["metadata"]["finishing_features_included"])


if __name__ == "__main__":
    unittest.main()

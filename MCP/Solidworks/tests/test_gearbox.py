from __future__ import annotations

import unittest

from solidworks_mcp.feature_graph import compile_feature_graph
from solidworks_mcp.gearbox import build_two_stage_reducer_graph


class GearboxTests(unittest.TestCase):
    def test_two_stage_reducer_compiles_with_expected_ratios(self) -> None:
        graph = build_two_stage_reducer_graph()
        plan = compile_feature_graph(graph)

        self.assertEqual(graph["metadata"]["total_ratio"], 6.0)
        self.assertEqual(graph["metadata"]["stage1_center_distance_mm"], 60.0)
        self.assertEqual(graph["metadata"]["stage2_center_distance_mm"], 80.0)
        self.assertIn("reference_plane_offset", {step["operation"] for step in plan})
        self.assertEqual(plan[-1]["name"], "ReducerKeywayCut")


if __name__ == "__main__":
    unittest.main()

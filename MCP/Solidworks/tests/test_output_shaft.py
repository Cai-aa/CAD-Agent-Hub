from __future__ import annotations

import unittest

from solidworks_mcp.feature_graph import compile_feature_graph
from solidworks_mcp.output_shaft import build_output_shaft_from_dwg_graph


class OutputShaftTests(unittest.TestCase):
    def test_output_shaft_dwg_dimensions_compile(self) -> None:
        graph = build_output_shaft_from_dwg_graph()
        plan = compile_feature_graph(graph)

        self.assertEqual(graph["metadata"]["total_length_mm"], 333.0)
        self.assertEqual(
            graph["metadata"]["segment_diameters_mm"],
            [55.0, 60.0, 65.0, 60.0, 55.0, 50.0, 45.0],
        )
        self.assertEqual(plan[-1]["name"], "EndBlindHoleDia3Depth12")
        self.assertEqual(plan[-1]["depth_mm"], 12.0)


if __name__ == "__main__":
    unittest.main()

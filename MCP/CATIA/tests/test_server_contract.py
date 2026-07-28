from __future__ import annotations

import unittest

from catia_mcp.server import mcp


class ServerContractTests(unittest.TestCase):
    def test_required_tool_surface(self) -> None:
        tools = set(mcp._tool_manager._tools)
        required = {
            "catia_health_check",
            "catia_connect",
            "catia_create_sketch",
            "catia_add_pad",
            "catia_create_analysis_document",
            "catia_add_analysis_mesh_part",
            "catia_add_analysis_entity",
            "catia_run_analysis_transition",
            "catia_compute_analysis",
            "catia_build_analysis_report",
        }
        self.assertTrue(required.issubset(tools))
        self.assertGreaterEqual(len(tools), 35)


if __name__ == "__main__":
    unittest.main()

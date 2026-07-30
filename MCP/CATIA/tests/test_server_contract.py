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
            "catia_surface_capabilities",
            "catia_create_3d_points",
            "catia_create_spline",
            "catia_create_offset_plane",
            "catia_create_connect_curve",
            "catia_create_loft",
            "catia_create_fill",
            "catia_join_surfaces",
            "catia_heal_surfaces",
            "catia_create_boundary",
            "catia_close_surface",
            "catia_thick_surface",
            "catia_check_surface_quality",
        }
        self.assertTrue(required.issubset(tools))
        self.assertGreaterEqual(len(tools), 53)


if __name__ == "__main__":
    unittest.main()

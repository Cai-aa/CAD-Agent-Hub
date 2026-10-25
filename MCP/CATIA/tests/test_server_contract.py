from __future__ import annotations

import asyncio
import unittest

from catia_mcp.com_runtime import CatiaUnavailable
from catia_mcp.contracts import ContractError
from catia_mcp.server import _result, mcp


class ServerContractTests(unittest.TestCase):
    @staticmethod
    def _tools():
        return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}

    @staticmethod
    def _schema(tool):
        if hasattr(tool, "input_schema"):
            return tool.input_schema
        return tool.inputSchema

    def test_required_tool_surface(self) -> None:
        tools = set(self._tools())
        required = {
            "catia_health_check",
            "catia_connect",
            "catia_create_sketch",
            "catia_add_pad",
            "catia_inspect_edges",
            "catia_add_edge_fillet",
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
        self.assertGreaterEqual(len(tools), 55)

    def test_export_tool_defaults_to_non_overwriting_policy(self) -> None:
        schema = self._schema(self._tools()["catia_export_active"])
        properties = schema["properties"]
        self.assertEqual(properties["overwrite_policy"]["default"], "error")
        self.assertTrue(properties["verify_reimport"]["default"])

    def test_pocket_tool_exposes_backward_compatible_reverse_flag(self) -> None:
        schema = self._schema(self._tools()["catia_add_pocket"])
        self.assertFalse(schema["properties"]["reverse"]["default"])

    def test_edge_fillet_tool_exposes_typed_selection_and_propagation(self) -> None:
        schema = self._schema(self._tools()["catia_add_edge_fillet"])
        properties = schema["properties"]
        self.assertIn("edge_indices", schema["required"])
        self.assertIn("radius_mm", schema["required"])
        self.assertEqual(properties["edge_indices"]["items"]["type"], "integer")
        self.assertEqual(properties["propagation"]["default"], "tangency")

    def test_missing_catia_session_is_reported_as_non_recoverable(self) -> None:
        def failing() -> dict[str, object]:
            raise CatiaUnavailable("CATIA desktop is not running")

        outcome = _result("catia_connect", failing)
        self.assertEqual(outcome["operation"], "catia_connect")
        self.assertIn("CATIA desktop is not running", outcome["error"]["message"])
        self.assertFalse(outcome["error"]["recoverable"])
        self.assertIn("catia_connect(start_if_missing=True)", outcome["error"]["suggestion"])

    def test_recoverable_errors_keep_the_retry_path(self) -> None:
        def failing() -> dict[str, object]:
            raise ContractError("invalid pad length")

        outcome = _result("catia_add_pad", failing)
        self.assertEqual(outcome["error"]["message"], "invalid pad length")
        self.assertTrue(outcome["error"]["recoverable"])
        self.assertNotIn("suggestion", outcome["error"])


if __name__ == "__main__":
    unittest.main()

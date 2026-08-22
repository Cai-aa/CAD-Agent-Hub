from __future__ import annotations

import asyncio
import unittest

from solidworks_mcp.server import mcp


class ServerCompatibilityTests(unittest.TestCase):
    def test_high_level_server_registers_tools(self) -> None:
        tools = asyncio.run(mcp.list_tools())
        names = {tool.name for tool in tools}

        self.assertTrue(
            {
                "solidworks_health_check",
                "solidworks_connect",
                "solidworks_list_documents",
                "solidworks_activate_document",
                "solidworks_get_bounding_box",
                "solidworks_get_mass_properties",
                "solidworks_rebuild_diagnostics",
                "solidworks_capture_view",
                "solidworks_list_configurations",
                "solidworks_activate_configuration",
                "solidworks_create_configuration",
                "solidworks_get_custom_properties",
                "solidworks_set_custom_properties",
                "solidworks_list_material_databases",
                "solidworks_get_material",
                "solidworks_assign_material",
            }.issubset(names)
        )


if __name__ == "__main__":
    unittest.main()

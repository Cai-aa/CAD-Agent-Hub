from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from solidworks_mcp.contracts import ContractError
from solidworks_mcp.metadata import (
    activate_configuration,
    assign_material,
    create_configuration,
    get_custom_properties,
    get_material,
    list_configurations,
    list_material_databases,
    set_custom_properties,
)


class FakeConfiguration:
    def __init__(self, name: str, comment: str = "", alternate_name: str = "") -> None:
        self.Name = name
        self.Comment = comment
        self.AlternateName = alternate_name
        self.IsDerived = False

    def __call__(self) -> object:
        raise RuntimeError("COM dispatch properties must not be invoked")


class FakeConfigurationManager:
    def __init__(self, model: "FakeModel") -> None:
        self.model = model

    @property
    def ActiveConfiguration(self) -> FakeConfiguration:
        return self.model.configurations[self.model.active_configuration]


class FakeCustomPropertyManager:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    @property
    def GetNames(self) -> tuple[str, ...] | None:
        return tuple(self.values) if self.values else None

    def Get6(
        self,
        name: str,
        use_cached: bool,
        raw: object,
        resolved: object,
        was_resolved: object,
        link_to_property: object,
    ) -> int:
        value = self.values.get(name, "")
        raw.value = value
        resolved.value = value
        was_resolved.value = True
        link_to_property.value = False
        return 2 if name in self.values else 1

    def Add3(self, name: str, property_type: int, value: str, option: int) -> int:
        self.values[name] = value
        return 0


class FakeExtension:
    def __init__(self) -> None:
        self.managers: dict[str, FakeCustomPropertyManager] = {}

    def CustomPropertyManager(self, scope: str) -> FakeCustomPropertyManager:
        return self.managers.setdefault(scope, FakeCustomPropertyManager())


class FakeModel:
    def __init__(self) -> None:
        self.configurations = {"Default": FakeConfiguration("Default")}
        self.active_configuration = "Default"
        self.ConfigurationManager = FakeConfigurationManager(self)
        self.Extension = FakeExtension()
        self.materials: dict[str, tuple[str, str]] = {}
        self.rebuild_count = 0

    @property
    def GetConfigurationNames(self) -> tuple[str, ...]:
        return tuple(self.configurations)

    def GetConfigurationByName(self, name: str) -> FakeConfiguration | None:
        return self.configurations.get(name)

    def ShowConfiguration2(self, name: str) -> bool:
        if name not in self.configurations:
            return False
        self.active_configuration = name
        return False

    def AddConfiguration3(
        self,
        name: str,
        comment: str,
        alternate_name: str,
        options: int,
    ) -> FakeConfiguration:
        configuration = FakeConfiguration(name, comment, alternate_name)
        self.configurations[name] = configuration
        return configuration

    def GetType(self) -> int:
        return 1

    def GetMaterialPropertyName2(self, configuration: str, database: object) -> str:
        stored_database, material = self.materials.get(configuration, ("", ""))
        database.value = stored_database
        return material

    def SetMaterialPropertyName2(
        self,
        configuration: str,
        database: str,
        material: str,
    ) -> bool:
        self.materials[configuration] = (database, material)
        return True

    def EditRebuild3(self) -> bool:
        self.rebuild_count += 1
        return True


class FakeApplication:
    def __init__(self, databases: list[str]) -> None:
        self.GetMaterialDatabases = tuple(databases)


class MetadataTests(unittest.TestCase):
    def test_lists_and_activates_configurations(self) -> None:
        model = FakeModel()
        model.configurations["Machined"] = FakeConfiguration("Machined", "Final state")

        listed = list_configurations(model)
        activated = activate_configuration(model, "Machined")

        self.assertEqual(listed["configuration_count"], 2)
        self.assertEqual(activated["configuration_name"], "Machined")
        self.assertEqual(model.active_configuration, "Machined")

    def test_creates_configuration_and_rejects_duplicates(self) -> None:
        model = FakeModel()
        created = create_configuration(
            model,
            "Inspection",
            comment="QA state",
            alternate_name="INSPECT",
        )

        self.assertTrue(created["active"])
        self.assertEqual(model.configurations["Inspection"].Comment, "QA state")
        with self.assertRaisesRegex(ContractError, "already exists"):
            create_configuration(model, "Inspection")

    def test_sets_and_reads_document_custom_properties(self) -> None:
        model = FakeModel()
        written = set_custom_properties(
            model,
            {"PartNumber": "SW-MCP-001", "Revision": 2, "Released": True},
        )
        read = get_custom_properties(model)

        self.assertEqual(written["write_count"], 3)
        values = {item["name"]: item["raw_value"] for item in read["properties"]}
        self.assertEqual(values["PartNumber"], "SW-MCP-001")
        self.assertEqual(values["Revision"], "2")
        self.assertEqual(values["Released"], "Yes")

    def test_configuration_properties_use_exact_scope(self) -> None:
        model = FakeModel()
        set_custom_properties(model, {"Finish": "Ground"}, "Default")

        configuration = get_custom_properties(model, "Default")
        document = get_custom_properties(model)

        self.assertEqual(configuration["configuration_name"], "Default")
        self.assertEqual(configuration["property_count"], 1)
        self.assertEqual(document["property_count"], 0)

    def test_lists_material_databases_and_file_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "materials.sldmat"
            database.write_text("<materials />", encoding="utf-8")
            result = list_material_databases(FakeApplication([str(database), "missing.sldmat"]))

        self.assertEqual(result["database_count"], 2)
        self.assertTrue(result["databases"][0]["exists"])
        self.assertFalse(result["databases"][1]["exists"])

    def test_assigns_and_reads_material_for_exact_configuration(self) -> None:
        model = FakeModel()
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "materials.sldmat"
            database.write_text("<materials />", encoding="utf-8")
            assigned = assign_material(model, str(database), "Alloy Steel")

        read = get_material(model)
        self.assertEqual(assigned["material_name"], "Alloy Steel")
        self.assertEqual(read["material_name"], "Alloy Steel")
        self.assertEqual(read["database_name"], str(database))
        self.assertEqual(model.rebuild_count, 1)

    def test_material_assignment_requires_existing_sldmat(self) -> None:
        with self.assertRaisesRegex(ContractError, "existing .sldmat"):
            assign_material(FakeModel(), "missing.sldmat", "Alloy Steel")


if __name__ == "__main__":
    unittest.main()

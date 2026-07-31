from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory

from catia_mcp.contracts import ContractError
from pathlib import Path

from catia_mcp.modeling import (
    _body,
    _validate_entities,
    add_components,
    close_active,
    export_active,
)


class ModelingContractTests(unittest.TestCase):
    @staticmethod
    def _export_app(payload: bytes = b"new export"):
        class Document:
            Name = "Source.CATPart"
            FullName = r"C:\workspace\Source.CATPart"

            def __init__(self):
                self.export_calls = []
                self.fail = False
                self.app = None

            def ExportData(self, path, format_name):
                self.export_calls.append(
                    {
                        "path": path,
                        "format": format_name,
                        "alerts": self.app.DisplayFileAlerts,
                    }
                )
                if self.fail:
                    raise RuntimeError("simulated export failure")
                Path(path).write_bytes(payload)

            def Activate(self):
                self.app.ActiveDocument = self

        document = Document()
        documents = type("Documents", (), {"Count": 1})()
        app = type(
            "App",
            (),
            {
                "Documents": documents,
                "ActiveDocument": document,
                "DisplayFileAlerts": True,
            },
        )()
        document.app = app
        return app, document

    def test_default_partbody_falls_back_to_localized_main_body(self) -> None:
        main = object()

        class Bodies:
            Count = 1

            def Item(self, value):
                if isinstance(value, str):
                    raise RuntimeError("localized body name")
                return main

        part = type("Part", (), {"Bodies": Bodies(), "MainBody": main})()
        self.assertIs(_body(part, "PartBody"), main)

    def test_validates_mixed_sketch(self) -> None:
        result = _validate_entities(
            [
                {"kind": "line", "start": [0, 0], "end": [10, 0]},
                {"kind": "circle", "center": [5, 5], "radius": 2},
                {"kind": "rectangle", "origin": [0, 0], "width": 10, "height": 5},
                {"kind": "polyline", "points": [[0, 0], [1, 1], [2, 0]], "closed": True},
            ]
        )
        self.assertEqual([item["kind"] for item in result], ["line", "circle", "rectangle", "polyline"])

    def test_rejects_empty_sketch(self) -> None:
        with self.assertRaises(ContractError):
            _validate_entities([])

    def test_rejects_invalid_circle(self) -> None:
        with self.assertRaises(ContractError):
            _validate_entities([{"kind": "circle", "center": [0, 0], "radius": 0}])

    def test_close_refuses_unexpected_active_document(self) -> None:
        document = type("Document", (), {"Name": "UserModel.CATPart", "Saved": True})()
        documents = type("Documents", (), {"Count": 1})()
        app = type("App", (), {"Documents": documents, "ActiveDocument": document})()
        with self.assertRaises(ContractError):
            close_active(app, expected_document_name="ProbeModel.CATPart")

    def test_add_components_uses_plain_sequence_for_dynamic_dispatch(self) -> None:
        calls = []

        class Products:
            Count = 0

            def AddComponentsFromFiles(self, values, method):
                calls.append((values, method))
                self.Count += len(values)

        products = Products()
        product = type("Product", (), {"Products": products, "Update": lambda self: None})()
        document = type("Document", (), {"Name": "Assembly.CATProduct", "Product": product})()
        documents = type("Documents", (), {"Count": 1})()
        app = type("App", (), {"Documents": documents, "ActiveDocument": document})()

        result = add_components(app, [Path("A.CATPart"), Path("B.CATPart")])

        self.assertEqual(calls, [(("A.CATPart", "B.CATPart"), "All")])
        self.assertEqual(result["component_count"], 2)

    def test_export_default_refuses_existing_target_before_catia(self) -> None:
        app, document = self._export_app()
        with TemporaryDirectory() as folder:
            target = Path(folder) / "Existing.step"
            target.write_bytes(b"old")
            with self.assertRaises(ContractError):
                export_active(app, target, verify_reimport=False)
        self.assertEqual(document.export_calls, [])
        self.assertTrue(app.DisplayFileAlerts)

    def test_export_replace_uses_validated_temporary_file(self) -> None:
        app, document = self._export_app(b"replacement")
        with TemporaryDirectory() as folder:
            target = Path(folder) / "Model.step"
            target.write_bytes(b"old")
            result = export_active(
                app,
                target,
                overwrite_policy="replace",
                verify_reimport=False,
            )
            self.assertEqual(target.read_bytes(), b"replacement")
            self.assertTrue(result["replaced_existing"])
            self.assertEqual(result["overwrite_policy"], "replace")
            self.assertFalse(Path(result["temporary_path"]).exists())
            self.assertIn(".__exporting_", document.export_calls[0]["path"])
            self.assertFalse(document.export_calls[0]["alerts"])
        self.assertTrue(app.DisplayFileAlerts)

    def test_export_versioned_preserves_existing_target(self) -> None:
        app, _ = self._export_app(b"version two")
        with TemporaryDirectory() as folder:
            target = Path(folder) / "Model.step"
            target.write_bytes(b"version one")
            result = export_active(
                app,
                target,
                overwrite_policy="versioned",
                verify_reimport=False,
            )
            versioned = Path(result["path"])
            self.assertEqual(target.read_bytes(), b"version one")
            self.assertEqual(versioned.read_bytes(), b"version two")
            self.assertNotEqual(versioned, target)
            self.assertIn(".__version_", versioned.name)

    def test_export_restores_alerts_and_releases_guard_after_failure(self) -> None:
        app, document = self._export_app()
        document.fail = True
        with TemporaryDirectory() as folder:
            target = Path(folder) / "Model.step"
            with self.assertRaisesRegex(RuntimeError, "simulated export failure"):
                export_active(
                    app,
                    target,
                    overwrite_policy="replace",
                    verify_reimport=False,
                )
            self.assertTrue(app.DisplayFileAlerts)
            document.fail = False
            result = export_active(
                app,
                target,
                overwrite_policy="replace",
                verify_reimport=False,
            )
            self.assertTrue(Path(result["path"]).exists())

    def test_step_export_reimports_and_restores_original_document(self) -> None:
        app, document = self._export_app(b"validated step")

        shapes = type("Shapes", (), {"Count": 1})()
        body = type("Body", (), {"Shapes": shapes})()

        class Bodies:
            Count = 1

            def Item(self, index):
                return body

        imported = type(
            "Imported",
            (),
            {
                "Name": "Validated.CATPart",
                "Part": type("Part", (), {"Bodies": Bodies()})(),
                "Close": lambda self: None,
            },
        )()

        class Documents:
            Count = 1

            def Open(self, path):
                app.ActiveDocument = imported
                return imported

        app.Documents = Documents()
        with TemporaryDirectory() as folder:
            target = Path(folder) / "Model.step"
            result = export_active(app, target)
        self.assertTrue(result["reimport_validation"]["passed"])
        self.assertEqual(result["reimport_validation"]["shape_count"], 1)
        self.assertIs(app.ActiveDocument, document)


if __name__ == "__main__":
    unittest.main()

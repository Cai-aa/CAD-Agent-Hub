from __future__ import annotations

import unittest

from catia_mcp.contracts import ContractError
from pathlib import Path

from catia_mcp.modeling import _body, _validate_entities, add_components, close_active


class ModelingContractTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

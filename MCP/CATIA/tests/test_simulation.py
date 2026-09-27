from __future__ import annotations

import unittest

from catia_mcp.simulation import BUILTIN_ANALYSIS_CATALOG, bind_mesh_support_from_search, compute_case


class Collection:
    def __init__(self, items):
        self._items = list(items)
        self.Count = len(self._items)

    def Item(self, index, *_args):
        return self._items[index - 1]

    def __iter__(self):
        return iter(self._items)


class FakeCase:
    Name = "Static Case.1"

    def __init__(self) -> None:
        self.compute_calls = 0
        self.mesh_calls = 0

    def Compute(self) -> None:
        self.compute_calls += 1

    def ComputeMeshOnly(self) -> None:
        self.mesh_calls += 1


class SimulationTests(unittest.TestCase):
    def _app(self):
        case = FakeCase()
        model = type("Model", (), {"AnalysisCases": Collection([case])})()
        manager = type("Manager", (), {"AnalysisModels": Collection([model])})()
        document = type("Document", (), {"Name": "Test.CATAnalysis", "Analysis": manager})()
        documents = type("Documents", (), {"Count": 1})()
        app = type("App", (), {"Documents": documents, "ActiveDocument": document})()
        return app, case

    def test_compute_uses_internal_case_api(self) -> None:
        app, case = self._app()
        result = compute_case(app, mesh_only=False)
        self.assertEqual(case.compute_calls, 1)
        self.assertEqual(case.mesh_calls, 0)
        self.assertEqual(result["solver" ] if "solver" in result else "CATIA", "CATIA")

    def test_mesh_only_uses_separate_api(self) -> None:
        app, case = self._app()
        compute_case(app, mesh_only=True)
        self.assertEqual(case.mesh_calls, 1)

    def test_catalog_contains_native_structural_types(self) -> None:
        self.assertIn("SAMClamp", BUILTIN_ANALYSIS_CATALOG["common_structural_entities"])
        self.assertIn("LoadSet", BUILTIN_ANALYSIS_CATALOG["set_types"])

    def _bind_app(self, calls, part_factory):
        class Selected:
            Value = "SELECTED"

        class Selection:
            Count2 = 1

            def Clear(self):
                calls["cleared"] = calls.get("cleared", 0) + 1

            def Search(self, query):
                calls["query"] = query

            def Item2(self, index):
                return Selected()

        selection_instance = Selection()

        class MeshPart:
            def AddSupportFromReference(self, product, reference):
                calls["support_reference"] = reference

        class MeshParts:
            Count = 1

            def Item(self, index):
                return MeshPart()

        class MeshManager:
            AnalysisMeshParts = MeshParts()

        class Analysis:
            AnalysisModels = Collection([type("Model", (), {"MeshManager": MeshManager()})()])

            def CreateReferenceFromGeometry(self, product, selected):
                calls["geometry_reference"] = True
                return "GEOMETRY_REF"

        class Source:
            Name = "Source.CATPart"
            Selection = selection_instance
            Product = "PRODUCT"

        Source.Part = part_factory(calls)
        analysis_doc = type("Doc", (), {"Name": "A.CATAnalysis", "Analysis": Analysis()})()
        documents = type("Docs", (), {"Count": 1, "Item": lambda self, name: Source()})()
        return type("App", (), {"Documents": documents, "ActiveDocument": analysis_doc})()

    def test_bind_mesh_support_prefers_feature_reference(self) -> None:
        calls: dict = {}

        class Part:
            def CreateReferenceFromObject(self, obj):
                calls["feature_reference"] = obj
                return "FEATURE_REF"

        app = self._bind_app(calls, lambda c: Part())
        bind_mesh_support_from_search(app, "Source.CATPart", "Name=PartBody,all")
        self.assertEqual(calls.get("support_reference"), "FEATURE_REF")
        self.assertNotIn("geometry_reference", calls)
        self.assertEqual(calls.get("query"), "Name=PartBody,all")
        self.assertEqual(calls.get("cleared"), 2)

    def test_bind_mesh_support_falls_back_to_geometry_reference(self) -> None:
        calls: dict = {}

        class Part:
            def CreateReferenceFromObject(self, obj):
                raise RuntimeError("feature reference rejected")

        app = self._bind_app(calls, lambda c: Part())
        bind_mesh_support_from_search(app, "Source.CATPart", "Topology.CGMFace,sel")
        self.assertTrue(calls.get("geometry_reference"))
        self.assertEqual(calls.get("support_reference"), "GEOMETRY_REF")


if __name__ == "__main__":
    unittest.main()

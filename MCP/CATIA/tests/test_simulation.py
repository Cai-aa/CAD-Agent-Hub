from __future__ import annotations

import unittest

from catia_mcp.simulation import BUILTIN_ANALYSIS_CATALOG, compute_case


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


if __name__ == "__main__":
    unittest.main()

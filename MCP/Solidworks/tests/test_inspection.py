from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from solidworks_mcp.contracts import ContractError
from solidworks_mcp.inspection import (
    activate_document,
    capture_view,
    get_bounding_box,
    get_mass_properties,
    list_documents,
    rebuild_diagnostics,
)


class FakeDocument:
    def __init__(
        self,
        title: str = "Part1",
        document_type: int = 1,
        path: str = "",
        dirty: bool = False,
    ) -> None:
        self.title = title
        self.document_type = document_type
        self.path = path
        self.dirty = dirty

    def GetTitle(self) -> str:
        return self.title

    def GetType(self) -> int:
        return self.document_type

    def GetPathName(self) -> str:
        return self.path

    def GetSaveFlag(self) -> bool:
        return self.dirty


class FakeApplication:
    def __init__(self, documents: list[FakeDocument]) -> None:
        self.documents = documents
        self.ActiveDoc = documents[0] if documents else None

    def ActivateDoc3(self, title: str, use_preferences: bool, option: int, errors: int) -> FakeDocument:
        self.ActiveDoc = next(document for document in self.documents if document.title == title)
        return self.ActiveDoc


class FakeMassProperty:
    Mass = 7.85
    Volume = 0.001
    SurfaceArea = 0.06
    Density = 7850.0
    CenterOfMass = (0.01, 0.02, 0.03)
    PrincipalMomentsOfInertia = (0.1, 0.2, 0.3)


class FakeExtension:
    def __init__(self) -> None:
        self.NeedsRebuild2 = True

    def CreateMassProperty(self) -> FakeMassProperty:
        return FakeMassProperty()


class FakePart(FakeDocument):
    def __init__(self) -> None:
        super().__init__(path=r"E:\parts\sample.sldprt")
        self.Extension = FakeExtension()
        self.rebuild_count = 0
        self.full_rebuild_count = 0
        self.zoom_count = 0

    def GetPartBox(self, include_hidden: bool) -> tuple[float, ...]:
        return (-0.01, -0.02, 0.0, 0.04, 0.03, 0.08)

    def GetFeatureCount(self) -> int:
        return 5

    def EditRebuild3(self) -> bool:
        self.rebuild_count += 1
        self.Extension.NeedsRebuild2 = False
        return True

    def ForceRebuild3(self, top_only: bool) -> bool:
        self.full_rebuild_count += 1
        self.Extension.NeedsRebuild2 = False
        return True

    def ViewZoomtofit2(self) -> None:
        self.zoom_count += 1

    def GraphicsRedraw2(self) -> None:
        return None

    def SaveBMP(self, path: str, width: int, height: int) -> bool:
        Path(path).write_bytes(b"BM-test-image")
        return True


class FakeLegacyExtension:
    def CreateMassProperty(self) -> object:
        raise AttributeError("CreateMassProperty is unavailable")


class FakeLegacyPart(FakePart):
    def __init__(self) -> None:
        super().__init__()
        self.Extension = FakeLegacyExtension()
        self.GetMassProperties = (
            0.0,
            0.0,
            -0.01,
            0.00008,
            0.0132,
            0.08,
            1.9e-5,
            4.5e-5,
            5.9e-5,
            0.0,
            0.0,
            0.0,
        )


class InspectionTests(unittest.TestCase):
    def test_lists_documents_and_marks_active_title(self) -> None:
        first = FakeDocument("Part1", path=r"E:\parts\one.sldprt")
        second = FakeDocument("Assembly1", document_type=2, dirty=True)
        result = list_documents([first, second], second)

        self.assertEqual(result["document_count"], 2)
        self.assertEqual(result["active_title"], "Assembly1")
        self.assertTrue(result["documents"][1]["active"])
        self.assertTrue(result["documents"][1]["dirty"])

    def test_activates_only_an_existing_exact_title(self) -> None:
        documents = [FakeDocument("Part1"), FakeDocument("Part2")]
        app = FakeApplication(documents)
        result = activate_document(app, "Part2", documents)

        self.assertEqual(result["title"], "Part2")
        self.assertIs(app.ActiveDoc, documents[1])
        with self.assertRaisesRegex(ContractError, "No open SolidWorks document"):
            activate_document(app, "Missing", documents)

    def test_returns_part_bounding_box_in_millimetres(self) -> None:
        result = get_bounding_box(FakePart())

        self.assertEqual(result["minimum_mm"], [-10.0, -20.0, 0.0])
        self.assertEqual(result["maximum_mm"], [40.0, 30.0, 80.0])
        self.assertEqual(result["size_mm"], [50.0, 50.0, 80.0])

    def test_returns_mass_properties_with_explicit_units(self) -> None:
        result = get_mass_properties(FakePart())

        self.assertEqual(result["mass_kg"], 7.85)
        self.assertEqual(result["center_of_mass_mm"], [10.0, 20.0, 30.0])
        self.assertEqual(result["principal_moments_kg_m2"], [0.1, 0.2, 0.3])

    def test_falls_back_to_legacy_mass_property_array(self) -> None:
        result = get_mass_properties(FakeLegacyPart())

        self.assertEqual(result["source"], "ModelDoc2.GetMassProperties")
        self.assertEqual(result["mass_kg"], 0.08)
        self.assertEqual(result["volume_m3"], 0.00008)
        self.assertEqual(result["center_of_mass_mm"], [0.0, 0.0, -10.0])
        self.assertAlmostEqual(result["density_kg_m3"], 1000.0)

    def test_rebuild_diagnostics_can_perform_normal_rebuild(self) -> None:
        part = FakePart()
        result = rebuild_diagnostics(part, perform_rebuild=True)

        self.assertTrue(result["rebuild_result"])
        self.assertTrue(result["needs_rebuild_before"])
        self.assertFalse(result["needs_rebuild_after"])
        self.assertEqual(part.rebuild_count, 1)

    def test_capture_view_requires_bmp_and_protects_existing_output(self) -> None:
        part = FakePart()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "view.bmp"
            result = capture_view(part, str(target), width=800, height=600)

            self.assertTrue(target.exists())
            self.assertGreater(result["bytes"], 0)
            self.assertEqual(part.zoom_count, 1)
            with self.assertRaisesRegex(ContractError, "already exists"):
                capture_view(part, str(target))
            with self.assertRaisesRegex(ContractError, "must end with .bmp"):
                capture_view(part, str(Path(directory) / "view.png"))


if __name__ == "__main__":
    unittest.main()

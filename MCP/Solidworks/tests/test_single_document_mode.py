import unittest

from solidworks_mcp.executor import SolidWorksExecutor


class FakeFeature:
    def __init__(self, name: str, type_name: str = "ProfileFeature") -> None:
        self.Name = name
        self._type_name = type_name

    def GetTypeName2(self) -> str:
        return self._type_name


class FakeDocument:
    def __init__(self, title: str, features: list[str], path: str = "", dirty: bool = False) -> None:
        self._title = title
        self._path = path
        self._dirty = dirty
        self._features = [FakeFeature(name) for name in features]

    def GetTitle(self) -> str:
        return self._title

    def GetPathName(self) -> str:
        return self._path

    def GetSaveFlag(self) -> bool:
        return self._dirty

    def GetFeatureCount(self) -> int:
        return len(self._features)

    def FeatureByPositionReverse(self, position: int) -> FakeFeature:
        return list(reversed(self._features))[position]


class FakeApp:
    def __init__(self, documents: list[FakeDocument]) -> None:
        self.documents = documents
        self.closed: list[str] = []

    def GetDocuments(self) -> list[FakeDocument]:
        return list(self.documents)

    def CloseDoc(self, title: str) -> None:
        self.closed.append(title)
        self.documents = [document for document in self.documents if document.GetTitle() != title]

    def GetDocumentCount(self) -> int:
        return len(self.documents)


class SingleDocumentModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.executor = SolidWorksExecutor()

    def tearDown(self) -> None:
        self.executor.session.close()

    def test_closes_previous_clean_mcp_document(self) -> None:
        app = FakeApp([
            FakeDocument("gear.sldprt", ["GearBlank", "InvoluteToothSketch"], "C:/gear.sldprt", False)
        ])
        self.assertEqual(self.executor._prepare_single_document_test(app), ["gear.sldprt"])
        self.assertEqual(app.GetDocumentCount(), 0)

    def test_refuses_to_close_user_document(self) -> None:
        app = FakeApp([FakeDocument("customer.sldprt", ["Boss-Extrude1"], "C:/customer.sldprt")])
        with self.assertRaisesRegex(RuntimeError, "user/unmanaged document"):
            self.executor._prepare_single_document_test(app)
        self.assertEqual(app.closed, [])

    def test_closes_owned_blank_document_without_feature_markers(self) -> None:
        app = FakeApp([FakeDocument("Part1", [])])
        self.executor._owned_document_titles.add("Part1")
        self.assertEqual(self.executor._prepare_single_document_test(app), ["Part1"])
        self.assertEqual(app.GetDocumentCount(), 0)

    def test_refuses_to_close_dirty_mcp_document(self) -> None:
        app = FakeApp([
            FakeDocument("edited-gear.sldprt", ["GearBlank"], "C:/edited-gear.sldprt", True)
        ])
        with self.assertRaisesRegex(RuntimeError, "unsaved changes"):
            self.executor._prepare_single_document_test(app)
        self.assertEqual(app.closed, [])


if __name__ == "__main__":
    unittest.main()

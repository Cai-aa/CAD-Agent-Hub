import tempfile
import unittest
from pathlib import Path

from solidworks_mcp.executor import _save_as


class _NativeModel:
    def __init__(self) -> None:
        self.extension_called = False
        self.Extension = self

    def SaveAs3(self, path: str, version: int, options: int) -> int:
        Path(path).write_bytes(b"native")
        return 0

    def SaveAs(self, *args):
        self.extension_called = True
        raise AssertionError("native saves must not use export SaveAs")


class _ExportExtension:
    def __init__(self) -> None:
        self.calls = 0

    def SaveAs(self, *args):
        self.calls += 1
        Path(args[0]).write_bytes(b"export")
        return True, 0, 0


class _ExportModel:
    def __init__(self) -> None:
        self.Extension = _ExportExtension()

    def SaveAs3(self, *args):
        raise AssertionError("foreign exports must not use native SaveAs3")


class SaveRoutingTests(unittest.TestCase):
    def test_native_document_uses_save_as_3_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "part.sldprt"
            model = _NativeModel()
            self.assertEqual(_save_as(model, target), (True, 0, 0))
            self.assertFalse(model.extension_called)

    def test_foreign_export_uses_extension_save_as_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "part.step"
            model = _ExportModel()
            self.assertEqual(_save_as(model, target), (True, 0, 0))
            self.assertEqual(model.Extension.calls, 1)


if __name__ == "__main__":
    unittest.main()

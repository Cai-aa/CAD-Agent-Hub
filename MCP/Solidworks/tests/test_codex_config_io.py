"""Regression coverage for the Windows CRCRLF configuration outage."""
import importlib.util
from pathlib import Path
import tempfile
import tomllib
import unittest

module_path = Path(__file__).resolve().parents[1] / "scripts/config_toml_io.py"
spec = importlib.util.spec_from_file_location("config_toml_io", module_path)
config_io = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_io)


class CodexConfigIOTests(unittest.TestCase):
    def test_windows_newlines_are_written_once_and_values_are_preserved(self):
        windows_path = chr(92).join(["C:", "Tools", "python.exe"])
        text = 'model = "sample"\r\n[mcp_servers.example]\r\ncommand = ' + "'" + windows_path + "'\r\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            original = b'model = "sample"\r\n'
            path.write_bytes(original)
            config_io.write_validated_config(path, text, expected_original=original)
            payload = path.read_bytes()
        self.assertNotIn(b"\r", payload)
        self.assertEqual(tomllib.loads(payload.decode()), tomllib.loads(text))

    def test_malformed_carriage_returns_do_not_replace_live_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            original = b'model = "sample"\n'
            path.write_bytes(original)
            with self.assertRaises(ValueError):
                config_io.write_validated_config(path, 'model = "sample"\r\r\n', expected_original=original)
            self.assertEqual(path.read_bytes(), original)

    def test_concurrent_edit_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            actual = b'model = "user-change"\n'
            path.write_bytes(actual)
            with self.assertRaises(RuntimeError):
                config_io.write_validated_config(path, 'model = "sample"\n', expected_original=b'')
            self.assertEqual(path.read_bytes(), actual)

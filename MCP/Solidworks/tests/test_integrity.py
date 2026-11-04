from __future__ import annotations

import contextvars
from dataclasses import replace
import math
import sys
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

from solidworks_mcp.com_runtime import SolidWorksSession, StaExecutor
from solidworks_mcp.config import Settings
from solidworks_mcp.contracts import ContractError, require_positive
from solidworks_mcp.executor import SolidWorksExecutor, _save_as, _raw_save_as
from solidworks_mcp.feature_graph import compile_feature_graph
from solidworks_mcp.interactive import (
    set_dimension,
    edit_sketch,
    _persist_token,
    _resolve_token,
)
from solidworks_mcp.native_features import rebuild
from solidworks_mcp.safety import CadProcessLock, SafetyError, fingerprint
from solidworks_mcp.verification import verify_model
from solidworks_mcp.inspection import activate_document
from test_interactive import FakeModel, FakeSketchModel


class SaveIntegrityTests(unittest.TestCase):
    def test_native_save_failure_survives_missing_com_fallback(self):
        model = SimpleNamespace(SaveAs3=lambda *args: 7, Extension=object())
        with patch.dict(sys.modules, {"pythoncom": None}):
            self.assertEqual(_raw_save_as(model, Path("part.sldprt")), (False, 7, 0))

    def test_existing_file_is_not_a_success_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "part.sldprt"
            target.write_bytes(b"old")
            called = []
            model = SimpleNamespace(SaveAs3=lambda *args: called.append(args))
            with self.assertRaises(ContractError):
                _save_as(model, target)
            self.assertEqual(called, [])
            self.assertEqual(target.read_bytes(), b"old")

    def test_failed_explicit_overwrite_restores_original(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "part.sldprt"
            target.write_bytes(b"old")

            def fail(path, *args):
                Path(path).write_bytes(b"partial")
                return 1

            with self.assertRaises(SafetyError):
                _save_as(SimpleNamespace(SaveAs3=fail), target, overwrite=True)
            self.assertEqual(target.read_bytes(), b"old")
            self.assertEqual(len(list((target.parent / ".swmcp-backups").iterdir())), 1)

    def test_failed_new_save_removes_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "part.sldprt"

            def fail(path, *args):
                Path(path).write_bytes(b"partial")
                return 7

            with self.assertRaises(SafetyError):
                _save_as(SimpleNamespace(SaveAs3=fail), target)
            self.assertFalse(target.exists())

    def test_api_success_without_file_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SafetyError):
                _save_as(
                    SimpleNamespace(SaveAs3=lambda *a: 0),
                    Path(directory) / "part.sldprt",
                )


class RuntimeIntegrityTests(unittest.TestCase):
    def session(self, path=None):
        session = SolidWorksSession(journal_path=path)
        session._application = object()
        self.addCleanup(session.close)
        return session

    def test_request_id_binds_operation_and_parameters(self):
        session = self.session()
        session.execute(
            "id", lambda app: {"ok": True}, operation="edit", parameters={"x": 1}
        )
        for op, params in [("delete", {"x": 1}), ("edit", {"x": 2})]:
            with self.assertRaisesRegex(SafetyError, "another operation"):
                session.execute("id", lambda app: {}, operation=op, parameters=params)

    def test_failure_is_not_reexecuted(self):
        session, changes = self.session(), []

        def action(app):
            changes.append(1)
            raise RuntimeError("after mutation")

        with self.assertRaises(RuntimeError):
            session.execute("id", action, operation="edit")
        with self.assertRaisesRegex(SafetyError, "Previous request failed"):
            session.execute("id", action, operation="edit")
        self.assertEqual(len(changes), 1)
        self.assertEqual(session.operation_result("id")["state"], "FAILED")

    def test_success_replays_across_session_restart_without_reexecution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.sqlite3"
            one = SolidWorksSession(journal_path=path)
            one._application = object()
            result = one.execute("id", lambda app: {"items": [1]}, operation="edit")
            result["items"].append(2)
            one.close()
            two = SolidWorksSession(journal_path=path)
            try:
                result = two.execute(
                    "id", lambda app: self.fail("must not reexecute"), operation="edit"
                )
                self.assertTrue(result["idempotent_replay"])
                self.assertEqual(result["items"], [1])
            finally:
                two.close()

    def test_abandoned_running_request_is_never_replayed(self):
        session = self.session()
        session._journal.put(
            "id", {"fingerprint": fingerprint("edit", {}), "state": "RUNNING"}
        )
        with self.assertRaises(SafetyError):
            session.execute(
                "id", lambda app: self.fail("unknown must not run"), operation="edit"
            )
        self.assertEqual(session.operation_result("id")["state"], "UNKNOWN")

    def test_simultaneous_admission_accepts_only_one(self):
        executor = StaExecutor()
        entered, release = threading.Event(), threading.Event()
        first = threading.Thread(
            target=lambda: executor.call(
                lambda: (entered.set(), release.wait(3)), reject_if_busy=True
            )
        )
        first.start()
        self.assertTrue(entered.wait(1))
        try:
            for _ in range(10):
                with self.assertRaises(SafetyError):
                    executor.call(lambda: None, reject_if_busy=True)
            with self.assertRaises(SafetyError):
                executor.close(timeout=0.01)
            self.assertFalse(executor.status()["closed"])
        finally:
            release.set()
            first.join(3)
            executor.close()
        with self.assertRaises(SafetyError):
            executor.call(lambda: None)

    def test_context_is_carried_to_sta(self):
        value = contextvars.ContextVar("test", default=None)
        value.set("document")
        executor = StaExecutor()
        try:
            self.assertEqual(executor.call(value.get), "document")
        finally:
            executor.close()

    def test_process_lock_excludes_another_executor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cad.lock"
            with CadProcessLock(path):
                with self.assertRaises(SafetyError):
                    with CadProcessLock(path):
                        self.fail("second owner admitted")


class BoundModel(FakeModel):
    def __init__(self, title="A.sldprt"):
        super().__init__()
        self.title = title
        self.ConfigurationManager = SimpleNamespace(
            ActiveConfiguration=SimpleNamespace(Name="Default")
        )
        self.Extension.StartRecordingUndoObject = lambda: None
        self.Extension.FinishRecordingUndoObject2 = lambda *args: True

    def GetTitle(self):
        return self.title

    def GetPathName(self):
        return "C:/models/" + self.title

    def GetType(self):
        return 1


class DocumentIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.executor = SolidWorksExecutor(
            replace(Settings(), operation_journal_path=None)
        )
        self.model = BoundModel()
        self.app = SimpleNamespace(ActiveDoc=self.model)
        self.executor.session._application = self.app
        self.addCleanup(self.executor.session.close)
        self.token = self.executor.bind_document("bind", self.model.title)[
            "document_token"
        ]

    def test_missing_token_refuses_edit(self):
        with self.assertRaisesRegex(SafetyError, "Bind the intended"):
            self.executor.set_dimension("edit", "D1@Boss1", 20)
        self.assertEqual(self.model.dimension.value, 0.01)

    def test_switching_document_refuses_edit(self):
        other = BoundModel("B.sldprt")
        self.app.ActiveDoc = other
        with self.assertRaisesRegex(SafetyError, "changed"):
            self.executor.set_dimension(
                "edit", "D1@Boss1", 20, document_token=self.token
            )
        self.assertEqual(other.dimension.value, 0.01)

    def test_switching_configuration_refuses_edit(self):
        self.model.ConfigurationManager.ActiveConfiguration.Name = "Other"
        with self.assertRaises(SafetyError):
            self.executor.set_dimension(
                "edit", "D1@Boss1", 20, document_token=self.token
            )

    def test_reopening_same_path_is_a_different_document(self):
        self.app.ActiveDoc = BoundModel()
        with self.assertRaises(SafetyError):
            self.executor.set_dimension(
                "edit", "D1@Boss1", 20, document_token=self.token
            )

    def test_duplicate_titles_cannot_be_activated_by_guessing(self):
        with self.assertRaisesRegex(ContractError, "ambiguous"):
            activate_document(self.app, self.model.title, [self.model, BoundModel()])

    def test_foreign_persistent_reference_never_enters_com_resolver(self):
        self.model.Extension.GetPersistReference3 = lambda entity: b"native-reference"
        token = _persist_token(self.model, object())
        other = BoundModel("B.sldprt")
        other.Extension.GetObjectByPersistReference3 = lambda *args: self.fail(
            "foreign reference entered COM"
        )
        with self.assertRaises(ContractError):
            _resolve_token(other, token)

    def test_creation_cannot_fall_back_to_an_unrelated_active_document(self):
        with tempfile.TemporaryDirectory() as directory:
            template = Path(directory) / "part.prtdot"
            template.write_text("template")
            self.executor.settings = replace(
                self.executor.settings, part_template=template
            )
            self.app.NewDocument = lambda *args: BoundModel("New.sldprt")
            with self.assertRaisesRegex(SafetyError, "just created"):
                self.executor._new_part_document(self.app)

    def test_explicit_bound_edit_succeeds(self):
        result = self.executor.set_dimension(
            "edit", "D1@Boss1", 20, document_token=self.token
        )
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(self.model.dimension.value, 0.02)

    def test_partial_failure_blocks_further_writes_and_rebinding(self):
        def failed_set(*args):
            self.model.dimension.value = 0.02
            raise RuntimeError("partial")

        self.model.dimension.SetSystemValue3 = failed_set
        with self.assertRaises(SafetyError):
            self.executor.set_dimension(
                "edit", "D1@Boss1", 20, document_token=self.token
            )
        with self.assertRaisesRegex(SafetyError, "Previous mutation failed"):
            self.executor.delete_feature("next", "Boss1", document_token=self.token)
        with self.assertRaises(SafetyError):
            self.executor.bind_document("rebind", self.model.title)
        result = self.executor.bind_document(
            "ack", self.model.title, acknowledge_partial_changes=True
        )
        self.assertNotEqual(result["document_token"], self.token)


class GeometryIntegrityTests(unittest.TestCase):
    def test_failed_replacement_never_deletes_old_sketch_first(self):
        model = FakeSketchModel()
        model.SketchManager.ActiveSketch = SimpleNamespace(
            GetSketchSegments=lambda: [object()]
        )
        with (
            patch("solidworks_mcp.interactive._select_by_id", return_value=True),
            patch(
                "solidworks_mcp.interactive._append_entities",
                side_effect=RuntimeError("creation failed"),
            ),
            patch(
                "solidworks_mcp.interactive._delete_active_sketch_segments"
            ) as deletion,
        ):
            with self.assertRaises(RuntimeError):
                edit_sketch(
                    model,
                    "Sketch1",
                    [{"kind": "circle", "radius_mm": 3}],
                    mode="replace",
                )
            deletion.assert_not_called()

    def test_extrusion_cannot_reference_a_new_part_as_its_sketch(self):
        with self.assertRaises(ContractError):
            compile_feature_graph(
                {
                    "version": "1.0",
                    "features": [
                        {"name": "Part", "kind": "new_part"},
                        {
                            "name": "Boss",
                            "kind": "boss_extrude",
                            "sketch": "Part",
                            "depth_mm": 2,
                        },
                    ],
                }
            )

    def test_nonfinite_dimensions_rejected(self):
        for value in [math.nan, math.inf, -math.inf]:
            with self.assertRaises(ContractError):
                require_positive(value, "size")
            with self.assertRaises(ContractError):
                set_dimension(FakeModel(), "D1@Boss1", value)

    def test_nonfinite_string_coordinates_rejected(self):
        graph = {
            "version": "1.0",
            "features": [
                {"name": "Part", "kind": "new_part"},
                {
                    "name": "Sketch",
                    "kind": "sketch",
                    "entities": [
                        {"kind": "circle", "center": ["nan", 0], "radius_mm": 1}
                    ],
                },
            ],
        }
        with self.assertRaises(ContractError):
            compile_feature_graph(graph)

    def test_graph_budget_enforced(self):
        with self.assertRaises(ContractError):
            compile_feature_graph(
                {
                    "version": "1.0",
                    "features": [
                        {"name": str(i), "kind": "new_part"} for i in range(257)
                    ],
                }
            )

    def test_failed_rebuild_is_failure(self):
        with self.assertRaises(RuntimeError):
            rebuild(
                SimpleNamespace(
                    ClearSelection2=lambda *a: None, EditRebuild3=lambda: False
                )
            )

    def test_dimension_api_error_is_failure(self):
        model = FakeModel()
        model.dimension.SetSystemValue3 = lambda *a: 2
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            set_dimension(model, "D1@Boss1", 20)

    def test_dimension_unchanged_after_api_success_is_failure(self):
        model = FakeModel()
        model.dimension.SetSystemValue3 = lambda *a: 0
        with self.assertRaisesRegex(RuntimeError, "readback"):
            set_dimension(model, "D1@Boss1", 20)

    def test_native_feature_error_refuses_verification(self):
        model = FakeModel()
        model.Extension.NeedsRebuild2 = False
        model.FeatureByName = lambda name: SimpleNamespace(GetErrorCode2=lambda *a: 7)
        with patch(
            "solidworks_mcp.verification.feature_names",
            return_value=[{"name": "Boss1"}],
        ):
            with self.assertRaisesRegex(SafetyError, "Native features"):
                verify_model(model, ["Boss1"])


if __name__ == "__main__":
    unittest.main()

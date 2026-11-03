from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any
from . import __version__

from .safety import (
    SafetyError,
    document_context,
    request_context,
    request_operation,
    same_com_object,
)
from .file_safety import protected_output
from .verification import verify_model, analytic_volume
from .com_runtime import SolidWorksSession
from .config import Settings
from .contracts import ContractError, require_text
from .feature_graph import compile_feature_graph
from .modeling_rules import review_feature_graph
from .gearbox import build_two_stage_reducer_graph
from .involute_gear import build_involute_gear_graph, validate_gear_spec
from .output_shaft import build_output_shaft_from_dwg_graph
from .interactive import (
    add_edge_feature,
    add_stepped_shaft_with_keyway,
    delete_feature,
    edit_sketch,
    inspect_relations,
    rollback,
    select_references,
    set_dimension,
    set_feature_parameter,
)
from .inspection import (
    activate_document as activate_open_document,
    capture_view as capture_model_view,
    get_bounding_box as inspect_bounding_box,
    get_mass_properties as inspect_mass_properties,
    list_documents as inspect_documents,
    rebuild_diagnostics as inspect_rebuild_diagnostics,
)
from .metadata import (
    activate_configuration as activate_model_configuration,
    assign_material as assign_model_material,
    create_configuration as create_model_configuration,
    get_custom_properties as inspect_custom_properties,
    get_material as inspect_model_material,
    list_configurations as inspect_configurations,
    list_material_databases as inspect_material_databases,
    set_custom_properties as write_custom_properties,
)
from .native_features import execute_plan, feature_names
from .part_generators import build_parametric_part_graph
from .primitives import build_sphere_graph

_EXPORT_TYPES = {
    ".step": 214,
    ".stp": 214,
    ".iges": 214,
    ".igs": 214,
    ".stl": 214,
    ".pdf": 214,
    ".dxf": 214,
    ".dwg": 214,
}

_MCP_FEATURE_MARKERS = {
    "GearBlankSketch",
    "GearBlank",
    "GearAxis",
    "InvoluteToothSketch",
    "SphereProfileSketch",
    "SphereRevolve",
    "AdjacentGearBlank",
    "AdjacentGearTeeth",
}

_NATIVE_DOCUMENT_EXTENSIONS = {".sldprt", ".sldasm", ".slddrw"}


def _com_value(obj: Any, name: str, *args: Any) -> Any:
    """Read a COM member regardless of whether pywin32 exposes it as a property or method."""
    member = getattr(obj, name)
    return member(*args) if callable(member) else member


def _raw_save_as(model: Any, target: Path) -> tuple[bool, int, int]:
    """Route native saves and foreign exports through separate COM paths."""
    if target.suffix.lower() in _NATIVE_DOCUMENT_EXTENSIONS:
        try:
            result = model.SaveAs3(str(target), 0, 1)
        except Exception as exc:
            raise RuntimeError(
                f"native SaveAs3 failed: {type(exc).__name__}: {exc}"
            ) from exc
        # Legacy ModelDoc2.SaveAs3 returns an integer error code, 0 on success.
        # A bool is a distinct binding contract and must not be inverted.
        if isinstance(result, bool) and result:
            return True,0,0
        if isinstance(result, int):
            if result == 0 and not isinstance(result,bool):
                return True,0,0
            import pythoncom
            from win32com.client import VARIANT
            errors=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
            warnings=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
            empty=VARIANT(pythoncom.VT_DISPATCH,None)
            for arguments in [(str(target),0,1,empty),(str(target),0,1,empty,0,0),(str(target),0,1,empty,errors,warnings)]:
                try:
                    value=model.Extension.SaveAs(*arguments)
                    if isinstance(value,tuple):
                        if bool(value[0]) and int(value[1])==0:
                            return True,0,int(value[2])
                        continue
                    if bool(value) and int(errors.value)==0:
                        return True,0,int(warnings.value)
                except Exception:
                    continue
            return False,int(result) or 1,0
        raise SafetyError("SAVE_CONTRACT", "Unrecognized native SaveAs3 return value")

    # makepy-generated wrappers accept plain integers for [out] parameters and
    # return (ok, errors, warnings); dynamic Dispatch requires explicit by-ref
    # VARIANTs. Support both because SolidWorks may return either proxy type.
    generated_errors: list[str] = []
    try:
        import pythoncom
        from win32com.client import VARIANT
        empty_export_data = VARIANT(pythoncom.VT_DISPATCH, None)
    except ImportError:
        empty_export_data = None
    for arguments in (
        (str(target), 0, 1, empty_export_data),
        (str(target), 0, 1, empty_export_data, 0, 0),
        (str(target), 0, 1, None),
        (str(target), 0, 1, None, 0, 0),
    ):
        try:
            result = model.Extension.SaveAs(*arguments)
            if isinstance(result, tuple):
                ok = bool(result[0])
                errors_value = int(result[1]) if len(result) > 1 else 0
                warnings_value = int(result[2]) if len(result) > 2 else 0
                return ok, errors_value, warnings_value
            return bool(result), 0, 0
        except Exception as exc:
            generated_errors.append(
                f"{len(arguments)} args: {type(exc).__name__}: {exc}"
            )
    try:
        import pythoncom  # type: ignore
        from win32com.client import VARIANT  # type: ignore

        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        ok = bool(model.Extension.SaveAs(str(target), 0, 1, empty_export_data, errors, warnings))
        return ok, int(errors.value), int(warnings.value)
    except Exception as exc:
        raise RuntimeError(
            "Export SaveAs binding attempts failed; "
            + "; ".join(generated_errors)
            + f"; dynamic by-ref: {type(exc).__name__}: {exc}"
        ) from exc


def _save_as(
    model: Any, target: Path, overwrite: bool = False
) -> tuple[bool, int, int]:
    with protected_output(target, overwrite):
        # SolidWorks exports selected entities only when a selection is active.
        # Always export the complete explicitly bound model.
        if target.suffix.lower() not in _NATIVE_DOCUMENT_EXTENSIONS:
            model.ClearSelection2(True)
        ok, errors, warnings = _raw_save_as(model, target)
        if not ok or errors:
            raise SafetyError(
                "SAVE_FAILED",
                f"SolidWorks save failed (errors={errors}, warnings={warnings})",
            )
    return True, 0, warnings


class SolidWorksExecutor:
    """Deterministic document operations. Never expose raw COM or arbitrary Python."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        # One-argument construction remains compatible with an already-running
        # pre-0.3 com_runtime module during hot reload. New runtimes expose the
        # timeout attribute and receive the configured value immediately.
        self.session = SolidWorksSession(
            self.settings.operation_cache_size,
            operation_timeout_seconds=self.settings.operation_timeout_seconds,
            journal_path=self.settings.operation_journal_path,
        )
        if hasattr(self.session, "_operation_timeout_seconds"):
            self.session._operation_timeout_seconds = getattr(
                self.settings, "operation_timeout_seconds", 180.0
            )
        # Keep the COM proxy on the STA-owned execution path. Some pywin32
        # bindings return a transient `ActiveDoc` after NewDocument, while the
        # returned ModelDoc proxy is valid and remains the authoritative handle.
        self._active_document: Any | None = None
        self._owned_document_titles: set[str] = set()
        self._bound_model = None
        self._bound_identity = None
        self._document_token = None
        self._recovery_required = False

    def _identity(self, model: Any) -> dict[str, Any]:
        path = str(_com_value(model, "GetPathName"))
        kind = int(_com_value(model, "GetType"))
        configuration = ""
        if kind in (1, 2):
            configuration = str(model.ConfigurationManager.ActiveConfiguration.Name)
        return {
            "path": os.path.normcase(os.path.abspath(path)) if path else "",
            "title": str(_com_value(model, "GetTitle")),
            "configuration": configuration,
            "document_type": kind,
        }

    def _bind_model(self, model: Any) -> dict[str, Any]:
        self._bound_model = model
        self._bound_identity = self._identity(model)
        self._document_token = str(uuid.uuid4())
        self._active_document = model
        return {
            "document_token": self._document_token,
            "document_identity": self._bound_identity.copy(),
        }

    def _active_model(self, app: Any) -> Any:
        model = getattr(app, "ActiveDoc", None)
        context = request_context.get()
        if context and context["mutating"]:
            token = document_context.get()
            if (
                not token
                or token != self._document_token
                or model is None
                or self._bound_model is None
            ):
                raise SafetyError(
                    "DOCUMENT_NOT_BOUND",
                    "Bind the intended active document and supply its document_token",
                )
            if (
                not same_com_object(model, self._bound_model)
                or self._identity(model) != self._bound_identity
            ):
                raise SafetyError(
                    "DOCUMENT_CHANGED",
                    "Active document or configuration changed; write refused",
                )
            if self._recovery_required:
                raise SafetyError(
                    "RECOVERY_REQUIRED",
                    "Previous mutation failed; inspect and explicitly acknowledge partial changes when rebinding",
                )
        return model

    @request_operation
    def bind_document(
        self,
        request_id: str,
        title: str,
        expected_path: str | None = None,
        acknowledge_partial_changes: bool = False,
    ) -> dict[str, Any]:
        def action(app):
            model = getattr(app, "ActiveDoc", None)
            if model is None or str(_com_value(model, "GetTitle")) != require_text(
                title, "title"
            ):
                raise SafetyError(
                    "DOCUMENT_CHANGED",
                    "The exact intended title is not the active document",
                )
            if expected_path is not None:
                actual = self._identity(model)["path"]
                if actual != os.path.normcase(os.path.abspath(expected_path)):
                    raise SafetyError(
                        "DOCUMENT_CHANGED",
                        "The active document path does not match expected_path",
                    )
            if self._recovery_required and not acknowledge_partial_changes:
                raise SafetyError(
                    "RECOVERY_REQUIRED",
                    "Inspect the failed edit before acknowledging partial changes",
                )
            self._recovery_required = False
            return {"ok": True, **self._bind_model(model)}

        return self.session.execute(request_id, action)

    def _new_part_document(self, app: Any) -> Any:
        template = self.settings.part_template
        if not template.exists():
            raise ContractError(f"SolidWorks part template does not exist: {template}")
        created_model = app.NewDocument(str(template), 0, 0.0, 0.0)
        if created_model is None:
            raise RuntimeError("SolidWorks returned no document from NewDocument")
        # NewDocument can return a narrow transient dispatch proxy. Reacquiring
        # ActiveDoc yields the documented IModelDoc2 interface (SketchManager,
        # FeatureManager, SelectionManager) on late-bound pywin32 hosts.
        active_model = getattr(app, "ActiveDoc", None)
        if active_model is not None and not same_com_object(
            active_model, created_model
        ):
            raise SafetyError(
                "DOCUMENT_CHANGED",
                "Active document is not the document just created; modeling refused",
            )
        model = active_model or created_model
        self._active_document = model
        try:
            self._owned_document_titles.add(str(_com_value(model, "GetTitle")))
        except Exception:
            pass
        return model

    def _open_documents(self, app: Any) -> list[Any]:
        try:
            documents = _com_value(app, "GetDocuments") or []
            if isinstance(documents, (list, tuple)):
                return list(documents)
            return [documents]
        except (AttributeError, TypeError):
            # Some makepy-generated SolidWorks 2025 wrappers omit the array-returning
            # ISldWorks.GetDocuments member. Walk the documented ModelDoc2 linked list
            # instead so single-document safety checks still inspect every open file.
            documents = []
            document = _com_value(app, "GetFirstDocument")
            seen: set[int] = set()
            while document is not None:
                identity = id(document)
                if identity in seen:
                    raise RuntimeError("SolidWorks document enumeration returned a cycle")
                seen.add(identity)
                documents.append(document)
                document = _com_value(document, "GetNext")
            return documents

    def _require_active_instance(self, app: Any, model: Any) -> None:
        if not same_com_object(getattr(app, "ActiveDoc", None), model):
            raise SafetyError(
                "DOCUMENT_CHANGED",
                "Active document changed during execution; operation stopped",
            )

    def _document_path(self, document: Any) -> str:
        try:
            return str(_com_value(document, "GetPathName"))
        except Exception:
            return ""

    def _document_is_dirty(self, document: Any) -> bool:
        try:
            return bool(_com_value(document, "GetSaveFlag"))
        except Exception:
            # Unknown state must be treated as dirty; closing would risk data loss.
            return True

    def _prepare_single_document_test(self, app: Any) -> list[str]:
        """Leave zero open documents before a test without touching user work."""
        if self._open_documents(app):
            raise ContractError(
                "Single-document mode requires zero open documents; automatic document closing has been removed"
            )
        return []

    def _close_failed_document(self, app: Any, model: Any) -> None:
        try:
            try:
                title = str(_com_value(model, "GetTitle"))
                matching = [
                    document
                    for document in self._open_documents(app)
                    if str(_com_value(document, "GetTitle")) == title
                ]
                if len(matching) != 1 or not same_com_object(matching[0], model):
                    return  # Never close a different model merely sharing a title.
                app.CloseDoc(title)
                self._owned_document_titles.discard(title)
            except Exception:
                # Never mask the original modeling failure with cleanup errors.
                pass
        finally:
            if self._active_document is model:
                self._active_document = None

    def health_check(self) -> dict[str, Any]:
        part_template = self.settings.part_template
        return {
            "ok": True,
            "version": __version__,
            "document_binding_required": True,
            "runtime_reload_enabled": False,
            "platform": "Windows required",
            "part_template": str(part_template),
            "part_template_exists": part_template.exists(),
            "state_version": self.session.state_version,
            "operation_timeout_seconds": getattr(
                self.settings, "operation_timeout_seconds", 180.0
            ),
            "interactive_mode": getattr(self.settings, "interactive_mode", True),
            "single_document_mode": getattr(
                self.settings, "single_document_mode", False
            ),
            "verify_feature_tree": getattr(self.settings, "verify_feature_tree", False),
            "redraw_after_operation": getattr(
                self.settings, "redraw_after_operation", False
            ),
            "executor_status": self.session.status(),
            "architecture": "MCP adapter -> validated operations -> serialized STA COM executor",
        }

    def operation_status(self) -> dict[str, Any]:
        return {"ok": True, **self.session.status()}

    def connect(self, start_if_missing: bool = False) -> dict[str, Any]:
        return self.session.connect(self.settings.visible, start_if_missing)

    @request_operation
    def list_documents(self, request_id: str) -> dict[str, Any]:
        def action(app: Any) -> dict[str, Any]:
            active = self._active_model(app)
            return {
                "operation": "list_documents",
                **inspect_documents(self._open_documents(app), active),
            }

        return self.session.execute(request_id, action)

    @request_operation
    def activate_document(self, request_id: str, title: str) -> dict[str, Any]:
        title = require_text(title, "title")

        def action(app: Any) -> dict[str, Any]:
            result = activate_open_document(app, title, self._open_documents(app))
            self._active_document = getattr(app, "ActiveDoc", None)
            return result

        return self.session.execute(request_id, action)

    @request_operation
    def get_bounding_box(
        self, request_id: str, include_hidden: bool = True
    ) -> dict[str, Any]:
        def action(app: Any) -> dict[str, Any]:
            model = self._active_model(app)
            if model is None:
                raise ContractError("No active SolidWorks document")
            return {
                "operation": "get_bounding_box",
                **inspect_bounding_box(model, include_hidden),
            }

        return self.session.execute(request_id, action)

    @request_operation
    def get_mass_properties(self, request_id: str) -> dict[str, Any]:
        def action(app: Any) -> dict[str, Any]:
            model = self._active_model(app)
            if model is None:
                raise ContractError("No active SolidWorks document")
            return {
                "operation": "get_mass_properties",
                **inspect_mass_properties(model),
            }

        return self.session.execute(request_id, action)

    @request_operation
    def rebuild_diagnostics(
        self,
        request_id: str,
        perform_rebuild: bool = False,
        full_rebuild: bool = False,
    ) -> dict[str, Any]:
        def action(app: Any) -> dict[str, Any]:
            model = self._active_model(app)
            if model is None:
                raise ContractError("No active SolidWorks document")
            return inspect_rebuild_diagnostics(
                model,
                perform_rebuild=perform_rebuild,
                full_rebuild=full_rebuild,
            )

        return self.session.execute(request_id, action)

    @request_operation
    def capture_view(
        self,
        request_id: str,
        output_path: str,
        width: int = 1600,
        height: int = 900,
        fit_view: bool = True,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        def action(app: Any) -> dict[str, Any]:
            model = self._active_model(app)
            if model is None:
                raise ContractError("No active SolidWorks document")
            return capture_model_view(
                model,
                output_path,
                width=width,
                height=height,
                fit_view=fit_view,
                overwrite=overwrite,
            )

        return self.session.execute(request_id, action)

    @request_operation
    def list_configurations(self, request_id: str) -> dict[str, Any]:
        def action(app: Any) -> dict[str, Any]:
            model = self._active_model(app)
            if model is None:
                raise ContractError("No active SolidWorks document")
            return {"operation": "list_configurations", **inspect_configurations(model)}

        return self.session.execute(request_id, action)

    @request_operation
    def activate_configuration(
        self, request_id: str, configuration_name: str
    ) -> dict[str, Any]:
        return self._execute_on_active(
            request_id,
            "activate_configuration",
            lambda model: activate_model_configuration(model, configuration_name),
        )

    @request_operation
    def create_configuration(
        self,
        request_id: str,
        configuration_name: str,
        comment: str = "",
        alternate_name: str = "",
        activate: bool = True,
    ) -> dict[str, Any]:
        return self._execute_on_active(
            request_id,
            "create_configuration",
            lambda model: create_model_configuration(
                model,
                configuration_name,
                comment=comment,
                alternate_name=alternate_name,
                activate=activate,
            ),
        )

    @request_operation
    def get_custom_properties(
        self,
        request_id: str,
        configuration_name: str | None = None,
    ) -> dict[str, Any]:
        def action(app: Any) -> dict[str, Any]:
            model = self._active_model(app)
            if model is None:
                raise ContractError("No active SolidWorks document")
            return {
                "operation": "get_custom_properties",
                **inspect_custom_properties(model, configuration_name),
            }

        return self.session.execute(request_id, action)

    @request_operation
    def set_custom_properties(
        self,
        request_id: str,
        properties: dict[str, Any],
        configuration_name: str | None = None,
    ) -> dict[str, Any]:
        return self._execute_on_active(
            request_id,
            "set_custom_properties",
            lambda model: write_custom_properties(
                model, properties, configuration_name
            ),
        )

    @request_operation
    def list_material_databases(self, request_id: str) -> dict[str, Any]:
        def action(app: Any) -> dict[str, Any]:
            return {
                "operation": "list_material_databases",
                **inspect_material_databases(app),
            }

        return self.session.execute(request_id, action)

    @request_operation
    def get_material(
        self,
        request_id: str,
        configuration_name: str | None = None,
    ) -> dict[str, Any]:
        def action(app: Any) -> dict[str, Any]:
            model = self._active_model(app)
            if model is None:
                raise ContractError("No active SolidWorks document")
            return {
                "operation": "get_material",
                **inspect_model_material(model, configuration_name),
            }

        return self.session.execute(request_id, action)

    @request_operation
    def assign_material(
        self,
        request_id: str,
        database_path: str,
        material_name: str,
        configuration_name: str | None = None,
        rebuild: bool = True,
    ) -> dict[str, Any]:
        return self._execute_on_active(
            request_id,
            "assign_material",
            lambda model: assign_model_material(
                model, database_path, material_name, configuration_name, rebuild=rebuild
            ),
        )

    @request_operation
    def new_part(self, request_id: str, title: str = "Part") -> dict[str, Any]:
        title = require_text(title, "title")
        template = self.settings.part_template
        if not template.exists():
            raise ContractError(f"SolidWorks part template does not exist: {template}")

        def action(app: Any) -> dict[str, Any]:
            # NewDocument(template, paper_size, width, height) is more reliable than NewPart().
            closed_previous = (
                self._prepare_single_document_test(app)
                if self.settings.single_document_mode
                else []
            )
            model = self._new_part_document(app)
            # Document title is read-only in this COM binding. The requested title is
            # retained as intent; it becomes the file title when `save_active(path)` runs.
            return {
                "ok": True,
                "document_title": str(_com_value(model, "GetTitle")),
                "requested_title": title,
                **self._bind_model(model),
                "operation": "new_part",
                "single_document_test_mode": getattr(
                    self.settings, "single_document_mode", False
                ),
                "closed_previous_documents": closed_previous,
            }

        return self.session.execute(request_id, action)

    @request_operation
    def execute_feature_graph(
        self,
        request_id: str,
        feature_graph: dict[str, Any],
        output_path: str,
    ) -> dict[str, Any]:
        plan = compile_feature_graph(feature_graph)
        planning_review = review_feature_graph(feature_graph,plan)
        target = Path(require_text(output_path, "output_path")).expanduser().resolve()
        if target.suffix.lower() != ".sldprt":
            raise ContractError("output_path must end in .sldprt")

        def action(app: Any) -> dict[str, Any]:
            if target.exists():
                raise ContractError(f"Output already exists: {target}")
            strict_single_document = getattr(
                self.settings, "single_document_mode", False
            )
            closed_previous = (
                self._prepare_single_document_test(app)
                if strict_single_document
                else []
            )
            model = self._new_part_document(app)
            try:
                steps = execute_plan(
                    model,
                    plan,
                    full_rebuild=not getattr(self.settings, "interactive_mode", True),
                    redraw=getattr(self.settings, "redraw_after_operation", False),
                    before_step=lambda: self._require_active_instance(app, model),
                    application=app,
                )
                verification = verify_model(
                    model,
                    [step["name"] for step in plan[1:]],
                    analytic_volume(feature_graph.get("metadata", {})),
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    self._require_active_instance(app, model)
                    ok, errors, warnings = _save_as(model, target)
                except Exception as exc:
                    raise RuntimeError(
                        f"Native SaveAs call failed: {type(exc).__name__}: {exc}"
                    ) from exc
                if not ok:
                    raise RuntimeError(
                        f"SolidWorks SaveAs failed after feature execution "
                        f"(errors={errors}, warnings={warnings})"
                    )
                if not target.exists() or target.stat().st_size <= 0:
                    raise RuntimeError(
                        f"SolidWorks reported success but output is missing: {target}"
                    )
                verify_tree = True
                tree = verification["features"]
                if verify_tree:
                    missing = [
                        step["name"]
                        for step in plan[1:]
                        if step["name"] not in {item["name"] for item in tree}
                    ]
                    if missing:
                        raise RuntimeError(
                            f"Native feature tree is missing expected features: {missing}"
                        )
                return {
                    "ok": True,
                    "operation": "execute_feature_graph",
                    "planning_review": planning_review,
                    "path": str(target),
                    "bytes": target.stat().st_size,
                    "warnings": warnings,
                    "steps": steps,
                    "features": tree
                    if verify_tree
                    else [step["name"] for step in plan[1:]],
                    "feature_tree_verified": verify_tree,
                    "verification": verification,
                    **self._bind_model(model),
                    "metadata": feature_graph.get("metadata", {}),
                    "single_document_test_mode": strict_single_document,
                    "closed_previous_documents": closed_previous,
                }
            except Exception:
                self._close_failed_document(app, model)
                raise

        return self.session.execute(request_id, action)

    def _execute_on_active(
        self,
        request_id: str,
        operation: str,
        action: Any,
    ) -> dict[str, Any]:
        def run(app: Any) -> dict[str, Any]:
            model = self._active_model(app)
            if model is None:
                raise RuntimeError("No active SolidWorks document")
            context = request_context.get()
            geometry_edit = operation in {
                "set_dimension",
                "set_feature_parameter",
                "edit_sketch",
                "delete_feature",
                "add_edge_feature",
                "add_stepped_shaft_with_keyway",
            }
            recording = False
            if geometry_edit:
                # StartRecordingUndoObject is void, unlike FinishRecordingUndoObject2.
                _com_value(model.Extension, "StartRecordingUndoObject")
                recording = True
            try:
                result = action(model)
                self._require_active_instance(app, model)
                if geometry_edit:
                    if not _com_value(
                        model.Extension,
                        "FinishRecordingUndoObject2",
                        "SolidWorks MCP edit",
                        False,
                    ):
                        raise SafetyError(
                            "UNDO_INCOMPLETE", "Cannot finalize undo group"
                        )
                    recording = False
                # Refresh path/configuration after an intentional change, keeping
                # the per-call token stable until the next explicit binding.
                if context and context["mutating"]:
                    self._bound_identity = self._identity(model)
                return {"operation": operation, **result}
            except Exception as exc:
                if context and context["mutating"]:
                    self._recovery_required = True
                if recording:
                    try:
                        _com_value(
                            model.Extension,
                            "FinishRecordingUndoObject2",
                            "Failed MCP edit - inspect before undo",
                            False,
                        )
                    except Exception:
                        pass
                # Never blindly undo: an empty/unsupported group could undo the
                # user's preceding edit. Preserve it for explicit recovery.
                raise SafetyError(
                    "MUTATION_FAILED",
                    str(exc),
                    partial_changes_possible=True,
                    automatic_retry=False,
                    recovery_required=True,
                ) from exc

        return self.session.execute(request_id, run)

    @request_operation
    def set_dimension(
        self,
        request_id: str,
        dimension_name: str,
        value: float,
        unit: str = "mm",
        configuration: str = "this",
        configuration_names: list[str] | None = None,
        rebuild: bool = True,
    ) -> dict[str, Any]:
        return self._execute_on_active(
            request_id,
            "set_dimension",
            lambda model: set_dimension(
                model,
                dimension_name,
                value,
                unit,
                configuration,
                configuration_names,
                rebuild,
            ),
        )

    @request_operation
    def set_feature_parameter(
        self,
        request_id: str,
        feature_name: str,
        parameter_name: str,
        value: float,
        unit: str = "mm",
        configuration: str = "this",
        rebuild: bool = True,
    ) -> dict[str, Any]:
        return self._execute_on_active(
            request_id,
            "set_feature_parameter",
            lambda model: set_feature_parameter(
                model, feature_name, parameter_name, value, unit, configuration, rebuild
            ),
        )

    @request_operation
    def edit_sketch(
        self,
        request_id: str,
        sketch_name: str,
        entities: list[dict[str, Any]],
        mode: str = "append",
        rebuild: bool = True,
    ) -> dict[str, Any]:
        return self._execute_on_active(
            request_id,
            "edit_sketch",
            lambda model: edit_sketch(model, sketch_name, entities, mode, rebuild),
        )

    @request_operation
    def delete_feature(
        self,
        request_id: str,
        feature_name: str,
        delete_children: bool = False,
        delete_absorbed: bool = False,
        rebuild: bool = True,
    ) -> dict[str, Any]:
        return self._execute_on_active(
            request_id,
            "delete_feature",
            lambda model: delete_feature(
                model,
                feature_name,
                delete_children=delete_children,
                delete_absorbed=delete_absorbed,
                rebuild=rebuild,
            ),
        )

    @request_operation
    def rollback(
        self,
        request_id: str,
        location: str,
        feature_name: str | None = None,
    ) -> dict[str, Any]:
        return self._execute_on_active(
            request_id,
            "rollback",
            lambda model: rollback(model, location, feature_name),
        )

    @request_operation
    def inspect_relations(
        self,
        request_id: str,
        include_topology: bool = True,
        include_persistent_references: bool = True,
        limit: int = 200,
    ) -> dict[str, Any]:
        return self._execute_on_active(
            request_id,
            "inspect_relations",
            lambda model: inspect_relations(
                model,
                include_topology=include_topology,
                include_persistent_references=include_persistent_references,
                limit=limit,
            ),
        )

    @request_operation
    def select_references(
        self,
        request_id: str,
        reference_tokens: list[str],
    ) -> dict[str, Any]:
        return self._execute_on_active(
            request_id,
            "select_references",
            lambda model: select_references(model, reference_tokens),
        )

    @request_operation
    def add_edge_feature(
        self,
        request_id: str,
        kind: str,
        feature_name: str,
        reference_tokens: list[str],
        size_mm: float,
        angle_deg: float = 45.0,
        rebuild: bool = True,
    ) -> dict[str, Any]:
        return self._execute_on_active(
            request_id,
            "add_edge_feature",
            lambda model: add_edge_feature(
                model,
                kind,
                feature_name,
                reference_tokens,
                size_mm,
                angle_deg,
                rebuild,
            ),
        )

    @request_operation
    def add_stepped_shaft_with_keyway(
        self,
        request_id: str,
        **parameters: Any,
    ) -> dict[str, Any]:
        return self._execute_on_active(
            request_id,
            "add_stepped_shaft_with_keyway",
            lambda model: add_stepped_shaft_with_keyway(model, **parameters),
        )

    @request_operation
    def create_parametric_part(
        self,
        request_id: str,
        part_type: str,
        parameters: dict[str, Any],
        output_path: str,
    ) -> dict[str, Any]:
        graph = build_parametric_part_graph(part_type, parameters)
        return self.execute_feature_graph(request_id, graph, output_path)

    @request_operation
    def create_involute_spur_gear(
        self,
        request_id: str,
        output_path: str,
        tooth_count: int = 20,
        module_mm: float = 2.0,
        pressure_angle_deg: float = 20.0,
        thickness_mm: float = 10.0,
        bore_diameter_mm: float = 10.0,
        root_fillet_mm: float = 0.45,
        tip_chamfer_mm: float = 0.25,
    ) -> dict[str, Any]:
        spec = validate_gear_spec(
            module_mm=module_mm,
            tooth_count=tooth_count,
            pressure_angle_deg=pressure_angle_deg,
            thickness_mm=thickness_mm,
            bore_diameter_mm=bore_diameter_mm,
            root_fillet_mm=root_fillet_mm,
            tip_chamfer_mm=tip_chamfer_mm,
        )
        graph = build_involute_gear_graph(spec, include_finishing=False)
        result = self.execute_feature_graph(request_id, graph, output_path)
        result["finishing_features_applied"] = False
        result["finishing_note"] = (
            "Root fillet and tip chamfer were skipped because this SolidWorks "
            "late-bound COM host does not expose the required finishing member reliably."
        )
        return result

    @request_operation
    def create_two_stage_reducer(
        self,
        request_id: str,
        output_path: str,
        **parameters: Any,
    ) -> dict[str, Any]:
        graph = build_two_stage_reducer_graph(**parameters)
        return self.execute_feature_graph(request_id, graph, output_path)

    @request_operation
    def create_output_shaft_from_dwg(
        self,
        request_id: str,
        output_path: str,
    ) -> dict[str, Any]:
        return self.execute_feature_graph(
            request_id,
            build_output_shaft_from_dwg_graph(),
            output_path,
        )

    @request_operation
    def create_sphere(
        self,
        request_id: str,
        output_path: str,
        diameter_mm: float = 50.0,
    ) -> dict[str, Any]:
        graph = build_sphere_graph(diameter_mm)
        return self.execute_feature_graph(request_id, graph, output_path)

    @request_operation
    def open_document(self, request_id: str, path: str) -> dict[str, Any]:
        source = Path(require_text(path, "path")).expanduser().resolve()
        if not source.is_file():
            raise ContractError(f"document does not exist: {source}")
        # SolidWorks imports STEP as a part document; after import it can be
        # persisted as native .sldprt through save_active().
        doc_type = {
            ".sldprt": 1,
            ".sldasm": 2,
            ".slddrw": 3,
            ".step": 1,
            ".stp": 1,
        }.get(source.suffix.lower())
        if doc_type is None:
            raise ContractError(
                "path must end in .sldprt, .sldasm, .slddrw, .step, or .stp"
            )

        def action(app: Any) -> dict[str, Any]:
            # Errors/warnings are by-ref I4 values; integer placeholders produce
            # a type-mismatch error under the pywin32 binding on this host.
            import pythoncom  # type: ignore
            from win32com.client import VARIANT  # type: ignore

            errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            if source.suffix.lower() in {".step", ".stp"}:
                # STEP is a foreign-format import, not a native OpenDoc6 path.
                # "r" requests direct import and prevents an interactive dialog
                # from blocking the headless stdio MCP session.
                import_data = app.GetImportFileData(str(source))
                if import_data is None:
                    raise RuntimeError(
                        f"SolidWorks could not create STEP import settings: {source}"
                    )
                model = app.LoadFile4(str(source), "r", import_data, errors)
            else:
                model = app.OpenDoc6(str(source), doc_type, 1, "", errors, warnings)
            if model is None:
                raise RuntimeError(f"SolidWorks failed to load: {source}")
            self._active_document = model
            binding = self._bind_model(model)
            return {
                **binding,
                "ok": True,
                "document_title": str(_com_value(model, "GetTitle")),
                "path": str(source),
                "operation": "open_document",
            }

        return self.session.execute(request_id, action)

    @request_operation
    def save_active(
        self, request_id: str, path: str | None = None, overwrite: bool = False
    ) -> dict[str, Any]:
        target = Path(path).expanduser().resolve() if path else None

        def action(app: Any) -> dict[str, Any]:
            model = self._active_model(app)
            if model is None:
                raise RuntimeError("No active SolidWorks document")
            actual_target = target or Path(str(_com_value(model, "GetPathName")))
            if not path and not str(_com_value(model, "GetPathName")):
                raise ContractError("path is required when saving an unsaved document")
            actual_target.parent.mkdir(parents=True, exist_ok=True)
            if actual_target.suffix.lower() not in _NATIVE_DOCUMENT_EXTENSIONS:
                raise ContractError(
                    "save_active requires a native SolidWorks extension"
                )
            expected_suffix = {1: ".sldprt", 2: ".sldasm", 3: ".slddrw"}[
                int(_com_value(model, "GetType"))
            ]
            if actual_target.suffix.lower() != expected_suffix:
                raise ContractError(
                    "Native output extension does not match the active document type"
                )
            verification = verify_model(model)
            self._active_model(app)  # Recheck after the multi-call verification.
            ok, errors, warnings = _save_as(model, actual_target, overwrite)
            self._bound_identity = self._identity(model)
            if not ok:
                raise RuntimeError(
                    f"SolidWorks SaveAs failed (errors={errors}, warnings={warnings})"
                )
            if not actual_target.exists():
                raise RuntimeError(
                    f"SolidWorks SaveAs reported success but file is missing: {actual_target}"
                )
            return {
                "ok": True,
                "path": str(actual_target),
                "bytes": actual_target.stat().st_size,
                "warnings": warnings,
                "operation": "save",
                "verification": verification,
            }

        return self.session.execute(request_id, action)

    @request_operation
    def export_active(
        self, request_id: str, path: str, overwrite: bool = False
    ) -> dict[str, Any]:
        target = Path(require_text(path, "path")).expanduser().resolve()
        if target.suffix.lower() not in _EXPORT_TYPES:
            raise ContractError(
                "export extension must be STEP/STP/IGES/IGS/STL/PDF/DXF/DWG"
            )

        def action(app: Any) -> dict[str, Any]:
            model = self._active_model(app)
            if model is None:
                raise RuntimeError("No active SolidWorks document")
            target.parent.mkdir(parents=True, exist_ok=True)
            verification = verify_model(model)
            self._active_model(app)
            ok, errors, warnings = _save_as(model, target, overwrite)
            if not ok or not target.exists():
                raise RuntimeError(
                    f"SolidWorks export failed (errors={errors}, warnings={warnings}): {target}"
                )
            return {
                "ok": True,
                "path": str(target),
                "bytes": target.stat().st_size,
                "warnings": warnings,
                "operation": "export",
                "verification": verification,
            }

        return self.session.execute(request_id, action)

    @request_operation
    def create_spur_gear(
        self,
        request_id: str,
        output_path: str,
        tooth_count: int = 20,
        module_mm: float = 2.0,
        thickness_mm: float = 10.0,
        bore_diameter_mm: float = 10.0,
    ) -> dict[str, Any]:
        raise ContractError(
            "Conceptual non-involute gear execution is retired; use create_involute_spur_gear"
        )

    @request_operation
    def inspect_active(
        self, request_id: str, include_features: bool = False
    ) -> dict[str, Any]:
        def action(app: Any) -> dict[str, Any]:
            try:
                open_document_count = int(_com_value(app, "GetDocumentCount"))
            except (AttributeError, TypeError):
                open_document_count = len(self._open_documents(app))
            model = self._active_model(app)
            if model is None:
                return {
                    "ok": True,
                    "active_document": False,
                    "open_document_count": open_document_count,
                    "operation": "inspect",
                }
            result = {
                "ok": True,
                "active_document": True,
                "open_document_count": open_document_count,
                "title": str(_com_value(model, "GetTitle")),
                "document_type": int(_com_value(model, "GetType")),
                "operation": "inspect",
            }
            try:
                result["path"] = str(_com_value(model, "GetPathName"))
            except Exception:
                result["path"] = ""
            # Feature tree reads are intentionally opt-in: some third-party
            # add-ins block FirstFeature() during document rebuild. Metadata is
            # enough for the default verification gate and remains fast/reliable.
            if include_features:
                result["features"] = feature_names(model)
            if self._document_token and self._bound_model is not None:
                if getattr(model, "_oleobj_", model) == getattr(
                    self._bound_model, "_oleobj_", self._bound_model
                ):
                    if self._identity(model) == self._bound_identity:
                        result["document_token"] = self._document_token
            result["recovery_required"] = self._recovery_required
            return result

        return self.session.execute(request_id, action)

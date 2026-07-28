from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .com_runtime import SolidWorksSession
from .config import Settings
from .contracts import ContractError, require_positive, require_text
from .feature_graph import compile_feature_graph
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
from .native_features import execute_plan, feature_names
from .part_generators import build_parametric_part_graph
from .primitives import build_sphere_graph

_EXPORT_TYPES = {
    ".step": 214, ".stp": 214, ".iges": 214, ".igs": 214, ".stl": 214,
    ".pdf": 214, ".dxf": 214, ".dwg": 214,
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


def _save_as(model: Any, target: Path) -> tuple[bool, int, int]:
    """Route native saves and foreign exports through separate COM paths."""
    if target.suffix.lower() in _NATIVE_DOCUMENT_EXTENSIONS:
        try:
            result = model.SaveAs3(str(target), 0, 1)
        except Exception as exc:
            raise RuntimeError(f"native SaveAs3 failed: {type(exc).__name__}: {exc}") from exc
        if target.exists() and target.stat().st_size > 0:
            return True, 0, 0
        return bool(result), 0 if result else 1, 0

    # makepy-generated wrappers accept plain integers for [out] parameters and
    # return (ok, errors, warnings); dynamic Dispatch requires explicit by-ref
    # VARIANTs. Support both because SolidWorks may return either proxy type.
    generated_errors: list[str] = []
    for arguments in (
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
            generated_errors.append(f"{len(arguments)} args: {type(exc).__name__}: {exc}")
    try:
        import pythoncom  # type: ignore
        from win32com.client import VARIANT  # type: ignore
        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        ok = bool(model.Extension.SaveAs(str(target), 0, 1, None, errors, warnings))
        return ok, int(errors.value), int(warnings.value)
    except Exception as exc:
        raise RuntimeError(
            "Export SaveAs binding attempts failed; " + "; ".join(generated_errors)
            + f"; dynamic by-ref: {type(exc).__name__}: {exc}"
        ) from exc


class SolidWorksExecutor:
    """Deterministic document operations. Never expose raw COM or arbitrary Python."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        # One-argument construction remains compatible with an already-running
        # pre-0.3 com_runtime module during hot reload. New runtimes expose the
        # timeout attribute and receive the configured value immediately.
        self.session = SolidWorksSession(self.settings.operation_cache_size)
        if hasattr(self.session, "_operation_timeout_seconds"):
            self.session._operation_timeout_seconds = getattr(
                self.settings, "operation_timeout_seconds", 180.0
            )
        # Keep the COM proxy on the STA-owned execution path. Some pywin32
        # bindings return a transient `ActiveDoc` after NewDocument, while the
        # returned ModelDoc proxy is valid and remains the authoritative handle.
        self._active_document: Any | None = None
        self._owned_document_titles: set[str] = set()

    def _active_model(self, app: Any) -> Any:
        return getattr(app, "ActiveDoc", None) or self._active_document

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
        closed: list[str] = []
        try:
            documents = self._open_documents(app)
        except Exception as exc:
            raise RuntimeError(
                f"Single-document test mode could not enumerate open documents: {exc}"
            ) from exc

        blockers: list[str] = []
        for document in documents:
            try:
                title = str(_com_value(document, "GetTitle"))
                path = self._document_path(document)
                names = {item["name"] for item in feature_names(document)}
                is_mcp_document = bool(names.intersection(_MCP_FEATURE_MARKERS)) or title in self._owned_document_titles
                if not is_mcp_document:
                    blockers.append(f"{title} (user/unmanaged document)")
                    continue
                if path and self._document_is_dirty(document):
                    blockers.append(f"{title} (MCP document has unsaved changes)")
                    continue
                app.CloseDoc(title)
                closed.append(title)
                self._owned_document_titles.discard(title)
            except Exception as exc:
                blockers.append(f"<unreadable document: {type(exc).__name__}: {exc}>")

        if blockers:
            raise RuntimeError(
                "Single-document test mode refused to create another SolidWorks document. "
                "Save/close these documents first: " + "; ".join(blockers)
            )

        try:
            remaining = int(_com_value(app, "GetDocumentCount"))
        except (AttributeError, TypeError):
            remaining = len(self._open_documents(app))
        if remaining != 0:
            raise RuntimeError(
                f"Single-document test mode expected zero documents before NewDocument, found {remaining}"
            )
        self._active_document = None
        return closed

    def _close_failed_document(self, app: Any, model: Any) -> None:
        try:
            try:
                title = str(_com_value(model, "GetTitle"))
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
            "platform": "Windows required",
            "part_template": str(part_template),
            "part_template_exists": part_template.exists(),
            "state_version": self.session.state_version,
            "operation_timeout_seconds": getattr(self.settings, "operation_timeout_seconds", 180.0),
            "interactive_mode": getattr(self.settings, "interactive_mode", True),
            "single_document_mode": getattr(self.settings, "single_document_mode", False),
            "verify_feature_tree": getattr(self.settings, "verify_feature_tree", False),
            "redraw_after_operation": getattr(self.settings, "redraw_after_operation", False),
            "executor_status": self.session.status(),
            "architecture": "MCP adapter -> validated operations -> serialized STA COM executor",
        }

    def operation_status(self) -> dict[str, Any]:
        return {"ok": True, **self.session.status()}

    def connect(self, start_if_missing: bool = False) -> dict[str, Any]:
        return self.session.connect(self.settings.visible, start_if_missing)

    def new_part(self, request_id: str, title: str = "Part") -> dict[str, Any]:
        title = require_text(title, "title")
        template = self.settings.part_template
        if not template.exists():
            raise ContractError(f"SolidWorks part template does not exist: {template}")

        def action(app: Any) -> dict[str, Any]:
            # NewDocument(template, paper_size, width, height) is more reliable than NewPart().
            closed_previous = (
                self._prepare_single_document_test(app)
                if getattr(self.settings, "single_document_mode", False)
                else []
            )
            model = self._new_part_document(app)
            # Document title is read-only in this COM binding. The requested title is
            # retained as intent; it becomes the file title when `save_active(path)` runs.
            return {
                "ok": True,
                "document_title": str(_com_value(model, "GetTitle")),
                "requested_title": title,
                "operation": "new_part",
                "single_document_test_mode": getattr(self.settings, "single_document_mode", False),
                "closed_previous_documents": closed_previous,
            }
        return self.session.execute(request_id, action)

    def execute_feature_graph(
        self,
        request_id: str,
        feature_graph: dict[str, Any],
        output_path: str,
    ) -> dict[str, Any]:
        plan = compile_feature_graph(feature_graph)
        target = Path(require_text(output_path, "output_path")).expanduser().resolve()
        if target.suffix.lower() != ".sldprt":
            raise ContractError("output_path must end in .sldprt")

        def action(app: Any) -> dict[str, Any]:
            strict_single_document = getattr(self.settings, "single_document_mode", False)
            closed_previous = self._prepare_single_document_test(app) if strict_single_document else []
            model = self._new_part_document(app)
            try:
                steps = execute_plan(
                    model,
                    plan,
                    full_rebuild=not getattr(self.settings, "interactive_mode", True),
                    redraw=getattr(self.settings, "redraw_after_operation", False),
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    ok, errors, warnings = _save_as(model, target)
                except Exception as exc:
                    raise RuntimeError(f"Native SaveAs call failed: {type(exc).__name__}: {exc}") from exc
                if not ok:
                    raise RuntimeError(
                        f"SolidWorks SaveAs failed after feature execution "
                        f"(errors={errors}, warnings={warnings})"
                    )
                if not target.exists() or target.stat().st_size <= 0:
                    raise RuntimeError(f"SolidWorks reported success but output is missing: {target}")
                verify_tree = getattr(self.settings, "verify_feature_tree", False)
                tree = feature_names(model) if verify_tree else []
                if verify_tree:
                    missing = [
                        step["name"] for step in plan[1:]
                        if step["name"] not in {item["name"] for item in tree}
                    ]
                    if missing:
                        raise RuntimeError(f"Native feature tree is missing expected features: {missing}")
                return {
                    "ok": True,
                    "operation": "execute_feature_graph",
                    "path": str(target),
                    "bytes": target.stat().st_size,
                    "warnings": warnings,
                    "steps": steps,
                    "features": tree if verify_tree else [step["name"] for step in plan[1:]],
                    "feature_tree_verified": verify_tree,
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
            return {"operation": operation, **action(model)}
        return self.session.execute(request_id, run)

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

    def create_parametric_part(
        self,
        request_id: str,
        part_type: str,
        parameters: dict[str, Any],
        output_path: str,
    ) -> dict[str, Any]:
        graph = build_parametric_part_graph(part_type, parameters)
        return self.execute_feature_graph(request_id, graph, output_path)

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

    def create_two_stage_reducer(
        self,
        request_id: str,
        output_path: str,
        **parameters: Any,
    ) -> dict[str, Any]:
        graph = build_two_stage_reducer_graph(**parameters)
        return self.execute_feature_graph(request_id, graph, output_path)

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

    def create_sphere(
        self,
        request_id: str,
        output_path: str,
        diameter_mm: float = 50.0,
    ) -> dict[str, Any]:
        graph = build_sphere_graph(diameter_mm)
        return self.execute_feature_graph(request_id, graph, output_path)

    def open_document(self, request_id: str, path: str) -> dict[str, Any]:
        source = Path(require_text(path, "path")).expanduser().resolve()
        if not source.is_file():
            raise ContractError(f"document does not exist: {source}")
        # SolidWorks imports STEP as a part document; after import it can be
        # persisted as native .sldprt through save_active().
        doc_type = {".sldprt": 1, ".sldasm": 2, ".slddrw": 3, ".step": 1, ".stp": 1}.get(source.suffix.lower())
        if doc_type is None:
            raise ContractError("path must end in .sldprt, .sldasm, .slddrw, .step, or .stp")

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
                    raise RuntimeError(f"SolidWorks could not create STEP import settings: {source}")
                model = app.LoadFile4(str(source), "r", import_data, errors)
            else:
                model = app.OpenDoc6(str(source), doc_type, 1, "", errors, warnings)
            if model is None:
                raise RuntimeError(f"SolidWorks failed to load: {source}")
            self._active_document = model
            return {"ok": True, "document_title": str(_com_value(model, "GetTitle")), "path": str(source), "operation": "open_document"}
        return self.session.execute(request_id, action)

    def save_active(self, request_id: str, path: str | None = None) -> dict[str, Any]:
        target = Path(path).expanduser().resolve() if path else None
        def action(app: Any) -> dict[str, Any]:
            model = self._active_model(app)
            if model is None:
                raise RuntimeError("No active SolidWorks document")
            actual_target = target or Path(str(_com_value(model, "GetPathName")))
            if not actual_target.name:
                raise ContractError("path is required when saving an unsaved document")
            actual_target.parent.mkdir(parents=True, exist_ok=True)
            ok, errors, warnings = _save_as(model, actual_target)
            if not ok:
                raise RuntimeError(f"SolidWorks SaveAs failed (errors={errors}, warnings={warnings})")
            if not actual_target.exists():
                raise RuntimeError(f"SolidWorks SaveAs reported success but file is missing: {actual_target}")
            return {"ok": True, "path": str(actual_target), "bytes": actual_target.stat().st_size, "warnings": warnings, "operation": "save"}
        return self.session.execute(request_id, action)

    def export_active(self, request_id: str, path: str) -> dict[str, Any]:
        target = Path(require_text(path, "path")).expanduser().resolve()
        if target.suffix.lower() not in _EXPORT_TYPES:
            raise ContractError("export extension must be STEP/STP/IGES/IGS/STL/PDF/DXF/DWG")
        def action(app: Any) -> dict[str, Any]:
            model = self._active_model(app)
            if model is None:
                raise RuntimeError("No active SolidWorks document")
            target.parent.mkdir(parents=True, exist_ok=True)
            ok, errors, warnings = _save_as(model, target)
            if not ok or not target.exists():
                raise RuntimeError(f"SolidWorks export failed (errors={errors}, warnings={warnings}): {target}")
            return {"ok": True, "path": str(target), "bytes": target.stat().st_size, "warnings": warnings, "operation": "export"}
        return self.session.execute(request_id, action)

    def create_spur_gear(
        self,
        request_id: str,
        output_path: str,
        tooth_count: int = 20,
        module_mm: float = 2.0,
        thickness_mm: float = 10.0,
        bore_diameter_mm: float = 10.0,
    ) -> dict[str, Any]:
        """Create and save a robust straight-tooth *approximate* spur gear.

        The outline is deliberately generated as a closed, four-segment tooth
        profile rather than pretending to generate an involute. It is suitable
        for visualisation, fixtures and concept models; a transmission-ready
        involute profile needs a separately verified gear standard/compiler.
        """
        if not isinstance(tooth_count, int) or isinstance(tooth_count, bool) or not 8 <= tooth_count <= 160:
            raise ContractError("tooth_count must be an integer from 8 to 160")
        module_mm = require_positive(module_mm, "module_mm")
        thickness_mm = require_positive(thickness_mm, "thickness_mm")
        bore_diameter_mm = require_positive(bore_diameter_mm, "bore_diameter_mm")
        root_radius_mm = module_mm * (tooth_count - 2.5) / 2.0
        outer_radius_mm = module_mm * (tooth_count + 2.0) / 2.0
        if bore_diameter_mm / 2 >= root_radius_mm - 0.25:
            raise ContractError("bore_diameter_mm is too large for the requested tooth count/module")
        target = Path(require_text(output_path, "output_path")).expanduser().resolve()
        if target.suffix.lower() != ".sldprt":
            raise ContractError("output_path must end in .sldprt")
        template = self.settings.part_template
        if not template.exists():
            raise ContractError(f"SolidWorks part template does not exist: {template}")

        def action(app: Any) -> dict[str, Any]:
            strict_single_document = getattr(self.settings, "single_document_mode", False)
            closed_previous = self._prepare_single_document_test(app) if strict_single_document else []
            model = self._new_part_document(app)
            extension = model.Extension
            if not extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, None, 0):
                # The fallback covers Chinese-localized default template names.
                if not extension.SelectByID2("前视基准面", "PLANE", 0, 0, 0, False, 0, None, 0):
                    raise RuntimeError("Could not select Front Plane for gear sketch")
            model.InsertSketch2(True)
            sketch = model.SketchManager
            step = 2.0 * math.pi / tooth_count
            tooth_half = step * 0.20
            root_m, outer_m = root_radius_mm / 1000.0, outer_radius_mm / 1000.0
            points: list[tuple[float, float]] = [(root_m * math.cos(-step / 2), root_m * math.sin(-step / 2))]
            for index in range(tooth_count):
                center = index * step
                points.extend([
                    (outer_m * math.cos(center - tooth_half), outer_m * math.sin(center - tooth_half)),
                    (outer_m * math.cos(center + tooth_half), outer_m * math.sin(center + tooth_half)),
                    (root_m * math.cos(center + step / 2), root_m * math.sin(center + step / 2)),
                ])
            for start, end in zip(points, points[1:] + [points[0]]):
                sketch.CreateLine(start[0], start[1], 0.0, end[0], end[1], 0.0)
            bore_m = bore_diameter_mm / 2000.0
            sketch.CreateCircle(0.0, 0.0, 0.0, bore_m, 0.0, 0.0)
            model.InsertSketch2(True)
            feature = model.FeatureManager.FeatureExtrusion2(
                True, False, False, 0, 0, thickness_mm / 1000.0, thickness_mm / 1000.0,
                False, False, False, False, 0.0, 0.0, False, False, False, False,
                True, True, True, 0, 0.0, False,
            )
            if feature is None:
                raise RuntimeError("Gear extrusion failed; no solid feature was created")
            try:
                if getattr(self.settings, "interactive_mode", True):
                    _com_value(model, "EditRebuild3")
                else:
                    _com_value(model, "ForceRebuild3", False)
                if getattr(self.settings, "redraw_after_operation", False):
                    _com_value(model, "ViewZoomtofit2")
            except Exception:
                pass
            target.parent.mkdir(parents=True, exist_ok=True)
            ok, errors, warnings = _save_as(model, target)
            if not ok or not target.exists():
                raise RuntimeError(
                    f"SolidWorks could not save gear (errors={errors}, warnings={warnings}): {target}"
                )
            return {
                "ok": True,
                "operation": "create_spur_gear",
                "path": str(target),
                "bytes": target.stat().st_size,
                "tooth_count": tooth_count,
                "module_mm": module_mm,
                "thickness_mm": thickness_mm,
                "bore_diameter_mm": bore_diameter_mm,
                "pitch_diameter_mm": module_mm * tooth_count,
                "outer_diameter_mm": 2.0 * outer_radius_mm,
                "profile": "straight-sided conceptual spur gear (not involute-certified)",
                "single_document_test_mode": strict_single_document,
                "closed_previous_documents": closed_previous,
            }
        return self.session.execute(request_id, action)

    def inspect_active(self, request_id: str, include_features: bool = False) -> dict[str, Any]:
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
            return result
        return self.session.execute(request_id, action)

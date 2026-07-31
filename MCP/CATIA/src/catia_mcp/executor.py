from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from . import __version__
from . import modeling, simulation, surfaces
from .compatibility import environment_report
from .config import Settings
from .contracts import ContractError, resolve_within
from .com_runtime import CatiaSession


class CatiaExecutor:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.session = CatiaSession(self.settings)

    def _read_path(self, path: str) -> Path:
        return resolve_within(path, self.settings.allowed_roots, must_exist=True)

    def _material_path(self, path: str) -> Path:
        report = environment_report(self.settings)
        selected = report.get("selected_installation")
        roots = list(self.settings.allowed_roots)
        if selected:
            roots.append(Path(selected["install_path"]) / "startup" / "materials")
        return resolve_within(path, roots, must_exist=True)

    def _write_path(self, path: str) -> Path:
        return resolve_within(path, self.settings.allowed_roots, must_exist=False)

    def _run(self, request_id: str, action: Callable[[Any], dict[str, Any]], *, mutating: bool = True) -> dict[str, Any]:
        return self.session.run(request_id, action, mutating=mutating)

    def health_check(self) -> dict[str, Any]:
        return {
            "server_version": __version__,
            "workspace": str(self.settings.workspace.resolve(strict=False)),
            "allowed_roots": [str(path.resolve(strict=False)) for path in self.settings.allowed_roots],
            "session": self.session.status(),
            "environment": environment_report(self.settings),
            "solver_policy": "CATIA internal Analysis/ELFINI only; no third-party solver integration",
        }

    def operation_status(self) -> dict[str, Any]:
        return self.session.status()

    def connect(self, start_if_missing: bool = False) -> dict[str, Any]:
        return self.session.connect(start_if_missing)

    def list_documents(self, request_id: str) -> dict[str, Any]:
        def action(app: Any) -> dict[str, Any]:
            documents = []
            for index in range(1, int(app.Documents.Count) + 1):
                document = app.Documents.Item(index)
                documents.append({
                    "index": index,
                    "name": document.Name,
                    "kind": modeling.document_kind(document),
                    "full_name": str(modeling._safe_attr(document, "FullName", "")),
                    "saved": bool(modeling._safe_attr(document, "Saved", False)),
                })
            return {"documents": documents, "count": len(documents)}

        return self._run(request_id, action, mutating=False)

    def create_part(self, request_id: str, title: str) -> dict[str, Any]:
        return self._run(request_id, lambda app: modeling.create_part(app, title))

    def create_product(self, request_id: str, title: str) -> dict[str, Any]:
        return self._run(request_id, lambda app: modeling.create_product(app, title))

    def open_document(self, request_id: str, path: str) -> dict[str, Any]:
        source = self._read_path(path)
        return self._run(request_id, lambda app: modeling.open_document(app, source))

    def save_active(self, request_id: str, path: str | None) -> dict[str, Any]:
        target = self._write_path(path) if path else None
        return self._run(request_id, lambda app: modeling.save_active(app, target))

    def export_active(
        self,
        request_id: str,
        path: str,
        format_name: str | None,
        overwrite_policy: str,
        verify_reimport: bool,
    ) -> dict[str, Any]:
        target = self._write_path(path)
        return self._run(
            request_id,
            lambda app: modeling.export_active(
                app,
                target,
                format_name,
                overwrite_policy,
                verify_reimport,
            ),
        )

    def create_sketch(
        self,
        request_id: str,
        name: str,
        plane: str,
        entities: list[dict[str, Any]],
        body_name: str,
    ) -> dict[str, Any]:
        return self._run(request_id, lambda app: modeling.create_sketch(app, name, plane, entities, body_name))

    def surface_capabilities(self, request_id: str) -> dict[str, Any]:
        return self._run(request_id, surfaces.surface_capabilities, mutating=False)

    def create_geometrical_set(self, request_id: str, name: str) -> dict[str, Any]:
        return self._run(request_id, lambda app: surfaces.create_geometrical_set(app, name))

    def create_3d_points(
        self,
        request_id: str,
        points: list[dict[str, Any]],
        geometrical_set: str,
    ) -> dict[str, Any]:
        return self._run(
            request_id,
            lambda app: surfaces.create_3d_points(app, points, geometrical_set),
        )

    def create_spline(
        self,
        request_id: str,
        name: str,
        point_names: list[str],
        closed: bool,
        constraints: list[dict[str, Any]] | None,
        geometrical_set: str,
    ) -> dict[str, Any]:
        return self._run(
            request_id,
            lambda app: surfaces.create_spline(
                app, name, point_names, closed, constraints, geometrical_set
            ),
        )

    def create_offset_plane(
        self,
        request_id: str,
        name: str,
        base_plane: str,
        offset_mm: float,
        orientation: bool,
        geometrical_set: str,
    ) -> dict[str, Any]:
        return self._run(
            request_id,
            lambda app: surfaces.create_offset_plane(
                app, name, base_plane, offset_mm, orientation, geometrical_set
            ),
        )

    def create_connect_curve(self, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._run(request_id, lambda app: surfaces.create_connect_curve(app, **kwargs))

    def create_loft(self, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._run(request_id, lambda app: surfaces.create_loft(app, **kwargs))

    def create_fill(self, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._run(request_id, lambda app: surfaces.create_fill(app, **kwargs))

    def join_surfaces(self, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._run(request_id, lambda app: surfaces.join_surfaces(app, **kwargs))

    def heal_surfaces(self, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._run(request_id, lambda app: surfaces.heal_surfaces(app, **kwargs))

    def create_boundary(
        self,
        request_id: str,
        name: str,
        surface_name: str,
        geometrical_set: str,
    ) -> dict[str, Any]:
        return self._run(
            request_id,
            lambda app: surfaces.create_boundary(app, name, surface_name, geometrical_set),
        )

    def close_surface(
        self,
        request_id: str,
        name: str,
        surface_name: str,
        body_name: str,
    ) -> dict[str, Any]:
        return self._run(
            request_id,
            lambda app: surfaces.close_surface(app, name, surface_name, body_name),
        )

    def thick_surface(self, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._run(request_id, lambda app: surfaces.thick_surface(app, **kwargs))

    def check_surface_quality(
        self,
        request_id: str,
        element_names: list[str],
        gap_pairs: list[list[str]] | None,
    ) -> dict[str, Any]:
        return self._run(
            request_id,
            lambda app: surfaces.check_surface_quality(app, element_names, gap_pairs),
        )

    def add_pad(self, request_id: str, sketch_name: str, length_mm: float, name: str, body_name: str) -> dict[str, Any]:
        return self._run(request_id, lambda app: modeling.add_pad(app, sketch_name, length_mm, name, body_name))

    def add_pocket(self, request_id: str, sketch_name: str, length_mm: float, name: str, body_name: str) -> dict[str, Any]:
        return self._run(request_id, lambda app: modeling.add_pocket(app, sketch_name, length_mm, name, body_name))

    def create_parametric_part(
        self,
        request_id: str,
        part_type: str,
        parameters: dict[str, Any],
        title: str,
        output_path: str,
    ) -> dict[str, Any]:
        target = self._write_path(output_path)
        if target.suffix.casefold() != ".catpart":
            raise ContractError("output_path must end in .CATPart")

        def action(app: Any) -> dict[str, Any]:
            result = modeling.create_parametric_part(app, part_type, parameters, title)
            saved = modeling.save_active(app, target)
            return {**result, "document": saved["document"], "saved": saved}

        return self._run(request_id, action)

    def add_components(self, request_id: str, paths: list[str]) -> dict[str, Any]:
        sources = [self._read_path(path) for path in paths]
        return self._run(request_id, lambda app: modeling.add_components(app, sources))

    def list_materials(self, request_id: str, catalog_path: str, family_name: str | None, limit: int) -> dict[str, Any]:
        source = self._material_path(catalog_path)
        return self._run(
            request_id,
            lambda app: modeling.list_materials(app, source, family_name, limit),
            mutating=False,
        )

    def apply_material(
        self,
        request_id: str,
        catalog_path: str,
        family_name: str,
        material_name: str,
        link_mode: int,
    ) -> dict[str, Any]:
        source = self._material_path(catalog_path)
        return self._run(
            request_id,
            lambda app: modeling.apply_material(app, source, family_name, material_name, link_mode),
        )

    def update_active(self, request_id: str) -> dict[str, Any]:
        return self._run(request_id, modeling.update_active)

    def inspect_active(self, request_id: str, include_parameters: bool, limit: int) -> dict[str, Any]:
        return self._run(request_id, lambda app: modeling.inspect_active(app, include_parameters, limit), mutating=False)

    def list_parameters(self, request_id: str, limit: int) -> dict[str, Any]:
        return self._run(request_id, lambda app: modeling.list_parameters(app, limit), mutating=False)

    def set_parameter(self, request_id: str, parameter_name: str, value: str, update: bool) -> dict[str, Any]:
        return self._run(request_id, lambda app: modeling.set_parameter(app, parameter_name, value, update))

    def capture_view(self, request_id: str, path: str) -> dict[str, Any]:
        target = self._write_path(path)
        return self._run(request_id, lambda app: modeling.capture_view(app, target), mutating=False)

    def close_active(
        self,
        request_id: str,
        save: bool,
        discard_unsaved: bool,
        expected_document_name: str | None = None,
    ) -> dict[str, Any]:
        return self._run(
            request_id,
            lambda app: modeling.close_active(app, save, discard_unsaved, expected_document_name),
        )

    def analysis_catalog(self) -> dict[str, Any]:
        report = environment_report(self.settings)
        return {"catalog": simulation.catalog(), "detected_typelib": report["analysis_typelib"]}

    def create_analysis_document(
        self,
        request_id: str,
        source_document_name: str | None,
        case_type: str | None,
        analysis_name: str,
        output_path: str | None,
    ) -> dict[str, Any]:
        target = self._write_path(output_path) if output_path else None
        if target and target.suffix.casefold() != ".catanalysis":
            raise ContractError("output_path must end in .CATAnalysis")

        def action(app: Any) -> dict[str, Any]:
            result = simulation.create_analysis_document(app, source_document_name, case_type, analysis_name)
            if target:
                result["saved"] = modeling.save_active(app, target)
            return result

        return self._run(request_id, action)

    def inspect_analysis(self, request_id: str, limit: int) -> dict[str, Any]:
        return self._run(request_id, lambda app: simulation.inspect_analysis(app, limit), mutating=False)

    def add_analysis_case(self, request_id: str, case_type: str, model_index: int, name: str | None) -> dict[str, Any]:
        return self._run(request_id, lambda app: simulation.add_case(app, case_type, model_index, name))

    def run_analysis_transition(self, request_id: str, transition_name: str, model_index: int) -> dict[str, Any]:
        return self._run(request_id, lambda app: simulation.run_transition(app, transition_name, model_index))

    def add_analysis_solution(self, request_id: str, solution_type: str, model_index: int, case_index: int) -> dict[str, Any]:
        return self._run(request_id, lambda app: simulation.add_solution(app, solution_type, model_index, case_index))

    def add_analysis_set(self, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._run(request_id, lambda app: simulation.add_set(app, **kwargs))

    def add_analysis_entity(self, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._run(request_id, lambda app: simulation.add_entity(app, **kwargs))

    def set_analysis_entity_value(self, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._run(request_id, lambda app: simulation.set_entity_value(app, **kwargs))

    def add_analysis_mesh_part(self, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._run(request_id, lambda app: simulation.add_mesh_part(app, **kwargs))

    def set_analysis_mesh_specification(self, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._run(request_id, lambda app: simulation.set_mesh_specification(app, **kwargs))

    def bind_analysis_mesh_support(self, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._run(request_id, lambda app: simulation.bind_mesh_support_from_search(app, **kwargs))

    def bind_analysis_support(self, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._run(request_id, lambda app: simulation.bind_entity_support_from_search(app, **kwargs))

    def compute_analysis(self, request_id: str, model_index: int, case_index: int, mesh_only: bool) -> dict[str, Any]:
        return self._run(request_id, lambda app: simulation.compute_case(app, model_index, case_index, mesh_only))

    def create_analysis_result_image(self, request_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._run(request_id, lambda app: simulation.create_result_image(app, **kwargs))

    def export_analysis_result_data(self, request_id: str, folder: str, **kwargs: Any) -> dict[str, Any]:
        target = self._write_path(folder)
        return self._run(request_id, lambda app: simulation.export_result_image_data(app, target, **kwargs))

    def build_analysis_report(
        self,
        request_id: str,
        folder: str,
        title: str,
        model_index: int,
        case_index: int,
        add_created_images: bool,
    ) -> dict[str, Any]:
        target = self._write_path(folder)
        return self._run(
            request_id,
            lambda app: simulation.build_report(app, target, title, model_index, case_index, add_created_images),
        )

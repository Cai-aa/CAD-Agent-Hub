from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .contracts import ContractError, require_choice, require_index, require_safe_name, require_text
from .modeling import _safe_attr, active_document, document_kind


BUILTIN_ANALYSIS_CATALOG: dict[str, Any] = {
    "case_types": [
        {"name": "Static Case", "transition": "CATGPSStressAnalysis_template"},
        {"name": "Frequency Case", "transition": "CATGPSModalAnalysis_template"},
        {"name": "Free Frequency Case", "transition": "CATGPSFreeModalAnalysis_template"},
    ],
    "set_types": [
        "LoadSet",
        "RestraintSet",
        "PropertySet",
        "MassSet",
        "MaterialSet",
        "SensorSet",
        "GroupSet",
        "MSHMeshSet",
    ],
    "common_structural_entities": [
        "SAMClamp",
        "SAMPressure",
        "SAMRestraint",
        "SAMDistributedForce",
        "SAMMoment",
        "SAMBearingLoad",
        "SAMDistributedMass",
    ],
    "common_mesh_types": [
        {"late_type": "MSHPartOctree3D", "display_name": "OCTREE Tetrahedron Mesh"},
        {"late_type": "MSHPartOctree2D", "display_name": "OCTREE Triangle Mesh"},
        {"late_type": "MSHPartGHS3D", "display_name": "Tetrahedron Filler Mesh"},
    ],
    "note": (
        "Identifiers are native CATIA Analysis late types. Availability and component labels depend "
        "on the installed workbench, licence and release; use inspect/describe after creation."
    ),
}

_CASE_TRANSITIONS = {
    "static case": "CATGPSStressAnalysis_template",
    "staticcase": "CATGPSStressAnalysis_template",
    "frequency case": "CATGPSModalAnalysis_template",
    "frequencycase": "CATGPSModalAnalysis_template",
    "free frequency case": "CATGPSFreeModalAnalysis_template",
    "freefrequencycase": "CATGPSFreeModalAnalysis_template",
}


def _iter_com(collection: Any, limit: int = 500) -> Iterable[Any]:
    count = min(int(collection.Count), limit)
    try:
        iterator = iter(collection)
    except TypeError:
        iterator = None
    if iterator is not None:
        for index, item in enumerate(iterator):
            if index >= count:
                break
            yield item
        return
    for index in range(1, count + 1):
        try:
            yield collection.Item(index)
        except Exception:
            yield collection.Item(index, 3)  # catAnalysisSetSearchAll


def _analysis_document(app: Any) -> Any:
    document = active_document(app)
    if not hasattr(document, "Analysis"):
        raise RuntimeError(f"active document is not a CATAnalysis document: {document.Name}")
    return document


def _analysis_manager(document: Any) -> Any:
    manager = document.Analysis
    if manager is None:
        raise RuntimeError("CATAnalysis document did not expose an AnalysisManager")
    return manager


def _model(manager: Any, model_index: int) -> Any:
    index = require_index(model_index, "model_index")
    if index > int(manager.AnalysisModels.Count):
        raise ContractError(f"model_index exceeds model count: {manager.AnalysisModels.Count}")
    return manager.AnalysisModels.Item(index)


def _case(model: Any, case_index: int) -> Any:
    index = require_index(case_index, "case_index")
    if index > int(model.AnalysisCases.Count):
        raise ContractError(f"case_index exceeds case count: {model.AnalysisCases.Count}")
    return model.AnalysisCases.Item(index)


def _set_owner(model: Any, case: Any, scope: str) -> Any:
    normalized = require_choice(scope, "scope", ("case", "model"))
    return case if normalized == "case" else model


def _find_set(owner: Any, set_type: str | None, set_index: int | None) -> Any:
    collection = owner.AnalysisSets
    if set_type:
        type_name = require_text(set_type, "set_type", max_length=256)
        try:
            return collection.ItemByType(type_name)
        except Exception:
            for item in _iter_com(collection):
                if str(_safe_attr(item, "Type", "")).casefold() == type_name.casefold():
                    return item
            raise RuntimeError(f"analysis set type not found: {type_name}")
    index = require_index(set_index or 1, "set_index")
    try:
        return collection.Item(index, 3)
    except Exception:
        return collection.Item(index)


def _entity(
    manager: Any,
    model_index: int,
    case_index: int,
    scope: str,
    set_type: str | None,
    set_index: int | None,
    entity_index: int,
) -> Any:
    model = _model(manager, model_index)
    case = _case(model, case_index)
    analysis_set = _find_set(_set_owner(model, case, scope), set_type, set_index)
    index = require_index(entity_index, "entity_index")
    if index > int(analysis_set.AnalysisEntities.Count):
        raise ContractError(f"entity_index exceeds entity count: {analysis_set.AnalysisEntities.Count}")
    return analysis_set.AnalysisEntities.Item(index)


def create_analysis_document(
    app: Any,
    source_document_name: str | None = None,
    case_type: str | None = None,
    analysis_name: str = "Analysis",
) -> dict[str, Any]:
    analysis_name = require_safe_name(analysis_name, "analysis_name")
    if source_document_name:
        source_name = require_text(source_document_name, "source_document_name", max_length=512)
        try:
            source = app.Documents.Item(source_name)
        except Exception as exc:
            raise RuntimeError(f"source document not found: {source_name}") from exc
    else:
        source = active_document(app)
    if document_kind(source).casefold() == "analysis" or hasattr(source, "Analysis"):
        raise ContractError("source document must be a CATPart or CATProduct, not CATAnalysis")
    document = app.Documents.Add("CATAnalysis")
    try:
        document.Name = analysis_name
    except Exception:
        pass
    manager = _analysis_manager(document)
    manager.Import(source)
    model_count = int(manager.AnalysisModels.Count)
    if model_count < 1:
        raise RuntimeError("CATIA imported the source but did not create an AnalysisModel")
    created_case = None
    if case_type:
        type_name = require_text(case_type, "case_type", max_length=256)
        created_case, _ = _create_case(manager.AnalysisModels.Item(1), type_name)
    return {
        "document": document.Name,
        "source_document": source.Name,
        "model_count": model_count,
        "created_case": str(_safe_attr(created_case, "Name", "")) if created_case is not None else None,
        "case_type": case_type,
        "license_verified": True,
        "solver": "CATIA internal Analysis/ELFINI",
    }


def _describe_entity(entity: Any, component_limit: int = 100) -> dict[str, Any]:
    components = []
    collection = entity.BasicComponents
    for component in _iter_com(collection, component_limit):
        components.append({
            "name": str(_safe_attr(component, "Name", "")),
            "type": str(_safe_attr(component, "Type", "")),
        })
    return {
        "name": str(_safe_attr(entity, "Name", "")),
        "type": str(_safe_attr(entity, "Type", "")),
        "support_count": int(_safe_attr(entity.AnalysisSupports, "Count", 0)),
        "basic_components": components,
    }


def _describe_set(analysis_set: Any, depth: int = 0, limit: int = 200) -> dict[str, Any]:
    entities = [_describe_entity(entity) for entity in _iter_com(analysis_set.AnalysisEntities, limit)]
    images = []
    try:
        images = [
            {"name": str(_safe_attr(image, "Name", ""))}
            for image in _iter_com(analysis_set.AnalysisImages, limit)
        ]
    except Exception:
        pass
    nested = []
    if depth < 3:
        try:
            nested = [_describe_set(item, depth + 1, limit) for item in _iter_com(analysis_set.AnalysisSets, limit)]
        except Exception:
            pass
    return {
        "name": str(_safe_attr(analysis_set, "Name", "")),
        "type": str(_safe_attr(analysis_set, "Type", "")),
        "entities": entities,
        "images": images,
        "sets": nested,
    }


def inspect_analysis(app: Any, limit: int = 200) -> dict[str, Any]:
    document = _analysis_document(app)
    manager = _analysis_manager(document)
    models = []
    for model_index, model in enumerate(_iter_com(manager.AnalysisModels, limit), 1):
        cases = []
        for case_index, case in enumerate(_iter_com(model.AnalysisCases, limit), 1):
            cases.append({
                "index": case_index,
                "name": str(_safe_attr(case, "Name", "")),
                "sets": [_describe_set(item, limit=limit) for item in _iter_com(case.AnalysisSets, limit)],
            })
        mesh_parts = []
        try:
            mesh_parts = [
                {
                    "name": str(_safe_attr(item, "Name", "")),
                    "type": str(_safe_attr(item, "Type", "")),
                    "active": bool(_safe_attr(item, "Activity", True)),
                }
                for item in _iter_com(model.MeshManager.AnalysisMeshParts, limit)
            ]
        except Exception:
            pass
        models.append({
            "index": model_index,
            "name": str(_safe_attr(model, "Name", "")),
            "cases": cases,
            "model_sets": [_describe_set(item, limit=limit) for item in _iter_com(model.AnalysisSets, limit)],
            "mesh_parts": mesh_parts,
        })
    return {
        "document": document.Name,
        "full_name": str(_safe_attr(document, "FullName", "")),
        "model_count": int(manager.AnalysisModels.Count),
        "models": models,
    }


def _create_case(model: Any, case_type: str) -> tuple[Any, str]:
    type_name = require_text(case_type, "case_type", max_length=256)
    transition = _CASE_TRANSITIONS.get(type_name.casefold())
    if transition:
        before = int(model.AnalysisCases.Count)
        model.RunTransition(transition)
        after = int(model.AnalysisCases.Count)
        if after <= before:
            raise RuntimeError(f"CATIA transition {transition} did not create an AnalysisCase")
        return model.AnalysisCases.Item(after), transition
    return model.AnalysisCases.NewCase(type_name), "AnalysisCases.NewCase"


def add_case(app: Any, case_type: str, model_index: int = 1, name: str | None = None) -> dict[str, Any]:
    document = _analysis_document(app)
    manager = _analysis_manager(document)
    model = _model(manager, model_index)
    type_name = require_text(case_type, "case_type", max_length=256)
    case, creation_route = _create_case(model, type_name)
    if name:
        case.Name = require_safe_name(name)
    return {
        "document": document.Name,
        "model_index": model_index,
        "case": case.Name,
        "case_type": type_name,
        "creation_route": creation_route,
    }


def run_transition(app: Any, transition_name: str, model_index: int = 1) -> dict[str, Any]:
    document = _analysis_document(app)
    manager = _analysis_manager(document)
    model = _model(manager, model_index)
    transition = require_text(transition_name, "transition_name", max_length=256)
    before = int(model.AnalysisCases.Count)
    model.RunTransition(transition)
    after = int(model.AnalysisCases.Count)
    return {
        "document": document.Name,
        "model_index": model_index,
        "transition": transition,
        "case_count_before": before,
        "case_count_after": after,
    }


def add_solution(app: Any, solution_type: str, model_index: int = 1, case_index: int = 1) -> dict[str, Any]:
    document = _analysis_document(app)
    manager = _analysis_manager(document)
    case = _case(_model(manager, model_index), case_index)
    type_name = require_text(solution_type, "solution_type", max_length=256)
    solution = case.AddSolution(type_name)
    return {
        "document": document.Name,
        "model_index": model_index,
        "case_index": case_index,
        "solution_type": type_name,
        "solution": str(_safe_attr(solution, "Name", "")),
    }


def add_set(
    app: Any,
    set_type: str,
    set_kind: str = "in",
    model_index: int = 1,
    case_index: int = 1,
    scope: str = "case",
    name: str | None = None,
) -> dict[str, Any]:
    document = _analysis_document(app)
    manager = _analysis_manager(document)
    model = _model(manager, model_index)
    case = _case(model, case_index)
    owner = _set_owner(model, case, scope)
    kind = require_choice(set_kind, "set_kind", ("in", "out", "neutral"))
    set_kind_value = {"in": 0, "out": 1, "neutral": 2}[kind]
    analysis_set = owner.AnalysisSets.Add(require_text(set_type, "set_type", max_length=256), set_kind_value)
    if name:
        analysis_set.Name = require_safe_name(name)
    return {
        "document": document.Name,
        "scope": scope,
        "set": analysis_set.Name,
        "set_type": str(_safe_attr(analysis_set, "Type", set_type)),
        "set_kind": kind,
    }


def add_entity(
    app: Any,
    entity_type: str,
    model_index: int = 1,
    case_index: int = 1,
    scope: str = "case",
    set_type: str | None = None,
    set_index: int | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    document = _analysis_document(app)
    manager = _analysis_manager(document)
    model = _model(manager, model_index)
    case = _case(model, case_index)
    analysis_set = _find_set(_set_owner(model, case, scope), set_type, set_index)
    type_name = require_text(entity_type, "entity_type", max_length=256)
    entity = analysis_set.AnalysisEntities.Add(type_name)
    if name:
        entity.Name = require_safe_name(name)
    return {
        "document": document.Name,
        "set": analysis_set.Name,
        "entity_index": int(analysis_set.AnalysisEntities.Count),
        "entity": _describe_entity(entity),
    }


def set_entity_value(
    app: Any,
    component: str,
    label: str,
    value: Any,
    model_index: int = 1,
    case_index: int = 1,
    scope: str = "case",
    set_type: str | None = None,
    set_index: int | None = None,
    entity_index: int = 1,
    line_index: int = 1,
    column_index: int = 1,
    layer_index: int = 1,
) -> dict[str, Any]:
    document = _analysis_document(app)
    manager = _analysis_manager(document)
    entity = _entity(manager, model_index, case_index, scope, set_type, set_index, entity_index)
    component_name = require_text(component, "component", max_length=256)
    label_name = require_text(label, "label", max_length=256)
    line = require_index(line_index, "line_index")
    column = require_index(column_index, "column_index")
    layer = require_index(layer_index, "layer_index")
    if not isinstance(value, (str, int, float, bool)):
        raise ContractError("value must be a JSON scalar")
    entity.SetValue(component_name, label_name, line, column, layer, value)
    return {
        "document": document.Name,
        "entity": _describe_entity(entity),
        "component": component_name,
        "label": label_name,
        "indices": [line, column, layer],
        "value": value,
    }


def add_mesh_part(
    app: Any,
    mesh_type: str,
    model_index: int = 1,
    name: str | None = None,
) -> dict[str, Any]:
    document = _analysis_document(app)
    manager = _analysis_manager(document)
    model = _model(manager, model_index)
    type_name = require_text(mesh_type, "mesh_type", max_length=256)
    mesh_part = model.MeshManager.AnalysisMeshParts.Add(type_name)
    if name:
        mesh_part.Name = require_safe_name(name)
    return {
        "document": document.Name,
        "model_index": model_index,
        "mesh_part_index": int(model.MeshManager.AnalysisMeshParts.Count),
        "mesh_part": str(_safe_attr(mesh_part, "Name", "")),
        "mesh_type": str(_safe_attr(mesh_part, "Type", type_name)),
    }


def set_mesh_specification(
    app: Any,
    specification_name: str,
    value: Any,
    model_index: int = 1,
    mesh_part_index: int = 1,
    update: bool = True,
) -> dict[str, Any]:
    document = _analysis_document(app)
    manager = _analysis_manager(document)
    model = _model(manager, model_index)
    index = require_index(mesh_part_index, "mesh_part_index")
    mesh_parts = model.MeshManager.AnalysisMeshParts
    if index > int(mesh_parts.Count):
        raise ContractError(f"mesh_part_index exceeds mesh part count: {mesh_parts.Count}")
    mesh_part = mesh_parts.Item(index)
    name = require_text(specification_name, "specification_name", max_length=256)
    if not isinstance(value, (str, int, float, bool)):
        raise ContractError("value must be a JSON scalar")
    mesh_part.SetGlobalSpecification(name, value)
    if update:
        mesh_part.Update()
    return {
        "document": document.Name,
        "mesh_part": str(_safe_attr(mesh_part, "Name", "")),
        "specification": name,
        "value": value,
        "updated": update,
    }


def bind_mesh_support_from_search(
    app: Any,
    source_document_name: str,
    search_query: str,
    selection_index: int = 1,
    model_index: int = 1,
    mesh_part_index: int = 1,
) -> dict[str, Any]:
    document = _analysis_document(app)
    manager = _analysis_manager(document)
    model = _model(manager, model_index)
    mesh_parts = model.MeshManager.AnalysisMeshParts
    mesh_index = require_index(mesh_part_index, "mesh_part_index")
    if mesh_index > int(mesh_parts.Count):
        raise ContractError(f"mesh_part_index exceeds mesh part count: {mesh_parts.Count}")
    mesh_part = mesh_parts.Item(mesh_index)
    source_name = require_text(source_document_name, "source_document_name", max_length=512)
    query = require_text(search_query, "search_query", max_length=1000)
    try:
        source = app.Documents.Item(source_name)
    except Exception as exc:
        raise RuntimeError(f"source document not found: {source_name}") from exc
    selection = source.Selection
    selection.Clear()
    try:
        selection.Search(query)
        count = int(selection.Count2)
        index = require_index(selection_index, "selection_index")
        if index > count:
            raise ContractError(f"selection_index exceeds CATIA search result count: {count}")
        selected = selection.Item2(index).Value
        support_reference = manager.CreateReferenceFromGeometry(source.Product, selected)
        mesh_part.AddSupportFromReference(source.Product, support_reference)
    finally:
        selection.Clear()
    return {
        "document": document.Name,
        "mesh_part": str(_safe_attr(mesh_part, "Name", "")),
        "source_document": source.Name,
        "search_query": query,
        "matched": count,
        "selected_index": selection_index,
    }


def bind_entity_support_from_search(
    app: Any,
    source_document_name: str,
    search_query: str,
    selection_index: int = 1,
    model_index: int = 1,
    case_index: int = 1,
    scope: str = "case",
    set_type: str | None = None,
    set_index: int | None = None,
    entity_index: int = 1,
) -> dict[str, Any]:
    """Bind an Analysis entity to geometry found by CATIA's native Selection.Search.

    The operation is deliberately structured: it accepts a CATIA search expression,
    but no macro or arbitrary COM method. The source selection is always cleared.
    """
    analysis_document = _analysis_document(app)
    manager = _analysis_manager(analysis_document)
    entity = _entity(manager, model_index, case_index, scope, set_type, set_index, entity_index)
    source_name = require_text(source_document_name, "source_document_name", max_length=512)
    query = require_text(search_query, "search_query", max_length=1000)
    try:
        source = app.Documents.Item(source_name)
    except Exception as exc:
        raise RuntimeError(f"source document not found: {source_name}") from exc
    selection = source.Selection
    selection.Clear()
    try:
        selection.Search(query)
        count = int(selection.Count2)
        index = require_index(selection_index, "selection_index")
        if index > count:
            raise ContractError(f"selection_index exceeds CATIA search result count: {count}")
        selected = selection.Item2(index).Value
        product = source.Product
        context_reference = manager.CreateReferenceFromObject(product)
        support_reference = manager.CreateReferenceFromGeometry(product, selected)
        entity.AddSupportFromReference(context_reference, support_reference)
    finally:
        selection.Clear()
    return {
        "document": analysis_document.Name,
        "source_document": source.Name,
        "search_query": query,
        "matched": count,
        "selected_index": selection_index,
        "entity": _describe_entity(entity),
    }


def compute_case(app: Any, model_index: int = 1, case_index: int = 1, mesh_only: bool = False) -> dict[str, Any]:
    document = _analysis_document(app)
    manager = _analysis_manager(document)
    case = _case(_model(manager, model_index), case_index)
    if mesh_only:
        case.ComputeMeshOnly()
    else:
        case.Compute()
    return {
        "document": document.Name,
        "model_index": model_index,
        "case_index": case_index,
        "case": str(_safe_attr(case, "Name", "")),
        "mesh_only": mesh_only,
        "compute_call_returned": True,
        "quality_note": (
            "A returned Compute call is not by itself proof of a valid simulation. "
            "Inspect result images, reports, mesh and numerical outputs before accepting the run."
        ),
    }


def create_result_image(
    app: Any,
    image_type: str,
    model_index: int = 1,
    case_index: int = 1,
    scope: str = "case",
    set_type: str | None = None,
    set_index: int | None = None,
    hide_existing_images: bool = True,
    show_mesh: bool = False,
    duplicate: bool = False,
) -> dict[str, Any]:
    document = _analysis_document(app)
    manager = _analysis_manager(document)
    model = _model(manager, model_index)
    case = _case(model, case_index)
    analysis_set = _find_set(_set_owner(model, case, scope), set_type, set_index)
    type_name = require_text(image_type, "image_type", max_length=256)
    image = analysis_set.AnalysisImages.Add(type_name, bool(hide_existing_images), bool(show_mesh), bool(duplicate))
    image.Update()
    return {
        "document": document.Name,
        "set": str(_safe_attr(analysis_set, "Name", "")),
        "image_index": int(analysis_set.AnalysisImages.Count),
        "image": str(_safe_attr(image, "Name", type_name)),
        "image_type": type_name,
    }


def export_result_image_data(
    app: Any,
    folder: Path,
    file_name: str,
    extension_type: str,
    model_index: int = 1,
    case_index: int = 1,
    scope: str = "case",
    set_type: str | None = None,
    set_index: int | None = None,
    image_index: int = 1,
) -> dict[str, Any]:
    document = _analysis_document(app)
    manager = _analysis_manager(document)
    model = _model(manager, model_index)
    case = _case(model, case_index)
    analysis_set = _find_set(_set_owner(model, case, scope), set_type, set_index)
    index = require_index(image_index, "image_index")
    if index > int(analysis_set.AnalysisImages.Count):
        raise ContractError(f"image_index exceeds image count: {analysis_set.AnalysisImages.Count}")
    image = analysis_set.AnalysisImages.Item(index)
    folder.mkdir(parents=True, exist_ok=True)
    base_name = require_safe_name(file_name, "file_name")
    extension = require_text(extension_type, "extension_type", max_length=32)
    image.ExportData(str(folder), base_name, extension)
    artifacts = sorted(str(path) for path in folder.glob(f"{base_name}*"))
    return {
        "document": document.Name,
        "image": str(_safe_attr(image, "Name", "")),
        "folder": str(folder),
        "file_name": base_name,
        "extension_type": extension,
        "artifacts": artifacts,
    }


def build_report(
    app: Any,
    folder: Path,
    title: str,
    model_index: int = 1,
    case_index: int = 1,
    add_created_images: bool = True,
) -> dict[str, Any]:
    document = _analysis_document(app)
    manager = _analysis_manager(document)
    model = _model(manager, model_index)
    case = _case(model, case_index)
    folder.mkdir(parents=True, exist_ok=True)
    post = model.PostManager
    post.AddExistingCaseForReport(case)
    post.BuildReport(str(folder), require_text(title, "title", max_length=256), bool(add_created_images))
    artifacts = sorted(str(path) for path in folder.rglob("*") if path.is_file())
    return {
        "document": document.Name,
        "folder": str(folder),
        "artifacts": artifacts[:500],
        "artifact_count": len(artifacts),
        "truncated": len(artifacts) > 500,
    }


def catalog() -> dict[str, Any]:
    return BUILTIN_ANALYSIS_CATALOG

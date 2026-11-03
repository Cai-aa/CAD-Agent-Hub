"""Fail-closed evidence identity and acceptance. This module never calls EPLAN.

Hashes identify local saved evidence, not a signed electrical approval. A saved
report is never presented as a live read, even when its input hashes still match.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from .config import source_root

COLLECTOR_VERSION = "native-evidence-2"
EVIDENCE_SCHEMA = "eplan-native-evidence-2"
ROUTES = {
    "motor-design-1.2": ("legacy", "legacy-native-audit-2"),
    "motor-design-1.3-three-phase": ("three_phase", "three-phase-native-audit-2"),
    "motor-design-1.4-reference-interfaces": ("reference", "reference-native-audit-2"),
}
TRACKED_FILES = ("eplan_mcp/review.py", "eplan_mcp/server.py", "eplan_mcp/design.py",
                 "audit_native.py", "audit_three_phase.py", "eplan_mcp/curated_parts.py",
                 "eplan_mcp/config.py", "eplan_mcp/bridge.py", "eplan_mcp/transport.py",
                 "eplan_mcp/enhancements.py", "eplan_mcp/help_search.py", "eplan_mcp/intent.py",
                 "eplan_mcp/native_snapshot.py", "eplan_mcp/schemas/native-snapshot-plan.schema.json",
                 "eplan_mcp/schemas/design-intent.schema.json")
_LOADED = {}


class EvidenceError(RuntimeError):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def register_loaded(path):
    """Record source hashes once at module import, never refresh them on status."""
    path = Path(path).resolve()
    _LOADED.setdefault(str(path), sha256(path.read_bytes()))


def route_for(model):
    schema = model.get("schema_version")
    if schema not in ROUTES:
        raise EvidenceError("UNSUPPORTED_MODEL_SCHEMA: " + str(schema))
    return ROUTES[schema]


def context(root):
    root = Path(root)
    model_path = root / "artifacts/motor_forward_reverse.design.json"
    model_bytes = model_path.read_bytes()
    model = json.loads(model_bytes.decode("utf-8-sig"))
    route, report_schema = route_for(model)
    names = (["audit_native.py"] if route == "legacy" else
             ["artifacts/three_phase_applied.json"])
    if route == "reference":
        names.append("artifacts/reference_interfaces_applied.json")
    if model.get('client_engineering_revision'):
        names.extend(['artifacts/client_engineering_A0_applied.json','artifacts/client_engineering_A0.plan.json','artifacts/client_engineering_A0_finish.plan.json'])
    if model.get('native_parts_revision'):
        if model['native_parts_revision']!='project-curated-parts-A1':raise EvidenceError('UNSUPPORTED_NATIVE_PARTS_REVISION')
        names.extend(['artifacts/curated_parts_A1_applied.json','artifacts/curated_parts_A1.plan.json'])
    if model.get('native_parts_doc_revision'):
        if model['native_parts_doc_revision']!='parts-caption-A1':raise EvidenceError('UNSUPPORTED_PARTS_DOCUMENT_REVISION')
        names.extend(['artifacts/parts_caption_A1_applied.json','artifacts/parts_caption_A1.plan.json'])
    manifest_files = {name: sha256((root / name).read_bytes()) for name in names}
    code_files = {name: sha256((source_root() / name).read_bytes()) for name in TRACKED_FILES}
    binding = {
        "schema": EVIDENCE_SCHEMA, "model_schema": model["schema_version"],
        "model_sha256": sha256(model_bytes),
        "route_manifest_sha256": sha256(json.dumps(manifest_files, sort_keys=True).encode()),
        "route_manifest_files": manifest_files,
        "collector_version": COLLECTOR_VERSION, "collector_schema": report_schema,
        "collector_code_sha256": sha256(json.dumps(code_files, sort_keys=True).encode()),
    }
    return model, binding


def bind_report(report, before, root):
    _, after = context(root)
    if before != after:
        raise EvidenceError("EVIDENCE_INPUT_CHANGED_DURING_COLLECTION")
    if report.get("schema") != before["collector_schema"]:
        raise EvidenceError("COLLECTOR_SCHEMA_MISMATCH")
    report["evidence"] = dict(before)
    report["production_release_allowed"] = False
    return report


def edge_key(edge):
    a = f"{edge['start_type_id']}:{edge['start_object_id']}:{edge['start_index']}"
    b = f"{edge['end_type_id']}:{edge['end_object_id']}:{edge['end_index']}"
    return "|".join(sorted((a, b))) + "|" + str(edge["placed"])


def validate_report(report, root):
    """Independently reject an obsolete collector's plausible-looking summary."""
    model, binding = context(root)
    if report.get("evidence") != binding:
        raise EvidenceError("STALE_OR_UNBOUND_NATIVE_EVIDENCE")
    if report.get("schema") != binding["collector_schema"]:
        raise EvidenceError("COLLECTOR_SCHEMA_MISMATCH")
    for key in ("instance_id", "database_id", "project_name", "collected_utc"):
        if key not in report or report[key] is None:
            raise EvidenceError("MISSING_NATIVE_IDENTITY: " + key)
    stamp = datetime.fromisoformat(report["collected_utc"])
    if stamp.tzinfo is None or stamp > datetime.now(timezone.utc):
        raise EvidenceError("INVALID_COLLECTION_TIME")
    s = report["summary"]
    edges = report["placed_edges"]
    ids = [(e["database_id"], e["object_id"]) for e in edges]
    keys = [edge_key(e) for e in edges]
    if len(set(ids)) != len(ids) or len(set(keys)) != len(keys):
        raise EvidenceError("DUPLICATE_NATIVE_CONNECTION")
    for e in edges:
        if (e["database_id"] != report["database_id"] or e["placed"] is not True or
                any(type(e[k]) is not int or e[k] < 0 for k in
                    ("start_type_id", "start_object_id", "start_index",
                     "end_type_id", "end_object_id", "end_index"))):
            raise EvidenceError("INVALID_TYPED_NATIVE_CONNECTION")
    if (s["native_edges"] != len(edges) or s["placed_edges"] != len(edges) or
            s["unplaced_edges"] != 0 or report["unplaced_edges"] or
            s["unexpected_native_edges"] != 0 or s["missing_expected_routes"] or
            s["design_device_tags_missing_native"] or
            report["route_check"]["missing"] or report["route_check"]["unexpected_native_edges"] or
            s["pages_scanned"] != len(report["pages"]) or
            s["pages_scanned"] != len(model["pages"]) or
            s["design_connection_intents"] != len(model["connections"])):
        raise EvidenceError("NATIVE_AUDIT_INCOMPLETE_OR_INCONSISTENT")
    route, _ = route_for(model)
    if route != "legacy":
        manifest = json.loads((Path(root) / "artifacts/three_phase_applied.json").read_text(encoding="utf-8-sig"))
        expected = manifest["expected_native_edges"]
        if (len(set(expected)) != len(expected) or set(expected) != set(keys) or
                s["verified_native_routes"] != len(expected) or
                len(expected) != model["native_implementation"]["expected_native_edges"] or
                report["static_conductor_check"]["direct_conductor_shorts"]):
            raise EvidenceError("NATIVE_ROUTE_MANIFEST_MISMATCH")
        logical = report["logical_intent_paths"]
        missing = report["unresolved_intents"]
        actual_ids = [p["id"] for p in logical + missing]
        if (len(set(actual_ids)) != len(actual_ids) or
                set(actual_ids) != {c["id"] for c in model["connections"]} or
                s["design_intents_verified_native"] != len(logical) or
                s["design_intents_not_placed"] != len(missing)):
            raise EvidenceError("LOGICAL_COVERAGE_MISMATCH")
        edge_ids = {e["object_id"] for e in edges}
        for p in logical:
            if (not set(p["native_edge_ids"]) <= edge_ids or
                    not p["native_edge_ids"] and not p.get("logical_bus_collapsed") or
                    len(p["source"]) != 4 or len(p["target"]) != 4 or
                    p["source"][0] != report["database_id"] or
                    p["target"][0] != report["database_id"]):
                raise EvidenceError("INVALID_LOGICAL_PATH_IDENTITY")
        terminals = [f for p in report["pages"] for f in p["function_details"] if f["symbol"] == "X"]
        expected_groups = dict(Counter(t["strip"] for t in model["terminals"]))
        actual_groups = dict(Counter(f["name"].rsplit("-", 1)[-1].split(":", 1)[0] for f in terminals))
        if (s["terminal_positions"] != len(terminals) or len(terminals) != len(model["terminals"]) or
                actual_groups != expected_groups or s["terminal_groups"] != actual_groups):
            raise EvidenceError("TERMINAL_COVERAGE_MISMATCH")
        if route == "reference" and missing:
            raise EvidenceError("REFERENCE_INTERFACES_NOT_COMPLETE")
    elif s["design_intents_not_placed"] or s["design_intents_verified_native"] != len(model["connections"]):
        raise EvidenceError("LEGACY_NATIVE_AUDIT_INCOMPLETE")
    if model.get('native_parts_revision'):
        proof=report.get('native_parts_verification') or {};scope=model['native_parts_scope']
        committed=json.loads((Path(root)/'artifacts/curated_parts_A1_applied.json').read_text(encoding='utf-8-sig'))
        if (proof.get('complete') is not True or proof.get('verified_references')!=scope['native_references'] or
            proof.get('definitions')!=scope['project_records'] or proof.get('plan_sha256')!=committed['plan_sha256'] or
            proof.get('scope')!='project_local_curated_records_not_vendor_macros' or proof.get('procurement_approved') is not False):
            raise EvidenceError('CURATED_PART_EVIDENCE_INCOMPLETE_OR_INCONSISTENT')
    return True


def atomic_snapshot(report, path, root):
    validate_report(report, root)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temp = Path(stream.name)
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        # Reject an input edit that happened while serializing the snapshot.
        validate_report(report, root)
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def snapshot_status(path, root):
    result = {"available": False, "source": "saved_snapshot_not_live", "live_verified_this_call": False,
              "path": str(path), "stale": True}
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        result.update(available=True, collected_utc=report.get("collected_utc"),
                      instance_id=report.get("instance_id"), database_id=report.get("database_id"),
                      summary=report.get("summary"), evidence=report.get("evidence"))
        validate_report(report, root)
        result.update(stale=False, reason="INPUTS_MATCH_SAVED_EVIDENCE; NOT_A_LIVE_READ")
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        result["reason"] = str(exc)
    return result


def runtime_status(root, snapshot_path):
    root = Path(root)
    files = {}
    for name in TRACKED_FILES:
        path = source_root() / name
        loaded = _LOADED.get(str(path.resolve()))
        disk = sha256(path.read_bytes()) if path.is_file() else None
        files[name] = {"loaded_sha256": loaded, "disk_sha256": disk,
                       "loaded_source_tracked": loaded is not None, "matches": loaded is not None and loaded == disk}
    try:
        _, binding = context(root)
        error = None
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        binding, error = None, str(exc)
    snapshot = snapshot_status(snapshot_path, root)
    return {"ok": error is None, "process_id": os.getpid(), "root": str(root),
            "fingerprint_scope": "source bytes captured at module import versus current disk bytes",
            "code_files": files, "code_stale": not all(f["matches"] for f in files.values()),
            "expected_evidence": binding, "context_error": error,
            "collector_version": COLLECTOR_VERSION, "snapshot": snapshot,
            "stale": error is not None or snapshot["stale"] or not all(f["matches"] for f in files.values()),
            "production_release_allowed": False}


def acceptance(model, native_status, scope="reference"):
    from .design import validate
    if scope not in ("reference", "construction"):
        raise EvidenceError("UNSUPPORTED_ACCEPTANCE_SCOPE")
    route, _ = route_for(model)
    checked = validate(model)
    summary = native_status.get("summary") or {}
    native_complete = (not native_status.get("stale", True) and native_status.get("available") is True and
                       summary.get("design_intents_not_placed") == 0 and
                       summary.get("design_intents_verified_native") == len(model["connections"]))
    reference_complete = route == "reference" and checked["ok"] and native_complete
    blockers = model.get("release_blockers", [])
    return {"ok": True, "scope": scope, "accepted": reference_complete if scope == "reference" else False,
            "decision": ("REFERENCE_DOCUMENT_CONSISTENCY_VERIFIED" if reference_complete else "REFERENCE_EVIDENCE_INCOMPLETE")
                        if scope == "reference" else "CONSTRUCTION_RELEASE_DISABLED",
            "reference_complete": reference_complete, "native_evidence": native_status,
            "design_validation": checked, "release_blockers": blockers,
            "production_release_allowed": False, "construction_ready": False, "commissioning_ready": False,
            "immutable_release_limits": ["This bridge operates on a disposable trial project only.",
                "Reference acceptance does not authorize procurement, manufacturing, installation or operation.",
                "Clearing TBD text or model blockers cannot enable production release."],
            "scope_limits": ["Native paths and logical consistency only; not PLC execution or functional safety validation.",
                "Saved evidence is not a live project read; refresh_native=True requests fresh read-only collection."]}


register_loaded(__file__)

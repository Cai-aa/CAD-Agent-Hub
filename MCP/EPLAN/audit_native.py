"""Read back native EPLAN schematic connectivity from the dedicated trial instance.

This is an evidence collector, not a substitute for EPLAN's project check.  It
does not edit the project or infer that a graphical line is an electrical net.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from eplan_mcp.bridge import discover, request
from eplan_mcp.config import workspace_root


ROOT = workspace_root()
OUT = ROOT / "artifacts" / "native_connectivity_audit.json"


def endpoint(tag: str, symbol: str, pin: int, address: str | None = None,
             terminal: str | None = None, role: str | None = None) -> dict:
    result = {"tag": tag, "symbol": symbol, "pin": pin}
    if address:
        result["plc_address"] = address
    if terminal:
        result["name_suffix"] = "-" + terminal
        result.pop("tag")
    if role:
        result["role_designation"] = role
    return result


# Version-specific draft pin geometry verified against the installed symbols.
# Pin indices are API indices, never claimed as vendor physical terminal labels.
ROUTES = [
    ("N001", endpoint("", "X", 1, terminal="X1:1"), endpoint("QS1", "Q2", 0)),
    ("N002", endpoint("", "X", 1, terminal="X1:2"), endpoint("QS1", "Q2", 2)),
    ("N004", endpoint("QS1", "Q2", 1), endpoint("QF0", "FA2", 0)),
    ("N005", endpoint("QS1", "Q2", 3), endpoint("QF0", "FA2", 2)),
    ("N010", endpoint("QF1", "FA2", 1), endpoint("KM0", "S", 0, role="L_IN_TBD")),
    ("N011", endpoint("QF1", "FA2", 3), endpoint("KM0", "S", 0, role="N_IN_TBD")),
    ("N012", endpoint("KM0", "S", 1, role="L_IN_TBD"), endpoint("VFD1", "DCP", 0, role="ROLE_L_TBD")),
    ("N013", endpoint("KM0", "S", 1, role="N_IN_TBD"), endpoint("VFD1", "DCP", 0, role="ROLE_N_TBD")),
    ("N014", endpoint("", "DCP", 0, terminal="VFD1:U", role="U"), endpoint("", "X", 0, terminal="X3:1")),
    ("N015", endpoint("", "DCP", 0, terminal="VFD1:V", role="V"), endpoint("", "X", 0, terminal="X3:2")),
    ("N016", endpoint("", "DCP", 0, terminal="VFD1:W", role="W"), endpoint("", "X", 0, terminal="X3:3")),
    ("N017", endpoint("", "X", 1, terminal="X3:1"), endpoint("M1", "M3", 0)),
    ("N018", endpoint("", "X", 1, terminal="X3:2"), endpoint("M1", "M3", 1)),
    ("N019", endpoint("", "X", 1, terminal="X3:3"), endpoint("M1", "M3", 2)),
    ("N021", endpoint("", "X", 1, terminal="X3:4"), endpoint("M1", "M3", 3)),
    ("N028", endpoint("QF2", "FA2", 1), endpoint("PS1", "DCP", 0, role="ROLE_L_TBD")),
    ("N029", endpoint("QF2", "FA2", 3), endpoint("PS1", "DCP", 0, role="ROLE_N_TBD")),
    ("N033", endpoint("FU1", "FA1", 1), endpoint("PLC1", "DCP", 0, role="ROLE_LPLUS_TBD")),
    ("N036", endpoint("FU2", "FA1", 1), endpoint("", "X", 0, terminal="X2:1")),
    ("N037", endpoint("FU2", "FA1", 1), endpoint("SR1", "DCP", 0, role="ROLE_PWR_PLUS_TBD")),
    ("N039", endpoint("", "X", 1, terminal="X2:1"), endpoint("SB1", "SSA", 0)),
    ("N042", endpoint("", "X", 1, terminal="X2:1"), endpoint("SB2", "SOA", 0)),
    ("N045", endpoint("", "X", 1, terminal="X2:1"), endpoint("SB3", "SSA", 0)),
    ("N048", endpoint("", "X", 1, terminal="X2:1"), endpoint("SB4", "SSA", 0)),
    ("N051", endpoint("SR1", "DCP", 0, role="ROLE_CH_A_OUT_TBD"), endpoint("", "X", 0, terminal="X2:7")),
    ("N052", endpoint("", "X", 1, terminal="X2:7"), endpoint("SB0", "SONOT1", 0, role="CH_A_IN_TBD")),
    ("N053", endpoint("SB0", "SONOT1", 1, role="CH_A_IN_TBD"), endpoint("", "X", 0, terminal="X2:8")),
    ("N054", endpoint("", "X", 1, terminal="X2:8"), endpoint("SR1", "DCP", 0, role="ROLE_CH_A_RETURN_TBD")),
    ("N055", endpoint("SR1", "DCP", 0, role="ROLE_CH_B_OUT_TBD"), endpoint("", "X", 0, terminal="X2:9")),
    ("N056", endpoint("", "X", 1, terminal="X2:9"), endpoint("SB0", "SONOT1", 0, role="CH_B_IN_TBD")),
    ("N057", endpoint("SB0", "SONOT1", 1, role="CH_B_IN_TBD"), endpoint("", "X", 0, terminal="X2:10")),
    ("N058", endpoint("", "X", 1, terminal="X2:10"), endpoint("SR1", "DCP", 0, role="ROLE_CH_B_RETURN_TBD")),
    ("N059", endpoint("FU3", "FA1", 1), endpoint("SR1", "DCP", 0, role="ROLE_SAFE_IN_TBD")),
    ("N060", endpoint("SR1", "DCP", 0, role="ROLE_SAFE_OUT_TBD"), endpoint("KM0", "K", 0)),
    ("N069", endpoint("FU3", "FA1", 1), endpoint("PLC1", "DCP", 0, role="ROLE_DO_LPLUS_TBD")),
    ("N070", endpoint("PLC1", "PLCCP", 0, "Q0.0"), endpoint("KA2", "O", 1)),
    ("N071", endpoint("KA2", "O", 0), endpoint("KA1", "K", 1)),
    ("N072", endpoint("PLC1", "PLCCP", 0, "Q0.1"), endpoint("KA1", "O", 1)),
    ("N073", endpoint("KA1", "O", 0), endpoint("KA2", "K", 1)),
    ("N081", endpoint("PLC1", "PLCCP", 0, "Q0.2"), endpoint("KA3", "K", 1)),
    ("N084", endpoint("PLC1", "PLCCP", 0, "Q0.3"), endpoint("HL3", "H", 1)),
    ("N086", endpoint("PLC1", "PLCCP", 0, "Q0.4"), endpoint("HL4", "H", 1)),
    ("N088", endpoint("PLC1", "PLCCP", 0, "Q0.5"), endpoint("HL5", "H", 1)),
    ("N097", endpoint("SQ1", "SSM", 1), endpoint("EL1", "H", 0)),
    ("N103", endpoint("TS1", "SSM", 1), endpoint("FAN1", "M2W_VE", 0)),
    ("N095", endpoint("QF3", "FA1", 1), endpoint("", "X", 0, terminal="X4:3")),
    ("N096", endpoint("", "X", 1, terminal="X4:3"), endpoint("SQ1", "SSM", 0)),
    ("N101", endpoint("QF4", "FA1", 1), endpoint("", "X", 0, terminal="X4:1")),
    ("N102", endpoint("", "X", 1, terminal="X4:1"), endpoint("TS1", "SSM", 0)),
    ("N098", endpoint("EL1", "H", 1), endpoint("", "X", 0, terminal="X4:4")),
    ("N104", endpoint("FAN1", "M2W_VE", 1), endpoint("", "X", 1, terminal="X4:2")),
]
for channel, first_id in enumerate((40, 43, 46, 49)):
    terminal_name = f"X2:{channel + 2}"
    ROUTES.extend([
        (f"N{first_id:03}", endpoint(f"SB{channel + 1}", "SOA" if channel == 1 else "SSA", 1),
         endpoint("", "X", 0, terminal=terminal_name)),
        (f"N{first_id + 1:03}", endpoint("", "X", 1, terminal=terminal_name),
         endpoint("PLC1", "PLCCP", 0, f"I0.{channel}")),
    ])

PATH_ROUTES = []
PATH_ROUTES.extend([
    ("AC_N_FAN", endpoint("QF0", "FA2", 3), endpoint("", "X", 0, terminal="X4:2"), ("N007", "N105")),
    ("AC_N_LIGHT", endpoint("QF0", "FA2", 3), endpoint("", "X", 1, terminal="X4:4"), ("N007", "N099")),
])
for label, target, logical_id in [
    ("PS1", endpoint("PS1", "DCP", 0, role="ROLE_PE_TBD"), "N023"),
    ("VFD1", endpoint("VFD1", "DCP", 0, role="ROLE_PE_TBD"), "N022"),
    ("MOTOR_TERMINAL", endpoint("", "X", 0, terminal="X3:4"), "N020"),
    ("CABINET", endpoint("CABINET1", "DCP", 0, role="ROLE_PE_TBD"), "N024"),
    ("DOOR", endpoint("DOOR1", "DCP", 0, role="ROLE_PE_TBD"), "N025"),
]:
    PATH_ROUTES.append(("PE_" + label, endpoint("", "X", 1, terminal="X1:3"), target, ("N003", logical_id)))
PATH_ROUTES.append(("DC0_SR1", endpoint("PS1", "DCP", 0, role="ROLE_0V_TBD"),
                    endpoint("SR1", "DCP", 0, role="ROLE_PWR_0V_TBD"), ("N031", "N038")))
for tag, symbol, logical_id in (("QF1", "FA2", "N008"), ("QF2", "FA2", "N026"),
                                ("QF3", "FA1", "N094"), ("QF4", "FA1", "N100"), ("HL1", "H", "N090")):
    PATH_ROUTES.append(("AC_L_" + tag, endpoint("QF0", "FA2", 1), endpoint(tag, symbol, 0), ("N006", logical_id)))
for tag, symbol, index, logical_id in (("QF1", "FA2", 2, "N009"), ("QF2", "FA2", 2, "N027"),
                                       ("HL1", "H", 1, "N091")):
    PATH_ROUTES.append(("AC_N_" + tag, endpoint("QF0", "FA2", 3), endpoint(tag, symbol, index), ("N007", logical_id)))
for tag, symbol, logical_id in (("FU1", "FA1", "N032"), ("FU2", "FA1", "N035"),
                                ("FU3", "FA1", "N068"), ("HL2", "H", "N092")):
    PATH_ROUTES.append(("DC24_" + tag, endpoint("PS1", "DCP", 0, role="ROLE_24V_TBD"),
                        endpoint(tag, symbol, 0), ("N030", logical_id)))
for label, target, logical_id in [
    ("PLC_M", endpoint("PLC1", "DCP", 0, role="ROLE_M_TBD"), "N034"),
    ("KA1", endpoint("KA1", "K", 0), "N074"), ("KA2", endpoint("KA2", "K", 0), "N075"),
    ("KA3", endpoint("KA3", "K", 0), "N082"), ("HL3", endpoint("HL3", "H", 0), "N085"),
    ("HL4", endpoint("HL4", "H", 0), "N087"), ("HL5", endpoint("HL5", "H", 0), "N089"),
    ("HL2", endpoint("HL2", "H", 1), "N093"), ("X2_6", endpoint("", "X", 0, terminal="X2:6"), "N106"),
]:
    PATH_ROUTES.append(("DC0_" + label, endpoint("PS1", "DCP", 0, role="ROLE_0V_TBD"), target, ("N031", logical_id)))


def _identity_int(record: dict, key: str, kind: str) -> int:
    if key not in record:
        raise RuntimeError(f"Native {kind} missing {key}; reload the identity-aware EPLAN bridge")
    value = record[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError(f"Native {kind} has invalid {key}")
    return value


def _native_database_id(functions: list[dict], edges: list[dict]) -> int | None:
    database_ids = set()
    function_ids = set()
    for function in functions:
        database = _identity_int(function, "database_id", "function")
        type_id = _identity_int(function, "type_id", "function")
        object_id = _identity_int(function, "object_id", "function")
        database_ids.add(database)
        identity = (database, type_id, object_id)
        if identity in function_ids:
            raise RuntimeError("Duplicate native function identity during audit")
        function_ids.add(identity)
    edge_signatures = {}
    for edge in edges:
        values = {key: _identity_int(edge, key, "connection") for key in (
            "database_id", "object_id", "start_type_id", "start_object_id", "start_index",
            "end_type_id", "end_object_id", "end_index")}
        database_ids.add(values["database_id"])
        identity = (values["database_id"], values["object_id"])
        signature = (values["start_type_id"], values["start_object_id"], values["start_index"],
                     values["end_type_id"], values["end_object_id"], values["end_index"], edge.get("placed"))
        if identity in edge_signatures and edge_signatures[identity] != signature:
            raise RuntimeError("Native connection identity changed during audit")
        edge_signatures[identity] = signature
    if len(database_ids) > 1:
        raise RuntimeError("Native project database_id changed during audit")
    return next(iter(database_ids)) if database_ids else None


def match_routes(functions: list[dict], placed: list[dict], routes=None) -> dict:
    database_id = _native_database_id(functions, placed)
    def resolve(selector):
        matches = [f for f in functions
                   if f["symbol"] == selector["symbol"]
                   and ("tag" not in selector or f["tag"] == selector["tag"])
                   and ("plc_address" not in selector or f.get("plc_address") == selector["plc_address"])
                   and ("role_designation" not in selector or f.get("role_designation") == selector["role_designation"])
                   and ("name_suffix" not in selector or f["name"].endswith(selector["name_suffix"]))]
        return matches[0] if len(matches) == 1 else None

    verified, missing, used = [], [], set()
    selected_routes = [(row[0], row[1], row[2], (row[0],)) for row in ROUTES] + PATH_ROUTES if routes is None else [(row[0], row[1], row[2], (row[0],)) for row in routes]
    for logical_id, source, target, path_ids in selected_routes:
        a, b = resolve(source), resolve(target)
        if a is None or b is None:
            missing.append({"id": logical_id, "reason": "endpoint_missing_or_ambiguous"})
            continue
        expected = {(a["type_id"], a["object_id"], source["pin"]),
                    (b["type_id"], b["object_id"], target["pin"])}
        matches = [e for e in placed if {(e["start_type_id"], e["start_object_id"], e["start_index"]),
                                        (e["end_type_id"], e["end_object_id"], e["end_index"])} == expected]
        if len(matches) != 1:
            missing.append({"id": logical_id, "reason": "missing_or_duplicate_native_connection",
                            "native_matches": len(matches)})
            continue
        edge = matches[0]
        used.add((edge["database_id"], edge["object_id"]))
        verified.append({"id": logical_id, "native_edge_id": edge["object_id"],
                         "database_id": edge["database_id"],
                         "design_path_ids": list(path_ids),
                         "source_type_id": a["type_id"],
                         "source_object_id": a["object_id"], "source_pin_index": source["pin"],
                         "target_type_id": b["type_id"],
                         "target_object_id": b["object_id"], "target_pin_index": target["pin"]})
    return {"database_id": database_id, "verified": verified, "missing": missing,
            "unexpected_native_edges": [e for e in placed if (e["database_id"], e["object_id"]) not in used]}


def checked(instance: str, operation: str, payload: dict | None = None) -> dict:
    result = request(instance, operation, payload)
    if not result.get("ok"):
        raise RuntimeError(f"{operation}: {result.get('error')}")
    return result["data"]


def collect() -> dict:
    from eplan_mcp import review
    model,binding=review.context(ROOT)
    route,_=review.route_for(model)
    if route in ('three_phase','reference'):
        from audit_three_phase import collect as collect_three_phase
        return collect_three_phase()
    report=collect_legacy();report['schema']=binding['collector_schema']
    return review.bind_report(report,binding,ROOT)


def collect_legacy() -> dict:
    instances = [entry for entry in discover() if entry["trial_writes_enabled"]]
    if len(instances) != 1:
        raise RuntimeError(f"Expected one dedicated trial instance, found {len(instances)}")
    instance = instances[0]["instance_id"]
    # This existing read-only audit also opens the fixed trial project if needed.
    checked(instance, "trial_plc_audit")
    projects = checked(instance, "list_projects")["projects"]
    names = [name for name in projects if name.lower().endswith("motor_forward_reverse_trial")]
    if len(names) != 1:
        raise RuntimeError(f"Trial project ambiguous: {names}")
    project_name = names[0]
    pages = checked(instance, "list_pages", {"project_name": project_name})["pages"]
    collected = []
    edges: dict[tuple[int, int], dict] = {}
    for page in pages:
        functions = checked(instance, "list_functions", {"project_name": project_name, "page_name": page})["functions"]
        page_edges = [edge for function in functions for edge in function["native_edges"]]
        _native_database_id(functions, page_edges)
        for function in functions:
            for edge in function["native_edges"]:
                identity = (edge["database_id"], edge["object_id"])
                previous = edges.get(identity)
                if previous is not None and {k: v for k, v in previous.items() if k != "page"} != edge:
                    raise RuntimeError("Native connection changed between page readbacks")
                edges.setdefault(identity, {"page": page, **edge})
        collected.append({"page": page, "functions": len(functions),
                          "with_native_connections": sum(bool(f["native_connections"]) for f in functions),
                          "with_graphical_connections": sum(bool(f["graphical_connections"]) for f in functions),
                          "connection_point_count": sum(f["connection_points"] for f in functions),
                          "function_details": [{"tag": f["visible_name"], "symbol": f["symbol"],
                                                "object_id": f["object_id"], "name": f["name"],
                                                "type_id": f["type_id"], "database_id": f["database_id"],
                                                "plc_address": f.get("plc_address"),
                                                "terminal_number": f.get("terminal_number"),
                                                "role_designation": f.get("role_designation"),
                                                "native": f["native_connections"],
                                                "graphical": f["graphical_connections"],
                                                "point_count": f["connection_points"],
                                                "location": f["location"]} for f in functions]})
    placed = [edge for edge in edges.values() if edge["placed"]]
    unplaced = [edge for edge in edges.values() if not edge["placed"]]
    design = json.loads((ROOT / "artifacts" / "motor_forward_reverse.design.json").read_text(encoding="utf-8"))
    design_tags = {d["tag"] for d in design["devices"]} - {"AC_BUS", "DC_BUS", "PE_BUS", "CABINET1", "DOOR1"}
    native_tags = {f["tag"] for page in collected for f in page["function_details"]}
    all_functions = [f for p in collected for f in p["function_details"]]
    database_id = _native_database_id(all_functions, list(edges.values()))
    route_check = match_routes(all_functions, placed)
    verified_intents = {logical_id for route in route_check["verified"] for logical_id in route["design_path_ids"]}
    return {"collected_utc": datetime.now(timezone.utc).isoformat(),
            "instance_id": instance, "database_id": database_id, "project_name": project_name,
            "summary": {"pages_scanned": len(collected), "schematic_pages": sum(p["page"] in {f"/{n}" for n in range(1,10)} for p in collected), "native_edges": len(edges),
                        "placed_edges": len(placed), "unplaced_edges": len(unplaced),
                        "design_connection_intents": len(design["connections"]),
                        "verified_native_routes": len(route_check["verified"]),
                        "design_intents_verified_native": len(verified_intents),
                        "design_intents_not_placed": len(design["connections"]) - len(verified_intents),
                        "design_device_tags_missing_native": sorted(design_tags - native_tags),
                        "unexpected_native_edges": len(route_check["unexpected_native_edges"]),
                        "missing_expected_routes": route_check["missing"],
                        "pages_without_graphical_connections": [p["page"] for p in collected if p["with_graphical_connections"] == 0]},
            "route_check": route_check, "pages": collected, "placed_edges": placed, "unplaced_edges": unplaced}


if __name__ == "__main__":
    report = collect()
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUT), **report["summary"]}, ensure_ascii=False, indent=2))

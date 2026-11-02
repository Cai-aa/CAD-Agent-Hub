"""Public stdio MCP surface. Native operations are intentionally explicit and bounded."""
from __future__ import annotations

from pathlib import Path
from typing import Literal
from mcp.server.fastmcp import FastMCP

from .bridge import discover, request
from .design import load_design, validate
from .bom import provisional_rows
from audit_native import collect as collect_native_trial_audit, OUT as NATIVE_AUDIT_PATH
from . import review
from . import curated_parts
from . import design as design_module
from .config import workspace_root, load_settings, source_root
import audit_native as native_module
import audit_three_phase as phase_module
import json
import csv
from datetime import datetime, timezone

ROOT=workspace_root()
for loaded in [__file__,design_module.__file__,native_module.__file__,phase_module.__file__,curated_parts.__file__]:
    review.register_loaded(loaded)

mcp = FastMCP("eplan29-lab", instructions="EPLAN 2.9 native bridge. The default review profile reads explicitly named open projects and provides local SDK search and offline intent checks. Optional trial writes remain restricted to the fixed disposable project, exact build and immutable plans. Discover capabilities before planning; production release and arbitrary scripts/actions are disabled.")


def _native_audit_snapshot() -> dict:
    return review.snapshot_status(NATIVE_AUDIT_PATH,ROOT)

def _collect_verified():
    status=review.runtime_status(ROOT,NATIVE_AUDIT_PATH)
    if status['code_stale']:raise review.EvidenceError('LOADED_CODE_STALE_RESTART_MCP')
    report=collect_native_trial_audit()
    review.atomic_snapshot(report,NATIVE_AUDIT_PATH,ROOT)
    return report


def _native_check_snapshot() -> dict:
    path = NATIVE_AUDIT_PATH.parent / "native_check_and_layout_summary.json"
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
        return {"available": True, "source": "saved_snapshot_not_live", "path": str(path),
                "message_categories": summary["categories"], "messages_returned": summary["messages_returned"],
                "previous_messages_cleared": summary["previous_messages_cleared"],
                "production_release_allowed": False}
    except (OSError, ValueError, KeyError, TypeError):
        return {"available": False, "source": "saved_snapshot_not_live"}


@mcp.tool(description="Return installed EPLAN 2.9 path, bridge status, and tested capability states.")
def eplan_diagnostics() -> dict:
    settings = load_settings()
    exe = settings.eplan_exe
    dll = exe.parent / 'Eplan.EplApi.DataModelu.dll' if exe else None
    if exe is None:
        return {'ok': False, 'error': 'EPLAN_EXE_NOT_CONFIGURED', 'bridge_instances': discover()}
    return {"eplan_executable_exists": exe.is_file(), "eplan_api_assembly_exists": dll.is_file(),
            "eplan_executable": str(exe), "bridge_instances": discover(),
            "native_audit_snapshot": _native_audit_snapshot(),
            "native_check_snapshot": _native_check_snapshot(),
            "capabilities": {"offline_design": "tested", "offline_validation": "tested",
                             "native_project_read": "smoke_tested_2.9.4.14642",
                             "native_page_create": "disposable_trial_smoke_tested",
                             "native_function_place": "disposable_trial_smoke_tested",
                             "native_unplaced_connection": "disposable_trial_smoke_tested",
                             "native_pdf_export": "disposable_trial_smoke_tested",
                             "native_routed_wire": "typed_trial_audit_available",
                             "native_plc_bind": "24_selected_CPU1214C_digital_channels" if load_design().get('client_engineering_revision') else "16_draft_addresses_smoke_tested",
                             "native_terminal_strip": "typed_trial_audit_available; see native_audit_snapshot",
                             "native_project_check": "last_used_local_scheme_executed; see native_check_snapshot for result and limits",
                             "native_project_backup": "trial_smoke_tested_restore_pending",
                             "native_part_import": "project_local_curated_records_and_references_only" if load_design().get('native_parts_revision') else "disabled",
                             "native_vendor_macros": "not_imported", "global_parts_database_import": "disabled", "production_release": "disabled"}}


@mcp.tool(description="Return the reviewable PLC-controlled VFD forward/reverse design model, with all unknown ratings marked TBD.")
def eplan_motor_design_get(section: str = "all") -> dict:
    model = load_design()
    if section == "all":
        return model
    if section not in model:
        return {"ok": False, "error": "Unknown design section"}
    return {"section": section, "data": model[section]}


@mcp.tool(description="Validate the stored motor design's endpoints, address uniqueness, interlocks, and unresolved inputs.")
def eplan_motor_design_validate() -> dict:
    return validate(load_design())


@mcp.tool(description="Read every native function and connection on all fixed trial project pages. Verify database/type/object/pin identities against the implemented route manifest, reject duplicate/unplaced or unexpected routes, and save detailed JSON evidence. This does not edit EPLAN.")
def eplan_trial_connectivity_audit() -> dict:
    try:
        report = _collect_verified()
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        failure={'checked_utc':datetime.now(timezone.utc).isoformat(),'code':'NATIVE_AUDIT_UNAVAILABLE','message':str(exc),'last_good_snapshot_overwritten':False}
        (ROOT/'artifacts/native_audit_failed_latest.json').write_text(json.dumps(failure,ensure_ascii=False,indent=2),encoding='utf-8')
        return {"ok": False, "error": {"code": "NATIVE_AUDIT_UNAVAILABLE", "message": str(exc)}}
    return {"ok": True, "data": {"path": str(NATIVE_AUDIT_PATH),'evidence':report['evidence'], **report["summary"]}}


@mcp.tool(description='Read loaded/disk source fingerprints, exact schema route and snapshot freshness. This does not open or modify EPLAN. A saved snapshot is never a live read.')
def eplan_runtime_status() -> dict:
    return review.runtime_status(ROOT,NATIVE_AUDIT_PATH)


@mcp.tool(description='Inspect project-internal native article records and function references in the fixed trial. Curated record assignment requires a compiled immutable plan. This does not import manufacturer macros, modify the global parts database or approve procurement/construction.')
def eplan_trial_curated_parts(instance_id: str, mode: Literal['inspect','probe','apply','reconcile','finalize']='inspect') -> dict:
    if mode!='inspect':
        try:
            curated_parts.load_pinned(ROOT)
            if mode=='finalize':curated_parts.load_document_pinned(ROOT)
        except (OSError,ValueError,KeyError,TypeError) as exc:return {'ok':False,'error':{'code':'CURATED_PLAN_UNAVAILABLE','message':str(exc)}}
    return request(instance_id,'trial_curated_parts_'+mode)


@mcp.tool(description='Inspect, apply or reconcile the compiled immutable client engineering plan in the fixed disposable project. Adds selected CPU1214C physical terminals, native commons/FE/unused analog wiring, spare channels, owned BOM and measured-layout documents. Does not authorize construction or field operation.')
def eplan_trial_client_engineering(instance_id: str, mode: Literal['inspect','apply','reconcile','finalize']='inspect') -> dict:
    return request(instance_id,'trial_client_engineering_'+mode)


@mcp.tool(description='Read-only acceptance with separate reference/construction scope. Optional fresh native read requires an already-open fixed trial. Changed or unbound evidence is rejected. Construction/commissioning release remains disabled.')
def eplan_design_acceptance(scope: Literal['reference','construction']='reference', refresh_native: bool=False) -> dict:
    try:
        if refresh_native:
            _collect_verified()
        status=review.snapshot_status(NATIVE_AUDIT_PATH,ROOT)
        if refresh_native and not status['stale']:
            status.update(source='live_native_this_call',live_verified_this_call=True)
        result=review.acceptance(load_design(),status,scope)
        runtime=review.runtime_status(ROOT,NATIVE_AUDIT_PATH)
        result['runtime_code_stale']=runtime['code_stale']
        if runtime['code_stale']:result.update(accepted=False,decision='LOADED_CODE_STALE_RESTART_MCP')
        return result
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        return {'ok':False,'scope':scope,'accepted':False,'error':{'code':'ACCEPTANCE_EVIDENCE_UNAVAILABLE','message':str(exc)},'production_release_allowed':False}


@mcp.tool(description="Export a provisional planning BOM to a fixed CSV: logical device groups, explicit terminal positions and unquantified hardware requirements. Siemens is the specified PLC vendor; unknown parts and purchase quantities remain TBD. This is not an EPLAN native parts report.")
def eplan_motor_design_bom_provisional_export() -> dict:
    model = load_design()
    rows = provisional_rows(model)
    path = ROOT / "artifacts" / "motor_forward_reverse_provisional_bom.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return {"ok": True, "path": str(path), "rows": len(rows),
            "logical_device_groups": sum(r["status"] == "provisional_unverified" for r in rows),
            "unquantified_hardware_requirements": sum(r["status"] == "unquantified_requirement" for r in rows),
            "native_eplan_report": False, "procurement_ready": False}


@mcp.tool(description="Discover native EPLAN bridge instances for this Windows user.")
def eplan_bridge_discover() -> dict:
    return {"instances": discover()}


@mcp.tool(description="Read the exact native EPLAN build and API thread identity from a discovered bridge instance.")
def eplan_bridge_hello(instance_id: str) -> dict:
    return request(instance_id, "hello")


@mcp.tool(description="List EPLAN projects currently open in the selected native bridge instance.")
def eplan_projects_list(instance_id: str) -> dict:
    return request(instance_id, "list_projects")


@mcp.tool(description="List pages in an explicitly named open EPLAN project. project_name is the full native project path.")
def eplan_pages_list(instance_id: str, project_name: str) -> dict:
    return request(instance_id, "list_pages", {"project_name": project_name})


@mcp.tool(description="Create a native EPLAN trial project from the installed GB base template in the fixed disposable workspace, create pages 1-9, and read them back. Never overwrites.")
def eplan_trial_prepare_pages(instance_id: str) -> dict:
    return request(instance_id, "prepare_trial_pages")


@mcp.tool(description="Place a fixed GB motor function M1 on page /4 of the disposable trial project and read back the native function. No arbitrary symbol or project input.")
def eplan_trial_place_motor(instance_id: str) -> dict:
    return request(instance_id, "trial_place_motor")


@mcp.tool(description="Read native function names, symbols, and connection point counts on an explicit EPLAN page.")
def eplan_functions_list(instance_id: str, project_name: str, page_name: str) -> dict:
    return request(instance_id, "list_functions", {"project_name": project_name, "page_name": page_name})


@mcp.tool(description="Inspect selected contact, relay coil and motor symbols in the installed GB library of the disposable trial project.")
def eplan_trial_symbol_catalog(instance_id: str) -> dict:
    return request(instance_id, "trial_symbol_catalog")


@mcp.tool(description="Place fixed KA1/KA2/KA3 relay coil functions with native GB symbols on trial page /7 and read them back.")
def eplan_trial_place_relay_coils(instance_id: str) -> dict:
    return request(instance_id, "trial_place_relay_coils")


@mcp.tool(description="Place fixed dual emergency-stop NC, start/stop/reset pushbuttons, and KA1/KA2/KA3 NO/NC contacts in the disposable trial project; read native function counts back.")
def eplan_trial_place_control_symbols(instance_id: str) -> dict:
    return request(instance_id, "trial_place_control_symbols")


@mcp.tool(description="Set Chinese descriptions on trial pages /1-/9 from the fixed design and verify native page properties.")
def eplan_trial_set_page_descriptions(instance_id: str) -> dict:
    return request(instance_id, "trial_set_page_descriptions")


@mcp.tool(description="Ensure two KA1/KA2 NC-to-opposite-coil native trial pairs; a fresh trial still needs the route and reconcile tools to make visible unique wires.")
def eplan_trial_connect_interlocks(instance_id: str) -> dict:
    return request(instance_id, "trial_connect_interlocks")


@mcp.tool(description="Export planned native schematic pages and existing BOM/layout review pages to the fixed PDF artifact for visual review.")
def eplan_trial_export_pdf(instance_id: str) -> dict:
    return request(instance_id, "trial_export_pdf")


@mcp.tool(description="Align fixed NC-to-opposite-coil interlock symbol pins in the disposable trial and invoke native Generate.Connections; return graphical and logical readback.")
def eplan_trial_route_interlocks(instance_id: str) -> dict:
    return request(instance_id, "trial_route_interlocks")


@mcp.tool(description="In the disposable trial only, remove redundant unplaced interlock connections after native graphical generation and require exactly two placed graphical connections.")
def eplan_trial_reconcile_interlocks(instance_id: str) -> dict:
    return request(instance_id, "trial_reconcile_interlocks")


@mcp.tool(description="Search the disposable trial project's native symbol libraries by one fixed engineering category; read only.")
def eplan_trial_asset_catalog(instance_id: str, category: Literal["power", "drive", "converter", "box", "plc", "terminal", "lamp", "fan", "breaker", "safety"]) -> dict:
    return request(instance_id, "trial_asset_catalog", {"category": category})


@mcp.tool(description="Place fixed generic isolator, breakers, indicators, fan, door switch and cabinet light functions on trial pages; no parts or wiring are assigned.")
def eplan_trial_place_aux_devices(instance_id: str) -> dict:
    return request(instance_id, "trial_place_aux_devices")


@mcp.tool(description="Place fixed native generic PLC1, PS1, VFD1 and SR1 boxes in disposable trial pages, with exact models and terminals still TBD.")
def eplan_trial_place_control_boxes(instance_id: str) -> dict:
    return request(instance_id, "trial_place_control_boxes")


@mcp.tool(description="Trial only: create native PLC1 I0.0 and Q0.0 connection points, then read back address and placement. CPU/module remains Siemens TBD.")
def eplan_trial_place_plc_probe(instance_id: str) -> dict:
    return request(instance_id, "trial_place_plc_probe")


@mcp.tool(description="Trial only: place 8 DI and 8 DO native PLC1 connection points with draft I0.x/Q0.x addresses and symbolic variables; actual Siemens CPU/module and physical terminals remain TBD.")
def eplan_trial_place_plc_channels(instance_id: str) -> dict:
    return request(instance_id, "trial_place_plc_channels")


@mcp.tool(description="Trial only: place native X1 terminal strip and terminal numbers 1-3 on page /9, then read back terminal designations.")
def eplan_trial_place_terminal_probe(instance_id: str) -> dict:
    return request(instance_id, "trial_place_terminal_probe")


@mcp.tool(description="Trial only: create missing X1-X4 definitions and 21 generic numbered terminals. Preserve existing terminal identities, pages and placements across distributed schematic pages; actual terminal parts remain TBD.")
def eplan_trial_place_terminal_strips(instance_id: str) -> dict:
    return request(instance_id, "trial_place_terminal_strips")


@mcp.tool(description="Read the disposable trial PLC boxes and every native PLCCP address, variable and PLC association to detect duplicates across EPLAN restarts.")
def eplan_trial_plc_audit(instance_id: str) -> dict:
    return request(instance_id, "trial_plc_audit")


@mcp.tool(description="Trial only: preserve the uniquely identified PLC Q0.0-Q0.7 channels at approved draft coordinates and remove disconnected duplicates from earlier failed retries.")
def eplan_trial_reconcile_plc_channels(instance_id: str) -> dict:
    return request(instance_id, "trial_reconcile_plc_channels")


@mcp.tool(description="Trial only: place an auxiliary PLC1 box on output page /7 and read back its related Q channels; no extra part assignment.")
def eplan_trial_place_plc_output_box(instance_id: str) -> dict:
    return request(instance_id, "trial_place_plc_output_box")


@mcp.tool(description="Read the trial's native X1-X4 strips and terminal object IDs/numbers to detect repeated terminal records after reopening EPLAN.")
def eplan_trial_terminal_audit(instance_id: str) -> dict:
    return request(instance_id, "trial_terminal_audit")


@mcp.tool(description="Trial only: remove strictly identical, disconnected duplicate X2-X4 terminal placements and verify 21 unique native terminals.")
def eplan_trial_reconcile_terminals(instance_id: str) -> dict:
    return request(instance_id, "trial_reconcile_terminals")


@mcp.tool(description="Run EPLAN's native project check on the fixed disposable trial using the locally selected verification scheme; return messages without declaring production readiness.")
def eplan_trial_check_project(instance_id: str) -> dict:
    return request(instance_id, "trial_check_project")


@mcp.tool(description="Trial only: assign documented SPECIAL/DC and TDEF symbol logic to generic boxes/strips and mark only one SB0 contact as main; native check must be rerun.")
def eplan_trial_repair_definitions(instance_id: str) -> dict:
    return request(instance_id, "trial_repair_definitions")


@mcp.tool(description="Trial only: generate visible native Q0.0→KA2 NC and Q0.1→KA1 NC lines, then check both required and forbidden pairs.")
def eplan_trial_route_plc_outputs(instance_id: str) -> dict:
    return request(instance_id, "trial_route_plc_outputs")


@mcp.tool(description="Trial only: generate four visible native Q0.2→KA3 and Q0.3-Q0.5→HL3-HL5 routes with required/forbidden pair readback.")
def eplan_trial_route_aux_outputs(instance_id: str) -> dict:
    return request(instance_id, "trial_route_aux_outputs")


@mcp.tool(description="Trial only: route TS1 to FAN1 and SQ1 to EL1 with native auto-connections, then verify required and forbidden connection pairs. Remaining supply and return wiring is not included.")
def eplan_trial_route_aux_services(instance_id: str) -> dict:
    return request(instance_id, "trial_route_aux_services")


@mcp.tool(description="Trial only: move the existing X2:2-X2:5 terminals to input page /6 and route SB1-SB4 through their respective terminals to I0.0-I0.3. Verify eight placed native connections and reject crossed channels. Button supply remains incomplete.")
def eplan_trial_route_plc_inputs(instance_id: str) -> dict:
    return request(instance_id, "trial_route_plc_inputs")


@mcp.tool(description="Close only the fixed disposable trial project through EPLAN's native Project.Close API and verify it is no longer open. Use after backup/export before shutting down the dedicated instance.")
def eplan_trial_close_project(instance_id: str) -> dict:
    return request(instance_id, "trial_close_project")


@mcp.tool(description="Fixed trial only: append the pinned 2026-10-22 start/stop logic review to finalized page 16. Preserve 121 native edges; reject conflicting user text. No PLC deployment.")
def eplan_trial_review_logic(instance_id: str) -> dict:
    return request(instance_id, "trial_review_logic")


@mcp.tool(description="Fixed trial only: repair the confirmed fan PE omission with one extra X7PE terminal, keep all other conductive routes and move the overlapping KM0 note. Reject changed baseline; read back exact resulting 123 edges. No device ratings or safety interfaces are guessed.")
def eplan_trial_repair_basic_requirements(instance_id: str) -> dict:
    return request(instance_id, "trial_repair_basic_requirements")


@mcp.tool(description="Fixed trial only: inspect installed reference symbols, or apply the pinned V20/3SK1 reference-interface plan to the exact captured 123-edge baseline. Manufacturer references remain subject to actual ratings, PLC compatibility and standstill validation. No commissioning or PLC deployment.")
def eplan_trial_complete_reference_interfaces(instance_id: str, mode: Literal['inspect', 'apply', 'reconcile', 'finalize','parameter_fix'] = 'inspect') -> dict:
    return request(instance_id, {'inspect':'trial_reference_inspect','apply':'trial_reference_complete','reconcile':'trial_reference_reconcile','finalize':'trial_reference_finalize','parameter_fix':'trial_reference_parameter_fix'}[mode])


@mcp.tool(description="Trial only: move X1:1/X1:2 to page /2 and create four visible native L/N connections through QS1 to QF0. Verify exact native pin indices and keep downstream distribution incomplete.")
def eplan_trial_route_ac_input(instance_id: str) -> dict:
    return request(instance_id, "trial_route_ac_input")


@mcp.tool(description="Read installed trial symbol variants for interruption points, device connection points and potential connection points, including native pin geometry. No symbol placement.")
def eplan_trial_connection_catalog(instance_id: str) -> dict:
    return request(instance_id, "trial_connection_catalog")


@mcp.tool(description="Trial only: route QF3/QF4 from page /2 through native named interruption points to X4:3/X4:1 and SQ1/TS1 on page /8. Verify exact native endpoint pins; neutral and upstream branch supply remain incomplete.")
def eplan_trial_route_aux_feeds(instance_id: str) -> dict:
    return request(instance_id, "trial_route_aux_feeds")


@mcp.tool(description="Trial only: distribute QF0 L/N to QF1-QF4 and HL1 with native named star interruption points. Verify eight exact native edges and L/N separation; logical AC_BUS nodes collapse into these native nets.")
def eplan_trial_route_ac_distribution(instance_id: str) -> dict:
    return request(instance_id, "trial_route_ac_distribution")


@mcp.tool(description="Trial only: give PS1 five native generic device connection points labeled as logical roles with physical pins TBD, resize its black box, and route QF2 L/N to PS1 through native interruption points. PE and DC output remain incomplete.")
def eplan_trial_place_ps1_interfaces(instance_id: str) -> dict:
    return request(instance_id, "trial_place_ps1_interfaces")


@mcp.tool(description="Trial only: route PS1 24V/0V through FU1-FU3 to generic PLC supply roles, button common X2:1, X2:6 and relay/lamp returns. Verify 20 placed native edges. PLC physical pins and 24V sourcing output hardware remain TBD.")
def eplan_trial_route_dc_distribution(instance_id: str) -> dict:
    return request(instance_id, "trial_route_dc_distribution")


@mcp.tool(description="Trial only: route FAN1/EL1 neutral returns through X4:2/X4:4 to the AC_N network, verifying four exact native pin paths and L/N separation. PE requirements remain subject to device selection.")
def eplan_trial_route_aux_neutral(instance_id: str) -> dict:
    return request(instance_id, "trial_route_aux_neutral")


@mcp.tool(description="Trial only: route QF1 through two generic KM0 power contacts into VFD1 logical L/N roles, then VFD U/V/W through X3:1-3 to M1. Verify ten placed native pin paths and phase separation. Actual contactor/VFD/motor part ratings and PE remain unverified.")
def eplan_trial_route_drive_power(instance_id: str) -> dict:
    return request(instance_id, "trial_route_drive_power")


@mcp.tool(description="Trial only: route the logical PE network from X1:3 to PS1/VFD1/cabinet/door and X3:4 to the installed M3 symbol's verified PE pin. Verify six placed routes and N/PE separation. PE bus hardware and physical parts remain TBD.")
def eplan_trial_route_protective_earth(instance_id: str) -> dict:
    return request(instance_id, "trial_route_protective_earth")


@mcp.tool(description="Trial only: route both SB0 NC channels through X2:7-10 to generic SR1 channel roles, plus SR1 supply and a permit lead to KM0. Verify twelve routes; EDM, status common, reset and safe return remain unresolved, so the safety circuit is incomplete.")
def eplan_trial_route_safety_channels(instance_id: str) -> dict:
    return request(instance_id, "trial_route_safety_channels")


@mcp.tool(description="Trial only: apply a SHA256-pinned, model-bound review plan containing bounded native text/table/mechanical rectangles. Add provisional BOM pages 10-11 and 2D cabinet/door concept pages 12-13 plus notes. This creates no parts report, part placement or electrical wires.")
def eplan_trial_add_review_pages(instance_id: str) -> dict:
    return request(instance_id, "trial_add_review_pages")


@mcp.tool(description="Trial only: show explicit X1-X4 device tags on the first terminals of distributed schematic groups. Verify native strip identities and terminal numbers remain unchanged; create no electrical connections.")
def eplan_trial_label_terminal_groups(instance_id: str) -> dict:
    return request(instance_id, "trial_label_terminal_groups")


@mcp.tool(description="Trial only: apply the compiled, hash-pinned Chinese annotation and Siemens PLC box layout revision. Preserve native endpoint identities and verify the exact electrical edge set. CPU, hardware pins and COM grouping remain TBD.")
def eplan_trial_format_plc_chinese(instance_id: str) -> dict:
    return request(instance_id, "trial_format_plc_chinese")

@mcp.tool(description="Trial only: stagger X1-X4 terminal placements, regenerate native connections, and require zero unintended terminal links before any cable wiring is added.")
def eplan_trial_spread_terminals(instance_id: str) -> dict:
    return request(instance_id, "trial_spread_terminals")


@mcp.tool(description="Create a timestamped native .zw1 EPLAN backup of the fixed disposable trial project without overwriting prior archives.")
def eplan_trial_backup_project(instance_id: str) -> dict:
    return request(instance_id, "trial_backup_project")


@mcp.tool(description="Trial only: separate HL1 from QS1, regenerate native connections, and require zero unintended AC page connections.")
def eplan_trial_fix_ac_indicator(instance_id: str) -> dict:
    return request(instance_id, "trial_fix_ac_indicator")


@mcp.tool(description="Return production drawing preflight. Fixed trial tools work, while full project generation and release remain gated.")
def eplan_draw_preflight() -> dict:
    model = load_design()
    result = validate(model)
    return {"ready": False, "reason": "Native trial coverage and physical hardware/interface release gates remain incomplete.",
            "design_validation": result,
            "native_audit_snapshot": _native_audit_snapshot(),
            "native_check_snapshot": _native_check_snapshot(),
            "hardware_release_blockers": model.get("release_blockers", []),
            "missing_evidence": ["approved production base project and asset manifests",
                                 "Siemens CPU/module selection",
                                 "VFD/SR1/PLC terminal maps", "approved native macros or symbols",
                                 "all design connection intents mapped and natively verified",
                                 "fixed native check scheme and BOM/I-O/wiring report verification",
                                 "electrical ratings and safety risk assessment"]}


def main() -> None:
    from .enhancements import configure_server
    configure_server(mcp)
    mcp.run(transport="stdio")


@mcp.tool(description="Read the fixed trial's installed three/four-pole symbol geometry before upgrading the three-phase power topology; no object changes.")
def eplan_trial_three_phase_catalog(instance_id: str) -> dict:
    return request(instance_id, "trial_three_phase_catalog")


@mcp.tool(description="Trial only: apply the immutable three-phase supply upgrade, three-pole VFD feed and bounded two-target distribution terminal chains. Verify the full native edge set; unknown voltages, parts and safety interfaces still block production.")
def eplan_trial_upgrade_three_phase(instance_id: str) -> dict:
    return request(instance_id, "trial_upgrade_three_phase")


@mcp.tool(description="Trial only: reconcile the captured three-phase partial checkpoint by assigning the installed symbols' native function definitions. Reject changed circuitry and verify the complete expected typed endpoint edge set before finalizing annotations.")
def eplan_trial_reconcile_three_phase(instance_id: str) -> dict:
    return request(instance_id, "trial_reconcile_three_phase")


@mcp.tool(description="Trial only: reorder the verified three-phase document into schematics, tables/BOM, then cabinet/door concepts. Use native validated page rename; preserve the entire typed electrical edge set and reject changed cover/page preconditions.")
def eplan_trial_finalize_three_phase_order(instance_id: str) -> dict:
    return request(instance_id, "trial_finalize_three_phase_order")

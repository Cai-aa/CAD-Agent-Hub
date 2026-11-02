"""Reviewable logical design. Endpoints are roles, not invented vendor terminal numbers."""
from __future__ import annotations

import json
import math
from pathlib import Path
from .config import workspace_root

MODEL_PATH = workspace_root() / "artifacts" / "motor_forward_reverse.design.json"


def load_design() -> dict:
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def _validate_reference_interfaces(model, endpoint_pairs, add):
    """Check the selected reference circuit, without claiming installed hardware.

    These are the published 1.4 interface choices, not generic rules for every
    Siemens product. Physical pin matching, ratings and safety acceptance stay
    separate release gates even when every reference wire is defined.
    """
    pin_map = model.get("manufacturer_reference_pin_map", {})
    expected_maps = {
        "VFD1": {"DI1": "8", "DI2": "9", "RESET": "10",
                 "DI_REFERENCE_ROLE": "12", "DI_SUPPLY_ROLE": "13",
                 "CONTROL_0V": "14", "READY_COMMON_ROLE": "15+", "READY": "16-",
                 "FAULT_COMMON_ROLE": "19", "FAULT": "18"},
        "SR1": {"PWR_PLUS_ROLE": "A1", "PWR_0V_ROLE": "A2", "CH_A_OUT": "T1",
                "CH_A_RETURN": "IN1", "CH_B_OUT": "T2", "CH_B_RETURN": "IN2",
                "TEST3": "T3", "INPUT3": "IN3", "EDM_SEND": "T4", "EDM_RETURN": "IN F/S",
                "SAFE_IN_ROLE": "13", "SAFE_OUT": "14", "STATUS_COMMON_ROLE": "23", "STATUS": "24"},
        "KM0": {"A1": "A1", "A2": "A2", "EDM_IN": "21", "EDM_OUT": "22"},
        "KA1": {"A1": "A1", "A2": "A2", "NO_IN": "13", "NO_OUT": "14", "NC_IN": "21", "NC_OUT": "22"},
        "KA2": {"A1": "A1", "A2": "A2", "NO_IN": "13", "NO_OUT": "14", "NC_IN": "21", "NC_OUT": "22"},
        "KA3": {"A1": "A1", "A2": "A2", "NO_IN": "13", "NO_OUT": "14"},
        "SB5": {"NO_IN": "13", "NO_OUT": "14"},
        "R1": {"IN": "1", "OUT": "2"},
    }
    for tag, expected in expected_maps.items():
        actual = pin_map.get(tag, {})
        for role, terminal in expected.items():
            if actual.get(role) != terminal:
                add("REFERENCE_TERMINAL_MISMATCH", "error", f"{tag}.{role} must map to reference terminal {terminal}")

    # Validate the complete incident wire set at sensitive interfaces. Merely
    # counting wires misses a swapped supply/common, a bypassed EDM contact or
    # an extra wire shorting two otherwise correct reference circuits.
    vfd_links = {
        ("VFD1.DI_SUPPLY_ROLE", "KA1.NO_IN"), ("VFD1.DI_SUPPLY_ROLE", "KA2.NO_IN"),
        ("VFD1.DI_SUPPLY_ROLE", "KA3.NO_IN"), ("KA1.NO_OUT", "VFD1.DI1"),
        ("KA2.NO_OUT", "VFD1.DI2"), ("KA3.NO_OUT", "VFD1.RESET"),
        ("VFD1.CONTROL_0V", "VFD1.DI_REFERENCE_ROLE"),
        ("FU2.OUT", "VFD1.READY_COMMON_ROLE"), ("VFD1.READY", "PLC1.I0.5"),
        ("FU2.OUT", "VFD1.FAULT_COMMON_ROLE"), ("VFD1.FAULT", "PLC1.I0.6"),
    }
    safety_links = {
        ("FU2.OUT", "SR1.PWR_PLUS_ROLE"), ("DC_BUS.0V", "SR1.PWR_0V_ROLE"),
        ("SR1.CH_A_OUT", "X2.7"), ("X2.8", "SR1.CH_A_RETURN"),
        ("SR1.CH_B_OUT", "X2.9"), ("X2.10", "SR1.CH_B_RETURN"),
        ("FU3.OUT", "SR1.SAFE_IN_ROLE"), ("SR1.SAFE_OUT", "KM0.A1"),
        ("KM0.A2", "DC_BUS.0V"), ("SR1.EDM_SEND", "KM0.EDM_IN"),
        ("KM0.EDM_OUT", "SB5.NO_IN"), ("SB5.NO_OUT", "SR1.EDM_RETURN"),
        ("SR1.TEST3", "SR1.INPUT3"), ("FU2.OUT", "SR1.STATUS_COMMON_ROLE"),
        ("SR1.STATUS", "PLC1.I0.4"), ("SR1.STATUS", "R1.IN"), ("R1.OUT", "DC_BUS.0V"),
    }
    for code, required, interfaces in (
        ("REFERENCE_VFD_WIRING_MISMATCH", vfd_links,
         {f"VFD1.{role}" for role in expected_maps["VFD1"]}),
        ("REFERENCE_SAFETY_WIRING_MISMATCH", safety_links,
         {f"SR1.{role}" for role in expected_maps["SR1"]} |
         {"KM0.A1", "KM0.A2", "KM0.EDM_IN", "KM0.EDM_OUT", "SB5.NO_IN", "SB5.NO_OUT", "R1.IN", "R1.OUT"}),
    ):
        actual = {pair for pair in endpoint_pairs if interfaces.intersection(pair)}
        for src, dst in sorted(required - actual):
            add(code, "error", f"Missing reference wire: {src} -> {dst}")
        for src, dst in sorted(actual - required):
            add(code, "error", f"Unexpected reference wire: {src} -> {dst}")

    expected_parameters = {
        "P0719[0]": 0, "P0700[0]": 2, "P0727[0]": 1,
        "P0701[0]": 1, "P0702[0]": 2, "P0703[0]": 9, "P0704[0]": 0,
        "P0731[0]": "52.0", "P0732[0]": "52.3", "P0748": 2, "P1210": 0,
        "P1000[0]": 1, "P1031[0]": 0, "P1032": 0,
        "P1035[0]": 0, "P1036[0]": 0, "P1041[0]": 0, "P1043[0]": 0,
        "P1055[0]": 0, "P1056[0]": 0, "P1057": 0, "P1075[0]": 0,
    }
    parameters = model.get("logic_contract", {}).get("VFD_parameter_targets", {})
    for key, value in expected_parameters.items():
        if parameters.get(key) != value or isinstance(parameters.get(key), bool):
            add("REFERENCE_VFD_PARAMETER_MISMATCH", "error", f"{key} must equal {value!r} for this reference wiring and polarity")
    speed=parameters.get('P1040[0]')
    policy=model.get('logic_contract',{}).get('setpoint_policy',{})
    valid_speed=(speed=='TBD_positive_Hz' or (isinstance(speed,(int,float)) and not isinstance(speed,bool) and math.isfinite(speed) and speed>0))
    if (not valid_speed or policy.get('positive_magnitude_only') is not True or
            policy.get('runtime_mop_up_down_enabled') is not False or policy.get('jog_enabled') is not False or
            policy.get('additional_setpoint_enabled') is not False or policy.get('direction_authority')!='PLC_independent_ON_FWD_ON_REV'):
        add('REFERENCE_VFD_SPEED_POLICY','error','A positive commissioned magnitude must not be reversed by runtime MOP/JOG/additional sources')

    selection = model.get("reference_selection", {})
    if (selection.get("SR1", {}).get("article_number") != "3SK1111-1AB30" or
            selection.get("SB5", {}).get("distinct_from_SB4_VFD_reset") is not True):
        add("REFERENCE_SAFETY_SELECTION_MISMATCH", "error", "3SK1111 reference requires a separate SB5 monitored safety reset, independent of SB4 drive reset")
    # The resistor is a deliberate minimum-contact-load branch, not a promise
    # that every value in the calculation examples is a valid system supply.
    resistor = selection.get("R1", {})
    if (resistor.get("nominal_resistance_ohm") != 2200 or
            resistor.get("minimum_reference_power_W") != 1.0 or
            resistor.get("examples_define_full_system_operating_range") is not False):
        add("REFERENCE_STATUS_LOAD_MISMATCH", "error", "SR1 23-24 monitoring requires the declared 2.2kohm/1W reference load; example voltages are not the system operating range")


def validate(model: dict) -> dict:
    findings = []
    def add(code, severity, detail):
        findings.append({"code": code, "severity": severity, "detail": detail})
    reference = (model.get("schema_version") == "motor-design-1.4-reference-interfaces" or
                 "manufacturer_reference_pin_map" in model or "reference_selection" in model)
    ids = [d["tag"] for d in model.get("devices", [])]
    if len(ids) != len(set(ids)):
        add("DUPLICATE_DEVICE", "error", "Duplicate device tag")
    tags = set(ids)
    contract = model.get("endpoint_contract")
    contract_devices = contract.get("devices") if isinstance(contract, dict) else None
    contract_present = isinstance(contract_devices, dict) and bool(contract_devices)
    allowed_endpoints = set()
    if not contract_present:
        add("ENDPOINT_CONTRACT_MISSING", "error", "Explicit logical endpoint contract is required")
    else:
        if contract.get("scope") != "logical_roles_only" or contract.get("physical_pin_mapping_verified") is not False:
            add("ENDPOINT_CONTRACT_SCOPE_INVALID", "error", "This draft contract must identify logical roles, not verified physical pins")
        for tag in sorted(tags - contract_devices.keys()):
            add("ENDPOINT_CONTRACT_DEVICE_MISSING", "error", tag)
        for tag, interfaces in contract_devices.items():
            if tag not in tags:
                add("ENDPOINT_CONTRACT_UNKNOWN_DEVICE", "error", str(tag))
                continue
            if (not isinstance(interfaces, list) or not interfaces or
                    any(not isinstance(role, str) or not role or role != role.strip() for role in interfaces)):
                add("ENDPOINT_CONTRACT_INVALID_INTERFACES", "error", tag)
                continue
            if len(interfaces) != len(set(interfaces)):
                add("ENDPOINT_CONTRACT_DUPLICATE_INTERFACE", "error", tag)
            allowed_endpoints.update(f"{tag}.{role}" for role in interfaces)
    addresses = []
    for io in model.get("plc_io", []):
        addr = io["address"]
        if addr in addresses:
            add("DUPLICATE_PLC_ADDRESS", "error", addr)
        addresses.append(addr)
        if io["device"] not in tags:
            add("UNKNOWN_IO_DEVICE", "error", io["device"])
        if contract_present and f"{contract.get('plc_device_tag')}.{addr}" not in allowed_endpoints:
            add("UNKNOWN_PLC_ADDRESS", "error", str(addr))
    if contract_present:
        for terminal in model.get("terminals", []):
            name = f"{terminal['strip']}.{terminal['number']}"
            if name not in allowed_endpoints:
                add("UNKNOWN_TERMINAL_ENDPOINT", "error", name)
    networks = model.get("connections", [])
    endpoint_pairs = set()
    connection_ids = set()
    for c in networks:
        connection_id = c.get("id")
        if not isinstance(connection_id, str) or not connection_id:
            add("INVALID_CONNECTION_ID", "error", str(connection_id))
        elif connection_id in connection_ids:
            add("DUPLICATE_CONNECTION_ID", "error", connection_id)
        else:
            connection_ids.add(connection_id)
        for side in ("from", "to"):
            name = c.get(side)
            if not isinstance(name, str):
                add("UNKNOWN_ENDPOINT", "error", str(name))
                continue
            # Compare the complete endpoint string. Splitting on the last dot
            # would corrupt valid PLC interfaces such as PLC1.I0.0.
            tag, separator, interface = name.partition(".")
            if (tag not in tags or not separator or not interface or
                    (contract_present and name not in allowed_endpoints)):
                add("UNKNOWN_ENDPOINT", "error", name)
        if not isinstance(c.get("from"), str) or not isinstance(c.get("to"), str):
            continue
        pair = (c["from"], c["to"])
        if pair in endpoint_pairs:
            add("DUPLICATE_CONNECTION", "error", str(pair))
        endpoint_pairs.add(pair)
    required = [("PLC1.Q0.0", "KA2.NC_IN"), ("KA2.NC_OUT", "KA1.A1"),
                ("PLC1.Q0.1", "KA1.NC_IN"), ("KA1.NC_OUT", "KA2.A1"),
                ("SB0.CH_A_NC_OUT", "X2.8"),
                ("SB0.CH_B_NC_OUT", "X2.10"),
                ("SR1.SAFE_OUT", "KM0.A1"),
                ("VFD1.U", "X3.1"), ("VFD1.V", "X3.2"),
                ("VFD1.W", "X3.3"), ("PE_BUS.PE", "X3.4")]
    for pair in required:
        if pair not in endpoint_pairs:
            add("MISSING_REQUIRED_LINK", "error", f"{pair[0]} -> {pair[1]}")
    for c in networks:
        if not isinstance(c.get("from"), str) or not isinstance(c.get("to"), str):
            continue
        if c["potential"] == "PE" and (c["from"].endswith(".N") or c["to"].endswith(".N")):
            add("PE_N_MIX", "error", c["id"])
        if c["potential"].startswith("AC") and any(x in c["to"] for x in (".I0.", ".Q0.")):
            add("AC_TO_PLC_IO", "error", c["id"])
    unresolved = model.get("tbd", [])
    if model.get('logic_review_revision') or reference:
        contract=model.get('logic_contract',{})
        rows={row['state']:row for row in model.get('logic',[])}
        if (contract.get('initial_state')!='STOP_UNVERIFIED' or contract.get('start_source_state')!='IDLE_ARMED' or
            any(rows.get(s,{}).get('from_state')!='IDLE_ARMED' for s in ['FORWARD','REVERSE']) or
            rows.get('IDLE_ARM',{}).get('from_state')!='IDLE_DISARMED' or
            rows.get('IDLE_ARM',{}).get('to_state')!='IDLE_ARMED' or
            rows.get('STANDSTILL_VERIFIED',{}).get('from_state')!='STOP_UNVERIFIED' or
            rows.get('STANDSTILL_VERIFIED',{}).get('to_state')!='IDLE_DISARMED'):
            add('INCONSISTENT_START_STATE_CHAIN','error','Stop verification, release/arming and fresh-edge start must form one reachable state chain')
        if rows.get('READY_LOST',{}).get('to_state')!='STOP_UNVERIFIED':
            add('READY_LOSS_UNHANDLED','error','READY loss while running must remove run permission and require rearming')
        if model.get('logic_review_revision') == '2026-10-22-r2' or reference:
            reset=contract.get('reset_sublogic',{})
            if ('RESET' in contract.get('transition_priority',[]) or
                reset.get('scope')!='independent_Q0_2_pulse_not_main_state_priority' or
                reset.get('output_owner')!='reset_sublogic_only' or
                reset.get('fault_level_may_remain_active') is not True or
                reset.get('ready_required') is not False or
                reset.get('held_button_retrigger') is not False or
                reset.get('motor_start_inhibited_while_active') is not True or
                reset.get('changes_run_state_arming_or_standstill_permission') is not False):
                add('RESET_SUBLOGIC_CONTRADICTORY','error','Reset must be an independent bounded pulse: a persistent fault/READY low cannot mask it; reset cannot arm or start the motor')
    if (model.get('schema_version','').endswith('three-phase') or reference or
            'restart_gate' in model.get('logic_contract', {})):
        gate=model.get('logic_contract',{}).get('restart_gate',{})
        if (gate.get('scope')!='all_motor_start_and_restart_paths' or
            gate.get('ready_is_standstill') is not False or gate.get('run_command_off_is_standstill') is not False or
            gate.get('automatic_pending_opposite_start') is not False or
            gate.get('no_validated_standstill_criterion')!='block_all_start_and_restart_permissions'):
            add('UNSAFE_RESTART_GATE','error','All start/restart paths require validated standstill; READY and command-off are insufficient')
    if reference:
        _validate_reference_interfaces(model, endpoint_pairs, add)
        logic = model.get('logic_contract', {})
        gate = logic.get('restart_gate', {})
        permissions = {
            'validated_standstill_criterion_configured',
            'standstill_evidence_current_and_valid_for_this_stop_or_restore_event',
            'validated_stop_sequence_and_required_delay_completed', 'safety_ok',
            'vfd_ready', 'not_vfd_fault', 'stop_nc_healthy', 'both_direction_outputs_off',
        }
        if (not permissions.issubset(gate.get('required_permissions', [])) or
                logic.get('start_requires_fresh_rising_edge') is not True or
                logic.get('start_arming_requires_both_start_buttons_released') is not True or
                logic.get('automatic_pending_opposite_start') is not False or
                logic.get('stop_confirmation', {}).get('VFD_READY_is_stopped_confirmation') is not False):
            add('UNSAFE_RESTART_GATE', 'error', 'Current-event stop evidence, all start permissives, released buttons and a fresh edge must remain mandatory')
        transitions = {row.get('event'): row for row in gate.get('transitions', [])}
        for event, target in {
            'power_on_or_restore': 'STOP_UNVERIFIED',
            'normal_stop_or_opposite_request': 'STOP_UNVERIFIED',
            'fault_or_safety_loss': 'FAULT_OR_EMERGENCY_STOP',
            'fault_or_safety_recovered': 'STOP_UNVERIFIED',
            'simultaneous_direction_requests': 'STOP_UNVERIFIED',
        }.items():
            row = transitions.get(event, {})
            if (row.get('to') != target or row.get('outputs') != 'both_off' or
                    row.get('clear_pending_start') is not True):
                add('UNSAFE_RESTART_GATE', 'error', f'{event} must remove both commands and pending starts; recovery requires current-event stop validation')
        reset = logic.get('reset_sublogic', {})
        required_reset = {
            'fresh_PB_RESET_rising_edge', 'both_start_buttons_released',
            'both_run_outputs_off', 'stop_nc_healthy', 'safety_ok',
            'reset_interface_verified', 'positive_finite_pulse_width_validated',
        }
        abort_reset = {
            'any_run_command', 'ordinary_stop_or_stop_nc_open', 'safety_loss',
            'either_start_button_pressed', 'interface_or_pulse_configuration_invalid',
        }
        width = reset.get('pulse_width_seconds')
        invalid_width = width is not None and (isinstance(width, bool) or
            not isinstance(width, (int, float)) or not math.isfinite(width) or width <= 0)
        if (not required_reset.issubset(reset.get('requires', [])) or
                not abort_reset.issubset(reset.get('abort_conditions', [])) or invalid_width or
                (reset.get('pulse_width_validated') is True and width is None)):
            add('RESET_SUBLOGIC_CONTRADICTORY', 'error', 'Reset must require a validated positive finite pulse, stopped commands, released starts and safety/stop conditions; unsafe events abort it')
    release_blockers = model.get('release_blockers', [])
    if unresolved:
        add("PRODUCTION_RELEASE_BLOCKED", "blocker", f"{len(unresolved)} unresolved design inputs")
    elif release_blockers or reference:
        add("PRODUCTION_RELEASE_BLOCKED", "blocker", "Reference interfaces do not verify field ratings, final PLC modules, standstill, safety or manufacturing dimensions")
    return {"ok": not any(f["severity"] == "error" for f in findings),
            "validation_scope": "logical_model_consistency_only; not native circuit completeness or functional acceptance",
            "production_release_allowed": False if unresolved or release_blockers or reference else not findings,
            "counts": {"pages": len(model.get("pages", [])), "devices": len(ids),
                       "plc_io": len(addresses), "connections": len(networks),
                       "terminals": len(model.get("terminals", []))},
            "findings": findings}

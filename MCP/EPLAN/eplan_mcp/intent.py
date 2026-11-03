"""Generic wire-graph checks. Never treats contact logic as a conducting wire."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parent / 'schemas/design-intent.schema.json'


def schema():
    return json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))


def validate_intent(model):
    findings = []

    def add(code, severity, detail):
        findings.append({'code': code, 'severity': severity, 'detail': detail})

    for error in Draft202012Validator(schema()).iter_errors(model):
        add('SCHEMA_INVALID', 'error', '/'.join(str(p) for p in error.absolute_path) + ': ' + error.message)
        if len(findings) >= 100:
            break
    if findings:
        return result(model, findings)
    ports = {}
    tags = set()
    for device in model['devices']:
        tag = device['tag']
        if tag in tags:
            add('DUPLICATE_DEVICE_TAG', 'error', tag)
        tags.add(tag)
        if not device.get('description_zh'):
            add('CHINESE_FUNCTION_TEXT_MISSING', 'warning', tag)
        if not device.get('part_number') or device['part_number'].upper() == 'TBD':
            add('PART_NOT_SELECTED', 'warning', tag)
        for port in device['ports']:
            name = tag + ':' + port['id']
            if name in ports:
                add('DUPLICATE_PORT', 'error', name)
            ports[name] = port
            if not port.get('physical_pin') or port['physical_pin'].upper() == 'TBD':
                add('PHYSICAL_PIN_UNVERIFIED', 'warning', name)

    parent = {p: p for p in ports}
    degree = Counter()

    def find(p):
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    edge_ids, pairs = set(), set()
    valid_wires = []
    for wire in model['connections']:
        a, b = wire['from'], wire['to']
        if wire['id'] in edge_ids:
            add('DUPLICATE_WIRE_ID', 'error', wire['id'])
        edge_ids.add(wire['id'])
        if a not in ports or b not in ports:
            add('UNKNOWN_ENDPOINT', 'error', wire['id'] + ': ' + a + ' / ' + b)
            continue
        pair = tuple(sorted((a, b)))
        if a == b or pair in pairs:
            add('DUPLICATE_OR_SELF_WIRE', 'error', wire['id'])
            continue
        pairs.add(pair)
        valid_wires.append(wire)
        degree[a] += 1
        degree[b] += 1
        parent[find(a)] = find(b)
    groups = defaultdict(list)
    for name, port in ports.items():
        groups[find(name)].append((name, port['conductor']))
        if port.get('required') and degree[name] == 0:
            add('REQUIRED_PORT_UNWIRED', 'error', name)
        if degree[name] > port.get('max_connections', 100):
            add('TERMINAL_CAPACITY_EXCEEDED', 'error', name)
        if port['conductor'] == 'TBD':
            add('CONDUCTOR_UNRESOLVED', 'warning', name)
    # Removing explicitly declared 0V/FE-to-PE bonds must leave homogeneous
    # nets. A tree requirement rejects parallel/second bonding paths.
    by_id = {w['id']: w for w in valid_wires}
    bonded = set()
    for bond in model.get('intentional_bonds', []):
        wire = by_id.get(bond['connection_id'])
        if not wire or wire['id'] in bonded:
            add('INVALID_BOND_REFERENCE', 'error', bond['connection_id'])
            continue
        kinds = frozenset(ports[p]['conductor'] for p in [wire['from'], wire['to']])
        if kinds not in {frozenset({'DC0', 'PE'}), frozenset({'FE', 'PE'})}:
            add('INVALID_BOND_CONDUCTORS', 'error', wire['id'])
            continue
        bonded.add(wire['id'])
    isolated = {p: p for p in ports}
    def isolated_find(p):
        while isolated[p] != p:
            isolated[p] = isolated[isolated[p]]
            p = isolated[p]
        return p
    for wire in valid_wires:
        if wire['id'] not in bonded:
            isolated[isolated_find(wire['from'])] = isolated_find(wire['to'])
    for group_id, group in groups.items():
        kinds = {kind for _, kind in group} - {'SIGNAL', 'TBD'}
        if len(kinds) > 1:
            splits = defaultdict(set)
            for name, kind in group:
                splits[isolated_find(name)].update({kind} - {'SIGNAL', 'TBD'})
            count = sum(w['id'] in bonded and find(w['from']) == group_id for w in valid_wires)
            allowed = (kinds <= {'DC0', 'FE', 'PE'} and count == len(splits) - 1 and
                       all(len(s) <= 1 for s in splits.values()))
            if not allowed:
                add('CONDUCTOR_CONFLICT', 'error', ', '.join(name + '=' + kind for name, kind in group))
    for field, should_connect in [('required_paths', True), ('forbidden_pairs', False)]:
        for a, b in model.get(field, []):
            if a not in ports or b not in ports:
                add('UNKNOWN_PATH_ENDPOINT', 'error', a + ' / ' + b)
            elif (find(a) == find(b)) != should_connect:
                add('REQUIRED_PATH_MISSING' if should_connect else 'FORBIDDEN_PATH_PRESENT', 'error', a + ' / ' + b)
    for device in model['devices']:
        if device['kind'] != 'plc':
            continue
        tag = device['tag']
        addresses = {}
        channel_ids = {p['id'] for p in device['ports'] if p.get('plc_address')}
        for port in device['ports']:
            if port.get('plc_address'):
                address = port['plc_address'].lstrip('%')
                if address in addresses:
                    add('DUPLICATE_PLC_ADDRESS', 'error', tag + ': ' + address)
                addresses[address] = port['id']
        covered = []
        group_ids = set()
        for group in device.get('io_groups', []):
            if group['id'] in group_ids:
                add('DUPLICATE_IO_GROUP', 'error', tag + ':' + group['id'])
            group_ids.add(group['id'])
            covered.extend(group['channels'])
            for channel in group['channels']:
                if channel not in channel_ids:
                    add('IO_GROUP_CHANNEL_UNKNOWN', 'error', tag + ':' + channel)
            needed = [group['common_port']]
            if group['type'] in {'PNP', 'NPN'}:
                if not group.get('supply_port'):
                    add('IO_SUPPLY_PORT_MISSING', 'error', tag + ':' + group['id'])
                else:
                    needed.append(group['supply_port'])
            for role in needed:
                endpoint = tag + ':' + role
                if endpoint not in ports or degree[endpoint] == 0:
                    add('PLC_COMMON_OR_SUPPLY_UNWIRED', 'error', endpoint)
            if group['type'] in {'PNP', 'NPN'}:
                expected_common = group.get('common_conductor', 'TBD')
                common = ports.get(tag + ':' + group['common_port'], {})
                supply = ports.get(tag + ':' + group.get('supply_port', ''), {})
                if expected_common == 'TBD':
                    add('PLC_COMMON_POLARITY_UNVERIFIED', 'warning', tag + ':' + group['id'])
                elif common.get('conductor') != expected_common:
                    add('PLC_IO_GROUP_POLARITY_UNVERIFIED', 'error', tag + ':' + group['id'])
                if supply.get('conductor') != 'DC24':
                    add('PLC_IO_SUPPLY_POLARITY_UNVERIFIED', 'error', tag + ':' + group['id'])
            if group['type'] == 'TBD':
                add('PLC_IO_TYPE_UNRESOLVED', 'warning', tag + ':' + group['id'])
        for channel in sorted(channel_ids - set(covered)):
            add('PLC_CHANNEL_WITHOUT_COMMON_GROUP', 'error', tag + ':' + channel)
        if len(covered) != len(set(covered)):
            add('PLC_CHANNEL_IN_MULTIPLE_GROUPS', 'error', tag)
    supply = model.get('supply', {})
    line, phase = supply.get('line_voltage_v'), supply.get('phase_voltage_v')
    for name, value in supply.items():
        if isinstance(value, (int, float)) and not math.isfinite(value):
            add('NONFINITE_SUPPLY_VALUE', 'error', name)
    if line is not None and phase is not None and {'L1', 'L2', 'L3', 'N'} <= set(supply.get('conductors', [])):
        if not math.isclose(line / phase, math.sqrt(3), rel_tol=.03):
            add('LINE_PHASE_VOLTAGE_INCONSISTENT', 'error', 'Three-phase L-N and L-L values must be distinguished')
    if any(d['kind'] == 'motor' for d in model['devices']) and not model.get('forward_reverse'):
        add('MOTOR_CONTROL_LOGIC_NOT_REVIEWED', 'warning', 'No forward/reverse intent was supplied')
    logic = model.get('forward_reverse')
    if logic:
        outputs = [logic['forward_output'], logic['reverse_output']]
        if outputs[0] == outputs[1]:
            add('DIRECTION_OUTPUTS_NOT_DISTINCT', 'error', outputs[0])
        for output in outputs:
            if output not in ports or not ports[output].get('plc_address', '').lstrip('%').startswith('Q'):
                add('DIRECTION_OUTPUT_NOT_PLC_Q', 'error', output)
        for key in ['mutual_exclusion', 'restart_requires_new_start_edge', 'reversal_requires_standstill']:
            if logic[key] is not True:
                add('CONTROL_INTENT_INCOMPLETE', 'error', key)
    return result(model, findings, len(groups))


def result(model, findings, groups=None):
    encoded = json.dumps(model, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=True).encode()
    return {'ok': not any(f['severity'] == 'error' for f in findings),
            'scope': 'offline_declared_wire_graph_and_constraints_only',
            'model_sha256': hashlib.sha256(encoded).hexdigest(), 'wire_groups': groups,
            'findings': findings, 'native_apply_ready': False, 'construction_ready': False,
            'limits': ['No native project was read or changed.',
                       'Contacts, device conversion and PLC execution are not simulated.',
                       'Control flags are declared requirements, not proof of implemented safety.']}

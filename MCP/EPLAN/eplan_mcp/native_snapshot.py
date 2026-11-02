"""Offline native endpoint audit. No EPLAN calls, writes or case-specific counts.

The supplied capture is data, never proof that a native read happened now.
Wire edges are compared exactly; only declared terminal internals are joined.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
from itertools import islice
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator
from . import intent

SCHEMA = Path(__file__).with_name('schemas') / 'native-snapshot-plan.schema.json'
MAX_BYTES = 16 * 1024 * 1024
ADDRESS = re.compile(r'%?([IQ])(\d+)\.([0-7])\Z')
NATIVE_KEY = re.compile(r'[0-9]+:[0-9]+:[0-9]+\Z')


def schema():
    return json.loads(SCHEMA.read_text(encoding='utf-8'))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _ep(value):
    return value['function_id'], value['pin_index']


def _edge(a, b):
    return tuple(sorted((a, b)))


def _address(value):
    match = ADDRESS.fullmatch(value) if isinstance(value, str) else None
    return f'{match[1]}{int(match[2])}.{match[3]}' if match else None


def _dsu():
    parent = {}

    def find(node):
        parent.setdefault(node, node)
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != node:
            following = parent[node]
            parent[node] = root
            node = following
        return root

    def join(a, b):
        parent[find(a)] = find(b)

    return find, join


def validate_snapshot(plan: dict, capture: dict) -> dict:
    findings, stats = [], {}

    def add(code, detail, severity='error'):
        if len(findings) < 200:
            findings.append({'code': code, 'severity': severity, 'detail': detail})

    def result():
        return {'ok': not any(x['severity'] == 'error' for x in findings),
                'scope': 'provided_full_snapshot_offline', 'native_read_this_call': False,
                'construction_ready': False, 'commissioning_ready': False,
                'plan_sha256': plan_hash, 'capture_sha256': capture_hash,
                'statistics': stats, 'findings': findings,
                'limits': ['Exact edges do not establish correctness of the design itself.',
                           'Native pin capacity is not manufacturer clamp/bridge capacity.',
                           'No contact/coil/load internals are treated as a conducting wire.',
                           'No PLC execution, stopping-time, pneumatic or PL/SIL verification.']}

    plan_hash = capture_hash = None
    try:
        for value in [plan, capture]:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            if len(encoded) > MAX_BYTES:
                raise ValueError('Each input must be at most 16 MiB')
        plan_hash, capture_hash = _digest(plan), _digest(capture)
    except (ValueError, TypeError, RecursionError) as exc:
        add('INVALID_OR_OVERSIZE_INPUT', str(exc))
        return result()
    errors = list(islice(Draft202012Validator(schema()).iter_errors(plan), 101))
    for error in errors[:100]:
        add('PLAN_SCHEMA_INVALID', '/'.join(map(str, error.absolute_path)) + ': ' + error.message)
    if errors:
        return result()
    if not isinstance(capture, dict) or capture.get('success') is not True:
        add('CAPTURE_NOT_SUCCESSFUL', 'A successful full capture envelope is required')
        return result()
    if capture.get('project') != plan['project'] or capture.get('build') != plan['native_build']:
        add('PROJECT_OR_BUILD_MISMATCH', 'Capture identity differs from the reviewed plan')
    database = capture.get('database_id')
    if type(database) is not int or database < 0:
        add('INVALID_DATABASE_IDENTITY', 'Capture requires its native session database ID')
    snap = capture.get('snapshot')
    if not isinstance(snap, dict) or not isinstance(snap.get('functions'), list) or not isinstance(snap.get('connections'), list):
        add('FULL_SNAPSHOT_REQUIRED', 'A page fragment, geometric count or legacy summary is insufficient')
        return result()
    if len(snap['functions']) > 5000 or len(snap['connections']) > 15000:
        add('CAPTURE_LIMIT_EXCEEDED', 'At most 5000 functions and 15000 connections')
        return result()
    if capture.get('truncated') or snap.get('truncated') or capture.get('partial'):
        add('PARTIAL_CAPTURE_REJECTED', 'Explicit partial/truncated capture cannot pass a full inventory audit')
    pages = capture.get('pages', [])
    if not isinstance(pages, list) or any(not isinstance(p, dict) or not isinstance(p.get('name'), str) for p in pages):
        add('INVALID_PAGE_INVENTORY', 'Full page identity records are required')
    elif len({p['name'] for p in pages}) != len(pages) or {p['name'] for p in pages} != set(plan['pages']):
        add('PAGE_INVENTORY_MISMATCH', 'Missing, additional or duplicated pages')
    fs, actual_pins, native_ids = {}, {}, set()
    for f in snap['functions']:
        if not isinstance(f, dict) or not isinstance(f.get('id'), str) or not isinstance(f.get('native_key'), str) or not isinstance(f.get('pins'), list):
            add('INVALID_FUNCTION_RECORD', 'Function requires logical ID, native identity and pins')
            continue
        fid, key = f['id'], f['native_key']
        if not NATIVE_KEY.fullmatch(key):
            add('INVALID_NATIVE_IDENTITY', fid)
        elif key.split(':', 1)[0] != str(database):
            add('MIXED_NATIVE_DATABASE', fid)
        if fid in fs or key in native_ids:
            add('DUPLICATE_FUNCTION_IDENTITY', fid)
        fs[fid] = f
        native_ids.add(key)
        if f.get('placed') is not True:
            add('FUNCTION_NOT_PLACED', fid)
        if len(f['pins']) > 1000:
            add('PIN_LIMIT_EXCEEDED', fid)
            continue
        for pin in f['pins']:
            if not isinstance(pin, dict) or type(pin.get('index')) is not int or pin['index'] < 0:
                add('INVALID_PIN', fid)
                continue
            ep = fid, pin['index']
            if ep in actual_pins:
                add('DUPLICATE_PIN', str(ep))
            actual_pins[ep] = pin
    specs = {}
    expected_pins = {}
    for f in plan['functions']:
        fid = f['id']
        if fid in specs:
            add('DUPLICATE_PLAN_FUNCTION', fid)
        specs[fid] = f
        if f['page'] not in plan['pages']:
            add('FUNCTION_PAGE_NOT_PLANNED', fid)
        for pin in f['pins']:
            ep = fid, pin['index']
            if ep in expected_pins:
                add('DUPLICATE_PLAN_PIN', str(ep))
            expected_pins[ep] = pin
    for fid in sorted(specs.keys() - fs.keys()):
        add('MISSING_FUNCTION', fid)
    for fid in sorted(fs.keys() - specs.keys()):
        add('UNEXPECTED_FUNCTION', fid)
    plc_addresses = set()
    for fid in sorted(specs.keys() & fs.keys()):
        expected, actual = specs[fid], fs[fid]
        if expected['page'] != actual.get('page') or expected['symbol'] != actual.get('symbol'):
            add('FUNCTION_PLACEMENT_MISMATCH', fid)
        if expected.get('native_key') and expected['native_key'] != actual['native_key']:
            add('FUNCTION_NATIVE_ID_CHANGED', fid)
        if expected['kind'] == 'plc_channel':
            address = _address(actual.get('address'))
            owner_address = expected['plc_device'], address
            if not address or owner_address in plc_addresses:
                add('INVALID_OR_DUPLICATE_PLC_ADDRESS', fid)
            plc_addresses.add(owner_address)
            if address != _address(expected['address']) or actual.get('variable') != expected['variable']:
                add('PLC_ASSIGNMENT_CHANGED', fid)
        elif actual.get('address'):
            add('UNEXPECTED_PLC_ASSIGNMENT', fid)
    for ep, expected in expected_pins.items():
        actual = actual_pins.get(ep)
        if actual is None:
            add('MISSING_NATIVE_PIN', str(ep))
        elif actual.get('displayed_designation') != expected['displayed_designation']:
            add('PHYSICAL_PIN_LABEL_CHANGED', str(ep))
        if actual is not None and specs[ep[0]]['kind'] == 'plc_channel':
            address = _address(fs[ep[0]].get('address'))
            signal = 'DigitalOutput' if address and address.startswith('Q') else 'DigitalInput'
            if actual.get('signal') != signal:
                add('PLC_SIGNAL_TYPE_CHANGED', str(ep))
    for ep in actual_pins.keys() - expected_pins.keys():
        add('UNEXPECTED_NATIVE_PIN', str(ep))
    wanted, names, endpoint_groups = set(), set(), {}
    for group in plan['route_groups']:
        if group['name'] in names:
            add('DUPLICATE_ROUTE_NAME', group['name'])
        names.add(group['name'])
        ends = list(map(_ep, group['ends']))
        for ep in ends:
            if ep not in expected_pins:
                add('UNKNOWN_PLAN_ENDPOINT', str(ep))
            if ep in endpoint_groups:
                add('ENDPOINT_IN_MULTIPLE_GROUPS', str(ep))
            endpoint_groups[ep] = group['name']
        for ep in ends[1:]:
            pair = _edge(ends[0], ep)
            if ends[0] == ep or pair in wanted:
                add('DUPLICATE_OR_SELF_PLAN_EDGE', str(pair))
            wanted.add(pair)
    actual_edges, connection_ids, degree = set(), set(), Counter()
    for c in snap['connections']:
        if not isinstance(c, dict) or not isinstance(c.get('native_key'), str) or any(type(c.get(k)) is not int or c[k] < 0 for k in ['from_pin', 'to_pin']):
            add('INVALID_NATIVE_CONNECTION', 'Native connection requires identity and nonnegative typed pin indices')
            continue
        if not NATIVE_KEY.fullmatch(c['native_key']):
            add('INVALID_NATIVE_IDENTITY', c['native_key'])
        elif c['native_key'].split(':', 1)[0] != str(database):
            add('MIXED_NATIVE_DATABASE', c['native_key'])
        a, b = (c.get('from_id'), c['from_pin']), (c.get('to_id'), c['to_pin'])
        if not isinstance(a[0], str) or not isinstance(b[0], str) or a not in actual_pins or b not in actual_pins:
            add('UNBOUND_NATIVE_CONNECTION', c['native_key'])
            continue
        if c.get('from_native') != fs[a[0]]['native_key'] or c.get('to_native') != fs[b[0]]['native_key']:
            add('CONNECTION_OBJECT_ID_MISMATCH', c['native_key'])
        if c.get('placed') is not True:
            add('UNPLACED_CONNECTION', c['native_key'])
        pair = _edge(a, b)
        if c['native_key'] in connection_ids or pair in actual_edges or a == b:
            add('DUPLICATE_OR_SELF_NATIVE_CONNECTION', c['native_key'])
        connection_ids.add(c['native_key'])
        actual_edges.add(pair)
        degree.update((a, b))
    for ep, count in degree.items():
        cap = actual_pins[ep].get('max_connections')
        if type(cap) is not int or cap < 1:
            add('INVALID_NATIVE_CAPACITY', str(ep))
            continue
        cap = min(cap, expected_pins.get(ep, {}).get('external_wire_limit', cap))
        if specs.get(ep[0], {}).get('kind') == 'plc_channel':
            cap = min(1, cap)
        if count > cap:
            add('NATIVE_OR_DECLARED_CAPACITY_EXCEEDED', str(ep))
    for pair in sorted(wanted - actual_edges):
        add('MISSING_NATIVE_EDGE', str(pair))
    for pair in sorted(actual_edges - wanted):
        add('UNEXPECTED_NATIVE_EDGE', str(pair))
    for key, size in [('function_count', len(snap['functions'])), ('connection_count', len(snap['connections']))]:
        if type(snap.get(key)) is not int or snap[key] != size:
            add('CAPTURE_COUNT_MISMATCH', key)
    find, join = _dsu()
    for a, b in actual_edges:
        join(a, b)
    for pair in plan.get('terminal_continuities', []):
        a, b = map(_ep, pair)
        if (a not in expected_pins or b not in expected_pins or a[0] != b[0] or
                specs.get(a[0], {}).get('kind') != 'terminal' or a == b):
            add('INVALID_TERMINAL_CONTINUITY', str(pair))
        else:
            join(a, b)
    stats.update(functions=len(fs), connections=len(actual_edges), expected_connections=len(wanted),
                 missing_connections=len(wanted - actual_edges), extra_connections=len(actual_edges - wanted),
                 plc_channels=len(plc_addresses), semantic_intent_checked=False)
    if 'semantic_model' in plan:
        checked = intent.validate_intent(plan['semantic_model'])
        for issue in checked['findings']:
            add('INTENT_' + issue['code'], issue['detail'], issue['severity'])
        if checked['ok']:
            mf, mu = _dsu()
            model = plan['semantic_model']
            ports = {d['tag'] + ':' + p['id']: p for d in model['devices'] for p in d['ports']}
            for wire in model['connections']:
                mu(wire['from'], wire['to'])
            mapping = plan['port_map']
            for port in mapping:
                if port not in ports or _ep(mapping[port]) not in expected_pins:
                    add('INVALID_SEMANTIC_MAPPING', port)
            missing = [p for p in ports if ports[p].get('required') and p not in mapping]
            if missing:
                add('REQUIRED_PORT_NOT_MAPPED', ', '.join(missing[:20]))
            if all(p in ports and _ep(mapping[p]) in expected_pins for p in mapping):
                mg, ng = defaultdict(set), defaultdict(set)
                for port, ep in mapping.items():
                    mg[mf(port)].add(port)
                    ng[find(_ep(ep))].add(port)
                if {frozenset(g) for g in mg.values()} != {frozenset(g) for g in ng.values()}:
                    add('SEMANTIC_NET_PARTITION_MISMATCH', 'Native and intent wire-network membership differs')
                stats.update(semantic_intent_checked=True, mapped_ports=len(mapping),
                             equivalent_pair_relations=len(mapping) * (len(mapping) - 1) // 2)
    else:
        add('ELECTRICAL_INTENT_NOT_CHECKED', 'No semantic_model/port_map supplied; exact edges only', 'warning')
    return result()

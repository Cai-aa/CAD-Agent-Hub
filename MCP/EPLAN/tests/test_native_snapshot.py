import copy
import json
from pathlib import Path

import pytest
from eplan_mcp.native_snapshot import validate_snapshot


@pytest.fixture
def bundle():
    root=Path(__file__).resolve().parents[1]/'examples'
    return tuple(json.loads((root/n).read_text(encoding='utf-8')) for n in
                 ['native-snapshot-plan.json','native-snapshot-capture.json'])


def codes(result):
    return {x['code'] for x in result['findings']}


def test_full_graph_and_semantics_pass_without_claiming_live_read(bundle):
    p,c=bundle;r=validate_snapshot(p,c)
    assert r['ok'] and r['statistics']['semantic_intent_checked']
    assert r['statistics']['equivalent_pair_relations']==36
    assert not r['native_read_this_call'] and not r['construction_ready']
    assert not r['commissioning_ready']


@pytest.mark.parametrize('change,expected',[
    ('missing','MISSING_NATIVE_EDGE'),('extra','UNEXPECTED_NATIVE_EDGE'),
    ('duplicate','DUPLICATE_OR_SELF_NATIVE_CONNECTION'),('unplaced','UNPLACED_CONNECTION'),
    ('physical_label','PHYSICAL_PIN_LABEL_CHANGED'),('capacity','NATIVE_OR_DECLARED_CAPACITY_EXCEEDED'),
    ('plc_signal','PLC_SIGNAL_TYPE_CHANGED'),('object_binding','CONNECTION_OBJECT_ID_MISMATCH'),
    ('duplicate_function','DUPLICATE_FUNCTION_IDENTITY'),('unknown_pin','UNBOUND_NATIVE_CONNECTION'),
    ('page','PAGE_INVENTORY_MISMATCH'),('counts','CAPTURE_COUNT_MISMATCH'),
    ('mixed_db','MIXED_NATIVE_DATABASE'),('extra_pin','UNEXPECTED_NATIVE_PIN'),
    ('partial','PARTIAL_CAPTURE_REJECTED'),('build','PROJECT_OR_BUILD_MISMATCH'),
])
def test_observed_failures_cannot_be_hidden_by_equal_counts(bundle,change,expected):
    p,c=bundle;s=c['snapshot']
    if change=='missing':s['connections'].pop()
    elif change=='extra':
        w=copy.deepcopy(s['connections'][0]);w.update(native_key='1:24:99',to_id='PLC1.M',to_pin=0,to_native='1:17:3');s['connections'].append(w)
    elif change=='duplicate':s['connections'].append(copy.deepcopy(s['connections'][0]))
    elif change=='unplaced':s['connections'][0]['placed']=False
    elif change=='physical_label':s['functions'][-1]['pins'][0]['displayed_designation']='13'
    elif change=='capacity':s['functions'][4]['pins'][0]['max_connections']=1
    elif change=='plc_signal':s['functions'][0]['pins'][0]['signal']='DigitalInput'
    elif change=='object_binding':s['connections'][0]['from_native']='1:17:999'
    elif change=='duplicate_function':s['functions'].append(copy.deepcopy(s['functions'][0]))
    elif change=='unknown_pin':s['connections'][0]['to_pin']=88
    elif change=='page':c['pages'].append({'name':'/2'})
    elif change=='counts':s['connection_count']+=1
    elif change=='mixed_db':s['connections'][0]['native_key']='99:24:1'
    elif change=='extra_pin':s['functions'][1]['pins'].append({'index':8,'max_connections':1})
    elif change=='partial':c['partial']=True
    elif change=='build':c['build']='2026.1.1.1'
    r=validate_snapshot(p,c);assert not r['ok'] and expected in codes(r)


def test_terminal_continuity_is_explicit_and_never_applied_to_a_coil(bundle):
    p,c=bundle;p['terminal_continuities']=[]
    assert 'SEMANTIC_NET_PARTITION_MISMATCH' in codes(validate_snapshot(p,c))
    p['terminal_continuities']=[[{'function_id':'KA1.COIL','pin_index':0},{'function_id':'KA1.COIL','pin_index':1}]]
    assert 'INVALID_TERMINAL_CONTINUITY' in codes(validate_snapshot(p,c))


def test_valid_native_edges_do_not_mask_wrong_electrical_intent(bundle):
    p,c=bundle;p['semantic_model']['connections'][0]['to']='PLC1:DO_M'
    r=validate_snapshot(p,c)
    assert not r['ok'] and 'INTENT_CONDUCTOR_CONFLICT' in codes(r)


def test_semantic_net_membership_requires_all_required_ports_mapped(bundle):
    p,c=bundle;p['port_map'].pop('PLC1:DO_M')
    assert 'REQUIRED_PORT_NOT_MAPPED' in codes(validate_snapshot(p,c))


def test_missing_semantics_is_disclosed_not_invented(bundle):
    p,c=bundle;p.pop('port_map');p.pop('semantic_model')
    r=validate_snapshot(p,c)
    assert r['ok'] and not r['statistics']['semantic_intent_checked']
    assert 'ELECTRICAL_INTENT_NOT_CHECKED' in codes(r)


def test_plc_aliases_are_normalized_per_physical_plc(bundle):
    p,c=bundle
    f=copy.deepcopy(p['functions'][0]);f.update(id='PLC1.Q_ALIAS',address='%Q00.0');p['functions'].append(f)
    f=copy.deepcopy(c['snapshot']['functions'][0]);f.update(id='PLC1.Q_ALIAS',native_key='1:17:98',address='%Q00.0');c['snapshot']['functions'].append(f)
    assert 'INVALID_OR_DUPLICATE_PLC_ADDRESS' in codes(validate_snapshot(p,c))
    p['functions'][-1]['plc_device']='PLC2'
    r=validate_snapshot(p,c)
    assert 'INVALID_OR_DUPLICATE_PLC_ADDRESS' not in codes(r)


@pytest.mark.parametrize('value',[float('nan'),float('inf')])
def test_nonfinite_capture_is_rejected(bundle,value):
    p,c=bundle;c['snapshot']['function_count']=value
    assert 'INVALID_OR_OVERSIZE_INPUT' in codes(validate_snapshot(p,c))


def test_schema_rejects_unknown_or_unsafe_route_contract(bundle):
    p,c=bundle;p['arbitrary_script']='not allowed'
    assert 'PLAN_SCHEMA_INVALID' in codes(validate_snapshot(p,c))


@pytest.mark.parametrize('value',[[],123,True])
def test_malformed_plc_address_is_a_finding_not_an_exception(bundle,value):
    p,c=bundle;c['snapshot']['functions'][0]['address']=value
    r=validate_snapshot(p,c)
    assert not r['ok'] and 'INVALID_OR_DUPLICATE_PLC_ADDRESS' in codes(r)


def test_valid_edges_do_not_cover_missing_plc_common_in_semantic_model(bundle):
    p,c=bundle
    p['semantic_model']['connections']=[w for w in p['semantic_model']['connections'] if w['to']!='PLC1:DO_M']
    r=validate_snapshot(p,c)
    assert not r['ok'] and 'INTENT_PLC_COMMON_OR_SUPPLY_UNWIRED' in codes(r)

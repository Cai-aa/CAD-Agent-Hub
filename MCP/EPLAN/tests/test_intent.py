from copy import deepcopy
import math

import pytest

from eplan_mcp.intent import validate_intent


def codes(model):
    return {f['code'] for f in validate_intent(model)['findings']}


def test_partial_control_model_is_not_native_drawing_or_construction(model):
    result = validate_intent(model)
    assert result['ok']
    assert not result['native_apply_ready'] and not result['construction_ready']
    assert 'PHYSICAL_PIN_UNVERIFIED' in codes(model)


@pytest.mark.parametrize('a,b', [('L1', 'L2'), ('L1', 'N'), ('N', 'PE'), ('DC24', 'DC0'), ('U', 'V')])
def test_conductor_short_detected_through_unlabelled_signal_bridge(model, a, b):
    model['devices'] = [{'tag': 'X', 'kind': 'terminal', 'ports': [
        {'id': '1', 'conductor': a}, {'id': '2', 'conductor': 'SIGNAL'}, {'id': '3', 'conductor': b}]}]
    model['connections'] = [{'id': 'a', 'from': 'X:1', 'to': 'X:2'}, {'id': 'b', 'from': 'X:2', 'to': 'X:3'}]
    model.pop('forward_reverse')
    assert 'CONDUCTOR_CONFLICT' in codes(model)


def test_unknown_endpoint_and_duplicate_wire_rejected(model):
    model['connections'].append({'id': 'missing', 'from': 'PLC2:Q0.0', 'to': 'KA1:A1'})
    assert 'UNKNOWN_ENDPOINT' in codes(model)
    model['connections'].pop()
    model['connections'].append(deepcopy(model['connections'][0]))
    assert {'DUPLICATE_WIRE_ID', 'DUPLICATE_OR_SELF_WIRE'} <= codes(model)


def test_missing_wire_and_terminal_capacity(model):
    model['devices'][0]['ports'][0]['max_connections'] = 1
    model['connections'].append({'id': 'extra', 'from': 'PS1:24V', 'to': 'KA1:A1'})
    assert 'TERMINAL_CAPACITY_EXCEEDED' in codes(model)
    model['connections'] = [w for w in model['connections'] if w['to'] != 'PLC1:M']
    assert 'PLC_COMMON_OR_SUPPLY_UNWIRED' in codes(model)


def test_plc_address_aliases_duplicate_within_cpu_not_between_cpus(model):
    plc = model['devices'][1]
    plc['ports'][3]['plc_address'] = '%Q0.0'
    assert 'DUPLICATE_PLC_ADDRESS' in codes(model)
    plc['ports'][3]['plc_address'] = 'Q0.1'
    another = deepcopy(plc)
    another['tag'] = 'PLC2'
    for p in another['ports']:
        p['required'] = False
    model['devices'].append(another)
    assert 'DUPLICATE_PLC_ADDRESS' not in codes(model)


def test_common_mapping_is_explicit_not_inferred_from_pnp_or_npn(model):
    group = model['devices'][1]['io_groups'][0]
    group['common_port'] = 'L+'
    assert 'PLC_IO_GROUP_POLARITY_UNVERIFIED' in codes(model)
    group['type'] = 'NPN'
    group.pop('common_conductor')
    assert 'PLC_COMMON_POLARITY_UNVERIFIED' in codes(model)


def test_required_and_forbidden_paths_use_network_not_line_counts(model):
    model['required_paths'] = [['PS1:0V', 'KA1:A2']]
    model['forbidden_pairs'] = [['PLC1:Q0.0', 'KA1:A1']]
    assert 'FORBIDDEN_PATH_PRESENT' in codes(model)
    model['required_paths'] = [['PLC1:Q0.1', 'KA1:A1']]
    assert 'REQUIRED_PATH_MISSING' in codes(model)


@pytest.mark.parametrize('field', ['mutual_exclusion', 'restart_requires_new_start_edge', 'reversal_requires_standstill'])
def test_direction_contract_requires_each_constraint(model, field):
    model['forward_reverse'][field] = False
    assert 'CONTROL_INTENT_INCOMPLETE' in codes(model)


def test_220v_is_not_both_line_and_phase_voltage(model):
    model['supply'] = {'conductors': ['L1', 'L2', 'L3', 'N', 'PE'], 'line_voltage_v': 220, 'phase_voltage_v': 220}
    assert 'LINE_PHASE_VOLTAGE_INCONSISTENT' in codes(model)
    model['supply']['line_voltage_v'] = 380
    assert 'LINE_PHASE_VOLTAGE_INCONSISTENT' not in codes(model)
    model['supply']['line_voltage_v'] = math.nan
    assert 'NONFINITE_SUPPLY_VALUE' in codes(model)


def test_declared_single_0v_pe_bond_does_not_hide_parallel_short(model):
    model['devices'].append({'tag': 'PE', 'kind': 'terminal', 'ports': [
        {'id': '1', 'conductor': 'PE'}, {'id': '2', 'conductor': 'PE'}]})
    model['connections'].extend([{'id': 'bond', 'from': 'PS1:0V', 'to': 'PE:1'},
                                 {'id': 'pe', 'from': 'PE:1', 'to': 'PE:2'}])
    model['intentional_bonds'] = [{'connection_id': 'bond', 'reason': 'Declared 0V reference; engineering approval separate'}]
    assert 'CONDUCTOR_CONFLICT' not in codes(model)
    model['connections'].append({'id': 'bypass', 'from': 'KA1:A2', 'to': 'PE:2'})
    assert 'CONDUCTOR_CONFLICT' in codes(model)
    model['intentional_bonds'].append({'connection_id': 'bypass', 'reason': 'Second bond still violates single-point topology'})
    assert 'CONDUCTOR_CONFLICT' in codes(model)


def test_n_pe_merge_cannot_be_approved_by_bond_annotation(model):
    model['devices'][0]['ports'][1]['conductor'] = 'N'
    model['devices'].append({'tag': 'PE', 'kind': 'terminal', 'ports': [{'id': '1', 'conductor': 'PE'}]})
    model['connections'].append({'id': 'bond', 'from': 'PS1:0V', 'to': 'PE:1'})
    model['intentional_bonds'] = [{'connection_id': 'bond', 'reason': 'A label cannot authorize N/PE merging'}]
    assert {'INVALID_BOND_CONDUCTORS', 'CONDUCTOR_CONFLICT'} <= codes(model)


@pytest.mark.parametrize('value', [[], None, {}, {'schema_version': 'unknown'}, {'schema_version': 'eplan-design-intent-1', 'devices': [], 'connections': []}])
def test_malformed_models_are_results_not_crashes(value):
    result = validate_intent(value)
    assert not result['ok'] and 'SCHEMA_INVALID' in {f['code'] for f in result['findings']}

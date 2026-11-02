import json
import time

import pytest

from eplan_mcp import bridge
from eplan_mcp.config import Settings, load_settings

INSTANCE = {'instance_id': 'a' * 32, 'pipe': 'eplan-mcp-123-' + 'a' * 32, 'trial_writes_enabled': True}


def test_review_blocks_mutations_before_discovery(monkeypatch):
    monkeypatch.setattr(bridge, 'discover', lambda: pytest.fail('No native discovery should be attempted'))
    assert bridge.request(INSTANCE['instance_id'], 'trial_place_motor')['error']['code'] == 'READ_ONLY_PROFILE'


@pytest.mark.parametrize('raw', [b'[]', b'{"ok":"yes"}', b'{"ok":true,"ok":false}'])
def test_invalid_response_envelopes_rejected(monkeypatch, raw):
    monkeypatch.setattr(bridge, 'discover', lambda: [INSTANCE])
    monkeypatch.setattr(bridge, 'exchange', lambda *args: raw)
    assert bridge.request(INSTANCE['instance_id'], 'hello')['ok'] is False


def test_wrong_native_build_prevents_write(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, 'load_settings', lambda: Settings(workspace=tmp_path, profile='trial'))
    monkeypatch.setattr(bridge, 'discover', lambda: [INSTANCE])
    calls = []
    def exchange(pipe, body, *args):
        calls.append(json.loads(body)['operation'])
        return b'{"ok":true,"data":{"build":"2027.0.0.0"}}'
    monkeypatch.setattr(bridge, 'exchange', exchange)
    result = bridge.request(INSTANCE['instance_id'], 'trial_place_motor')
    assert result['error']['code'] == 'NATIVE_BUILD_NOT_VERIFIED'
    assert calls == ['hello']


def test_mutation_timeout_is_unknown_and_never_retried(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, 'load_settings', lambda: Settings(workspace=tmp_path, profile='trial'))
    monkeypatch.setattr(bridge, 'discover', lambda: [INSTANCE])
    calls = []
    def exchange(pipe, body, *args):
        operation = json.loads(body)['operation']
        calls.append(operation)
        if operation == 'hello':
            return b'{"ok":true,"data":{"build":"2.9.4.14642"}}'
        raise TimeoutError('delayed native response')
    monkeypatch.setattr(bridge, 'exchange', exchange)
    error = bridge.request(INSTANCE['instance_id'], 'trial_place_motor')['error']
    assert error['native_outcome_unknown'] and not error['automatic_retry_allowed']
    assert calls == ['hello', 'trial_place_motor']


@pytest.mark.parametrize('pipe', ['eplan-mcp-../../x', 'eplan-mcp-1-abc\\x', '\\\\remote\\pipe\\x'])
def test_pipe_names_are_not_freeform(pipe):
    assert not bridge.PIPE_PATTERN.fullmatch(pipe)


def test_settings_reject_unknown_profile_and_remain_fixed_until_restart(monkeypatch, tmp_path):
    monkeypatch.setenv('EPLAN_MCP_WORKSPACE', str(tmp_path))
    settings = load_settings()
    monkeypatch.setenv('EPLAN_MCP_PROFILE', 'trial')
    assert load_settings() is settings and settings.profile == 'review'
    load_settings.cache_clear()
    monkeypatch.setenv('EPLAN_MCP_PROFILE', 'production')
    with pytest.raises(ValueError):
        load_settings()

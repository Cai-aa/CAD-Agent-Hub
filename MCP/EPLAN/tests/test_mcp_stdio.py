import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.parametrize('profile', ['review', 'trial'])
def test_real_sdk_stdio_and_readonly_tool_filter(model, tmp_path, profile):
    async def check():
        root = Path(__file__).resolve().parent.parent
        env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                   EPLAN_MCP_WORKSPACE=str(tmp_path), EPLAN_MCP_PROFILE=profile)
        params = StdioServerParameters(command=sys.executable, args=[str(root / 'server.py')], cwd=str(tmp_path), env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                names = [t.name for t in tools]
                assert len(names) == len(set(names))
                assert {'eplan_capabilities', 'eplan_help_search', 'eplan_page_inventory', 'eplan_design_intent_validate', 'eplan_native_snapshot_validate'} <= set(names)
                assert ('eplan_trial_place_motor' in names) == (profile == 'trial')
                def payload(response):
                    assert not response.isError, response
                    return response.structuredContent or json.loads(next(c.text for c in response.content if c.type == 'text'))
                result = await session.call_tool('eplan_design_intent_validate', {'model': model})
                assert payload(result)['ok']
                assert not payload(result)['construction_ready']
                status = await session.call_tool('eplan_capabilities', {})
                assert (payload(status)['native_writes'] == 'disabled') == (profile == 'review')
                resources = (await session.list_resources()).resources
                assert 'eplan://schemas/design-intent-1' in {str(r.uri) for r in resources}
                assert 'eplan://schemas/native-snapshot-plan-1' in {str(r.uri) for r in resources}
                examples=root/'examples'
                snapshot_result=payload(await session.call_tool('eplan_native_snapshot_validate', {
                    'plan':json.loads((examples/'native-snapshot-plan.json').read_text(encoding='utf-8')),
                    'capture':json.loads((examples/'native-snapshot-capture.json').read_text(encoding='utf-8'))}))
                assert snapshot_result['ok'] and not snapshot_result['native_read_this_call']
                assert snapshot_result['statistics']['semantic_intent_checked']
                runtime = await session.call_tool('eplan_runtime_status', {})
                assert not payload(runtime)['code_stale']
                assert payload(runtime)['snapshot']['available'] is False
    asyncio.run(check())


def test_inventory_counts_native_edges_not_only_geometry(monkeypatch):
    from mcp.server.fastmcp import FastMCP
    from eplan_mcp import enhancements
    native = {'database_id': 1, 'type_id': 2, 'object_id': 3, 'placed': True}
    data = {'functions': [{'name': 'F1', 'native_edges': [native]}, {'name': 'F2', 'native_edges': [native]}]}
    monkeypatch.setattr(enhancements, 'request', lambda *a, **kw: {'ok': True, 'data': data})
    server = FastMCP('test')
    enhancements.configure_server(server)
    fn = server._tool_manager.get_tool('eplan_page_inventory').fn
    out = fn('id', 'explicit-project', '/1', limit=1)
    assert out['observed_native_connection_records'] == 1 and out['placed_connection_records'] == 1
    assert out['total_functions'] == 2 and out['returned'] == 1 and out['next_offset'] == 1
    assert out['truncated'] and not out['full_project_connectivity_verified']
    data['functions'] = [{'name': 'F1', 'graphical_connections': 5}]
    assert fn('id', 'explicit-project', '/1')['error']['code'] == 'NATIVE_INVENTORY_SCHEMA_MISMATCH'

import json
from pathlib import Path

import pytest

from eplan_mcp.config import load_settings


@pytest.fixture(autouse=True)
def clean_configuration(monkeypatch):
    for name in ['EPLAN_MCP_CONFIG', 'EPLAN_MCP_WORKSPACE', 'EPLAN_EXE', 'EPLAN_MCP_PROFILE']:
        monkeypatch.delenv(name, raising=False)
    load_settings.cache_clear()
    yield
    load_settings.cache_clear()


@pytest.fixture
def model():
    path = Path(__file__).resolve().parent.parent / 'examples/control-intent.json'
    return json.loads(path.read_text(encoding='utf-8'))

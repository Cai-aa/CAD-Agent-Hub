from pathlib import Path

import pytest

from eplan_mcp.config import Settings
from eplan_mcp.help_search import index, search


@pytest.fixture
def settings(tmp_path):
    docs = tmp_path / 'docs'
    docs.mkdir()
    (docs / 'sdk.xml').write_text('<doc><members><member name="M:Eplan.Generate.Connections"><summary>Update native connections on pages</summary></member><member name="T:LockingStep"><summary>Lock API objects</summary></member></members></doc>', encoding='utf-8')
    (docs / 'help.html').write_text('<html><style>hiddenword</style><script>secretcommand</script><body>PLC common terminals</body></html>', encoding='utf-8')
    return Settings(workspace=tmp_path / 'work', help_roots=(docs,))


def test_sdk_api_member_and_html_are_separately_searchable(settings):
    result = index(settings)
    assert result['ok'] and result['records'] == 3
    found = search(settings, 'Generate.Connections')
    assert len(found['results']) == 1 and found['results'][0]['source_unchanged']
    assert search(settings, 'PLC')['results']
    assert not search(settings, 'secretcommand')['results']
    assert not search(settings, 'hiddenword')['results']


def test_changed_source_is_marked_stale_and_reindex_removes_old_text(settings):
    index(settings)
    path = settings.help_roots[0] / 'help.html'
    path.write_text('Different topic', encoding='utf-8')
    assert search(settings, 'PLC')['results'][0]['source_unchanged'] is False
    index(settings)
    assert not search(settings, 'PLC')['results']


def test_failed_rebuild_preserves_previous_index(settings):
    index(settings)
    target = settings.workspace / 'artifacts/help-search.sqlite3'
    original = target.read_bytes()
    for p in settings.help_roots[0].iterdir():
        p.unlink()
    with pytest.raises(ValueError, match='previous index preserved'):
        index(settings)
    assert target.read_bytes() == original


def test_missing_configuration_and_query_are_explicit(settings):
    assert index(Settings(workspace=settings.workspace))['error'] == 'HELP_ROOTS_NOT_CONFIGURED'
    assert search(settings, 'LockingStep')['error'] == 'HELP_INDEX_NOT_BUILT'
    with pytest.raises(ValueError):
        search(settings, '() "')


def test_index_cannot_be_reused_for_different_roots(settings, tmp_path):
    index(settings)
    other = tmp_path / 'other'
    other.mkdir()
    result = search(Settings(workspace=settings.workspace, help_roots=(other,)), 'PLC')
    assert result['error'] == 'HELP_INDEX_CONFIGURATION_CHANGED'

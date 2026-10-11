from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import pytest

from powerapps_sim.fixtures import locale_tables_project
from powerapps_sim.web import Workspace
from powerapps_sim.authoring import revision, data_revision
from powerapps_sim.runtime import serial


@pytest.mark.parametrize('language', ['en-US', 'fr-CA', 'ja-JP', 'ar-EG'])
@pytest.mark.parametrize('mode', ['float', 'decimal'])
@pytest.mark.parametrize('enum_mode', ['legacy', 'strong'])
def test_component_selectors_typed_callbacks_reset_save_and_owner(tmp_path, language, mode, enum_mode):
    p = locale_tables_project(tmp_path/'calendar')
    w = Workspace(tmp_path, p.root, start=False)
    try:
        before = (revision(p.root), data_revision(w.runtime.store), w.ai.read_runtime(), w.ai.export_source())
        scenario = deepcopy(w.workflows.catalog()['scenarios'][0]['scenario'])
        scenario['environment'] = {'language': language, 'number_mode': mode, 'enum_mode': enum_mode}
        result = w.workflows.run(scenario, expected_revision=before[0])
        assert result['status'] == 'passed' and len(result['steps']) == 21 and not result['diagnostics'], result
        assert result['types']['collections']['history']['row']['fields']['Month']['kind'] == 'Text'
        assert result['types']['collections']['monthSnapshot']['row']['fields']['Value']['kind'] == 'Text'
        assert before == (revision(p.root), data_revision(w.runtime.store), w.ai.read_runtime(), w.ai.export_source())
        with ZipFile(BytesIO(p.export())) as archive:
            assert set(archive.namelist()) == {'Src/locale-tables.pa.yaml', 'Src/Components/CalendarPanel.pa.yaml'}
            text = archive.read('Src/Components/CalendarPanel.pa.yaml').decode()
            assert 'Calendar.MonthsLong()' in text and 'Clock.IsClock24()' in text and 'locale_tables' not in text
    finally:
        w.runtime.close()


def test_component_locale_outputs_recalculate_but_started_collections_are_snapshots(tmp_path):
    p = locale_tables_project(tmp_path/'calendar')
    w = Workspace(tmp_path, p.root)
    try:
        r = w.runtime
        r.state()
        assert r.fx.evaluate('First(Left.Months).Value') == 'January'
        frozen = deepcopy(serial(r.collections['monthSnapshot']))
        for language, name, clock24 in [('ja-JP', '1月', True), ('ar-EG', 'يناير', False), ('fr-CA', 'janvier', True)]:
            r.environment['language'] = language
            r.invalidate()
            r.state()
            assert r.fx.evaluate('First(Left.Months).Value') == name
            assert r.fx.evaluate('First(Right.Months).Value') == name
            assert r.fx.evaluate('First(MonthOptions).Value') == name
            assert r.fx.evaluate('Left.Is24') is clock24
            assert serial(r.collections['monthSnapshot']) == frozen
        assert not r.diagnostics
    finally:
        w.runtime.close()

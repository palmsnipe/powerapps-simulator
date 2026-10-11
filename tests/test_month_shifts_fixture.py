from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import pytest
from powerapps_sim.fixtures import month_shifts_project
from powerapps_sim.web import Workspace
from powerapps_sim.runtime import Runtime, serial
from powerapps_sim.source import Project
from powerapps_sim.authoring import revision, data_revision


@pytest.mark.parametrize('language', ['en-US', 'fr-CA'])
@pytest.mark.parametrize('mode', ['float', 'decimal'])
@pytest.mark.parametrize('enum_mode', ['legacy', 'strong'])
def test_typed_component_dates_workflow_export_and_owner(tmp_path, language, mode, enum_mode):
    p = month_shifts_project(tmp_path/'planning')
    w = Workspace(tmp_path, p.root, start=False)
    try:
        before = revision(p.root), data_revision(w.runtime.store), w.ai.read_runtime(), w.ai.export_source()
        scenario = deepcopy(w.workflows.catalog()['scenarios'][0]['scenario'])
        scenario['environment'] = {'language':language, 'number_mode':mode, 'enum_mode':enum_mode}
        result = w.workflows.run(scenario, expected_revision=before[0])
        assert result['status'] == 'passed' and len(result['steps']) == 16 and not result['diagnostics'], result
        assert result['types']['collections']['history']['row']['fields']['Renewal']['kind'] == 'Date'
        assert before == (revision(p.root), data_revision(w.runtime.store), w.ai.read_runtime(), w.ai.export_source())
        with ZipFile(BytesIO(p.export())) as archive:
            assert set(archive.namelist()) == {'Src/month-shifts.pa.yaml', 'Src/Components/MonthPanel.pa.yaml'}
            assert 'EDate(' in archive.read('Src/Components/MonthPanel.pa.yaml').decode()
    finally:w.runtime.close()


def test_reactive_dates_failed_save_persistence_and_reset(tmp_path):
    p = month_shifts_project(tmp_path/'planning')
    w = Workspace(tmp_path, p.root)
    try:
        r=w.runtime
        r.state()
        r.event('Home/Panels/Left/Months','OnChange',-1.9)
        assert serial(r.fx.evaluate('Left.Renewal'))=='2023-12-31'
        assert serial(r.fx.evaluate('Right.Renewal'))=='2023-06-15'
        r.store.failures['Plans']='write'
        r.event('Home/Save','OnSelect')
        assert r.store.rows('Plans')==[]
        assert serial(r.fx.evaluate('Left.Renewal'))=='2023-12-31'
        r.store.failures.clear()
        r.event('Home/Save','OnSelect')
        assert r.fx.evaluate('First(Plans).\'Renewal date\'').kind=='Date'
        assert r.store.rows('Plans')[0]['Renewal date']=='2023-12-31'
        other=Runtime(Project(p.root))
        try:
            assert serial(other.fx.evaluate('First(Plans).\'Renewal date\''))=='2023-12-31'
            assert other.fx.evaluate('First(Plans).\'Period end\'').kind=='Date'
        finally:other.close()
        r.event('Home/Panels/Left/ResetButton','OnSelect')
        assert serial(r.fx.evaluate('Left.Renewal'))=='2024-02-29'
        assert len(r.collections['history'])==1
    finally:w.runtime.close()

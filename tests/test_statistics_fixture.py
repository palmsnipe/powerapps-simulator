"""Statistics in independent components and persistent, mapped draft data."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

import pytest

from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision, data_revision
from powerapps_sim.fixtures import statistics_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.syntax import FxError


@pytest.fixture
def r(tmp_path):
    result = Runtime(statistics_project(tmp_path / 'p'))
    result.restart(); result.state()
    assert not result.diagnostics
    yield result
    result.close()


def click(r, name):
    r.event('StatisticsLab/' + name, 'OnSelect'); r.state()


def test_component_actions_callbacks_and_reset_isolate_statistics(r):
    click(r, 'Panels/LeftStats/AddSample')
    summary = r.fx.evaluate('LeftStats.Summary')
    assert summary['Count'] == 3 and summary['Variance'] == pytest.approx(8/3)
    assert r.collections['trace'][0]['Panel'] == 'LeftStats'
    assert r.collections['trace'][0]['Deviation'] == pytest.approx((8/3)**.5)
    assert r.fx.evaluate('RightStats.Summary.Deviation') == 2
    assert 'localSamples' not in r.collections
    click(r, 'Panels/LeftStats/ResetSamples')
    assert r.fx.evaluate('LeftStats.Summary.Deviation') == 1
    assert r.fx.evaluate('RightStats.ResetCount') == 1
    assert not r.diagnostics


def test_empty_statistics_error_cells_remain_unobserved_until_consumed(r):
    click(r, 'ToggleSamples')
    summary = r.fx.evaluate('LeftStats.Summary')
    assert summary['Count'] == 0 and isinstance(summary['Variance'], FxError)
    assert isinstance(summary['Mean'], FxError) and summary['Mean'].kind == 'Div0'
    assert r.fx.evaluate('IsError(LeftStats.Summary)') is False
    assert r.fx.evaluate('IsError(LeftStats.Summary.Deviation)') is True
    assert not r.collections['failures'] and not r.app_errors.reports
    assert r.refs['StatisticsLab/Panels/LeftStats/Result'].property('Text') == 'No samples'
    click(r, 'ToggleSamples')
    assert r.fx.evaluate('LeftStats.Summary.Deviation') == 1 and not r.diagnostics


def test_mapped_writes_recalculate_only_affected_component_and_persist(tmp_path):
    project = statistics_project(tmp_path / 'p')
    r = Runtime(project)
    try:
        r.restart(); r.state()
        click(r, 'Panels/LeftStats/AddSample')
        r.event('StatisticsLab/EditAmount', 'OnChange', 8)
        r.store.failures['Drafts'] = 'write'; click(r, 'SaveDraft')
        assert r.store.rows('Drafts')[0]['Sample amount'] == 2
        assert r.fx.evaluate('LeftStats.Summary.Count') == 3
        r.store.failures.clear(); click(r, 'SaveDraft')
        assert r.fx.evaluate('LeftStats.Summary.Count') == 2
        assert r.fx.evaluate('LeftStats.Summary.Deviation') == 2
        assert r.fx.evaluate('RightStats.ResetCount') == 1
    finally:
        r.close()
    reopened = Runtime(project)
    try:
        reopened.restart(); reopened.state()
        assert reopened.fx.evaluate('LeftStats.Summary.Deviation') == 2
        assert reopened.store.rows('Drafts')[0]['Sample amount'] == 8
    finally:
        reopened.close()


@pytest.mark.parametrize('language', ['en-CA', 'fr-CA'])
@pytest.mark.parametrize('number_mode', ['float', 'decimal'])
def test_statistics_workflow_preserves_owner_and_translates(tmp_path, language, number_mode):
    project = statistics_project(tmp_path / 'p')
    w = Workspace(tmp_path, project.root)
    try:
        before = (revision(project.root), data_revision(w.runtime.store), w.ai.call('read_runtime', {}))
        scenario = deepcopy(w.workflows.catalog()['scenarios'][0]['scenario'])
        scenario['environment'] = {'language': language, 'number_mode': number_mode, 'enum_mode': 'strong'}
        result = w.workflows.run(scenario, expected_revision=revision(project.root))
        assert result['status'] == 'passed', [step for step in result['steps'] if step['status'] != 'passed']
        assert len(result['steps']) == 30
        assert len(result['diagnostics']) == 1 and result['diagnostics'][0]['member'] == 'SaveDraft.OnSelect'
        assert before == (revision(project.root), data_revision(w.runtime.store), w.ai.call('read_runtime', {}))
        w.runtime.environment.update(scenario['environment']); w.runtime.restart(); w.runtime.state()
        label = w.runtime.refs['StatisticsLab/Panels/LeftStats/Heading'].property('Text')
        assert label.startswith('Gauche' if language.startswith('fr') else 'Left')
    finally:
        w.runtime.close()


def test_fixture_source_roundtrip_exports_power_apps_only(r):
    with ZipFile(BytesIO(r.project.export())) as archive:
        assert archive.namelist() == ['Src/statistics.pa.yaml']
        text = archive.read(archive.namelist()[0]).decode()
    assert text == r.project.documents['Src/statistics.pa.yaml']
    assert 'StdevP(' in text and 'VarP(' in text and 'RaiseOnReset: true' in text
    assert 'data.sqlite' not in text and 'format_version' not in text

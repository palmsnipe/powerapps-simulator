"""Clean linked-data component fixture, separate from the erroneous imported app."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

import pytest

from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision, data_revision
from powerapps_sim.fixtures import component_reset_project
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime, serial
from powerapps_sim.syntax import FxError


@pytest.fixture
def r(tmp_path):
    result = Runtime(component_reset_project(tmp_path / 'p'))
    result.restart(); result.state()
    assert not result.diagnostics
    yield result
    result.close()


def click(r, name):
    r.event('ResetLab/' + name, 'OnSelect')
    return r.state()


def test_callbacks_see_committed_values_and_shadow_host_parameters(r):
    click(r, 'Panels/LeftPanel/Increase')
    assert r.collections['trace'][-1] == {
        'Instance': 'LeftPanel', 'Stage': 'change', 'Total': 11,
        'Snapshot': 11, 'HostStage': 'host', 'Peer': 100, 'ResetCount': 1,
    }
    assert r.globals['stage'] == 'host' and 'current' not in r.globals
    click(r, 'Panels/RightPanel/Increase')
    assert r.fx.evaluate('LeftPanel.Total') == 11 and r.fx.evaluate('RightPanel.Total') == 101
    click(r, 'Toolbar/ResetLeft')
    assert r.fx.evaluate('LeftPanel.Total') == 10 and r.fx.evaluate('RightPanel.Total') == 101
    assert r.fx.evaluate('RightPanel.ResetCount') == 1


def test_pure_formatter_and_action_contract_validate_before_effects(r):
    assert r.fx.evaluate('LeftPanel.Format("Amount",3)') == 'Amount · 3'
    with pytest.raises(FxError):
        r.fx.evaluate('LeftPanel.Increase()', Context(r))
    before = deepcopy(r.collections['trace'])
    with pytest.raises(FxError):
        r.fx.evaluate('LeftPanel.Increase("bad")', Context(r, behavior=True))
    assert r.collections['trace'] == before and r.fx.evaluate('LeftPanel.Total') == 10


def test_input_failure_keeps_baseline_and_recovering_same_seed_keeps_local_edit(r):
    click(r, 'Panels/LeftPanel/Increase'); click(r, 'Toolbar/FailInput')
    assert r.fx.evaluate('LeftPanel.Total') == 11 and r.fx.evaluate('LeftPanel.ResetCount') == 1
    assert len(r.collections['failures']) == 1
    assert r.collections['failures'][0]['Observed'] == 'ResetLab/Panels/LeftPanel.Seed'
    click(r, 'Toolbar/Recover')
    assert r.fx.evaluate('LeftPanel.Total') == 11 and r.fx.evaluate('LeftPanel.ResetCount') == 1
    click(r, 'Toolbar/SelectSecond')
    assert r.fx.evaluate('LeftPanel.Total') == 25 and r.fx.evaluate('LeftPanel.ResetCount') == 2
    click(r, 'Toolbar/BlankSeed')
    assert r.fx.evaluate('LeftPanel.Total') == 0 and r.fx.evaluate('LeftPanel.ResetCount') == 3


def test_reset_error_retains_origin_and_consuming_property(r):
    click(r, 'Toolbar/FailReset')
    error = r.collections['failures'][0]
    assert error['Source'] == 'ResetLab/Panels/LeftPanel.ResetGate'
    assert error['Observed'] == 'ResetLab/Panels/LeftPanel/Note.Reset'
    for _ in range(3):
        r.state()
    assert len(r.collections['failures']) == 1
    diagnostic = next(d for d in r.diagnostics if d.get('observed') == error['Observed'])
    assert diagnostic['member'] == 'Note.Reset'
    formula = r.global_refs['LeftPanel'].control.properties['ResetGate']
    assert formula[diagnostic['start']:diagnostic['end']] == '1/0'


@pytest.mark.parametrize('language', ['en-CA', 'fr-CA'])
@pytest.mark.parametrize('number_mode', ['float', 'decimal'])
def test_workflow_and_translation_preserve_owner(tmp_path, language, number_mode):
    project = component_reset_project(tmp_path / 'p')
    w = Workspace(tmp_path, project.root)
    try:
        before = (revision(project.root), data_revision(w.runtime.store),
                  serial(w.runtime.globals), serial(w.runtime.collections), serial(w.runtime.component_state))
        scenario = deepcopy(w.workflows.catalog()['scenarios'][0]['scenario'])
        scenario['environment'] = {'language': language, 'number_mode': number_mode, 'enum_mode': 'strong'}
        result = w.workflows.run(scenario, expected_revision=revision(project.root))
        assert result['status'] == 'passed', result['steps']
        assert len(result['steps']) == 38
        assert len(result['diagnostics']) == 3
        assert {d['observed'] for d in result['diagnostics']} == {
            'ResetLab/Panels/LeftPanel.Seed',
            'ResetLab/Panels/LeftPanel/Note.Reset',
            'ResetLab/Toolbar/Save.OnSelect',
        }
        assert before == (revision(project.root), data_revision(w.runtime.store),
                          serial(w.runtime.globals), serial(w.runtime.collections), serial(w.runtime.component_state))
        w.runtime.environment.update(scenario['environment']); w.runtime.restart(); w.runtime.state()
        expected = 'Actuel' if language.startswith('fr') else 'Current'
        assert w.runtime.refs['ResetLab/Panels/LeftPanel/Caption'].property('Text').startswith(expected)
    finally:
        w.runtime.close()


def test_source_export_retains_contracts_and_excludes_fixture_configuration(r):
    with ZipFile(BytesIO(r.project.export())) as archive:
        assert archive.namelist() == ['Src/component-reset.pa.yaml']
        source = archive.read(archive.namelist()[0]).decode()
    assert source == r.project.documents['Src/component-reset.pa.yaml']
    assert 'RaiseOnReset: true' in source and 'PropertyKind: Function' in source
    assert 'data.sqlite' not in source and 'format_version' not in source

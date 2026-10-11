"""Simulator lifecycle limits isolate feedback without rewriting Power Apps source."""
from copy import deepcopy

import pytest

from powerapps_sim.fixtures import lifecycle_project
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import dump_yaml


def feedback(tmp_path, *, number='float', language='en-US', repair=False):
    project = lifecycle_project(tmp_path / 'feedback')
    name = 'Src/lifecycle.pa.yaml'
    source = deepcopy(project.parsed[name])
    app = source['App']['Properties']
    app['OnStart'] += ';Set(feedbackEnabled,true);Clear(failures);Set(queued,0)'
    app['OnError'] = '=Collect(failures,AllErrors)' + (';Set(feedbackEnabled,false);Set(seed,500)' if repair else '')
    panel = source['Screens']['Lifecycle']['Children'][5]['Panels']['Children'][0]['LeftPanel']
    panel['Properties']['OnResetDone'] += ';If(feedbackEnabled,Set(seed,seed+1))'
    source['Screens']['Lifecycle']['Children'].append({'Healthy': {
        'Control': 'ModernButton@1.0.0', 'Properties': {
            'Text': '="Healthy callback"', 'OnSelect': '=Set(queued,queued+1)'}}})
    project.update_source(name, dump_yaml(source))
    project.config['environment'].update(number_mode=number, language=language)
    project.save_config()
    r = Runtime(project)
    r.restart()
    assert not r.diagnostics
    return r


@pytest.mark.parametrize('number', ['float', 'decimal'])
@pytest.mark.parametrize('language', ['en-US', 'fr-CA'])
def test_feedback_is_bounded_across_state_reads_and_peers_keep_working(tmp_path, number, language):
    r = feedback(tmp_path, number=number, language=language)
    try:
        original = dict(r.project.documents)
        r.fx.evaluate('Set(seed,20);Select(Healthy)', r.refs['Lifecycle/ChangeSeed'].context(True))
        state = r.state()
        resets = r.fx.evaluate('LeftPanel.ResetCount')
        assert resets == 100 and r.globals['queued'] == 1
        assert len(r.collections['failures']) == 1
        error = r.collections['failures'][0]
        assert error['Source'] == error['Observed'] == 'Lifecycle/Panels/LeftPanel.OnReset'
        assert 'simulator' in error['Message'].lower()
        for _ in range(3):
            r.state()
        assert r.fx.evaluate('LeftPanel.ResetCount') == resets
        assert len(r.collections['failures']) == 1
        r.event('Lifecycle/Panels/RightPanel/Increase', 'OnSelect')
        assert r.fx.evaluate('RightPanel.Total') == 101
        r.event('Lifecycle/Healthy', 'OnSelect')
        assert r.globals['queued'] == 2 and r.fx.evaluate('LeftPanel.ResetCount') == resets
        assert state['screen'] == 'Lifecycle'
        assert r.project.documents == original
        assert not r.resetting and not r.app_errors.pending
    finally:
        r.close()


def test_external_input_change_rearms_and_restart_clears_the_guard(tmp_path):
    r = feedback(tmp_path)
    try:
        r.event('Lifecycle/ChangeSeed', 'OnSelect')
        assert r.fx.evaluate('LeftPanel.ResetCount') == 100
        r.fx.evaluate('Set(feedbackEnabled,false);Set(seed,300)', Context(r, behavior=True))
        r.drain_events()
        assert r.fx.evaluate('LeftPanel.Total') == 300
        assert r.fx.evaluate('LeftPanel.ResetCount') == 101
        r.state(); assert len(r.collections['failures']) == 1
        r.fx.evaluate('Set(feedbackEnabled,true);Set(seed,400)', Context(r, behavior=True))
        r.drain_events()
        assert r.fx.evaluate('LeftPanel.ResetCount') == 201
        assert len(r.collections['failures']) == 2
        r.restart(); r.state()
        assert r.fx.evaluate('LeftPanel.ResetCount') == 0
        assert not r.collections['failures'] and not r.diagnostics
    finally:
        r.close()


def test_onerror_can_repair_and_rearm_the_failed_instance(tmp_path):
    r = feedback(tmp_path, repair=True)
    try:
        r.event('Lifecycle/ChangeSeed', 'OnSelect')
        assert r.fx.evaluate('LeftPanel.Total') == 500
        assert r.fx.evaluate('LeftPanel.ResetCount') == 101
        assert len(r.collections['failures']) == 1
        r.state(); assert len(r.collections['failures']) == 1
    finally:
        r.close()


def test_explicit_reset_rearms_without_changing_an_input(tmp_path):
    r = feedback(tmp_path)
    try:
        r.event('Lifecycle/ChangeSeed', 'OnSelect')
        seed = r.globals['seed']
        assert r.component_reset_blocks
        r.fx.evaluate('Set(feedbackEnabled,false);Reset(LeftPanel)', Context(r, behavior=True))
        r.state()
        assert r.fx.evaluate('LeftPanel.Total') == seed
        assert r.fx.evaluate('LeftPanel.ResetCount') == 101
        assert not r.component_reset_blocks
    finally:
        r.close()


def test_distinct_instances_do_not_share_the_reset_budget(tmp_path):
    from powerapps_sim.source import Project
    project = Project(tmp_path / 'many')
    project.update_source('Src/many.pa.yaml', dump_yaml({
        'App': {'Properties': {'OnStart': '=Set(seed,10)'}},
        'ComponentDefinitions': {'Counter': {
            'AccessAppScope': False,
            'CustomProperties': {
                'Seed': {'PropertyKind': 'Input', 'DataType': 'Number', 'RaiseOnReset': True, 'Default': '=0'},
                'Count': {'PropertyKind': 'Output', 'DataType': 'Number', 'Default': '=Coalesce(count,0)'}},
            'Properties': {'OnReset': '=Set(count,Counter.Count+1)'}}},
        'Screens': {'Home': {'Children': [
            {f'C{i}': {'Control': 'CanvasComponent', 'ComponentName': 'Counter', 'Properties': {'Seed': '=seed'}}}
            for i in range(105)]}}}))
    r = Runtime(project)
    try:
        r.restart()
        r.fx.evaluate('Set(seed,20)', Context(r, behavior=True))
        r.drain_events()
        assert all(r.fx.evaluate(f'C{i}.Count') == 1 for i in range(105))
        assert not r.component_reset_blocks and not r.diagnostics
    finally:
        r.close()


def test_nested_feedback_isolated_at_the_leaf_and_callbacks_retain_host_scope(tmp_path):
    from powerapps_sim.fixtures import nested_project
    project = nested_project(tmp_path / 'nested-feedback')
    name = 'Src/nested.pa.yaml'
    source = deepcopy(project.parsed[name])
    shell = source['ComponentDefinitions']['Shell']
    shell['Children'][1]['InnerA']['Properties']['Seed'] = '=Coalesce(localSeed,Shell.Seed)'
    shell['Children'][1]['InnerA']['Properties']['Changed'] += ';If(total>10,Set(localSeed,total+1))'
    shell['Children'][2]['InnerB']['Properties']['Seed'] = '=110'
    leaf = source['ComponentDefinitions']['Leaf']
    leaf['CustomProperties']['Seed']['RaiseOnReset'] = True
    leaf['Properties']['OnReset'] += ';Leaf.Changed(Leaf.Total)'
    project.update_source(name, dump_yaml(source))
    r = Runtime(project)
    try:
        r.restart(); r.state()
        r.event('Nested/ChangeSeed', 'OnSelect')
        r.state()
        assert 'Nested/LeftShell/InnerA' in r.component_reset_blocks
        count = r.refs['Nested/LeftShell/InnerA'].property('ResetCount')
        r.state(); assert r.refs['Nested/LeftShell/InnerA'].property('ResetCount') == count
        assert 'localSeed' not in r.globals
        assert r.component_state['Nested/LeftShell']['variables']['localSeed'] > 20
        assert r.refs['Nested/LeftShell/InnerB'].property('ResetCount') == 1
        assert r.refs['Nested/RightShell/InnerA'].property('ResetCount') == 0
        assert r.fx.evaluate('RightShell.FirstTotal') == 1000
        assert not r.component_call_stack and not r.resetting
    finally:
        r.close()


def test_reentrant_visibility_callback_reports_a_formula_error_instead_of_python_recursion(tmp_path):
    project = lifecycle_project(tmp_path / 'navigation-cycle')
    name = 'Src/lifecycle.pa.yaml'
    source = deepcopy(project.parsed[name])
    source['App']['Properties']['OnStart'] += ';Clear(failures)'
    source['App']['Properties']['OnError'] = '=Collect(failures,AllErrors)'
    source['Screens']['Lifecycle']['Properties']['OnVisible'] = '=Navigate(Lifecycle)'
    project.update_source(name, dump_yaml(source))
    r = Runtime(project)
    try:
        r.restart(); r.state()
        assert r.active_screen == 'Lifecycle'
        assert len(r.collections['failures']) == 1
        error = r.collections['failures'][0]
        assert error['Source'] == 'Lifecycle.OnVisible'
        assert 'OnVisible' in error['Message'] and 'cycle' in error['Message'].lower()
        r.event('Lifecycle/Panels/RightPanel/Increase', 'OnSelect')
        assert r.fx.evaluate('RightPanel.Total') == 101
        assert not r.active_event_stack
    finally:
        r.close()


@pytest.mark.parametrize('number', ['float', 'decimal'])
@pytest.mark.parametrize('language', ['en-US', 'fr-CA'])
def test_public_feedback_workflow_preserves_the_owner_and_native_source(tmp_path, number, language):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision, data_revision
    from powerapps_sim.fixtures import component_feedback_project
    p = component_feedback_project(tmp_path / 'public')
    w = Workspace(tmp_path, p.root, start=False)
    try:
        before = w.ai.read_runtime(), revision(p.root), data_revision(w.runtime.store), w.ai.export_source()
        scenario = deepcopy(w.workflows.catalog()['scenarios'][0]['scenario'])
        scenario['environment'] = {'number_mode': number, 'language': language}
        report = w.workflows.run(scenario, expected_revision=before[1])
        assert report['status'] == 'passed' and len(report['steps']) == 23
        assert len(report['diagnostics']) == 1
        assert report['diagnostics'][0]['expression_member'] == 'Home/Panels/LeftPanel.OnReset'
        assert before == (w.ai.read_runtime(), revision(p.root), data_revision(w.runtime.store), w.ai.export_source())
        source = next(iter(p.documents.values()))
        assert 'RaiseOnReset: true' in source
        assert 'component_reset_blocks' not in source and 'simulator limit' not in source
    finally:
        w.runtime.close()

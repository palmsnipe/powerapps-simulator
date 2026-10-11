"""Errors consumed by component/reset lifecycle rules reach deferred App.OnError."""
from copy import deepcopy

import pytest

from powerapps_sim.fixtures import lifecycle_project
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import dump_yaml


def variant(tmp_path, change, number_mode='float'):
    project = lifecycle_project(tmp_path / 'reset-errors')
    name = 'Src/lifecycle.pa.yaml'
    source = deepcopy(project.parsed[name])
    source['App']['Properties']['OnStart'] += ';Clear(failures)'
    source['App']['Properties']['OnError'] = '=Collect(failures, AllErrors)'
    change(source)
    project.update_source(name, dump_yaml(source))
    project.config['environment']['number_mode'] = number_mode
    project.save_config()
    runtime = Runtime(project)
    runtime.restart()
    runtime.state()
    return runtime


def bad_input(source):
    panel = source['Screens']['Lifecycle']['Children'][5]['Panels']['Children'][0]['LeftPanel']
    panel['Properties']['Seed'] = '=If(seed=20,1/0,seed)'
    # A caught visual value must not hide the independent lifecycle failure.
    source['ComponentDefinitions']['ResetPanel']['Children'][0]['Caption']['Properties']['Text'] = '=IfError(Text(ResetPanel.Total),"caught")'


@pytest.mark.parametrize('number_mode', ['float', 'decimal'])
def test_raise_on_reset_failure_is_observed_once_then_recovers(tmp_path, number_mode):
    r = variant(tmp_path, bad_input, number_mode)
    try:
        r.event('Lifecycle/ChangeSeed', 'OnSelect')
        assert len(r.collections['failures']) == 1
        error = r.collections['failures'][0]
        assert error['Kind'] == 13
        assert error['Source'] == error['Observed'] == 'Lifecycle/Panels/LeftPanel.Seed'
        assert r.fx.evaluate('LeftPanel.ResetCount') == 0
        assert r.fx.evaluate('RightPanel.Total') == 100
        for _ in range(3):
            r.state()
        assert len(r.collections['failures']) == 1
        r.event('Lifecycle/ChangeSeed', 'OnSelect')
        assert r.fx.evaluate('LeftPanel.Total') == 30
        assert r.fx.evaluate('LeftPanel.ResetCount') == 1
        r.fx.evaluate('Set(seed,20)', Context(r, behavior=True))
        r.drain_events()
        assert len(r.collections['failures']) == 2
        assert r.fx.evaluate('LeftPanel.ResetCount') == 1
        assert not r.app_errors.pending
    finally:
        r.close()


def test_pure_input_read_can_be_caught_before_lifecycle_consumes_it(tmp_path):
    r = variant(tmp_path, bad_input)
    try:
        r.fx.evaluate('Set(seed,20)', Context(r, behavior=True))
        assert r.fx.evaluate('IfError(LeftPanel.Seed,42)') == 42
        assert not r.collections['failures'] and not r.app_errors.pending
        r.changed_component_inputs()
        assert not r.collections['failures'] and len(r.app_errors.pending) == 1
        r.drain_events()
        assert len(r.collections['failures']) == 1
    finally:
        r.close()


def bad_reset(source):
    source['App']['Properties']['OnStart'] = '=Set(badReset,false);' + source['App']['Properties']['OnStart'][1:]
    source['Screens']['Lifecycle']['Children'].append({'ResetInput': {
        'Control': 'Classic/TextInput@2.3.2',
        'Properties': {'Visible': '=false', 'Default': '="initial"', 'Reset': '=If(Coalesce(badReset,false),1/0=0,false)'}
    }})


@pytest.mark.parametrize('number_mode', ['float', 'decimal'])
def test_hidden_reset_rule_failure_and_healthy_rearming(tmp_path, number_mode):
    r = variant(tmp_path, bad_reset, number_mode)
    try:
        r.fx.evaluate('Set(badReset,true)', Context(r, behavior=True))
        r.sync_reset_properties()
        assert len(r.app_errors.pending) == 1 and not r.collections['failures']
        r.drain_events()
        assert len(r.collections['failures']) == 1
        assert r.collections['failures'][0]['Observed'] == 'Lifecycle/ResetInput.Reset'
        assert r.collections['failures'][0]['Source'] == 'Lifecycle/ResetInput.Reset'
        r.state(); r.sync_reset_properties(); r.drain_events()
        assert len(r.collections['failures']) == 1
        r.fx.evaluate('Set(badReset,false)', Context(r, behavior=True)); r.drain_events()
        r.fx.evaluate('Set(badReset,true)', Context(r, behavior=True)); r.drain_events()
        assert len(r.collections['failures']) == 2
        assert r.fx.evaluate('RightPanel.Total') == 100
    finally:
        r.close()


def test_reset_type_error_reports_without_resetting_or_recursive_handler(tmp_path):
    def change(source):
        bad_reset(source)
        source['App']['Properties']['OnError'] = '=Collect(failures,AllErrors);Error(FirstError)'
    r = variant(tmp_path, change)
    try:
        assert not r.collections['failures']
        r.refs['Lifecycle/ResetInput'].control.properties['Reset'] = '=42'
        r.invalidate(); r.drain_events()
        assert len(r.collections['failures']) == len(r.app_errors.reports) == 1
        assert r.collections['failures'][0]['Kind'] == 25
        assert not r.app_errors.pending and not r.app_errors.handling
        assert not r.app_errors.reports[0]['handled']
        assert r.notifications[-1]['origin'] == 'App.OnError'
        r.state(); assert len(r.collections['failures']) == 1
    finally:
        r.close()


def test_handler_can_repair_failed_input_and_reset_after_current_behavior(tmp_path):
    def change(source):
        bad_input(source)
        source['App']['Properties']['OnError'] = '=Collect(failures,AllErrors);Set(seed,30)'
    r = variant(tmp_path, change)
    try:
        r.event('Lifecycle/ChangeSeed', 'OnSelect')
        assert len(r.collections['failures']) == 1
        assert r.fx.evaluate('LeftPanel.Total') == 30
        assert r.fx.evaluate('LeftPanel.ResetCount') == 1
        assert [row['Step'] for row in r.collections['trace']][-3:] == ['before seed', 'after seed', 'LeftPanel reset 30']
        assert not r.app_errors.pending and not r.resetting
        r.state(); assert len(r.collections['failures']) == 1
    finally:
        r.close()

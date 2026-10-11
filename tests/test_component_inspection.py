"""Inspect contracts without executing callbacks, and observe nested data safely."""
from copy import deepcopy
import pytest
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision, data_revision
from powerapps_sim.component_inspection import describe
from powerapps_sim.fixtures import nested_project
from powerapps_sim.runtime import Ref, serial
from powerapps_sim.source import dump_yaml, load_yaml


@pytest.fixture
def workspace(tmp_path):
    p = nested_project(tmp_path/'nested')
    w = Workspace(tmp_path/'workspace', p.root)
    w.runtime.state()
    yield w
    w.runtime.close()


def owner(w):
    r = w.runtime
    return deepcopy(serial([r.globals, r.collections, r.component_state, r.control_state,
        r.screen_context, r.input_baselines, r.reset_property_baselines, r.notifications,
        r.app_errors.reports, list(r.component_input_baselines.items())])), revision(w.project.root), data_revision(r.store)


def test_ai_contract_discovery_never_evaluates_properties_or_parameter_defaults(workspace, monkeypatch):
    w = workspace; before = owner(w)
    monkeypatch.setattr(Ref, 'property', lambda *_: pytest.fail('Read-only metadata evaluated a property'))
    monkeypatch.setattr(w.runtime.fx, 'evaluate', lambda *_: pytest.fail('Read-only metadata evaluated a formula'))
    contracts = w.ai.read_runtime()['component_contracts']
    leaf = contracts['Nested/LeftShell/InnerA']['properties']
    assert leaf['Seed']['type']['kind'] == 'Number'
    assert leaf['Seed']['overridden'] and leaf['Seed']['formula'] == '=Shell.Seed'
    assert 'value' not in leaf['Total']
    assert leaf['Add']['parameters'] == [{'name':'amount', 'type':{'kind':'Number'}, 'required':False, 'optional':True,'default':'=1'}]
    assert leaf['Add']['type']['kind'] == 'Void'
    assert leaf['Changed']['parameters'][0]['required']
    assert contracts['Nested/LeftShell/InnerA']['definition'] == 'Leaf'
    assert not contracts['Nested/LeftShell/InnerA']['access_app_scope']
    assert owner(w) == before


@pytest.mark.parametrize('mode', ['float', 'decimal'])
@pytest.mark.parametrize('language', ['en-US', 'fr-CA'])
def test_data_observation_tracks_nested_actions_resets_and_peer_isolation(workspace, mode, language):
    w=workspace
    w.project.config['environment'].update(number_mode=mode, language=language); w.project.save_config(); w.open(w.project)
    r=w.runtime; r.state()
    r.event('Nested/AddLeft','OnSelect')
    before=owner(w)
    report=describe(r,evaluate=True)
    left=report['Nested/LeftShell/InnerA']['properties']; right=report['Nested/RightShell/InnerA']['properties']
    assert left['Total']['value'] == (11 if mode=='float' else {'$decimal':'11'})
    assert right['Total']['value'] == (1000 if mode=='float' else {'$decimal':'1000'})
    assert len(left['Rows']['value']) == 1 and right['Rows']['value'] == []
    assert left['Rows']['type']['row']['fields']['Total']['kind'] == ('Number' if mode=='float' else 'Decimal')
    assert owner(w)==before
    r.event('Nested/ResetLeft','OnSelect')
    reset=describe(r,evaluate=True)['Nested/LeftShell/InnerA']['properties']
    assert reset['Rows']['value']==[]
    assert reset['ResetCount']['value']==(1 if mode=='float' else {'$decimal':'1'})
    assert not r.diagnostics


def test_http_inspection_never_invokes_callable_properties(app,tmp_path,monkeypatch):
    w=app.extensions['workspace'];w.open(nested_project(tmp_path/'http-components'));w.runtime.state()
    before=owner(w)
    monkeypatch.setattr(w.runtime,'component_call',lambda *_:pytest.fail('Inspector invoked a callable'))
    monkeypatch.setattr(w.runtime,'reset_ref',lambda *_:pytest.fail('Inspector dispatched OnReset'))
    monkeypatch.setattr(w.runtime,'drain_events',lambda *_:pytest.fail('Inspector drained events'))
    client=app.test_client(); result=client.get('/api/component-inspection')
    assert result.status_code==200
    properties=result.json['Nested/LeftShell/InnerA']['properties']
    assert 'value' not in properties['Add'] and properties['Total']['value']==10
    assert owner(w)==before
    properties['Seed']['type']['kind']='Text'
    assert client.get('/api/component-inspection').json['Nested/LeftShell/InnerA']['properties']['Seed']['type']['kind']=='Number'


def test_inspection_isolates_bad_data_and_contracts_without_running_app_onerror(workspace):
    w=workspace; doc='Src/nested.pa.yaml'
    if doc not in w.project.documents:doc=next(iter(w.project.documents))
    source=load_yaml(w.project.documents[doc])
    leaf=source['ComponentDefinitions']['Leaf']['CustomProperties']
    leaf['Broken']={'PropertyKind':'Output','DataType':'Number','Default':'=1/0'}
    leaf['BadSignature']={'PropertyKind':'Action','ReturnType':'None','Parameters':[{'bad':{'DataType':'Void'}}],'Default':'=Set(shouldNeverRun,true)'}
    w.project.update_source(doc,dump_yaml(source)); w.open(w.project); w.runtime.state()
    before=owner(w)
    report=describe(w.runtime,evaluate=True)['Nested/LeftShell/InnerA']['properties']
    assert report['Broken']['value']['$error']['Kind']==13
    assert 'Void is not a parameter type' in report['BadSignature']['error']['$error']['Message']
    assert report['Total']['value']==10 and 'shouldNeverRun' not in w.runtime.globals
    assert owner(w)==before


def test_contract_metadata_and_observation_do_not_enter_powerapps_exports(workspace):
    w=workspace; before=w.ai.export_source()
    describe(w.runtime,evaluate=True); w.ai.read_runtime()
    assert w.ai.export_source()==before

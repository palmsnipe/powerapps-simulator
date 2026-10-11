"""Native random invariants and actual dependency/lifecycle contracts."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import pytest
from powerapps_sim.fx import Context
from powerapps_sim.binding import BindScope,NUMBER,value_type
from powerapps_sim.runtime import serial
from powerapps_sim.syntax import FxError
from powerapps_sim.conformance import _run_case

CASES=json.loads((Path(__file__).parents[1]/'powerapps_sim/conformance_cases/volatile_contracts.json').read_text())['cases']

@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_pinned_random_and_shuffle_oracles(runtime,case):
    runtime.environment.update(case['environment']);runtime.invalidate()
    result=_run_case(runtime,case)
    assert result['status']=='passed',result

@pytest.fixture
def workspace(tmp_path):
    from powerapps_sim.application import Workspace
    from powerapps_sim.fixtures import volatile_project
    p=volatile_project(tmp_path/'project');w=Workspace(tmp_path,p.root)
    yield w
    w.runtime.close()

def expression_rule(r,formula,name='Probe'):
    from powerapps_sim.source import Control
    control=Control(name,'ModernText@1.0.0',{'Properties':{'Text':'='+formula}},'Src/volatile.pa.yaml')
    return r.build(control,'VolatileLab/'+name)

def draw_states(r):return {key:stream.getstate() for key,stream in r.reactive.streams.items()}

@pytest.mark.parametrize('mode',['float','decimal'])
def test_property_dependencies_behavior_and_repeatable_restart(workspace,mode):
    r=workspace.runtime;r.environment['number_mode']=mode;r.restart();r.state()
    assert not r.diagnostics
    fixed=r.fx.evaluate('LeftPanel.Fixed');right=r.fx.evaluate('RightPanel.Fixed');jitter=r.fx.evaluate('LeftPanel.Jitter');list_roll=r.fx.evaluate('ListRoll');deck=serial(r.fx.evaluate('LeftPanel.Shuffled'))
    r.event('VolatileLab/Unrelated','OnSelect');r.state()
    assert (fixed,right,jitter,list_roll,deck)==(r.fx.evaluate('LeftPanel.Fixed'),r.fx.evaluate('RightPanel.Fixed'),r.fx.evaluate('LeftPanel.Jitter'),r.fx.evaluate('ListRoll'),serial(r.fx.evaluate('LeftPanel.Shuffled')))
    before=draw_states(r)
    r.event('VolatileLab/LeftPanel/Input','OnChange',45);r.state()
    assert fixed==r.fx.evaluate('LeftPanel.Fixed') and right==r.fx.evaluate('RightPanel.Fixed')
    assert 45<=r.fx.evaluate('LeftPanel.Jitter')<46 and jitter!=r.fx.evaluate('LeftPanel.Jitter')
    assert before[('formula','VolatileLab/RightPanel','Jitter')]==draw_states(r)[('formula','VolatileLab/RightPanel','Jitter')]
    r.event('VolatileLab/LeftPanel/DrawButton','OnSelect');r.event('VolatileLab/LeftPanel/DrawButton','OnSelect')
    assert r.collections['draws'][0]['Value']!=r.collections['draws'][1]['Value']
    r.event('VolatileLab/AddCard','OnSelect');r.state()
    assert r.fx.evaluate('ListRoll')!=list_roll and len(r.fx.evaluate('LeftPanel.Shuffled'))==4
    assert r.fx.evaluate('LeftPanel.Fixed')==fixed
    r.restart();r.state()
    assert r.fx.evaluate('LeftPanel.Fixed')==fixed and r.fx.evaluate('RightPanel.Fixed')==right


def test_readonly_inspector_and_isolated_workflow_do_not_consume_owner_random(workspace):
    from powerapps_sim.authoring import revision,data_revision
    w=workspace;r=w.runtime;r.state()
    before=(serial(w.ai.read_runtime()),revision(w.project.root),data_revision(r.store),draw_states(r))
    for _ in range(3):w.ai.read_runtime()
    scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario'])
    result=w.workflows.run(scenario,expected_revision=before[1])
    assert result['status']=='passed' and len(result['steps'])==14,result
    assert before==(serial(w.ai.read_runtime()),revision(w.project.root),data_revision(r.store),draw_states(r))


def test_named_rule_static_float_type_and_fresh_udf(workspace):
    r=workspace.runtime
    permanent=r.fx.evaluate('Permanent');r.execute('Set(counter,counter+1)',Context(r,behavior=True))
    assert permanent==r.fx.evaluate('Permanent')
    assert r.fx.evaluate('Jitter(10)')!=r.fx.evaluate('Jitter(10)')
    r.environment['number_mode']='decimal';r.invalidate()
    assert isinstance(r.fx.evaluate('Rand()'),float)
    assert isinstance(r.fx.evaluate('RandBetween(1,2)'),Decimal)
    assert isinstance(r.fx.evaluate('RandBetween(Float(1),2)'),float)
    assert r.binder.bind(r.fx.parse('Rand()'),BindScope()).kind=='Number'
    assert r.binder.bind(r.fx.parse('RandBetween(1,2)'),BindScope()).kind=='Decimal'


@pytest.mark.parametrize('formula',['Rand(1)','RandBetween(1)','RandBetween(1,2,3)','Shuffle()','Shuffle({ID:1})','RandBetween([1],2)'])
def test_invalid_arity_and_types_are_binding_errors(runtime,formula):
    runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(formula),BindScope())
    assert runtime.binder.errors
    with pytest.raises(FxError):runtime.fx.evaluate(formula)


def test_shuffle_preserves_aliases_duplicates_blank_and_lazy_errors(runtime):
    from powerapps_sim.tables import SourceRecord,OrderedRecord
    rows=[SourceRecord({'Card title':'a'},{'Card title':'Title'},'Cards'),SourceRecord({'Card title':'a'},{'Card title':'Title'},'Cards')]
    runtime.collections['deck']=rows;runtime.binder.collections['deck']=value_type(rows)
    before=deepcopy(serial(rows));result=runtime.fx.evaluate('Shuffle(deck)')
    assert result is not rows and serial(rows)==before and len(result)==2
    assert all(row.logical_names=={'Card title':'Title'} for row in result)
    assert runtime.fx.evaluate('First(Shuffle(deck)).Title')=='a'
    result=runtime.fx.evaluate('Shuffle(Table({Value:"healthy"},{Value:1/0}))')
    assert len(result)==2 and any(isinstance(row['Value'],FxError) for row in result)
    assert runtime.fx.evaluate('If(false,Shuffle(1/0),"kept")')=='kept'


def test_seed_validation_through_settings_and_workflows(post):
    from powerapps_sim.workflows import validate
    for seed in (True,1.5,'1',2**53):
        with pytest.raises(ValueError):validate({'format_version':1,'name':'seed','environment':{'random_seed':seed},'steps':[{'op':'assert','formula':'true','expect':True}]})
        result=post('/api/scenario',{'environment':{'user':{'Email':'fictional@example.invalid'},'random_seed':seed}})
        assert result.status_code==400


def test_global_collection_lazy_branches_and_transitive_properties(workspace):
    r=workspace.runtime
    r.globals.update(amount=2,enabled=False);r.binder.globals.update(amount=NUMBER,enabled=value_type(False))
    r.collections['local']=[{'Value':2}];r.binder.collections['local']=value_type(r.collections['local'])
    probe=expression_rule(r,'Rand()+If(enabled,CountRows(Cards),amount)+Sum(local,Value)')
    child=expression_rule(r,'Probe.Text & "!"','Child')
    first=probe.property('Text');child_first=child.property('Text');stream=draw_states(r)[('formula',probe.path,'Text')]
    r.store.patch('Cards',None,{'Title':'Unused branch'});r.invalidate()
    assert first==probe.property('Text') and child_first==child.property('Text')
    r.globals['amount']=2;r.invalidate()
    assert first==probe.property('Text') and stream==draw_states(r)[('formula',probe.path,'Text')]
    r.globals['amount']=3;r.invalidate()
    assert first!=probe.property('Text') and child_first!=child.property('Text')
    updated=probe.property('Text');r.collections['local'][0]['Value']=4;r.invalidate()
    assert updated!=probe.property('Text')
    r.globals['enabled']=True;r.invalidate();enabled=probe.property('Text')
    r.globals['amount']=99;r.invalidate();assert enabled==probe.property('Text')
    r.store.patch('Cards',None,{'Title':'Used branch'});r.invalidate();assert enabled!=probe.property('Text')


def test_errors_cycles_and_list_failure_isolation(workspace):
    r=workspace.runtime
    r.globals['amount']=0;r.binder.globals['amount']=NUMBER
    failure=expression_rule(r,'Rand()+1/amount')
    with pytest.raises(FxError) as caught:failure.property('Text')
    assert caught.value.kind=='Div0'
    states=draw_states(r);r.invalidate()
    with pytest.raises(FxError):failure.property('Text')
    assert states==draw_states(r)
    r.globals['amount']=2;r.invalidate();assert failure.property('Text')
    failure.control.properties['Text']='=Probe.Text+Rand()';r.invalidate()
    with pytest.raises(FxError) as caught:failure.property('Text')
    assert caught.value.kind=='Cycle'
    failure.control.properties['Text']='=IfError(CountRows(Cards),0)+Rand()';r.invalidate()
    healthy=failure.property('Text');stable=r.fx.evaluate('LeftPanel.Fixed')
    r.store.failures['Cards']='read';r.invalidate();failed=failure.property('Text')
    assert failed!=healthy and float(failed)<1 and r.fx.evaluate('LeftPanel.Fixed')==stable
    state=draw_states(r);r.invalidate();assert failure.property('Text')==failed and state==draw_states(r)
    r.store.failures.clear();r.invalidate();assert float(failure.property('Text'))>=3


def test_environment_app_and_clock_observed_inputs(workspace):
    r=workspace.runtime
    probe=expression_rule(r,'Text(App.Width+Rand()) & User().Email & Param("case") & Text(Now())')
    value=probe.property('Text');r.environment['parameters']['other']='ignored';r.invalidate()
    assert value==probe.property('Text')
    r.environment['parameters']['case']='fictional';r.invalidate();new=probe.property('Text');assert new!=value
    r.environment['user']['Email']='fictional@example.invalid';r.invalidate();value=probe.property('Text');assert value!=new
    r.viewport['width']+=1;r.invalidate();new=probe.property('Text');assert new!=value
    r.environment['clock']='2026-02-01T12:00:00+00:00';r.invalidate();assert new!=probe.property('Text')
    guid=expression_rule(r,'Text(GUID())','GuidProbe');first=guid.property('Text');r.invalidate();assert first==guid.property('Text')
    assert r.fx.evaluate('GUID()')!=r.fx.evaluate('GUID()')


def test_gallery_scope_changes_and_source_roundtrip(workspace):
    from io import BytesIO
    from zipfile import ZipFile
    w=workspace;r=w.runtime
    item_probe=expression_rule(r,'ThisItem.Value+Rand()');item_probe.item={'Value':3}
    first=item_probe.property('Text');r.invalidate();assert item_probe.property('Text')==first
    item_probe.item={'Value':4};r.invalidate();assert item_probe.property('Text')!=first
    before=w.ai.export_source()
    with ZipFile(BytesIO(w.project.export())) as archive:
        text=archive.read('Src/volatile.pa.yaml').decode()
    assert 'Rand(' in text and 'Shuffle(' in text and 'random_seed' not in text and 'ReactiveValues' not in text
    assert before==w.ai.export_source()


def test_decimal_extreme_intervals_no_overflow_and_blank_bounds(runtime):
    runtime.environment.update(number_mode='decimal',random_seed=7)
    for _ in range(10):
        value=runtime.fx.evaluate('RandBetween(-79228162514264337593543950335,79228162514264337593543950335)')
        assert isinstance(value,Decimal) and abs(value)<=Decimal('79228162514264337593543950335')
    assert runtime.fx.evaluate('RandBetween(Blank(),Blank())')==Decimal(0)
    assert runtime.fx.evaluate('RandBetween("4","4")')==Decimal(4)

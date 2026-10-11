"""Imperative app functions retain typed, lazy and isolated behavior semantics."""
import pytest
from powerapps_sim.binding import BindScope
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project, dump_yaml, load_yaml
from powerapps_sim.syntax import Parser, FxError


def make(tmp_path, formulas, startup='=Set(balance,20);Set(spent,0)', children=None):
    p=Project(tmp_path/'app')
    p.update_source('Src/app.pa.yaml',dump_yaml({'App':{'Properties':{'Formulas':'='+formulas,'OnStart':startup}},'Screens':{'Home':{'Children':children or []},'Other':{}}}))
    r=Runtime(p);r.restart()
    return r


@pytest.fixture
def actions(tmp_path):
    r=make(tmp_path, '''
        Spend(amount: Number): Void = {
          If(amount > balance, Error({Kind:ErrorKind.Validation,Message:"Insufficient balance"}),
            Set(balance,balance-amount);Set(spent,spent+amount));
        };
        Add(amount: Number): Number = { Set(balance,balance+amount); balance };
        Twice(amount: Number): Void = { Spend(amount); Spend(amount) };
        Ready = balance >= 0;
        Row := Type({N:Number});
        Pure(x:Number): Row = {N:x};
        Remember(x:Row): Void = {Collect(history,x)};
    ''')
    yield r
    r.close()


def run(r,s):return r.fx.evaluate(s,Context(r,behavior=True))


def test_parse_record_and_behavior_bodies_with_source_spans():
    source='A(x:Number):Void={/* record inside */ Set(value,{N:x});}; B(x:Number):Record={N:x}; C():Record={};'
    defs,errors=Parser(source).definitions()
    assert not errors and defs['A'].behavior and not defs['B'].behavior and not defs['C'].behavior
    assert source[defs['A'].body.start:defs['A'].body.end]=='Set(value,{N:x})'
    implicit,errors=Parser('Act():Void {Set(value,1);};').definitions()
    assert not errors and implicit['Act'].behavior
    broken,errors=Parser('Bad():Void={Set(x,);}; Healthy=42; Good():Void={Set(y,1)};').definitions()
    assert len(errors)==1 and set(broken)=={'Healthy','Good'}


def test_actions_lazy_branches_order_returns_and_reactive_properties(actions):
    r=actions; assert not r.diagnostics
    assert run(r,'Spend(3)') is None
    assert r.globals['balance']==17 and r.globals['spent']==3
    assert run(r,'Add(2)')==19
    run(r,'Twice(4)')
    assert r.globals['balance']==11 and r.globals['spent']==11
    assert r.fx.evaluate('Ready') is True
    assert r.fx.evaluate('Pure(5)')=={'N':5}
    assert r.analysis()['named']['Spend']['kind']=='behavior function'
    with pytest.raises(FxError,match='Insufficient'):run(r,'Spend(100)')
    assert r.globals['balance']==11 and r.globals['spent']==11


@pytest.mark.parametrize('expression',['Spend(1)','If(false,Spend(1),Blank())','With({x:1},Spend(x))'])
def test_value_properties_diagnose_actions_without_running_them(actions,expression):
    r=actions;r.binder.errors.clear()
    r.binder.bind(r.fx.parse(expression),BindScope(),('test','',0))
    assert any('behavior formula' in e.message for _,e in r.binder.errors)
    before=dict(r.globals)
    if 'false' not in expression:
        with pytest.raises(FxError,match='Behavior'):r.fx.evaluate(expression)
    else:assert r.fx.evaluate(expression) is None
    assert r.globals==before


@pytest.mark.parametrize('expression',['Spend("three")','Spend(1,2)','Remember({N:Color.Red})'])
def test_argument_validation_precedes_effects(actions,expression):
    before=dict(actions.globals)
    with pytest.raises(FxError):run(actions,expression)
    assert actions.globals==before and not actions.collections


def test_typed_alias_and_shadowed_caller_record_scopes(actions):
    r=actions
    run(r,'With({balance:999,spent:999},Spend(2))')
    assert r.globals['balance']==18 and r.globals['spent']==2
    run(r,'Remember(Pure(7))')
    assert r.collections['history']==[{'N':7}]


def test_void_propagates_errors_and_outer_chain_continues(actions):
    r=actions
    assert run(r,'IfError(Spend(100),Set(message,FirstError.Message))') is None
    assert r.globals['message']=='Insufficient balance'
    with pytest.raises(FxError,match='Insufficient'):run(r,'Spend(100);Set(after,true)')
    assert r.globals['after'] is True and r.globals['balance']==20


def test_failure_inside_block_continues_but_iferror_guards(tmp_path):
    r=make(tmp_path,'Bad():Void={Error({Kind:ErrorKind.Validation,Message:"bad"});Set(after,true)}; Safe():Void={IfError(Error({Kind:ErrorKind.Validation,Message:"bad"}),Set(recovered,true),Set(unreachable,true))};')
    try:
        with pytest.raises(FxError,match='bad'):run(r,'Bad()')
        assert r.globals['after'] is True
        run(r,'Safe()');assert r.globals['recovered'] is True and 'unreachable' not in r.globals
    finally:r.close()


@pytest.mark.parametrize('body',[
 'Bad():Void=Set(effect,1);',
 'Bad(x:Void):Void={Set(effect,1)};',
 'Bad(x:Number,x:Number):Void={Set(effect,1)};',
 'Bad():Number=Set(effect,1);',
])
def test_invalid_signatures_or_pure_side_effects_report_binding_errors(tmp_path,body):
    r=make(tmp_path,body)
    try:
        assert r.diagnostics
        if 'Void=Set' in body or 'x:Void' in body or 'x:Number,x:' in body:
            with pytest.raises(FxError):run(r,'Bad()' if 'x:' not in body else 'Bad(1)' if 'x:Void' in body else 'Bad(1,2)')
            assert 'effect' not in r.globals
        elif ':Number=Set' in body:
            with pytest.raises(FxError,match='Behavior'):run(r,'Bad()')
            assert 'effect' not in r.globals
    finally:r.close()


def test_forward_definition_startup_and_recursion(tmp_path):
    r=make(tmp_path,'Initialize():Void={Later(3)}; Later(x:Number):Void={Set(initial,x)}; Recurse():Void={Recurse()};',startup='=Initialize()')
    try:
        assert r.globals['initial']==3 and len(r.diagnostics)==1
        with pytest.raises(FxError,match='Recursive'):run(r,'Recurse()')
    finally:r.close()


def test_forall_restrictions_survive_function_call(tmp_path):
    r=make(tmp_path,'ClearRows():Void={Clear(history)}; AddRow(x:Number):Void={Collect(history,{N:x})};')
    try:
        run(r,'ForAll([1,2,3],AddRow(Value))')
        assert [row['N'] for row in r.collections['history']]==[1,2,3]
        with pytest.raises(FxError,match='ForAll'):run(r,'ForAll([1],ClearRows())')
        assert len(r.collections['history'])==3
    finally:r.close()


def test_behavior_return_record_and_navigation(tmp_path):
    r=make(tmp_path,'Go():Boolean={Navigate(Other)}; Data(x:Number):Record={Set(last,x);{N:x}};')
    try:
        assert run(r,'Data(4)')=={'N':4} and r.globals['last']==4
        assert run(r,'Go()') is True and r.active_screen=='Other'
    finally:r.close()


def test_component_callbacks_call_app_actions_without_leaking_local_state(tmp_path):
    from powerapps_sim.fixtures import actions_project
    r=Runtime(actions_project(tmp_path/'fixture'));r.restart()
    try:
        assert not r.diagnostics
        r.event('Actions/Left/Increase','OnSelect')
        assert r.fx.evaluate('Left.Total')==11 and r.fx.evaluate('Right.Total')==100
        assert r.globals['lastTotal']==11 and 'current' not in r.globals
        assert r.component_state['Actions/Left']['variables']['current']==11
        with pytest.raises(FxError,match='cannot access app function'):
            r.fx.evaluate('Remember(999,"blocked")',r.refs['Actions/Left'].context(True))
        assert r.globals['lastTotal']==11
        with pytest.raises(FxError,match='component function'):
            r.fx.evaluate('Remember(999,"blocked")',Context(r,behavior=True,function_pure=True))
        assert r.globals['lastTotal']==11
        r.binder.errors.clear()
        node=r.fx.parse('Remember(999,"blocked")')
        r.binder.bind(node,BindScope(behavior=True,component=r.refs['Actions/Left'].control),('test','',0))
        assert any('cannot access app function' in e.message for _,e in r.binder.errors)
    finally:r.close()


def test_clean_actions_workflow_is_repeatable_and_preserves_live_state(tmp_path):
    from copy import deepcopy
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision,data_revision
    from powerapps_sim.fixtures import actions_project
    w=Workspace(tmp_path,actions_project(tmp_path/'fixture').root)
    try:
        live=deepcopy(w.runtime.globals);before=data_revision(w.runtime.store)
        entry=w.workflows.catalog()['scenarios'][0]
        for _ in range(2):
            result=w.workflows.run(entry['scenario'],expected_revision=revision(w.project.root))
            assert result['status']=='passed',result['steps']
            assert len(result['steps'])==30 and not result['diagnostics']
            assert len(result['writes'])==1
        assert w.runtime.globals==live and data_revision(w.runtime.store)==before
    finally:w.runtime.close()


def test_mutually_recursive_actions_are_rejected_before_partial_writes(tmp_path):
    r=make(tmp_path,'One():Void={Set(partial,1);Two()};Two():Void={One()};')
    try:
        assert len(r.diagnostics)==2
        with pytest.raises(FxError,match='Recursive'):run(r,'One()')
        assert 'partial' not in r.globals
    finally:r.close()


def test_access_app_scope_action_writes_app_state_not_component_storage(tmp_path):
    from pathlib import Path
    from powerapps_sim.fixtures import actions_project
    source=load_yaml((Path(__file__).parents[1]/'powerapps_sim/examples/actions.pa.yaml').read_text())
    source['ComponentDefinitions']['Counter']['AccessAppScope']=True
    source['ComponentDefinitions']['Counter']['CustomProperties']['Add']['Default']='=Remember(amount,"direct")'
    p=actions_project(tmp_path/'app');p.update_source('Src/actions.pa.yaml',dump_yaml(source))
    r=Runtime(p);r.restart()
    try:
        r.fx.evaluate('Left.Add(9)',Context(r,behavior=True))
        assert r.globals['lastTotal']==9
        assert 'lastTotal' not in r.component_state.get('Actions/Left',{}).get('variables',{})
        assert not r.diagnostics
    finally:r.close()

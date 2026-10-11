"""Native component optionality is independent of default/schema values."""
from copy import deepcopy
import pytest
from powerapps_sim.source import Project,dump_yaml
from powerapps_sim.runtime import Runtime,serial
from powerapps_sim.fx import Context
from powerapps_sim.binding import BindScope
from powerapps_sim.syntax import FxError
from powerapps_sim.component_inspection import describe


def make(tmp_path,kind='OutputFunction',parameters=None):
    parameters=parameters if parameters is not None else [
        {'lhs':{'DataType':'Number','Default':'=100'}},
        {'rhs':{'DataType':'Number','IsOptional':True,'Default':'=1'}}]
    custom={'PropertyKind':kind,'ReturnType':'Number','Parameters':parameters}
    if kind=='InputFunction':custom['Default']='=lhs+rhs'
    if kind=='Event':custom['Default']='=Set(hostResult,lhs+rhs);lhs+rhs'
    body='=Set(localResult,lhs+rhs);Worker.Done(lhs+rhs);lhs+rhs' if kind=='Action' else '=lhs+rhs'
    src={'App':{'Properties':{'OnStart':'=Clear(history)'}},'ComponentDefinitions':{'Worker':{
        'DefinitionType':'CanvasComponent','CustomProperties':{'Call':custom,'Done':{'PropertyKind':'Event','ReturnType':'None','Parameters':[{'value':{'DataType':'Number','Default':'=100'}}]}},
        'Properties':{'Width':'=200','Height':'=100','Call':body}}},'Screens':{'Home':{'Children':[
            {name:{'Control':'CanvasComponent','ComponentName':'Worker','Properties':{'Done':f'=Collect(history,{{Panel:"{name}",Value:value}})'}}} for name in ('Left','Right')]}}}
    p=Project(tmp_path/'fixture');p.update_source('Src/optional.pa.yaml',dump_yaml(src));r=Runtime(p);r.restart();return r


@pytest.mark.parametrize('kind',['OutputFunction','InputFunction','Action','Event'])
@pytest.mark.parametrize('number,language',[('float','en-CA'),('decimal','fr-CA')])
def test_required_default_and_optional_default_native_contract(tmp_path,kind,number,language):
    r=make(tmp_path,kind);r.environment.update(number_mode=number,language=language);r.analyze()
    try:
        assert not r.diagnostics
        ctx=Context(r,behavior=kind in ('Action','Event'))
        with pytest.raises(FxError,match='1–2 arguments'):r.fx.evaluate('Left.Call()',ctx)
        assert not r.collections['history'] and not r.component_state
        assert r.fx.evaluate('Left.Call(7)',ctx)==8
        assert r.fx.evaluate('Right.Call(7,3)',ctx)==10
        assert r.fx.evaluate('Right.Call(7,Blank())',ctx)==7
        if kind=='Action':
            assert r.component_state['Home/Left']['variables']['localResult']==8
            assert r.component_state['Home/Right']['variables']['localResult']==7
            assert r.collections['history'][0]=={'Panel':'Left','Value':8}
        if kind=='Event':assert r.globals['hostResult']==7
        info=describe(r)['Home/Left']['properties']['Call']
        assert (info['minimum_arguments'],info['maximum_arguments'])==(1,2)
        assert info['parameters'][0]['required'] and not info['parameters'][0]['optional']
        assert info['parameters'][1]['optional'] and not info['parameters'][1]['required']
    finally:r.close()


@pytest.mark.parametrize('optional',[False,True,None])
def test_explicit_flags_and_omitted_blank_are_distinct(tmp_path,optional):
    spec={'DataType':'Number'}
    if optional is not None:spec['IsOptional']=optional
    r=make(tmp_path,parameters=[{'lhs':spec},{'rhs':{'DataType':'Number','Default':'=1','IsOptional':True}}])
    try:
        if optional is True:assert r.fx.evaluate('Left.Call()')==1
        else:
            with pytest.raises(FxError,match='1–2 arguments'):r.fx.evaluate('Left.Call()')
        assert r.fx.evaluate('Left.Call(Blank())')==1
    finally:r.close()


def test_required_schema_default_never_substitutes_an_argument(tmp_path):
    r=make(tmp_path,parameters=[{'lhs':{'DataType':'Record','Default':'={Amount:0,Label:""}'}},{'rhs':{'DataType':'Number','IsOptional':True,'Default':'=2'}}])
    try:
        ref=r.refs['Home/Left'];r.project.components['Worker'].properties['Call']='=lhs.Amount*rhs';r.invalidate();r.analyze()
        assert not r.diagnostics
        with pytest.raises(FxError):r.fx.evaluate('Left.Call()')
        assert r.fx.evaluate('Left.Call({Amount:"4",Label:7,Extra:true})')==8
        spec=r.project.components['Worker'].raw['CustomProperties']['Call']['Parameters'][0]['lhs']
        assert set(r.binder.parameter_type(spec).fields)=={'Amount','Label'}
    finally:r.close()


def test_optional_before_required_cannot_skip_a_positional_argument(tmp_path):
    r=make(tmp_path,parameters=[{'lhs':{'DataType':'Number','IsOptional':True,'Default':'=100'}},{'rhs':{'DataType':'Number','Default':'=1'}}])
    try:
        for formula in ('Left.Call()','Left.Call(7)'):
            with pytest.raises(FxError,match='2 arguments'):r.fx.evaluate(formula)
        assert r.fx.evaluate('Left.Call(7,3)')==10
    finally:r.close()


@pytest.mark.parametrize('flag',['true','=true',1,None,{},[]])
def test_invalid_optional_metadata_is_located_and_blocks_argument_effects(tmp_path,flag):
    r=make(tmp_path,parameters=[{'lhs':{'DataType':'Number','IsOptional':flag,'Default':'=100'}},{'rhs':{'DataType':'Number','Default':'=1'}}])
    try:
        assert any(d.get('expression_member')=='Worker.Call.lhs.IsOptional' and 'IsOptional:' in r.project.documents[d['source']].splitlines()[d['line']-1] for d in r.bind_diagnostics)
        before=deepcopy(serial([r.globals,r.collections,r.component_state]))
        with pytest.raises(FxError) as caught:r.fx.evaluate('Left.Call(If(true,Set(argumentEffect,true);1),2)',Context(r,behavior=True))
        assert caught.value.record()['Source']=='Home/Left.Call.lhs.IsOptional'
        assert before==serial([r.globals,r.collections,r.component_state])
    finally:r.close()


def test_wrong_arity_is_bound_and_stops_all_argument_effects(tmp_path):
    r=make(tmp_path,kind='Action')
    try:
        r.binder.errors.clear();r.binder.bind(r.fx.parse('Left.Call()'),BindScope(behavior=True),('test','',0))
        assert any('1–2 arguments' in e.message for _,e in r.binder.errors)
        with pytest.raises(FxError):r.fx.evaluate('Left.Call(If(true,Set(argumentEffect,true);1),2,3)',Context(r,behavior=True))
        assert 'argumentEffect' not in r.globals and not r.collections['history']
    finally:r.close()


def test_required_error_default_is_bypassed_with_explicit_value(tmp_path):
    r=make(tmp_path,parameters=[{'lhs':{'DataType':'Number','Default':'=1/0'}},{'rhs':{'DataType':'Number','IsOptional':True,'Default':'=1'}}])
    try:
        assert not r.diagnostics and r.fx.evaluate('Left.Call(7)')==8
        assert r.fx.evaluate('IfError(Left.Call(),FirstError.Kind)=ErrorKind.InvalidArgument')
    finally:r.close()


@pytest.mark.parametrize('number,language',[('float','en-CA'),('float','fr-CA'),('decimal','en-CA'),('decimal','fr-CA')])
def test_optional_public_workflow_preserves_owner_and_exports_native_flags(tmp_path,number,language):
    from powerapps_sim.fixtures import optional_parameters_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision,data_revision
    p=optional_parameters_project(tmp_path/'public');w=Workspace(tmp_path,p.root)
    try:
        w.runtime.state();before=deepcopy(w.ai.read_runtime());source=revision(p.root);data=data_revision(w.runtime.store);deps=w.ai.read_dependencies()
        scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);scenario['environment']={'number_mode':number,'language':language,'enum_mode':'strong'}
        result=w.workflows.run(scenario,expected_revision=source)
        assert result['status']=='passed' and len(result['steps'])==19 and not result['diagnostics'],result['steps']
        assert w.ai.read_runtime()==before and revision(p.root)==source and data_revision(w.runtime.store)==data and w.ai.read_dependencies()==deps
        assert 'IsOptional: true' in p.documents['Src/Components/Calculator.pa.yaml']
        entry=w.ai.read_runtime()['component_contracts']['Home/Left']['properties']['Calculate']
        assert entry['minimum_arguments']==1 and entry['parameters'][0]['default']=='=100' and entry['parameters'][0]['required']
    finally:w.runtime.close()

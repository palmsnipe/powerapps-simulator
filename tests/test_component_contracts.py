"""Component schemas, defaults and conversions without app-function restrictions."""
from decimal import Decimal
import pytest
from powerapps_sim.binding import BindScope
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project, dump_yaml
from powerapps_sim.syntax import FxError


def source():
    customs={
      'Seed':{'PropertyKind':'Data','PropertyDefinition':'Input','DataType':'Number','Default':'=1'},
      'Row':{'PropertyKind':'Input','DataType':'Record','Default':'={N:0,Active:false}'},
      'Rows':{'PropertyKind':'Input','DataType':'Table','Default':'=Table({N:0,Active:false})'},
      'Total':{'PropertyKind':'Output','DataType':'Number','Default':'=Coalesce(counter,Contract.Seed)'},
      'Flag':{'PropertyKind':'Output','DataType':'Boolean','Default':'="false"'},
      'Snapshot':{'PropertyKind':'Output','DataType':'Record','Default':'={N:Contract.Total,Active:Contract.Row.Active}'},
      'Times':{'PropertyKind':'Function','ReturnType':'Number','Parameters':[{'x':{'IsOptional':True,'DataType':'Number','Default':'="2.5"'}},{'factor':{'IsOptional':True,'DataType':'Number','Default':2}}],'Default':'=x*factor'},
      'AsNumber':{'PropertyKind':'Function','ReturnType':'Number','Parameters':[{'x':{'DataType':'Text'}}],'Default':'=x'},
      'Build':{'PropertyKind':'Function','ReturnType':'Record','Parameters':[{'x':{'DataType':'Number'}},{'flag':{'IsOptional':True,'DataType':'Boolean','Default':'=false'}}],'Default':'={N:x,Active:flag}'},
      'Echo':{'PropertyKind':'Function','ReturnType':'Record','Parameters':[{'row':{'IsOptional':True,'DataType':'Record','Default':'={N:0,Active:false}'}}],'Default':'=row'},
      'EchoRows':{'PropertyKind':'Function','ReturnType':'Table','Parameters':[{'rows':{'IsOptional':True,'DataType':'Table','Default':'=Table({N:0,Detail:{Enabled:false}})'}}],'Default':'=rows'},
      'LabelOnly':{'PropertyKind':'Function','ReturnType':'Text','Parameters':[{'row':{'IsOptional':True,'DataType':'Record','Default':'={Label:"",N:0}'}}],'Default':'=row.Label'},
      'ColorEcho':{'PropertyKind':'Function','ReturnType':'Color','Parameters':[{'color':{'IsOptional':True,'DataType':'Color','Default':'=Color.Red'}}],'Default':'=color'},
      'ColorFromDynamic':{'PropertyKind':'Function','ReturnType':'Color','Parameters':[{'value':{'DataType':'Dynamic'}}],'Default':'=value'},
      'Caption':{'PropertyKind':'InputFunction','ReturnType':'Text','Parameters':[{'n':{'DataType':'Number'}}],'Default':'=n'},
      'SetAmount':{'PropertyKind':'Action','ReturnType':'Number','Parameters':[{'amount':{'IsOptional':True,'DataType':'Number','Default':'="3"'}}],'Default':'=Set(counter,amount);Contract.Changed(amount);amount'},
      'Changed':{'PropertyKind':'Event','ReturnType':'None','Parameters':[{'amount':{'DataType':'Number'}}],'Default':'=Blank()'},
    }
    definition={'AccessAppScope':False,'CustomProperties':customs,'Properties':{'Width':'=300','Height':'=100','OnReset':'=Set(counter,Contract.Seed)'},'Children':[{'Add':{'Control':'ModernButton@1.0.0','Properties':{'Text':'=Contract.Caption(Contract.Total)','OnSelect':'=Contract.SetAmount("3")'}}}]}
    children=[{name:{'Control':'CanvasComponent','ComponentName':'Contract','Properties':{'Seed':f'="{seed}"','Row':'={N:"4",Active:"true",Extra:"kept"}','Rows':'={N:"5",Active:1,Extra:"kept"}','Changed':f'=Set({name}Changed,amount);Collect(history,{{Title:"{name}",Amount:amount}})','Caption':'=n'}}} for name,seed in [('Left',10),('Right',100)]]
    return {'App':{'Properties':{'OnStart':'=Set(host,42)','Formulas':'=Good=42; R:=Type({N:Number,Active:Boolean});'}},'ComponentDefinitions':{'Contract':definition},'Screens':{'Home':{'Children':children}}}


def make(tmp_path,src):
    p=Project(tmp_path/'contract');p.update_source('Src/contract.pa.yaml',dump_yaml(src));r=Runtime(p);r.restart();return r


@pytest.fixture
def contracts(tmp_path):
    r=make(tmp_path,source());assert not r.diagnostics
    yield r;r.close()


def assert_bound(r,expression,valid=True,behavior=False):
    r.binder.errors.clear();typ=r.binder.bind(r.fx.parse(expression),BindScope(behavior=behavior),('test','',0))
    assert bool(r.binder.errors) is not valid
    return typ


@pytest.mark.parametrize('expression,expected',[
 ('Left.Seed',10),('Left.Flag',False),('Left.Times()',5),('Left.Times("4")',8),
 ('Left.Times("4",true)',4),('Left.AsNumber("3.5")',3.5),
 ('Left.Times(Blank())',0),('Left.Times(4,Blank())',0),
 ('Left.Build("7","true")',{'N':7,'Active':True}),
 ('Left.Build(7)',{'N':7,'Active':False}),
 ('Left.Echo({N:"4",Active:1,Extra:"kept"})',{'N':4,'Active':True,'Extra':'kept'}),
 ('Left.Echo({Extra:1})',{'N':None,'Active':None,'Extra':1}),
 ('Left.EchoRows({N:"5",Detail:{Enabled:"true",Extra:1},Extra:2})',[{'N':5,'Detail':{'Enabled':True,'Extra':1},'Extra':2}]),
 ('Left.Row',{'N':4,'Active':True,'Extra':'kept'}),
 ('Left.Rows',[{'N':5,'Active':True,'Extra':'kept'}]),
 ('Left.Snapshot',{'N':10,'Active':True}),
 ('Left.ColorEcho()', '#ff0000'),('Left.ColorEcho(Color.Blue)','#0000ff'),
 ('Left.ColorFromDynamic(ParseJSON("""red"""))','red'),
 ('Left.Caption(true)','1'),
 ('Left.Echo(Blank())',None),('Left.EchoRows([])',[]),
])
def test_data_function_defaults_return_values_and_aggregate_coercions(contracts,expression,expected):
    assert_bound(contracts,expression)
    assert contracts.fx.evaluate(expression)==expected


def test_default_record_schema_stays_authoritative_under_instance_overrides(contracts):
    r=contracts
    row=r.binder.property_type(r.project.controls['Left'][0],'Row')
    assert set(row.fields)=={'N','Active'} and row.fields['N'].kind=='Number'
    typ=assert_bound(r,'Left.Build("7").N')
    assert typ.kind=='Number'
    _,errors=r.binder.bind(r.fx.parse('Left.Row.Extra'),BindScope(),('test','',0)),r.binder.errors
    assert any('Unknown field Extra' in e.message for _,e in errors)
    with pytest.raises(FxError,match='Unknown field Extra'):
        r.fx.evaluate('Left.Row.Extra')
    with pytest.raises(FxError,match='Unknown field Extra'):
        r.fx.evaluate('Left.Echo({Extra:1}).Extra')
    assert r.fx.evaluate('Good')==42


def test_failed_cells_are_lazy_and_do_not_change_peer_state(contracts):
    r=contracts
    assert r.fx.evaluate('Left.LabelOnly({Label:123,N:"wrong"})')=='123'
    row=r.fx.evaluate('Left.Echo({N:"wrong",Active:true})')
    assert isinstance(row['N'],FxError) and row['Active'] is True
    assert r.fx.evaluate('IfError(Left.Echo({N:"wrong"}).N,0)')==0
    assert r.fx.evaluate('Right.Total')==100
    assert r.fx.evaluate('Left.EchoRows(FirstN(Table({N:1,Detail:{Enabled:true}}),0))')==[]


def test_actions_events_typed_returns_isolation_and_reset(contracts):
    r=contracts;ctx=Context(r,behavior=True)
    assert r.fx.evaluate('Left.SetAmount("8")',ctx)==8
    assert r.fx.evaluate('Left.Total')==8 and r.fx.evaluate('Right.Total')==100
    assert r.globals['LeftChanged']==8 and 'RightChanged' not in r.globals
    assert r.collections['history']==[{'Title':'Left','Amount':8}]
    assert r.refs['Home/Left/Add'].property('Text')=='8'
    r.fx.evaluate('Reset(Left)',ctx)
    assert r.fx.evaluate('Left.Total')==10 and r.fx.evaluate('Right.Total')==100
    assert r.fx.evaluate('Right.SetAmount()',ctx)==3
    assert r.globals['RightChanged']==3
    assert r.component_state['Home/Right']['variables']['counter']==3


@pytest.mark.parametrize('expression',[
 'Left.Times("bad")','Left.AsNumber("bad")','Left.ColorFromDynamic(ParseJSON("{}"))',
])
def test_bindable_scalar_failure_is_catchable(contracts,expression):
    assert_bound(contracts,expression)
    with pytest.raises(FxError):contracts.fx.evaluate(expression)
    assert contracts.fx.evaluate(f'IfError({expression},Blank())') is None


@pytest.mark.parametrize('expression',[
 'Left.Times(Color.Red)','Left.ColorEcho("red")','Left.Echo({N:{Inner:1}})',
 'Left.Build(1,Date(2026,1,1))','Left.Times(1,2,3)',
])
def test_incompatible_types_or_arity_fail_before_argument_actions(contracts,expression):
    assert_bound(contracts,expression,False)
    with pytest.raises(FxError):contracts.fx.evaluate(expression)
    assert not contracts.collections


def test_invalid_static_argument_stops_other_argument_effects(contracts):
    r=contracts
    with pytest.raises(FxError):r.fx.evaluate('Left.Times(If(true,Set(argumentEffect,true);1),Color.Red)',Context(r,behavior=True))
    assert 'argumentEffect' not in r.globals
    with pytest.raises(FxError):r.fx.evaluate('Left.SetAmount("wrong")',Context(r,behavior=True))
    assert not r.collections and 'LeftChanged' not in r.globals


@pytest.mark.parametrize('default',['=host','=x','=Self.Seed','=Set(sideEffect,1)'])
def test_parameter_defaults_bind_purely_and_cannot_capture_values(tmp_path,default):
    src=source();src['ComponentDefinitions']['Contract']['CustomProperties']['Times']['Parameters'][0]['x']['Default']=default
    r=make(tmp_path,src)
    try:
        assert any(d['member']=='Contract.Times.x.Default' for d in r.diagnostics)
        with pytest.raises(FxError):r.fx.evaluate('Left.Times()')
        assert 'sideEffect' not in r.globals and r.fx.evaluate('Good')==42
    finally:r.close()


@pytest.mark.parametrize('spec',[
 {'DataType':'Missing'}, {'DataType':'Void'}, {'DataType':'Record','Default':'=2'},
])
def test_invalid_unused_signature_or_default_is_reported_and_cannot_run(tmp_path,spec):
    src=source();src['ComponentDefinitions']['Contract']['CustomProperties']['SetAmount']['Parameters']=[{'amount':spec}]
    r=make(tmp_path,src)
    try:
        assert r.diagnostics
        with pytest.raises(FxError):r.fx.evaluate('Left.SetAmount(1)',Context(r,behavior=True))
        assert not r.collections and 'LeftChanged' not in r.globals
        assert r.fx.evaluate('Right.Total')==100 and r.fx.evaluate('Good')==42
    finally:r.close()


@pytest.mark.parametrize('parameters',[
 [{'x':{'DataType':'Number'}},{'x':{'DataType':'Number'}}],
 'bad', [{'x':5}], [{'x':{'DataType':'Number'},'y':{'DataType':'Number'}}],
])
def test_malformed_parameter_metadata_is_isolated(tmp_path,parameters):
    src=source();src['ComponentDefinitions']['Contract']['CustomProperties']['Times']['Parameters']=parameters
    r=make(tmp_path,src)
    try:
        assert r.diagnostics
        with pytest.raises(FxError):r.fx.evaluate('Left.Times(1)')
        assert r.fx.evaluate('Good')==42 and r.fx.evaluate('Right.Total')==100
    finally:r.close()


def test_unknown_return_type_and_pure_side_effect_body_are_isolated(tmp_path):
    src=source();custom=src['ComponentDefinitions']['Contract']['CustomProperties']
    custom['Times']['ReturnType']='Missing'
    custom['AsNumber']['Default']='=Set(sideEffect,1)'
    r=make(tmp_path,src)
    try:
        assert r.diagnostics
        with pytest.raises(FxError):r.fx.evaluate('Left.Times(1)')
        with pytest.raises(FxError):r.fx.evaluate('Left.AsNumber("2")')
        assert 'sideEffect' not in r.globals and r.fx.evaluate('Good')==42
    finally:r.close()


def test_declared_alias_parameter_keeps_schema_instead_of_partial_default(tmp_path):
    src=source();custom=src['ComponentDefinitions']['Contract']['CustomProperties']['Echo']
    custom['Parameters']=[{'row':{'DataType':'R','Default':'={N:0}','IsOptional':True}}]
    r=make(tmp_path,src)
    try:
        assert not r.diagnostics
        assert set(r.binder.parameter_type(custom['Parameters'][0]['row']).fields)=={'N','Active'}
        assert r.fx.evaluate('Left.Echo()')=={'N':0,'Active':None}
    finally:r.close()


def test_decimal_and_french_conversion_are_consistent(contracts):
    r=contracts;r.environment.update(number_mode='decimal',language='fr-FR');r.analyze()
    assert r.fx.evaluate('Left.Times("1,25")')==Decimal('2.5')
    assert r.fx.evaluate('Left.Caption(1.25)')=='1,25'
    assert r.fx.evaluate('Left.Echo({N:"12,5",Active:"true"})')['N']==Decimal('12.5')


def test_clean_contracts_fixture_roundtrip_and_isolated_workflow(tmp_path):
    from copy import deepcopy
    from powerapps_sim.fixtures import contracts_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision, data_revision
    from powerapps_sim.source import load_yaml
    p=contracts_project(tmp_path/'fixture');w=Workspace(tmp_path,p.root)
    try:
        assert not w.runtime.diagnostics
        source=p.documents['Src/contracts.pa.yaml']
        assert load_yaml(dump_yaml(load_yaml(source)))==load_yaml(source)
        live=deepcopy(w.runtime.globals);data=data_revision(w.runtime.store)
        result=w.workflows.run(w.workflows.catalog()['scenarios'][0]['scenario'],expected_revision=revision(p.root))
        assert result['status']=='passed',result['steps']
        assert len(result['steps'])==37 and not result['diagnostics']
        assert len(result['writes'])==2
        assert w.runtime.globals==live and data_revision(w.runtime.store)==data
    finally:w.runtime.close()

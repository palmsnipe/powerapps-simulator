"""UDF coercions compared with Microsoft DType and UDF interpreter contracts."""
from decimal import Decimal
import pytest

from powerapps_sim.binding import BindScope
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime, serial
from powerapps_sim.source import Project, dump_yaml
from powerapps_sim.syntax import FxError


@pytest.fixture
def functions(tmp_path):
    p=Project(tmp_path/'coercion')
    p.update_source('Src/app.pa.yaml',dump_yaml({'App':{'Properties':{'Formulas':'''=
        N(x:Number):Number=x;
        F(x:Float):Float=x;
        S(x:Text):Text=x;
        B(x:Boolean):Boolean=x;
        D(x:Date):Date=x;
        DT(x:DateTime):DateTime=x;
        TM(x:Time):Time=x;
        G(x:GUID):GUID=x;
        C(x:Color):Color=x;
        U(x:Dynamic):Dynamic=x;
        R := Type({Label:Text,Amount:Number,Enabled:Boolean,When:Date,Nested:{Amount:Number},Values:[Number]});
        Rows := Type([R]);
        Echo(x:R):R=x;
        Many(x:Rows):Rows=x;
        LabelOnly(x:R):Text=x.Label;
        AmountOnly(x:R):Number=x.Amount;
        FromText(x:Text):Number=x;
        AsText(x:Number):Text=x;
        AsBool(x:Text):Boolean=x;
        ReturnRow():R={Label:42,Amount:"2.5",Enabled:1,Nested:{Amount:"3"},Values:{Value:"4"}};
        Remember(x:R):Void={Collect(history,x)};
        Save(a:Number,b:R):Void={Set(saved,b)};
        BadReturn():Number={Set(effect,true);"wrong"};
        Good=42;
    '''}},'Screens':{'Home':{}}}))
    r=Runtime(p);r.restart()
    assert not r.diagnostics
    yield r
    r.close()


def assert_bound(r, expression, valid=True):
    r.binder.errors.clear()
    r.binder.bind(r.fx.parse(expression),BindScope(),('test','',0))
    assert bool(r.binder.errors) is not valid


@pytest.mark.parametrize('expression,expected',[
    ('N("12.5")',12.5),('N(true)',1),('N(false)',0),('F("1.25")',1.25),
    ('S(12.5)','12.5'),('S(true)','true'),('S(false)','false'),
    ('B("TRUE")',True),('B("false")',False),('B(2)',True),('B(0)',False),
    ('FromText("3.5")',3.5),('AsText(12)','12'),('AsBool("true")',True),
    ('S(Date(2026,1,2))','1/2/2026'),('S(Time(13,30,0))','1:30 PM'),
    ('S(DateTime(2026,1,2,13,30,0))','1/2/2026 1:30 PM'),
    ('G("unvalidated identity")','unvalidated identity'),
    ('S(G("00000000-0000-0000-0000-000000000001"))','00000000-0000-0000-0000-000000000001'),
    ('C(Color.Red)','#ff0000'),
])
def test_scalar_parameter_and_return_coercions(functions,expression,expected):
    assert_bound(functions,expression)
    assert functions.fx.evaluate(expression)==expected


@pytest.mark.parametrize('expression,expected',[
    ('D("2026-01-02")','2026-01-02'),
    ('DT("2026-01-02T13:30:00Z")','2026-01-02T13:30:00+00:00'),
    ('TM("13:30:00")','13:30:00'),
    ('D(DateTime(2026,1,2,13,30,0))','2026-01-02'),
    ('D(Time(30,0,0))','1899-12-31'),
    ('DT(Time(30,0,0))','1899-12-31T06:00:00+00:00'),
    ('TM(DateTime(2026,1,2,13,30,0))','13:30:00'),
])
def test_temporal_parameter_coercions_and_hidden_day_offsets(functions,expression,expected):
    assert_bound(functions,expression)
    assert serial(functions.fx.evaluate(expression))==expected
    if expression.startswith('D('):
        assert functions.fx.evaluate(expression).value.hour==0
    if expression.startswith('TM(DateTime'):
        # Engine DateTimeToTime retains the full epoch offset, not just TimeOfDay.
        assert functions.fx.evaluate(expression).value.year==2026


@pytest.mark.parametrize('mode,day,halfday',[
    ('canvas-milliseconds',86400000,43200000),('powerfx-days',1,.5),
])
def test_numeric_temporal_conversion_respects_host_profile(functions,mode,day,halfday):
    r=functions;r.environment['date_numeric_mode']=mode
    assert r.fx.evaluate(f'Value(D({day}))')==day
    assert r.fx.evaluate(f'Value(TM({halfday}))')==halfday
    assert r.fx.evaluate('N(Time(12,0,0))')==halfday
    assert r.fx.evaluate('N(Date(1970,1,2))')==(86400000 if mode=='canvas-milliseconds' else 25570)


@pytest.mark.parametrize('expression',[
    'N(Color.Red)','B(Date(2026,1,1))','D(true)','S({X:1})',
    'C("red")','U("text")','Echo({Extra:1})','Many(Table({Label:"x",Extra:1}))',
    'Echo({Nested:{Extra:1}})','Many(FirstN(Table({Extra:1}),0))',
])
def test_unsupported_coercions_and_extra_fields_are_type_failures(functions,expression):
    assert_bound(functions,expression,False)
    with pytest.raises(FxError) as exc:functions.fx.evaluate(expression)
    assert exc.value.kind=='Type'
    assert functions.fx.evaluate('Good')==42


@pytest.mark.parametrize('expression',[
    'N("wrong")','B("maybe")','D("not a date")','TM("wrong")',
    'DT("wrong")','N(ParseJSON("{}"))','N(ParseJSON("[1]"))',
])
def test_bindable_invalid_values_fail_at_runtime_and_are_catchable(functions,expression):
    assert_bound(functions,expression)
    with pytest.raises(FxError) as exc:functions.fx.evaluate(expression)
    assert exc.value.end>exc.value.start
    assert functions.fx.evaluate(f'IfError({expression},Blank())') is None


@pytest.mark.parametrize('expression,expected',[
    ('N(ParseJSON("""12.5"""))',12.5),('B(ParseJSON("1"))',True),
    ('S(ParseJSON("1.2500"))','1.2500'),
    ('D(ParseJSON("""2026-01-02"""))','2026-01-02'),
    ('TM(ParseJSON("""13:30:00"""))','13:30:00'),
    ('C(ParseJSON("""red"""))','red'),
])
def test_dynamic_scalar_parameter_coercion(functions,expression,expected):
    assert_bound(functions,expression)
    assert serial(functions.fx.evaluate(expression))==expected


def test_nested_aggregate_coercions_partial_fields_and_record_to_table(functions):
    r=functions
    row=r.fx.evaluate('Echo({Label:12,Amount:"2.5",Enabled:"true",Nested:{Amount:"3"},Values:{Value:"4"}})')
    assert row=={'Label':'12','Amount':2.5,'Enabled':True,'When':None,'Nested':{'Amount':3},'Values':[{'Value':4}]}
    assert r.fx.evaluate('ReturnRow()')=={**row,'Label':'42'}
    assert r.fx.evaluate('Many({Amount:"5"})')==[{'Label':None,'Amount':5,'Enabled':None,'When':None,'Nested':None,'Values':None}]
    assert_bound(r,'Many({Amount:"5"})')
    assert r.fx.evaluate('Many(Blank())') is None
    assert r.fx.evaluate('Many([])')==[]
    assert r.fx.evaluate('Echo(Blank())') is None
    assert r.fx.evaluate('N(Blank())') is None
    assert r.fx.evaluate('S(Blank())') is None


def test_failed_cells_remain_lazy_across_functions_and_collections(functions):
    r=functions
    assert r.fx.evaluate('LabelOnly({Label:"healthy",Amount:"wrong"})')=='healthy'
    row=r.fx.evaluate('Echo({Label:"healthy",Amount:"wrong"})')
    assert isinstance(row['Amount'],FxError)
    assert r.fx.evaluate('IfError(AmountOnly({Amount:"wrong"}),0)')==0
    r.fx.evaluate('Remember({Label:"healthy",Amount:"wrong"})',Context(r,behavior=True))
    assert r.collections['history'][0]['Label']=='healthy'
    assert isinstance(r.collections['history'][0]['Amount'],FxError)
    with pytest.raises(FxError):r.fx.evaluate('Sum(history,Amount)')


def test_invalid_bound_argument_prevents_evaluating_other_arguments(functions):
    r=functions
    with pytest.raises(FxError):r.fx.evaluate('Save(If(true,Set(argumentEffect,true);1),{Extra:1})',Context(r,behavior=True))
    assert 'argumentEffect' not in r.globals and 'saved' not in r.globals
    # A valid signature with an invalid runtime return is not a transaction.
    with pytest.raises(FxError):r.fx.evaluate('BadReturn()',Context(r,behavior=True))
    assert r.globals['effect'] is True


def test_decimal_host_rebinds_and_localized_scalar_coercions(functions):
    r=functions;r.environment.update(number_mode='decimal',language='fr-FR');r.analyze()
    assert r.fx.evaluate('N("12,5")')==Decimal('12.5')
    assert r.fx.evaluate('S(12.5)')=='12,5'
    assert r.fx.evaluate('F("12,5")')==12.5
    assert r.fx.evaluate('D("02/01/2026")').isoformat()=='2026-01-02'
    exact=r.fx.evaluate('FromText("9007199254740993,25")')
    assert exact==Decimal('9007199254740993.25')
    assert r.fx.evaluate('AsText(N("9007199254740993,25"))')=='9007199254740993,25'


def test_clean_coercion_fixture_roundtrip_and_isolated_workflow(tmp_path):
    from copy import deepcopy
    from powerapps_sim.fixtures import coercion_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision, data_revision
    from powerapps_sim.source import load_yaml
    p=coercion_project(tmp_path/'fixture');w=Workspace(tmp_path,p.root)
    try:
        assert not w.runtime.diagnostics
        source=p.documents['Src/coercion.pa.yaml']
        assert load_yaml(dump_yaml(load_yaml(source)))==load_yaml(source)
        live=deepcopy(w.runtime.globals);data=data_revision(w.runtime.store)
        result=w.workflows.run(w.workflows.catalog()['scenarios'][0]['scenario'],expected_revision=revision(p.root))
        assert result['status']=='passed',result['steps']
        assert len(result['steps'])==33 and not result['diagnostics']
        assert len(result['writes'])==2
        assert w.runtime.globals==live and data_revision(w.runtime.store)==data
    finally:w.runtime.close()

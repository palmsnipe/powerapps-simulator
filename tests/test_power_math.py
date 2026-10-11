"""Math overloads, Float/Decimal contracts, table errors and scoped callbacks."""
from decimal import Decimal
import math
import pytest
from powerapps_sim.binding import BindScope,NUMBER,DECIMAL
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError
from powerapps_sim.conformance import equivalent

@pytest.mark.parametrize('expression,expected',[
 ('Sqrt(9)',3),('Exp(2)',math.exp(2)),('Ln(100)',math.log(100)),('Log(100)',2),('Log(64,2)',6),('Power(5,3)',125),
 ('Int(-4.3)',-5),('Trunc(-4.3)',-4),('Sin(Pi()/2)',1),('Cos(Pi())',-1),('Tan(Pi()/4)',1),('Cot(Pi()/4)',1),
 ('Acos(0.5)',math.pi/3),('Asin(1)',math.pi/2),('Atan(1)',math.pi/4),('Acot(-1)',3*math.pi/4),
 ('Atan2(0,1)',math.pi/2),('Atan2(-1,0)',math.pi),('Degrees(Pi())',180),('Radians(180)',math.pi),('Pi()',math.pi),
 ('Power(0,0)',1),('Sqrt(Blank())',0),('Exp(Blank())',1),('Int(true)',1),('Sqrt("9")',3),('Power("2","3")',8)])
def test_math_scalar_builtins_and_coercion(runtime,expression,expected):
 assert runtime.fx.evaluate(expression)==pytest.approx(expected,abs=1e-14)
 typ=runtime.binder.bind(runtime.fx.parse(expression),BindScope())
 assert typ==NUMBER and not runtime.binder.errors

@pytest.mark.parametrize('expression,kind',[
 ('Sqrt(-1)','Numeric'),('Ln(0)','Numeric'),('Log(-1)','Numeric'),('Log(0,1)','Div0'),('Log(64,0)','Numeric'),
 ('Power(0,-1)','Div0'),('0^-1','Div0'),('Power(-2,0.5)','Numeric'),('(-2)^0.5','Numeric'),('Exp(1000)','Numeric'),
 ('Power(1e200,2)','Numeric'),('Cot(0)','Div0'),('Asin(2)','Numeric'),('Acos(-2)','Numeric'),('Atan2(0,0)','Div0'),
 ('Sqrt("bad")','InvalidArgument'),('Log(1/0)','Div0')])
def test_math_failures_preserve_kind_and_source_span(runtime,expression,kind):
 with pytest.raises(FxError) as error:runtime.fx.evaluate(expression)
 assert error.value.kind==kind and error.value.end>error.value.start
 assert runtime.fx.evaluate(f'IfError({expression},FirstError.Kind)')=={'Numeric':24,'Div0':13,'InvalidArgument':25}[kind]
 assert runtime.fx.evaluate(f'IsBlankOrError({expression})') is True

@pytest.mark.parametrize('function',['Sqrt','Exp','Ln','Log','Int','Trunc','Sin','Cos','Tan','Cot','Acos','Asin','Atan','Acot','Degrees','Radians'])
def test_single_column_table_math_output_types_and_empty_typed_tables(runtime,function):
 expression=f'{function}(ShowColumns(Table({{Amount:1,Name:"A"}},{{Amount:0,Name:"B"}}),Amount))'
 result=runtime.fx.evaluate(expression)
 assert len(result)==2 and all(set(row)=={'Value'} for row in result)
 typ=runtime.binder.bind(runtime.fx.parse(expression),BindScope());assert typ.row.fields['Value']==NUMBER
 assert runtime.fx.evaluate(f'{function}(FirstN([1],0))')==[]
 assert runtime.fx.evaluate(f'{function}(If(false,[1]))') is None
 assert not runtime.binder.errors

def test_binary_math_broadcast_longest_table_and_unchanged_source(runtime):
 ctx=Context(runtime,behavior=True);runtime.fx.evaluate('ClearCollect(source,Table({N:2},{N:3},{N:4}))',ctx)
 assert runtime.fx.evaluate('Power(source,2)')==[{'Value':4},{'Value':9},{'Value':16}]
 assert runtime.fx.evaluate('Power(2,[1,2,3])')==[{'Value':2},{'Value':4},{'Value':8}]
 result=runtime.fx.evaluate('Power(source,[3])');assert result[0]=={'Value':8}
 assert [row['Value'].kind for row in result[1:]]==['NotApplicable','NotApplicable']
 result=runtime.fx.evaluate('Log([1,8],2)');assert result==[{'Value':0},{'Value':3}]
 assert runtime.collections['source']==[{'N':2},{'N':3},{'N':4}]
 assert runtime.fx.evaluate('Power(FirstN([1],0),1/0)')==[]

def test_embedded_error_rows_blank_rows_and_cells_remain_distinct(runtime):
 result=runtime.fx.evaluate('Sqrt(Table({N:4},{N:-1},{N:1/0},If(false,{N:1}),If(1/0<0,{N:1})))')
 assert result[0]=={'Value':2} and result[1]['Value'].kind=='Numeric' and result[2]['Value'].kind=='Div0'
 assert result[3] is None and result[4].kind=='Div0'
 assert runtime.fx.evaluate('CountRows(Sqrt(Table({N:4},{N:-1})))')==2
 assert runtime.fx.evaluate('ForAll(Sqrt([4,-1,9]),IfError(Value,-1))')==[{'Value':2},{'Value':-1},{'Value':3}]
 assert runtime.fx.evaluate('If(false,Sqrt(-1),5)')==5
 assert runtime.fx.evaluate('IfError(Power("bad","also bad"),CountRows(AllErrors))')==2

@pytest.mark.parametrize('expression',['Sqrt()','Power(2)','Pi(1)','Atan2([1],[2])','Trunc(1.2,1)','Sqrt([])','Cos([{A:1,B:2}])','Int({N:3})'])
def test_invalid_signatures_report_binding_errors(runtime,expression):
 runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(expression),BindScope())
 assert runtime.binder.errors and all(error.end>error.start for _,error in runtime.binder.errors)

def test_decimal_host_retains_integral_precision_and_promotes_math_to_float(runtime):
 runtime.environment['number_mode']='decimal';runtime.invalidate()
 n='1000000000000000000000001.1'
 assert runtime.fx.evaluate(f'Int({n})')==Decimal('1000000000000000000000001')
 assert runtime.fx.evaluate(f'Trunc(-{n})')==Decimal('-1000000000000000000000001')
 for function in ('Sqrt','Exp','Ln','Log','Sin','Cos','Tan','Acos','Asin','Atan','Acot','Degrees','Radians'):
  expression=f'{function}(1)';value=runtime.fx.evaluate(expression)
  assert isinstance(value,float) and runtime.binder.bind(runtime.fx.parse(expression),BindScope())==NUMBER
 assert runtime.binder.bind(runtime.fx.parse(f'Int({n})'),BindScope())==DECIMAL
 assert runtime.binder.bind(runtime.fx.parse('Int(Float(1.2))'),BindScope())==NUMBER
 assert isinstance(runtime.fx.evaluate('Int(Float(1.2))'),float)
 assert runtime.binder.bind(runtime.fx.parse('Sqrt([4,9])'),BindScope()).row.fields['Value']==NUMBER
 assert isinstance(runtime.fx.evaluate('Power(2,3)'),float) and isinstance(runtime.fx.evaluate('Pi()'),float)
 assert not runtime.binder.errors

def test_locale_temporal_and_dynamic_numeric_coercion(runtime):
 runtime.environment['language']='fr-CA';runtime.invalidate()
 assert runtime.fx.evaluate('Sqrt("6,25")')==2.5
 assert runtime.fx.evaluate('Sqrt(ParseJSON("9"))')==3
 runtime.environment['date_numeric_mode']='powerfx-days';runtime.invalidate()
 assert runtime.fx.evaluate('Sqrt(Date(1900,1,3))')==2
 assert runtime.fx.evaluate('Int(Time(12,0,0))')==0


def test_power_operator_and_function_share_results_and_errors(runtime):
 for base,exp in [(0,0),(0,-1),(-3,0.5),(2,-4),(1e200,2),(2,8)]:
  formula=lambda b:f'IfError({b},FirstError.Kind)'
  assert runtime.fx.evaluate(formula(f'Power({base},{exp})'))==runtime.fx.evaluate(formula(f'({base})^({exp})'))


def test_reference_numeric_tolerance_is_explicit_and_preserves_types_errors():
 assert not equivalent(1.000001,1)
 assert equivalent(1.000001,1,True)
 assert not equivalent(True,1,True) and not equivalent(None,0,True)
 assert not equivalent({'$error':{'Kind':24.000001}},{'$error':{'Kind':24}},True)
 assert not equivalent(float('inf'),1,True)
 assert not equivalent(1.0001,1,True)

@pytest.fixture
def math_app(tmp_path):
 from powerapps_sim.fixtures import math_project
 from powerapps_sim.runtime import Runtime
 r=Runtime(math_project(tmp_path/'p'));r.restart();r.state();assert not r.diagnostics
 yield r
 r.close()

def test_component_math_function_reactivity_callbacks_and_reset(math_app):
 r=math_app
 assert r.fx.evaluate('LeftPanel.Current.Estimate')==8 and r.fx.evaluate('RightPanel.Current.Estimate')==15
 r.event('Math/LeftPanel/Area','OnChange',36)
 assert r.fx.evaluate('LeftPanel.Current.Estimate')==12 and r.fx.evaluate('RightPanel.Current.Estimate')==15
 assert r.collections['history'][0]['Area']==36 and r.collections['history'][0]['Radius']==3.3851
 r.event('Math/LeftPanel/Angle','OnInput',90);assert r.fx.evaluate('LeftPanel.Current.X')==0 and len(r.collections['history'])==1
 r.event('Math/LeftPanel/Angle','OnChange',90);assert len(r.collections['history'])==2
 r.event('Math/ResetLeft','OnSelect');assert r.fx.evaluate('LeftPanel.Current.Angle')==30 and r.fx.evaluate('LeftPanel.Current.Area')==16
 assert r.component_state['Math/LeftPanel']['collections']['captured']==[] and not r.diagnostics

def test_live_table_projection_retains_numeric_types_and_error_cells(math_app):
 r=math_app;r.event('Math/BuildTable','OnSelect');r.event('Math/CaptureErrors','OnSelect')
 assert len(r.collections['results'])==13 and len(r.collections['results'][0])==20
 assert r.collections['results'][0]['Cot'] is None and r.collections['results'][3]['Y']==50
 assert r.collections['errorCells'][1]['Root'].kind=='Numeric'
 assert r.fx.evaluate('RootTotal')==5 and r.fx.evaluate('CountRows(errorCells)')==4
 assert r.binder.collections['results'].row.fields['Exponential']==NUMBER
 assert not r.diagnostics

def test_math_component_values_persist_and_write_failure_preserves_data(math_app):
 r=math_app;r.event('Math/LeftPanel/Area','OnChange',36)
 r.store.failures['Measurements']='write';r.event('Math/SaveLeft','OnSelect');assert r.globals['status']=='Save failed'
 assert r.store.rows('Measurements')[0]['Area']==16
 r.store.failures.clear();r.event('Math/SaveLeft','OnSelect')
 assert r.globals['status']=='Saved' and r.store.rows('Measurements')[0]['Area']==36 and r.store.rows('Measurements')[0]['Estimate']==12
 assert r.fx.evaluate('LeftPanel.Current.Area')==36 and not r.diagnostics

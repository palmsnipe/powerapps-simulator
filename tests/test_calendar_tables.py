"""Canvas documented week-table overloads, schema, errors and component contracts."""
from decimal import Decimal
import pytest
from powerapps_sim.binding import BindScope
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError

@pytest.mark.parametrize('name,expected',[
 ('WeekNum',[1,2,53]),('ISOWeekNum',[53,1,52])])
@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('language',['en-US','fr-CA'])
def test_week_table_dates_and_host_result_types(runtime,name,expected,mode,language):
 runtime.environment.update(number_mode=mode,language=language);runtime.analyze()
 f=f'{name}([Date(2021,1,1),Date(2021,1,4),Date(2021,12,31)])'
 result=runtime.fx.evaluate(f);assert result==[{'Value':x} for x in expected]
 assert all(isinstance(row['Value'],Decimal)==(mode=='decimal') for row in result)
 typ=runtime.binder.bind(runtime.fx.parse(f),BindScope());assert typ.kind=='Table'
 assert typ.row.fields['Value'].kind==('Decimal' if mode=='decimal' else 'Number')

@pytest.mark.parametrize('formula,expected',[
 ('WeekNum(Table({Day:Date(2021,1,3)},{Day:Date(2021,1,4)}),StartOfWeek.Monday)',[1,2]),
 ('ISOWeekNum(ShowColumns(Table({Day:Date(2021,1,1),Unused:1}),Day))',[53]),
 ('WeekNum([Date(2021,1,1),Blank()],Blank())',[1,52]),
 ('ISOWeekNum([Date(2021,1,1),Blank()])',[53,52]),
 ('ISOWeekNum(["2021-01-01","2021-01-04"])',[53,1]),
 ('WeekNum([1,5],"12")',[53,2])])
def test_custom_columns_coercion_and_blank_cells(runtime,formula,expected):
 runtime.environment['date_numeric_mode']='powerfx-days';runtime.invalidate()
 assert runtime.fx.evaluate(formula)==[{'Value':x} for x in expected]

@pytest.mark.parametrize('name',['WeekNum','ISOWeekNum'])
@pytest.mark.parametrize('source',['[]','Table()','[{A:1,B:2}]','FirstN([{A:1,B:2}],0)','[{Day:{X:1}}]'])
def test_date_table_schema_is_checked_before_evaluation(runtime,name,source):
 formula=f'{name}({source})';runtime.binder.errors.clear()
 runtime.binder.bind(runtime.fx.parse(formula),BindScope());assert runtime.binder.errors
 with pytest.raises(FxError) as error:runtime.fx.evaluate(formula)
 assert error.value.kind=='Type' and error.value.end>error.value.start

@pytest.mark.parametrize('name',['WeekNum','ISOWeekNum'])
def test_typed_empty_blank_error_table_and_source_rows_are_distinct(runtime,name):
 assert runtime.fx.evaluate(f'{name}(FirstN([Date(2021,1,1)],0))')==[]
 assert runtime.fx.evaluate(f'{name}(If(false,[Date(2021,1,1)]))') is None
 with pytest.raises(FxError) as error:runtime.fx.evaluate(f'{name}(If(1/0<1,[Date(2021,1,1)]))')
 assert error.value.kind=='Div0'
 runtime.fx.evaluate('Set(dates,Table({D:Date(2021,1,1)}))',Context(runtime,behavior=True))
 day=runtime.globals['dates'][0]
 runtime.globals['dates']=[day,None,FxError('Fictional row error','Network'),{'D':None}]
 result=runtime.fx.evaluate(f'{name}(dates)')
 assert result[0]['Value']==(1 if name=='WeekNum' else 53)
 assert result[1] is None and result[2].kind=='Network'
 assert result[3]['Value']==52
 assert runtime.globals['dates'][0] is day and 'D' in day and 'Value' not in day

@pytest.mark.parametrize('formula',[
 'WeekNum(Date(2021,1,1),[1,2])','WeekNum([Date(2021,1,1)],[1,2])',
 'WeekNum(FirstN([Date(2021,1,1)],0),FirstN([1],0))'])
def test_start_of_week_is_a_scalar_parameter(runtime,formula):
 runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(formula),BindScope());assert runtime.binder.errors
 with pytest.raises(FxError) as error:runtime.fx.evaluate(formula)
 assert error.value.kind=='Type'

def test_bad_date_cells_invalid_codes_and_scalar_errors_do_not_abort_healthy_rows(runtime):
 result=runtime.fx.evaluate('ISOWeekNum([Date(2021,1,1),"not a date",1/0,Date(2021,1,4)])')
 assert result[0]=={'Value':53} and result[3]=={'Value':1}
 assert result[1]['Value'].kind=='InvalidArgument' and result[2]['Value'].kind=='Div0'
 assert runtime.fx.evaluate('ForAll(ISOWeekNum([Date(2021,1,1),"bad"]),IfError(Value,-FirstError.Kind))')==[{'Value':53},{'Value':-25}]
 assert all(row['Value'].kind=='Div0' for row in runtime.fx.evaluate('WeekNum([Date(2021,1,1),Date(2021,1,4)],1/0)'))
 assert runtime.fx.evaluate('WeekNum(FirstN([Date(2021,1,1)],0),1/0)')==[]
 assert runtime.fx.evaluate('WeekNum(If(false,[Date(2021,1,1)]),1/0)') is None
 assert all(row['Value'].kind=='InvalidArgument' for row in runtime.fx.evaluate('WeekNum([Date(2021,1,1),Date(2021,1,4)],StartOfWeek.MondayZero)'))

@pytest.mark.parametrize('kind',['legacy','strong'])
def test_table_returning_typed_functions_and_nested_record_results(runtime,kind):
 runtime.environment.update(enum_mode=kind,number_mode='decimal');runtime.analyze()
 runtime.fx.set_definitions('Days := Type([{D:Date}]); Weeks := Type([{Value:Number}]); Calendar(days:Days):Weeks = ISOWeekNum(days);')
 assert runtime.fx.evaluate('Calendar([{D:Date(2021,1,1)},{D:Date(2021,1,4)}])')==[{'Value':Decimal(53)},{'Value':Decimal(1)}]
 assert runtime.fx.evaluate('Calendar([])')==[]
 assert runtime.fx.evaluate('Calendar(If(false,[{D:Date(2021,1,1)}]))') is None
 assert runtime.fx.evaluate('First({Weeks:Calendar([{D:Date(2021,1,1)}])}.Weeks).Value')==53

@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('mode',['float','decimal'])
def test_calendar_table_component_workflows_and_nested_saved_owner(tmp_path,language,mode):
 from powerapps_sim.fixtures import calendar_tables_project
 from powerapps_sim.web import Workspace
 from powerapps_sim.authoring import revision,data_revision
 p=calendar_tables_project(tmp_path/'project');w=Workspace(tmp_path,p.root,start=False)
 try:
  before=(revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime())
  scenario=w.workflows.catalog()['scenarios'][0]['scenario']
  if mode == 'decimal':
   for step in scenario['steps']:
    if type(step.get('expect')) is int and ('LookUp(' not in step.get('formula', '') or step['formula'].startswith('CountRows(')):
     step['expect'] = {'$decimal': str(step['expect'])}
  result=w.workflows.run({**scenario,'environment':{'language':language,'enum_mode':'strong','number_mode':mode}},expected_revision=before[0])
  assert result['status']=='passed',[s for s in result['steps'] if s['status']!='passed']
  assert len(result['steps'])==49 and not result['diagnostics']
  assert len(result['collections']['results'][0])==20
  row=result['types']['collections']['history']['row']['fields']
  assert row['Weeks']['kind']=='Table' and row['Weeks']['row']['fields']['Value']['kind']==('Decimal' if mode=='decimal' else 'Number')
  assert (revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime())==before
 finally:w.runtime.close()

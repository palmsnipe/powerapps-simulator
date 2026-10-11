"""Calendar contracts, reference examples, component events and saved dates."""
from decimal import Decimal
import pytest
from powerapps_sim.binding import BindScope
from powerapps_sim.syntax import FxError

# Literal results from Microsoft's WeekNum/ISOWeekNum documentation.
@pytest.mark.parametrize('month,day,week,iso,wednesday',[
 (1,1,1,53,1),(1,2,1,53,1),(1,3,2,53,1),(1,4,2,1,1),
 (1,5,2,1,1),(1,6,2,1,2),(1,7,2,1,2),
 (12,25,52,51,52),(12,26,53,51,52),(12,27,53,52,52),
 (12,28,53,52,52),(12,29,53,52,53),(12,30,53,52,53),(12,31,53,52,53)])
def test_microsoft_calendar_examples(runtime,month,day,week,iso,wednesday):
 date=f'Date(2021,{month},{day})'
 assert runtime.fx.evaluate(f'WeekNum({date})')==week
 assert runtime.fx.evaluate(f'ISOWeekNum({date})')==iso
 assert runtime.fx.evaluate(f'WeekNum({date},StartOfWeek.Wednesday)')==wednesday

@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('profile',['legacy','strong'])
def test_result_types_blank_rules_and_extreme_years(runtime,mode,profile):
 runtime.environment.update(number_mode=mode,enum_mode=profile);runtime.analyze()
 for f,v in [('Weekday(Blank())',7),('WeekNum(Blank())',52),('ISOWeekNum(Blank())',52),
             ('WeekNum(Blank(),Blank())',52),('WeekNum(Date(2000,12,31))',54),
             ('ISOWeekNum(Date(9999,12,31))',52),('ISOWeekNum(DateValue("0001-01-01"))',1)]:
  value=runtime.fx.evaluate(f);assert value==v
  assert isinstance(value,Decimal)==(mode=='decimal')
  assert runtime.binder.bind(runtime.fx.parse(f),BindScope()).kind==('Decimal' if mode=='decimal' else 'Number')
 with pytest.raises(FxError) as error:runtime.fx.evaluate('Weekday(Blank(),Blank())')
 assert error.value.kind=='InvalidArgument'

@pytest.mark.parametrize('formula',[
 'Weekday(Date(2021,1,1),0)','Weekday(Date(2021,1,1),"abc")',
 'WeekNum(Date(2021,1,1),12.9)','WeekNum(Date(2021,1,1),21)',
 'WeekNum(Date(2021,1,1),StartOfWeek.MondayZero)'])
def test_invalid_start_codes_remain_catchable(runtime,formula):
 with pytest.raises(FxError) as error:runtime.fx.evaluate(formula)
 assert error.value.kind=='InvalidArgument'
 assert runtime.fx.evaluate('IfError('+formula+',FirstError.Kind)')==25
 assert runtime.fx.evaluate('If(false,'+formula+',9)')==9

@pytest.mark.parametrize('formula',[
 'Weekday(Date(2021,1,1),2)','WeekNum(Date(2021,1,1),ErrorKind.Div0)',
 'Weekday(Date(2021,1,1),"2")','WeekNum(Date(2021,1,1),true)',
 'WeekNum([{Day:Date(2021,1,1),Extra:1}])','ISOWeekNum({Day:Date(2021,1,1)})'])
def test_scalar_schema_and_strong_enum_checks(runtime,formula):
 runtime.environment['enum_mode']='strong';runtime.analyze()
 runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(formula),BindScope())
 assert runtime.binder.errors and all(e.kind=='Type' for _,e in runtime.binder.errors)
 with pytest.raises(FxError) as error:runtime.fx.evaluate(formula)
 assert error.value.kind=='Type'

@pytest.mark.parametrize('formula,value',[
 ('If(1,7,1/0)',7),('If(0,1/0,9)',9),('If(-2,7)',7),
 ('If(Decimal(0),1/0,9)',9),('IfError(WeekNum(If(1/0,Date(2021,1,1))),FirstError.Kind)',13)])
def test_numeric_if_conditions_are_lazy_and_keep_errors(runtime,formula,value):
 runtime.environment['number_mode']='decimal';runtime.analyze();runtime.binder.errors.clear()
 runtime.binder.bind(runtime.fx.parse(formula),BindScope());assert not runtime.binder.errors
 assert runtime.fx.evaluate(formula)==value

@pytest.mark.parametrize('language',['en-US','fr-CA'])
def test_component_dates_callbacks_reset_workflow_and_saved_owner(tmp_path,language):
 from powerapps_sim.fixtures import calendar_project
 from powerapps_sim.web import Workspace
 from powerapps_sim.authoring import revision,data_revision
 p=calendar_project(tmp_path/'project');w=Workspace(tmp_path,p.root,start=False)
 try:
  before=(revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime())
  scenario=w.workflows.catalog()['scenarios'][0]['scenario']
  result=w.workflows.run({**scenario,'environment':{'language':language,'enum_mode':'strong'}},expected_revision=before[0])
  assert result['status']=='passed',result
  assert len(result['steps'])==35 and not result['diagnostics']
  assert result['types']['collections']['history']['row']['fields']['Day']['kind']=='Date'
  assert (revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime())==before
 finally:w.runtime.close()

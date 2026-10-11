"""UTF-16 text contracts, positional table arguments and scoped reactive values."""
import pytest
from powerapps_sim.binding import BindScope,TEXT
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError

@pytest.mark.parametrize('formula,expected',[
 ('Left("🌲 river",2)','🌲'),('Right("river 🌲",2)','🌲'),('Mid("🌲river",3,3)','riv'),
 ('Len(Left("🌲",1))',1),('Left("🌲",1)','\ud83c'),('Right("🌲",1)','\udf32'),
 ('Concatenate(Left("🌲",1),Right("🌲",1))','🌲'),
 ('Replace("🌲river",3,3,"lake")','🌲lakeer'),('Replace("abc",100,20,"x")','abcx'),
 ('Replace("abc",2,0,"x")','axbc'),('Replace("abc",2.9,1.2,"x")','axc'),
 ('Substitute("aaabbb","aa","x")','xabbb'),('Substitute("aaa","a","aa",2)','aaaa'),
 ('Substitute("aaa","a","b",100000000000000000000)','aaa'),('Substitute("abc","","x")','abc'),
 ('Substitute("abc",Blank(),"x",2)','abc'),('Substitute("HelloHello","He","Je",2.7)','HelloJello'),
 ('Left("abc","")',''),('Right("abc",Blank())',''),('Mid("abc",2)','bc'),
 ('Left("abc",1e28)','abc'),('Left("abc",-0.5)',''),('Left(true,2)','tr'),
 ('Concatenate(12.5,true,Blank())','12.5true')])
def test_scalar_positions_substitution_coercions_and_utf16(runtime,formula,expected):
 assert runtime.fx.evaluate(formula)==expected

@pytest.mark.parametrize('formula,expected',[
 ('Left(["alpha","beta"],2)',['al','be']),('Right("alpha",[1,3])',['a','pha']),
 ('Mid(["alpha","beta"],[2,3],[2,1])',['lp','t']),('Replace(["alpha","beta"],2,2,"!")',['a!ha','b!a']),
 ('Replace("alpha",[1,3],1,["A","P"])',['Alpha','alPha']),
 ('Substitute("aaa","a",["X","Y"],[1,2])',['Xaa','aYa']),
 ('Concatenate("Name: ",["alpha","beta"]," / ",[1,true])',['Name: alpha / 1','Name: beta / 1'])])
def test_table_broadcast_pairing_and_text_result_binding(runtime,formula,expected):
 assert runtime.fx.evaluate(formula)==[{'Value':value} for value in expected]
 typ=runtime.binder.bind(runtime.fx.parse(formula),BindScope())
 assert typ.row.fields['Value']==TEXT and not runtime.binder.errors

@pytest.mark.parametrize('formula',[
 'Mid("abc",0)','Mid("abc",2,-1)','Replace("abc",0,1,"x")',
 'Replace("abc",1,-1,"x")','Substitute("abc","a","b",0)',
 'Substitute("abc","a","b",Blank())','Left("abc","bad")'])
def test_invalid_positions_remain_catchable_errors_with_locations(runtime,formula):
 with pytest.raises(FxError) as caught:runtime.fx.evaluate(formula)
 assert caught.value.kind=='InvalidArgument' and caught.value.end>caught.value.start
 assert runtime.fx.evaluate(f'Value(IfError({formula},FirstError.Kind))')==25

@pytest.mark.parametrize('formula',[
 'Left([] ,1)','Mid(FirstN([{A:"a",B:1}],0),2)','Right("x",[{A:1,B:2}])',
 'Replace("x",1,{N:1},"!")','Substitute("x","x","y",[{A:1,B:2}])','Concatenate({X:"a"})'])
def test_argument_roles_and_column_shapes_are_checked_before_execution(runtime,formula):
 runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(formula),BindScope())
 assert runtime.binder.errors and all(error.end>error.start for _,error in runtime.binder.errors)

@pytest.mark.parametrize('formula',[
 'Left(FirstN(["x"],0),1/0)','Mid(FirstN(["x"],0),1/0)',
 'Right("x",FirstN([1],0))','Substitute(FirstN(["x"],0),"a","b",1/0)',
 'Replace(FirstN(["x"],0),1,1/0,"a")','Concatenate(1/0,FirstN(["x"],0))'])
def test_typed_empty_tables_do_not_observe_scalar_errors(runtime,formula):
 assert runtime.fx.evaluate(formula)==[]

def test_blank_table_missing_pairs_error_cells_and_aggregated_errors(runtime):
 assert runtime.fx.evaluate('Left(If(false,["x"]),1/0)') is None
 with pytest.raises(FxError) as error:runtime.fx.evaluate('Concatenate(If(1/0<0,["a"]),"x")')
 assert error.value.kind=='Div0'
 result=runtime.fx.evaluate('Concatenate(["a","b"],["x"])')
 assert result[0]=={'Value':'ax'} and result[1]['Value'].kind=='NotApplicable'
 result=runtime.fx.evaluate('Mid(["abc","def"],[2,0])')
 assert result[0]=={'Value':'bc'} and result[1]['Value'].kind=='InvalidArgument'
 assert runtime.fx.evaluate('Value(IfError(Replace("abc","bad","also bad","x"),CountRows(AllErrors)))')==2
 assert runtime.fx.evaluate('Value(IfError(Mid("abc",0,-1),CountRows(AllErrors)))')==2
 assert runtime.fx.evaluate('If(false,Substitute("x","x","a",0),"healthy")')=='healthy'

def test_locale_decimal_dynamic_and_source_tables_remain_intact(runtime):
 runtime.environment.update(language='fr-CA',number_mode='decimal');runtime.invalidate()
 assert runtime.fx.evaluate('Left(12.5,3)')=='12,'
 assert runtime.fx.evaluate('Mid("alpha","2,5",2)')=='lp'
 assert runtime.fx.evaluate('Concatenate(ParseJSON("12.5"),true)')=='12.5true'
 runtime.fx.evaluate('ClearCollect(source,{Name:"alpha"},{Name:"beta"})',Context(runtime,behavior=True))
 assert runtime.fx.evaluate('Substitute(source,"a","A")')==[{'Value':'AlphA'},{'Value':'betA'}]
 assert runtime.collections['source']==[{'Name':'alpha'},{'Name':'beta'}]

@pytest.fixture
def text_app(tmp_path):
 from powerapps_sim.fixtures import text_tables_project
 from powerapps_sim.runtime import Runtime
 r=Runtime(text_tables_project(tmp_path/'p'));r.restart();r.state();assert not r.diagnostics
 yield r
 r.close()

def test_component_text_reactivity_table_function_callbacks_and_reset(text_app):
 r=text_app;r.event('TextTransforms/LeftPanel/Input','OnInput','River survey')
 assert r.fx.evaluate('LeftPanel.Current.Prefix')=='Riv' and r.collections['history']==[]
 r.event('TextTransforms/LeftPanel/Input','OnChange','River survey')
 assert len(r.collections['history'])==1 and r.fx.evaluate('RightPanel.Current.Raw')=='Étude rivière'
 assert r.fx.evaluate('First(LeftPanel.Rows).Value')=='Riv · River_survey · ey'
 r.event('TextTransforms/ResetLeft','OnSelect')
 assert r.fx.evaluate('LeftPanel.Current.Raw')=='App planning'
 assert r.component_state['TextTransforms/LeftPanel']['collections']['captured']==[]
 assert not r.diagnostics

def test_component_text_error_cells_types_and_mapped_write_failure(text_app):
 r=text_app;r.event('TextTransforms/BuildTable','OnSelect');r.event('TextTransforms/CaptureErrors','OnSelect')
 assert len(r.collections['results'][0])==20 and r.binder.collections['results'].row.fields['Normalized']==TEXT
 assert r.collections['errorCells'][1]['Value'].kind=='InvalidArgument'
 r.event('TextTransforms/LeftPanel/Input','OnChange','River survey')
 r.store.failures['Titles']='write';r.event('TextTransforms/SaveLeft','OnSelect')
 assert r.globals['status']=='Save failed' and r.store.rows('Titles')[0]['Project Title']=='Fictional title'
 r.store.failures.clear();r.event('TextTransforms/SaveLeft','OnSelect')
 assert r.store.rows('Titles')[0]['Normalized Title']=='River_survey' and not r.diagnostics

@pytest.mark.parametrize('language',['en-US','fr-CA'])
def test_text_workflow_preserves_owner_source_data_and_runtime(tmp_path,language):
 from powerapps_sim.fixtures import text_tables_project
 from powerapps_sim.application import Workspace
 from powerapps_sim.authoring import revision,data_revision
 p=text_tables_project(tmp_path/'p');w=Workspace(tmp_path,p.root,start=False)
 try:
  before=(revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime())
  entry=w.workflows.catalog()['scenarios'][0]
  result=w.workflows.run({**entry['scenario'],'environment':{'language':language}},expected_revision=before[0])
  assert result['status']=='passed' and len(result['steps'])==49 and not result['diagnostics']
  assert (revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime())==before
 finally:w.runtime.close()

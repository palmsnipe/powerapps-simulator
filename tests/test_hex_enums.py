"""Canvas hex conversion and optional typed built-in enum contracts."""
from copy import deepcopy
from decimal import Decimal
import pytest
from powerapps_sim.binding import BindScope,TEXT,value_type
from powerapps_sim.fx import Context
from powerapps_sim.enum_fx import EnumValue
from powerapps_sim.syntax import FxError

@pytest.mark.parametrize('formula,expected',[
 ('Dec2Hex(Blank())','0'),('Dec2Hex(165)','A5'),('Dec2Hex(-165)','FFFFFFFF5B'),
 ('Dec2Hex(-3.74)','FFFFFFFFFD'),('Dec2Hex(-0.9,2)','00'),('Dec2Hex(3.74)','3'),
 ('Dec2Hex(255,3.9)','0FF'),('Dec2Hex(0,10)','0000000000'),('Dec2Hex(-1,1)','FFFFFFFFFF'),
 ('Dec2Hex(549755813887.9)','7FFFFFFFFF'),('Dec2Hex(-549755813888.9)','8000000000'),
 ('Dec2Hex(true)','1'),('Dec2Hex("15","6")','00000F'),('Hex2Dec(Dec2Hex(-3.74))',-3)])
def test_dec2hex_canvas_truncation_padding_domains_and_roundtrip(runtime,formula,expected):
 assert runtime.fx.evaluate(formula)==expected

@pytest.mark.parametrize('formula,kind',[
 ('Dec2Hex(1e50)','Numeric'),('Dec2Hex(-549755813889)','Numeric'),('Dec2Hex(549755813888)','Numeric'),
 ('Dec2Hex(255,1)','Numeric'),('Dec2Hex(-1,0)','Numeric'),('Dec2Hex(-1,11)','Numeric'),
 ('Dec2Hex(0,Blank())','Numeric'),('Dec2Hex(1,"bad")','InvalidArgument'),('Dec2Hex("true")','InvalidArgument')])
def test_dec2hex_errors_are_located_and_catchable(runtime,formula,kind):
 with pytest.raises(FxError) as caught:runtime.fx.evaluate(formula)
 assert caught.value.kind==kind and caught.value.end>caught.value.start
 assert runtime.fx.evaluate(f'IsError({formula})')

@pytest.mark.parametrize('formula',[
 'Dec2Hex([])','Dec2Hex([{A:1,B:2}])','Dec2Hex({N:1})','Dec2Hex(1,[{A:1,B:2}])'])
def test_dec2hex_scalar_and_column_schema_roles(runtime,formula):
 runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(formula),BindScope())
 assert runtime.binder.errors

@pytest.mark.parametrize('formula',[
 'Dec2Hex(FirstN([1],0),1/0)','Dec2Hex(1/0,FirstN([1],0))',
 'Dec2Hex(If(false,[1]),1/0)'])
def test_dec2hex_empty_and_blank_tables_do_not_observe_unused_scalars(runtime,formula):
 assert runtime.fx.evaluate(formula)==(None if 'If(false' in formula else [])

def test_dec2hex_table_broadcast_blank_cells_unequal_length_and_aggregated_errors(runtime):
 assert runtime.fx.evaluate('Dec2Hex([10,255,-16],4)')==[{'Value':'000A'},{'Value':'00FF'},{'Value':'FFFFFFFFF0'}]
 result=runtime.fx.evaluate('Dec2Hex([10,255],[2,1,3])')
 assert result[0]=={'Value':'0A'} and result[1]['Value'].kind=='Numeric' and result[2]['Value'].kind=='NotApplicable'
 assert runtime.fx.evaluate('Value(IfError(Dec2Hex(1/0,1/0),CountRows(AllErrors)))')==2
 assert runtime.binder.bind(runtime.fx.parse('Dec2Hex([1],2)'),BindScope()).row.fields['Value']==TEXT

@pytest.fixture
def strong(runtime):
 runtime.environment['enum_mode']='strong';runtime.analyze();return runtime

@pytest.mark.parametrize('formula,expected',[
 ('Text(ErrorKind.Network)','Network'),('Find("x",ErrorKind.BadRegex)',8),
 ('Len(ErrorKind.Network)',7),('Left(ErrorKind.Network,3)','Net'),
 ('Text(StartOfWeek.Monday)','Monday'),('Value(StartOfWeek.Wednesday)',13),
 ('Float(StartOfWeek.Sunday)',1),('Text(TimeUnit.Months)','months'),
 ('Text(SortOrder.Descending)','descending'),('Text(DateTimeFormat.LongDate)',"'longdate'"),
 ('ErrorKind.Network+ErrorKind.Div0',36),('ErrorKind.Network> ErrorKind.Unknown',True),
 ('ErrorKind.Network=23',True),('TimeUnit.Days=TimeUnit.Days',True),
 ('DateTimeFormat.LongDate="\'longdate\'"',True),('Text(If(false,DateTimeFormat.LongDate,"help"))','help'),
 ('Concat([StartOfWeek.Monday,StartOfWeek.Friday],Value)','MondayFriday'),
 ('Text(Date(1980,1,2),"\'longdate\'","en-US")',"'long2ate'")])
def test_strong_enums_text_number_comparison_branch_and_format_contracts(strong,formula,expected):
 assert strong.fx.evaluate(formula)==expected

@pytest.mark.parametrize('formula',[
 'Boolean(ErrorKind.Network)','Value(TimeUnit.Days)','Sqrt(StartOfWeek.Monday)',
 'ErrorKind.Network=StartOfWeek.Friday','TimeUnit.Days="days"','SortOrder.Ascending<SortOrder.Descending',
 'ErrorKind.Network=true','ErrorKind.Network="23"','If(false,ErrorKind.Network,23)',
 'DateAdd(Date(2026,1,1),1,SortOrder.Ascending)','Sort([1,2],Value,TimeUnit.Days)',
 'Text(Date(2026,1,1),SortOrder.Ascending)'])
def test_strong_enum_wrong_namespaces_and_conversions_are_binding_errors(strong,formula):
 strong.binder.errors.clear();strong.binder.bind(strong.fx.parse(formula),BindScope())
 assert strong.binder.errors and all(e.kind=='Type' for _,e in strong.binder.errors)

@pytest.mark.parametrize('formula',[
 'Boolean(ErrorKind.Network)','Sqrt(StartOfWeek.Monday)','ErrorKind.Network=StartOfWeek.Friday',
 'SortOrder.Ascending<SortOrder.Descending','If(StartOfWeek.Monday,"yes","no")'])
def test_strong_enum_runtime_guards_do_not_depend_on_editor_diagnostics(strong,formula):
 with pytest.raises(FxError) as caught:strong.fx.evaluate(formula)
 assert caught.value.kind=='Type'

def test_enum_identity_typed_empty_tables_json_and_decimal_constructors(strong):
 r=strong;value=r.fx.evaluate('ErrorKind.Network');assert isinstance(value,EnumValue) and deepcopy(value)==value
 assert value_type(value).kind=='Enum' and value_type(value).name=='ErrorKind'
 assert r.fx.evaluate('Left([ErrorKind.Network,ErrorKind.Numeric],3)')==[{'Value':'Net'},{'Value':'Num'}]
 assert r.fx.evaluate('Char([ErrorKind.GeneratedValue,ErrorKind.Network])')==[{'Value':'\t'},{'Value':'\x17'}]
 assert r.fx.evaluate('Dec2Hex([ErrorKind.Network,ErrorKind.Numeric],2)')==[{'Value':'17'},{'Value':'18'}]
 r.environment['number_mode']='decimal';r.invalidate();r.analyze()
 assert r.fx.evaluate('Decimal(StartOfWeek.Monday)')==Decimal(2)
 r.environment['language']='fr-CA';r.invalidate()
 assert r.fx.evaluate('Dec2Hex("-3,74",1)',Context(r))=='FFFFFFFFFD'
 assert r.fx.evaluate('JSON(ErrorKind.Network)',Context(r,behavior=True))=='23'
 assert r.fx.evaluate('JSON({Kind:ErrorKind.Network,Title:"kept"},JSONFormat.IgnoreUnsupportedTypes)',Context(r,behavior=True))=='{"Kind":23,"Title":"kept"}'

@pytest.fixture
def hex_app(tmp_path):
 from powerapps_sim.fixtures import hex_enums_project
 from powerapps_sim.runtime import Runtime
 r=Runtime(hex_enums_project(tmp_path/'p'));r.restart();r.state();assert not r.diagnostics
 yield r
 r.close()

def test_component_caught_function_errors_do_not_become_diagnostics(hex_app):
 r=hex_app;r.event('HexEnums/LeftPanel/Places','OnChange','1');r.state()
 assert r.fx.evaluate('LeftPanel.Current.ErrorCode')==24 and not r.diagnostics
 assert r.fx.evaluate('RightPanel.Current.Hex')=='FFFFFFFFFD'
 r.event('HexEnums/LeftPanel/Places','OnChange','4');r.state()
 assert r.fx.evaluate('LeftPanel.Current.Hex')=='00A5' and not r.diagnostics
 with pytest.raises(FxError):r.fx.evaluate('LeftPanel.Encode(255,1)')
 assert not r.diagnostics  # The caller decides whether to observe the error.
 r.global_refs['Heading'].control.properties['Text']='=LeftPanel.Encode(255,1)';r.invalidate();r.state()
 assert any(d['kind']=='Numeric' and d['member']=='Heading.Text' for d in r.diagnostics)

def test_enum_component_records_wide_tables_and_mapped_save_failures(hex_app):
 r=hex_app;r.event('HexEnums/LeftPanel/Input','OnChange','255');r.event('HexEnums/BuildTable','OnSelect');r.event('HexEnums/Errors','OnSelect')
 assert len(r.collections['results'][0])==20 and isinstance(r.collections['history'][0]['Kind'],EnumValue)
 assert r.collections['codeErrors'][0]['Value'].kind=='Numeric'
 r.store.failures['Snapshots']='write';r.event('HexEnums/SaveLeft','OnSelect')
 assert r.globals['status']=='Save failed' and r.store.rows('Snapshots')[0]['Hex Code']=='00'
 r.store.failures.clear();r.event('HexEnums/SaveLeft','OnSelect')
 assert r.store.rows('Snapshots')[0]['Hex Code']=='00FF' and r.store.rows('Snapshots')[0]['Error Kind']=='Network'
 r.event('HexEnums/ResetLeft','OnSelect');assert r.fx.evaluate('LeftPanel.Current.Hex')=='00A5' and not r.diagnostics

@pytest.mark.parametrize('language',['en-US','fr-CA'])
def test_hex_enum_workflow_preserves_owner_source_data_and_runtime(tmp_path,language):
 from powerapps_sim.fixtures import hex_enums_project
 from powerapps_sim.application import Workspace
 from powerapps_sim.authoring import revision,data_revision
 p=hex_enums_project(tmp_path/'p');w=Workspace(tmp_path,p.root,start=False)
 try:
  before=(revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime())
  entry=w.workflows.catalog()['scenarios'][0]
  result=w.workflows.run({**entry['scenario'],'environment':{'language':language,'enum_mode':'strong'}},expected_revision=before[0])
  assert result['status']=='passed' and len(result['steps'])==55 and not result['diagnostics']
  assert result['types']['collections']['results']['row']['fields']['Kind']=={'kind':'Enum','name':'ErrorKind'}
  assert result['collections']['results'][0]['Kind']['$enum']['value']==23
  assert (revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime())==before
 finally:w.runtime.close()

def test_invalid_enum_profile_is_rejected_in_workflows():
 from powerapps_sim.workflows import validate,STARTER
 with pytest.raises(ValueError,match='enum_mode'):validate({**STARTER,'environment':{'enum_mode':'guess'}})

@pytest.mark.parametrize('formula',['[ErrorKind.Network,StartOfWeek.Monday]','Table({V:TimeUnit.Days},{V:SortOrder.Ascending})'])
def test_enum_table_union_rejects_different_namespaces(strong,formula):
 strong.binder.errors.clear();strong.binder.bind(strong.fx.parse(formula),BindScope());assert strong.binder.errors

def test_enum_mode_settings_rebind_and_reject_invalid_values(tmp_path):
 from powerapps_sim.fixtures import hex_enums_project
 from powerapps_sim.web import create_app
 p=hex_enums_project(tmp_path/'p');app=create_app(tmp_path,p.root);r=app.extensions['workspace'].runtime
 try:
  client=app.test_client();env=deepcopy(r.environment);headers={'X-Emulator-Request':'1'}
  assert client.post('/api/scenario',json={'environment':{**env,'enum_mode':'guess'}},headers=headers).status_code==400
  assert r.environment==env
  assert client.post('/api/scenario',json={'environment':{**env,'enum_mode':'legacy'}},headers=headers).status_code==200
  assert r.fx.evaluate('Text(ErrorKind.Network)')=='23' and r.binder.globals['ErrorKind'].fields['Network'].kind=='Number'
  assert client.post('/api/scenario',json={'environment':env},headers=headers).status_code==200
  assert r.fx.evaluate('Text(ErrorKind.Network)')=='Network' and r.binder.globals['ErrorKind'].fields['Network'].kind=='Enum'
 finally:r.close()

def test_modern_date_picker_consumes_strong_startofweek(tmp_path):
 from powerapps_sim.source import Project
 from powerapps_sim.runtime import Runtime
 from powerapps_sim.input_controls import date_contract
 p=Project(tmp_path/'p');p.config['environment']['enum_mode']='strong'
 p.update_source('Src/week.yaml','Screens:\n  Week:\n    Children:\n    - Day:\n        Control: ModernDatePicker@1.0.0\n        Properties:\n          StartOfWeek: =StartOfWeek.Monday\n')
 r=Runtime(p)
 try:
  r.restart();r.state();assert not r.diagnostics and date_contract(r.global_refs['Day'])[2]==0
 finally:r.close()

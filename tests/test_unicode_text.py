"""Text searching/splitting, character code domains and table error isolation."""
from decimal import Decimal
import pytest
from powerapps_sim.binding import BindScope,NUMBER,TEXT,DECIMAL
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError

@pytest.mark.parametrize('formula,expected',[
 ('Find("r","🌲river")',3),('Find("🌲","x🌲river")',2),('Find("R","river")',None),
 ('Find("","🌲river",3)',3),('Find("","abc",4)',4),('Find("a","abc",4)',None),
 ('Find("b","abc",1.9)',2),('Find("",Blank())',1),('Find(2,123)',2),
 ('Split("🌲x","")',[{'Value':'\ud83c'},{'Value':'\udf32'},{'Value':'x'}]),
 ('Split("🌲x🌲y","🌲")',[{'Value':''},{'Value':'x'},{'Value':'y'}]),
 ('Split("a,,b,",",")',[{'Value':'a'},{'Value':''},{'Value':'b'},{'Value':''}]),
 ('Split(Blank(),Blank())',[]),('Split(Blank(),",")',[{'Value':''}]),
 ('Char(255.9)','ÿ'),('Char(65.9)','A'),('UniChar(127794)','🌲'),('UniChar(119137.9)','𝅘𝅥𝅯'),
 ('UniChar(1114111.99)','\U0010ffff'),('UniChar("233")','é'),('Hex2Dec("1F332")',127794),
 ('Hex2Dec("8000000000")',-549755813888),('Hex2Dec("FFFFFFFFFF")',-1),('Hex2Dec(Blank())',0)])
def test_unicode_positions_blank_search_split_and_code_scalar_values(runtime,formula,expected):
 assert runtime.fx.evaluate(formula)==expected

@pytest.mark.parametrize('formula,kind',[
 ('Find("a","abc",0)','InvalidArgument'),('Find("","abc",5)','InvalidArgument'),
 ('Find("a","abc",Blank())','InvalidArgument'),('Find("a","abc",-1)','InvalidArgument'),
 ('Char(0)','InvalidArgument'),('Char(256)','InvalidArgument'),('Char(0.9)','InvalidArgument'),
 ('UniChar(0)','InvalidArgument'),('UniChar(1114112)','InvalidArgument'),
 ('UniChar(55296)','NotApplicable'),('UniChar(57343.9)','NotApplicable'),
 ('Hex2Dec("ZZZZZZZZZZ")','Numeric'),('Hex2Dec("FFFFFFFFFFF")','Numeric'),
 ('Hex2Dec("0xFF")','Numeric'),('Hex2Dec("-FF")','Numeric')])
def test_character_hex_and_search_failures_remain_catchable(runtime,formula,kind):
 with pytest.raises(FxError) as error:runtime.fx.evaluate(formula)
 assert error.value.kind==kind and error.value.end>error.value.start
 assert runtime.fx.evaluate(f'IsError({formula})') is True

@pytest.mark.parametrize('name',['Find','Char','UniChar','Hex2Dec'])
def test_new_single_column_table_output_types_and_typed_empty_tables(runtime,name):
 source='[65,66]' if name in ('Char','UniChar') else '["41","42"]'
 formula=f'{name}("4",{source})' if name=='Find' else f'{name}({source})'
 result=runtime.fx.evaluate(formula);assert len(result)==2 and all(set(row)=={'Value'} for row in result)
 typ=runtime.binder.bind(runtime.fx.parse(formula),BindScope())
 assert typ.row.fields['Value']==(NUMBER if name in ('Find','Hex2Dec') else TEXT)
 empty=f'{name}(1/0,FirstN(["x"],0))' if name=='Find' else f'{name}(FirstN({source},0))'
 assert runtime.fx.evaluate(empty)==[]

@pytest.mark.parametrize('formula',[
 'Find({X:"a"},"abc")','Find("a","abc",{X:1})','Find(["a"],[{A:"x",B:"y"}])',
 'Split(["a"],",")','Split("a",[","])','Char([{A:65,B:66}])',
 'UniChar({N:65})','Hex2Dec([])','Hex2Dec({Text:"41"})'])
def test_search_code_and_split_schema_argument_validation(runtime,formula):
 runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(formula),BindScope())
 assert runtime.binder.errors and all(error.end>error.start for _,error in runtime.binder.errors)

def test_table_broadcast_cell_and_row_errors_and_blank_tables(runtime):
 result=runtime.fx.evaluate('Find(["a","b"],["abc"],1)')
 assert result[0]=={'Value':1} and result[1]['Value'].kind=='NotApplicable'
 result=runtime.fx.evaluate('UniChar([65,55296,0,127794])')
 assert result[0]=={'Value':'A'} and result[1]['Value'].kind=='NotApplicable' and result[2]['Value'].kind=='InvalidArgument' and result[3]=={'Value':'🌲'}
 result=runtime.fx.evaluate('Char(Table({N:65},If(1/0<0,{N:66}),If(false,{N:65}),{N:Blank()}))')
 assert result[1].kind=='Div0' and result[2] is None and result[3]['Value'].kind=='InvalidArgument'
 assert runtime.fx.evaluate('Find(If(false,["x"]),1/0)') is None
 assert runtime.fx.evaluate('Value(IfError(Find(1/0,1/0),CountRows(AllErrors)))')==2
 assert runtime.fx.evaluate('First(IfError(Split(1/0,1/0),Table({Value:Text(CountRows(AllErrors))}))).Value')=='2'


def test_decimal_locale_dynamic_and_lazy_character_conversion(runtime):
 runtime.environment.update(language='fr-CA',number_mode='decimal');runtime.invalidate()
 assert runtime.fx.evaluate('Char("65,5")')=='A'
 assert runtime.fx.evaluate('UniChar(ParseJSON("127794"))')=='🌲'
 assert runtime.fx.evaluate('Hex2Dec("FFFFFFFFFF")')==Decimal(-1)
 assert runtime.binder.bind(runtime.fx.parse('Hex2Dec("41")'),BindScope())==DECIMAL
 assert runtime.binder.bind(runtime.fx.parse('Find("a","abc")'),BindScope())==NUMBER
 assert runtime.fx.evaluate('Split(12.5,",")')==[{'Value':'12'},{'Value':'5'}]
 assert runtime.fx.evaluate('If(false,UniChar(55296),"healthy")')=='healthy'


def test_character_creation_and_splitting_preserve_source_collections(runtime):
 runtime.fx.evaluate('ClearCollect(codes,{Code:65},{Code:127794});Set(raw,"a,,b")',Context(runtime,behavior=True))
 assert runtime.fx.evaluate('UniChar(codes)')==[{'Value':'A'},{'Value':'🌲'}]
 assert runtime.fx.evaluate('Split(raw,",")')==[{'Value':'a'},{'Value':''},{'Value':'b'}]
 assert runtime.collections['codes']==[{'Code':65},{'Code':127794}] and runtime.globals['raw']=='a,,b'

@pytest.mark.parametrize('formula,expected',[
 ('[1,]',[{'Value':1}]),('["a", /* trailing */]',[{'Value':'a'}]),
 ('Find(["a",],["abc",])',[{'Value':1}])])
def test_reference_table_trailing_comma_preserves_rows(runtime,formula,expected):
 assert runtime.fx.evaluate(formula)==expected

@pytest.mark.parametrize('formula',['[,]','[1,,]'])
def test_table_comma_without_expression_remains_a_syntax_error(runtime,formula):
 with pytest.raises(FxError):runtime.fx.parse(formula)

@pytest.mark.parametrize('formula',[
 'Concat(Split("🌲x",""),Value)',
 'Left("🌲",1) & Right("🌲",1) & "x"',
 'Concat(Split("🌲x",""),Value,"")'])
def test_split_unicode_recombination_preserves_character_identity(runtime,formula):
 assert runtime.fx.evaluate(formula)=='🌲x'

@pytest.fixture
def unicode_app(tmp_path):
 from powerapps_sim.fixtures import unicode_project
 from powerapps_sim.runtime import Runtime
 r=Runtime(unicode_project(tmp_path/'p'));r.restart();r.state();assert not r.diagnostics
 yield r
 r.close()

def test_unicode_component_callbacks_reactive_search_and_instance_reset(unicode_app):
 r=unicode_app;r.event('UnicodeText/LeftPanel/Input','OnInput','🌲 Coast,,Lake,')
 assert r.fx.evaluate('IsBlank(LeftPanel.Current.Found)') and r.collections['history']==[]
 r.event('UnicodeText/LeftPanel/Needle','OnChange','Coast')
 assert r.fx.evaluate('LeftPanel.FindPosition(LeftPanel.Current.Raw,"Coast")')==4
 assert len(r.collections['history'])==1 and r.fx.evaluate('RightPanel.Current.Symbol')=='λ'
 r.event('UnicodeText/ResetLeft','OnSelect')
 assert r.fx.evaluate('LeftPanel.Current.Raw')=='🌲 River,,Lake,'
 assert r.component_state['UnicodeText/LeftPanel']['collections']['captured']==[] and not r.diagnostics

def test_unicode_table_errors_mapped_persistent_save_and_disabled_guard(unicode_app):
 r=unicode_app;r.event('UnicodeText/BuildTable','OnSelect');r.event('UnicodeText/Errors','OnSelect')
 assert len(r.collections['results'][0])==20 and r.collections['codeErrors'][1]['Value'].kind=='NotApplicable'
 assert r.fx.evaluate('Concat(First(results).Characters,Value)')=='🌲 River,,Lake,'
 r.store.failures['Snapshots']='write';r.event('UnicodeText/SaveLeft','OnSelect')
 assert r.globals['status']=='Save failed' and r.store.rows('Snapshots')[0]['Unicode Symbol']=='A'
 r.store.failures.clear();r.event('UnicodeText/SaveLeft','OnSelect')
 assert r.store.rows('Snapshots')[0]['Unicode Symbol']=='🌲'
 r.event('UnicodeText/LeftPanel/Hex','OnChange','D800')
 assert r.fx.evaluate('SaveLeft.DisplayMode')=='Disabled' and not r.diagnostics

@pytest.mark.parametrize('language',['en-US','fr-CA'])
def test_unicode_workflow_reports_utf16_and_preserves_owner(tmp_path,language):
 import json
 from powerapps_sim.fixtures import unicode_project
 from powerapps_sim.application import Workspace
 from powerapps_sim.authoring import revision,data_revision
 p=unicode_project(tmp_path/'p');w=Workspace(tmp_path,p.root,start=False)
 try:
  before=(revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime())
  entry=w.workflows.catalog()['scenarios'][0]
  result=w.workflows.run({**entry['scenario'],'environment':{'language':language}},expected_revision=before[0])
  assert result['status']=='passed' and len(result['steps'])==58 and not result['diagnostics']
  saved=json.loads((p.root/'.emu/runs'/f"{result['id']}.json").read_text())
  assert saved['collections']['results'][0]['Characters'][0]['Value']=='\ud83c'
  assert saved['steps'][48]['blocked']
  assert (revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime())==before
 finally:w.runtime.close()

def test_json_exports_escape_utf16_units_without_changing_text(runtime):
 import json
 from powerapps_sim.catalog import json_text
 assert json.loads(json_text({'unit':'\ud83c','text':'🌲'}))=={'unit':'\ud83c','text':'🌲'}
 value=runtime.fx.evaluate('JSON(Split("🌲",""))',Context(runtime,behavior=True))
 assert json.loads(value)==[{'Value':'\ud83c'},{'Value':'\udf32'}] and value.encode('utf-8')

def test_mcp_transport_exposes_isolated_utf16_units_losslessly():
 from powerapps_sim.mcp_server import mcp_value
 assert mcp_value({'text':'🌲','units':[{'Value':'\ud83c'},{'Value':'\udf32'}]})=={'text':'🌲','units':[{'Value':{'$utf16':[55356]}},{'Value':{'$utf16':[57138]}}]}
 assert mcp_value('a\ud83c')=={'$utf16':[97,55356]}

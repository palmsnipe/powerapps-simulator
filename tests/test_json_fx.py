"""Documented JSON contracts and representative upstream Power Fx cases."""
from decimal import Decimal
import json
from copy import deepcopy
import pytest

from powerapps_sim.binding import BindScope
from powerapps_sim.fx import Context
from powerapps_sim.json_fx import Dynamic, JsonNumber
from powerapps_sim.runtime import Runtime, serial
from powerapps_sim.source import Project, dump_yaml
from powerapps_sim.syntax import FxError


def quote(value):
    return '"'+value.replace('"','""')+'"'


@pytest.fixture
def runtime(tmp_path):
    p=Project(tmp_path/'json')
    p.update_source('Src/json.pa.yaml',dump_yaml({'App':{'Properties':{'Formulas':'=Row := Type({Name:Text,Amount:Number,Owner:{Email:Text},Tags:[Text]});Rows := Type([Row]);Good=42;','OnStart':'=Set(doc,ParseJSON("{ ""name"": ""Fictional record"", ""rows"": [{""n"":1},{""n"":2}] }"))'}},'Screens':{'Home':{}}}))
    r=Runtime(p);r.restart()
    yield r
    r.close()


@pytest.mark.parametrize('formula,expected',[
 ('Text(doc.name)','Fictional record'),
 ('Text(doc.missing.child)',None),
 ('IsBlank(doc.missing)',True),
 ('CountRows(doc.rows)',2),
 ('Value(Index(doc.rows,2).n)',2),
 ('Value(First(doc.rows).n)',1),
 ('Value(Last(doc.rows).n)',2),
 ('CountRows(FirstN(doc.rows,1))',1),
 ('CountRows(LastN(doc.rows,8))',2),
 ('IsEmpty(FirstN(doc.rows,0))',True),
 ('Text(Column(doc,"name"))','Fictional record'),
 ('ColumnNames(doc)',[{'Value':'name'},{'Value':'rows'}]),
 ('ForAll(doc.rows As entry,{N:Value(entry.n),Label:Text(entry.n)})',[{'N':1,'Label':'1'},{'N':2,'Label':'2'}]),
 ('ForAll(Table(doc.rows),Value(ThisRecord.Value.n))',[{'Value':1},{'Value':2}]),
 ('Value(ParseJSON("true"))',1),
 ('Boolean(ParseJSON("0"))',False),
 ('Boolean(ParseJSON("""true"""))',True),
 ('Text(ParseJSON("1.2300e2"))','1.2300e2'),
 ('ParseJSON("4")+2',6),
 ('ParseJSON("4")=4',True),
 ('ParseJSON("""text""")="text"',True),
 ('ParseJSON("4")<5',True),
 ('If(ParseJSON("true"),"yes","no")','yes'),
 ('If(false,Value(ParseJSON("{}")),3)',3),
])
def test_dynamic_navigation_arrays_and_scalar_conversions(runtime,formula,expected):
    assert runtime.fx.evaluate(formula)==expected


@pytest.mark.parametrize('value',['','{','[1,]','{"x":NaN}','Infinity','{"x":1} trailing','"raw\nnewline"'])
def test_invalid_json_is_catchable_and_located(runtime,value):
    formula=f'ParseJSON({quote(value)})'
    with pytest.raises(FxError) as exc:runtime.fx.evaluate(formula)
    assert exc.value.kind=='InvalidJSON' and exc.value.end>exc.value.start
    assert runtime.fx.evaluate(f'IfError({formula},Blank())') is None
    assert runtime.fx.evaluate('Good')==42


def test_typed_projection_nested_shapes_forward_alias_and_missing_fields(runtime):
    data='{"Name":"Fictional nested","Amount":12.5,"Extra":true,"Owner":{"Email":"person@example.test","Extra":1},"Tags":["A","B"]}'
    value=runtime.fx.evaluate(f'ParseJSON({quote(data)},Row)')
    assert value=={'Name':'Fictional nested','Amount':12.5,'Owner':{'Email':'person@example.test'},'Tags':[{'Value':'A'},{'Value':'B'}]}
    assert runtime.fx.evaluate('ParseJSON("{}",Row)')=={'Name':None,'Amount':None,'Owner':None,'Tags':None}
    assert runtime.fx.evaluate('ParseJSON("[1,2,null]",Type([Number]))')==[{'Value':1},{'Value':2},{'Value':None}]
    assert runtime.fx.evaluate('ParseJSON("[{""Amount"":1}]",Rows)')[0]['Amount']==1
    assert runtime.fx.evaluate('AsType(ParseJSON("42"),Type(Number))')==42
    assert isinstance(runtime.fx.evaluate('ParseJSON("42",Dynamic)'),Dynamic)
    with pytest.raises(FxError,match=r'\$\.Owner\.Email'):
        runtime.fx.evaluate('ParseJSON("{ ""Owner"": { ""Email"": 1 } }",Row)')


@pytest.mark.parametrize('source,target',[
 ('5','Text'),('"42"','Number'),('"true"','Boolean'),('true','Number'),
 ('{"Amount":"bad"}','Row'),('[{"Amount":true}]','Rows'),
 ('[1]','Row'),('{}','Rows'),('"bad date"','Date'),('"24:59:59"','Time'),
])
def test_typed_json_checks_scalar_kinds_and_all_nested_fields(runtime,source,target):
    assert runtime.fx.evaluate(f'IsType(ParseJSON({quote(source)}),{target})') is False
    for formula in [f'ParseJSON({quote(source)},{target})',f'AsType(ParseJSON({quote(source)}),{target})']:
        with pytest.raises(FxError) as exc:runtime.fx.evaluate(formula)
        assert exc.value.kind=='InvalidArgument'


def test_type_test_does_not_swallow_source_error_or_validate_invalid_type(runtime):
    assert runtime.fx.evaluate('IsType(ParseJSON(Blank()),Number)') is False
    assert runtime.fx.evaluate('IsType(ParseJSON("{}"),Row)') is True
    with pytest.raises(FxError,match='Invalid JSON'):runtime.fx.evaluate('IsType(ParseJSON("bad"),Number)')
    for target in ['Color','Missing','Type(5)','Type({N:Color})','Void','Type([Number,Text])']:
        expression=f'ParseJSON("null",{target})'
        with pytest.raises(FxError):runtime.fx.evaluate(expression)
        runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(expression),BindScope(),('test','',0))
        assert runtime.binder.errors


def test_typed_dates_are_iso_and_independent_of_user_language(runtime):
    runtime.environment['language']='fr-CA'
    assert runtime.fx.evaluate('ParseJSON("""1984-01-01""",Date)').isoformat().startswith('1984-01-01')
    assert runtime.fx.evaluate('DateTimeValue(ParseJSON("""2026-01-01T02:00:00+02:00"""))').value.hour==0
    assert runtime.fx.evaluate('TimeValue(ParseJSON("""12:34:56.7891"""))').value.microsecond==789100
    with pytest.raises(FxError):runtime.fx.evaluate('DateValue(ParseJSON("""May 5, 2022"""))')
    assert runtime.fx.evaluate('DateValue(Text(ParseJSON("""May 5, 2022""")),"en-US")').value.day==5


def test_decimal_json_preserves_digits_and_inspector_dynamic_identity(runtime):
    runtime.environment['number_mode']='decimal'
    # Evaluator reads the environment for its numeric mode.
    value=runtime.fx.evaluate('AsType(ParseJSON("12345678901234.567890123456"),Decimal)')
    assert value==Decimal('12345678901234.567890123456')
    output=runtime.fx.evaluate('JSON(ParseJSON("12345678901234.567890123456"))',Context(runtime,behavior=True))
    assert output=='12345678901234.567890123456'
    assert serial(runtime.globals['doc'])['$dynamic']['rows'][0]['n']=={'$jsonNumber':'1'}
    assert runtime.binder.variables['doc'].kind=='Dynamic'


def test_json_behaviors_formats_logical_names_and_temporal_values(runtime):
    ctx=Context(runtime,behavior=True)
    assert runtime.fx.evaluate('JSON([1,2,3],JSONFormat.FlattenValueTables)',ctx)=='[1,2,3]'
    assert runtime.fx.evaluate('JSON([1,2,3])',ctx)=='[{"Value":1},{"Value":2},{"Value":3}]'
    output=runtime.fx.evaluate('JSON({Rows:[1,2],Name:"é\nline"},JSONFormat.IndentFour & JSONFormat.FlattenValueTables)',ctx)
    assert '\n    "Rows": [' in output and json.loads(output)=={'Rows':[1,2],'Name':'é\nline'}
    output=runtime.fx.evaluate('JSON({Day:Date(2026,1,2),Clock:Time(12,34,56),Stamp:DateTimeValue("2026-01-02T02:00:00+02:00")})',ctx)
    assert json.loads(output)=={'Day':'2026-01-02','Clock':'12:34:56.000','Stamp':'2026-01-02T00:00:00.000Z'}
    runtime.store.add_list('Mapped',{'fields':{'ID':{'type':'integer'},'Title':{'type':'string'},'internal_amount':{'type':'number'}},'mapping':{'internal_amount':'Total amount'}})
    runtime.store.patch('Mapped',{}, {'Title':'Fictional JSON record','Total amount':12})
    output=runtime.fx.evaluate('JSON(ShowColumns(Mapped,Title,\'Total amount\'))',ctx)
    assert json.loads(output)==[{'Title':'Fictional JSON record','internal_amount':12}]
    output=runtime.fx.evaluate('JSON(Table(First(Mapped)))',ctx)
    assert json.loads(output)[0]['internal_amount']==12
    output=runtime.fx.evaluate('JSON(GroupBy(Mapped,\'Total amount\',Members))',ctx)
    assert json.loads(output)[0]['internal_amount']==12
    output=runtime.fx.evaluate('JSON(Ungroup(GroupBy(Mapped,Title,Members),Members))',ctx)
    assert json.loads(output)[0]['internal_amount']==12
    runtime.fx.evaluate('Set(saved,First(Mapped));Set(payload,JSON(saved))',ctx)
    assert json.loads(runtime.globals['payload'])['internal_amount']==12
    with pytest.raises(FxError):runtime.fx.evaluate('JSON({A:1})')
    with pytest.raises(FxError):runtime.fx.evaluate('JSON({A:1},JSONFormat.IncludeBinaryData & JSONFormat.IgnoreBinaryData)',ctx)
    with pytest.raises(FxError):runtime.fx.evaluate('JSON({Bad:Home})',ctx)
    assert json.loads(runtime.fx.evaluate('JSON({Good:1,Bad:Home},JSONFormat.IgnoreUnsupportedTypes)',ctx))=={'Good':1}


def test_json_actions_are_purely_bound_and_single_table_arg_runs_once(runtime):
    # Table's Dynamic overload must not evaluate an ordinary behavior arg twice.
    runtime.store.add_list('Drafts',{'fields':{'ID':{'type':'integer'},'Title':{'type':'string'}},'mapping':{}})
    runtime.fx.evaluate('Table(Patch(Drafts,Defaults(Drafts),{Title:"Fictional once"}))',Context(runtime,behavior=True))
    assert len(runtime.store.rows('Drafts'))==1
    runtime.binder.bind(runtime.fx.parse('JSON({A:1})'),BindScope(),('test','',0))
    assert any('only allowed in behavior' in error.message for _,error in runtime.binder.errors)
    assert 'payload' not in runtime.globals


@pytest.mark.parametrize('expression',[
 'Value(ParseJSON("{}"))','Text(ParseJSON("[]"))','Boolean(ParseJSON("{}"))',
 'Table(ParseJSON("{}"))','Index(ParseJSON("{}"),1)','ColumnNames(ParseJSON("[]"))',
 'Column(ParseJSON("1"),"A")','Index(ParseJSON("[1]"),0)','Index(ParseJSON("[1]"),2)',
])
def test_dynamic_shape_errors_are_visible(runtime,expression):
    with pytest.raises(FxError):runtime.fx.evaluate(expression)


def test_json_fixture_components_nested_list_writes_and_isolated_workflow(tmp_path):
    from powerapps_sim.fixtures import json_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision, data_revision
    from powerapps_sim.source import load_yaml
    p=json_project(tmp_path/'fixture');w=Workspace(tmp_path,p.root)
    try:
        assert not w.runtime.diagnostics
        assert w.runtime.store.choices('Projects','Owners',w.runtime.people)[0]['Email']=='admin@example.test'
        source=p.documents['Src/json.pa.yaml']
        assert load_yaml(dump_yaml(load_yaml(source)))==load_yaml(source)
        live=deepcopy(w.runtime.globals);data=data_revision(w.runtime.store)
        scenario=w.workflows.catalog()['scenarios'][0]['scenario']
        result=w.workflows.run(scenario,expected_revision=revision(p.root))
        assert result['status']=='passed',result['steps']
        assert len(result['steps'])==31 and not result['diagnostics']
        assert result['writes']==[{'list':'Projects','id':1,'operation':'insert'}]
        assert w.runtime.globals==live and data_revision(w.runtime.store)==data
        assert '$dynamic' in w.runtime.state()['globals']['document']
    finally:w.runtime.close()


def test_json_color_media_formats_and_text_uri_identity(runtime):
    from powerapps_sim.json_fx import Media, json_text
    ctx=Context(runtime,behavior=True)
    assert runtime.fx.evaluate('JSON(RGBA(16,32,48,1))',ctx)=='"#102030ff"'
    assert runtime.fx.evaluate('JSON(Color.Red)',ctx)=='"#ff0000ff"'
    assert runtime.fx.evaluate('Text(ParseJSON("12.5"),"0.00")')=='12.50'
    uri='data:image/png;base64,AAAA'
    assert json.loads(runtime.fx.evaluate('JSON("data:image/png;base64,AAAA")',ctx))==uri
    assert json_text({'Picture':Media(uri)},'G')=='{}'
    assert json.loads(json_text(Media(uri),'B'))==uri
    with pytest.raises(FxError,match='media requires'):json_text(Media(uri))
    with pytest.raises(FxError,match='unsupported'):json_text(Media('blob:unavailable'),'B')
    assert json.loads(json_text(Media('https://example.test/picture.png')))=='https://example.test/picture.png'
    assets=runtime.project.root/'Assets';assets.mkdir()
    (assets/'fictional.png').write_bytes(b'fictional bytes')
    runtime.project.config['resource_metadata']=[{'Name':'FictionalPicture','ResourceKind':'LocalFile','Path':'Assets/fictional.png'}]
    runtime.analyze()
    encoded=runtime.fx.evaluate('JSON(FictionalPicture,JSONFormat.IncludeBinaryData)',ctx)
    assert json.loads(encoded)=='data:image/png;base64,ZmljdGlvbmFsIGJ5dGVz'
    with pytest.raises(FxError,match='media requires'):
        runtime.fx.evaluate('JSON(If(true,FictionalPicture,Blank()))',ctx)
    with pytest.raises(FxError):json_text(Media('/api/asset/Assets/../app.yaml',assets),'B')

"""Pinned interpolation oracles, source spans, scoping and component integration."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from powerapps_sim.syntax import Parser,walk,call_name,FxError
from powerapps_sim.fx import Context
from powerapps_sim.binding import BindScope
from powerapps_sim.conformance import run_case
from powerapps_sim.enum_fx import EnumValue

CORPUS=json.loads((Path(__file__).parents[1]/'powerapps_sim/conformance_cases/interpolation.json').read_text())
@pytest.mark.parametrize('case',CORPUS['cases'],ids=lambda c:c['id'])
def test_complete_pinned_interpolation_oracle(runtime,case):
    result=run_case(runtime,case)
    assert result['status']=='passed',result

@pytest.mark.parametrize('formula,expected',[
 ('$"{1 /* } $\" */+2}"','3'),('$"{1 // } $\"\n+2}"','3'),
 ('$"{With({\'a}b\':7},\'a}b\')}"','7'),('$"{\"{{ } // /* $\"}"','{{ } // /* $'),
 ('$"JSON {{\""n\"":{With({n:7},n)}}}"','JSON {"n":7}'),
 ('$"{If(false,1/0,\"healthy\")}"','healthy'),
 ('$"{Concat([1,2] As row,$\"{row.Value}\",\",\")}"','1,2'),
 ('$"{With({base:10},Concat([1,2] As row,$\"{base+row.Value}\",\",\"))}"','11,12'),
 ('$"{ParseJSON(\"123.450\")}"','123.450'),
 ('$"{Blank()}"',None),('$"x{Blank()}y"','xy'),('$"{{{Blank()}}}"','{}'),
 ('$"Backslash \\ is literal"','Backslash \\ is literal'),
 ('$"{With({r:{n:7}},r.n)}"','7')])
def test_nested_lexical_scopes_and_coercions(runtime,formula,expected):
    assert runtime.fx.evaluate(formula)==expected

@pytest.mark.parametrize('formula',[
 '$"{}"','$"{ /* empty */ }"','$"{\n// empty\n}"', '$"}', '$"unterminated',
 '$"{1"', '$"{With({a:1},a)"', '$"{ $\"unterminated }"', '$"literal }"', '$"{(1)}extra}"'])
def test_malformed_interpolation_has_specific_parse_error_and_span(formula):
    with pytest.raises(FxError) as caught:Parser(formula).parse()
    assert caught.value.kind=='Validation'
    assert 0<=caught.value.start<=caught.value.end<=len(formula)


def test_nested_source_locations_and_dependency_visitors(runtime):
    formula='$"😀 before {$\"{UnknownVariable}\"} after"'
    runtime.binder.errors.clear();node=runtime.fx.parse(formula);runtime.binder.bind(node,BindScope())
    error=next(error for _,error in runtime.binder.errors if error.kind=='Name')
    assert formula[error.start:error.end]=='UnknownVariable'
    nodes=list(walk(Parser('$"{With({r:7},$\"{Abs(r)}\")}"').parse()))
    assert {call_name(n.children[0]) for n in nodes if n.kind=='call'}=={'With','Abs'}


def test_interpolation_preserves_strong_single_enum_identity(runtime):
    runtime.environment['enum_mode']='strong';runtime.analyze()
    value=runtime.fx.evaluate('$"{JSONFormat.IndentFour}"')
    assert isinstance(value,EnumValue) and value.member=='IndentFour'
    assert runtime.fx.evaluate('$"{JSONFormat.IndentFour}{JSONFormat.FlattenValueTables}"').backing=='4_'
    assert runtime.fx.evaluate('$"^{Match.MultipleDigits}$"').namespace=='Match'
    assert runtime.fx.evaluate('IsMatch("123",$"^{Match.MultipleDigits}$")')
    assert runtime.fx.evaluate('$"flags {JSONFormat.IndentFour}"')=='flags 4'

@pytest.mark.parametrize('formula',[
 '$"{[1,2]}"','$"{ {A:1} }"','$"{App}"','$"{Icon.Add}"'])
def test_invalid_interpolation_is_guarded_at_binding_and_direct_execution(runtime,formula):
    runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(formula),BindScope())
    assert any(error.kind=='Type' for _,error in runtime.binder.errors)
    with pytest.raises(FxError) as caught:runtime.fx.evaluate(formula)
    assert caught.value.kind=='Type'


def test_interpolation_evaluates_behavior_segments_in_order_and_combines_errors(runtime):
    ctx=Context(runtime,behavior=True)
    runtime.fx.evaluate('Set(n,0)',ctx)
    assert runtime.fx.evaluate('$"{Set(n,n+1);n}-{Set(n,n+1);n}"',ctx)=='1-2'
    assert runtime.globals['n']==2
    with pytest.raises(FxError) as caught:runtime.fx.evaluate('$"{1/0}-{Set(n,7);n}-{Error({Kind:ErrorKind.Network,Message:\"fixture\"})}"',ctx)
    assert len(caught.value.records())==2 and runtime.globals['n']==7
    assert runtime.fx.evaluate('IfError($"{1/0}{1/0}",CountRows(AllErrors))')=='2'
    with pytest.raises(FxError):runtime.fx.evaluate('$"{Set(n,99);n}"')
    assert runtime.globals['n']==7


def test_interpolated_named_formula_cycles_stay_local_and_udfs_recalculate(runtime):
    runtime.fx.set_definitions('=A=$"{B}";B=$"{A}";Healthy=$"ok {7}";Format(x:Number):Text=$"value {x}";')
    with pytest.raises(FxError):runtime.fx.evaluate('A')
    assert runtime.fx.evaluate('Healthy')=='ok 7'
    assert runtime.fx.evaluate('Format(8)')=='value 8'

@pytest.mark.parametrize('number',['float','decimal'])
@pytest.mark.parametrize('language,expected',[('en-US','1.25 · true'),('fr-CA','1,25 · true')])
def test_numeric_locale_is_the_live_host_contract(runtime,number,language,expected):
    runtime.environment.update(number_mode=number,language=language);runtime.analyze()
    assert runtime.fx.evaluate('$"{1.25} · {true}"')==expected


def test_named_formula_recovery_tracks_semicolons_inside_interpolation():
    defs,errors=Parser('Good=$"ok";Bad=$"{1+;}";Later=$"{7}";').definitions()
    assert len(errors)==1 and set(defs)=={'Good','Later'}
    defs,errors=Parser('Good=$"ok";Bad=$"{}";Later=$"{7}";').definitions()
    assert len(errors)==1 and set(defs)=={'Good','Later'}


def test_interpolation_source_roundtrip_and_export_excludes_configuration(tmp_path):
    from io import BytesIO
    from zipfile import ZipFile
    from powerapps_sim.fixtures import interpolation_project
    from powerapps_sim.source import Project,load_yaml,dump_yaml
    p=interpolation_project(tmp_path/'p');path='Src/interpolation.pa.yaml';source=p.documents[path]
    assert dump_yaml(load_yaml(source))==dump_yaml(load_yaml(dump_yaml(load_yaml(source))))
    p.update_source(path,source);restored=Project(p.root)
    assert restored.documents[path]==source
    assert '$"' in p.export_control('LeftPanel')
    assert 'Compose' in p.export_control('InterpolationPanel')
    with ZipFile(BytesIO(p.export())) as archive:
        assert set(archive.namelist())=={path}
        assert archive.read(path).decode()==source
    with pytest.raises(Exception):p.update_source(path,'Screens: [')
    assert p.documents[path]==source
    assert (p.root/'drafts'/path).read_text()=='Screens: ['

@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('number',['float','decimal'])
def test_interpolation_components_workflow_preserves_owner(tmp_path,language,number):
    from powerapps_sim.fixtures import interpolation_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    p=interpolation_project(tmp_path/'p');w=Workspace(tmp_path,p.root)
    try:
        w.runtime.store.patch('Snapshots',{}, {'Title':'Fictional owner row','Quantity':99,'Preview':'owner'})
        w.runtime.restart();before=deepcopy(w.ai.read_runtime());rows=deepcopy(w.runtime.store.rows('Snapshots'))
        entry=w.workflows.catalog()['scenarios'][0]
        result=w.workflows.run({**entry['scenario'],'environment':{'enum_mode':'strong','language':language,'number_mode':number}},expected_revision=revision(p.root))
        assert result['status']=='passed',[s for s in result['steps'] if s['status']!='passed']
        assert len(result['steps'])==41 and not result['diagnostics']
        assert len(result['collections']['results'][0])==20
        assert result['types']['collections']['results']['row']['fields']['NestedText']['kind']=='Text'
        assert w.ai.read_runtime()==before and w.runtime.store.rows('Snapshots')==rows
    finally:w.runtime.close()


def test_quoted_reserved_words_remain_identifiers_inside_and_outside_interpolation(runtime):
    assert runtime.fx.evaluate('With({\'true\':7,\'not\':3,\'or\':2,\'as\':1},$"{\'true\'}/{\'not\'}/{\'or\'}/{\'as\'}")')=='7/3/2/1'
    assert runtime.fx.evaluate('With({\'false\':8},\'false\')')==8
    with pytest.raises(FxError):Parser("1 'or' 2").parse()

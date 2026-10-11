"""Authored AST ownership and static findings do not execute the application."""
from copy import deepcopy
from pathlib import Path
import pytest
from ruamel.yaml.scalarstring import LiteralScalarString,FoldedScalarString
from powerapps_sim.source import Project,dump_yaml,load_yaml
from powerapps_sim.runtime import Runtime,serial
from powerapps_sim.syntax import FxError

APP='Src/app.pa.yaml';MASTER='Src/Components/Unit.pa.yaml';SCREEN='Src/Screens/Home.pa.yaml'

def project(tmp_path):
    p=Project(tmp_path/'p')
    app={'App':{'Properties':{'StartScreen':'=Home','OnStart':'=Set(boot,1);Clear(reports)','OnError':'=Collect(reports,AllErrors)',
        'Formulas':LiteralScalarString('=Good=10;\nFirstBad=Missing_1+Missing_1;\nSecondBad=Missing_1+Missing_1;\nConsumer=FirstBad;\nBadType := Type({N:NonType_1});\nBadReturn(n:Number):Number={N:n};\nHealthy(n:Number):Number=n*2;')}}}
    custom={
        'Seed':{'PropertyKind':'Input','DataType':'Number','Default':'=5'},
        'Total':{'PropertyKind':'Output','DataType':'Number','Default':'=Unit.Seed'},
        'Bad':{'PropertyKind':'Output','DataType':'Number','Default':'=Missing_1'},
        'BadAgain':{'PropertyKind':'Output','DataType':'Number','Default':'=Missing_1'},
        'BadRecord':{'PropertyKind':'Output','DataType':'Record','Default':'={N:Missing_1}'},
        'Read':{'PropertyKind':'OutputFunction','ReturnType':'Number','Parameters':[{'n':{'IsOptional':True,'DataType':'Number','Default':'=MissingArg_1'}}],'Default':'=n'},
        'ReadAgain':{'PropertyKind':'OutputFunction','ReturnType':'Number','Parameters':[{'n':{'IsOptional':True,'DataType':'Number','Default':'=MissingArg_1'}}],'Default':'=n'},
        'RecordFn':{'PropertyKind':'OutputFunction','ReturnType':'Number','Parameters':[{'row':{'IsOptional':True,'DataType':'Record','Default':'={N:MissingRecord_1}'}}],'Default':'=row.N'},
    }
    master={'ComponentDefinitions':{'Unit':{'DefinitionType':'CanvasComponent','AccessAppScope':False,'CustomProperties':custom,'Properties':{'Width':'=200','Height':'=100'}}}}
    screen={'Screens':{'Home':{'Children':[
        {'Left':{'Control':'CanvasComponent','ComponentName':'Unit','Properties':{'Seed':'=Good'}}},
        {'Right':{'Control':'CanvasComponent','ComponentName':'Unit','Properties':{'Total':'=999'}}},
        {'First':{'Control':'ModernText@1.0.0','Properties':{'Text':'=Text(Missing_1)'}}},
        {'Second':{'Control':'ModernText@1.0.0','Properties':{'Text':'=Text(Missing_1)'}}},
        {'ReadNamed':{'Control':'ModernText@1.0.0','Properties':{'Text':'=Text(Consumer)'}}},
        {'ReadRecord':{'Control':'ModernText@1.0.0','Properties':{'Text':'=Text(Left.BadRecord.N)'}}},
        {'CallRecord':{'Control':'ModernButton@1.0.0','Properties':{'OnSelect':'=Set(answer,Left.RecordFn())'}}},
        {'Healthy':{'Control':'ModernText@1.0.0','Properties':{'Text':'=Text(Left.Total)'}}},
    ]}}}
    for source,data in [(APP,app),(MASTER,master),(SCREEN,screen)]:p.update_source(source,dump_yaml(data))
    p.config['historical_checker']={'results':[{'message':'Historical example','line':12,'source':'Old.pa.yaml'}]};p.save_config();return p

@pytest.fixture(params=[('float','en-CA'),('float','fr-CA'),('decimal','en-CA'),('decimal','fr-CA')])
def r(tmp_path,request):
    p=project(tmp_path);p.config['environment'].update(number_mode=request.param[0],language=request.param[1]);p.save_config()
    r=Runtime(p);yield r;r.close()

def source_line(r,needle):return next(i+1 for i,line in enumerate(r.project.documents[APP].splitlines()) if needle in line)

def findings(r,member):return [d for d in r.bind_diagnostics if d.get('expression_member')==member]

def test_named_definitions_duplicate_occurrences_and_dependency_ownership(r):
    first=findings(r,'App.Formulas.FirstBad');second=findings(r,'App.Formulas.SecondBad')
    assert len(first)==len(second)==2
    assert all(d['source']==APP and d['line']==source_line(r,'FirstBad=') for d in first)
    assert all(d['line']==source_line(r,'SecondBad=') for d in second)
    assert len({(d['start'],d['end']) for d in first})==2
    assert not findings(r,'App.Formulas.Consumer')
    for row in first+second:assert r.project.app['Formulas'][row['start']:row['end']]=='Missing_1'
    assert r.fx.evaluate('Healthy(4)')==8


def test_alias_and_return_contract_errors_have_their_own_declaration(r):
    types=findings(r,'App.Formulas.BadType');returns=findings(r,'App.Formulas.BadReturn')
    assert types and returns and all(d['source']==APP for d in types+returns)
    assert all(d['line']==source_line(r,'BadType :=') for d in types) and all(d['line']==source_line(r,'BadReturn(n:') for d in returns)
    assert any(r.project.app['Formulas'][d['start']:d['end']]=='NonType_1' for d in types)


def test_duplicate_component_defaults_and_parameter_defaults_keep_distinct_lines(r):
    locations=[]
    for member in ('Unit.Bad','Unit.BadAgain','Unit.Read.n.Default','Unit.ReadAgain.n.Default'):
        rows=findings(r,member);assert len(rows)==1
        row=rows[0];locations.append(row['line']);assert row['source']==MASTER
        assert 'Missing' in r.project.documents[MASTER].splitlines()[row['line']-1]
    assert len(set(locations))==4
    assert len(findings(r,'Unit.BadRecord'))==1 and len(findings(r,'Unit.RecordFn.row.Default'))==1
    assert not any(d['member']=='CallRecord.OnSelect' and 'MissingRecord_1' in d['message'] for d in r.bind_diagnostics)
    assert not any(d['member']=='ReadRecord.Text' and 'Missing_1' in d['message'] for d in r.bind_diagnostics)


def test_duplicate_control_rules_use_ast_origin_not_first_text_match(r):
    first=findings(r,'First.Text');second=findings(r,'Second.Text')
    assert len(first)==len(second)==1 and first[0]['source']==second[0]['source']==SCREEN
    assert first[0]['line']!=second[0]['line']
    for row in first+second:assert 'Text: =Text(Missing_1)' in r.project.documents[SCREEN].splitlines()[row['line']-1]


def test_illegal_host_override_is_located_at_host_and_runtime_remains_definition_owned(r):
    rows=findings(r,'Right.Total');assert len(rows)==1
    assert rows[0]['source']==SCREEN and 'Total: =999' in r.project.documents[SCREEN].splitlines()[rows[0]['line']-1]
    assert r.fx.evaluate('Right.Total')==5 and r.refs['Home/Right'].expression('Total').source==MASTER


def test_binding_inspection_is_detached_and_never_starts_or_runs_callbacks(r,monkeypatch):
    before=deepcopy(serial([r.globals,r.collections,r.component_state,r.diagnostics,r.project.config['historical_checker']]))
    monkeypatch.setattr(r.fx,'evaluate',lambda *_:pytest.fail('Inspection evaluated Power Fx'))
    r.analysis()
    assert not r.started and serial([r.globals,r.collections,r.component_state,r.diagnostics,r.project.config['historical_checker']])==before
    assert r.project.config['historical_checker']['results'][0]['line']==12


@pytest.mark.parametrize('style',[LiteralScalarString,FoldedScalarString])
def test_multiline_defaults_parse_type_and_name_errors_use_physical_yaml_lines(tmp_path,style):
    p=project(tmp_path);data=load_yaml(p.documents[MASTER]);custom=data['ComponentDefinitions']['Unit']['CustomProperties']
    custom['Read']['Parameters'][0]['n']['Default']=style('=Coalesce(Blank(),\nMissingArg_1)')
    custom['ReadAgain']['Parameters'][0]['n']['Default']=style('=Coalesce(Blank(),\nMissingArg_1)')
    custom['Bad']['Default']=style('=If(\ntrue,')
    custom['BadAgain']['Default']=style('=If(\ntrue,')
    p.update_source(MASTER,dump_yaml(data));r=Runtime(p)
    try:
        first=findings(r,'Unit.Read.n.Default');second=findings(r,'Unit.ReadAgain.n.Default')
        assert first and second and first[0]['line']!=second[0]['line']
        assert all('MissingArg_1' in p.documents[MASTER].splitlines()[d['line']-1] for d in first+second)
        one=findings(r,'Unit.Bad');two=findings(r,'Unit.BadAgain');assert one and two and one[0]['line']!=two[0]['line']
    finally:r.close()


def test_app_source_follows_the_selected_mapping_not_an_earlier_app(tmp_path):
    p=project(tmp_path);p.update_source('Src/zzz-app.pa.yaml',dump_yaml({'App':{'Properties':{'Formulas':LiteralScalarString('=Good=7;\nBad=MissingLast_1;')}}}))
    r=Runtime(p)
    try:
        assert r.app_source()=='Src/zzz-app.pa.yaml' and r.fx.evaluate('Good')==7
        row=findings(r,'App.Formulas.Bad')[0];assert row['source']==r.app_source() and 'MissingLast_1' in p.documents[row['source']].splitlines()[row['line']-1]
    finally:r.close()


@pytest.mark.parametrize('variant,key,value',[
    ('parameter','DataType','Void'),('parameter','DataType','UnknownType_1'),
    ('return','ReturnType','Void'),('return','ReturnType','UnknownType_1'),
    ('parameters','Parameters','invalid'),('kind','PropertyKind','UnknownKind_1'),
])
def test_signature_metadata_findings_point_to_declaration_fields(tmp_path,variant,key,value):
    p=project(tmp_path);data=load_yaml(p.documents[MASTER]);custom=data['ComponentDefinitions']['Unit']['CustomProperties']['Read']
    if variant=='parameter':custom['Parameters'][0]['n'][key]=value
    else:custom[key]=value
    p.update_source(MASTER,dump_yaml(data));r=Runtime(p)
    try:
        member='Unit.Read.'+('n.' if variant=='parameter' else '')+key
        rows=findings(r,member);assert rows
        assert all(d['source']==MASTER and key+':' in p.documents[MASTER].splitlines()[d['line']-1] for d in rows)
        assert not r.started and not r.globals
    finally:r.close()


def test_alias_signature_fault_keeps_alias_source_and_never_mutates_cached_error(r):
    original=r.binder.type_errors['BadType'];before=(original.source,original.expression_origin,hasattr(original,'component_declaration'))
    with pytest.raises(FxError) as caught:r.component_signature('Read',{'PropertyKind':'OutputFunction','ReturnType':'Number','Parameters':[{'n':{'DataType':'BadType'}}]})
    error=caught.value
    assert error.expression_origin.member=='App.Formulas.BadType' and error.expression_origin.source==APP
    assert (original.source,original.expression_origin,hasattr(original,'component_declaration'))==before


def test_replacing_definitions_clears_analysis_owner_ids_and_manual_bind_ownership(r):
    assert r.binder.expression_owners and r.binder.expression_roots
    r.fx.set_definitions('=Good=9;')
    assert not r.binder.expression_owners and not r.binder.expression_roots
    from powerapps_sim.binding import BindScope
    r.binder.errors.clear();r.binder.bind(r.fx.parse('=MissingManual_1'),BindScope(),('manual','',0))
    assert all(key[0]==('manual','',0) for key,error in r.binder.errors)
    assert r.fx.evaluate('Good')==9


@pytest.mark.parametrize('key,member',[('parameter','n.DataType'),('return','ReturnType')])
def test_runtime_signature_fault_retains_master_declaration_and_prevents_body(tmp_path,key,member):
    p=project(tmp_path);data=load_yaml(p.documents[MASTER]);custom=data['ComponentDefinitions']['Unit']['CustomProperties']['Read']
    if key=='parameter':custom['Parameters'][0]['n']['DataType']='Void'
    else:custom['ReturnType']='Void'
    p.update_source(MASTER,dump_yaml(data));r=Runtime(p)
    try:
        with pytest.raises(FxError) as caught:r.fx.evaluate('Left.Read(2)')
        error=caught.value
        assert error.record()['Source']=='Home/Left.Read.'+member and error.expression_origin.source==MASTER
        assert member.split('.')[-1]+':' in p.documents[MASTER].splitlines()[error.expression_origin.line-1]
        assert not r.globals and not r.collections
    finally:r.close()


@pytest.mark.parametrize('key',['parameter','return'])
def test_missing_signature_fields_anchor_the_existing_declaration(tmp_path,key):
    p=project(tmp_path);data=load_yaml(p.documents[MASTER]);custom=data['ComponentDefinitions']['Unit']['CustomProperties']['Read']
    if key=='parameter':custom['Parameters'][0]['n'].pop('DataType')
    else:custom.pop('ReturnType')
    p.update_source(MASTER,dump_yaml(data));r=Runtime(p)
    try:
        rows=findings(r,'Unit.Read.'+('n.DataType' if key=='parameter' else 'DataType'));assert rows
        assert all(d['source']==MASTER and d['line']>1 for d in rows)
    finally:r.close()


@pytest.mark.parametrize('language',['en-CA','fr-CA'])
@pytest.mark.parametrize('number',['float','decimal'])
def test_public_binding_fixture_isolates_errors_and_preserves_complete_owner(tmp_path,language,number):
    from powerapps_sim.fixtures import binding_locations_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision,data_revision
    p=binding_locations_project(tmp_path/'public');w=Workspace(tmp_path,p.root)
    try:
        w.runtime.state();before=deepcopy(w.ai.read_runtime());source=revision(p.root);data=data_revision(w.runtime.store);deps=w.ai.read_dependencies()
        scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);scenario['environment'].update(language=language,number_mode=number,enum_mode='strong')
        result=w.workflows.run(scenario,expected_revision=source)
        assert result['status']=='passed' and len(result['steps'])==17 and len(result['diagnostics'])==11,result['steps']
        assert w.ai.read_runtime()==before and revision(p.root)==source and data_revision(w.runtime.store)==data and w.ai.read_dependencies()==deps
        assert len(p.documents)==2 and all('expression_member' not in text for text in p.documents.values())
    finally:w.runtime.close()

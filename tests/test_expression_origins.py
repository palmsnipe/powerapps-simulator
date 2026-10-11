"""Component defaults, callback ownership, source spans and reset boundaries."""
from copy import deepcopy
import pytest
from powerapps_sim.source import Project,dump_yaml,load_yaml
from powerapps_sim.runtime import Runtime,serial
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError

APP='Src/app.pa.yaml';MASTER='Src/Components/Panel.pa.yaml'

def project(tmp_path):
    p=Project(tmp_path/'project')
    custom={
        'Seed':{'PropertyKind':'Input','DataType':'Number','RaiseOnReset':True,'Default':'=5'},
        'Record':{'PropertyKind':'Input','DataType':'Record','RaiseOnReset':True,'Default':'={N:0,Label:""}'},
        'Total':{'PropertyKind':'Output','DataType':'Number','Default':'=Coalesce(local,Panel.Seed)'},
        'Resets':{'PropertyKind':'Output','DataType':'Number','Default':'=Coalesce(resets,0)'},
        'Caption':{'PropertyKind':'InputFunction','ReturnType':'Text','Parameters':[{'n':{'IsOptional':True,'DataType':'Number','Default':'=2'}}],'Default':'="Definition " & Text(n)'},
        'RowsTotal':{'PropertyKind':'OutputFunction','ReturnType':'Number','Parameters':[{'rows':{'IsOptional':True,'DataType':'Table','Default':'=Table({ID:1,N:2},{ID:2,N:3})'}}],'Default':'=Sum(rows,N+Rand())'},
        'BadDefault':{'PropertyKind':'Function','ReturnType':'Number','Parameters':[{'n':{'IsOptional':True,'DataType':'Number','Default':'=1/0'}}],'Default':'=n'},
        'BadDefaultAgain':{'PropertyKind':'Function','ReturnType':'Number','Parameters':[{'n':{'IsOptional':True,'DataType':'Number','Default':'=1/0'}}],'Default':'=n'},
        'BadCast':{'PropertyKind':'Function','ReturnType':'Number','Parameters':[{'n':{'IsOptional':True,'DataType':'Number','Default':'="bad"'}}],'Default':'=n'},
        'BadReturn':{'PropertyKind':'Function','ReturnType':'Number','Parameters':[],'Default':'="bad"'},
        'NamedFailure':{'PropertyKind':'Function','ReturnType':'Number','Parameters':[{'n':{'IsOptional':True,'DataType':'Number','Default':'=2'}}],'Default':'=Divide(n,0)'},
        'Fault':{'PropertyKind':'Output','DataType':'Number','Default':'=1/0'},
        'Change':{'PropertyKind':'Action','ReturnType':'None','Parameters':[{'n':{'IsOptional':True,'DataType':'Number','Default':'=3'}}],'Default':'=Set(local,n);Panel.Changed(n);Blank()'},
        'Changed':{'PropertyKind':'Event','ReturnType':'None','Parameters':[{'n':{'IsOptional':True,'DataType':'Number','Default':'=4'}}],'Default':'=Blank()'},
    }
    master={'ComponentDefinitions':{'Panel':{'DefinitionType':'CanvasComponent','AccessAppScope':False,'CustomProperties':custom,'Properties':{'OnReset':'=Set(resets,Coalesce(resets,0)+1);Set(local,Panel.Seed)'},'Children':[{'Draft':{'Control':'Classic/TextInput@2.3.2','Properties':{'Default':'=Text(Panel.Total)'}}}]}}}
    app={'App':{'Properties':{'StartScreen':'=Home','OnStart':'=Set(seed,10);Set(record,{N:1,Label:"Fictional"});Clear(history);Clear(failures)','OnError':'=Collect(failures,AllErrors)','Formulas':'=Divide(n:Number,d:Number):Number=n/d;'}},'Screens':{'Home':{'Children':[
        {'Left':{'Control':'CanvasComponent','ComponentName':'Panel','Properties':{'Seed':'=seed','Record':'=record','Caption':'="Host " & Text(n)','Changed':'=Collect(history,{Panel:"left",N:n})'}}},
        {'Right':{'Control':'CanvasComponent','ComponentName':'Panel','Properties':{'Changed':'=Collect(history,{Panel:"right",N:n})'}}},
        {'Call':{'Control':'ModernButton@1.0.0','Properties':{'OnSelect':'=Left.BadDefault()'}}},
        {'Probe':{'Control':'ModernText@1.0.0','Properties':{'Text':'=Text(Left.RowsTotal())'}}},
    ]}}}
    p.update_source(APP,dump_yaml(app));p.update_source(MASTER,dump_yaml(master));p.config['environment']['random_seed']=20261014;p.save_config();return p

@pytest.fixture(params=[('float','en-CA'),('float','fr-CA'),('decimal','en-CA'),('decimal','fr-CA')])
def r(tmp_path,request):
    p=project(tmp_path);p.config['environment'].update(number_mode=request.param[0],language=request.param[1]);p.save_config()
    r=Runtime(p);r.restart();yield r;r.close()

@pytest.mark.parametrize('name,source,member,needle',[
 ('BadDefault',MASTER,'Home/Left.BadDefault.n.Default','1/0'),
 ('BadDefaultAgain',MASTER,'Home/Left.BadDefaultAgain.n.Default','1/0'),
 ('BadCast',MASTER,'Home/Left.BadCast.n.Default','"bad"'),
 ('BadReturn',MASTER,'Home/Left.BadReturn','"bad"'),
 ('NamedFailure',APP,'App.Formulas.Divide','n/d'),
])
def test_omitted_argument_and_return_errors_retain_declaration(r,name,source,member,needle):
    with pytest.raises(FxError) as caught:r.fx.evaluate('Left.'+name+'()')
    error=caught.value;origin=error.expression_origin
    assert error.source==member and origin.source==source and origin.member==member
    assert needle in str(origin.formula)[error.start:error.end]
    r.diagnostic(error,APP,'caller','=Left.'+name+'()')
    diagnostic=r.diagnostics[-1]
    assert diagnostic['source']==source and diagnostic['expression_member']==member and diagnostic['line']==origin.line_at(error.start)
    assert r.fx.evaluate('Right.Total')==5 and not r.collections['failures']


def test_duplicate_defaults_use_distinct_yaml_lines(r):
    lines=[]
    for name in ('BadDefault','BadDefaultAgain'):
        with pytest.raises(FxError) as caught:r.fx.evaluate('Left.'+name+'()')
        origin=caught.value.expression_origin;lines.append(origin.line)
        assert '1/0' in r.project.documents[MASTER].splitlines()[origin.line-1]
    assert lines[0]!=lines[1]


def test_supplied_arguments_bypass_bad_defaults_and_effects_validate_first(r):
    assert r.fx.evaluate('Left.BadDefault(7)')==7 and r.fx.evaluate('Left.BadCast(8)')==8
    with pytest.raises(FxError):r.fx.evaluate('Left.Change("bad")',Context(r,behavior=True))
    assert not r.collections['history'] and r.fx.evaluate('Left.Total')==10
    r.fx.evaluate('Left.Change()',Context(r,behavior=True));r.drain_events()
    assert r.fx.evaluate('Left.Total')==3 and r.collections['history']==[{'Panel':'left','N':3}]
    r.fx.evaluate('Right.Changed()',Context(r,behavior=True));r.drain_events()
    assert r.collections['history'][-1]=={'Panel':'right','N':4}


def test_input_function_and_definition_owned_outputs_use_right_sources(r):
    assert r.fx.evaluate('Left.Caption()')=='Host 2' and r.fx.evaluate('Right.Caption()')=='Definition 2'
    assert r.refs['Home/Left'].expression('Caption').source==APP
    assert r.refs['Home/Right'].expression('Caption').source==MASTER
    r.refs['Home/Left'].control.properties['BadReturn']='=99'
    with pytest.raises(FxError) as caught:r.fx.evaluate('Left.BadReturn()')
    assert caught.value.expression_origin.source==MASTER
    assert r.refs['Home/Left'].expression('Total').source==MASTER


def test_pure_query_owner_spans_and_readonly_inspection(r):
    ref=r.refs['Home/Probe'];first=ref.property('Text')
    before={k:v.getstate() for k,v in r.reactive.streams.items()}
    report=r.reactive.describe(query='RowsTotal',limit=500)
    rows=[row for row in r.reactive.describe(query='Home/Left',limit=500)['rows'] if row['kind'] in ('query','query-row')]
    assert rows and all(row['source']==MASTER and row['line'] for row in rows)
    assert all(row['path']=='Home/Left' for row in rows)
    assert any(row['formula']=='N+Rand()' for row in rows)
    r.invalidate();assert ref.property('Text')==first and before=={k:v.getstate() for k,v in r.reactive.streams.items()}
    assert r.reactive.describe(query='RowsTotal',limit=500)['rows']
    assert not r.collections['history'] and not r.collections['failures']


def test_default_reset_and_multiple_flagged_inputs_preserve_peer_and_draft(r):
    r.state();left=r.refs['Home/Left'];right=r.refs['Home/Right'];draft=r.refs['Home/Left/Draft']
    r.event(draft.path,'OnChange','72');r.state();assert draft.property('Text')=='72'
    r.fx.evaluate('Set(seed,20);Set(record,{N:2,Label:"Fictional changed"})',Context(r,behavior=True))
    # Reading inputs is pure; reset happens when lifecycle work is drained.
    assert left.property('Seed')==20 and left.property('Resets')==0 and draft.property('Text')=='20'
    r.drain_events();r.state()
    assert left.property('Resets')==1 and draft.property('Text')=='20' and right.property('Resets')==0
    r.fx.evaluate('Reset(Left)',Context(r,behavior=True));r.drain_events()
    assert left.property('Resets')==2 and right.property('Resets')==0
    assert r.refs['Home/Left'].expression('Seed').source==APP and right.expression('Seed').source==MASTER


def test_uncaught_default_report_observed_at_caller_and_export_unchanged(r):
    before=r.project.export();r.event('Home/Call','OnSelect');r.state()
    row=r.collections['failures'][0]
    assert row['Source']=='Home/Left.BadDefault.n.Default' and row['Observed']=='Home/Call.OnSelect'
    diagnostic=next(row for row in r.diagnostics if row.get('observed')=='Home/Call.OnSelect')
    assert diagnostic['source']==MASTER and diagnostic['expression_member']==row['Source']
    assert r.project.export()==before and set(row)<= {'Kind','Message','Source','Observed','Details'}

@pytest.mark.parametrize('style',['|','>'])
def test_multiline_component_formula_lines(tmp_path,style):
    p=project(tmp_path)
    import re
    text=re.sub(r'(?m)^( +)Default: =1/0$',lambda m:m[1]+'Default: '+style+'-\n'+m[1]+'  =Coalesce(Blank(),\n'+m[1]+'  1/0)',p.documents[MASTER],count=1)
    p.update_source(MASTER,text);r=Runtime(p);r.restart()
    try:
        with pytest.raises(FxError) as caught:r.fx.evaluate('Left.BadDefault()')
        origin=caught.value.expression_origin
        assert '1/0' in p.documents[MASTER].splitlines()[origin.line_at(caught.value.start)-1]
    finally:r.close()


def test_readonly_contract_origins_are_detached_and_never_invoke_defaults(r,monkeypatch):
    from powerapps_sim.component_inspection import describe
    before=deepcopy(serial([r.globals,r.collections,r.component_state,r.diagnostics]))
    monkeypatch.setattr(r.fx,'evaluate',lambda *_:pytest.fail('Inspection evaluated a default'))
    report=describe(r);left=report['Home/Left']['properties'];right=report['Home/Right']['properties']
    assert left['Caption']['source']==APP and right['Caption']['source']==MASTER
    origin=left['BadDefault']['parameter_origins']['n']
    assert origin['source']==MASTER and '1/0' in r.project.documents[MASTER].splitlines()[origin['line']-1]
    report['Home/Left']['properties']['BadDefault']['parameter_origins']['n']['line']=1
    assert describe(r)['Home/Left']['properties']['BadDefault']['parameter_origins']['n']['line']!=1
    assert serial([r.globals,r.collections,r.component_state,r.diagnostics])==before


@pytest.mark.parametrize('language',['en-CA','fr-CA'])
@pytest.mark.parametrize('number',['float','decimal'])
def test_public_split_file_workflow_preserves_complete_owner(tmp_path,language,number):
    from powerapps_sim.fixtures import component_origins_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision,data_revision
    p=component_origins_project(tmp_path/'public');w=Workspace(tmp_path,p.root)
    try:
        w.runtime.state();before=deepcopy(w.ai.read_runtime());deps=w.ai.read_dependencies();data=data_revision(w.runtime.store);source=revision(p.root)
        scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);scenario['environment'].update(language=language,number_mode=number,enum_mode='strong')
        result=w.workflows.run(scenario,expected_revision=source)
        assert result['status']=='passed' and len(result['steps'])==17 and not result['diagnostics'],result['steps']
        assert w.ai.read_runtime()==before and w.ai.read_dependencies()==deps and data_revision(w.runtime.store)==data and revision(p.root)==source
        assert len(p.documents)==2 and all('expression_member' not in text for text in p.documents.values())
    finally:w.runtime.close()


def test_default_and_reset_origin_master_after_runtime_effects(r):
    source=r.project.parsed[MASTER]['ComponentDefinitions']['Panel']['Properties']
    source['OnReset']='=Set(resets,Coalesce(resets,0)+1);1/0'
    r.fx.evaluate('Reset(Left)',Context(r,behavior=True));r.drain_events()
    diagnostic=next(d for d in r.diagnostics if d.get('expression_member')=='Home/Left.OnReset')
    assert diagnostic['source']==MASTER and r.fx.evaluate('Left.Resets')==1 and r.fx.evaluate('Right.Resets')==0
    assert r.collections['failures'][0]['Source']=='Home/Left.OnReset'
    assert r.collections['failures'][0]['Observed']=='Home/Left.OnReset'


def test_host_callback_failure_retains_instance_override(r):
    r.refs['Home/Left'].control.properties['Changed']='=1/0'
    with pytest.raises(FxError) as caught:r.fx.evaluate('Left.Change()',Context(r,behavior=True))
    error=caught.value
    assert error.record()['Source']=='Home/Left.Changed' and error.expression_origin.source==APP
    assert r.fx.evaluate('Left.Total')==3 and r.fx.evaluate('Right.Total')==5


def test_data_property_coercion_origin_and_app_property_origin(r):
    definition=r.project.parsed[MASTER]['ComponentDefinitions']['Panel']['CustomProperties']
    definition['Seed']['Default']='="bad"';r.invalidate()
    with pytest.raises(FxError) as caught:r.fx.evaluate('Right.Seed')
    assert caught.value.expression_origin.source==MASTER and caught.value.record()['Source']=='Home/Right.Seed'
    r.project.app['MinScreenWidth']='=1/0';r.invalidate()
    with pytest.raises(FxError) as caught:r.fx.evaluate('App.MinScreenWidth')
    assert caught.value.expression_origin.source==APP and caught.value.record()['Source']=='App.MinScreenWidth'

"""Authored names cannot be hidden or mistaken for lexical metadata."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import pytest
from powerapps_sim.binding import BindScope, value_type
from powerapps_sim.fx import Context
from powerapps_sim.inspection import observe, schema
from powerapps_sim.scopes import ScopeFrame
from powerapps_sim.runtime import serial
from powerapps_sim.syntax import FxError

NAMES=['__count','__sources__','__source_rows__','__scope_alias__','__open__','sources','aliased','open_schema']

@pytest.mark.parametrize('name',NAMES)
@pytest.mark.parametrize('template,expected',[
 ('With({NAME:3},NAME+1)',4),
 ('Sum(Table({NAME:2},{NAME:5}),NAME)',7),
 ('Sum(Table({NAME:2},{NAME:5}) As R,R.NAME)',7),
 ('Concat(Table({NAME:"Fictional"}),NAME)','Fictional'),
 ('First(AddColumns(Table({NAME:2}),Twice,NAME*2)).Twice',4),
 ('Sum(ForAll(Table({NAME:2},{NAME:5}),{Result:NAME*2}),Result)',14),
])
def test_authored_names_in_implicit_and_aliased_record_scopes(runtime,name,template,expected):
    formula=template.replace('NAME',name)
    runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(formula),BindScope())
    assert not runtime.binder.errors
    assert runtime.fx.evaluate(formula)==expected

@pytest.mark.parametrize('name',NAMES)
def test_nested_qualified_source_scopes_cannot_collide_with_authored_fields(runtime,name):
    formula=f'With({{Rows:Table({{{name}:2}},{{{name}:5}})}},Sum(Rows,Sum(Table({{{name}:10}}) As Inner,Rows[@{name}]+Inner.{name})))'
    assert runtime.fx.evaluate(formula)==27
    assert runtime.fx.evaluate('With({Rows:Table({__source_rows__:{Rows:{Value:900}},Value:2})},Sum(Rows,Rows[@Value]))')==2

@pytest.mark.parametrize('name',NAMES)
def test_names_in_closed_rows_do_not_enable_unknown_identifiers(runtime,name):
    formula=f'Sum(Table({{{name}:true}}),Missing)'
    runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(formula),BindScope())
    assert any(e.kind=='Name' and 'Missing' in e.message for _,e in runtime.binder.errors)
    with pytest.raises(FxError):runtime.fx.evaluate(formula)

@pytest.mark.parametrize('name',NAMES)
def test_parameter_frame_types_participate_in_ast_cache_keys(runtime,name):
    first=runtime.fx.bound_node(name,Context(runtime,frames=[{name:2}]))
    second=runtime.fx.bound_node(name,Context(runtime,frames=[{name:'Fictional'}]))
    assert first is not second
    assert runtime.fx.node_types[id(first)].kind=='Number'
    assert runtime.fx.node_types[id(second)].kind=='Text'
    assert runtime.fx.evaluate(name,Context(runtime,frames=[{name:'Fictional'}]))=='Fictional'

@pytest.mark.parametrize('name',NAMES)
def test_read_only_values_and_schemas_keep_authored_names(runtime,name,monkeypatch):
    value={name:[{name:3,'Caption':'Fictional'}]}
    runtime.globals[name]=deepcopy(value);runtime.binder.variables[name]=value_type(value)
    runtime.collections[name]=[{name:True}];runtime.binder.collections[name]=value_type(runtime.collections[name])
    monkeypatch.setattr(runtime.fx,'evaluate',lambda *_:pytest.fail('Inspection evaluated a formula'))
    assert serial(runtime.globals)[name]==value
    types=observe(runtime)
    assert types['globals'][name]['fields'][name]['row']['fields'][name]['kind']=='Number'
    assert types['collections'][name]['row']['fields'][name]['kind']=='Boolean'
    assert schema(value_type(value))['fields'][name]['kind']=='Table'


def test_scope_bookkeeping_is_not_a_record_field(runtime):
    original=ScopeFrame({'__sources__':7},sources={'Rows':{'__sources__':7}},aliased=True,open_schema=False)
    converted=original.typed(lambda _,v:value_type(v))
    assert set(original)==set(converted)=={'__sources__'}
    assert converted.aliased and not converted.open_schema
    assert converted.sources['Rows'].fields['__sources__'].kind=='Number'
    assert serial(original)=={'__sources__':7}
    assert 'sources' not in schema(value_type(original))['fields']

@pytest.fixture
def workspace(tmp_path):
    from powerapps_sim.application import Workspace
    from powerapps_sim.fixtures import scope_reset_project
    project=scope_reset_project(tmp_path/'project');w=Workspace(tmp_path,project.root)
    assert not w.runtime.diagnostics
    yield w
    w.runtime.close()

@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('language',['en-CA','fr-CA'])
def test_nested_input_reset_callbacks_inspection_and_saved_values(workspace,mode,language):
    w=workspace;r=w.runtime;r.environment.update(number_mode=mode,language=language);r.restart();r.state()
    r.event('Nested/AddLeft','OnSelect')
    assert r.fx.evaluate('LeftShell.FirstTotal')==11
    r.event('Nested/ChangeSeed','OnSelect');r.state()
    assert r.fx.evaluate('LeftShell.FirstTotal')==10
    assert r.fx.evaluate('LeftShell.SecondTotal')==110
    assert r.fx.evaluate('LeftShell.ResetCount')==0
    assert r.fx.evaluate('CountRows(trace)')==4
    assert [row['__phase'] for row in r.component_state['Nested/LeftShell']['collections']['history']]==['InnerA','InnerB','InnerA','InnerB']
    for path in ('Nested/LeftShell/InnerA','Nested/LeftShell/InnerB'):
        assert r.refs[path].property('ResetCount')==1
    assert r.refs['Nested/RightShell/InnerA'].property('ResetCount')==0
    from powerapps_sim.component_inspection import describe
    before=deepcopy(w.ai.read_runtime())
    inputs=describe(r,evaluate=True)['Nested/LeftShell/InnerA']['properties']['Config']
    assert inputs['value']['__source_rows__']=='Fictional updated note'
    assert inputs['type']['fields']['__open__']['kind']=='Boolean'
    assert w.ai.read_runtime()==before
    r.event('Nested/ChangeSeed','OnSelect');r.state()
    assert r.refs['Nested/LeftShell/InnerA'].property('ResetCount')==1
    r.event('Nested/ToggleFlag','OnSelect');r.state()
    assert r.refs['Nested/LeftShell/InnerA'].property('ResetCount')==2
    assert r.fx.evaluate('SelectedConfig.__open__') is True
    r.event('Nested/ResetLeft','OnSelect');r.state()
    assert r.fx.evaluate('LeftShell.ResetCount')==1
    assert r.refs['Nested/LeftShell/InnerA'].property('ResetCount')==3
    r.event('Nested/Save','OnSelect');r.state()
    row=r.store.rows('Snapshots')[0]
    assert row['__count']==10 and row['__open__'] is True
    assert '__host' in w.ai.read_runtime()['globals']
    assert w.ai.read_runtime()['types']['globals']['__host']['fields']['__phase']['kind']=='Text'
    assert not r.diagnostics

@pytest.mark.parametrize('language',['en-CA','fr-CA'])
@pytest.mark.parametrize('mode',['float','decimal'])
def test_repeatable_workflow_preserves_owner_after_record_edits(workspace,language,mode):
    from powerapps_sim.authoring import revision,data_revision
    w=workspace;r=w.runtime
    r.store.patch('Settings',r.store.rows('Settings')[0],{'__sources__':25,'__source_rows__':'Fictional owned note'})
    r.invalidate();r.state()
    assert r.fx.evaluate('LeftShell.FirstTotal')==25
    before=(revision(w.project.root),data_revision(r.store),deepcopy(w.ai.read_runtime()))
    entry=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);entry['environment']={'language':language,'number_mode':mode,'enum_mode':'strong'}
    report=w.workflows.run(entry,expected_revision=before[0])
    assert report['status']=='passed',report['steps']
    assert len(report['steps'])==24 and not report['diagnostics']
    assert before==(revision(w.project.root),data_revision(r.store),w.ai.read_runtime())


def test_exports_keep_authored_fields_without_scope_metadata(workspace):
    w=workspace;original=w.ai.export_source();w.ai.read_runtime()
    assert w.ai.export_source()==original
    with ZipFile(BytesIO(w.project.export())) as z:
        assert z.namelist()==['Src/scope-reset.pa.yaml']
        text=z.read(z.namelist()[0]).decode()
    assert '__source_rows__' in text and '__total' in text and 'RaiseOnReset: true' in text
    assert 'ScopeFrame' not in text and 'open_schema' not in text

"""Gallery interactions and row scope; clean source remains unchanged."""
import pytest
from powerapps_sim.fixtures import galleries_project
from powerapps_sim.runtime import Runtime,serial
from powerapps_sim.fx import Context
from powerapps_sim.authoring import revision
from powerapps_sim.application import Workspace

@pytest.fixture
def r(tmp_path):
    runtime=Runtime(galleries_project(tmp_path/'galleries'));runtime.restart()
    yield runtime
    runtime.close()

def rows(r,name='Records'):return r.render(r.global_refs[name])['rows']
def child(r,index,name='Caption',gallery='Records'):
    return next(c['path'] for c in rows(r,gallery)[index]['children'] if c['name']==name)
def act(r,formula):return r.fx.evaluate(formula,Context(r,behavior=True))

def test_defaults_are_runtime_only_and_row_click_is_token_checked(r):
    before=revision(r.project.root);node=r.render(r.global_refs['Records']);row=node['rows'][0]
    r.event(node['path'],'OnSelect',{'row_key':row['key'],'items_token':node['items_token']})
    assert r.fx.evaluate('Records.Selected.ID')==1 and r.fx.evaluate('clicks')==1
    assert r.fx.evaluate('status')=='gallery Fictional Alpha'
    assert revision(r.project.root)==before
    ref=r.refs[child(r,0)]
    assert ref.raw_property('OnSelect')=='=Select(Parent)' and 'OnSelect' not in ref.control.properties
    assert r.render(ref)['selectable'] and r.render(ref)['tab_stop']
    assert not r.diagnostics

@pytest.mark.parametrize('name',['Caption','Note','Custom','Silent'])
def test_child_selection_and_explicit_callback_override(r,name):
    r.event(child(r,2,name),'OnSelect')
    assert r.fx.evaluate('Records.Selected.ID')==3
    if name in ('Caption','Note'):
        assert r.fx.evaluate('clicks')==1 and r.fx.evaluate('status')=='gallery Fictional Gamma'
    else:
        assert r.fx.evaluate('clicks')==0
        assert r.fx.evaluate('status')==('custom Fictional Gamma' if name=='Custom' else 'ready')
    assert not r.diagnostics

def test_nonselectable_child_runs_authored_action_without_changing_selected(r):
    act(r,'Set(canSelect,false)')
    r.event(child(r,0,'Custom'),'OnSelect')
    assert r.fx.evaluate('Records.Selected.ID')==2 and r.fx.evaluate('status')=='custom Fictional Alpha'
    r.event('GalleryScreen/Records','OnSelect',selection=[2])
    assert r.fx.evaluate('Records.Selected.ID')==2

@pytest.mark.parametrize('mutation',['ClearCollect(rows,Sort(rows,ID,SortOrder.Descending))','ClearCollect(rows,Filter(rows,ID<>1))','Set(rows,Table({ID:1,Title:"Changed"}))','Reset(Records)'])
def test_stale_row_payload_cannot_execute_handler(r,mutation):
    node=r.render(r.global_refs['Records']);payload={'row_key':node['rows'][0]['key'],'items_token':node['items_token']}
    act(r,mutation)
    with pytest.raises(ValueError,match='changed'):r.event(node['path'],'OnSelect',payload)
    assert r.fx.evaluate('clicks')==0

def test_selected_ref_refresh_and_stable_keys_after_reorder(r):
    old=rows(r)[1];act(r,'ClearCollect(rows,Sort(rows,ID,SortOrder.Descending))')
    assert rows(r)[1]['key']==old['key'] and r.fx.evaluate('Records.Selected.ID')==2
    act(r,'ClearCollect(rows,Table({ID:2,Title:"Fresh"},{ID:4,Title:"Added"}))')
    assert r.fx.evaluate('Records.Selected.Title')=='Fresh'
    act(r,'ClearCollect(rows,Table({ID:4,Title:"Added"}))')
    assert r.fx.evaluate('Records.Selected.ID')==4

def test_duplicate_records_select_distinct_template_occurrences(r):
    act(r,'ClearCollect(rows,Table({ID:7,Title:"Same"},{ID:7,Title:"Same"}))')
    act(r,'Select(Records,2,Custom)');r.drain_events()
    rendered=rows(r)
    assert rendered[0]['key']!=rendered[1]['key']
    assert [row['selected'] for row in rendered]==[False,True]
    assert r.fx.evaluate('status')=='custom Same' and r.fx.evaluate('clicks')==0
    assert r.refs[child(r,1)].property('IsSelected') is True
    assert r.refs[child(r,0)].property('IsSelected') is False

def test_template_fill_and_virtual_selected_field_do_not_pollute_records(r):
    rendered=rows(r);assert rendered[0]['props']['TemplateFill']!=rendered[1]['props']['TemplateFill']
    assert r.fx.evaluate('Records.Selected.IsSelected') is True
    assert 'IsSelected' not in serial(r.fx.evaluate('Records.Selected'))
    ref=r.refs[child(r,0)]
    assert r.fx.evaluate('ThisItem.IsSelected',ref.context()) is False
    assert not r.diagnostics

def test_nested_items_and_inner_event_use_different_scopes(r):
    outer=rows(r,'Groups')[1];inner=next(c for c in outer['children'] if c['name']=='Nested')
    assert inner['rows'][0]['item']['ID']==21
    r.event(inner['rows'][0]['children'][0]['path'],'OnSelect')
    assert r.fx.evaluate('status')=='inner Inner Beta'
    assert r.fx.evaluate('Groups.Selected.ID')==2
    assert not r.diagnostics

def test_reset_selection_and_scroll_token_without_resetting_child_input(r):
    path=child(r,1,'Note');r.event(path,'OnChange','edited')
    node=r.render(r.global_refs['Records']);r.event(child(r,0),'OnSelect')
    r.event('GalleryScreen/ResetRecords','OnSelect')
    assert r.fx.evaluate('Records.Selected.ID')==2
    assert r.refs[path].property('Text')=='edited'
    assert r.render(r.global_refs['Records'])['reset_token']!=node['reset_token']
    token=r.render(r.global_refs['Records'])['reset_token'];r.restart()
    assert r.render(r.global_refs['Records'])['reset_token']!=token

def test_loaded_count_matches_viewport_buffer_and_horizontal_wrap_dimensions(r):
    act(r,'ClearCollect(rows,Sequence(501))')
    assert r.fx.evaluate('Records.AllItemsCount')==6 and r.fx.evaluate('CountRows(Records.AllItems)')==6
    ref=r.global_refs['Records'];ref.control.raw['Variant']='Horizontal';act(r,'Set(wrapCount,2)')
    assert ref.property('TemplateHeight')==130 and ref.property('TemplateWidth')==104

@pytest.mark.parametrize('selection',[[],[0,1],[-1],[3],[True]])
def test_invalid_gallery_selection_does_not_mutate_state(r,selection):
    with pytest.raises(ValueError):r.event('GalleryScreen/Records','OnSelect',selection=selection)
    assert r.fx.evaluate('Records.Selected.ID')==2 and r.fx.evaluate('clicks')==0

def test_packaged_workflow_is_isolated_and_clean(tmp_path):
    p=galleries_project(tmp_path/'fixture');w=Workspace(tmp_path,p.root,start=False)
    try:
        result=w.workflows.run(w.workflows.catalog()['scenarios'][0]['scenario'],expected_revision=revision(p.root))
        assert result['status']=='passed',result['steps']
        assert not result['diagnostics']
    finally:w.runtime.close()


def test_nonselectable_gallery_allows_programmatic_parent_selection(r):
    act(r,'Set(canSelect,false)')
    r.event(child(r,0,'Caption'),'OnSelect')
    assert r.fx.evaluate('Records.Selected.ID')==1
    assert r.fx.evaluate('status')=='gallery Fictional Alpha'
    assert not r.diagnostics


def test_container_default_chain_and_component_boundary(tmp_path):
    from powerapps_sim.source import Project,dump_yaml
    source={'App':{'Properties':{'StartScreen':'=Home','OnStart':'=Set(clicks,0)'}},
        'ComponentDefinitions':{'Badge':{'AccessAppScope':False,'Children':[{'PrivateCaption':{'Control':'ModernText@1.0.0','Properties':{'Text':'="Private caption"'}}}]}},
        'Screens':{'Home':{'Children':[{'G':{'Control':'Gallery@2.15.0','Properties':{'Items':'=Table({ID:1},{ID:2})','OnSelect':'=Set(clicks,clicks+1)'},'Children':[
            {'Box':{'Control':'GroupContainer@1.5.0','Variant':'AutoLayout','Children':[{'Text':{'Control':'ModernText@1.0.0','Properties':{'Text':'=Text(ThisItem.ID)'}}}]}},
            {'BadgeInstance':{'Control':'CanvasComponent','ComponentName':'Badge'}}]}}]}}}
    p=Project(tmp_path/'chain');p.update_source('Src/chain.pa.yaml',dump_yaml(source));r=Runtime(p);r.restart()
    try:
        r.render(r.global_refs['G'])
        text=next(ref for ref in r.refs.values() if ref.name=='Text' and ref.item['ID']==2)
        assert text.raw_property('AcceptsFocus')=='=true'
        r.event(text.path,'OnSelect')
        assert r.fx.evaluate('G.Selected.ID')==2 and r.fx.evaluate('clicks')==1
        private=next(ref for ref in r.refs.values() if ref.name=='PrivateCaption')
        assert private.raw_property('OnSelect')=='=Blank()' and not r.render(private)['selectable']
        assert len(r.diagnostics)==1
        assert r.diagnostics[0]['kind']=='Unsupported'
        assert 'components inside galleries' in r.diagnostics[0]['message']
    finally:r.close()

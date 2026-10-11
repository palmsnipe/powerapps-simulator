"""Incremental presentation must preserve Power Fx behavior and row lifetimes."""
import pytest
from powerapps_sim.fixtures import gallery_loading_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError
from powerapps_sim.gallery_loading import viewport,token,geometry
from powerapps_sim.workflows import validate,WorkflowService

@pytest.fixture
def r(tmp_path):
    runtime=Runtime(gallery_loading_project(tmp_path/'loading'));runtime.restart()
    yield runtime
    runtime.close()

def act(r,formula):return r.fx.evaluate(formula,Context(r,behavior=True))
def gallery(r):return r.global_refs['Records']
def scroll(r,offset,extent=300,ref=None):
    ref=ref or gallery(r)
    r.event(ref.path,'OnViewport',{'offset':offset,'extent':extent,'viewport_token':token(ref)})
def item(r,id):return next(row for row in gallery(r).property('AllItems') if row['ID']==id)

def test_initial_loading_is_bounded_and_delay_waits_for_visible_frame(r):
    assert r.fx.evaluate('LoadedCount')==6
    assert r.fx.evaluate('CountRows(rows)')==2048
    ref=r.global_refs['Horizontal'];node=r.render(ref)
    assert node['loading']['waiting'] and node['rows']==[] and ref.property('AllItemsCount')==0
    scroll(r,0,850,ref)
    assert not r.render(ref)['loading']['waiting']
    assert ref.property('AllItemsCount')==24
    assert not r.diagnostics

def test_jump_loads_only_window_and_reactive_count_has_no_behavior(r):
    scroll(r,60000)
    assert r.fx.evaluate('LoadedCount')==15
    assert [row['ID'] for row in gallery(r).property('AllItems')]==list(range(1,7))+list(range(598,607))
    rendered=r.render(gallery(r));assert len(rendered['rows'])==9
    assert [row['index'] for row in rendered['rows']]==list(range(597,606))
    assert r.fx.evaluate('clicks')==0 and r.fx.evaluate('changes')==0
    assert r.fx.evaluate('CountRows(rows)')==2048

def test_more_than_500_loaded_without_expanding_rendered_window(r):
    for offset in range(0,51000,300):scroll(r,offset)
    assert r.fx.evaluate('LoadedCount')>500
    assert len(r.render(gallery(r))['rows'])<=9
    assert len(gallery(r).property('AllItems'))==r.fx.evaluate('LoadedCount')

def test_loaded_refs_edits_capture_sort_reset_and_restart(r):
    first=item(r,1);amount=first['AmountInput'];note=first['Note']
    r.event(amount.path,'OnChange',99)
    r.event(note.path,'OnChange','Fictional edited first')
    act(r,'ClearCollect(captured,Records.AllItems)')
    scroll(r,60000)
    assert item(r,1)['AmountInput'] is amount and amount.property('Value')==99
    assert r.fx.evaluate('First(captured).Note.Text')=='Fictional edited first'
    before=r.fx.evaluate('LoadedCount')
    act(r,'Set(reverseRows,true)')
    assert item(r,1)['AmountInput'] is amount
    assert r.fx.evaluate('LoadedCount')>=before
    act(r,'Reset(Records)')
    assert r.gallery_loading[gallery(r).path].offset==0 and amount.property('Value')==99
    assert r.fx.evaluate('LoadedCount')>=before
    r.restart()
    assert r.fx.evaluate('LoadedCount')==6
    assert item(r,1)['AmountInput'].property('Value')==1
    assert amount.property('Value')==1

def test_filtered_rows_release_controls_and_captured_refs_report_errors(r):
    amount=item(r,1)['AmountInput']
    act(r,'RemoveIf(rows,ID=1)')
    gallery(r).property('AllItems')
    with pytest.raises(FxError,match='no longer exists'):amount.property('Value')
    assert all(row['ID']!=1 for row in gallery(r).property('AllItems'))

def test_programmatic_child_selection_materializes_only_requested_far_row(r):
    act(r,'Select(Records,1800,Caption)');r.drain_events()
    assert r.fx.evaluate('Records.Selected.ID')==1800 and r.fx.evaluate('clicks')==1
    assert r.fx.evaluate('LoadedCount')==7 and item(r,1800)['Caption'].property('Text')=='Fictional row 1800'

@pytest.mark.parametrize('field,value',[('offset',-1),('offset',True),('offset','20'),('offset',float('nan')),('extent',float('inf')),('extent',301.5)])
def test_invalid_viewport_is_rejected_before_app_behavior(r,field,value):
    payload={'offset':0,'extent':300,'viewport_token':token(gallery(r))};payload[field]=value
    with pytest.raises(ValueError):r.event(gallery(r).path,'OnViewport',payload)
    assert r.fx.evaluate('clicks')==0 and r.fx.evaluate('LoadedCount')==6

def test_stale_source_reset_and_geometry_payloads_are_ignored(r):
    payload={'offset':60000,'extent':300,'viewport_token':token(gallery(r))}
    act(r,'Reset(Records)');assert viewport(gallery(r),payload) is False
    payload['viewport_token']=token(gallery(r));act(r,'Set(reverseRows,true)');assert viewport(gallery(r),payload) is False
    payload['viewport_token']=token(gallery(r));gallery(r).control.properties['Height']='=200';r.invalidate()
    assert viewport(gallery(r),payload) is False
    assert r.fx.evaluate('clicks')==0

def test_presentation_loading_works_in_view_mode_but_not_hidden(r):
    ref=gallery(r);ref.control.properties['DisplayMode']='=DisplayMode.View';r.invalidate();scroll(r,60000)
    count=ref.property('AllItemsCount');assert count==15
    ref.control.properties['Visible']='=false';r.invalidate();scroll(r,120000)
    assert ref.property('AllItemsCount')==count
    assert r.fx.evaluate('clicks')==0

def test_horizontal_wrapping_and_zero_extent(r):
    ref=r.global_refs['Horizontal'];scroll(r,1000,850,ref)
    node=r.render(ref);assert node['loading']['total']==30 and node['rows'][0]['index']==0
    assert ref.property('AllItemsCount')==30
    assert viewport(ref,{'offset':0,'extent':0,'viewport_token':token(ref)}) is False

@pytest.mark.parametrize('offset',[True,-1,'500',float('nan')])
def test_workflow_scroll_validation(offset):
    with pytest.raises(ValueError):validate({'format_version':1,'name':'Scroll','steps':[{'op':'scroll','path':'LoadingScreen/Records','offset':offset},{'op':'assert','formula':'true'}]})

def test_workflow_scroll_uses_presentation_event(r):
    entry={};WorkflowService._step(r,{'op':'scroll','path':gallery(r).path,'offset':60000},entry)
    assert entry['actual']=={'loaded':15} and r.fx.evaluate('clicks')==0

def test_loading_dependency_cycle_is_isolated(r):
    ref=gallery(r);ref.control.properties['Height']='=Self.AllItemsCount*100';r.invalidate()
    with pytest.raises(FxError) as error:ref.property('AllItemsCount')
    assert error.value.kind=='Cycle'
    node=r.render(ref);assert node['errors']
    assert r.render(r.global_refs['Help'])['props']['Text']

def test_zero_sized_gallery_loads_no_rows(r):
    ref=gallery(r);ref.control.properties['Width']='=0';r.invalidate();r.gallery_loading.clear()
    assert ref.property('AllItemsCount')==0
    assert r.render(ref)['rows']==[]

def test_packaged_loading_workflow_is_isolated(tmp_path):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision,data_revision
    p=gallery_loading_project(tmp_path/'fixture');w=Workspace(tmp_path,p.root,start=False)
    try:
        before=revision(p.root);data=data_revision(w.runtime.store)
        result=w.workflows.run(w.workflows.catalog()['scenarios'][0]['scenario'],expected_revision=before)
        assert result['status']=='passed' and not result['diagnostics'],result['steps']
        assert not w.runtime.started and w.runtime.gallery_loading=={}
        assert revision(p.root)==before and data_revision(w.runtime.store)==data
    finally:w.runtime.close()

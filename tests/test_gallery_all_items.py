"""Live gallery control columns, table scopes and local record writes."""
from pathlib import Path
import pytest
from powerapps_sim.fixtures import galleries_project,remove_project
from powerapps_sim.runtime import Runtime,Ref,serial
from powerapps_sim.fx import Context
from powerapps_sim.binding import BindScope,value_type
from powerapps_sim.syntax import FxError
from powerapps_sim.source import Project,dump_yaml

@pytest.fixture
def r(tmp_path):
    runtime=Runtime(galleries_project(tmp_path/'all-items'));runtime.restart()
    yield runtime
    runtime.close()

def act(r,f):return r.fx.evaluate(f,Context(r,behavior=True))
def edit(r,index,value):
    row=r.global_refs['Records'].property('AllItems')[index]
    r.event(row['Note'].path,'OnChange',value)
    return row

def test_all_items_materializes_before_any_preview_and_never_runs_events(r):
    assert not any('/row:' in path for path in r.refs)
    data=r.fx.evaluate('Records.AllItems')
    assert len(data)==3 and isinstance(data[0]['Note'],Ref)
    assert r.fx.evaluate('First(Records.AllItems).Note.Text')=='Fictional Alpha'
    assert r.fx.evaluate('First(Records.AllItems).Caption.Text')=='Fictional Alpha'
    assert r.fx.evaluate('clicks')==0 and not r.diagnostics
    assert value_type(data).row.fields['Note'].kind=='Control'

def test_forall_alias_thisrecord_and_direct_control_resolution(r):
    edit(r,1,'Edited Beta')
    for formula in ['ForAll(Records.AllItems,Note.Text)',
                    'ForAll(Records.AllItems As item,item.Note.Text)',
                    'ForAll(Records.AllItems,ThisRecord.Note.Text)']:
        assert r.fx.evaluate(formula)==[{'Value':'Fictional Alpha'},{'Value':'Edited Beta'},{'Value':'Fictional Gamma'}]
    assert r.fx.evaluate('LookUp(Records.AllItems,ID=2,Note.Text)')=='Edited Beta'
    assert r.fx.evaluate('Concat(Records.AllItems,Note.Text,"|")')=='Fictional Alpha|Edited Beta|Fictional Gamma'
    assert not r.diagnostics

def test_control_projection_queries_shaping_and_aggregates(r):
    edit(r,0,'A')
    assert r.fx.evaluate('First(Records.AllItems.Note).Note.Text')=='A'
    assert r.fx.evaluate('Sum(Records.AllItems,Len(Note.Text))')==30
    assert r.fx.evaluate('CountRows(Filter(Records.AllItems,StartsWith(Note.Text,"Fictional")))')==2
    assert r.fx.evaluate('First(AddColumns(Records.AllItems,Edited,Note.Text)).Edited')=='A'
    assert r.fx.evaluate('First(ShowColumns(Records.AllItems,ID,Note)).Note.Text')=='A'
    assert r.fx.evaluate('First(RenameColumns(Records.AllItems,Note,Input)).Input.Text')=='A'
    assert set(r.fx.evaluate('First(DropColumns(Records.AllItems,Caption,Note,Custom,Silent))'))=={'ID','Title','Children'}
    assert not r.diagnostics

def test_control_refs_live_in_collections_and_survive_id_reordering(r):
    act(r,'ClearCollect(inputs,Records.AllItems)')
    first=r.collections['inputs'][0]['Note'];edit(r,0,'Live Alpha')
    assert r.fx.evaluate('First(inputs).Note.Text')=='Live Alpha'
    act(r,'ClearCollect(rows,Sort(rows,ID,SortOrder.Descending))')
    current=r.fx.evaluate('Last(Records.AllItems).Note')
    assert current is first and current.property('Text')=='Live Alpha'
    assert r.fx.evaluate('First(inputs).Note.Text')=='Live Alpha'
    assert serial(r.collections['inputs'])[0]['Note']=={'$control':'Note','path':first.path}
    assert not r.diagnostics

def test_reset_preserves_loaded_controls_but_explicit_child_reset_updates_allitems(r):
    ref=edit(r,1,'Edited')['Note'];act(r,'Reset(Records)')
    assert r.fx.evaluate('Index(Records.AllItems,2).Note.Text')=='Edited'
    act(r,'Select(Records,2,Custom)');r.drain_events()
    r.fx.evaluate('Reset(Self)',ref.context(True))
    assert r.fx.evaluate('Index(Records.AllItems,2).Note.Text')=='Fictional Beta'

def test_nested_gallery_controls_remain_in_their_own_record_scopes(r):
    outer=r.fx.evaluate('Index(Groups.AllItems,2)')
    assert isinstance(outer['Nested'],Ref) and 'InnerCaption' not in outer
    assert r.fx.evaluate('Index(Groups.AllItems,2).Nested.AllItemsCount')==1
    assert r.fx.evaluate('First(Index(Groups.AllItems,2).Nested.AllItems).InnerCaption.Text')=='Inner Beta'
    values=r.fx.evaluate('ForAll(Groups.AllItems As outer,ForAll(outer.Nested.AllItems As inner,{Outer:outer.ID,Inner:inner.ID,Caption:inner.InnerCaption.Text}))')
    assert values==[{'Outer':1,'Inner':11,'Caption':'Inner Alpha'},{'Outer':2,'Inner':21,'Caption':'Inner Beta'},{'Outer':3,'Inner':31,'Caption':'Inner Gamma'}]
    assert not r.diagnostics

def test_removed_instances_cannot_recreate_state_through_stored_refs(r):
    ref=edit(r,0,'Old')['Note'];act(r,'ClearCollect(inputs,Records.AllItems)')
    act(r,'ClearCollect(rows,Filter(rows,ID<>1))');r.fx.evaluate('Records.AllItems')
    assert ref.path not in r.refs and ref.path not in r.control_state
    with pytest.raises(FxError,match='no longer exists'):r.fx.evaluate('First(inputs).Note.Text')
    assert ref.path not in r.control_state


def make(tmp_path,children,items='Table({ID:1,Title:"Alpha"},{ID:2,Title:"Beta"})',extra=None):
    p=Project(tmp_path/'custom')
    p.update_source('Src/custom.pa.yaml',dump_yaml({'App':{'Properties':{'StartScreen':'=Home'}},'Screens':{'Home':{'Children':[{'G':{'Control':'Gallery@2.15.0','Properties':{'Items':'='+items},'Children':children}},*(extra or [])]}}}))
    r=Runtime(p);r.restart();return r


def test_container_descendant_columns_and_row_specific_siblings(tmp_path):
    r=make(tmp_path,[{'Box':{'Control':'GroupContainer@1.5.0','Children':[
        {'Input':{'Control':'ModernTextInput@1.1.2','Properties':{'Default':'=ThisItem.Title'}}},
        {'Echo':{'Control':'ModernText@1.0.0','Properties':{'Text':'=Input.Text & ":" & ThisItem.ID'}}}]}}])
    try:
        data=r.fx.evaluate('G.AllItems');r.event(data[1]['Input'].path,'OnChange','Edited')
        assert r.fx.evaluate('Last(G.AllItems).Echo.Text')=='Edited:2'
        assert r.fx.evaluate('First(G.AllItems).Echo.Text')=='Alpha:1'
        assert isinstance(data[0]['Box'],Ref) and not r.diagnostics
    finally:r.close()

@pytest.mark.parametrize('items',['Table({Input:"source value"})','Table({ID:1},{ID:1})'])
def test_conflicts_are_visible_and_duplicate_control_instances_are_independent(tmp_path,items):
    r=make(tmp_path,[{'Input':{'Control':'ModernTextInput@1.1.2','Properties':{'Default':'="Initial"'}}}],items)
    try:
        if 'source value' in items:
            with pytest.raises(FxError,match='conflicts'):r.fx.evaluate('G.AllItems')
            assert len(r.render(r.global_refs['G'])['rows'])==1
        else:
            data=r.fx.evaluate('G.AllItems');r.event(data[1]['Input'].path,'OnChange','Second')
            assert r.fx.evaluate('ForAll(G.AllItems,Input.Text)')==[{'Value':'Initial'},{'Value':'Second'}]
    finally:r.close()


def test_control_property_failure_isolated_to_its_row(r):
    r.global_refs['Records'].control.children[0].properties['Text']='=If(ThisItem.ID=2,Text(1/0),ThisItem.Title)'
    r.invalidate();values=r.fx.evaluate('ForAll(Records.AllItems,{Cell:Caption.Text})')
    assert values[0]=={'Cell':'Fictional Alpha'} and values[2]=={'Cell':'Fictional Gamma'}
    assert isinstance(values[1]['Cell'],FxError)


def test_allitems_cycle_does_not_block_other_properties(tmp_path):
    r=make(tmp_path,[{'Input':{'Control':'ModernTextInput@1.1.2'}}],'G.AllItems')
    try:
        with pytest.raises(FxError,match='cycle'):r.fx.evaluate('G.AllItems')
        assert r.global_refs['G'].property('Visible') is True
    finally:r.close()


def test_sqlite_fixture_bulk_component_save_and_isolated_failure_retry(tmp_path):
    from powerapps_sim.fixtures import gallery_edits_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision,data_revision
    p=gallery_edits_project(tmp_path/'fixture');w=Workspace(tmp_path,p.root,start=False)
    try:
        source=(p.root/'Src/gallery-edits.pa.yaml').read_bytes()
        before=data_revision(w.runtime.store)
        scenario=w.workflows.catalog()['scenarios'][0]['scenario']
        result=w.workflows.run(scenario,expected_revision=revision(p.root))
        assert result['status']=='passed' and len(result['steps'])==49,result['steps']
        assert not result['diagnostics']
        assert data_revision(w.runtime.store)==before and not w.runtime.started
        assert (p.root/'Src/gallery-edits.pa.yaml').read_bytes()==source
        assert result['collections']['editsSnapshot'][1]['Title']=='Fictional edited Beta'
        assert result['collections']['controlRows'][1]['CostInput']['$control']=='CostInput'
    finally:w.runtime.close()


def test_source_aliases_and_typed_payloads_write_only_real_list_fields(tmp_path):
    from powerapps_sim.fixtures import gallery_edits_project
    r=Runtime(gallery_edits_project(tmp_path/'fixture'));r.restart()
    try:
        rows=r.fx.evaluate('ProjectsGallery.AllItems');ref=rows[1]['TitleInput']
        assert rows[1].logical_names['Project name']=='Title'
        r.event(ref.path,'OnChange','Fictional edited Beta')
        r.event(rows[1]['CostInput'].path,'OnChange',25)
        assert r.fx.evaluate('LookUp(Edits,ID=2).Title')=='Fictional edited Beta'
        r.event('GalleryEdits/Panel/SaveRows','OnSelect')
        assert r.fx.evaluate('StoredTotal')==65 and r.fx.evaluate('callbacks')==1
        persisted=r.store.rows('Projects')[1]
        assert persisted['Project name']=='Fictional edited Beta' and persisted['Amount']==25
        assert all(not name.endswith('Input') and name!='IsSelected' for name in persisted)
        assert not r.diagnostics
    finally:r.close()


def test_allitems_controls_have_static_binder_types_and_readable_ai_values(tmp_path):
    from powerapps_sim.fixtures import gallery_edits_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import data_revision,revision
    p=gallery_edits_project(tmp_path/'fixture');w=Workspace(tmp_path,p.root)
    try:
        before=(revision(p.root),data_revision(w.runtime.store))
        for formula,kind in [('First(ProjectsGallery.AllItems).TitleInput.Text','Text'),
                             ('First(ProjectsGallery.AllItems).CostInput.Value','Number'),
                             ('First(ProjectsGallery.AllItems).DueInput.SelectedDate','Date'),
                             ('First(ProjectsGallery.AllItems).EnabledInput.Checked','Boolean')]:
            typ=w.runtime.binder.bind(w.runtime.fx.parse(formula),BindScope(),('test','',0))
            assert typ.kind==kind
        w.runtime.event('GalleryEdits/CaptureControls','OnSelect')
        data=serial(w.ai.read_runtime())['collections']['controlRows']
        assert value_type(w.runtime.collections['controlRows']).row.fields['TitleInput'].kind=='Control'
        assert data[0]['TitleInput']['$control']=='TitleInput'
        assert (revision(p.root),data_revision(w.runtime.store))==before
        assert not w.runtime.diagnostics
    finally:w.runtime.close()


def test_numeric_date_boolean_and_choice_reads_stay_row_specific(tmp_path):
    from powerapps_sim.fixtures import gallery_edits_project
    r=Runtime(gallery_edits_project(tmp_path/'fixture'));r.restart()
    try:
        items=r.fx.evaluate('ProjectsGallery.AllItems');row=items[1]
        r.event(row['CostInput'].path,'OnChange',77)
        r.event(row['DueInput'].path,'OnChange','2026-06-07')
        r.event(row['StatusInput'].path,'OnChange',selection=[1])
        from powerapps_sim.canvas_scalars import token
        r.event(row['EnabledInput'].path,'OnSelect',{'checked':False,'reset_token':token(row['EnabledInput'])})
        edited=r.fx.evaluate('LookUp(Edits,ID=2)')
        assert edited['Cost']==77 and edited['Enabled'] is False and edited['Status']=={'Value':'Done'}
        assert edited['Due'].isoformat()=='2026-06-07'
        assert r.fx.evaluate('LookUp(Edits,ID=1).Cost')==10
        assert r.fx.evaluate('LookUp(Projects,ID=2).Cost')==20 and not r.diagnostics
    finally:r.close()


def test_control_inspector_shows_current_output_before_save_and_hides_bookkeeping(tmp_path):
    from powerapps_sim.fixtures import gallery_edits_project
    from powerapps_sim.web import create_app
    p=gallery_edits_project(tmp_path/'fixture');app=create_app(tmp_path,p.root)
    w=app.extensions['workspace'];r=w.runtime;client=app.test_client()
    try:
        row=r.fx.evaluate('Index(ProjectsGallery.AllItems,2)')
        r.event(row['CostInput'].path,'OnChange',25)
        data=client.get('/api/control',query_string={'path':row['CostInput'].path}).get_json()
        assert data['values']['Value']==25 and data['values']['Default']==20
        assert 'dirty' not in data['values'] and 'Value' not in data['formulas']
        assert 'Value:' not in data['export']
        panel=client.get('/api/control',query_string={'path':'GalleryEdits/Panel'}).get_json()
        assert panel['values']['Total']==65 and len(panel['values']['Edits'])==3
        gallery=client.get('/api/control',query_string={'path':'GalleryEdits/ProjectsGallery'}).get_json()
        assert gallery['values']['AllItemsCount']==3
        assert gallery['values']['AllItems'][1]['CostInput']['$control']=='CostInput'
        assert not r.diagnostics
    finally:r.close()

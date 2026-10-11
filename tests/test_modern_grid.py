"""Documented modern grid source contract and authoritative interaction semantics."""
from copy import deepcopy
from tempfile import TemporaryDirectory
import pytest
from powerapps_sim.fixtures import modern_grid_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project,dump_yaml
from powerapps_sim.syntax import FxError
from powerapps_sim.modern_grid import token,view

@pytest.fixture
def r(tmp_path):
    value=Runtime(modern_grid_project(tmp_path/'grid'));value.restart();value.state()
    assert not value.diagnostics
    yield value;value.close()
def grid(r,panel='LeftPanel'):return r.refs['GridLab/'+panel+'/Grid']
def event(r,name='OnChange',panel='LeftPanel',**data):
    ref=grid(r,panel);r.event(ref.path,name,{'items_token':token(ref),**data});r.state()
def test_documented_versions_defaults_cells_and_scope(r):
    g=grid(r);specs,rows,errors=view(g)
    assert len(specs)==20 and len(rows)==12 and not errors
    assert rows[4]['cells'][0]['text']=='Fictional draft 5'
    assert rows[4]['cells'][1]['value']==50
    assert g.property('Selected')['ID']==1 and g.property('SearchText')==''
    assert r.binder.property_type(g.control,'Selected').fields['ID'].kind=='Number'
    assert r.fx.evaluate('LeftPanel.Current.Title')=='Fictional draft 1'
    assert specs[0]['width']==240

def test_selection_callbacks_last_record_and_instance_isolation(r):
    event(r,indices=[4]);event(r,indices=[6],toggle=True)
    assert r.fx.evaluate('CountRows(LeftPanel.Selection)=2 && LeftPanel.Current.ID=7')
    assert r.fx.evaluate('RightPanel.Current.ID=1 && CountRows(RightPanel.History)=0')
    assert r.globals['selected']['ID']==7 and len(r.collections['events'])==2
    event(r,indices=[6],toggle=True)
    assert r.fx.evaluate('LeftPanel.Current.ID=5 && CountRows(LeftPanel.Selection)=1')

def test_search_and_sort_leave_items_selection_and_callbacks_unchanged(r):
    event(r,indices=[4,6]);before=deepcopy(r.collections['events'])
    event(r,'OnSearch',query='draft 1');g=grid(r)
    assert [row['index'] for row in view(g)[1]]==[0,9,10,11]
    event(r,'OnSort',column=g.path+'/AmountColumn',descending=True)
    assert [row['index'] for row in view(g)[1]]==[11,10,9,0]
    assert [row['ID'] for row in g.property('SelectedItems')]==[5,7]
    assert [row['ID'] for row in g.property('Items')]==list(range(1,13))
    assert r.collections['events']==before
    with pytest.raises(ValueError,match='visible'):event(r,indices=[4])
    event(r,indices=[11]);assert g.property('Selected')['ID']==12

def test_default_snapshot_requires_reset_and_source_writes_refresh_selected(r):
    g=grid(r);g.control=deepcopy(g.control);g.control.properties['DefaultSelectedItems']='=LastN(GridPanel.Rows,1)';r.invalidate();r.state()
    assert g.property('Selected')['ID']==1
    g.control.properties['DefaultSelectedItems']='=1/0';r.invalidate()
    assert g.property('Selected')['ID']==1  # Loaded selection does not reobserve changed defaults.
    g.control.properties['DefaultSelectedItems']='=LastN(GridPanel.Rows,1)';r.invalidate()
    r.reset_ref(g);r.state();assert g.property('Selected')['ID']==12
    r.store.patch('Drafts',r.store.rows('Drafts')[-1],{'Title':'Fictional refreshed draft'});r.invalidate();r.state()
    assert g.property('Selected')['Title']=='Fictional refreshed draft'
    event(r,indices=[4]);r.store.remove('Drafts',r.store.rows('Drafts')[4]);r.invalidate();r.state()
    assert g.property('Selected') is None

def test_reset_clears_query_sort_selection_and_only_one_component(r):
    event(r,indices=[4]);event(r,'OnSearch',query='draft 1');event(r,'OnSort',column=grid(r).path+'/AmountColumn',descending=True)
    event(r,panel='RightPanel',indices=[6]);r.event('GridLab/ResetLeft','OnSelect');r.state()
    assert r.fx.evaluate('LeftPanel.Query="" && LeftPanel.Current.ID=1 && CountRows(LeftPanel.History)=0')
    assert r.fx.evaluate('RightPanel.Current.ID=7 && CountRows(RightPanel.History)=1')
    assert 'GridSort' not in grid(r).state

@pytest.mark.parametrize('operation',[{'indices':[True]},{'indices':[12]},{'indices':[1,1]},{'indices':[1],'toggle':'yes'}])
def test_bad_selection_rejected_without_callbacks(r,operation):
    before=deepcopy(r.collections['events'])
    with pytest.raises(ValueError):event(r,**operation)
    assert r.collections['events']==before and grid(r).property('Selected')['ID']==1

def test_tokens_expire_on_data_source_and_reset_changes(r):
    g=grid(r);old=token(g);r.store.patch('Drafts',r.store.rows('Drafts')[0],{'Title':'Fictional stale write'});r.invalidate()
    with pytest.raises(ValueError,match='source changed'):r.event(g.path,'OnChange',{'indices':[1],'items_token':old})
    old=token(g);r.reset_ref(g)
    with pytest.raises(ValueError,match='source changed'):r.event(g.path,'OnChange',{'indices':[1],'items_token':old})

def test_mode_gates_search_sort_and_selection(r):
    g=grid(r);g.control=deepcopy(g.control);g.control.properties['DisplayMode']='=DisplayMode.View';r.invalidate()
    for name,data in [('OnSearch',{'query':'draft 1'}),('OnSort',{'column':g.path+'/AmountColumn','descending':True}),('OnChange',{'indices':[1]})]:r.event(g.path,name,{'items_token':token(g),**data})
    assert g.property('Selected')['ID']==1 and g.property('SearchText')=='' and not r.collections['events']

def test_flags_clear_search_sort_and_restrict_multiple(r):
    event(r,'OnSearch',query='draft 1');event(r,'OnSort',column=grid(r).path+'/AmountColumn',descending=True)
    g=grid(r);g.control=deepcopy(g.control);g.control.properties.update(Searchable='=false',Sortable='=false',SelectMultiple='=false');r.invalidate();r.state()
    assert g.property('SearchText')=='' and 'GridSort' not in g.state
    with pytest.raises(ValueError,match='disabled'):event(r,'OnSearch',query='draft')
    with pytest.raises(ValueError,match='disabled'):event(r,'OnSort',column=g.path+'/AmountColumn',descending=True)
    with pytest.raises(ValueError,match='one selection'):event(r,indices=[1,2])

def test_choice_cells_errors_and_unknown_variants_isolate(r):
    g=grid(r);c=g.children[0];c.control=deepcopy(c.control);c.control.properties['Text']='=Table({Value:"First"},{Value:"Second"})';r.invalidate()
    assert view(g)[1][0]['cells'][0]['text']=='First, Second'
    c.control.properties['Text']='=Missing_1.Title';r.invalidate();r.state()
    assert view(g)[1][0]['cells'][0]['error'] and view(grid(r,'RightPanel'))[1][0]['cells'][0]['text']=='Fictional draft 1'
    assert r.diagnostics

def test_pure_reads_and_source_exports_preserve_owner(r):
    before=deepcopy(r.control_state);source=(r.project.root/'Src/modern-grid.pa.yaml').read_bytes()
    for _ in range(2):grid(r).property('SelectedItems');view(grid(r));token(grid(r))
    assert r.control_state==before and (r.project.root/'Src/modern-grid.pa.yaml').read_bytes()==source
    assert b'GridSelection' not in source and b'ModernDataGridColumn@1.1.0' in source

@pytest.mark.parametrize('language,number',[('en-US','float'),('en-US','decimal'),('fr-CA','float'),('fr-CA','decimal')])
def test_workflow_forms_errors_retry_and_owner_preservation(tmp_path,language,number):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    from powerapps_sim.workflows import data_revision
    p=modern_grid_project(tmp_path/'grid');w=Workspace(tmp_path/'workspace',p.root)
    try:
        source=revision(p.root);data=data_revision(w.runtime.store);before=deepcopy(w.ai.read_runtime())
        scenario=w.workflows.catalog()['scenarios'][0]['scenario'];scenario={**scenario,'environment':{**scenario['environment'],'language':language,'number_mode':number}}
        report=w.workflows.run(scenario,expected_revision=source)
        assert report['status']=='passed',report['steps']
        assert len(report['steps'])==32 and not report['diagnostics']
        assert revision(p.root)==source and data_revision(w.runtime.store)==data and w.ai.read_runtime()==before
    finally:w.runtime.close()

def test_large_grid_full_server_queries_and_no_row_limit(r):
    r.event('GridLab/OpenLarge','OnSelect');r.state();g=r.refs['LargeLab/BigGrid']
    assert len(view(g)[1])==2105 and g.property('Selected')['ID']==1
    r.event(g.path,'OnSearch',{'query':'row 2105','items_token':token(g)});r.state()
    assert [row['index'] for row in view(g)[1]]==[2104]
    r.event(g.path,'OnChange',{'indices':[2104],'items_token':token(g)});r.state()
    assert g.property('Selected')['ID']==2105 and len(g.property('Items'))==2105
    assert not r.diagnostics

def test_duplicate_ids_have_distinct_selection_identity(r):
    g=grid(r);g.control=deepcopy(g.control);g.control.properties['Items']='=Table({ID:1,Title:"One",Amount:10},{ID:1,Title:"Two",Amount:20})'
    for child in g.children[2:]:child.control=deepcopy(child.control);child.control.properties['Visible']='=false'
    r.reset_ref(g);r.state();assert len(g.property('SelectedItems'))==1
    event(r,indices=[0,1]);assert [x['Title'] for x in g.property('SelectedItems')]==['One','Two']
    assert g.property('Selected')['Title']=='Two'
    event(r,indices=[1],toggle=True);assert g.property('Selected')['Title']=='One'

@pytest.mark.parametrize('property,value',[('Searchable','="yes"'),('Width','=-1'),('Items','=Table(1)'),('ShowAIRowSummary','=true')])
def test_invalid_and_unsupported_properties_report_errors(r,property,value):
    g=grid(r);g.control=deepcopy(g.control);g.control.properties[property]=value;r.invalidate()
    with pytest.raises(FxError):g.property(property)
    r.state();assert r.diagnostics
    assert grid(r,'RightPanel').property('Selected')['ID']==1

def test_grid_inside_required_form_card_validates_retains_failed_edit_and_retries(r):
    # Project-local control setup exercises the existing form service with a grid.
    card=r.refs['GridLab/DraftForm/TitleCard'];definition=deepcopy(grid(r).control)
    definition.name='Picker';definition.parent=card.control
    definition.raw['Properties']={'Items':'=Table({ID:1,Title:"Fictional draft 1"},{ID:2,Title:"Fictional card selection"})',
        'DefaultSelectedItems':'=FirstN(Self.Items,1)','Width':'=650','Height':'=100','OnChange':'=Blank()'}
    definition.children=definition.children[:1];definition.children[0].parent=definition
    definition.children[0].raw['Properties']={'Text':'=ThisItem.Title','FieldDisplayName':'="Draft"'}
    picker=r.build(definition,card.path+'/Picker',card,None,[],dict(card.scope),None);card.children.append(picker)
    card.scope['Picker']=picker;card.control=deepcopy(card.control);card.control.properties['Update']='=If(IsEmpty(Picker.SelectedItems),Blank(),Picker.Selected.Title)'
    r.invalidate();r.state();form=r.refs['GridLab/DraftForm'];assert form.property('Valid')
    r.event(picker.path,'OnChange',{'indices':[],'items_token':token(picker)});r.state()
    assert not form.property('Valid') and form.property('Unsaved')
    r.event('GridLab/Save','OnSelect');assert r.store.rows('Drafts')[0]['Title']=='Fictional draft 1'
    r.event(picker.path,'OnChange',{'indices':[1],'items_token':token(picker)});r.state()
    r.store.failures['Drafts']='write';r.event('GridLab/Save','OnSelect')
    assert picker.property('Selected')['ID']==2 and form.property('Unsaved')
    r.store.failures.clear();r.event('GridLab/Save','OnSelect');r.state()
    assert r.store.rows('Drafts')[0]['Title']=='Fictional card selection' and not form.property('Unsaved')


def test_temporal_sort_uses_powerfx_values_with_blank_last(r):
    g=grid(r);g.control=deepcopy(g.control);g.control.properties['Items']='=Table({ID:1,Title:"Late",Amount:Date(2026,2,1)},{ID:2,Title:"Early",Amount:Date(2026,1,1)},{ID:3,Title:"Blank",Amount:Blank()})'
    for child in g.children[2:]:child.control=deepcopy(child.control);child.control.properties['Visible']='=false'
    # Existing component callback's Number contract is deliberately not invoked.
    r.invalidate();event(r,'OnSort',column=g.path+'/AmountColumn',descending=False)
    assert [row['index'] for row in view(g)[1]]==[1,0,2]

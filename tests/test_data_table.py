"""Read-only DataTable contracts, row scopes, persistence and error isolation."""
from copy import deepcopy
import pytest
from powerapps_sim.fixtures import data_table_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.data_table import token,selected
from powerapps_sim.syntax import FxError
T='TableLab/DraftTable';F='TableLab/DraftForm';C=T+'/TitleColumn'
@pytest.fixture
def r(tmp_path):
    value=Runtime(data_table_project(tmp_path/'table'));value.restart();value.state();assert not value.diagnostics
    yield value
    value.close()
def choose(r,index,column=None,path=T,source=None):
    value={'index':index,'items_token':source or token(r.refs[path])}
    if column:value['column']=column
    r.event(path,'OnSelect',value)
def prop(r,name,value,path=T):
    ref=r.refs[path];ref.control=deepcopy(ref.control);ref.control.properties[name]=value;r.invalidate()
def test_columns_cell_scopes_header_and_source_order(r):
    n=r.render(r.refs[T]);assert len(n['columns'])==20 and len(n['rows'])==12
    assert [c['text'] for c in n['rows'][2]['cells'][:4]]==['3','Fictional draft 3','30.00','Draft']
    prop(r,'Order','=1',C);prop(r,'Order','=20',T+'/IDColumn')
    assert r.render(r.refs[T])['columns'][0]['name']=='TitleColumn'
def test_default_one_selection_cell_callback_and_independence(r):
    assert selected(r.refs[T])['ID']==1
    choose(r,3,C);assert selected(r.refs[T])['ID']==4
    assert r.collections['clicks']==[{'ID':4,'Kind':'Title'}]
    assert r.refs[C].property('Text')=='Fictional draft 4'
    assert r.fx.evaluate('OtherTable.Selected.ID')==101
    choose(r,1,path='TableLab/OtherTable');assert r.fx.evaluate('OtherTable.Selected.ID')==102
    assert r.fx.evaluate('DraftTable.Selected.ID')==4
    choose(r,4);assert len(r.collections['clicks'])==1
@pytest.mark.parametrize('i',[-1,12,True,'1',None])
def test_invalid_index_atomic(r,i):
    before=deepcopy(r.control_state)
    with pytest.raises(ValueError):choose(r,i)
    assert r.control_state==before
def test_source_token_survives_queued_selection_and_rejects_changed_rows(r):
    t=token(r.refs[T]);choose(r,1,source=t);choose(r,2,source=t)
    r.store.patch('Drafts',r.store.rows('Drafts')[2],{'Title':'Fictional refreshed'});r.invalidate()
    assert selected(r.refs[T])['Title']=='Fictional refreshed'
    with pytest.raises(ValueError,match='changed'):choose(r,5,source=t)
    choose(r,11);r.event('TableLab/LeftFilter/Switch','OnChange',True)
    assert selected(r.refs[T])['ID']==1
    assert len(r.render(r.refs[T])['rows'])==4
def test_empty_and_error_rows_isolated(r):
    prop(r,'Items','=Table()');assert selected(r.refs[T]) is None
    assert not r.render(r.refs[T])['rows']
    prop(r,'Items','=Table({ID:1,Title:"healthy",Amount:1,Status:{Value:"Draft"}},Error("broken"))')
    n=r.render(r.refs[T]);assert n['rows'][1]['disabled'] and selected(r.refs[T])['ID']==1
    with pytest.raises(FxError):choose(r,1)
    assert r.fx.evaluate('OtherTable.Selected.ID')==101
@pytest.mark.parametrize('mode',['View','Disabled'])
def test_display_modes_block_selection(r,mode):
    prop(r,'DisplayMode','=DisplayMode.'+mode);choose(r,5,C)
    assert selected(r.refs[T])['ID']==1 and not r.collections['clicks']
def test_column_hidden_disabled_and_foreign_events(r):
    prop(r,'Visible','=false',C);choose(r,2,C);assert selected(r.refs[T])['ID']==1
    prop(r,'Visible','=true',C);prop(r,'DisplayMode','=DisplayMode.Disabled',C)
    choose(r,2,C);assert selected(r.refs[T])['ID']==1
    with pytest.raises(ValueError):choose(r,3,'TableLab/OtherTable/OtherTitle')
    prop(r,'DisplayMode','=DisplayMode.Edit',C)
    with pytest.raises(ValueError):r.event(C,'OnSelect')
@pytest.mark.parametrize('path,name,value',[(T,'Items','=123'),(T+'/AmountColumn','Order','=0'),(T+'/AmountColumn','Width','=-1'),(T+'/AmountColumn','AutoWidth','=1'),(T+'/AmountColumn','IsHyperlink','="yes"'),(T,'HeadingSize','=false')])
def test_typed_contracts(r,path,name,value):
    prop(r,name,value,path)
    with pytest.raises(FxError):r.refs[path].property(name)
    assert r.fx.evaluate('OtherTable.Selected.ID')==101
def test_cell_errors_preserve_other_cells_and_tables(r):
    prop(r,'Text','=Missing_1.Title',C);n=r.render(r.refs[T])
    assert n['rows'][0]['cells'][1]['error'] and n['rows'][0]['cells'][0]['text']=='1'
    assert r.render(r.global_refs['OtherTable'])['rows'][0]['cells'][1]['text']=='Independent table A'
    assert any('Missing_1' in v['message'] for v in r.diagnostics)
def test_complex_field_requires_explicit_projection(r):
    prop(r,'Text','=ThisItem.Status',T+'/StatusColumn')
    assert r.render(r.refs[T])['rows'][0]['cells'][3]['error']
    prop(r,'Text','=ThisItem.Status.Value',T+'/StatusColumn')
    assert r.render(r.refs[T])['rows'][0]['cells'][3]['text']=='Draft'
def test_automatic_width_and_hidden_columns(r):
    prop(r,'AutoWidth','=true',C);assert r.render(r.refs[T])['columns'][1]['width']>=120
    r.event('TableLab/RightShow/Switch','OnChange',False)
    assert len(r.render(r.refs[T])['columns'])==19 and len(r.collections['events'])==1
    assert r.fx.evaluate('LeftFilter.Value') is False
def test_form_selection_updates_persistent_write_failed_retry(r):
    choose(r,4,C);r.event(F+'/TitleCard/TitleInput','OnChange','Fictional edited draft')
    r.event(F+'/AmountCard/AmountInput','OnChange','42')
    assert r.fx.evaluate('DraftForm.Unsaved && DraftForm.Updates.Amount=42')
    r.store.failures['Drafts']='write';r.event('TableLab/Save','OnSelect')
    assert r.fx.evaluate('DraftForm.Unsaved && status="Save failed"')
    assert selected(r.refs[T])['Amount']==50
    r.store.failures.pop('Drafts');r.event('TableLab/Save','OnSelect')
    assert selected(r.refs[T])['Title']=='Fictional edited draft'
    assert selected(r.refs[T])['Amount']==42
    assert r.fx.evaluate('DraftForm.LastSubmit.ID=5 && !DraftForm.Unsaved')
    n=r.render(r.refs[T]);assert n['rows'][4]['cells'][1]['text']=='Fictional edited draft'
    r.event(F+'/TitleCard/TitleInput','OnChange','');r.event('TableLab/Save','OnSelect')
    assert not r.fx.evaluate('DraftForm.Valid') and selected(r.refs[T])['Title']=='Fictional edited draft'
    r.event('TableLab/Reset','OnSelect');assert r.fx.evaluate('DraftForm.Valid && !DraftForm.Unsaved')
def test_render_is_pure_and_export_excludes_emulator_geometry(r):
    before=deepcopy(r.control_state);source=(r.project.root/'Src/data-table.pa.yaml').read_bytes()
    r.state();r.render(r.refs[T]);assert r.control_state==before
    assert (r.project.root/'Src/data-table.pa.yaml').read_bytes()==source
    assert b'items_token' not in source and b'TableSelected' not in source
    with pytest.raises(FxError,match='Reset does not support'):r.fx.evaluate('Reset(DraftTable)',r.refs[T].context(True))
    prop(r,'Selected','={ID:88}')
    with pytest.raises(FxError,match='output'):r.fx.evaluate('DraftTable.Selected')
@pytest.mark.parametrize('language,number',[('en-US','float'),('en-US','decimal'),('fr-CA','float'),('fr-CA','decimal')])
def test_workflow_disposable_snapshot(r,language,number):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    from powerapps_sim.workflows import data_revision
    w=Workspace(r.project.root.parent,r.project.root)
    try:
        before=deepcopy(w.ai.read_runtime());source=revision(r.project.root);data=data_revision(w.runtime.store)
        entry=w.workflows.catalog()['scenarios'][0]
        result=w.workflows.run({**entry['scenario'],'environment':{'language':language,'number_mode':number}},expected_revision=source)
        assert result['status']=='passed' and len(result['steps'])==35 and not result['diagnostics'],result['steps']
        assert w.ai.read_runtime()==before and revision(r.project.root)==source and data_revision(w.runtime.store)==data
    finally:w.runtime.close()


def test_restart_rejects_old_row_event(r):
    t=token(r.refs[T]);choose(r,4);r.restart()
    assert selected(r.refs[T])['ID']==1
    with pytest.raises(ValueError,match='changed'):choose(r,3,source=t)

def test_omitted_cell_text_inspector_matches_display(r):
    ref=r.refs[T+'/Detail1'];assert ref.property('Text')=='Fictional detail 1.1'
    choose(r,2);assert ref.property('Text')=='Fictional detail 3.1'

def test_source_mapping_and_column_export_remain_unchanged(r):
    from powerapps_sim.source import load_yaml
    control=r.refs[C].control;raw=deepcopy(control.raw)
    text=r.project.export_control(control.name)
    assert load_yaml(text)['Screens']['Scratch']['Children'][0]['TitleColumn']['Control']=='DataTableColumn@1.0.1'
    assert control.raw==raw and 'items_token' not in text

def test_component_and_form_placement_report_unsupported(r):
    from powerapps_sim.controls import contract_errors
    control=deepcopy(r.refs[T].control);control.parent=r.global_refs['DraftForm'].control
    assert 'Placement' in contract_errors(control)
    control.parent=r.global_refs['LeftFilter'].control
    assert 'Placement' in contract_errors(control)


def test_placement_findings_do_not_crash_analysis(r):
    table=r.refs[T].control;parent=table.parent
    try:
        table.parent=r.global_refs['LeftFilter'].control
        r.analyze()
        assert any('does not support DataTable inside' in d['message'] for d in r.diagnostics)
    finally:table.parent=parent

def test_malformed_and_multirow_payloads_atomic(r):
    before=deepcopy(r.control_state)
    for value,selection in [(None,[0,1]),({'index':0},None),({'index':0,'items_token':token(r.refs[T]),'extra':True},None)]:
        with pytest.raises(ValueError):r.event(T,'OnSelect',value,selection)
    assert r.control_state==before


def test_duplicate_ids_select_exactly_one_occurrence(r):
    prop(r,'Items','=Table({ID:1,Title:"First"},{ID:1,Title:"Second"},{ID:1,Title:"Third"})')
    for i in (0,2,1):
        choose(r,i)
        assert [row['index'] for row in r.render(r.refs[T])['rows'] if row['selected']]==[i]
        assert selected(r.refs[T])['Title']==['First','Second','Third'][i]
    prop(r,'Items','=Table({ID:1,Title:"First revised"},{ID:1,Title:"Second revised"},{ID:1,Title:"Third revised"})')
    assert selected(r.refs[T])['Title']=='Second revised'

def test_duplicate_identical_records_still_have_one_selected_row(r):
    prop(r,'Items','=Table({ID:1,Title:"Same"},{ID:1,Title:"Same"})')
    choose(r,1)
    assert [row['index'] for row in r.render(r.refs[T])['rows'] if row['selected']]==[1]


def test_column_property_cycles_are_isolated(r):
    prop(r,'Text','=Self.Text',C)
    n=r.render(r.refs[T])
    assert n['rows'][0]['cells'][1]['error'] and n['rows'][0]['cells'][0]['text']=='1'
    assert any(d['kind']=='Cycle' for d in r.diagnostics)
    prop(r,'Text','=IDColumn.Text',C);prop(r,'Text','=TitleColumn.Text',T+'/IDColumn')
    n=r.render(r.refs[T]);assert n['rows'][0]['cells'][0]['error']
    assert r.fx.evaluate('OtherTable.Selected.ID')==101

def test_cross_column_text_uses_the_current_cell_record(r):
    prop(r,'Text','=IDColumn.Text & ": " & ThisItem.Title',C)
    n=r.render(r.refs[T])
    assert n['rows'][2]['cells'][1]['text']=='3: Fictional draft 3'
    assert selected(r.refs[T])['ID']==1


def test_column_text_has_text_output_type_and_scalar_conversion(r):
    prop(r,'Text','=ThisItem.ID',C)
    assert r.binder.property_type(r.refs[C].control,'Text').kind=='Text'
    assert r.refs[C].property('Text')=='1'
    assert r.binder.property_type(None,'Text').kind=='Unknown'

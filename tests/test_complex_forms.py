"""Complex card edits, callbacks, resets and persistence use the real runtime."""
from copy import deepcopy
import pytest
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision
from powerapps_sim.fixtures import complex_project
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime
from powerapps_sim.scenarios import seed, PEOPLE
from powerapps_sim.store import ListStore

@pytest.fixture
def complex_app(tmp_path):
    r=Runtime(complex_project(tmp_path/'complex'));r.restart();r.state()
    yield r;r.close()


def change(r,card,picker,selection):
    r.event(f'ComplexScreen/TaskForm/{card}/{picker}','OnChange',selection=selection)


def test_defaults_table_shapes_required_and_clean_state(complex_app):
    r=complex_app
    assert r.fx.evaluate('TaskForm.Valid') is True and r.fx.evaluate('TaskForm.Unsaved') is False
    assert r.fx.evaluate('TagsPicker.SelectedItems')==[{'Value':'Planning'}]
    assert r.fx.evaluate('LinksPicker.SelectedItems')==[{'Id':1,'Value':'Fictional bridge study'}]
    assert r.fx.evaluate('OwnersPicker.Selected.Email')=='alex@example.test'
    assert r.fx.evaluate('CountRows(LeftPeople.Current)')==r.fx.evaluate('CountRows(RightLinks.Current)')==1
    assert not r.diagnostics


def test_multiple_values_failed_save_retry_and_reopening_are_persistent(complex_app):
    r=complex_app;before=deepcopy(r.store.rows('Tasks'))
    for card,picker in [('TagsCard','TagsPicker'),('LinksCard','LinksPicker'),('OwnersCard','OwnersPicker')]:change(r,card,picker,[0,1])
    assert r.fx.evaluate('TaskForm.Unsaved') is True
    r.store.failures['Tasks']='write';r.event('ComplexScreen/Save','OnSelect')
    assert r.store.rows('Tasks')==before and r.fx.evaluate('CountRows(OwnersPicker.SelectedItems)')==2
    assert r.fx.evaluate('TaskForm.Unsaved') is True
    r.store.failures.clear();r.event('ComplexScreen/Save','OnSelect')
    assert r.fx.evaluate("CountRows(TaskForm.LastSubmit.'Project Tags')")==2
    assert r.fx.evaluate("CountRows(TaskForm.LastSubmit.'Related Projects')")==2
    assert r.fx.evaluate('TaskForm.Unsaved') is False
    other=ListStore(r.project.root/'data.sqlite')
    try:assert other.rows('Tasks')==r.store.rows('Tasks')
    finally:other.close()
    assert not r.diagnostics


@pytest.mark.parametrize('card,picker',[('TagsCard','TagsPicker'),('OwnersCard','OwnersPicker')])
def test_required_empty_table_rejected_then_reset_restores_values(complex_app,card,picker):
    r=complex_app;before=deepcopy(r.store.rows('Tasks'));change(r,card,picker,[])
    assert r.fx.evaluate('TaskForm.Valid') is False
    r.event('ComplexScreen/Save','OnSelect');assert r.store.rows('Tasks')==before
    r.event('ComplexScreen/Reset','OnSelect')
    assert r.fx.evaluate('TaskForm.Valid') is True and r.fx.evaluate('TaskForm.Unsaved') is False
    assert r.fx.evaluate(f'CountRows({picker}.SelectedItems)')==1


def test_search_does_not_dirty_form_and_optional_lookup_clear_is_table(complex_app):
    r=complex_app;r.event('ComplexScreen/TaskForm/OwnersCard/OwnersPicker','OnSearch','sam')
    assert r.fx.evaluate('TaskForm.Unsaved') is False and r.fx.evaluate('OwnersPicker.Selected.Email')=='alex@example.test'
    change(r,'LinksCard','LinksPicker',[]);r.event('ComplexScreen/Save','OnSelect')
    assert r.store.rows('Tasks')[0]['Related Projects']==[] and not r.diagnostics


def test_new_form_requires_all_cards_and_allocates_list_id(complex_app):
    r=complex_app;r.event('ComplexScreen/New','OnSelect')
    assert r.fx.evaluate('TaskForm.Mode')=='New' and r.fx.evaluate('TaskForm.Valid') is False
    r.event('ComplexScreen/TaskForm/TitleCard/TaskTitle','OnChange','Fictional new task')
    change(r,'TagsCard','TagsPicker',[1]);change(r,'OwnersCard','OwnersPicker',[1]);change(r,'LinksCard','LinksPicker',[0,1])
    assert r.fx.evaluate('TaskForm.Valid') is True
    r.event('ComplexScreen/Save','OnSelect')
    row=r.store.rows('Tasks')[-1]
    assert row['ID']==3 and row['Title']=='Fictional new task' and row['Project Owners'][0]['Email']=='sam@example.test'
    assert r.fx.evaluate('TaskForm.Unsaved') is False and not r.diagnostics


def test_record_switch_discards_edits_and_restores_complex_defaults(complex_app):
    r=complex_app;change(r,'TagsCard','TagsPicker',[2]);change(r,'OwnersCard','OwnersPicker',[0,1]);r.event('ComplexScreen/Next','OnSelect')
    assert r.fx.evaluate('TagsPicker.Selected.Value')=='Review' and r.fx.evaluate('OwnersPicker.Selected.Email')=='sam@example.test'
    assert r.fx.evaluate('LinksPicker.Selected.Id')==2 and r.fx.evaluate('TaskForm.Unsaved') is False
    assert r.store.rows('Tasks')[0]['Project Tags']==[{'Value':'Planning'}]


def test_component_callback_keeps_typed_people_records_and_other_instance(complex_app):
    r=complex_app;r.event('ComplexScreen/LeftPeople/Picker','OnSearch','sam');r.event('ComplexScreen/LeftPeople/Picker','OnChange',selection=[0])
    assert r.globals['leftOwners'][0]['Email']=='sam@example.test'
    assert r.globals['leftOwners'][0]['Claims'].endswith('sam@example.test')
    assert r.fx.evaluate('First(RightLinks.Current).Id')==1 and r.fx.evaluate('CountRows(OwnersPicker.SelectedItems)')==1
    r.fx.evaluate('Reset(LeftPeople)',Context(r,behavior=True))
    assert r.fx.evaluate('First(LeftPeople.Current).Email')=='alex@example.test' and r.fx.evaluate('First(RightLinks.Current).Id')==1
    assert r.collections['events'][-1]['Event']=='left' and not r.diagnostics


def test_people_selection_refreshes_and_deselects_by_claims_not_display_fields(complex_app):
    r=complex_app;change(r,'OwnersCard','OwnersPicker',[1]);before=len(r.collections['events'])
    r.people[1]['Claims']=r.people[1]['Claims'].upper();r.people[1]['DisplayName']='Renamed fictional Sam';r.invalidate()
    assert r.fx.evaluate('OwnersPicker.Selected.DisplayName')=='Renamed fictional Sam'
    ref=r.global_refs['OwnersPicker'];node=r.render(ref)
    assert node['selection']==[1]
    r.event(ref.path,'OnChange',value={'operation':'toggle','index':1,'option_token':node['option_token']})
    assert r.fx.evaluate('OwnersPicker.SelectedItems')==[] and len(r.collections['events'])==before+1


def test_dataset_reset_populates_valid_complex_values_and_lookup_links(complex_app):
    r=complex_app;seed(r.store,'2026-01-01T12:00:00+00:00');r.people=PEOPLE;r.restart()
    rows=r.store.rows('Tasks')
    assert len(rows)==3
    for row in rows:
        assert row['Project Tags'] and row['Project Owners'] and row['Related Projects']
        r.store.validate('Tasks',r.store.internal('Tasks',row))
    assert r.fx.evaluate('TaskForm.Valid') is True and not r.diagnostics


def test_complex_workflow_is_stored_and_isolated_from_live_records(tmp_path):
    p=complex_project(tmp_path/'complex');w=Workspace(tmp_path,p.root,start=False)
    try:
        before=deepcopy(w.runtime.store.rows('Tasks'));entries=w.workflows.catalog()['scenarios'];assert len(entries)==1
        result=w.workflows.run(entries[0]['scenario'],expected_revision=revision(p.root))
        assert result['status']=='passed',result['steps']
        assert not result['diagnostics'] and w.runtime.store.rows('Tasks')==before
    finally:w.runtime.close()

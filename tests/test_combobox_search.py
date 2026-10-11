"""Server-owned search/selection, component isolation and form lifecycle."""
import pytest
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision
from powerapps_sim.fixtures import search_project, forms_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError

@pytest.fixture
def search(tmp_path):
    r=Runtime(search_project(tmp_path/'search'));r.restart();r.state()
    yield r;r.close()


def node(r,name='Multi'):
    return r.render(r.global_refs[name])


def choose(r,name='Multi',index=0,operation='toggle',path=None):
    ref=r.refs[path] if path else r.global_refs[name]
    rendered=r.render(ref)
    r.event(ref.path,'OnChange',value={'operation':operation,'index':index,'option_token':rendered['option_token']})


def test_search_updates_items_without_callback_or_dirty_and_retains_hidden_selection(search):
    r=search;r.event('SearchScreen/Multi','OnSearch','beta')
    assert r.fx.evaluate('Multi.SearchText')=='beta'
    assert r.fx.evaluate('Multi.Selected.ID')==1
    assert r.fx.evaluate('Multi.Items')==[{'ID':2,'Title':'Beta review','Team':'South','Amount':20}]
    assert node(r)['selected_labels']==['Alpha planning'] and node(r)['selection']==[]
    assert len(r.collections['events'])==1
    choose(r,index=0)
    assert [row['ID'] for row in r.fx.evaluate('Multi.SelectedItems')]==[1,2]
    assert r.collections['events'][-1]=={'Event':'multi','Count':2}
    r.event('SearchScreen/Multi','OnSearch','gamma');choose(r,index=0)
    assert [row['ID'] for row in r.fx.evaluate('Multi.SelectedItems')]==[1,2,3]
    r.event('SearchScreen/Multi','OnSearch','beta');choose(r,index=0)
    assert [row['ID'] for row in r.fx.evaluate('Multi.SelectedItems')]==[1,3]
    choose(r,operation='clear')
    assert r.fx.evaluate('Multi.Selected') is None
    before=len(r.collections['events']);choose(r,operation='clear')
    assert len(r.collections['events'])==before and not r.diagnostics


def test_builtin_display_search_retains_full_items_indices_and_single_selection(search):
    r=search;r.event('SearchScreen/Single','OnSearch','DELTA')
    assert node(r,'Single')['options']==[{'index':3,'label':'Delta review'}]
    assert r.fx.evaluate('CountRows(Single.Items)')==4
    choose(r,'Single',3);assert r.fx.evaluate('Single.Selected.ID')==4
    r.event('SearchScreen/Single','OnSearch','alpha');choose(r,'Single',0)
    assert [r['ID'] for r in r.fx.evaluate('Single.SelectedItems')]==[1]
    with pytest.raises(ValueError,match='one selected'):r.event('SearchScreen/Single','OnChange',selection=[0,1])


@pytest.mark.parametrize('selection',[[True],[1.5],[-1],[99],[0,0],{},'1'])
def test_invalid_legacy_selection_never_mutates(search,selection):
    before=search.fx.evaluate('Multi.SelectedItems')
    with pytest.raises(ValueError):search.event('SearchScreen/Multi','OnChange',selection=selection)
    assert search.fx.evaluate('Multi.SelectedItems')==before


def test_stale_option_token_rejects_item_reorder_and_search_changes(search):
    r=search;value={'operation':'toggle','index':0,'option_token':node(r)['option_token']}
    r.event('SearchScreen/Multi','OnSearch','beta')
    with pytest.raises(ValueError,match='Choices changed'):r.event('SearchScreen/Multi','OnChange',value)
    assert r.fx.evaluate('Multi.Selected.ID')==1 and len(r.collections['events'])==1
    value={'operation':'toggle','index':0,'option_token':node(r)['option_token']}
    r.global_refs['Multi'].control.properties['Items']='=SortByColumns(Records,ID,SortOrder.Descending)';r.invalidate()
    with pytest.raises(ValueError,match='Choices changed'):r.event('SearchScreen/Multi','OnChange',value)


@pytest.mark.parametrize('value',[None,False,2,{},[]])
def test_search_requires_text(search,value):
    with pytest.raises(ValueError,match='Text'):search.event('SearchScreen/Multi','OnSearch',value)
    assert search.fx.evaluate('Multi.SearchText')==''


@pytest.mark.parametrize('prop,value',[('Visible','=false'),('DisplayMode','=DisplayMode.Disabled'),('DisplayMode','=DisplayMode.View')])
def test_search_and_selection_respect_visibility_and_mode(search,prop,value):
    r=search;r.global_refs['Multi'].control.properties[prop]=value;r.invalidate()
    r.event('SearchScreen/Multi','OnSearch','beta');r.event('SearchScreen/Multi','OnChange',selection=[1])
    assert r.fx.evaluate('Multi.SearchText')=='' and r.fx.evaluate('Multi.Selected.ID')==1


def test_nonsearchable_control_rejects_search_but_allows_selection(search):
    r=search;r.global_refs['Multi'].control.properties['IsSearchable']='=false';r.invalidate()
    with pytest.raises(ValueError,match='disabled'):r.event('SearchScreen/Multi','OnSearch','beta')
    r.event('SearchScreen/Multi','OnChange',selection=[1]);assert r.fx.evaluate('Multi.Selected.ID')==2


@pytest.mark.parametrize('prop',['SearchText','Selected','SelectedItems'])
def test_authored_outputs_are_diagnosed_and_preserved(search,prop):
    r=search;r.global_refs['Multi'].control.properties[prop]='="unsupported"';r.invalidate()
    with pytest.raises(FxError,match='output'):r.fx.evaluate('Multi.'+prop)
    assert r.global_refs['Multi'].control.properties[prop]=='="unsupported"'


def test_component_queries_callbacks_and_reset_are_isolated(search):
    r=search;r.event('SearchScreen/LeftSearch/Picker','OnSearch','gamma')
    choose(r,path='SearchScreen/LeftSearch/Picker',index=0)
    assert r.fx.evaluate('First(LeftSearch.Current).ID')==3 and r.fx.evaluate('LeftSearch.Query')=='gamma'
    assert r.fx.evaluate('RightSearch.Query')=='' and r.fx.evaluate('CountRows(RightSearch.Current)')==0
    assert r.collections['events'][-1]=={'Event':'left','Count':1}
    before=r.render(r.refs['SearchScreen/LeftSearch/Picker'])['search_reset']
    r.fx.evaluate('Reset(LeftSearch)',Context(r,behavior=True))
    assert r.fx.evaluate('LeftSearch.Query')=='' and r.fx.evaluate('CountRows(LeftSearch.Current)')==0
    assert r.render(r.refs['SearchScreen/LeftSearch/Picker'])['search_reset']!=before
    assert len(r.collections['events'])==2


def test_choice_form_search_is_clean_failed_save_retains_edit_and_retry_persists(search):
    r=search;path='SearchScreen/ChoiceForm/TeamCard/TeamChoice'
    r.event(path,'OnSearch','south')
    assert r.fx.evaluate('ChoiceForm.Unsaved') is False and r.fx.evaluate('ChoiceForm.Valid') is True
    choose(r,path=path,index=1)
    assert r.fx.evaluate('ChoiceForm.Unsaved') is True and r.fx.evaluate('ChoiceForm.Updates.Team.Value')=='South'
    r.store.failures['Projects']='write';r.event('SearchScreen/Save','OnSelect')
    assert r.fx.evaluate('ChoiceForm.Unsaved') is True and r.fx.evaluate('TeamChoice.Selected.Value')=='South'
    assert r.store.rows('Projects')[0]['Team']=={'Value':'North'}
    r.store.failures.clear();r.event('SearchScreen/Save','OnSelect')
    assert r.store.rows('Projects')[0]['Team']=={'Value':'South'} and r.fx.evaluate('ChoiceForm.Unsaved') is False
    r.event(path,'OnSearch','north');choose(r,path=path,operation='clear')
    assert r.fx.evaluate('ChoiceForm.Valid') is False
    r.event('SearchScreen/Reset','OnSelect')
    assert r.fx.evaluate('TeamChoice.SearchText')=='' and r.fx.evaluate('TeamChoice.Selected.Value')=='South'
    assert not r.diagnostics


def test_search_fixture_workflow_and_list_fixture_files_are_stored(tmp_path):
    p=search_project(tmp_path/'search');w=Workspace(tmp_path,p.root,start=False)
    try:
        entries=w.workflows.catalog()['scenarios'];assert len(entries)==1
        assert (p.root/'tests/search.workflow.json').is_file()
        result=w.workflows.run(entries[0]['scenario'],expected_revision=revision(p.root))
        assert result['status']=='passed',result['steps']
        assert w.runtime.store.rows('Projects')[0]['Team']=={'Value':'North'}
    finally:w.runtime.close()
    forms=forms_project(tmp_path/'forms');assert len(list((forms.root/'tests').glob('*.workflow.json')))==3


def test_custom_query_can_search_other_columns_without_second_label_filter(search):
    r=search;r.event('SearchScreen/Multi','OnSearch','north')
    assert [o['label'] for o in node(r)['options']]==['Alpha planning','Gamma planning']
    assert 'SearchScreen/Multi' in r.combo_search_items
    r.global_refs['Multi'].control.properties['Items']='=Records';r.invalidate()
    assert node(r)['options']==[] and 'SearchScreen/Multi' not in r.combo_search_items


@pytest.mark.parametrize('prop',['IsSearchable','SelectMultiple','DelayOutput'])
def test_combobox_flags_require_boolean(search,prop):
    search.global_refs['Multi'].control.properties[prop]='="false"';search.invalidate()
    with pytest.raises(FxError,match='Boolean'):search.fx.evaluate('Multi.'+prop)


def test_form_reset_submit_and_changed_item_signal_pending_search_drafts(search):
    r=search;ref=r.global_refs['TeamChoice'];baseline=r.combo_resets.get(ref.path,0)
    r.event('SearchScreen/Reset','OnSelect')
    assert r.combo_resets[ref.path]>baseline
    baseline=r.combo_resets[ref.path];r.event('SearchScreen/Save','OnSelect')
    assert r.combo_resets[ref.path]>baseline
    r.store.patch('Projects',{'ID':1},{'Team':{'Value':'South'}});r.invalidate()
    baseline=r.combo_resets[ref.path];r.state()
    assert r.combo_resets[ref.path]>baseline and r.fx.evaluate('TeamChoice.Selected.Value')=='South'


def test_default_record_errors_are_isolated_in_preview(search):
    r=search;ref=r.global_refs['Multi'];ref.control.properties.pop('ItemDisplayText',None)
    ref.control.properties['DefaultSelectedItems']='=Table(IfError(1/0,Error({Kind:ErrorKind.Network,Message:"default failed"})))';r.invalidate()
    assert any('default failed' in error for error in node(r)['errors'])
    assert node(r,'Single')['options'] and any(d['kind']=='Network' for d in r.diagnostics)


def test_selected_records_refresh_by_id_and_single_mode_restricts_output(search):
    r=search;r.event('SearchScreen/Multi','OnChange',selection=[0,1])
    ref=r.global_refs['Multi'];ref.control.properties['Items']='=Table({ID:1,Title:"Renamed",Team:"North",Amount:99},{ID:2,Title:"Beta review",Team:"South",Amount:20})';r.invalidate()
    assert r.fx.evaluate('Multi.Selected.Title')=='Renamed' and r.fx.evaluate('Multi.Selected.Amount')==99
    ref.control.properties['SelectMultiple']='=false';r.invalidate()
    assert len(r.fx.evaluate('Multi.SelectedItems'))==1
    assert len(r.collections['events'])==2

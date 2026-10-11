"""Single-selection contracts, display-only indicators and component/form scopes."""
import pytest
from powerapps_sim.fixtures import selectors_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.fx import Context
from powerapps_sim.source import Project, dump_yaml
from powerapps_sim.syntax import FxError
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision
from powerapps_sim.store import ListStore


@pytest.fixture
def controls(tmp_path):
    r=Runtime(selectors_project(tmp_path/'selectors'));r.restart()
    yield r;r.close()


def test_representative_fixture_scopes_labels_defaults_and_dimensions(controls):
    r=controls;state=r.state()
    assert r.fx.evaluate('Status.Selected.Value')=='Draft'
    assert r.fx.evaluate('Priority.Selected.Amount')==25
    assert r.fx.evaluate('Priority.Height')==96
    assert r.fx.evaluate('LeftChoice.Current.Value')=='Draft'
    assert r.fx.evaluate('RightChoice.Current.Value')=='Approved'
    radio=next(c for c in state['tree']['children'] if c['name']=='Priority')
    assert [o['label'] for o in radio['options']]==['Low','Normal','High']
    assert radio['selection']==[0] and not r.diagnostics


def test_horizontal_radio_default_height_includes_padding(controls):
    r=controls;r.global_refs['Priority'].control.properties.update({'Layout':'=Layout.Horizontal','PaddingTop':'=4','PaddingBottom':'=8'});r.invalidate()
    assert r.fx.evaluate('Priority.Height')==44 and not r.diagnostics


def test_hidden_spinner_unsupported_callback_is_reported_before_preview(tmp_path):
    p=Project(tmp_path/'hidden');p.update_source('Src/main.pa.yaml',dump_yaml({'Screens':{'Home':{'Children':[
        {'Loading':{'Control':'ModernSpinner@1.1.0','Properties':{'Visible':'=false','OnChange':'=Set(unexpected,true)'}}}]}}}))
    r=Runtime(p)
    try:
        r.restart()
        assert any(d['category']=='unsupported' and d['member']=='Loading.OnChange' for d in r.diagnostics)
        assert 'unexpected' not in r.globals
    finally:r.close()


@pytest.mark.parametrize('name,index,key,expected',[('Status',2,'Value','Approved'),('Priority',1,'Label','Normal')])
def test_callbacks_observe_selected_record_and_reselect_has_no_callback(controls,name,index,key,expected):
    r=controls;r.event('ChoicesScreen/'+name,'OnChange',selection=[index])
    assert r.fx.evaluate(name+'.Selected.'+key)==expected
    assert r.collections['events'][-1]['Value']==expected
    before=list(r.collections['events'])
    r.event('ChoicesScreen/'+name,'OnChange',selection=[index])
    assert r.collections['events']==before


def test_reactive_scalar_default_and_record_reset(controls):
    r=controls;r.state();r.event('ChoicesScreen/Status','OnChange',selection=[2])
    before=list(r.collections['events'])
    r.fx.evaluate('Set(defaultStatus,"Submitted")',Context(r,behavior=True))
    assert r.fx.evaluate('Status.Selected.Value')=='Submitted'
    r.event('ChoicesScreen/Priority','OnChange',selection=[2])
    r.fx.evaluate('Reset(Priority)',Context(r,behavior=True))
    assert r.fx.evaluate('Priority.Selected.ID')==1
    assert len(r.collections['events'])==len(before)+1


def test_selected_record_refreshes_fields_and_disappears_when_removed(controls):
    r=controls;r.event('ChoicesScreen/Priority','OnChange',selection=[1])
    priority=r.global_refs['Priority'];priority.control.properties['Items']='=Table({ID:2,Label:"Updated",Amount:66})';r.invalidate()
    assert r.fx.evaluate('Priority.Selected.Amount')==66
    priority.control.properties['Items']='=Table({ID:3,Label:"Other",Amount:100})';r.invalidate()
    assert r.fx.evaluate('Priority.Selected') is None
    assert len(r.collections['events'])==2


@pytest.mark.parametrize('selection',[[True],[1.5],[0,1],[-1],[99],{},'1'])
def test_invalid_selection_does_not_mutate_state(controls,selection):
    r=controls;before=r.fx.evaluate('Status.Selected')
    with pytest.raises(ValueError):r.event('ChoicesScreen/Status','OnChange',selection=selection)
    assert r.fx.evaluate('Status.Selected')==before and len(r.collections['events'])==1


def test_value_events_and_output_assignments_are_rejected(controls):
    r=controls
    with pytest.raises(ValueError,match='indices'):r.event('ChoicesScreen/Status','OnChange',value='Approved')
    r.event('ChoicesScreen/Status','OnChange',selection=[1])
    r.global_refs['Status'].control.properties['Selected']='={Value:"Approved"}';r.invalidate()
    with pytest.raises(FxError,match='output'):r.fx.evaluate('Status.Selected')
    assert any(d['category']=='unsupported' for d in r.diagnostics)


@pytest.mark.parametrize('family',['ModernDropdown','ModernRadio'])
@pytest.mark.parametrize('default',['=Blank()','="absent"','=Table({Value:"Draft"})'])
def test_empty_missing_and_invalid_defaults(controls,family,default):
    r=controls;ref=r.global_refs['Status'];ref.control.kind=family+'@1.0.0'
    ref.control.properties['Default']=default;r.invalidate()
    if default.startswith('=Table'):
        with pytest.raises(FxError,match='not a table'):ref.property('Selected')
    else:assert ref.property('Selected') is None


def test_component_callbacks_and_resets_preserve_other_instances(controls):
    r=controls;r.event('ChoicesScreen/LeftChoice/Picker','OnChange',selection=[1])
    assert r.globals['LeftChoiceValue']=={'Value':'Submitted'}
    assert r.fx.evaluate('LeftChoice.Current.Value')=='Submitted'
    assert r.fx.evaluate('RightChoice.Current.Value')=='Approved'
    r.fx.evaluate('Reset(LeftChoice)',Context(r,behavior=True))
    assert r.fx.evaluate('LeftChoice.Current.Value')=='Draft'
    assert r.fx.evaluate('RightChoice.Current.Value')=='Approved'
    assert r.globals['LeftChoiceValue']=={'Value':'Submitted'} and not r.diagnostics


def test_disabled_and_hidden_selectors_preserve_values(controls):
    r=controls;r.global_refs['Status'].control.properties['DisplayMode']='=DisplayMode.View'
    r.global_refs['Priority'].control.properties['Visible']='=false';r.invalidate()
    r.event('ChoicesScreen/Status','OnChange',selection=[2]);r.event('ChoicesScreen/Priority','OnChange',selection=[2])
    assert r.fx.evaluate('Status.Selected.Value')=='Draft' and r.fx.evaluate('Priority.Selected.ID')==1
    assert len(r.collections['events'])==1


@pytest.mark.parametrize('value,expected',[('-4',0),('42',42),('200',100)])
def test_progress_clamps_display_preserving_powerfx_value(controls,value,expected):
    r=controls;ref=r.global_refs['Progress'];ref.control.properties['Value']='='+value;r.invalidate()
    assert r.render(ref)['progress']=={'indeterminate':False,'max':100,'value':expected}
    assert r.fx.evaluate('Progress.Value')==int(value) and not r.diagnostics


def test_indeterminate_progress_does_not_observe_value_or_max_errors(controls):
    r=controls;ref=r.global_refs['Progress'];ref.control.properties.update({'Value':'=1/0','Max':'=1/0','Indeterminate':'=true'});r.invalidate()
    assert r.render(ref)['progress']=={'indeterminate':True}
    assert not r.diagnostics
    with pytest.raises(FxError):r.fx.evaluate('Progress.Value')


@pytest.mark.parametrize('prop,formula',[('Value','="text"'),('Max','=0'),('Max','=-1'),('Indeterminate','="true"')])
def test_invalid_indicator_values_remain_errors(controls,prop,formula):
    r=controls;r.global_refs['Progress'].control.properties[prop]=formula;r.invalidate()
    tree=r.render(r.global_refs['Progress'])
    assert tree['errors'] and r.diagnostics


@pytest.mark.parametrize('name',['Progress','Loading'])
def test_indicators_reject_browser_events(controls,name):
    with pytest.raises(ValueError,match='display-only'):controls.event('ChoicesScreen/'+name,'OnChange',50)
    assert len(controls.collections['events'])==1


@pytest.mark.parametrize('name',['Progress','Loading'])
def test_powerfx_select_cannot_invoke_display_only_indicators(controls,name):
    r=controls;r.global_refs[name].control.properties['OnSelect']='=Set(unexpected,true)'
    with pytest.raises(FxError,match='OnSelect'):
        r.fx.evaluate(f'Select({name})',Context(r,behavior=True))
    r.drain_events()
    assert 'unexpected' not in r.globals and not r.event_queue


def test_spinner_callbacks_and_legacy_selector_properties_report_unsupported(controls):
    r=controls;r.global_refs['Loading'].control.properties['OnChange']='=Set(unexpected,true)'
    r.global_refs['Status'].control.properties['DefaultSelectedItems']='=["Approved"]';r.invalidate()
    r.state()
    assert 'unexpected' not in r.globals
    assert any(d['category']=='unsupported' and d['member']=='Loading.OnChange' for d in r.diagnostics)
    assert any(d['category']=='unsupported' and d['member']=='Status.DefaultSelectedItems' for d in r.diagnostics)


def test_gallery_radio_defaults_and_callbacks_keep_thisitem_scope(tmp_path):
    p=Project(tmp_path/'gallery');p.update_source('Src/main.pa.yaml',dump_yaml({'Screens':{'Home':{'Children':[
        {'Rows':{'Control':'Gallery@2.15.0','Properties':{'Items':'=Table({ID:1,Status:"Draft"},{ID:2,Status:"Approved"})'},'Children':[
            {'Choice':{'Control':'ModernRadio@1.0.0','Properties':{'Items':'=["Draft","Approved"]','Default':'=ThisItem.Status','OnChange':'=Set(chosenRow,ThisItem.ID); Set(chosenStatus,Self.Selected.Value)'}}}]}}]}}}))
    r=Runtime(p)
    try:
        r.restart();tree=r.render(r.global_refs['Rows']);children=[row['children'][0] for row in tree['rows']]
        assert [c['selection'] for c in children]==[[0],[1]]
        r.event(children[1]['path'],'OnChange',selection=[0])
        assert r.globals['chosenRow']==2 and r.globals['chosenStatus']=='Draft'
        assert r.refs[children[0]['path']].property('Selected')=={'Value':'Draft'} and not r.diagnostics
    finally:r.close()


def test_choice_form_updates_validation_unsaved_save_and_failed_save(tmp_path):
    p=Project(tmp_path/'form');p.update_source('Src/main.pa.yaml',dump_yaml({'Screens':{'Home':{'Children':[
        {'Edit':{'Control':'Form@2.4.4','Properties':{'DataSource':'=Drafts','Item':'=First(Drafts)'},'Children':[
            {'StatusCard':{'Control':'TypedDataCard@1.0.7','Properties':{'DataField':'="Status"','Default':'=ThisItem.Status','Required':'=true','Update':'=Choice.Selected'},'Children':[
                {'Choice':{'Control':'ModernDropdown@1.0.0','Properties':{'Items':'=Choices(Drafts.Status)','Default':'=Parent.Default'}}}]}}]}},
        {'Save':{'Control':'ModernButton@1.0.0','Properties':{'OnSelect':'=SubmitForm(Edit)'}}}]}}}))
    store=ListStore(p.root/'data.sqlite',schema_root=p.root/'lists')
    store.add_list('Drafts',{'fields':{'ID':{'type':'integer'},'Status':{'type':'object','properties':{'Value':{'type':'string'}},'required':True}},'choices':{'Status':['Draft','Approved']}})
    store.import_rows('Drafts',[{'ID':1,'Status':{'Value':'Draft'}}]);store.close()
    r=Runtime(p)
    try:
        r.restart()
        assert r.fx.evaluate('Edit.Unsaved') is False
        r.event('Home/Edit/StatusCard/Choice','OnChange',selection=[])
        assert r.fx.evaluate('Edit.Valid') is False and r.fx.evaluate('Edit.Unsaved') is True
        r.event('Home/Save','OnSelect');assert r.store.rows('Drafts')[0]['Status']=={'Value':'Draft'}
        r.event('Home/Edit/StatusCard/Choice','OnChange',selection=[1])
        assert r.fx.evaluate('Edit.Updates.Status')=={'Value':'Approved'}
        r.store.failures['Drafts']='write';r.event('Home/Save','OnSelect')
        assert r.fx.evaluate('Choice.Selected.Value')=='Approved' and r.fx.evaluate('Edit.Unsaved') is True
        r.store.failures.clear();r.event('Home/Save','OnSelect')
        assert r.store.rows('Drafts')[0]['Status']=={'Value':'Approved'}
        assert r.fx.evaluate('Edit.Unsaved') is False and not r.diagnostics
    finally:r.close()


def test_packaged_selector_workflow_passes_in_isolation(tmp_path):
    p=selectors_project(tmp_path/'selectors');w=Workspace(tmp_path,p.root)
    try:
        entry=w.workflows.catalog()['scenarios'][0]
        result=w.workflows.run(entry['scenario'],expected_revision=revision(p.root))
        assert result['status']=='passed',result['steps']
        assert not result['diagnostics'] and w.runtime.globals['defaultStatus']=='Draft'
    finally:w.runtime.close()

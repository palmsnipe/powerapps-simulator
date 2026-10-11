"""Versioned tab defaults, scopes, events, source fidelity and SQLite recovery."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import pytest
from powerapps_sim.fixtures import tabs_project
from powerapps_sim.runtime import Runtime,serial
from powerapps_sim.fx import table
from powerapps_sim.syntax import FxError

@pytest.fixture
def r(tmp_path):
    result=Runtime(tabs_project(tmp_path/'tabs'));result.restart();result.state()
    assert not result.diagnostics
    yield result
    result.close()

def left(r):return r.refs['TabsLab/LeftPanel/Tabs']
def choose(r,ref,index,token=None):
    r.event(ref.path,'OnChange',{'indices':[index],'option_token':token or r.selector_token(ref,table(ref.property('Items')))});r.state()

def test_native_versions_have_distinct_contracts_and_selected_record_schema(r):
    old=left(r);new=r.global_refs['ModernTabs']
    assert old.property('Selected')['Key']=='review' and new.property('Selected')['Value']=='Reports'
    assert old.property('Alignment')=='Horizontal' and new.property('Alignment')=='Center'
    assert old.property('TabSize')=='Medium'
    for ref in (old,new):
        kind=r.binder.property_type(ref.control,'Selected')
        assert kind.kind=='Record' and kind.fields
    old.control=deepcopy(old.control);old.control.properties.pop('TabSize');old.control.properties.pop('Appearance');old.control.properties.pop('Alignment');r.invalidate()
    assert old.property('TabSize')=='Large' and old.property('Appearance')=='Transparent'
    assert old.property('Alignment')=='Horizontal'
    new.control.properties.pop('Alignment');new.control.properties.pop('Appearance');r.invalidate()
    assert new.property('Alignment')=='Center' and new.property('Appearance')=='Transparent'

@pytest.mark.parametrize('value,key',[('=Blank()','draft'),({'ID':3},'complete'),({'ID':2},'review'),({'ID':90},None)])
def test_record_defaults_match_existing_items_and_preserve_source(r,value,key):
    ref=left(r);ref.control=deepcopy(ref.control);ref.control.properties['Default']=value;r.invalidate()
    selected=ref.property('Selected')
    assert (selected['Key'] if selected else None)==key
    assert ref.control.properties['Default']==value
    assert not r.collections['trace']

@pytest.mark.parametrize('raw,expected',[('="Settings"','Settings'),('={Value:"Overview"}','Overview'),('=Blank()','Overview'),('="Missing"',None)])
def test_new_default_accepts_scalar_or_record_in_single_column_items(r,raw,expected):
    ref=r.global_refs['ModernTabs'];ref.control.properties['Default']=raw;r.invalidate()
    selected=ref.property('Selected');assert (selected['Value'] if selected else None)==expected


def test_repeated_click_selects_without_duplicate_change_and_peer_state_isolated(r):
    ref=left(r);choose(r,ref,1)
    assert r.fx.evaluate('LeftPanel.Clicks=1 && LeftPanel.Changes=0 && IsEmpty(LeftPanel.History)')
    choose(r,ref,2);choose(r,ref,2)
    assert r.fx.evaluate('LeftPanel.Clicks=3 && LeftPanel.Changes=1 && leftKey="complete" && CountRows(LeftPanel.History)=1')
    assert r.fx.evaluate('RightPanel.Picked.Key="draft" && RightPanel.Clicks=0 && RightPanel.Changes=0')


def test_reset_changes_token_and_restores_default_without_callbacks(r):
    ref=left(r);choose(r,ref,2);token=r.render(ref)['option_token']
    r.fx.evaluate('Reset(Tabs)',ref.context(behavior=True));r.state()
    assert ref.property('Selected')['Key']=='review' and r.render(ref)['option_token']!=token
    assert r.fx.evaluate('LeftPanel.Clicks=1 && LeftPanel.Changes=1')
    with pytest.raises(ValueError,match='Tabs changed'):choose(r,ref,0,token)
    assert ref.property('Selected')['Key']=='review'


def test_changed_default_resets_selection_and_token_without_change_callback(r):
    ref=left(r);choose(r,ref,0);token=r.render(ref)['option_token']
    r.event('TabsLab/ChangeSeed','OnSelect');r.state()
    assert ref.property('Selected')['Key']=='complete' and r.render(ref)['option_token']!=token
    assert r.fx.evaluate('LeftPanel.Clicks=1 && LeftPanel.Changes=1')
    with pytest.raises(ValueError):choose(r,ref,1,token)


def test_refreshed_items_preserve_order_current_record_and_reject_stale_token(r):
    ref=left(r);ref.control=deepcopy(ref.control);choose(r,ref,2);token=r.render(ref)['option_token']
    ref.control.properties['Items']='=Table({ID:3,Key:"complete",Label:"Renamed"},{ID:2,Key:"review",Label:"Second"})';r.invalidate()
    node=r.render(ref)
    assert [o['label'] for o in node['options']]==['Renamed','Second']
    assert node['selection']==[0] and ref.property('Selected')['Label']=='Renamed'
    with pytest.raises(ValueError,match='Tabs changed'):choose(r,ref,1,token)


def test_removed_selection_uses_current_default_without_event(r):
    ref=left(r);ref.control=deepcopy(ref.control);choose(r,ref,2)
    ref.control.properties['Items']='=Filter(TabsPanel.Options,Key<>"complete")';r.invalidate()
    assert ref.property('Selected')['Key']=='review'
    assert r.fx.evaluate('LeftPanel.Changes=1')

def test_item_label_errors_disable_only_the_affected_row(r):
    ref=left(r);ref.control=deepcopy(ref.control)
    ref.control.properties['ItemDisplayText']='=If(ThisItem.ID=2,1/0,ThisItem.Label)';r.invalidate()
    node=r.render(ref)
    assert node['options'][1]['disabled'] and not node['options'][0].get('disabled')
    assert any(d['member']=='Tabs.ItemDisplayText' for d in r.diagnostics)
    choose(r,ref,0)
    assert ref.property('Selected')['Key']=='draft'

def test_lazy_default_catch_and_error_observation_are_isolated(r):
    ref=left(r);ref.control=deepcopy(ref.control)
    ref.control.properties['Default']='=IfError(LookUp(Table({ID:2}),1/0=0),{ID:2})';r.invalidate();r.state()
    assert ref.property('Selected')['Key']=='review' and not r.collections['failures']
    ref.control.properties['Default']='=1/0';r.invalidate();r.state()
    observed=len(r.collections['failures']);assert observed>0
    assert all(e['Source']==ref.path+'.Default' for e in r.collections['failures'])
    r.state();assert len(r.collections['failures'])==observed
    assert not r.render(r.global_refs['ModernTabs'])['errors']

def test_default_selection_cycle_is_diagnosed_without_affecting_other_tabs(r):
    ref=left(r);ref.control=deepcopy(ref.control)
    ref.control.properties['Default']='=Self.Selected';r.invalidate();r.state()
    assert any(d['kind']=='Cycle' for d in r.diagnostics)
    assert r.global_refs['ModernTabs'].property('Selected')['Value']=='Reports'

def test_unknown_version_reports_unsupported_instead_of_crashing(r):
    ref=left(r);ref.control=deepcopy(ref.control);ref.control.kind='ModernTabList@9.0.0';r.invalidate()
    with pytest.raises(FxError,match='version'):ref.property('Selected')
    node=r.render(ref)
    assert node['errors'] and any(d['kind']=='Unsupported' for d in r.diagnostics)

@pytest.mark.parametrize('selection',[[],[0,1],[True],[1.5],[-1],[4],['1'],None])
def test_invalid_selection_rejected_before_mutation(r,selection):
    ref=left(r)
    with pytest.raises(ValueError):r.event(ref.path,'OnChange',selection=selection)
    assert r.fx.evaluate('LeftPanel.Picked.Key="review" && LeftPanel.Clicks=0 && LeftPanel.Changes=0')

@pytest.mark.parametrize('prop,raw',[
 ('Alignment','=TabListAlignment.End'),('Appearance','=TabListAppearance.Filled'),('TabSize','="Giant"'),
 ('Default','=["draft","review"]'),('BorderThickness','=-1'),('RadiusBottomRight','=-2'),
 ('Color','="red"'),('Italic','=1'),('Align','="Top"'),('ItemDisplayText','=ThisItem.Missing'),
 ('Selected','={Key:"draft"}'),('SelectMultiple','=true'),('DefaultSelectedItems','=Table({Key:"draft"})')])
def test_errors_are_scoped_and_healthy_peers_remain_usable(r,prop,raw):
    ref=left(r);ref.control=deepcopy(ref.control);ref.control.properties[prop]=raw;r.invalidate();r.state()
    assert any(d['member'].endswith('.'+prop) for d in r.diagnostics)
    assert not r.render(r.refs['TabsLab/RightPanel/Tabs'])['errors']
    assert not r.render(r.global_refs['ModernTabs'])['errors']


def test_new_version_does_not_accept_legacy_orientation_or_tab_size(r):
    ref=r.global_refs['ModernTabs'];ref.control.properties['Alignment']='=LayoutDirection.Vertical';r.invalidate()
    with pytest.raises(FxError):ref.property('Alignment')
    ref.control.properties['TabSize']='=TabSize.Large';r.invalidate()
    with pytest.raises(FxError):ref.property('TabSize')


def test_view_disabled_hidden_and_parent_modes_block_events(r):
    ref=r.refs['TabsLab/RightPanel/Tabs'];r.event('TabsLab/ToggleGate','OnSelect');choose(r,ref,2)
    assert r.fx.evaluate('RightPanel.Clicks=0 && RightPanel.Picked.Key="draft"')
    r.event('TabsLab/ToggleGate','OnSelect');ref.control=deepcopy(ref.control)
    for prop,raw in [('DisplayMode','=DisplayMode.Disabled'),('Visible','=false')]:
        ref.control.properties[prop]=raw;r.invalidate();choose(r,ref,2)
        assert r.fx.evaluate('RightPanel.Clicks=0')
        ref.control.properties.pop(prop);r.invalidate()
    ref.parent.control.properties['DisplayMode']='=DisplayMode.View';r.invalidate();choose(r,ref,2)
    assert r.fx.evaluate('RightPanel.Clicks=0')

@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('language',['en-US','fr-CA'])
def test_full_workflow_on_disposable_snapshot_preserves_owner(tmp_path,mode,language):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision,data_revision
    p=tabs_project(tmp_path/'p');p.config['environment'].update(number_mode=mode,language=language,enum_mode='strong');p.save_config()
    w=Workspace(tmp_path/'workspace',p.root)
    try:
        before=(revision(p.root),data_revision(w.runtime.store),serial(w.ai.read_runtime()))
        entry=w.workflows.catalog()['scenarios'][0]
        result=w.workflows.run(entry['scenario'],expected_revision=before[0])
        assert result['status']=='passed' and len(result['steps'])==33,result
        assert len(result['diagnostics'])==1
        assert (revision(p.root),data_revision(w.runtime.store),serial(w.ai.read_runtime()))==before
    finally:w.runtime.close()


def test_export_roundtrip_omits_renderer_contract_tokens_and_retains_versions(r):
    from powerapps_sim.source import dump_yaml,load_yaml
    before=r.project.documents['Src/tabs.pa.yaml']
    assert load_yaml(dump_yaml(load_yaml(before)))==load_yaml(before)
    assert 'ModernTabList@1.0.2' in before and 'ModernTabList@1.0.0' in before
    assert 'tab_contract' not in before and 'option_token' not in before
    with ZipFile(BytesIO(r.project.export())) as archive:
        assert archive.namelist()==['Src/tabs.pa.yaml']
        exported=archive.read(archive.namelist()[0]).decode()
        assert load_yaml(exported)==load_yaml(before)
        assert 'tab_contract' not in exported and 'option_token' not in exported


def test_mapped_snapshot_is_persistent_after_restart(r):
    choose(r,left(r),2);r.event('TabsLab/SaveSnapshot','OnSelect');r.state()
    assert r.store.rows('Snapshots')[0]['Selected section']=='complete'
    r.restart();assert r.fx.evaluate('First(Snapshots).\'Selected section\'="complete"')
    assert not r.diagnostics

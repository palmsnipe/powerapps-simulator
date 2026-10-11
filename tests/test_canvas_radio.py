from copy import deepcopy
import pytest
from powerapps_sim.canvas_selectors import catalog,token,search_token,radio_enums
from powerapps_sim.fixtures import canvas_radio_project
from powerapps_sim.source import Project,dump_yaml
from powerapps_sim.runtime import Runtime
from powerapps_sim.syntax import FxError
from powerapps_sim.fx import Context


def make(tmp_path,version='0.0.24',properties=None,family='Radio'):
    p=Project(tmp_path/'radio')
    props={'Items':'=["A","B","C"]','DefaultSelectedItems':'=[{Value:"A"}]','OnChange':'=Collect(changes,{Row:Self.Selected,Count:CountRows(Self.SelectedItems)})',**(properties or {})}
    p.update_source('Src/radio.pa.yaml',dump_yaml({'App':{'Properties':{'OnStart':'=Clear(changes)'}},'Screens':{'Home':{'Children':[
        {'Picker':{'Control':family+'@'+version,'Properties':props}},
        {'Peer':{'Control':family+'@'+version,'Properties':{'Items':'=["A","B","C"]','DefaultSelectedItems':'=[{Value:"A"}]'}}},
        {'Modern':{'Control':'ModernRadio@1.0.0','Properties':{'Items':'=["A","B","C"]','Default':'="B"'}}}]}}}))
    r=Runtime(p);r.restart();r.state();return r


def send(r,g=None,indices=None,**data):
    g=g or r.refs['Home/Picker']
    r.event(g.path,'OnChange',{'indices':indices or [],'option_token':token(g),**data});r.state()


@pytest.mark.parametrize('version',['0.0.23','0.0.24'])
@pytest.mark.parametrize('number',['float','decimal'])
@pytest.mark.parametrize('enum_mode',['legacy','strong'])
def test_native_outputs_defaults_reset_and_property_types(tmp_path,version,number,enum_mode):
    r=make(tmp_path,version)
    try:
        r.environment.update(number_mode=number,enum_mode=enum_mode);r.analyze();r.invalidate();g=r.refs['Home/Picker'];r.state()
        assert not r.diagnostics,r.diagnostics
        assert g.property('Selected')=={'Value':'A'} and g.property('SelectedItems')==[{'Value':'A'}]
        assert r.fx.evaluate('Modern.Selected.Value="B"')
        for name in catalog()['Radio'][version]['types']:g.property(name)
        assert r.binder.property_type(g.control,'Selected').kind=='Record'
        assert r.binder.property_type(g.control,'SelectedItems').row.fields['Value'].kind=='Text'
        send(r,indices=[2]);send(r,indices=[2]);assert len(r.collections['changes'])==1 and g.state['dirty']
        assert r.collections['changes'][0]=={'Row':{'Value':'C'},'Count':1}
        assert r.refs['Home/Peer'].property('Selected')=={'Value':'A'}
        stale=token(g);r.fx.evaluate('Reset(Picker)',Context(r,behavior=True));r.state()
        assert g.property('Selected')=={'Value':'A'} and not g.state.get('dirty') and len(r.collections['changes'])==1
        send(r,indices=[1],option_token=stale);assert g.property('Selected')=={'Value':'A'}
    finally:r.close()


@pytest.mark.parametrize('prop',['Default','ItemDisplayText','Selected','SelectedItems','SelectedText','OnSelect','SelectMultiple','SearchText','TriggerOutput','DelayOutput','ValidationState','Fields','Color','Size','Reset','PCFTeamsTheme','AcceptsFocus'])
def test_unsupported_source_properties_preserved_and_peers_work(tmp_path,prop):
    r=make(tmp_path,properties={prop:'=Blank()'})
    try:
        assert any(d['kind']=='Unsupported' for d in r.diagnostics)
        assert prop in r.refs['Home/Picker'].control.properties
        with pytest.raises(FxError):r.refs['Home/Picker'].property(prop)
        assert r.refs['Home/Peer'].property('Selected')=={'Value':'A'}
    finally:r.close()


@pytest.mark.parametrize('prop,formula',[('Items','=42'),('Items','=Table(1)'),('DefaultSelectedItems','={Value:"A"}'),('DefaultSelectedItems','=Table(1)'),('Required','="yes"'),('Layout','="HorizontalStacked"'),('Layout','=1'),('RadioSize','=-1'),('RadioSize','="large"'),('FontSize','=-1'),('TabIndex','=0.5'),('FontColor','=42'),('Width','=-1')])
def test_invalid_properties_are_source_located_and_isolated(tmp_path,prop,formula):
    r=make(tmp_path,properties={prop:formula})
    try:
        assert r.diagnostics
        assert r.refs['Home/Peer'].property('Selected')=={'Value':'A'}
        assert any(d.get('source')=='Src/radio.pa.yaml' for d in r.diagnostics),r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('layout,backing',[('Vertical','Vertical'),('Horizontal','Horizontal'),('HorizontalStacked','Horizontal Stacked')])
@pytest.mark.parametrize('enum_mode',['legacy','strong'])
def test_archived_enum_names_backings_and_styling(tmp_path,layout,backing,enum_mode):
    r=make(tmp_path,properties={'Layout':'=RadioGroupCanvas.Layout.'+layout,'BasePaletteColor':'=RGBA(15,108,189,1)','FontColor':'=Color.Blue','FontSize':'=18','FontWeight':'="Semibold"','FontItalic':'=true','FontUnderline':'=true','RadioSize':'=20'})
    try:
        r.environment['enum_mode']=enum_mode;r.analyze();r.invalidate();n=r.state()['tree']['children'][0]
        assert not r.diagnostics,r.diagnostics
        assert n['props']['Layout']==backing and n['props']['RadioSize']==20
        assert radio_enums()['Layout'][layout]==backing
    finally:r.close()


@pytest.mark.parametrize('data',[{}, {'indices':[True]}, {'indices':[-1]}, {'indices':[99]}, {'indices':[0,0]}, {'indices':[0,1]}, {'indices':[0],'extra':True}, {'operation':'toggle','index':False}, {'operation':'remove','index':9}, {'operation':'clear','extra':True}])
def test_malformed_events_do_not_mutate_selection_or_callbacks(tmp_path,data):
    r=make(tmp_path)
    try:
        g=r.refs['Home/Picker'];before=deepcopy(g.state)
        with pytest.raises(ValueError):r.event(g.path,'OnChange',{**data,'option_token':token(g)})
        assert g.state==before and not r.collections['changes']
    finally:r.close()


@pytest.mark.parametrize('family,version',[('Radio','0.0.24'),('DropDown','0.0.44'),('ComboBox','0.0.49')])
def test_identical_native_instances_cannot_exchange_selection_or_search_events(tmp_path,family,version):
    r=make(tmp_path,version,family=family)
    try:
        g,peer=r.refs['Home/Picker'],r.refs['Home/Peer']
        assert token(g)!=token(peer)
        send(r,g,indices=[2],option_token=token(peer));assert g.property('Selected')=={'Value':'A'} and not r.collections['changes']
        if family=='ComboBox':
            g.control.properties['IsSearchable']=peer.control.properties['IsSearchable']='=true';r.invalidate()
            assert search_token(g)!=search_token(peer)
            r.event(g.path,'OnSearch',{'text':'C','reset_token':search_token(peer)})
            assert g.property('SearchText')==''
    finally:r.close()


def test_reactive_items_defaults_and_stale_restart_events(tmp_path):
    r=make(tmp_path)
    try:
        g=r.refs['Home/Picker'];old=token(g)
        g.control.properties['DefaultSelectedItems']='=[{Value:"B"}]';r.invalidate();r.state()
        send(r,indices=[2],option_token=old);assert g.property('Selected')=={'Value':'B'} and not r.collections['changes']
        old=token(g);g.control.properties['Items']='=["C","B","A"]';r.invalidate();r.state()
        send(r,indices=[0],option_token=old);assert g.property('Selected')=={'Value':'B'}
        old=token(g);r.restart();r.state();send(r,indices=[0],option_token=old);assert g.property('Selected')=={'Value':'B'}
        g.control.properties['DefaultSelectedItems']='=Blank()';r.invalidate();r.state()
        assert g.property('Selected') is None and g.property('SelectedItems')==[] and not g.state.get('dirty')
    finally:r.close()


@pytest.mark.parametrize('items,labels',[('=Table({Value1:"Item 7",Value2:7,Value3:70},{Value1:"Item 10",Value2:10,Value3:100})',['Item 7','Item 10']),('=Table({ID:1,Title:"First"},{ID:2,Title:"Second"})',['First','Second']),('=Table({Amount:1},{Amount:2})',['1','2'])])
def test_local_multicolumn_display_rule_retains_full_selected_records(tmp_path,items,labels):
    r=make(tmp_path,properties={'Items':items,'DefaultSelectedItems':'=Table()'})
    try:
        n=r.state()['tree']['children'][0];assert [o['label'] for o in n['options']]==labels
        send(r,indices=[1]);g=r.refs['Home/Picker'];assert g.property('Selected')==g.property('Items')[1]
        assert not r.diagnostics,r.diagnostics
    finally:r.close()


def test_bad_display_cell_disables_only_that_row_and_missing_child_contract_reported(tmp_path):
    r=make(tmp_path,properties={'Items':'=Table({Value:Error({Kind:ErrorKind.Validation,Message:"bad label"})},{Value:"Good"})','DefaultSelectedItems':'=Table()'})
    try:
        n=r.state()['tree']['children'][0];assert n['options'][0]['disabled'] and not n['options'][1]['disabled']
        with pytest.raises(FxError):send(r,indices=[0])
        send(r,indices=[1]);assert r.refs['Home/Picker'].property('Selected')=={'Value':'Good'}
    finally:r.close()


@pytest.mark.parametrize('kind',['Radio@9.0.0','Radio@0.0.23'])
def test_unknown_versions_and_variants_preserve_healthy_controls(tmp_path,kind):
    r=make(tmp_path)
    try:
        g=r.refs['Home/Picker'];g.control=deepcopy(g.control);g.control.kind=kind
        if kind=='Radio@0.0.23':g.control.raw['Variant']='Unknown'
        r.invalidate();r.state();assert any(d['kind']=='Unsupported' for d in r.diagnostics)
        assert r.refs['Home/Peer'].property('Selected')=={'Value':'A'}
    finally:r.close()


@pytest.mark.parametrize('number',['float','decimal'])
@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('enum_mode',['legacy','strong'])
def test_public_workflow_form_shapes_owner_preservation_after_live_edit(tmp_path,number,language,enum_mode):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision,data_revision
    p=canvas_radio_project(tmp_path/'owner');w=Workspace(tmp_path,p.root,start=False)
    try:
        w.runtime.store.patch('Plans',{'ID':1},{'Decision':{'Value':'Approved'}})
        before=w.ai.read_runtime(),revision(p.root),data_revision(w.runtime.store),w.ai.export_source()
        scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);scenario['environment']={'number_mode':number,'language':language,'enum_mode':enum_mode}
        result=w.workflows.run(scenario,expected_revision=before[1])
        assert result['status']=='passed' and len(result['steps'])==26 and not result['diagnostics'],result
        assert before==(w.ai.read_runtime(),revision(p.root),data_revision(w.runtime.store),w.ai.export_source())
    finally:w.runtime.close()

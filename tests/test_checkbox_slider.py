"""Modern Checkbox/Slider contracts, reactive defaults, event scopes and resets."""
import pytest
from powerapps_sim.source import Project,dump_yaml
from powerapps_sim.runtime import Runtime
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError


@pytest.fixture
def controls(tmp_path):
    p=Project(tmp_path/'controls');p.update_source('Src/controls.pa.yaml',dump_yaml({
        'App':{'Properties':{'StartScreen':'=Home','OnStart':'=Set(initialChecked,true); Set(initialValue,30); ClearCollect(trace,{Name:"start"})'}},
        'Screens':{'Home':{'Children':[
            {'Check':{'Control':'ModernCheckbox@1.0.0','Properties':{'Checked':'=initialChecked','Label':'="Enabled"','OnCheck':'=Collect(trace,{Name:"check",Value:Self.Checked})','OnUncheck':'=Collect(trace,{Name:"uncheck",Value:Self.Checked})','OnSelect':'=Set(selectedValue,Self.Checked)'}}},
            {'Range':{'Control':'ModernSlider@1.0.0','Properties':{'Default':'=initialValue','Min':'=10','Max':'=90','Size':'=SliderSize.Medium','OnChange':'=Set(lastValue,Self.Value)'}}},
        ]}}}))
    r=Runtime(p);r.restart();yield r;r.close()


def test_initial_boolean_numeric_values_and_no_startup_events(controls):
    r=controls;r.state()
    assert r.fx.evaluate('Check.Checked') is True
    assert r.fx.evaluate('Range.Value')==30
    assert len(r.collections['trace'])==1 and 'selectedValue' not in r.globals
    assert r.fx.evaluate('Range.Size')=='Medium'
    assert not r.diagnostics


def test_checkbox_callbacks_observe_committed_boolean_without_onchange(controls):
    r=controls
    r.event('Home/Check','OnChange',False)
    assert r.fx.evaluate('Check.Checked') is False and r.globals['selectedValue'] is False
    assert r.collections['trace'][-1]=={'Name':'uncheck','Value':False}
    r.event('Home/Check','OnChange',True)
    assert r.collections['trace'][-1]=={'Name':'check','Value':True}
    assert not r.diagnostics


def test_reset_and_reactive_defaults_do_not_invent_events(controls):
    r=controls;r.state();r.event('Home/Check','OnChange',False);r.event('Home/Range','OnChange',80)
    before=list(r.collections['trace']);ctx=Context(r,behavior=True)
    r.fx.evaluate('Reset(Check); Reset(Range)',ctx)
    assert r.fx.evaluate('Check.Checked') is True and r.fx.evaluate('Range.Value')==30
    assert r.collections['trace']==before and r.globals['lastValue']==80
    r.fx.evaluate('Set(initialChecked,false); Set(initialValue,40)',ctx)
    assert r.fx.evaluate('Check.Checked') is False and r.fx.evaluate('Range.Value')==40
    assert r.collections['trace']==before


@pytest.mark.parametrize('value,expected',[(-40,10),(34.5,34.5),(150,90)])
def test_slider_bounds_and_self_value_callback(controls,value,expected):
    r=controls;r.event('Home/Range','OnChange',value)
    assert r.fx.evaluate('Range.Value')==expected and r.globals['lastValue']==expected
    assert not r.diagnostics


@pytest.mark.parametrize('value',[None,True,float('nan'),float('inf'),'50'])
def test_slider_invalid_event_values_leave_state_unchanged(controls,value):
    r=controls;r.state()
    with pytest.raises((ValueError,FxError)):r.event('Home/Range','OnChange',value)
    assert r.fx.evaluate('Range.Value')==30 and 'lastValue' not in r.globals


def test_disabled_and_hidden_controls_do_not_change_values(controls):
    r=controls;r.refs['Home/Range'].control.properties['DisplayMode']='=DisplayMode.View'
    r.refs['Home/Check'].control.properties['Visible']='=false';r.invalidate()
    r.event('Home/Range','OnChange',80);r.event('Home/Check','OnChange',False)
    assert r.fx.evaluate('Range.Value')==30 and r.fx.evaluate('Check.Checked') is True
    assert len(r.collections['trace'])==1


def test_invalid_limits_and_output_assignment_are_visible_errors(controls):
    r=controls;r.refs['Home/Range'].control.properties['Min']='=200';r.invalidate()
    with pytest.raises(FxError,match='Min'):r.fx.evaluate('Range.Value')
    r.refs['Home/Range'].control.properties['Min']='=10';r.refs['Home/Range'].control.properties['Value']='=22';r.invalidate()
    with pytest.raises(FxError,match='output'):r.fx.evaluate('Range.Value')
    assert any(d['category']=='unsupported' for d in r.diagnostics)
    r.refs['Home/Check'].control.properties['Checked']='="bad"';r.invalidate()
    with pytest.raises(FxError,match='Boolean'):r.fx.evaluate('Check.Checked')


def test_reactive_slider_limits_clamp_output_without_firing_events(controls):
    r=controls;r.event('Home/Range','OnChange',80)
    r.refs['Home/Range'].control.properties['Max']='=50';r.invalidate()
    assert r.fx.evaluate('Range.Value')==50 and r.globals['lastValue']==80
    r.refs['Home/Range'].control.properties['Max']='=90';r.invalidate()
    assert r.fx.evaluate('Range.Value')==80


def test_gallery_checkbox_values_and_callbacks_are_row_scoped(tmp_path):
    p=Project(tmp_path/'gallery');p.update_source('Src/gallery.pa.yaml',dump_yaml({
        'Screens':{'Home':{'Children':[{'Rows':{'Control':'Gallery@2.15.0',
            'Properties':{'Items':'=Table({ID:1,Enabled:true},{ID:2,Enabled:false})'},
            'Children':[{'Check':{'Control':'ModernCheckbox@1.0.0','Properties':{
                'Checked':'=ThisItem.Enabled','OnCheck':'=Set(changedID,ThisItem.ID)',
                'OnUncheck':'=Set(changedID,ThisItem.ID)'}}}]}}]}}}))
    r=Runtime(p)
    try:
        r.restart();tree=r.render(r.global_refs['Rows'])
        first,second=(row['children'][0] for row in tree['rows'])
        assert first['value'] is True and second['value'] is False
        r.event(second['path'],'OnChange',True)
        assert r.globals['changedID']==2
        r.event(first['path'],'OnChange',False)
        assert r.globals['changedID']==1
        tree=r.render(r.global_refs['Rows'])
        assert [row['children'][0]['value'] for row in tree['rows']]==[False,True]
        assert not r.diagnostics
    finally:r.close()


def test_component_slider_callback_and_reset_are_instance_scoped(tmp_path):
    definition={'AccessAppScope':False,'CustomProperties':{
        'Seed':{'PropertyKind':'Input','DataType':'Number','Default':'=10'},
        'Value':{'PropertyKind':'Output','DataType':'Number','Default':'=Range.Value'},
        'Changed':{'PropertyKind':'Event','ReturnType':'None','Parameters':[{'value':{'DataType':'Number'}}],'Default':'=Blank()'}},
        'Children':[{'Range':{'Control':'ModernSlider@1.0.0','Properties':{
            'Default':'=Panel.Seed','OnChange':'=Panel.Changed(Self.Value)'}}}]}
    p=Project(tmp_path/'components');p.update_source('Src/components.pa.yaml',dump_yaml({
        'ComponentDefinitions':{'Panel':definition},'Screens':{'Home':{'Children':[
            {name:{'Control':'CanvasComponent','ComponentName':'Panel','Properties':{
                'Seed':f'={seed}','Changed':f'=Set({name}Value,value)'}}} for name,seed in [('Left',20),('Right',70)]]}}}))
    r=Runtime(p)
    try:
        r.restart();r.event('Home/Left/Range','OnChange',45)
        assert r.fx.evaluate('Left.Value')==45 and r.fx.evaluate('Right.Value')==70
        assert r.globals['LeftValue']==45 and 'RightValue' not in r.globals
        r.fx.evaluate('Reset(Left)',Context(r,behavior=True))
        assert r.fx.evaluate('Left.Value')==20 and r.fx.evaluate('Right.Value')==70
        assert r.globals['LeftValue']==45 and not r.diagnostics
    finally:r.close()

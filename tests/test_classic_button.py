"""Audited classic button defaults, typed presentation and scoped events."""
from copy import deepcopy
from decimal import Decimal
import pytest
from powerapps_sim.source import Project,dump_yaml
from powerapps_sim.runtime import Runtime
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError
from powerapps_sim.classic_button import catalog,TYPES


def make(tmp_path,version='2.2.0',props=None,profile=None,environment=None,parent_props=None):
    p=Project(tmp_path/'buttons')
    if profile:p.config['form_factor']=profile
    if environment:p.config['environment'].update(environment)
    p.save_config()
    props={'OnSelect':'=Collect(history,{Pressed:Self.Pressed,Mode:Self.DisplayMode});Set(clicks,clicks+1)',**(props or {})}
    children=[{'B':{'Control':'Classic/Button@'+version,'Properties':props}}]
    if parent_props:children=[{'Container':{'Control':'GroupContainer@1.3.0','Properties':parent_props,'Children':children}}]
    children.append({'Healthy':{'Control':'ModernText@1.0.0','Properties':{'Text':'="Healthy"'}}})
    p.update_source('Src/buttons.pa.yaml',dump_yaml({'App':{'Properties':{'OnStart':'=Clear(history);Set(clicks,0);Set(gate,DisplayMode.Edit);Set(shown,true)'}},'Screens':{'Home':{'Children':children}}}))
    r=Runtime(p);r.restart();r.state();return r


@pytest.mark.parametrize('version',['2.0.0','2.0.1','2.2.0'])
@pytest.mark.parametrize('profile,w,h,size',[(None,160,40,13),('phone',280,70,23),('web',85,32,13)])
def test_versioned_template_defaults_and_profile_dimensions(tmp_path,version,profile,w,h,size):
    r=make(tmp_path,version,profile=profile)
    try:
        b=r.refs['Home/B'];assert not r.diagnostics
        assert (b.property('Width'),b.property('Height'),b.property('Size'))==(w,h,size)
        assert b.property('RadiusTopLeft')==10 and b.property('BorderThickness')==2
        assert b.property('PaddingRight')==5 and b.property('FocusedBorderThickness')==4
        assert b.property('HoverFill')==r.fx.evaluate('ColorFade(B.Fill,20%)')
        assert b.property('PressedColor')==b.property('Fill') and b.property('PressedFill')==b.property('Color')
        assert b.property('AutoDisableOnSelect') is True and not b.property('Pressed')
        node=r.render(b);assert node['classic_button']=={'auto_disable':True,'pressed':False,'busy':False}
        assert node['props']['DisabledBorderColor']==b.property('DisabledBorderColor')
    finally:r.close()


@pytest.mark.parametrize('mode,language',[('float','en-CA'),('float','fr-CA'),('decimal','en-CA'),('decimal','fr-CA')])
def test_pressed_output_reactive_styles_and_ordered_release(tmp_path,mode,language):
    r=make(tmp_path,props={'Fill':'=If(Self.Pressed,Color.Red,Color.Blue)'},environment={'number_mode':mode,'language':language,'enum_mode':'strong'})
    try:
        b=r.refs['Home/B'];original=b.property('Fill')
        r.event(b.path,'Pressed',True);assert b.property('Pressed') and b.property('Fill')!=original
        r.event(b.path,'OnSelect');assert r.collections['history']==[{'Pressed':True,'Mode':'Edit'}]
        assert not r.button_busy
        r.event(b.path,'Pressed',False);assert not b.property('Pressed') and b.property('Fill')==original
        for name in ('BorderThickness','FocusedBorderThickness','RadiusTopLeft'):
            assert r.binder.property_type(b.control,name).kind=='Number'
        assert r.binder.property_type(b.control,'AutoDisableOnSelect').kind=='Boolean'
        assert r.binder.property_type(b.control,'HoverColor').kind=='Color'
        assert not r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('name,value',[('AutoDisableOnSelect','=1'),('Italic','="yes"'),('Underline','=1'),('Strikethrough','={Value:true}'),
    ('Align','="Diagonal"'),('VerticalAlign','="Side"'),('BorderStyle','="Double"'),('FontWeight','="Heavy"'),
    ('Size','=-1'),('PaddingLeft','=-2'),('RadiusTopLeft','=-1'),('FocusedBorderThickness','=-1'),('TabIndex','=0.5'),
    ('BorderColor','="red"'),('HoverColor','=1'),('DisabledFill','={Color:"red"}'),('Font','=12')])
def test_invalid_contracts_are_located_and_isolated(tmp_path,name,value):
    r=make(tmp_path,props={name:value})
    try:
        with pytest.raises(FxError):r.refs['Home/B'].property(name)
        assert any(d['member'].endswith('.'+name) for d in r.diagnostics)
        assert r.fx.evaluate('Healthy.Text')=='Healthy' and value in r.project.documents['Src/buttons.pa.yaml']
        if name=='AutoDisableOnSelect':
            r.event('Home/B','OnSelect');assert r.globals['clicks']==0
    finally:r.close()


@pytest.mark.parametrize('name',['Pressed','OnChange','OnInput','Icon','Layout','Appearance','BasePaletteColor','AcceptsFocus','Reset','FutureProperty'])
def test_unsupported_properties_are_preserved_and_never_evaluated(tmp_path,name):
    r=make(tmp_path,props={name:'=Set(unwanted,true)'})
    try:
        assert any(d['kind']=='Unsupported' and d['member'].endswith('.'+name) for d in r.diagnostics)
        assert 'unwanted' not in r.globals
        assert r.fx.evaluate('Healthy.Text')=='Healthy'
    finally:r.close()


@pytest.mark.parametrize('version',['2.0.0','2.0.1'])
def test_content_language_stays_unsupported_on_older_templates(tmp_path,version):
    r=make(tmp_path,version,{'ContentLanguage':'="fr-CA"'})
    try:assert any(d['kind']=='Unsupported' and d['member'].endswith('.ContentLanguage') for d in r.diagnostics)
    finally:r.close()


@pytest.mark.parametrize('props',[{'DisplayMode':'=DisplayMode.Disabled'},{'DisplayMode':'=DisplayMode.View'},{'Visible':'=false'}])
def test_ancestor_gates_and_release_cleanup(tmp_path,props):
    r=make(tmp_path,parent_props={'DisplayMode':'=gate','Visible':'=shown'})
    try:
        path='Home/Container/B'
        r.event(path,'Pressed',True)
        formula='Set(shown,false)' if 'Visible'in props else 'Set(gate,'+props['DisplayMode'][1:]+')'
        r.fx.evaluate(formula,Context(r,behavior=True));r.invalidate()
        r.event(path,'OnSelect');assert r.globals['clicks']==0
        r.event(path,'Pressed',False);assert not r.refs[path].property('Pressed') and not r.button_busy
    finally:r.close()


def test_auto_disabled_callback_guard_and_error_cleanup(tmp_path,monkeypatch):
    r=make(tmp_path,props={'OnSelect':'=Set(clicks,clicks+1);1/0'})
    try:
        original=r.execute;observed=[]
        def execute(raw,ctx,*args):
            if ctx.self_ref is r.refs['Home/B']:
                observed.append(r.render(ctx.self_ref)['classic_button']['busy'])
                r.run_event(ctx.self_ref,'OnSelect')
            return original(raw,ctx,*args)
        monkeypatch.setattr(r,'execute',execute)
        r.event('Home/B','OnSelect')
        assert observed==[True] and r.globals['clicks']==1 and not r.button_busy
        assert any('division'in d['message'].lower() for d in r.diagnostics)
    finally:r.close()


def test_unaudited_version_cannot_execute(tmp_path):
    r=make(tmp_path,'99.0.0')
    try:
        r.run_event(r.refs['Home/B'],'OnSelect');assert r.globals['clicks']==0
        assert r.fx.evaluate('Healthy.Text')=='Healthy' and not r.button_busy
        with pytest.raises(FxError):r.refs['Home/B'].property('Pressed')
    finally:r.close()

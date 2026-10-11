"""Focus effects, eligibility and stable visual keyboard contracts."""
import pytest
from powerapps_sim.source import Project, dump_yaml
from powerapps_sim.runtime import Runtime
from powerapps_sim.fx import Context
from powerapps_sim.binding import BindScope
from powerapps_sim.syntax import FxError


def leaf(kind='ModernTextInput@1.0.0', **props):
    return {'Control':kind,'Properties':props}


def source():
    return {'App':{'Properties':{'OnStart':'=Set(disabled,false);Set(hidden,false);Set(skip,false);Set(offset,300)'}},
     'ComponentDefinitions':{'Panel':{'AccessAppScope':False,'CustomProperties':{'Request':{'PropertyKind':'Event','ReturnType':'None','Default':'=Blank()'}},'Children':[{'Inner':leaf()},{'Ask':leaf('ModernButton@1.0.0',OnSelect='=Panel.Request()')}]}},
     'Screens':{'Home':{'Properties':{'OnVisible':'=SetFocus(First)'},'Children':[
       {'Late':leaf(X='=10',Y='=offset')},{'Second':leaf(X='=200',Y='=10')},
       {'First':leaf(X='=10',Y='=10',DisplayMode='=If(disabled,DisplayMode.Disabled,DisplayMode.Edit)',Visible='=!hidden',AcceptsFocus='=!skip')},
       {'Classic':leaf('Classic/Button@2.2.0',TabIndex='=-1',Y='=100')},
       {'Plain':leaf('Label@2.5.1',Text='="Fictional label"',Y='=130')},
       {'Picture':leaf('Image@2.2.3',Y='=160')},
       {'Go':leaf('ModernButton@1.0.0',OnSelect='=SetFocus(Second)',Y='=190')},
       {'Group':{'Control':'GroupContainer@1.5.0','Properties':{'Y':'=220'},'Children':[{'GroupInput':leaf()}]}},
       {'Gallery':{'Control':'Gallery@2.15.0','Properties':{'Items':'=Table({ID:1})','Y':'=240'},'Children':[{'GalleryInput':leaf()}]}},
       {'Form':{'Control':'Form@2.4.4','Properties':{'Y':'=260'},'Children':[{'Card':{'Control':'TypedDataCard@1.0.7','Children':[{'FormInput':leaf()}]}}]}},
       {'Left':{'Control':'CanvasComponent','ComponentName':'Panel','Properties':{'Y':'=280','Request':'=SetFocus(Second)'}}}
     ]},'Other':{'Properties':{'OnVisible':'=SetFocus(OtherInput)'},'Children':[{'OtherInput':leaf()}]}}}


@pytest.fixture
def r(tmp_path):
    p=Project(tmp_path/'focus');p.update_source('Src/focus.pa.yaml',dump_yaml(source()))
    r=Runtime(p);r.restart();assert not r.diagnostics
    yield r;r.close()


def behavior(r,formula,scope='Go'):
    return r.fx.evaluate(formula,r.global_refs[scope].context(True))


def bound(r,formula,scope='Go',behavior=True):
    r.binder.errors.clear()
    typ=r.binder.bind(r.fx.parse(formula),r.binder.scope_for(r.global_refs[scope].control,'OnSelect' if behavior else 'Text'),('test','',0))
    return typ,[error for _,error in r.binder.errors]


@pytest.mark.parametrize('target',['First','Second','Go','Classic','Plain','Picture'])
def test_supported_targets_and_programmatic_focus_ignores_tab_exclusion(r,target):
    assert behavior(r,f'SetFocus({target})') is None
    assert r.state()['focus_request']['path']==f'Home/{target}'
    assert not bound(r,f'SetFocus({target})')[1]


@pytest.mark.parametrize('target,match',[('GroupInput','GroupContainer'),('FormInput','Form'),('GalleryInput','Gallery'),('Gallery','Gallery'),('Form','Form'),('Group','GroupContainer'),('Left','CanvasComponent')])
def test_restricted_targets_are_visible_and_rejected(r,target,match):
    original=r.focus_request.copy()
    with pytest.raises(FxError,match=match):behavior(r,f'SetFocus({target})')
    assert r.focus_request==original
    assert bound(r,f'SetFocus({target})')[1]


@pytest.mark.parametrize('value',['42','"First"','Blank()','{Title:"First"}'])
def test_values_are_not_control_references(r,value):
    with pytest.raises(FxError,match='requires a control'):behavior(r,f'SetFocus({value})')


def test_behavior_scope_arity_and_error_handling(r):
    assert bound(r,'SetFocus(First)',behavior=False)[1]
    with pytest.raises(FxError,match='Behavior'):r.fx.evaluate('SetFocus(First)')
    for formula in ['SetFocus()','SetFocus(Set(count,1),Second)']:
        with pytest.raises(FxError):behavior(r,formula)
    assert 'count' not in r.globals
    assert behavior(r,'IfError(SetFocus(42),true)') is True


def test_order_unique_request_ids_no_replay_or_events(r):
    first=r.focus_request['id'];r.trace=[]
    behavior(r,'SetFocus(First);SetFocus(Second);Set(result,7)')
    request=r.state()['focus_request'];assert request['id']!=first and request['path']=='Home/Second'
    assert r.state()['focus_request']==request and r.globals['result']==7
    assert [event['path'] for event in r.trace if event['kind']=='focus']==['Home/First','Home/Second']


@pytest.mark.parametrize('flag',['disabled','hidden'])
def test_unavailable_target_is_no_op_and_later_gate_change_suppresses_request(r,flag):
    behavior(r,'SetFocus(Second)');previous=r.focus_request.copy()
    behavior(r,f'Set({flag},true);SetFocus(First)')
    assert r.focus_request==previous
    behavior(r,f'Set({flag},false);SetFocus(First);Set({flag},true)')
    assert r.state()['focus_request'] is None


def test_view_input_remains_programmatically_focusable(r):
    r.global_refs['First'].control.properties['DisplayMode']='=DisplayMode.View';r.invalidate()
    behavior(r,'SetFocus(First)');assert r.state()['focus_request']['path']=='Home/First'


def test_cross_screen_validation_navigation_onvisible_and_inspection(r):
    assert r.focus_request['path']=='Home/First'
    with pytest.raises(FxError,match='another screen'):behavior(r,'SetFocus(OtherInput)')
    assert bound(r,'SetFocus(OtherInput)')[1]
    r.preview_screen='Other';assert r.state()['focus_request'] is None
    r.preview_screen=None;r.navigate('Other')
    assert r.state()['focus_request']['path']=='Other/OtherInput'
    r.screens['Home'].control.properties['OnVisible']='=Blank()';r.navigate('Home')
    assert r.state()['focus_request'] is None
    r.restart();assert r.focus_request is None


def test_host_event_callback_can_focus_host_control(r):
    r.event('Home/Left/Ask','OnSelect')
    assert r.focus_request['path']=='Home/Second' and not r.diagnostics


def test_stable_visual_order_and_paint_order(r):
    tree=r.state()['tree'];names=[n['name'] for n in tree['children']]
    assert names[:2]==['First','Second'] and names[-1]=='Late'
    assert [n['paint_order'] for n in tree['children']][:2]==[2,1]
    behavior(r,'Set(offset,0)');assert [n['name'] for n in r.state()['tree']['children']]==names
    r.restart();assert [n['name'] for n in r.state()['tree']['children']]==names


@pytest.mark.parametrize('family,property,value,expected',[
 ('ModernTextInput@1.0.0','AcceptsFocus','=false',False),('ModernButton@1.0.0','AcceptsFocus','=true',True),
 ('Classic/Button@2.2.0','TabIndex','=-1',False),('Classic/Button@2.2.0','TabIndex','=7',True),
 ('ModernCheckbox@1.0.0','AcceptsFocus','=false',False),('ModernCombobox@1.1.2','AcceptsFocus','=false',False)])
def test_keyboard_properties(r,family,property,value,expected):
    ref=r.global_refs['Go'];ref.control.kind=family;ref.control.properties[property]=value;r.invalidate()
    assert r.render(ref)['tab_stop'] is expected


@pytest.mark.parametrize('property,value',[('AcceptsFocus','="bad"'),('TabIndex','=0.5'),('TabIndex','=true')])
def test_invalid_keyboard_contract_isolated(r,property,value):
    ref=r.global_refs['Go'];ref.control.properties[property]=value;r.invalidate()
    assert r.render(ref)['tab_stop'] is False
    assert any(property in d['message'] for d in r.diagnostics)
    assert r.render(r.global_refs['Second'])['tab_stop'] is True


def test_component_cannot_focus_internal_control(r):
    ctx=r.refs['Home/Left/Ask'].context(True)
    with pytest.raises(FxError,match='Component'):
        r.fx.evaluate('SetFocus(Inner)',ctx)
    control=r.refs['Home/Left/Ask'].control
    r.binder.errors.clear();r.binder.bind(r.fx.parse('SetFocus(Inner)'),r.binder.scope_for(control,'OnSelect'),('test','',0))
    assert any('Component' in error.message for _,error in r.binder.errors)


def test_packaged_focus_fixture_workflow_and_source_round_trip(tmp_path):
    from powerapps_sim.fixtures import focus_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    p=focus_project(tmp_path/'fixture');source_text=(p.root/'Src/focus.pa.yaml').read_text()
    w=Workspace(tmp_path,p.root,start=False)
    scenario=w.workflows.catalog()['scenarios'][0]['scenario'];assert len(scenario['steps'])==33
    result=w.workflows.run(scenario,expected_revision=revision(p.root))
    assert result['status']=='passed',result['steps']
    focus=[event for event in result['trace'] if event['kind']=='focus']
    assert len(focus)==9 and focus[-1]['path']=='FocusScreen/FirstName'
    assert w.runtime.globals=={} and w.runtime.focus_request is None
    assert (p.root/'Src/focus.pa.yaml').read_text()==source_text
    assert 'focus_request' not in p.export_control('FirstName')
    w.runtime.close()


def test_auto_layout_keeps_flex_order_when_hidden_children_return(r):
    ref=r.global_refs['Group'];ref.control.raw['Variant']='AutoLayout'
    ref.control.children.append(type(ref.control.children[0])('Last','ModernTextInput@1.0.0',{'Properties':{'Visible':'=hidden'}},ref.control.source,ref.control))
    child=r.build(ref.control.children[-1],ref.path+'/Last',ref);ref.children.append(child)
    assert [node['name'] for node in r.render(ref)['children']]==['GroupInput','Last']
    behavior(r,'Set(hidden,true)')
    assert [node['name'] for node in r.render(ref)['children']]==['GroupInput','Last']

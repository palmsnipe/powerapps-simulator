"""Nested component behavior keeps callee state and caller callbacks separate."""
from pathlib import Path
import pytest
from powerapps_sim.fixtures import nested_project
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project,load_yaml,dump_yaml
from powerapps_sim.syntax import FxError

@pytest.fixture
def nested(tmp_path):
    r=Runtime(nested_project(tmp_path/'nested'));r.restart();r.state()
    yield r
    r.close()

def totals(r,name='LeftShell'):
    return [r.fx.evaluate(f'{name}.{prop}') for prop in ('FirstTotal','SecondTotal','LastChild')]

def variant(tmp_path,change):
    source=load_yaml((Path(__file__).parents[1]/'powerapps_sim/examples/nested.pa.yaml').read_text())
    change(source)
    p=Project(tmp_path/'variant');p.update_source('Src/variant.pa.yaml',dump_yaml(source))
    r=Runtime(p);r.restart();r.state();return r

def test_nested_actions_isolate_callee_state_and_host_callback(nested):
    r=nested;assert totals(r)==[10,110,0] and totals(r,'RightShell')==[1000,1100,0]
    r.event('Nested/AddLeft','OnSelect')
    assert totals(r)==[11,112,112] and totals(r,'RightShell')==[1000,1100,0]
    assert r.globals['leftResult']==112 and r.globals['rightResult']==0
    assert r.component_state['Nested/LeftShell/InnerA']['collections']['history']==[{'Total':11}]
    assert r.component_state['Nested/LeftShell/InnerB']['collections']['history']==[{'Total':112}]
    assert r.component_state['Nested/LeftShell']['collections']['history']==[{'Total':11},{'Total':112}]
    assert 'current' not in r.globals and 'history' not in r.collections
    assert [x['Total'] for x in r.collections['trace']]==[0,11,112] and not r.diagnostics

def test_nested_button_optional_arguments_and_independent_outer_instances(nested):
    r=nested;r.event('Nested/LeftShell/InnerB/LeafIncrease','OnSelect')
    assert totals(r)==[10,111,111]
    r.event('Nested/AddRight','OnSelect')
    assert totals(r)==[10,111,111] and totals(r,'RightShell')==[1005,1106,1106]
    assert r.globals['rightResult']==1106 and not r.diagnostics

def test_reset_explicit_nested_actions_and_reactive_inputs(nested):
    r=nested;r.event('Nested/LeftShell/InnerA/LeafNote','OnChange','edited')
    r.event('Nested/AddLeft','OnSelect');r.event('Nested/ResetLeft','OnSelect')
    assert totals(r)==[10,110,0]
    for name in ('InnerA','InnerB'):
        assert r.refs[f'Nested/LeftShell/{name}'].property('ResetCount')==1
        assert r.refs[f'Nested/LeftShell/{name}'].property('Rows')==[]
    assert r.refs['Nested/LeftShell/InnerA/LeafNote'].property('Text')=='note Left first'
    r.event('Nested/ChangeSeed','OnSelect');assert totals(r)==[20,120,0]
    assert r.refs['Nested/LeftShell/InnerA'].property('ResetCount')==2
    assert r.refs['Nested/RightShell/InnerA'].property('ResetCount')==0
    r.state();r.state();assert r.refs['Nested/LeftShell/InnerA'].property('ResetCount')==2
    r.restart();r.state();assert totals(r)==[10,110,0] and not r.diagnostics

def test_nested_functions_pure_and_behavior_type_checks(nested):
    r=nested;inner=r.refs['Nested/LeftShell/InnerA']
    assert inner.property('Double')([3])==6
    with pytest.raises(FxError,match='Cannot parse number'):inner.property('Add')(['bad'])
    with pytest.raises(FxError,match='Behavior'):r.fx.evaluate('InnerA.Add()',r.refs['Nested/LeftShell'].context())
    with pytest.raises(FxError,match='arguments'):inner.property('Add')([1,2])
    assert totals(r)==[10,110,0]
    assert r.fx.evaluate('InnerA.Double(4)',r.refs['Nested/LeftShell'].context())==8
    assert not r.diagnostics

def test_callback_consuming_screen_context_and_parameter_shadowing(tmp_path):
    def change(s):
        s['Screens']['Nested']['Children'][5]['LeftShell']['Properties']['Changed']='=UpdateContext({screenTotal:total})'
        s['ComponentDefinitions']['Shell']['Children'][1]['InnerA']['Properties']['Changed']='=With({total:total+2},Set(current,total));Shell.Changed(total)'
    r=variant(tmp_path,change)
    try:
        r.event('Nested/LeftShell/InnerA/LeafIncrease','OnSelect')
        assert totals(r)==[11,110,13]
        assert r.screen_context['Nested']['screenTotal']==11
        assert 'screenTotal' not in r.globals and not r.diagnostics
    finally:r.close()

@pytest.mark.parametrize('inner_access,outer_access',[(True,False),(False,True),(True,True)])
def test_nested_access_app_scope_is_owned_by_each_definition(tmp_path,inner_access,outer_access):
    def change(s):
        s['ComponentDefinitions']['Leaf']['AccessAppScope']=inner_access
        s['ComponentDefinitions']['Shell']['AccessAppScope']=outer_access
    r=variant(tmp_path,change)
    try:
        r.event('Nested/LeftShell/InnerA/LeafIncrease','OnSelect')
        leaf=r.component_state.get('Nested/LeftShell/InnerA',{}).get('variables',{})
        shell=r.component_state.get('Nested/LeftShell',{}).get('variables',{})
        if inner_access:assert r.globals['current']==11 and 'current' not in leaf
        else:assert leaf['current']==11
        if outer_access:assert r.globals['current']==11 and 'current' not in shell
        else:assert shell['current']==11
        assert not r.diagnostics
    finally:r.close()

def test_standard_host_properties_bind_in_containing_component_scope(tmp_path):
    def change(s):
        s['ComponentDefinitions']['Shell']['Properties']['OnReset']+=';Set(panelWidth,250)'
        s['ComponentDefinitions']['Shell']['Children'][1]['InnerA']['Properties']['Width']='=Coalesce(panelWidth,280)'
    r=variant(tmp_path,change)
    try:
        assert not r.diagnostics
        r.event('Nested/ResetLeft','OnSelect')
        assert r.refs['Nested/LeftShell/InnerA'].property('Width')==250
        assert r.refs['Nested/RightShell/InnerA'].property('Width')==280
    finally:r.close()

def test_same_control_names_bind_to_their_own_definition(tmp_path):
    def change(s):
        leaf=s['ComponentDefinitions']['Leaf'];shell=s['ComponentDefinitions']['Shell']
        leaf['Children'][0]={'Shared':{'Control':'ModernText@1.0.0','Properties':{'Text':'=Text(Self.Width)','Width':'=Leaf.Total'}}}
        shell['Children'][0]={'Shared':{'Control':'ModernText@1.0.0','Properties':{'Text':'="shell"'}}}
        leaf['CustomProperties']['CaptionValue']={'PropertyKind':'Output','DataType':'Text','Default':'=Shared.Text'}
        shell['CustomProperties']['CaptionValue']={'PropertyKind':'Output','DataType':'Text','Default':'=Shared.Text'}
    r=variant(tmp_path,change)
    try:
        assert not r.diagnostics
        assert r.fx.evaluate('LeftShell.CaptionValue')=='shell'
        assert r.refs['Nested/LeftShell/InnerA'].property('CaptionValue')=='10'
        r.event('Nested/AddLeft','OnSelect')
        assert r.refs['Nested/LeftShell/InnerA'].property('CaptionValue')=='11'
        assert r.refs['Nested/RightShell/InnerA'].property('CaptionValue')=='1000'
    finally:r.close()

@pytest.mark.parametrize('indirect',[False,True])
def test_component_definition_cycle_isolated_without_recursive_build(tmp_path,indirect):
    def change(s):
        target='Shell' if indirect else 'Leaf'
        s['ComponentDefinitions']['Leaf']['Children'].append({'Recursive':{'Control':'CanvasComponent','ComponentName':target}})
    r=variant(tmp_path,change)
    try:
        assert any(d['kind']=='Cycle' and 'definition cycle' in d['message'] for d in r.diagnostics)
        assert len(r.refs)<60
        invalid=next(ref for ref in r.refs.values() if ref.component_error)
        with pytest.raises(FxError,match='definition cycle'):invalid.property('Width')
        with pytest.raises(FxError,match='definition cycle'):r.reset_ref(invalid)
        assert r.global_refs['Title'].property('Text')=='Nested actions and callbacks'
        r.state();r.restart();r.state()
        assert any(d['kind']=='Cycle' for d in r.diagnostics)
    finally:r.close()

def test_missing_component_preserves_healthy_preview(tmp_path):
    r=variant(tmp_path,lambda s:s['ComponentDefinitions'].pop('Leaf'))
    try:
        assert any('Missing component definition Leaf' in d['message'] for d in r.diagnostics)
        assert r.global_refs['Title'].property('Text')=='Nested actions and callbacks'
    finally:r.close()

@pytest.mark.parametrize('family',['Gallery@2.15.0','Form@2.4.4'])
def test_invalid_component_placement_is_visible(tmp_path,family):
    def change(s):s['Screens']['Nested']['Children'].append({'InvalidHost':{'Control':family,'Children':[{'InvalidChild':{'Control':'CanvasComponent','ComponentName':'Leaf'}}]}})
    r=variant(tmp_path,change)
    try:assert any('does not support canvas components inside' in d['message'] for d in r.diagnostics)
    finally:r.close()

def test_modern_data_property_output_is_not_host_overridden(tmp_path):
    def change(s):
        c=s['ComponentDefinitions']['Shell']['CustomProperties']['FirstTotal'];c.update(PropertyKind='Data',PropertyDefinition='Output')
        s['Screens']['Nested']['Children'][5]['LeftShell']['Properties']['FirstTotal']='=999'
    r=variant(tmp_path,change)
    try:
        assert totals(r)[0]==10
        assert any('cannot be overridden' in d['message'] for d in r.diagnostics)
    finally:r.close()


def test_unknown_property_kind_keeps_healthy_component_controls(tmp_path):
    def change(s):
        s['ComponentDefinitions']['Leaf']['CustomProperties']['Future']={'PropertyKind':'FutureKind','DataType':'Text','Default':'="future"'}
    r=variant(tmp_path,change)
    try:
        assert any('Unsupported component property kind FutureKind' in d['message'] for d in r.diagnostics)
        assert r.refs['Nested/LeftShell/InnerA/LeafCaption'].property('Text')=='Left first · 10 · resets 0'
    finally:r.close()


def test_stored_nested_workflow_isolated_from_live_state(nested):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    r=nested
    workspace=Workspace(r.project.root.parent,r.project.root,start=False)
    try:
        catalog=workspace.workflows.catalog()['scenarios']
        assert len(catalog)==1
        before=workspace.runtime.state()
        report=workspace.workflows.run(catalog[0]['scenario'],expected_revision=revision(r.project.root))
        assert report['status']=='passed' and not report['diagnostics']
        assert workspace.runtime.state()==before
    finally:workspace.runtime.close()

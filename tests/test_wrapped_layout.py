"""Wrapped geometry uses line-local limits and remains visible to components."""
import pytest
from powerapps_sim.source import Project, dump_yaml
from powerapps_sim.runtime import Runtime
from powerapps_sim.fixtures import lifecycle_project


def leaf(name, width=100, height=40, **props):
    return {name: {'Control':'ModernText@1.0.0','Properties':{'Width':f'={width}','Height':f'={height}',
        'LayoutMinWidth':'=0','LayoutMinHeight':'=0', **props}}}


def make(tmp_path, children, horizontal=True, **props):
    p = Project(tmp_path/'wrapped')
    p.update_source('Src/wrapped.pa.yaml', dump_yaml({'Screens':{'Home':{'Children':[
        {'Box':{'Control':'GroupContainer@1.5.0','Variant':'AutoLayout','Properties':{
            'Width':'=220','Height':'=160','LayoutWrap':'=true','LayoutDirection':'=LayoutDirection.'+('Horizontal' if horizontal else 'Vertical'),
            'LayoutAlignItems':'=LayoutAlignItems.Start','LayoutGap':'=10', **props}, 'Children':children}}]}}}))
    r = Runtime(p); r.restart()
    return r


def test_rows_padding_border_and_alignment(tmp_path):
    r=make(tmp_path,[leaf('A'),leaf('B',height=60),leaf('C',height=30)],Width='=234',PaddingLeft='=10',PaddingRight='=10',BorderThickness='=2',LayoutAlignItems='=LayoutAlignItems.End')
    try:
        assert r.fx.evaluate('A.X') == 12
        assert r.fx.evaluate('B.X') == 122
        # Interior height156, natural60+30+gap10, line stretch28 each.
        assert r.fx.evaluate('A.Y') == 50
        assert r.fx.evaluate('B.Y') == 30
        assert r.fx.evaluate('C.Y') == 128
        assert r.fx.evaluate('C.Width') == 100
        assert not r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('horizontal',[True,False])
def test_flexible_portions_are_allocated_per_line(tmp_path,horizontal):
    axis='Width' if horizontal else 'Height'; cross='Height' if horizontal else 'Width'
    children=[leaf('A',100,100,FillPortions='=1',**{'LayoutMin'+axis:'=90'}),leaf('B',100,100,FillPortions='=2',**{'LayoutMin'+axis:'=90'}),leaf('C',100,100,FillPortions='=1',**{'LayoutMin'+axis:'=90'})]
    r=make(tmp_path,children,horizontal,**{axis:'=220',cross:'=160','LayoutAlignItems':'=LayoutAlignItems.Stretch'})
    try:
        assert r.fx.evaluate('A.'+axis)==90
        assert r.fx.evaluate('B.'+axis)==120
        assert r.fx.evaluate('C.'+axis)==220
        # Natural100 minimum on both lines causes cross overflow.
        assert r.fx.evaluate('C.'+('Y' if horizontal else 'X'))==110
        assert not r.diagnostics
    finally:r.close()


def test_visibility_resize_and_maximum_are_reactive(tmp_path):
    r=make(tmp_path,[leaf('A',FillPortions='=1',LayoutMinWidth='=100',LayoutMaxWidth='=110'),leaf('B',FillPortions='=1',LayoutMinWidth='=100'),leaf('C',FillPortions='=1',LayoutMinWidth='=100')],Width='=App.Width',Height='=200',LayoutAlignItems='=LayoutAlignItems.Stretch')
    try:
        r.viewport['width']=220;r.invalidate()
        assert r.fx.evaluate('A.Width')==105
        assert r.fx.evaluate('C.Y')==105
        r.viewport['width']=400;r.invalidate()
        assert r.fx.evaluate('A.Width')==110
        assert r.fx.evaluate('B.Width')==135
        assert r.fx.evaluate('C.Y')==0
        r.global_refs['B'].control.properties['Visible']='=false';r.invalidate()
        assert r.fx.evaluate('C.X')==120
        assert r.fx.evaluate('C.Width')==280
        assert not r.diagnostics
    finally:r.close()


def test_oversized_item_overflows_and_exact_fit_does_not_wrap(tmp_path):
    r=make(tmp_path,[leaf('A',220),leaf('B',400),leaf('C',220)],Height='=100')
    try:
        assert r.fx.evaluate('A.Y')==0
        assert r.fx.evaluate('B.Y')==50
        assert r.fx.evaluate('C.Y')==100
        assert r.fx.evaluate('B.Width')==400
        assert not r.diagnostics
    finally:r.close()


def test_line_local_justification_and_cross_center(tmp_path):
    r=make(tmp_path,[leaf('A',80,20),leaf('B',80,40),leaf('C',80,30)],LayoutJustifyContent='=LayoutJustifyContent.SpaceBetween',LayoutAlignItems='=LayoutAlignItems.Center')
    try:
        assert r.fx.evaluate('B.X')==140
        assert r.fx.evaluate('C.X')==0
        assert r.fx.evaluate('A.Y')==30
        assert r.fx.evaluate('C.Y')==110
        assert not r.diagnostics
    finally:r.close()


def test_autoheight_measures_allocated_width_without_cycle(tmp_path):
    r=make(tmp_path,[leaf('A',100,40,FillPortions='=1',LayoutMinWidth='=100',AutoHeight='=true',Text='="Long text " & "Long text " & "Long text "'),leaf('B',100,40,FillPortions='=1',LayoutMinWidth='=100'),leaf('C',100,40,FillPortions='=1',LayoutMinWidth='=100')])
    try:
        assert r.fx.evaluate('A.Width')==105
        assert r.fx.evaluate('A.Height')>40
        assert r.fx.evaluate('C.Y')>r.fx.evaluate('A.Height')
        r.state(); assert not r.diagnostics
    finally:r.close()


def test_wrapped_component_instances_keep_events_and_parent_sizes(tmp_path):
    r=Runtime(lifecycle_project(tmp_path/'lifecycle'));r.restart()
    try:
        r.global_refs['Panels'].control.properties['LayoutWrap']='=true'
        r.viewport['width']=400;r.invalidate()
        assert r.fx.evaluate('LeftPanel.Width')==264
        assert r.fx.evaluate('RightPanel.Width')==336
        assert r.fx.evaluate('RightPanel.Y')>r.fx.evaluate('LeftPanel.Y')
        r.event('Lifecycle/Panels/LeftPanel/Increase','OnSelect')
        assert r.fx.evaluate('LeftPanel.Total')==11
        assert r.fx.evaluate('RightPanel.Total')==100
        r.event('Lifecycle/ChangeSeed','OnSelect')
        assert r.fx.evaluate('LeftPanel.ResetCount')==1
        assert r.fx.evaluate('RightPanel.ResetCount')==0
        assert not r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('horizontal',[True,False])
def test_wrap_ignores_child_alignment_override(tmp_path,horizontal):
    r=make(tmp_path,[leaf('A',40,40,AlignInContainer='=AlignInContainer.End')],horizontal,LayoutAlignItems='=LayoutAlignItems.Start')
    try:
        assert r.fx.evaluate('A.Width')==40
        assert r.fx.evaluate('A.Height')==40
        assert r.fx.evaluate('A.X')==0
        assert r.fx.evaluate('A.Y')==0
        assert not r.diagnostics
    finally:r.close()

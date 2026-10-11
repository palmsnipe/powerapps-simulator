"""Authored card minima/order remain separate from rendered form geometry."""
from pathlib import Path
from copy import deepcopy
import pytest
from powerapps_sim.source import Project,dump_yaml
from powerapps_sim.runtime import Runtime
from powerapps_sim.form_layout import bounds
from powerapps_sim.syntax import FxError


def card(name,width=100,height=50,x=0,y=0,fit=False,children=None,**props):
    return {name:{'Control':'TypedDataCard@1.0.7','Properties':{'Width':f'={width}','Height':f'={height}','X':f'={x}','Y':f'={y}','WidthFit':'=true' if fit else '=false',**props},'Children':children or []}}

def make(tmp_path,children,width=400,columns=2):
    p=Project(tmp_path/'form');p.update_source('Src/form.pa.yaml',dump_yaml({'Screens':{'Home':{'Children':[{'Editor':{'Control':'Form@2.4.4','Properties':{'Width':f'={width}','Height':'=150','NumberOfColumns':f'={columns}'},'Children':children}}]}}}))
    r=Runtime(p);r.restart();return r


def geo(r,name):return bounds(r.global_refs['Editor'])['cards']['Home/Editor/'+name]


def test_authored_order_rows_and_equal_visual_height(tmp_path):
    r=make(tmp_path,[card('B',100,80,1),card('C',100,90,0,1),card('A',200,50,0)])
    try:
        assert geo(r,'A')=={'X':0,'Y':0,'Width':200,'Height':80}
        assert geo(r,'B')=={'X':200,'Y':0,'Width':100,'Height':80}
        assert geo(r,'C')['Y']==80
        assert r.fx.evaluate('B.X')==1 and r.fx.evaluate('C.Y')==1
        assert r.fx.evaluate('A.Height')==50
        assert [n['name'] for n in r.render(r.global_refs['Editor'])['children']]==['A','B','C']
    finally:r.close()


def test_widthfit_shares_extra_without_shrinking_or_rewriting(tmp_path):
    r=make(tmp_path,[card('A',100,fit=True),card('B',200,x=1,fit=True),card('C',500,y=1,fit=True)])
    try:
        assert geo(r,'A')['Width']==150 and geo(r,'B')['Width']==250
        assert geo(r,'C')['Width']==500
        assert r.fx.evaluate('A.Width')==100
        assert bounds(r.global_refs['Editor'])['content_width']==500
    finally:r.close()


def test_overflow_wraps_within_logical_row_never_merges_rows(tmp_path):
    r=make(tmp_path,[card('A',250,60),card('B',200,80,1),card('C',100,30,0,1)])
    try:
        assert geo(r,'B')['Y']==60 and geo(r,'C')['Y']==140
        assert bounds(r.global_refs['Editor'])['content_height']==170
    finally:r.close()


def test_resize_visibility_and_variable_width_are_reactive(tmp_path):
    r=make(tmp_path,[card('A',100,fit=True),card('B',200,x=1,Visible='=show',Width='=size')])
    try:
        r.globals.update(show=True,size=200);r.invalidate();assert geo(r,'A')['Width']==200
        r.globals['show']=False;r.invalidate();assert geo(r,'A')['Width']==400
        r.globals.update(show=True,size=350);r.invalidate();assert geo(r,'B')['Y']==50
        r.global_refs['Editor'].control.properties['Width']='=600';r.invalidate();assert geo(r,'B')['Y']==0 and geo(r,'A')['Width']==250
    finally:r.close()


def test_default_card_width_uses_column_count_but_standalone_card_is_valid(tmp_path):
    c=card('A');del c['A']['Properties']['Width'];r=make(tmp_path,[c],columns=4)
    try:assert r.fx.evaluate('A.Width')==100
    finally:r.close()


@pytest.mark.parametrize('name,value',[('Width','=-1'),('Height','=-2'),('X','=true'),('Y','="bad"'),('WidthFit','=1')])
def test_invalid_card_geometry_is_visible_and_peer_survives(tmp_path,name,value):
    r=make(tmp_path,[card('A',**{name:value}),card('B',x=1)])
    try:
        with pytest.raises(FxError):r.global_refs['A'].property(name)
        node=r.render(r.global_refs['Editor']);assert node['children'][0]['errors']
        assert geo(r,'B')['Width']==100
    finally:r.close()


@pytest.mark.parametrize('columns',[0,-1,1.5,True,'"two"'])
def test_invalid_column_counts_report_errors(tmp_path,columns):
    r=make(tmp_path,[card('A')],columns=columns)
    try:assert r.render(r.global_refs['Editor'])['errors']
    finally:r.close()


def test_autoheight_content_grows_entire_row_and_empty_label_collapses(tmp_path):
    # A collapsing error label deliberately has no vertical padding. Native
    # Label templates otherwise contribute five pixels on each side.
    child={'ErrorLabel':{'Control':'Label@2.5.1','Properties':{'AutoHeight':'=true','Text':'=message','Width':'=100','Height':'=20','Y':'=40','PaddingTop':'=0','PaddingBottom':'=0'}}}
    r=make(tmp_path,[card('A',height=50,children=[child]),card('B',height=60,x=1),card('C',y=1)])
    try:
        r.globals['message']='';r.invalidate();assert r.fx.evaluate('ErrorLabel.Height')==0 and geo(r,'C')['Y']==60
        r.globals['message']='Fictional validation message '*5;r.invalidate()
        assert geo(r,'A')['Height']>60 and geo(r,'B')['Height']==geo(r,'A')['Height']
        assert geo(r,'C')['Y']==geo(r,'A')['Height']
    finally:r.close()


def test_layout_reads_keep_source_and_owner_state_pure(tmp_path):
    r=make(tmp_path,[card('A',fit=True),card('B',y=1)])
    try:
        r.state();source=(r.project.root/'Src/form.pa.yaml').read_bytes();state=deepcopy(r.control_state)
        r.state();r.render(r.global_refs['Editor']);bounds(r.global_refs['Editor'])
        assert r.control_state==state and (r.project.root/'Src/form.pa.yaml').read_bytes()==source
        assert b'form_bounds' not in source
    finally:r.close()


@pytest.mark.parametrize('language,number',[('en-US','float'),('en-US','decimal'),('fr-CA','float'),('fr-CA','decimal')])
def test_form_layout_workflow_preserves_owner_and_uses_same_geometry(tmp_path,language,number):
    from powerapps_sim.fixtures import form_layout_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    from powerapps_sim.workflows import data_revision
    p=form_layout_project(tmp_path/'owner');w=Workspace(tmp_path,p.root)
    try:
        assert w.runtime.store.rows('Drafts')[0]['Title']=='Fictional river draft'
        before=deepcopy(w.ai.read_runtime());source=revision(p.root);data=data_revision(w.runtime.store)
        entry=w.workflows.catalog()['scenarios'][0]
        report=w.workflows.run({**entry['scenario'],'environment':{'language':language,'number_mode':number}},expected_revision=source)
        assert report['status']=='passed' and len(report['steps'])==39 and not report['diagnostics']
        assert w.ai.read_runtime()==before and revision(p.root)==source and data_revision(w.runtime.store)==data
        form=w.runtime.global_refs['DraftForm'];b=bounds(form)['cards'];prefix='CardLayout/DraftForm/'
        assert b[prefix+'TitleCard']['Width']==280 and b[prefix+'AmountCard']['Width']==380
        w.runtime.event('CardLayout/LeftGrow/Switch','OnChange',True)
        w.runtime.event('CardLayout/RightShow/Switch','OnChange',False)
        b=bounds(form)['cards'];assert b[prefix+'TitleCard']['Width']==450 and b[prefix+'AmountCard']['Width']==450
        w.runtime.event('CardLayout/Narrow','OnSelect')
        b=bounds(form)['cards'];assert b[prefix+'TitleCard']['Width']==540 and b[prefix+'AmountCard']['Y']==95
        assert bounds(form)['content_height']==300
    finally:w.runtime.close()


def test_control_inspector_exposes_bounds_separately_from_export(tmp_path):
    from powerapps_sim.web import create_app
    from powerapps_sim.fixtures import form_layout_project
    p=form_layout_project(tmp_path/'project');app=create_app(tmp_path/'workspace',p.root);w=app.extensions['workspace']
    try:
        result=app.test_client().get('/api/control?path=CardLayout/DraftForm/AmountCard').json
        assert result['values']['Width']==280 and result['rendered_bounds']['Width']==380
        assert 'form_bounds' not in result['export'] and 'WidthFit: =true' in result['export']
    finally:w.runtime.close()


def test_nested_group_autoheight_and_healthy_gallery_do_not_measure_template_scope(tmp_path):
    group={'Group':{'Control':'GroupContainer@1.5.0','Variant':'ManualLayout','Properties':{'Y':'=30'},'Children':[{'Text':{'Control':'ModernText@1.0.0','Properties':{'AutoHeight':'=true','Text':'="Fictional long content " & "Fictional long content"','Width':'=50','Y':'=20'}}}]}}
    gallery={'Rows':{'Control':'Gallery@2.15.0','Properties':{'Items':'=Table({Caption:"Fictional"})'},'Children':[{'RowText':{'Control':'Label@2.5.1','Properties':{'AutoHeight':'=true','Text':'=ThisItem.Caption','Width':'=100'}}}]}}
    r=make(tmp_path,[card('A',children=[group,gallery]),card('B',x=1)])
    try:
        r.state();assert geo(r,'A')['Height']>50 and geo(r,'B')['Height']==geo(r,'A')['Height']
        assert not r.diagnostics
    finally:r.close()

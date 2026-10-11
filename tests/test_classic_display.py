"""Audited display contracts, hidden measurement, geometry and scoped behavior."""
import math
import pytest
from powerapps_sim.source import Project,dump_yaml
from powerapps_sim.runtime import Runtime
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError
from powerapps_sim.classic_display import VERSIONS,catalog

def make(tmp_path,family='Label',version=None,props=None,profile=None,variant=None,parent=None):
    p=Project(tmp_path/'display')
    if profile:p.config['form_factor']=profile;p.save_config()
    control={'Control':family+'@'+(version or max(VERSIONS[family],key=lambda v:tuple(map(int,v.split('.'))))),
             'Properties':{'OnSelect':'=Collect(history,{Name:Self.Name});Set(clicks,clicks+1)',**(props or {})}}
    if variant:control['Variant']=variant
    children=[{'D':control}]
    if parent:children=[{'Container':{'Control':'GroupContainer@1.3.0','Properties':parent,'Children':children}}]
    children.append({'Healthy':{'Control':'ModernText@1.0.0','Properties':{'Text':'="Healthy"'}}})
    p.update_source('Src/display.pa.yaml',dump_yaml({'App':{'Properties':{'OnStart':'=Clear(history);Set(clicks,0);Set(shown,true);Set(caption,"short");Set(wide,200)'}},'Screens':{'Home':{'Children':children}}}))
    r=Runtime(p);r.restart();r.state();return r

def ref(r):return next(v for v in r.refs.values() if v.name=='D')
def behavior(r,formula):r.fx.evaluate(formula,Context(r,behavior=True));r.invalidate()

@pytest.mark.parametrize('family,version',[(f,v) for f,vs in VERSIONS.items() for v in sorted(vs)])
def test_every_audited_version_defaults_and_geometry(tmp_path,family,version):
    r=make(tmp_path,family,version)
    try:
        d=ref(r);node=r.render(d);assert not r.diagnostics,r.diagnostics
        assert d.property('TabIndex')==-1 and not node['tab_stop']
        assert isinstance(d.property('HoverFill'),str)
        if family=='Label':
            assert d.property('LineHeight')==1.2 and d.property('PaddingLeft')==5
            assert d.property('Live')=='Off' and d.property('Overflow')=='Hidden'
            assert (d.property('Width'),d.property('Height'))==(150,40)
            assert node['classic_display']=={'heading':None,'live':'off','scroll':False}
        else:
            assert (d.property('Width'),d.property('Height'))==((150,100) if family=='Rectangle' else (100,100))
            assert node['classic_display']['geometry']['tag']=={'Rectangle':'rect','Circle':'ellipse','Star':'polygon'}[family]
    finally:r.close()

@pytest.mark.parametrize('version',sorted(VERSIONS['Label']))
@pytest.mark.parametrize('profile,w,h,size',[('phone',560,70,24),('web',260,40,14)])
def test_label_profile_defaults(tmp_path,version,profile,w,h,size):
    r=make(tmp_path,version=version,profile=profile)
    try:assert tuple(ref(r).property(n) for n in ('Width','Height','Size'))==(w,h,size)
    finally:r.close()

@pytest.mark.parametrize('name,value',[('LineHeight','=-1'),('PaddingTop','="five"'),('Size','=true'),('Width','="wide"'),('Height','={Value:3}'),
    ('Live','="Urgent"'),('Role','="Heading5"'),('Overflow','="Visible"'),('Wrap','=1'),('AutoHeight','="true"'),
    ('BorderStyle','="Double"'),('TabIndex','=0.5'),('Color','="red"'),('Fill','=1'),('Font','=12'),('IsErrorMessage','=true')])
def test_invalid_label_properties_are_located_and_isolated(tmp_path,name,value):
    r=make(tmp_path,props={name:value})
    try:
        with pytest.raises(FxError):ref(r).property(name)
        assert any(d['member'].endswith('.'+name) for d in r.diagnostics)
        assert r.fx.evaluate('Healthy.Text')=='Healthy'
        assert value in r.project.documents['Src/display.pa.yaml']
        r.state()  # Invalid geometry/semantic fields must never crash the screen.
    finally:r.close()

@pytest.mark.parametrize('family,name',[('Label','AccessibleLabel'),('Label','FutureProperty'),('Circle','Color'),('Star','Rotation'),('Rectangle','Pressed'),('Circle','Text')])
def test_no_invented_properties_or_behavior(tmp_path,family,name):
    r=make(tmp_path,family,props={name:'=Set(unwanted,true)'})
    try:
        assert any(d['kind']=='Unsupported' and d['member'].endswith('.'+name) for d in r.diagnostics)
        assert 'unwanted' not in r.globals
        assert r.fx.evaluate('Healthy.Text')=='Healthy'
    finally:r.close()

@pytest.mark.parametrize('family,name',[('Label','AccessibleLabel'),('Circle','Color'),('Star','Rotation'),('Rectangle','Pressed')])
def test_unsupported_property_reads_do_not_inherit_unrelated_common_defaults(tmp_path,family,name):
    r=make(tmp_path,family)
    try:
        with pytest.raises(FxError) as caught:r.fx.evaluate('D.'+name)
        assert caught.value.kind=='Unsupported'
        assert r.fx.evaluate('Healthy.Text')=='Healthy'
    finally:r.close()

@pytest.mark.parametrize('family',sorted(VERSIONS))
def test_unknown_versions_preserved_and_direct_selection_blocked(tmp_path,family):
    r=make(tmp_path,family,'99.0.0')
    try:
        r.run_event(ref(r),'OnSelect');assert r.globals['clicks']==0
        assert any(d['kind']=='Unsupported' for d in r.diagnostics)
        assert r.fx.evaluate('Healthy.Text')=='Healthy'
    finally:r.close()

@pytest.mark.parametrize('parent',[None,{'Visible':'=shown'}])
def test_auto_height_retains_hidden_measurement_and_recomputes_on_show(tmp_path,parent):
    r=make(tmp_path,props={'AutoHeight':'=true','Text':'=caption','Width':'=wide','Size':'=20','LineHeight':'=1.5',
        'Height':'=91','Visible':'=shown' if not parent else '=true'},parent=parent)
    try:
        d=ref(r);initial=d.property('Height');assert initial==40
        behavior(r,'Set(shown,false);Set(caption,"A much longer caption which wraps across several lines");Set(wide,80)')
        assert d.property('Height')==initial
        behavior(r,'Set(shown,true)');assert d.property('Height')>initial
        r.restart();assert ref(r).property('Height')==initial
    finally:r.close()

def test_initially_hidden_label_uses_authored_height_and_does_not_observe_text(tmp_path):
    r=make(tmp_path,props={'AutoHeight':'=true','Visible':'=false','Text':'=1/0','Height':'=91'})
    try:
        assert ref(r).property('Height')==91
        assert ref(r).path not in r.label_heights
    finally:r.close()

def test_hidden_cached_label_does_not_eagerly_evaluate_authored_height(tmp_path):
    r=make(tmp_path,props={'AutoHeight':'=true','Text':'=caption','Visible':'=shown','Height':'=1/0'})
    try:
        h=ref(r).property('Height');behavior(r,'Set(shown,false)');assert ref(r).property('Height')==h
    finally:r.close()

def test_auto_height_line_breaks_wrapping_padding_and_blank_fields(tmp_path):
    r=make(tmp_path,props={'AutoHeight':'=true','Text':'="first" & Char(10) & "second"','Size':'=10','LineHeight':'=2','Width':'=200'})
    try:assert ref(r).property('Height')==50
    finally:r.close()
    r=make(tmp_path,props={'AutoHeight':'=true','Text':'=""','PaddingTop':'=Blank()','Role':'=Blank()','Live':'=Blank()'})
    try:assert ref(r).property('Height')==5 and r.render(ref(r))['classic_display']['live']=='off'
    finally:r.close()

@pytest.mark.parametrize('family',sorted(VERSIONS))
def test_tab_stops_selection_event_validation_and_focus_contract(tmp_path,family):
    r=make(tmp_path,family,props={'TabIndex':'=0'})
    try:
        assert r.render(ref(r))['tab_stop'];r.event(ref(r).path,'OnSelect');assert r.globals['clicks']==1
        with pytest.raises(ValueError):r.event(ref(r).path,'OnChange')
        if family=='Label':behavior(r,'SetFocus(D)');assert r.focus_request['path']==ref(r).path
        else:
            with pytest.raises(FxError):behavior(r,'SetFocus(D)')
    finally:r.close()

@pytest.mark.parametrize('variant,count',[(None,5),('star6',6),('star8',8),('star12',12)])
def test_star_polygon_variant_bounds_and_dash_geometry(tmp_path,variant,count):
    r=make(tmp_path,'Star',variant=variant,props={'Width':'=200','Height':'=80','BorderThickness':'=4','BorderStyle':'=BorderStyle.Dashed'})
    try:
        g=r.render(ref(r))['classic_display']['geometry'];assert len(g['points'])==2*count
        assert g['dash']==[12,8] and g['stroke_width']==4
        assert all(0<=x<=200 and 0<=y<=80 and math.isfinite(x+y) for x,y in g['points'])
    finally:r.close()

def test_ellipse_geometry_respects_non_square_box_and_no_border(tmp_path):
    r=make(tmp_path,'Circle',props={'Width':'=200','Height':'=80','BorderThickness':'=4','BorderStyle':'=BorderStyle.None'})
    try:
        g=r.render(ref(r))['classic_display']['geometry'];assert g['stroke_width']==0
        assert g['attributes']=={'cx':100,'cy':40,'rx':100,'ry':40}
    finally:r.close()

def test_unsupported_variant_never_runs_behavior(tmp_path):
    r=make(tmp_path,'Star',variant='star7')
    try:r.run_event(ref(r),'OnSelect');assert r.globals['clicks']==0 and any(d['kind']=='Unsupported' for d in r.diagnostics)
    finally:r.close()

@pytest.mark.parametrize('family,version',[('Label','2.3.0'),('Rectangle','2.1.0'),('Circle','2.1.2')])
def test_older_templates_reject_authored_content_language(tmp_path,family,version):
    r=make(tmp_path,family,version,{'ContentLanguage':'="fr-CA"'})
    try:assert any(d['kind']=='Unsupported' and d['member'].endswith('.ContentLanguage') for d in r.diagnostics)
    finally:r.close()

def test_catalog_includes_inline_metadata_and_pinned_provenance():
    for version,spec in catalog()['families']['Label'].items():
        assert {'AutoHeight','Wrap','Live','LineHeight','Overflow','IsErrorMessage'}<=set(spec['properties'])
        assert spec['defaults']['LineHeight']=='=1.2'
    assert all(len(e['archive_sha256'])==64 and '/630e6973e5c81ddc196283cde26dd696d619d6c7/' in e['source'] for e in catalog()['evidence'])


@pytest.mark.parametrize('family',sorted(VERSIONS))
@pytest.mark.parametrize('implicit',[False,True])
def test_gallery_row_selection_and_thisitem_scope(tmp_path,family,implicit):
    p=Project(tmp_path/'gallery')
    props={'Width':'=80','Height':'=30'}
    if family=='Label':props['Text']='=ThisItem.Title'
    if not implicit:props['OnSelect']='=Collect(history,{ID:ThisItem.ID,Name:Self.Name})'
    version=max(VERSIONS[family],key=lambda v:tuple(map(int,v.split('.'))))
    p.update_source('Src/gallery.pa.yaml',dump_yaml({'App':{'Properties':{'OnStart':'=Clear(history)'}},'Screens':{'Home':{'Children':[{'Rows':{'Control':'Gallery@2.15.0','Properties':{'Items':'=Table({ID:1,Title:"First"},{ID:2,Title:"Second"})','OnSelect':'=Collect(history,{ID:Self.Selected.ID,Name:"Rows"})'},'Children':[{'D':{'Control':family+'@'+version,'Properties':props}}]}}]}}}))
    r=Runtime(p);r.restart()
    try:
        row=r.render(r.global_refs['Rows'])['rows'][1]['children'][0]
        assert not row['tab_stop'] and row['selectable']
        r.event(row['path'],'OnSelect');r.drain_events()
        assert r.collections['history']==[{'ID':2,'Name':'Rows' if implicit else 'D'}]
        assert r.fx.evaluate('Rows.Selected.ID')==2 and not r.diagnostics
    finally:r.close()

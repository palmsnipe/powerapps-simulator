"""HTML text contracts, formatting functions, scope and offline presentation."""
import json
from pathlib import Path
from copy import deepcopy
import pytest
from powerapps_sim.html_controls import fragment,estimate
from powerapps_sim.fixtures import html_text_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError
from powerapps_sim.conformance import run_case

CORPUS=json.loads((Path(__file__).parents[1]/'powerapps_sim/conformance_cases/html-text.json').read_text())

@pytest.fixture(scope='module')
def oracle_runtime(tmp_path_factory):
    r=Runtime(Project(tmp_path_factory.mktemp('html-oracle')))
    yield r
    r.close()

@pytest.mark.parametrize('case',CORPUS['cases'],ids=lambda c:c['id'])
def test_every_pinned_html_function_reference(oracle_runtime,case):
    result=run_case(oracle_runtime,case)
    assert result['status']=='passed',result

@pytest.fixture
def r(tmp_path):
    r=Runtime(html_text_project(tmp_path/'p'));r.restart();r.state();assert not r.diagnostics
    yield r
    r.close()

def test_shared_template_defaults_and_typed_outputs(r):
    ref=r.refs['HtmlLab/LeftPanel/LivePreview'];node=r.render(ref)
    assert node['family']=='HtmlViewer' and node['version']=='2.1.0' and node['tab_stop'] is False
    assert node['props']['PaddingTop']==5 and ref.property('AutoHeight') is True
    assert '<strong>Fictional LeftPanel</strong>' in node['html']
    assert r.binder.property_type(ref.control,'HtmlText').kind=='Text'
    assert r.binder.property_type(ref.control,'AutoHeight').kind=='Boolean'
    assert not r.diagnostics

def test_markup_input_is_escaped_and_pure_html_evaluation_does_not_invent_callbacks(r):
    r.event('HtmlLab/LeftPanel/Title','OnInput','<script>alert(1)</script> & "quoted"')
    r.state();left=r.refs['HtmlLab/LeftPanel/LivePreview'];right=r.refs['HtmlLab/RightPanel/LivePreview']
    assert '&lt;script&gt;' in r.render(left)['html'] and '<script>' not in r.render(left)['html']
    assert 'Fictional RightPanel' in r.render(right)['html']
    assert not r.collections['history'] and not r.diagnostics
    assert r.fx.evaluate('PlainText(LeftPanel.Preview)').startswith('<script>alert(1)</script> & "quoted"')

def test_html_onselect_and_gallery_thisitem_preserve_instance_isolation(r):
    r.event('HtmlLab/LeftPanel/LivePreview','OnSelect');r.state()
    assert r.collections['history'][0]['Panel']=='LeftPanel'
    assert len(r.fx.evaluate('LeftPanel.History'))==1 and not r.fx.evaluate('RightPanel.History')
    gallery=r.refs['HtmlLab/LeftPanel/CaptureGallery'];node=r.render(gallery)
    child=next(c for c in r.descendants(gallery) if c.family=='HtmlViewer')
    assert '<strong>Fictional LeftPanel</strong>' in r.render(child)['html']
    r.event(child.path,'OnSelect');r.state()
    assert gallery.property('Selected')['Title']=='Fictional LeftPanel'
    assert len(r.collections['history'])==1 and not r.diagnostics

@pytest.mark.parametrize('mode',['Disabled','View'])
def test_non_edit_or_hidden_html_cannot_run_app_actions(r,mode):
    panel=r.global_refs['LeftPanel'];panel.control.properties['DisplayMode']='=DisplayMode.'+mode;r.invalidate()
    r.event('HtmlLab/LeftPanel/LivePreview','OnSelect');assert not r.collections['history']
    panel.control.properties['DisplayMode']='=DisplayMode.Edit';panel.control.properties['Visible']='=false';r.invalidate()
    r.event('HtmlLab/LeftPanel/LivePreview','OnSelect');assert not r.collections['history']

@pytest.mark.parametrize('name',['TabIndex','AcceptsFocus','OnChange','OnInput','Reset','Text'])
def test_unknown_contracts_remain_visible_without_source_repair(r,name):
    ref=r.refs['HtmlLab/LeftPanel/LivePreview'];ref.control.properties[name]='=Blank()';r.analyze();r.invalidate()
    assert any(d['kind']=='Unsupported' and d['member'].endswith('.'+name) for d in r.state()['diagnostics'])
    assert name in ref.control.properties

@pytest.mark.parametrize('prop,value',[('AutoHeight','=1'),('HtmlText','={A:1}'),('Width','=-1'),('PaddingTop','=-1'),('Size','=false')])
def test_invalid_html_properties_are_isolated(r,prop,value):
    ref=r.refs['HtmlLab/LeftPanel/LivePreview'];ref.control.properties[prop]=value;r.analyze();r.invalidate()
    r.state();assert r.diagnostics and r.fx.evaluate('RightPanel.TitleValue')=='Fictional RightPanel'
    assert ref.control.properties[prop]==value

def test_html_does_not_accept_fake_input_or_reset_or_setfocus(r):
    ref=r.refs['HtmlLab/LeftPanel/LivePreview']
    for event in ('OnChange','OnInput','OnSearch'):
        with pytest.raises(ValueError,match='only accepts OnSelect'):r.event(ref.path,event,'injected')
    with pytest.raises(FxError,match='SetFocus does not support HtmlViewer'):r.fx.evaluate('SetFocus(LivePreview)',ref.context(behavior=True))
    with pytest.raises(FxError):r.fx.evaluate('Reset(LivePreview)',ref.context(behavior=True))

@pytest.mark.parametrize('version',['2.0.0','2.1.0'])
def test_autoheight_wrapping_cap_and_reactive_sibling_geometry(r,version):
    ref=r.refs['HtmlLab/LeftPanel/LivePreview'];ref.control.raw["Control"]="HtmlViewer@"+version
    initial=ref.property('Height');button=r.refs['HtmlLab/LeftPanel/CaptureButton']
    assert button.property('Y')==ref.property('Y')+initial+8
    ref.control.properties['HtmlText']='="<p>" & Concat(Sequence(500),"Long fictional text ") & "</p>"';r.invalidate()
    wide=ref.property('Height');assert initial<wide<=7680
    ref.control.properties['Width']='=180';r.invalidate();narrow=ref.property('Height');assert narrow>=wide
    assert button.property('Y')==ref.property('Y')+narrow+8
    ref.control.properties['HtmlText']='="<div style=\'height:9000px\'>Tall</div>"';r.invalidate();assert ref.property('Height')==7680
    ref.control.properties['AutoHeight']='=false';r.invalidate();assert ref.property('Height')==116
    assert not r.diagnostics

@pytest.mark.parametrize('raw,warning',[
    ('<script>alert(1)</script><p>Kept</p>','<script>'),
    ('<iframe src="https://example.test"></iframe><p>Kept</p>','<iframe>'),
    ('<style>body{display:none}</style><p>Kept</p>','<style>'),
    ('<svg><a href="javascript:alert(1)">bad</a></svg><p>Kept</p>','<svg>'),
    ('<img src="https://example.test/pixel"><p>Kept</p>','image source'),
    ('<a href="javascript:alert(1)">Kept</a>','external hyperlinks'),
    ('<p onclick="alert(1)">Kept</p>','p.onclick'),
    ('<div style="color:blue;background-image:url(https://example.test/x)">Kept</div>','background-image'),
    ('<div style="position:fixed">Kept</div>','position fixed'),
    ('<button>Kept</button>','<button>'),
])
def test_unsupported_html_is_diagnosed_and_raw_source_is_preserved(r,raw,warning):
    ref=r.refs['HtmlLab/LeftPanel/LivePreview'];source='="'+raw.replace('"','""')+'"';ref.control.properties['HtmlText']=source;r.analyze();r.invalidate()
    node=r.render(ref)
    assert 'Kept' in node['html'] and any(warning in e for e in node['errors'])
    assert any(d['kind']=='Unsupported' and d['member']=='LivePreview.HtmlText' for d in r.diagnostics)
    assert node['props']['HtmlText']==raw and ref.control.properties['HtmlText']==source
    assert r.fx.evaluate('RightPanel.TitleValue')=='Fictional RightPanel'

@pytest.mark.parametrize('source',[
    '<p><b>bold &amp; “quotes”</b></p>',
    '<ul style="list-style-type:disc;padding-inline-start:40px"><li>One</li><li>Two</li></ul>',
    '<table><tr><th>A</th><td colspan="2">B</td></tr></table>',
    '<div style="position:relative"><span style="position:absolute;top:0;left:0">Overlay</span>Text</div>',
    '<a href="#details">Link</a><p id="details">Target</p>',
    '<img src="data:image/png;base64,aGVsbG8=" alt="Local bitmap" width="10" height="20">',
    '<img src="/api/asset/Images/local.png" alt="Local asset">',
])
def test_offline_formatting_local_media_and_fragment_links(source):
    f=fragment(source);assert not f['issues'];assert f['html']
    assert fragment(f['html'])['html'] # Presentation reparses; exported source stays original.

@pytest.mark.parametrize('source',['//example.test/x','/api/asset/../private','/api/asset/%2e%2e/private','/api/asset/a?x=1','data:image/svg+xml;base64,PHN2Zz4=','file:///tmp/a','https://example.test/a'])
def test_image_sources_do_not_escape_the_local_asset_contract(source):
    f=fragment('<img src="'+source+'">');assert 'src=' not in f['html'] and f['issues']

@pytest.mark.parametrize('mode',['float','decimal'])
def test_encoding_is_scalar_lazy_and_propagates_errors(oracle_runtime,mode):
    r=oracle_runtime;r.environment['number_mode']=mode
    assert r.fx.evaluate('EncodeUrl("River & forest/é 😀")')=='River%20%26%20forest%2F%C3%A9%20%F0%9F%98%80'
    assert r.fx.evaluate('EncodeUrl(Blank())')==''
    assert r.fx.evaluate('If(false,EncodeHTML(1/0),"lazy")')=='lazy'
    assert r.fx.evaluate('IfError(PlainText(1/0),"caught")')=='caught'
    from powerapps_sim.binding import BindScope
    for name in ('EncodeHTML','PlainText','EncodeUrl'):
        r.binder.errors.clear();r.binder.bind(r.fx.parse(name+'(["one","two"])'),BindScope())
        assert r.binder.errors and r.binder.errors[0][1].kind=='Type'

@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('mode',['float','decimal'])
def test_html_workflow_keeps_owned_data_source_and_runtime(tmp_path,language,mode):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    p=html_text_project(tmp_path/'p');w=Workspace(tmp_path,p.root)
    try:
        w.runtime.store.patch('Snapshots',{}, {'Title':'Fictional owner','Quantity':9})
        w.runtime.restart();before=deepcopy(w.ai.read_runtime());rows=deepcopy(w.runtime.store.rows('Snapshots'))
        entry=w.workflows.catalog()['scenarios'][0]
        result=w.workflows.run({**entry['scenario'],'environment':{'enum_mode':'strong','language':language,'number_mode':mode}},expected_revision=revision(p.root))
        assert result['status']=='passed',result
        assert len(result['steps'])==43
        assert w.ai.read_runtime()==before and w.runtime.store.rows('Snapshots')==rows
    finally:w.runtime.close()

def test_export_roundtrip_and_malformed_drafts_retain_power_apps_source(r):
    from io import BytesIO
    from zipfile import ZipFile
    from powerapps_sim.source import load_yaml
    p=r.project;source=p.documents['Src/html-text.pa.yaml']
    with ZipFile(BytesIO(p.export())) as z:
        assert z.read('Src/html-text.pa.yaml').decode()==source
        assert not any('emu' in name or name.endswith('.sqlite') for name in z.namelist())
    subtree=load_yaml(p.export_control('LivePreview'))
    assert subtree['Screens']['Scratch']['Children'][0]['LivePreview']['Control']=='HtmlViewer@2.1.0'
    assert subtree['Screens']['Scratch']['Children'][0]['LivePreview']['Properties']['HtmlText']=='=HtmlPanel.Preview'
    with pytest.raises(Exception):p.update_source('Src/html-text.pa.yaml','Screens: [malformed')
    assert p.documents['Src/html-text.pa.yaml']==source
    assert r.render(r.refs['HtmlLab/LeftPanel/LivePreview'])['html']

def test_excessive_nesting_and_local_image_traversal_remain_diagnosed():
    f=fragment('<div>'*1500+'Kept'+'</div>'*1500)
    assert f['issues'] and 'Kept' in f['html']
    assert estimate(f['tree'],200)>0

@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('formula',['42.25','Date(2026,1,2)'])
def test_htmltext_scalar_coercion_uses_the_host_locale(r,language,mode,formula):
    r.environment.update(language=language,number_mode=mode)
    ref=r.refs['HtmlLab/LeftPanel/LivePreview'];ref.control.properties['HtmlText']='='+formula
    r.analyze();r.invalidate()
    assert ref.property('HtmlText')==r.fx.evaluate('Text('+formula+')')
    assert r.render(ref)['html']==ref.property('HtmlText') and not r.diagnostics

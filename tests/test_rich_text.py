"""Rich HTML output, control contracts, component scope and form persistence."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import json
import pytest
from powerapps_sim.rich_text import sanitize
from powerapps_sim.fixtures import rich_text_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.syntax import FxError
from powerapps_sim.fx import Context

LEFT='RichLab/LeftPanel/Body'
RIGHT='RichLab/RightPanel/Body'
FORM='RichLab/MemoForm/BodyCard/DraftBody'

@pytest.fixture
def r(tmp_path):
    runtime=Runtime(rich_text_project(tmp_path/'rich'));runtime.restart();runtime.state()
    assert not runtime.diagnostics
    yield runtime
    runtime.close()

def change(r,path=LEFT,html='<p><u>Edited</u> &amp; scoped</p>',token=None):
    r.event(path,'OnChange',html if token is None else {'html':html,'reset_token':token})

@pytest.mark.parametrize('version',['2.3.0','2.5.0','2.6.0'])
def test_verified_versions_output_type_and_defaults(r,version):
    ref=r.refs[LEFT];ref.control.kind='RichTextEditor@'+version;ref.control.raw['Control']=ref.control.kind
    r.analyze();r.invalidate();node=r.render(ref)
    assert node['value']=='<p>Fictional <strong>river</strong> memo</p>' and node['text_reset']
    assert node['props']['EnableSpellCheck'] is True and node['tab_stop'] is True
    assert ref.property('TabIndex')==0 and r.binder.property_type(ref.control,'HtmlText').kind=='Text'
    assert not r.diagnostics

@pytest.mark.parametrize('html',[
 '<p><strong>Bold</strong> <em>italic</em> <u>underlined</u></p>',
 '<p><span style="color:#0f6cbd;background-color:#fff59d;font-size:24px">Color</span></p>',
 '<ul><li>One</li><li>Two</li></ul><ol><li>First</li></ol>',
 '<a href="https://example.test/path?q=fictional&amp;id=1">Linked</a>',
 '<a href="mailto:fictional@example.test">Mail</a><a href="tel:+15550100">Call</a>',
 '<a href="#details">Detail</a><p id="details">Target</p>',
 '<table><tr><td>A</td><td>B</td></tr></table>',
 '<img src="data:image/png;base64,aGVsbG8=" alt="Fictional bitmap">',
 '<p>é 中文 😀 &lt;draft&gt; &amp; scope</p>',
])
def test_supported_formatting_roundtrips_without_loss_or_invented_navigation(html):
    cleaned=sanitize(html);assert not cleaned['issues'] and cleaned['html']
    assert sanitize(cleaned['html'])==cleaned

@pytest.mark.parametrize('size,px',[('1',10),('2',13),('3',16),('4',18),('5',24),('6',32),('7',48)])
def test_native_legacy_font_output_is_normalized(size,px):
    cleaned=sanitize(f'<font color="#0f6cbd" size="{size}" face="Segoe UI">Fictional</font>')
    assert not cleaned['issues'] and '<span style=' in cleaned['html'] and f'font-size:{px}px' in cleaned['html']
    assert '<font' not in cleaned['html']

@pytest.mark.parametrize('html',[
 '<script>alert(1)</script><p>Kept</p>',
 '<style>body{color:red}</style><p>Kept</p>',
 '<p onclick="alert(1)">Kept</p>',
 '<iframe src="https://example.test">Hidden</iframe><p>Kept</p>',
 '<object data="file:///tmp/private">Hidden</object><p>Kept</p>',
 '<a href="javascript:alert(1)">Kept</a>',
 '<a href="data:text/html,boom">Kept</a>',
 '<a href="file:///tmp/private">Kept</a>',
 '<p style="background-image:url(https://example.test/image)">Kept</p>',
 '<img src="https://example.test/photo"><p>Kept</p>',
])
def test_unsupported_content_is_removed_and_reported_without_app_actions(r,html):
    change(r,html=html);node=r.render(r.refs[LEFT]);value=r.fx.evaluate('LeftPanel.Html')
    assert 'Kept' in value and any(d['kind']=='Unsupported' for d in r.diagnostics)
    assert not any(s in value for s in ('<script','onclick','<style','<iframe','<object','javascript:','file:','url('))
    assert node['errors'] and r.fx.evaluate('RightPanel.Changes')==0

@pytest.mark.parametrize('html',['','<p><br></p>','<div> </div>','<p><strong></strong></p>','<p>&nbsp;</p>'])
def test_empty_formatting_is_blank_for_required_cards(r,html):
    change(r,FORM,html);assert r.fx.evaluate('MemoForm.Updates.Body')==''
    assert r.fx.evaluate('MemoForm.Valid') is False

@pytest.mark.parametrize('bad',[None,1,True,[],{}, {'html':'x','reset_token':1},{'html':'x','reset_token':'x','extra':True}])
def test_invalid_value_event_is_atomic(r,bad):
    before=deepcopy(r.control_state);history=deepcopy(r.collections)
    with pytest.raises(ValueError):r.event(LEFT,'OnChange',bad)
    assert r.control_state==before and r.collections==history

@pytest.mark.parametrize('event',['OnInput','OnSelect','OnSearch','Pressed','OnCalendar'])
def test_editor_does_not_adopt_text_input_or_selection_events(r,event):
    with pytest.raises(ValueError):r.event(LEFT,event,'injected')
    assert not r.collections['history']

@pytest.mark.parametrize('prop',['HtmlText','Text','OnInput','OnSelect','DelayOutput','TriggerOutput','ReadOnly','AutoHeight','MaxLength','Font','AcceptsFocus'])
def test_invalid_authored_contract_preserves_source_and_isolates_other_instance(r,prop):
    ref=r.refs[LEFT];ref.control.properties[prop]='=Blank()';r.analyze();r.invalidate();r.state()
    assert any(d['kind']=='Unsupported' and d['member']=='Body.'+prop for d in r.diagnostics)
    assert ref.control.properties[prop]=='=Blank()' and r.fx.evaluate('MemoForm.Valid') is True
    if prop=='HtmlText':
        with pytest.raises(FxError,match='output'):ref.property('HtmlText')

@pytest.mark.parametrize('prop,formula',[('Default','{A:1}'),('Default','["one","two"]'),('EnableSpellCheck','1'),('Reset','"true"'),('TabIndex','1.5'),('TabIndex','true'),('Width','-1'),('Height','false'),('Size','false')])
def test_type_validation_is_visible(r,prop,formula):
    ref=r.refs[LEFT];ref.control.properties[prop]='='+formula;r.analyze();r.invalidate();r.state()
    assert r.diagnostics and r.fx.evaluate('RightPanel.Changes')==0

@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('formula',['42.25','Date(2026,1,2)','true','Blank()'])
def test_default_scalar_coercion_matches_power_fx_text(r,language,mode,formula):
    ref=r.refs[LEFT];r.environment.update(language=language,number_mode=mode)
    ref.control.properties['Default']='='+formula;r.analyze();r.invalidate()
    assert ref.property('HtmlText')==sanitize(r.fx.evaluate('Text('+formula+')') or '')['html']
    assert not r.diagnostics

def test_duplicate_html_does_not_repeat_typed_component_callback(r):
    change(r);change(r);assert len(r.collections['history'])==1
    row=r.collections['history'][0]
    assert row=={'Html':'<p><u>Edited</u> &amp; scoped</p>','Plain':'Edited & scoped','Count':1,'Panel':'LeftPanel'}
    assert r.fx.evaluate('RightPanel.Changes')==0
    r.event('RichLab/LeftPanel/CaptureButton','OnSelect')
    assert r.fx.evaluate('CountRows(LeftPanel.History)')==1
    r.fx.evaluate('Reset(LeftPanel)',Context(r,behavior=True));r.state()
    assert r.fx.evaluate('LeftPanel.Changes')==0 and r.fx.evaluate('CountRows(LeftPanel.History)')==0
    assert len(r.collections['history'])==1 and r.fx.evaluate('LeftPanel.Plain')=='Fictional river memo'

@pytest.mark.parametrize('reset',['Reset(LeftPanel)','Reset(Body)','restart','default','pulse'])
def test_resets_invalidate_pending_html_without_new_callback(r,reset):
    ref=r.refs[LEFT];token=r.render(ref)['text_reset'];change(r,token=token)
    if reset=='restart':r.restart()
    elif reset=='default':
        r.global_refs['LeftPanel'].control.properties['InitialHtml']='="<p>New baseline</p>"';r.invalidate()
    elif reset=='pulse':ref.control.properties['Reset']='=true';r.invalidate();r.state()
    else:r.fx.evaluate(reset,Context(r,behavior=True) if reset=='Reset(LeftPanel)' else ref.context(behavior=True))
    new=r.render(ref);assert new['text_reset']!=token
    before=deepcopy(r.collections['history']);value=new['value']
    change(r,html='<p>Stale</p>',token=token)
    assert ref.property('HtmlText')==value and r.collections['history']==before

@pytest.mark.parametrize('mode',['View','Disabled'])
def test_ancestor_mode_and_visibility_gate_edits(r,mode):
    panel=r.global_refs['LeftPanel'];panel.control.properties['DisplayMode']='=DisplayMode.'+mode;r.invalidate()
    change(r);assert r.fx.evaluate('LeftPanel.Plain')=='Fictional river memo' and not r.collections['history']
    panel.control.properties['DisplayMode']='=DisplayMode.Edit';panel.control.properties['Visible']='=false';r.invalidate()
    change(r);assert not r.collections['history']

def test_gallery_html_patch_uses_thisitem_and_does_not_implicitly_select(r):
    g=r.global_refs['MemoGallery'];r.store.patch('Memos',{}, {'Title':'Fictional second','Body':'<p>Second</p>'});r.invalidate();r.state()
    rows=r.render(g)['rows'];ref=r.refs[rows[1]['children'][0]['path']]
    assert g.property('Selected')['ID']==1
    change(r,ref.path,'<p><u>Second scoped</u></p>');r.state()
    assert r.store.rows('Memos')[1]['Body']=='<p><u>Second scoped</u></p>'
    assert r.store.rows('Memos')[0]['Body'].startswith('<p>Initial') and g.property('Selected')['ID']==1
    assert not r.diagnostics

def test_form_failure_retry_reset_and_persistent_html(r):
    token=r.render(r.refs[FORM])['text_reset'];change(r,FORM,'<p>Fictional <strong>save</strong></p>',token)
    assert r.fx.evaluate('MemoForm.Unsaved') and r.fx.evaluate('MemoForm.Valid')
    r.store.failures['Memos']='write';r.event('RichLab/SaveDraft','OnSelect')
    assert r.fx.evaluate('status')=='Save failed' and r.fx.evaluate('MemoForm.Unsaved')
    assert r.store.rows('Memos')[0]['Body'].startswith('<p>Initial')
    r.store.failures.clear();r.event('RichLab/SaveDraft','OnSelect');r.state()
    assert r.fx.evaluate('MemoForm.LastSubmit.Body')=='<p>Fictional <strong>save</strong></p>' and not r.fx.evaluate('MemoForm.Unsaved')
    change(r,FORM,'<p>Late</p>',token);assert r.store.rows('Memos')[0]['Body']=='<p>Fictional <strong>save</strong></p>'
    # Reopen through Runtime so this also proves the project database survives restart.
    from powerapps_sim.source import Project
    other=Runtime(Project(r.project.root));other.restart();other.state()
    try:assert other.fx.evaluate('MemoForm.Updates.Body')=='<p>Fictional <strong>save</strong></p>'
    finally:other.close()

def test_unsupported_version_does_not_inherit_a_guessed_contract(r):
    r.refs[LEFT].control.kind='RichTextEditor@2.7.0';r.refs[LEFT].control.raw['Control']='RichTextEditor@2.7.0';r.analyze();r.state()
    assert any(d['kind']=='Unsupported' and '2.7.0' in d['message'] for d in r.diagnostics)

@pytest.mark.parametrize('command',['bold','italic','underline','foreColor','hiliteColor','fontSize','insertOrderedList','insertUnorderedList','createLink','unlink','removeFormat','undo','redo','insertHTML'])
def test_browser_formatting_failure_is_a_visible_diagnostic(r,command):
    r.event(LEFT,'OnEditorIssue',{'command':command});r.state()
    assert any(d['kind']=='Unsupported' and command in d['message'] for d in r.diagnostics)
    assert not r.collections['history']

def test_export_keeps_authored_html_and_malformed_draft_keeps_last_valid_preview(r):
    p=r.project;original=p.documents['Src/rich-text.pa.yaml'];change(r)
    with ZipFile(BytesIO(p.export())) as z:
        assert z.read('Src/rich-text.pa.yaml').decode()==original
        assert not any('emu' in f or f.endswith('.sqlite') for f in z.namelist())
    assert 'RichTextEditor@2.6.0' in p.export_control('Body')
    with pytest.raises(Exception):p.update_source('Src/rich-text.pa.yaml','Screens: [malformed')
    assert p.documents['Src/rich-text.pa.yaml']==original and r.fx.evaluate('LeftPanel.Plain')=='Edited & scoped'

@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('mode',['float','decimal'])
def test_full_workflow_is_repeatable_and_preserves_owned_source_data_runtime(tmp_path,language,mode):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision,data_revision
    p=rich_text_project(tmp_path/'rich');w=Workspace(tmp_path,p.root)
    try:
        w.runtime.store.patch('Memos',{}, {'Title':'Fictional owner','Body':'<p>Owned</p>'})
        w.runtime.restart();before=deepcopy(w.ai.read_runtime());source=revision(p.root);data=data_revision(w.runtime.store)
        entry=w.workflows.catalog()['scenarios'][0]
        scenario={**entry['scenario'],'environment':{'enum_mode':'strong','language':language,'number_mode':mode}}
        result=w.workflows.run(scenario,expected_revision=source)
        assert result['status']=='passed',[(i,s.get('error')) for i,s in enumerate(result['steps']) if s['status']!='passed']
        assert len(result['steps'])==65 and not result['diagnostics']
        assert w.ai.read_runtime()==before and revision(p.root)==source and data_revision(w.runtime.store)==data
    finally:w.runtime.close()

@pytest.mark.parametrize('html',['<p><span style="text-decoration-line:underline">Native underline</span></p>', '<p><span style="font-size:x-large;color:rgb(15,108,189);background-color:rgb(255,245,157)">Native color</span></p>'])
def test_native_browser_formatting_styles_survive_server_normalization(html):
    assert not sanitize(html)['issues'] and sanitize(html)['html']==html

def test_limits_and_nesting_are_explicit():
    with pytest.raises(ValueError,match='million'):sanitize('x'*1_000_001)
    result=sanitize('<div>'*1000+'Kept'+'</div>'*1000)
    assert result['issues'] and 'Kept' in result['html']

def test_default_change_removes_old_editor_issue_state(r):
    change(r,html='<script>hidden</script><p>Kept</p>');assert r.refs[LEFT].state['rich_issues']
    r.global_refs['LeftPanel'].control.properties['InitialHtml']='="<p>New baseline</p>"';r.invalidate()
    assert r.render(r.refs[LEFT])['value']=='<p>New baseline</p>'
    assert not r.refs[LEFT].state.get('rich_issues')

def test_no_setfocus_contract_is_invented_for_editor(r):
    with pytest.raises(FxError,match='SetFocus does not support RichTextEditor'):
        r.fx.evaluate('SetFocus(Body)',r.refs[LEFT].context(behavior=True))

@pytest.mark.parametrize('index',[-1,0,1,5])
def test_signed_tab_index_uses_canvas_tab_stop_contract(r,index):
    r.refs[LEFT].control.properties['TabIndex']='='+str(index);r.invalidate()
    assert r.render(r.refs[LEFT])['tab_stop']==(index>=0)
    assert not r.diagnostics

@pytest.fixture
def client(tmp_path):
    from powerapps_sim.web import create_app
    p=rich_text_project(tmp_path/'rich-web');app=create_app(tmp_path/'workspace',p.root)
    yield app.test_client(),app.extensions['workspace']
    app.extensions['workspace'].runtime.close()

@pytest.mark.parametrize('payload',[{}, {'path':LEFT,'html':[],'reset_token':'x'}, {'path':LEFT,'html':'x','reset_token':1}, {'path':'missing','html':'x','reset_token':'x'}])
def test_sanitizer_endpoint_rejects_malformed_requests(client,payload):
    c,w=client;assert c.post('/api/richtext/sanitize',json=payload,headers={'X-Emulator-Request':'1'}).status_code==400


def test_paste_sanitizer_does_not_publish_html_or_run_app_callback(client):
    c,w=client;token=w.runtime.render(w.runtime.refs[LEFT])['text_reset'];before=deepcopy(w.runtime.control_state)
    html='<p><strong>Fictional paste</strong></p><script>hidden</script>'
    request={'path':LEFT,'html':html,'reset_token':token}
    assert c.post('/api/richtext/sanitize',json=request).status_code==403
    reply=c.post('/api/richtext/sanitize',json=request,headers={'X-Emulator-Request':'1'})
    assert reply.status_code==200 and reply.json['html']=='<p><strong>Fictional paste</strong></p>' and reply.json['issues']
    assert w.runtime.control_state==before and not w.runtime.collections['history']
    w.runtime.fx.evaluate('Reset(LeftPanel)',Context(w.runtime,behavior=True))
    stale=c.post('/api/richtext/sanitize',json=request,headers={'X-Emulator-Request':'1'})
    assert stale.json=={'stale':True}

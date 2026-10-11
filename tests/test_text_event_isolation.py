"""Browser event identity across native, modern, classic and rich text editors."""
from copy import deepcopy
import pytest
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project, dump_yaml

KINDS=['TextInput@0.0.51','TextInput@0.0.53','ModernTextInput@1.0.0',
       'ModernTextInput@1.1.2','Classic/TextInput@2.3.2',
       'RichTextEditor@2.3.0','RichTextEditor@2.5.0','RichTextEditor@2.6.0']


def contracts(kind):
    family=kind.split('@')[0]
    return ('Value','Value','text') if family=='TextInput' else ('Default','HtmlText','html') if family=='RichTextEditor' else ('Default','Text','text')


def make(tmp_path,kind,numbers='float',enum_mode='legacy',gallery=False):
    binding,output,_=contracts(kind)
    initial='<p>Same initial</p>' if kind.startswith('RichTextEditor') else 'Same initial'
    p=Project(tmp_path/'owner');p.config['environment'].update(number_mode=numbers,enum_mode=enum_mode);p.save_config()
    props={binding:'=EditorPanel.Seed','OnChange':'=Collect(history,{Text:Self.'+output+'});EditorPanel.Changed(Self.'+output+')'}
    controls=[{'Draft':{'Control':kind,'Properties':props}}]
    definition={'AccessAppScope':False,'CustomProperties':{
        'Seed':{'PropertyKind':'Input','DataType':'Text','Default':'=""'},
        'Current':{'PropertyKind':'Output','DataType':'Text','Default':'=Draft.'+output},
        'History':{'PropertyKind':'Output','DataType':'Table','Default':'=history'},
        'Changed':{'PropertyKind':'Event','ReturnType':'None','Parameters':[{'published':{'DataType':'Text'}}],'Default':'=Blank()'}},
        'Properties':{'OnReset':'=Clear(history);Reset(Draft)'},'Children':controls}
    p.update_source('Src/Components/EditorPanel.pa.yaml',dump_yaml({'ComponentDefinitions':{'EditorPanel':definition}}))
    children=[{name:{'Control':'CanvasComponent','ComponentName':'EditorPanel','Properties':{'Seed':'=seed','Changed':'=Collect(events,{Panel:"'+name+'",Text:published})'}}} for name in ['Left','Right']]
    if gallery:
        children.append({'Rows':{'Control':'Gallery@2.15.0','Properties':{'Items':'=Table({ID:1,Title:seed},{ID:2,Title:seed})'},'Children':[
            {'RowDraft':{'Control':kind,'Properties':{binding:'=ThisItem.Title','OnChange':'=Collect(events,{Panel:Text(ThisItem.ID),Text:Self.'+output+'})'}}}]}})
    p.update_source('Src/isolation.pa.yaml',dump_yaml({'App':{'Properties':{'OnStart':'=Set(seed,'+__import__('json').dumps(initial)+');Clear(events);Reset(Left);Reset(Right)'}},'Screens':{'Home':{'Children':children}}}))
    r=Runtime(p);r.restart();r.state();assert not r.diagnostics,r.diagnostics
    return r


def publish(r,g,text,event='OnChange',stale=None):
    _,_,field=contracts(g.control.kind)
    r.event(g.path,event,{field:text,'reset_token':stale or r.render(g)['text_reset']})
    r.state()


@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('numbers,enum_mode',[('float','legacy'),('decimal','strong')])
def test_other_component_event_is_ignored_with_identical_defaults(tmp_path,kind,numbers,enum_mode):
    r=make(tmp_path,kind,numbers,enum_mode)
    try:
        left,right=r.refs['Home/Left/Draft'],r.refs['Home/Right/Draft']
        a,b=r.render(left),r.render(right);before=r.control_state.copy(),deepcopy(r.component_state),deepcopy(r.collections)
        assert a['value']==b['value']
        assert a['text_reset']!=b['text_reset']
        publish(r,right,'Wrong instance',stale=a['text_reset'])
        assert r.render(right)['value']==b['value']
        assert (r.control_state,r.component_state,r.collections)==before
        publish(r,right,'<p>Right edit</p>' if kind.startswith('Rich') else 'Right edit')
        assert r.fx.evaluate('Left.Current')==a['value'] and len(r.fx.evaluate('Left.History'))==0
        assert len(r.fx.evaluate('Right.History'))==1 and r.collections['events'][0]['Panel']=='Right'
        assert not r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('kind',KINDS)
def test_other_gallery_row_event_is_ignored_even_when_values_match(tmp_path,kind):
    r=make(tmp_path,kind,gallery=True)
    try:
        rows=r.fx.evaluate('Rows.AllItems');left,right=rows[0]['RowDraft'],rows[1]['RowDraft']
        a,b=r.render(left),r.render(right);assert a['value']==b['value'] and a['text_reset']!=b['text_reset']
        publish(r,right,'Wrong row',stale=a['text_reset'])
        assert r.render(right)['value']==b['value'] and not r.collections['events']
        publish(r,right,'<p>Row edit</p>' if kind.startswith('Rich') else 'Row edit')
        assert r.collections['events'][0]['Panel']=='2' and r.render(left)['value']==a['value']
        assert not r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('kind',KINDS)
def test_token_observes_binding_change_before_next_preview(tmp_path,kind):
    r=make(tmp_path,kind)
    try:
        g=r.refs['Home/Left/Draft'];old=r.text_token(g)
        r.fx.evaluate('Set(seed,"New default")',Context(r,behavior=True))
        current=r.text_token(g)
        assert current!=old
        publish(r,g,'Old draft',stale=old)
        assert r.fx.evaluate('Left.Current')=='New default' and not r.collections['events']
        assert not r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('kind',KINDS)
def test_changed_control_version_invalidates_event_at_same_path(tmp_path,kind):
    r=make(tmp_path,kind)
    try:
        g=r.refs['Home/Left/Draft'];old=r.render(g)['text_reset']
        g.control=deepcopy(g.control)
        if kind.startswith('TextInput'):g.control.kind='TextInput@'+('0.0.53' if kind.endswith('51') else '0.0.51')
        elif kind.startswith('RichText'):g.control.kind='RichTextEditor@'+('2.5.0' if kind.endswith('2.3.0') else '2.3.0')
        else:g.control.kind='ModernTextInput@'+('1.0.0' if kind.endswith('1.1.2') else '1.1.2')
        r.invalidate();current=r.render(g)
        assert current['text_reset']!=old
        publish(r,g,'Old version',stale=old)
        assert r.fx.evaluate('Left.Current')==current['value'] and not r.collections['events']
        assert not r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('kind',KINDS)
def test_user_changes_keep_token_stable_and_reset_is_instance_specific(tmp_path,kind):
    r=make(tmp_path,kind)
    try:
        left,right=r.refs['Home/Left/Draft'],r.refs['Home/Right/Draft'];a,b=r.render(left),r.render(right)
        value='<p>Edited</p>' if kind.startswith('Rich') else 'Edited'
        publish(r,left,value);publish(r,right,value)
        assert r.render(left)['text_reset']==a['text_reset'] and r.render(right)['text_reset']==b['text_reset']
        r.fx.evaluate('Reset(Left)',Context(r,behavior=True));r.state()
        assert r.render(left)['text_reset']!=a['text_reset'] and r.render(right)['text_reset']==b['text_reset']
        assert r.fx.evaluate('Left.Current')==a['value'] and r.fx.evaluate('Right.Current')==value
        assert len(r.collections['events'])==2 and not r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('kind,prop,formula',[
    ('ModernTextInput@1.0.0','TriggerOutput','="Delayed"'),('ModernTextInput@1.1.2','Type','=TextInputType.Password'),
    ('ModernTextInput@1.0.0','MaxLength','=40'),('Classic/TextInput@2.3.2','DelayOutput','=true'),
    ('Classic/TextInput@2.3.2','Mode','=TextMode.MultiLine'),('Classic/TextInput@2.3.2','MaxLength','=40'),
    ('TextInput@0.0.51','TriggerOutput','="Delayed"'),('TextInput@0.0.53','Mode','="Multiline"'),
    ('TextInput@0.0.51','MaxLength','=40'),('TextInput@0.0.53','Type','="Password"')])
def test_editing_contract_change_cancels_prior_draft(tmp_path,kind,prop,formula):
    r=make(tmp_path,kind)
    try:
        g=r.refs['Home/Left/Draft'];old=r.render(g)['text_reset']
        g.control=deepcopy(g.control);g.control.properties[prop]=formula;r.invalidate();n=r.render(g)
        assert not n['errors'],n['errors']
        assert n['text_reset']!=old
        publish(r,g,'Prior contract',stale=old)
        assert r.fx.evaluate('Left.Current')==n['value'] and not r.collections['events'] and not r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('kind',KINDS)
def test_style_changes_preserve_pending_edit_identity(tmp_path,kind):
    r=make(tmp_path,kind)
    try:
        g=r.refs['Home/Left/Draft'];old=r.render(g)['text_reset']
        g.control=deepcopy(g.control);g.control.properties['Width']='=350';r.invalidate()
        assert r.render(g)['text_reset']==old
        publish(r,g,'<p>Retained</p>' if kind.startswith('Rich') else 'Retained',stale=old)
        assert len(r.collections['events'])==1 and not r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('version',['2.3.0','2.5.0','2.6.0'])
def test_sanitizer_rejects_another_editor_token_without_observing_issues(tmp_path,version):
    from powerapps_sim.web import create_app
    r=make(tmp_path,'RichTextEditor@'+version);r.close()
    app=create_app(tmp_path/'workspace',r.project.root);w=app.extensions['workspace'];client=app.test_client()
    try:
        left,right=w.runtime.refs['Home/Left/Draft'],w.runtime.refs['Home/Right/Draft']
        before=deepcopy(w.runtime.control_state),deepcopy(w.runtime.collections),deepcopy(w.runtime.diagnostics)
        result=client.post('/api/richtext/sanitize',json={'path':right.path,'html':'<script>wrong</script><p>Wrong editor</p>','reset_token':w.runtime.render(left)['text_reset']},headers={'X-Emulator-Request':'1'})
        assert result.status_code==200 and result.json=={'stale':True}
        assert before==(w.runtime.control_state,w.runtime.collections,w.runtime.diagnostics)
    finally:w.runtime.close()


@pytest.mark.parametrize('kind',KINDS)
def test_return_to_prior_binding_does_not_revive_old_draft(tmp_path,kind):
    r=make(tmp_path,kind)
    try:
        g=r.refs['Home/Left/Draft'];a=r.render(g)
        r.fx.evaluate('Set(seed,"Intermediate default")',Context(r,behavior=True));b=r.text_token(g)
        r.fx.evaluate('Set(seed,'+__import__('json').dumps(a['value'])+')',Context(r,behavior=True));c=r.text_token(g)
        assert len({a['text_reset'],b,c})==3
        publish(r,g,'Resurrected draft',stale=a['text_reset'])
        assert r.fx.evaluate('Left.Current')==a['value'] and not r.collections['events'] and not r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('kind',KINDS)
def test_return_to_prior_kind_does_not_revive_old_draft(tmp_path,kind):
    r=make(tmp_path,kind)
    try:
        g=r.refs['Home/Left/Draft'];a=r.render(g);g.control=deepcopy(g.control)
        original=g.control.kind
        g.control.kind=('TextInput@0.0.53' if kind.endswith('51') else 'TextInput@0.0.51') if kind.startswith('TextInput') else ('RichTextEditor@2.5.0' if kind.endswith('2.3.0') else 'RichTextEditor@2.3.0') if kind.startswith('Rich') else ('ModernTextInput@1.0.0' if kind.endswith('1.1.2') else 'ModernTextInput@1.1.2')
        r.invalidate();b=r.render(g)['text_reset']
        g.control.kind=original;r.invalidate();c=r.render(g)['text_reset']
        assert len({a['text_reset'],b,c})==3
        publish(r,g,'Resurrected version',stale=a['text_reset'])
        assert r.fx.evaluate('Left.Current')==a['value'] and not r.collections['events'] and not r.diagnostics
    finally:r.close()


@pytest.mark.parametrize('kind',KINDS)
def test_form_record_switch_with_equal_defaults_invalidates_old_event(tmp_path,kind):
    binding,output,_=contracts(kind);initial='<p>Same initial</p>' if kind.startswith('Rich') else 'Same initial'
    p=Project(tmp_path/'form');p.update_source('Src/form.pa.yaml',dump_yaml({'App':{'Properties':{'OnStart':'=Set(currentID,1);Clear(events)'}},'Screens':{'Home':{'Children':[
        {'Editor':{'Control':'Form@2.4.4','Properties':{'DataSource':'=Notes','Item':'=LookUp(Notes,ID=currentID)'},'Children':[
            {'TitleCard':{'Control':'TypedDataCard@1.0.7','Variant':'TextualEdit','Properties':{'DataField':'="Title"','Default':'=ThisItem.Title','Update':'=Draft.'+output},'Children':[
                {'Draft':{'Control':kind,'Properties':{binding:'=Parent.Default','OnChange':'=Collect(events,{Text:Self.'+output+'})'}}}]}}]}}
    ]}}}))
    from powerapps_sim.store import ListStore
    store=ListStore(p.root/'data.sqlite',schema_root=p.root/'lists')
    try:
        store.add_list('Notes',{'fields':{'ID':{'type':'integer'},'Title':{'type':'string'}},'required':['Title']})
        store.import_rows('Notes',[{'ID':1,'Title':initial},{'ID':2,'Title':initial}])
    finally:store.close()
    r=Runtime(p)
    try:
        r.restart();r.state();g=r.refs['Home/Editor/TitleCard/Draft'];a=r.render(g)
        r.fx.evaluate('Set(currentID,2)',Context(r,behavior=True));new=r.text_token(g)
        assert new!=a['text_reset']
        publish(r,g,'Wrong record',stale=a['text_reset'])
        assert r.fx.evaluate('Editor.Item.ID')==2 and not r.fx.evaluate('Editor.Unsaved')
        assert r.render(g)['value']==initial and not r.collections['events'] and not r.diagnostics
        assert [row['Title'] for row in r.store.rows('Notes')]==[initial,initial]
    finally:r.close()


@pytest.mark.parametrize('kind',KINDS)
def test_http_event_isolation_does_not_dirty_peer_or_trigger_callback(tmp_path,kind):
    from powerapps_sim.web import create_app
    r=make(tmp_path,kind);r.close();app=create_app(tmp_path/'workspace',r.project.root);w=app.extensions['workspace'];client=app.test_client()
    try:
        _,_,field=contracts(kind);left,right=w.runtime.refs['Home/Left/Draft'],w.runtime.refs['Home/Right/Draft'];a,b=w.runtime.render(left),w.runtime.render(right)
        reply=client.post('/api/event',json={'path':right.path,'name':'OnChange','value':{field:'Wrong peer','reset_token':a['text_reset']}},headers={'X-Emulator-Request':'1'})
        assert reply.status_code==200 and not reply.json['diagnostics']
        assert w.runtime.render(right)['value']==b['value'] and not right.state.get('dirty') and not w.runtime.collections['events']
    finally:w.runtime.close()

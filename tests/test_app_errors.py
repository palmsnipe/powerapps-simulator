"""Deferred App.OnError, provenance, catches and isolated callback failures."""
from copy import deepcopy
import pytest
from powerapps_sim.fixtures import app_errors_project,data_table_project,modern_grid_project
from powerapps_sim.runtime import Runtime,serial
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError

@pytest.fixture
def r(tmp_path):
    result=Runtime(app_errors_project(tmp_path/'errors'));result.restart();result.state()
    assert not result.diagnostics
    yield result;result.close()

def click(r,name):
    r.event('ErrorLab/'+name,'OnSelect');return r.state()

def test_stored_errors_observe_lazily_without_mutating_provenance(r):
    original=r.globals['stored'];assert isinstance(original,FxError)
    assert not r.collections['reports'] and original.source=='App.OnStart' and not original.observed
    click(r,'ToggleFault')
    assert r.collections['reports'][0]['Source']=='App.OnStart'
    assert r.collections['reports'][0]['Observed']=='ErrorLab/Fault.Text'
    assert original.observed=='' and isinstance(r.globals['stored'],FxError)
    for _ in range(4):r.state()
    assert len(r.collections['reports'])==1 and not r.notifications
    click(r,'ToggleFault');click(r,'ToggleFault')
    assert len(r.collections['reports'])==2
    diagnostic=next(d for d in r.diagnostics if d.get('observed')=='ErrorLab/Fault.Text')
    assert diagnostic['member']=='Fault.Text' and diagnostic['error_source']=='App.OnStart'
    assert r.project.app['OnStart'][diagnostic['start']:diagnostic['end']]=='1/0'

def test_caught_control_property_never_reports_before_visual_consumption(r):
    fault=r.refs['ErrorLab/Fault'];fault.control=deepcopy(fault.control)
    fault.control.properties['Text']='=1/0';r.invalidate()
    assert r.fx.evaluate('IfError(Fault.Text,"recovered")',Context(r,error_source='Manual.Rule'))=='recovered'
    assert not r.diagnostics and not r.app_errors.pending and not r.app_errors.reports
    r.state();assert len(r.app_errors.reports)==1

def test_component_catches_and_instance_provenance(r):
    click(r,'CatchCallback');assert r.globals['caught']==13
    assert not r.collections['reports'] and not r.diagnostics
    click(r,'LeftPanel/Fire');click(r,'RightPanel/Fire')
    left,right=r.collections['reports']
    assert (left['Kind'],left['Source'],left['Observed'])==(13,'ErrorLab/LeftPanel.Failed','ErrorLab/LeftPanel/Fire.OnSelect')
    assert right['Kind']==1000 and right['HttpStatus']==503 and right['Response']=='Fictional offline service'
    assert right['Source']=='ErrorLab/RightPanel.Failed'
    assert all(entry['handled'] for entry in r.app_errors.reports)

def test_typed_function_chain_and_forall_preserve_order_and_side_effects(r):
    click(r,'FailFunction');assert r.collections['reports'][-1]['Source']=='App.Formulas.Reciprocal'
    click(r,'FailChain');assert r.globals['afterChain']==42
    assert r.collections['reports'][-1]['BatchCount']==2
    assert [row['Kind'] for row in r.app_errors.reports[-1]['records']]==[13,1000]
    result=r.execute('ForAll([0,1,0,2],If(Value=0,1/0,Collect(good,Value)))',Context(r,behavior=True),'','Manual.ForAll')
    assert isinstance(result,FxError) and r.collections['good']==[{'Value':1},{'Value':2}]
    r.drain_events();assert r.collections['reports'][-1]['BatchCount']==2

def test_handler_can_rethrow_without_recursion_or_replacing_values(r):
    r.globals['rethrow']=True;r.invalidate();click(r,'ToggleFault')
    assert len(r.app_errors.reports)==1 and not r.app_errors.reports[0]['handled']
    assert r.notifications[-1]['message']=='Division by zero'
    assert isinstance(r.globals['stored'],FxError)
    r.state();assert len(r.app_errors.reports)==1
    r.project.app['OnError']='=1/0';click(r,'LeftPanel/Fire')
    assert len(r.app_errors.reports)==2 and not r.app_errors.pending
    assert any(d['member']=='App.OnError' for d in r.diagnostics)

def test_default_reporting_repeat_events_and_restart(r):
    r.project.app.pop('OnError');click(r,'FailFunction');click(r,'FailFunction')
    assert len(r.app_errors.reports)==2 and len(r.notifications)==1
    r.restart();r.state();assert not r.app_errors.reports and not r.notifications

def test_handler_navigation_renders_destination(r):
    r.project.app['OnError']='=Navigate(Recovery);Set(showFault,false)'
    state=click(r,'ToggleFault')
    assert r.active_screen=='Recovery' and state['screen']=='Recovery' and state['tree']['name']=='Recovery'
    assert not r.globals['showFault']
    assert r.refs['ErrorLab/Fault'].property('Text')=='42'
    assert not r.app_errors.pending

def test_handler_navigation_after_gallery_component_input_reset_renders_destination(tmp_path):
    from powerapps_sim.source import dump_yaml
    p=app_errors_project(tmp_path/'p');name='Src/app-errors.pa.yaml';source=deepcopy(p.parsed[name])
    source['App']['Properties']['OnError']='=Navigate(Recovery)'
    source['App']['Properties']['OnStart']+=';ClearCollect(rows,{ID:1,Caption:"Initial"})'
    definition=source['ComponentDefinitions']['ErrorPanel']
    definition['CustomProperties']['Caption']['RaiseOnReset']=True
    definition['Properties']['OnReset']='=1/0'
    source['Screens']['ErrorLab']['Children'].append({'RowGallery':{'Control':'Gallery@2.15.0',
        'Properties':{'Items':'=rows','Height':'=100'},'Children':[{'RowPanel':{'Control':'CanvasComponent',
        'ComponentName':'ErrorPanel','Properties':{'Caption':'=ThisItem.Caption'}}}]}})
    p.update_source(name,dump_yaml(source));rr=Runtime(p)
    try:
        rr.restart();rr.state();assert rr.active_screen=='ErrorLab' and not rr.app_errors.reports
        # Existing row scopes refresh during materialization, after state() has
        # already chosen its screen. The input reset then invokes OnError.
        rr.collections['rows']=[{'ID':1,'Caption':'Changed'}];rr.invalidate();state=rr.state()
        assert rr.active_screen==state['screen']==state['tree']['name']=='Recovery'
        assert rr.app_errors.reports[-1]['records'][0]['Source'].endswith('/RowPanel.OnReset')
    finally:rr.close()

def test_failed_sqlite_write_reports_and_retry_persists(r):
    before=r.store.rows('Drafts');r.store.failures['Drafts']='write';click(r,'SaveDraft')
    assert r.store.rows('Drafts')==before and len(r.collections['reports'])==1
    assert r.collections['reports'][0]['Source']=='ErrorLab/SaveDraft.OnSelect'
    r.store.failures.clear();click(r,'SaveDraft')
    assert r.store.rows('Drafts')[0]['Title']=='Fictional updated draft' and len(r.collections['reports'])==1

@pytest.mark.parametrize('formula,expected',[
    ('Error({})',None),('Error(Table())',None),
    ('IfError(Error({Kind:13.0}),FirstError.Kind)',13),
    ('IfError(Error({Kind:ErrorKind.Div0,Source:"Origin",Observed:"Old",Details:{HttpStatusCode:503}}),FirstError.Source)', 'Origin'),
    ('IfError(Error({Kind:ErrorKind.Div0,Observed:"Old"}),FirstError.Observed)','Test.Rule'),
    ('IfError(Error({Kind:ErrorKind.Div0}),IsBlank(FirstError.Details))',True),
    ('IfError(If(false,1/0,42),0)',42),
    ('IfError(Error({Kind:13.5}),FirstError.Kind)',25),
    ('IfError(Error({Message:"missing kind"}),FirstError.Kind)',25),
    ('IfError(Error({Kind:13,Source:42}),FirstError.Kind)',25),
    ('IfError(Error({Kind:13,Details:true}),FirstError.Kind)',25),
])
def test_error_records_and_lazy_handlers(r,formula,expected):
    assert r.fx.evaluate(formula,Context(r,error_source='Test.Rule'))==expected
    assert not r.app_errors.pending and not r.app_errors.reports

@pytest.mark.parametrize('number_mode',['float','decimal'])
@pytest.mark.parametrize('enum_mode',['legacy','strong'])
def test_numeric_profiles_and_rethrow_metadata(tmp_path,number_mode,enum_mode):
    p=app_errors_project(tmp_path/'p');p.config['environment'].update(number_mode=number_mode,enum_mode=enum_mode);p.save_config()
    rr=Runtime(p)
    try:
        rr.restart();rr.state();click(rr,'CatchCallback');assert rr.globals['caught']==13
        click(rr,'RightPanel/Fire');assert rr.collections['reports'][-1]['HttpStatus']==503
        rr.globals['rethrow']=True;rr.invalidate();click(rr,'LeftPanel/Fire')
        assert rr.notifications[-1]['message']=='Fictional left callback'
        assert rr.app_errors.reports[-1]['records'][0]['Kind']==13
    finally:rr.close()

@pytest.mark.parametrize('factory',[data_table_project,modern_grid_project])
def test_table_cell_errors_are_deferred_and_stable(tmp_path,factory):
    rr=Runtime(factory(tmp_path/'p'))
    try:
        rr.project.app['OnError']='=Collect(captured,AllErrors)';rr.restart();rr.state()
        column=next(ref for ref in rr.refs.values() if ref.family in ('DataTableColumn','ModernDataGridColumn'))
        column.control=deepcopy(column.control);column.control.properties['Text']='=1/0';rr.invalidate()
        rr.state();count=len(rr.app_errors.reports);assert count>0
        assert all(row['Source']==column.path+'.Text' for row in rr.collections['captured'])
        rr.state();assert len(rr.app_errors.reports)==count
        column.control.properties['Text']='="healthy"';rr.invalidate();rr.state()
        column.control.properties['Text']='=1/0';rr.invalidate();rr.state()
        assert len(rr.app_errors.reports)>count
    finally:rr.close()

@pytest.mark.parametrize('language',['en-CA','fr-CA'])
@pytest.mark.parametrize('number_mode',['float','decimal'])
def test_workflow_preserves_owner_source_data_and_runtime(tmp_path,language,number_mode):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision,data_revision
    p=app_errors_project(tmp_path/'p');w=Workspace(tmp_path,p.root)
    try:
        before=(revision(p.root),data_revision(w.runtime.store),serial(w.runtime.globals),serial(w.runtime.app_errors.reports))
        scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario'])
        scenario['environment']={'language':language,'number_mode':number_mode}
        result=w.workflows.run(scenario,expected_revision=revision(p.root))
        assert result['status']=='passed',result['steps']
        assert len(result['steps'])==24
        assert before==(revision(p.root),data_revision(w.runtime.store),serial(w.runtime.globals),serial(w.runtime.app_errors.reports))
    finally:w.runtime.close()

def test_ai_read_source_export_and_authoring_onerror(tmp_path):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    p=app_errors_project(tmp_path/'p');w=Workspace(tmp_path,p.root)
    try:
        def ai(name,**kwargs):return w.ai.call(name,kwargs,expected_project=str(p.root))
        original=ai('read_source',app_property='OnError')['text']
        assert 'FirstError.Source' in original
        click(w.runtime,'LeftPanel/Fire');before=deepcopy(w.runtime.app_errors.reports)
        info=ai('read_runtime');assert info['error_reports']==serial(before)
        ai('evaluate_formula',formula='IfError(1/0,FirstError.Kind)')
        assert before==w.runtime.app_errors.reports
        exported=ai('export_source');assert exported['app']['OnError']==original
        assert all('error_reports' not in document for document in exported['documents'].values())
        current=revision(p.root)
        entry=w.authoring.save_source(expected_revision=current,property='OnError',text='Collect(reports,AllErrors)')
        assert ai('read_source',app_property='OnError')['text']=='=Collect(reports,AllErrors)'
        assert w.runtime.pending_source and w.runtime.project.app['OnError']==original
        w.authoring.undo(entry['id'],expected_revision=entry['after_revision'])
        assert ai('read_source',app_property='OnError')['text']==original
    finally:w.runtime.close()

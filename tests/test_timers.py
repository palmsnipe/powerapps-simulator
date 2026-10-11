"""Canvas timer scheduling, pure observation, scoped callbacks and clock control."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import pytest
from powerapps_sim.fixtures import timers_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError
from powerapps_sim.timers import advance,pulse,snapshot,MAX_MS

LEFT='TimerLab/LeftPulse/Beat'
RIGHT='TimerLab/RightPulse/Beat'

@pytest.fixture
def r(tmp_path):
    runtime=Runtime(timers_project(tmp_path/'timers'));runtime.restart();runtime.state()
    assert not runtime.diagnostics
    yield runtime
    runtime.close()

def start(r,name='LeftPulse'):
    r.event(f'TimerLab/{name}/ActionButton','OnSelect')

def test_cold_timer_outputs_and_template_defaults(r):
    assert r.fx.evaluate('LeftPulse.Elapsed')==0 and r.fx.evaluate('LeftPulse.Starts')==0
    assert r.fx.evaluate('BgTimer.AutoPause') is False and r.fx.evaluate('FgTimer.AutoPause') is True
    ref=r.refs[LEFT];assert ref.property('Reset') is False and r.binder.property_type(ref.control,'Value').kind=='Number'
    assert r.render(ref)['timer']['running'] is False and r.render(ref)['tab_stop'] is True
    assert not r.collections['history'] and not r.store.rows('Ticks')

@pytest.mark.parametrize('version',['2.0.0','2.0.1','2.1.0'])
def test_verified_versions_keep_the_same_scheduler_contract(r,version):
    ref=r.refs[LEFT];ref.control.kind='Timer@'+version;r.analyze();r.invalidate()
    r.event(LEFT,'OnSelect');advance(r,1000)
    assert r.fx.evaluate('LeftPulse.Cycles')==1 and not r.diagnostics

@pytest.mark.parametrize('mode',['float','decimal'])
def test_repeating_boundary_values_start_events_and_server_owned_clock(r,mode):
    r.environment['number_mode']=mode;original=r.environment['clock'];start(r)
    assert r.fx.evaluate('LeftPulse.Starts')==1
    advance(r,999);assert r.fx.evaluate('LeftPulse.Elapsed')==999 and not r.collections['history']
    advance(r,1);assert r.fx.evaluate('LeftPulse.Elapsed')==0 and r.fx.evaluate('LeftPulse.Starts')==2
    assert r.collections['history'][0]['ElapsedMs']==1000 and r.collections['history'][0]['Cycle']==1
    advance(r,1500);assert r.fx.evaluate('LeftPulse.Cycles')==2 and r.fx.evaluate('LeftPulse.Elapsed')==500
    assert r.fx.evaluate('RightPulse.Elapsed')==0 and r.fx.evaluate('RightPulse.Starts')==0
    assert len(r.store.rows('Ticks'))==2 and r.store.rows('Ticks')[0]['Panel']=='LeftPulse'
    assert r.store.rows('Ticks')[0]['At']=='2026-01-01 12:00:01'
    assert r.environment['clock']==original
    assert isinstance(r.fx.evaluate('LeftPulse.Elapsed'),Decimal if mode=='decimal' else float)
    assert not r.diagnostics


def test_pause_resume_keeps_elapsed_and_completion_starts_next_cycle(r):
    start(r);advance(r,400);start(r);advance(r,3000)
    assert r.fx.evaluate('LeftPulse.Elapsed')==400 and r.fx.evaluate('LeftPulse.Cycles')==0
    start(r);advance(r,600)
    assert r.fx.evaluate('LeftPulse.Elapsed')==0 and r.fx.evaluate('LeftPulse.Cycles')==1
    assert r.fx.evaluate('LeftPulse.Starts')==3 # Initial, resume, repeating cycle.


def test_native_timer_click_toggles_without_mutating_start_formula(r):
    ref=r.refs[LEFT];original=ref.control.properties['Start'];r.event(LEFT,'OnSelect');advance(r,200)
    assert ref.control.properties['Start']==original and ref.property('Start') is False
    r.event(LEFT,'OnSelect');advance(r,800);assert ref.property('Value')==200
    assert not r.diagnostics


def test_changing_start_formula_overrides_manual_playback(r):
    ref=r.refs[LEFT];r.event(LEFT,'OnSelect');advance(r,200)
    # A true edge is observed even when a native click already started the timer.
    r.component_state['TimerLab/LeftPulse']['variables']['playing']=True;r.invalidate();r.state()
    r.component_state['TimerLab/LeftPulse']['variables']['playing']=False;r.invalidate();r.state()
    advance(r,1000);assert ref.property('Value')==200


def test_independent_component_deadlines_and_tie_order(r):
    start(r);start(r,'RightPulse');advance(r,3000)
    assert r.fx.evaluate('LeftPulse.Cycles')==3 and r.fx.evaluate('RightPulse.Cycles')==2
    assert [v['Panel'] for v in r.collections['history']]==['LeftPulse','RightPulse','LeftPulse','LeftPulse','RightPulse']
    assert r.fx.evaluate('LeftPulse.Elapsed')==r.fx.evaluate('RightPulse.Elapsed')==0
    assert len(r.store.rows('Ticks'))==3


def test_component_reset_stops_only_its_own_timer_and_resets_local_state(r):
    start(r);start(r,'RightPulse');advance(r,1000)
    r.event('TimerLab/ResetLeft','OnSelect');advance(r,500)
    assert r.fx.evaluate('LeftPulse.Elapsed')==r.fx.evaluate('LeftPulse.Cycles')==r.fx.evaluate('LeftPulse.Starts')==0
    assert r.fx.evaluate('CountRows(LeftPulse.History)')==0 and r.fx.evaluate('RightPulse.Cycles')==1
    assert len(r.collections['history'])==2 and not r.diagnostics


def test_hidden_timers_autopause_background_and_navigation_auto_start(r):
    r.event('TimerLab/Background','OnSelect');advance(r,500)
    r.event('TimerLab/ReviewButton','OnSelect');advance(r,1500)
    assert r.active_screen=='Review' and r.fx.evaluate('bgEnds')==1 and r.fx.evaluate('fgEnds')==0
    assert r.fx.evaluate('reviews')==1 and r.global_refs['ReviewTimer'].property('Value')==750
    r.event('Review/Return','OnSelect');advance(r,1500)
    assert r.fx.evaluate('fgEnds')==1 and r.fx.evaluate('bgEnds')==1
    r.event('TimerLab/ReviewButton','OnSelect')
    assert r.global_refs['ReviewTimer'].property('Value')==0
    advance(r,750);assert r.fx.evaluate('reviews')==2 and not r.diagnostics


def test_screen_reentry_resumes_an_incomplete_autostart_timer(r):
    r.event('TimerLab/ReviewButton','OnSelect');advance(r,300);r.event('Review/Return','OnSelect');advance(r,1000)
    assert r.global_refs['ReviewTimer'].property('Value')==300 and r.fx.evaluate('reviews')==0
    r.event('TimerLab/ReviewButton','OnSelect');advance(r,450)
    assert r.fx.evaluate('reviews')==1


def test_reset_timer_while_start_true_starts_from_zero_and_does_not_emit_end(r):
    start(r);advance(r,450);r.fx.evaluate('Reset(Beat)',r.refs[LEFT].context(behavior=True));r.drain_events()
    assert r.fx.evaluate('LeftPulse.Elapsed')==0 and r.fx.evaluate('LeftPulse.Starts')==2
    assert not r.collections['history'];advance(r,1000);assert r.fx.evaluate('LeftPulse.Cycles')==1


def test_short_reset_pulse_is_not_missed(r):
    ref=r.refs[LEFT];ref.control.properties['Reset']='=resetFlag';r.component_state['TimerLab/LeftPulse']['variables']['resetFlag']=False
    r.invalidate();r.state();start(r);advance(r,450)
    r.fx.evaluate('Set(resetFlag,true);Set(resetFlag,false)',ref.context(behavior=True));r.drain_events()
    assert ref.property('Value')==0 and r.fx.evaluate('LeftPulse.Starts')==2


def test_pure_properties_and_ai_observation_do_not_advance_clock_or_run_behaviors(r,tmp_path):
    start(r);advance(r,250);before=deepcopy(snapshot(r));history=deepcopy(r.collections)
    for _ in range(20):assert r.fx.evaluate('LeftPulse.Elapsed')==250
    assert snapshot(r)==before and r.collections==history
    from powerapps_sim.application import Workspace
    w=Workspace(tmp_path/'workspace',r.project.root)
    try:
        before=deepcopy(w.ai.read_runtime());assert before['timers']['elapsed_ms']==0
        assert w.ai.read_runtime()==before and not w.runtime.collections['history']
    finally:w.runtime.close()


def test_direct_inspection_freezes_time_without_triggering_visible_screen_timers(r):
    start(r);advance(r,250);r.preview_screen='Review'
    assert advance(r,1000)['advanced_ms']==0 and r.fx.evaluate('LeftPulse.Elapsed')==250 and r.fx.evaluate('reviews')==0
    r.state();assert r.fx.evaluate('reviews')==0
    r.preview_screen=None;advance(r,750);assert r.fx.evaluate('LeftPulse.Cycles')==1


def test_browser_pulses_are_monotonic_and_multiple_clients_do_not_double_count(r):
    start(r);token=r.timer_token
    pulse(r,token,True,now=10);pulse(r,token,True,now=10.25);pulse(r,token,True,now=10.25)
    assert r.fx.evaluate('LeftPulse.Elapsed')==250
    pulse(r,token,False,now=10.5);pulse(r,token,True,now=20)
    assert r.fx.evaluate('LeftPulse.Elapsed')==250
    pulse(r,token,True,now=20.25);assert r.fx.evaluate('LeftPulse.Elapsed')==500


def test_pause_simulation_and_stale_generation_do_not_catch_up(r):
    start(r);token=r.timer_token;pulse(r,token,True,now=10)
    r.timer_playing=False;pulse(r,token,True,now=11);r.timer_playing=True;pulse(r,token,True,now=100)
    assert r.fx.evaluate('LeftPulse.Elapsed')==0
    r.restart();assert not pulse(r,token,True,now=100.5) and r.timer_elapsed==0

@pytest.mark.parametrize('payload',[None,-1,True,'1',float('nan'),float('inf'),MAX_MS+1])
def test_invalid_time_requests_are_atomic(r,payload):
    before=deepcopy(snapshot(r))
    with pytest.raises(ValueError):advance(r,payload)
    assert snapshot(r)==before and not r.collections['history']

@pytest.mark.parametrize('prop,formula',[('Duration','-1'),('Duration','86400001'),('Duration','true'),('Duration','"1000"'),('Start','1'),('Repeat','"true"'),('Reset','1'),('AutoStart','1'),('AutoPause','1')])
def test_invalid_timer_inputs_are_diagnosed_without_harming_other_timers(r,prop,formula):
    ref=r.global_refs['BgTimer'];ref.control.properties[prop]='='+formula;r.analyze();r.invalidate();r.state()
    assert r.diagnostics;start(r);advance(r,1000);assert r.fx.evaluate('LeftPulse.Cycles')==1

@pytest.mark.parametrize('name',['Value','Running','OnChange','OnInput','AcceptsFocus'])
def test_unknown_authored_contracts_remain_in_source_with_diagnostics(r,name):
    ref=r.global_refs['BgTimer'];ref.control.properties[name]='=Blank()';r.analyze();r.invalidate();r.state()
    assert ref.control.properties[name]=='=Blank()' and any(d['kind']=='Unsupported' and d['member']=='BgTimer.'+name for d in r.diagnostics)

@pytest.mark.parametrize('event',['OnChange','OnInput','OnTimerStart','OnTimerEnd','Pressed'])
def test_browser_cannot_inject_timer_values_or_callbacks(r,event):
    with pytest.raises(ValueError):r.event(LEFT,event,500)
    assert not r.collections['history'] and r.fx.evaluate('LeftPulse.Elapsed')==0

@pytest.mark.parametrize('mode',['View','Disabled'])
def test_user_input_gate_does_not_toggle_timer(r,mode):
    r.global_refs['LeftPulse'].control.properties['DisplayMode']='=DisplayMode.'+mode;r.invalidate();r.event(LEFT,'OnSelect')
    assert r.render(r.refs[LEFT])['timer']['running'] is False


def test_duration_can_be_changed_while_running(r):
    start(r);advance(r,400)
    r.global_refs['LeftPulse'].control.properties['Period']='=250';r.invalidate();r.drain_events()
    advance(r,0);assert r.fx.evaluate('LeftPulse.Cycles')==1 and r.collections['history'][0]['ElapsedMs']==250


def test_blank_template_null_defaults(r):
    ref=r.global_refs['BgTimer']
    for n in ('Duration','Start','Repeat','Reset'):ref.control.properties[n]='=Blank()'
    r.invalidate();r.state();assert ref.property('Duration')==0 and ref.property('Start') is False and not r.diagnostics


def test_zero_duration_one_shot_and_repeat_limit_are_visible(r):
    ref=r.global_refs['BgTimer'];ref.control.properties.update(Duration='=0',Start='=true',Repeat='=false');r.invalidate();r.state()
    advance(r,0);assert r.fx.evaluate('bgEnds')==1
    advance(r,1000);assert r.fx.evaluate('bgEnds')==1
    ref.control.properties['Repeat']='=true';r.fx.evaluate('Reset(BgTimer)',Context(r,behavior=True));r.drain_events()
    with pytest.raises(FxError,match='1000'):advance(r,1)
    assert r.timer_states[ref.path].suspended and any(d['kind']=='Cycle' for d in r.diagnostics)
    assert advance(r,250)['events']==0 # The same bad source cannot spin every browser pulse.


def test_callback_write_failure_preserves_cycle_progress_and_recovers(r):
    start(r);r.store.failures['Ticks']='write';advance(r,1000)
    assert r.fx.evaluate('status')=='Save failed' and r.fx.evaluate('LeftPulse.Cycles')==1 and not r.store.rows('Ticks')
    r.store.failures.clear();advance(r,1000)
    assert r.fx.evaluate('status')=='Saved' and r.store.rows('Ticks')[0]['Cycle']==2
    assert len(r.collections['history'])==2 and not r.diagnostics


def test_queued_select_from_start_is_drained_in_the_same_activation(r):
    ref=r.refs[LEFT];ref.control.properties['OnTimerStart']='=Select(ActionButton)';r.invalidate();r.event(LEFT,'OnSelect')
    assert r.render(ref)['timer']['running'] is True # ActionButton sets playing=true from its initial false.
    assert not r.event_queue

@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('mode',['float','decimal'])
def test_full_timer_workflow_preserves_owned_source_database_and_runtime(tmp_path,language,mode):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision,data_revision
    p=timers_project(tmp_path/'timer-owner');w=Workspace(tmp_path,p.root)
    try:
        w.runtime.store.patch('Ticks',{}, {'Title':'Fictional owner tick','Panel':'Owned','Cycle':99,'ElapsedMs':7,'At':'Owned'})
        start(w.runtime);advance(w.runtime,250)
        before=deepcopy(w.ai.read_runtime());source=revision(p.root);data=data_revision(w.runtime.store)
        entry=w.workflows.catalog()['scenarios'][0]
        result=w.workflows.run({**entry['scenario'],'environment':{**entry['scenario']['environment'],'language':language,'number_mode':mode}},expected_revision=source)
        assert result['status']=='passed',[(s['index'],s.get('error'),s.get('actual')) for s in result['steps'] if s['status']!='passed']
        assert len(result['steps'])==83 and not result['diagnostics'] and len(result['collections']['results'][0])==20
        assert w.ai.read_runtime()==before and revision(p.root)==source and data_revision(w.runtime.store)==data
        assert len(w.runtime.store.rows('Ticks'))==1
    finally:w.runtime.close()


def test_source_export_does_not_include_emulator_clock_or_runtime_state(r):
    from zipfile import ZipFile
    from io import BytesIO
    from powerapps_sim.source import load_yaml
    original=r.project.documents['Src/timers.pa.yaml'];start(r);advance(r,2500)
    with ZipFile(BytesIO(r.project.export())) as z:
        assert z.read('Src/timers.pa.yaml').decode()==original
        assert not any('simulator' in n or '.sqlite' in n for n in z.namelist())
    subtree=load_yaml(r.project.export_control('Beat'))
    assert subtree['Screens']['Scratch']['Children'][0]['Beat']['Properties']['Start']=='=playing'
    assert 'timer_token' not in original and 'advanced_ms' not in original
    with pytest.raises(Exception):r.project.update_source('Src/timers.pa.yaml','Screens: [malformed')
    assert r.project.documents['Src/timers.pa.yaml']==original and r.fx.evaluate('LeftPulse.Elapsed')==500


def test_failing_end_formula_does_not_stop_other_timer_or_repair_source(r):
    ref=r.refs[LEFT];source='=If(PulsePanel.Caption="Left",1/0,'+ref.control.properties['OnTimerEnd'][1:]+')';ref.control.properties['OnTimerEnd']=source;r.analyze();r.invalidate();start(r);start(r,'RightPulse')
    advance(r,3000)
    assert r.fx.evaluate('RightPulse.Cycles')==2 and ref.control.properties['OnTimerEnd']==source
    assert any(d['member']=='Beat.OnTimerEnd' for d in r.diagnostics)


def test_start_reset_cycle_quarantines_only_affected_timer(r):
    ref=r.refs[LEFT];ref.control.properties['OnTimerStart']='=If(PulsePanel.Caption="Left",Reset(Beat),Set(starts,starts+1))';r.invalidate()
    start(r);start(r,'RightPulse');advance(r,1500)
    assert r.timer_states[LEFT].suspended and r.fx.evaluate('RightPulse.Cycles')==1
    assert any(d['kind']=='Cycle' for d in r.diagnostics)


def test_clock_crosses_midnight_and_restart_restores_configured_epoch(r):
    r.environment['clock']='2026-01-01T23:59:59+00:00';r.restart();advance(r,1500)
    assert r.fx.evaluate('Day(Today())')==2 and r.fx.evaluate('Second(Now())')==0
    assert r.environment['clock']=='2026-01-01T23:59:59+00:00'
    r.restart();assert r.fx.evaluate('Day(Today())')==1 and r.timer_elapsed==0


def test_fractional_durations_and_maximum_duration_are_valid(r):
    ref=r.global_refs['BgTimer'];ref.control.properties.update(Duration='=0.5',Start='=true',Repeat='=true');r.invalidate();r.drain_events()
    advance(r,1.25);assert r.fx.evaluate('bgEnds')==2 and ref.property('Value')==0.25
    ref.control.properties.update(Duration='=86400000',Start='=false');r.invalidate();r.drain_events()
    assert ref.property('Duration')==MAX_MS and not r.diagnostics


def test_duration_change_clamps_output_and_immediately_finishes_shorter_cycle(r):
    start(r);advance(r,700);r.global_refs['LeftPulse'].control.properties['Period']='=250';r.invalidate();r.drain_events()
    assert r.refs[LEFT].property('Value')==250
    advance(r,0);assert r.fx.evaluate('LeftPulse.Cycles')==1

@pytest.fixture
def client(tmp_path):
    from powerapps_sim.web import create_app
    p=timers_project(tmp_path/'web-timer');app=create_app(tmp_path/'workspace',p.root)
    yield app.test_client(),app.extensions['workspace']
    app.extensions['workspace'].runtime.close()


def test_http_clock_control_token_pause_and_authoritative_advance(client):
    c,w=client;token=w.runtime.timer_token;headers={'X-Emulator-Request':'1'}
    start(w.runtime)
    assert c.post('/api/time/advance',json={'token':token,'milliseconds':1000}).status_code==403
    paused=c.post('/api/time/control',json={'token':token,'playing':False},headers=headers)
    assert paused.status_code==200 and paused.json['timers']['playing'] is False
    step=c.post('/api/time/advance',json={'token':token,'milliseconds':1000},headers=headers)
    assert step.status_code==200 and w.runtime.fx.evaluate('LeftPulse.Cycles')==1
    assert c.post('/api/time/pulse',json={'token':'old','playing':True},headers=headers).json=={'stale':True}
    assert c.post('/api/time/advance',json={'token':'old','milliseconds':1000},headers=headers).json=={'stale':True}
    assert c.post('/api/time/control',json={'token':'old','playing':True},headers=headers).json=={'stale':True}
    assert w.runtime.timer_elapsed==1000

@pytest.mark.parametrize('route,payload',[('pulse',{}),('pulse',{'token':1,'playing':True}),('pulse',{'token':'x','playing':1}),('pulse',{'token':'x','playing':True,'milliseconds':1000}),('control',{'token':'x','playing':1}),('advance',{'token':True,'milliseconds':1000}),('advance',{})])
def test_http_clock_rejects_bad_payload_without_mutating_time(client,route,payload):
    c,w=client;before=deepcopy(snapshot(w.runtime))
    assert c.post('/api/time/'+route,json=payload,headers={'X-Emulator-Request':'1'}).status_code==400
    assert snapshot(w.runtime)==before

@pytest.mark.parametrize('milliseconds',[-1,True,'1000',MAX_MS+1,None])
def test_http_advance_rejects_invalid_milliseconds(client,milliseconds):
    c,w=client;reply=c.post('/api/time/advance',json={'token':w.runtime.timer_token,'milliseconds':milliseconds},headers={'X-Emulator-Request':'1'})
    assert reply.status_code==400 and w.runtime.timer_elapsed==0


def test_gallery_row_timers_start_in_scope_and_stop_when_records_are_removed(tmp_path):
    p=Project.import_yaml('''App:
  Properties:
    OnStart: =Clear(events);ClearCollect(rows,{ID:1,Duration:1000},{ID:2,Duration:1500})
Screens:
  Main:
    Children:
    - Rows:
        Control: Gallery@2.15.0
        Properties:
          Items: =rows
        Children:
        - RowTimer:
            Control: Timer@2.1.0
            Properties:
              Start: =true
              Repeat: =true
              Duration: =ThisItem.Duration
              OnTimerStart: =Collect(events,{Kind:"start",ID:ThisItem.ID,Elapsed:Self.Value})
              OnTimerEnd: =Collect(events,{Kind:"end",ID:ThisItem.ID,Elapsed:Self.Value});Remove(rows,ThisItem)
''',tmp_path/'row-timers','rows.pa.yaml')
    runtime=Runtime(p)
    try:
        runtime.restart();runtime.state()
        assert [row['ID'] for row in runtime.collections['events']]==[1,2]
        paths=[x['path'] for x in snapshot(runtime)['controls']]
        advance(runtime,3000)
        assert [row['ID'] for row in runtime.collections['events'] if row['Kind']=='end']==[1,2]
        assert not runtime.collections['rows'] and not runtime.timer_states
        with pytest.raises(ValueError,match='row no longer exists'):runtime.event(paths[0],'OnSelect')
        assert not runtime.diagnostics
    finally:runtime.close()

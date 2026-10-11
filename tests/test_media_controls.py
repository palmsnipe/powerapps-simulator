"""Playback contracts, event ordering and stale/gated browser observations."""
from copy import deepcopy
from decimal import Decimal
import pytest

from powerapps_sim.source import Project, dump_yaml
from powerapps_sim.runtime import Runtime, serial
from powerapps_sim.fx import Context
from powerapps_sim.media_controls import snapshot, output
from powerapps_sim.syntax import FxError


def make(tmp_path,family='Audio',props=None,environment=None):
    properties={'Media':'="data:audio/wav;base64,AA=="','Start':'=run','Loop':'=loop',
        'AutoPause':'=pauseAway','AutoStart':'=auto','StartTime':'=startAt',
        'OnEnd':'=Collect(history,{Event:"end",Position:Self.Time,Paused:Self.Paused})',
        'OnPause':'=Collect(history,{Event:"pause",Position:Self.Time,Paused:Self.Paused})'}
    properties.update(props or {})
    p=Project(tmp_path/'media')
    if environment:p.config['environment'].update(environment);p.save_config()
    p.update_source('Src/media.pa.yaml',dump_yaml({'App':{'Properties':{'OnStart':'=Clear(history);Set(run,false);Set(loop,false);Set(pauseAway,true);Set(auto,false);Set(startAt,0)'}},
        'Screens':{'Home':{'Children':[{'Player':{'Control':'Audio@2.1.0' if family=='Audio' else 'Video','Properties':properties}},
            {'Healthy':{'Control':'ModernText@1.0.0','Properties':{'Text':'="Healthy"'}}}]},'Away':{}}}))
    r=Runtime(p);r.restart();r.state();return r


def send(r,operation,**values):
    payload={'token':snapshot(r.refs['Home/Player'])['token'],'operation':operation,**values}
    r.event('Home/Player','OnMedia',payload)
    return payload


def behavior(r,formula):return r.fx.evaluate(formula,Context(r,behavior=True))


@pytest.mark.parametrize('family',['Audio','Video'])
@pytest.mark.parametrize('mode,language',[('float','en-CA'),('float','fr-CA'),('decimal','en-CA'),('decimal','fr-CA')])
def test_play_pause_end_outputs_and_callbacks(tmp_path,family,mode,language):
    r=make(tmp_path,family,environment={'number_mode':mode,'language':language})
    try:
        assert not r.diagnostics
        assert r.fx.evaluate('Player.Paused') and r.fx.evaluate('Player.Time')==0
        send(r,'metadata',duration=6);send(r,'play');send(r,'time',time=2.5)
        assert not r.fx.evaluate('Player.Paused') and r.fx.evaluate('Player.Duration')==6
        assert r.fx.evaluate('Player.Time')==Decimal('2.5')
        assert isinstance(r.fx.evaluate('Player.Time'),Decimal)==(mode=='decimal')
        send(r,'pause',time=3)
        assert r.collections['history']==[{'Event':'pause','Position':3,'Paused':True}]
        send(r,'pause',time=3);assert len(r.collections['history'])==1
        send(r,'play');send(r,'end',time=6);send(r,'end',time=6)
        assert r.collections['history'][-1]=={'Event':'end','Position':6,'Paused':True}
        assert len(r.collections['history'])==2 and r.fx.evaluate('Player.Paused')
        assert not snapshot(r.refs['Home/Player'])['playing']
    finally:r.close()


def test_loop_end_is_once_per_generation_and_default_starttime(tmp_path):
    r=make(tmp_path)
    try:
        behavior(r,'Set(loop,true);Set(startAt,1)');r.state()
        send(r,'metadata',duration=6);send(r,'play');old=send(r,'end',time=6)
        assert r.fx.evaluate('Player.Time')==1 and len(r.collections['history'])==1
        assert snapshot(r.refs['Home/Player'])['playing'] and snapshot(r.refs['Home/Player'])['cycles']==1
        r.event('Home/Player','OnMedia',old);assert len(r.collections['history'])==1
        send(r,'play');send(r,'end',time=6);assert len(r.collections['history'])==2
    finally:r.close()


@pytest.mark.parametrize('reset',['Reset(Player)','Set(resetFlag,true);Set(resetFlag,false)'])
def test_reset_and_restart_reject_old_events(tmp_path,reset):
    r=make(tmp_path,props={'Reset':'=resetFlag'} if 'resetFlag' in reset else None)
    try:
        if 'resetFlag' in reset:behavior(r,'Set(resetFlag,false)');r.state()
        send(r,'metadata',duration=6);send(r,'play');old=send(r,'time',time=2)
        behavior(r,reset);r.state()
        assert r.fx.evaluate('Player.Time')==0 and r.fx.evaluate('Player.Paused')
        r.event('Home/Player','OnMedia',{**old,'operation':'end','time':6})
        assert not r.collections['history'] and r.fx.evaluate('Player.Time')==0
        old={'token':snapshot(r.refs['Home/Player'])['token'],'operation':'metadata','duration':99}
        r.restart();r.state();r.event('Home/Player','OnMedia',old)
        assert r.fx.evaluate('Player.Duration')==0
    finally:r.close()


@pytest.mark.parametrize('auto_pause',[True,False])
def test_navigation_autopause_and_background_completion(tmp_path,auto_pause):
    r=make(tmp_path)
    try:
        behavior(r,'Set(pauseAway,'+str(auto_pause).lower()+')');r.state()
        send(r,'metadata',duration=6);send(r,'play');send(r,'time',time=2)
        behavior(r,'Navigate(Away)');r.state()
        if auto_pause:
            assert r.fx.evaluate('Player.Paused') and r.collections['history'][0]['Event']=='pause'
            send(r,'end',time=6);assert len(r.collections['history'])==1
        else:
            assert not r.fx.evaluate('Player.Paused') and not r.collections['history']
            send(r,'end',time=6);assert r.collections['history'][0]['Event']=='end'
    finally:r.close()


def test_formula_start_edges_and_autostart_do_not_fake_decoding(tmp_path):
    r=make(tmp_path)
    try:
        behavior(r,'Set(run,true)');r.state()
        assert snapshot(r.refs['Home/Player'])['playing'] and r.fx.evaluate('Player.Paused')
        send(r,'metadata',duration=6);send(r,'play')
        behavior(r,'Set(run,false)');r.state()
        assert r.fx.evaluate('Player.Paused') and len(r.collections['history'])==1
        behavior(r,'Set(auto,true);Navigate(Away);Navigate(Home)');r.state()
        assert snapshot(r.refs['Home/Player'])['playing']
        assert r.fx.evaluate('Player.Paused')  # Browser has not confirmed playback.
    finally:r.close()


@pytest.mark.parametrize('props',[{'Visible':'=false'},{'DisplayMode':'=DisplayMode.Disabled'},{'DisplayMode':'=DisplayMode.View'}])
def test_user_playback_is_gated(tmp_path,props):
    r=make(tmp_path,props=props)
    try:
        send(r,'metadata',duration=6);send(r,'play');send(r,'end',time=6)
        assert not r.collections['history'] and r.fx.evaluate('Player.Paused')
    finally:r.close()


def test_view_mode_allows_formula_playback_and_inspection_has_no_callbacks(tmp_path):
    r=make(tmp_path,props={'DisplayMode':'=DisplayMode.View'})
    try:
        behavior(r,'Set(run,true)');r.state();send(r,'metadata',duration=6);send(r,'play')
        assert not r.fx.evaluate('Player.Paused')
        r.preview_screen='Home';r.state();send(r,'pause',time=1)
        assert not r.collections['history'] and r.fx.evaluate('Player.Paused')
    finally:r.close()


@pytest.mark.parametrize('payload',[{}, {'operation':'metadata','duration':True}, {'operation':'metadata','duration':-1},
    {'operation':'time','time':float('inf')},{'operation':'time','time':float('nan')},
    {'operation':'pause','time':'2'},{'operation':'end','time':7},{'operation':'play','extra':1},
    {'operation':'OnEnd'},{'operation':'issue','message':5}])
def test_malformed_observations_do_not_mutate_state(tmp_path,payload):
    r=make(tmp_path)
    try:
        send(r,'metadata',duration=6);send(r,'play');before=deepcopy(snapshot(r.refs['Home/Player']))
        with pytest.raises(ValueError):r.event('Home/Player','OnMedia',{'token':before['token'],**payload})
        assert snapshot(r.refs['Home/Player'])==before and not r.collections['history']
    finally:r.close()


@pytest.mark.parametrize('name',['Time','Duration','Paused','OnStart','Volume','PlaybackRate'])
def test_output_and_unsupported_authored_properties_remain_visible(tmp_path,name):
    r=make(tmp_path,props={name:'=1'})
    try:
        assert any(d['kind']=='Unsupported' and d['member'].endswith('.'+name) for d in r.diagnostics)
        assert r.fx.evaluate('Healthy.Text')=='Healthy'
        assert name in r.project.documents['Src/media.pa.yaml']
    finally:r.close()


@pytest.mark.parametrize('source',['="https://example.test/clip.mp4"','={File:"clip.wav"}','=Color.Red'])
def test_unsupported_source_is_isolated_and_never_fetched(tmp_path,source):
    r=make(tmp_path,props={'Media':source})
    try:
        assert r.diagnostics and not snapshot(r.refs['Home/Player'])['source']
        assert r.fx.evaluate('Healthy.Text')=='Healthy'
    finally:r.close()


def test_end_callback_reset_wins_over_loop_and_reports_errors(tmp_path):
    r=make(tmp_path,props={'OnEnd':'=Reset(Self);Collect(history,{Event:"reset"});1/0'})
    try:
        behavior(r,'Set(loop,true)');r.state();send(r,'metadata',duration=6);send(r,'play');send(r,'end',time=6)
        assert r.fx.evaluate('Player.Time')==0 and not snapshot(r.refs['Home/Player'])['playing']
        assert r.collections['history']==[{'Event':'reset'}]
        assert any('division' in d['message'].lower() for d in r.diagnostics)
    finally:r.close()


def test_readonly_snapshot_does_not_settle_media_or_invoke_callbacks(tmp_path):
    r=make(tmp_path)
    try:
        send(r,'metadata',duration=6)
        from powerapps_sim.media_controls import snapshots
        before=deepcopy(snapshots(r));assert snapshots(r)==before and not r.collections['history']
    finally:r.close()

@pytest.mark.parametrize('family,version',[('Audio','99.0.0'),('Video','2.1.0')])
def test_unaudited_control_versions_do_not_execute(tmp_path,family,version):
    r=make(tmp_path,family)
    try:
        ref=r.refs['Home/Player'];ref.control.kind=family+'@'+version;r.analyze();r.invalidate();r.state()
        assert not snapshot(ref)['token'] and r.fx.evaluate('Healthy.Text')=='Healthy'
        with pytest.raises(FxError):ref.property('Time')
        assert any(d['kind']=='Unsupported' for d in r.diagnostics)
    finally:r.close()

@pytest.mark.parametrize('captions',['="https://example.test/captions.vtt"','=42'])
def test_external_captions_are_diagnosed_without_blocking_local_video(tmp_path,captions):
    r=make(tmp_path,'Video',{'ClosedCaptionsUrl':captions})
    try:
        assert any(d['member'].endswith('.ClosedCaptionsUrl') for d in r.diagnostics)
        send(r,'metadata',duration=6);send(r,'play');send(r,'end',time=6)
        assert len(r.collections['history'])==1 and r.fx.evaluate('Healthy.Text')=='Healthy'
    finally:r.close()

def test_late_play_and_time_after_pause_or_end_are_stale(tmp_path):
    r=make(tmp_path)
    try:
        send(r,'metadata',duration=6);old=send(r,'play');send(r,'pause',time=1)
        r.event('Home/Player','OnMedia',old)
        r.event('Home/Player','OnMedia',{**old,'operation':'time','time':5})
        assert r.fx.evaluate('Player.Paused') and r.fx.evaluate('Player.Time')==1 and len(r.collections['history'])==1
        old=send(r,'play');send(r,'end',time=6);r.event('Home/Player','OnMedia',old)
        assert r.fx.evaluate('Player.Paused') and r.fx.evaluate('Player.Time')==6 and len(r.collections['history'])==2
    finally:r.close()

"""Canvas media contracts and validated browser playback observations.

Python owns playback intent and executes callbacks. The browser decodes clips
and reports position/duration in seconds; headless workflows use the same gate.
"""
from dataclasses import dataclass
from decimal import Decimal
import math
from uuid import uuid4

from .syntax import FxError

FAMILIES = frozenset(('Audio', 'Video'))
# Audio 2.1.0 is present in Microsoft's shipped Chess sample. Unversioned
# clipboard controls use the documented common contract. Other versions stay
# visible as unsupported until their templates are audited.
VERSIONS = {'Audio': {'', '2.1.0'}, 'Video': {''}}
OUTPUTS = frozenset(('Time', 'Duration', 'Paused'))
BOOLS = frozenset(('Start', 'AutoStart', 'AutoPause', 'Loop', 'ShowControls', 'Reset'))
TYPES = {**{n:'Boolean' for n in BOOLS}, 'Media':'Media', 'StartTime':'Number',
    'Time':'Number', 'Duration':'Number', 'Paused':'Boolean', 'ClosedCaptionsUrl':'Text'}
DEFAULTS = {'Media':'=Blank()', 'Start':'=false', 'AutoStart':'=false', 'AutoPause':'=true',
    'Loop':'=false', 'ShowControls':'=true', 'Reset':'=false', 'StartTime':'=0',
    'OnEnd':'=Blank()', 'OnPause':'=Blank()', 'Image':'=Blank()', 'ImagePosition':'=ImagePosition.Fit',
    'TabIndex':'=0', 'Width':'=320', 'Height':'=64'}


@dataclass
class Playback:
    token: str
    source: str = ''
    source_key: str = ''
    time: float = 0
    duration: float = 0
    metadata: bool = False
    paused: bool = True
    playing: bool = False
    start: bool | None = None
    override: bool | None = None
    start_time: float = 0
    active: bool = False
    blocked: bool = False
    cycles: int = 0


def init(runtime):
    runtime.media_states = {}
    runtime.media_settling = False


def current(ref):
    return ref.runtime.media_states.get(ref.path)


def output(ref, name):
    state = current(ref)
    if name == 'Paused': return state.paused if state else True
    value = getattr(state, name.lower()) if state else 0
    return Decimal(str(value)) if ref.runtime.fx.number_mode == 'decimal' else value


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(float(value)) or value < 0:
        raise ValueError(label+' must be a finite nonnegative Number')
    return float(value)


def validate(name, value):
    if name in BOOLS and value is not None and not isinstance(value, bool):
        raise FxError(f'Media control {name} requires Boolean', 'Type')
    if name == 'StartTime' and value is not None:
        try:number(value, 'StartTime')
        except ValueError as error:raise FxError(str(error), 'Validation') from None
    if name == 'Media' and value is not None:
        from .binding import value_type, function_compatible, FxType
        if not function_compatible(value_type(value), FxType('Media'), restrictive=False):
            raise FxError('Media requires VideoOrAudio or Text, not an Image/record', 'Type')
    if name == 'ClosedCaptionsUrl' and value:
        if not isinstance(value, str):raise FxError('ClosedCaptionsUrl requires Text', 'Type')
        if not value.startswith('/api/asset/'):
            raise FxError('External captions are unavailable offline; import a local WebVTT file', 'Unsupported')


def controls(runtime):
    # Reuse the gallery-instance eligibility rules, without treating media as
    # timers or advancing the simulation clock.
    from .galleries import keyed_rows, GalleryRecord
    result=[]
    for ref in list(runtime.refs.values()):
        if ref.family not in FAMILIES or ref.control.version not in VERSIONS[ref.family]:continue
        valid=True
        for ancestor in runtime.ancestors(ref):
            if ancestor.family!='Gallery':continue
            row=next((row for key,row in keyed_rows(ancestor) if ref.path.startswith(ancestor.path+'/row:'+key+'/')),None)
            if row is None:valid=False;break
            if isinstance(ref.item,GalleryRecord) and ref.item.gallery is ancestor and ref.item!=row:
                ref.item=row;runtime.invalidate()
        if valid:result.append(ref)
    return result


def allowed_source(value):
    source = '' if value is None else str(value)
    if not source or source.startswith('/api/asset/') or source.startswith(('data:audio/', 'data:video/')):
        return source
    raise FxError('External/unsupported media sources are unavailable in offline playback; import a local clip', 'Unsupported')


def issue(ref, message):
    if message is not None and ref.state.get('media_issue') == message:return
    ref.state['media_issue']=message
    r=ref.runtime
    r.diagnostics=[d for d in r.diagnostics if not (d.get('category')=='media' and d.get('control')==ref.path)]
    if message:
        r.diagnostic(FxError(message,'Unsupported').located(ref.path+'.Media'),ref.control.source,ref.path+'.Media',ref.raw_property('Media'),category='media')
        r.diagnostics[-1]['control']=ref.path


def reset(runtime, ref):
    runtime.media_states.pop(ref.path, None)


def settle(runtime):
    if runtime.media_settling or not runtime.started:return False
    runtime.media_settling=True;changed=False
    try:
        refs=controls(runtime);paths={ref.path for ref in refs}
        for path in set(runtime.media_states)-paths:
            del runtime.media_states[path];changed=True
        for ref in refs:
            try:
                raw=ref.property('Media');source=allowed_source(raw)
                from .reactivity import fingerprint
                key=fingerprint(raw)
                start=bool(ref.property('Start'));auto=bool(ref.property('AutoStart'))
                auto_pause=bool(ref.property('AutoPause'));start_time=number(ref.property('StartTime') or 0,'StartTime')
                shown=runtime.screen_for(ref)==runtime.active_screen
                available=all(a.property('Visible') is not False and a.property('DisplayMode')!='Disabled' for a in [ref,*runtime.ancestors(ref)])
                inspection=bool(runtime.preview_screen or runtime.preview_component)
                s=current(ref)
                if s is None or s.source_key!=key or s.source!=source:
                    s=Playback(uuid4().hex,source=source,source_key=key,time=start_time,start_time=start_time)
                    runtime.media_states[ref.path]=s;changed=True
                    issue(ref,None)
                if s.start is None or s.start!=start:
                    if s.start is not None:s.override=start;s.blocked=False
                    s.start=start
                entering=shown and not s.active
                if entering and auto:s.override=True;s.blocked=False
                if start_time!=s.start_time:
                    s.start_time=start_time;s.time=min(start_time,s.duration) if s.metadata else start_time
                    s.token=uuid4().hex;changed=True
                desired=bool(source and available and not inspection and not s.blocked and
                    (s.override if s.override is not None else start) and (shown or not auto_pause))
                if desired!=s.playing:
                    if not desired and not s.paused and not inspection:
                        s.paused=True;runtime.event_queue.append((ref,'OnPause',runtime.active_event_chain))
                    if not desired:s.paused=True
                    s.playing=desired;s.token=uuid4().hex;changed=True
                if s.active!=shown:s.active=shown;changed=True
            except FxError as error:
                if current(ref):
                    s=current(ref)
                    if s.source or s.playing:s.token=uuid4().hex;changed=True
                    s.source='';s.playing=False;s.paused=True
                runtime.observe_property_error(ref,'Media',error)
            except ValueError as error:
                runtime.observe_property_error(ref,'StartTime',FxError(str(error),'Validation'))
        if changed:runtime.invalidate()
        return changed
    finally:runtime.media_settling=False


def snapshot(ref):
    s=current(ref)
    if not s:return {'token':'','source':'','time':0,'duration':0,'paused':True,'playing':False,'cycles':0}
    return {'token':s.token,'source':s.source,'time':s.time,'duration':s.duration,
        'paused':s.paused,'playing':s.playing,'cycles':s.cycles}


def observe(ref, payload, selection=None):
    r=ref.runtime
    if selection is not None or not isinstance(payload,dict) or not {'token','operation'}<=payload.keys():
        raise ValueError('Media events require a playback token and operation')
    operation=payload['operation']
    fields={'metadata':{'duration'},'time':{'time'},'play':set(),'pause':{'time'},'end':{'time'},'issue':{'message'}}
    if not isinstance(operation,str) or operation not in fields or set(payload)!={'token','operation'}|fields[operation] or not isinstance(payload['token'],str):
        raise ValueError('Invalid media event shape')
    if operation=='metadata':value=number(payload['duration'],'Media duration')
    elif operation in ('time','pause','end'):value=number(payload['time'],'Media time')
    elif operation=='issue' and (not isinstance(payload['message'],str) or len(payload['message'])>500):raise ValueError('Invalid media issue')
    s=current(ref)
    if not s or payload['token']!=s.token:return
    if not s.source:return
    if not r.started or r.preview_screen or r.preview_component:return
    visible=all(a.property('Visible') is not False and a.property('DisplayMode')!='Disabled' for a in [ref,*r.ancestors(ref)])
    if not visible:return
    active=r.screen_for(ref)==r.active_screen
    if not active and (ref.property('AutoPause') or not s.playing):return
    if operation=='metadata':
        s.duration=value;s.metadata=True;s.time=min(s.time,value)
    elif operation=='issue':
        issue(ref,payload['message']);s.blocked=True;s.playing=False;s.paused=True
    else:
        if operation in ('time','pause','end'):
            if value>0 and not s.metadata:raise ValueError('Media metadata is required before position updates')
            if s.metadata and value>s.duration+0.05:raise ValueError('Media time exceeds clip duration')
        if operation=='play':
            if not s.source:return
            edit=all(a.property('DisplayMode')=='Edit' for a in [ref,*r.ancestors(ref)])
            if not s.playing and not edit:return
            s.override=True;s.blocked=False;s.playing=True;s.paused=False;issue(ref,None)
        elif operation=='time':s.time=min(value,s.duration) if s.metadata else value
        elif operation=='pause':
            if s.paused:return
            s.time=min(value,s.duration) if s.metadata else value
            s.override=False;s.playing=False;s.paused=True;s.token=uuid4().hex
            r.run_event(ref,'OnPause')
        else:
            if not s.metadata or not s.playing or s.paused or abs(value-s.duration)>0.05:return
            s.time=s.duration;s.paused=True;s.playing=False;s.cycles+=1;s.token=uuid4().hex
            boundary_token=s.token
            r.invalidate();r.run_event(ref,'OnEnd')
            if current(ref) is s and boundary_token==s.token:
                if ref.property('Loop'):
                    s.time=min(s.start_time,s.duration);s.playing=True;s.override=True;s.token=uuid4().hex
                else:s.override=False
    r.invalidate();r.drain_events()


def snapshots(runtime):
    return {'controls':[{'path':path,**snapshot(runtime.refs[path])}
        for path in sorted(runtime.media_states) if path in runtime.refs]}

"""Server-owned Canvas timers and a deterministic simulation clock.

Templates 2.0.0/2.0.1/2.1.0 are present in Microsoft's shipped apps. Native
callback timing and simultaneous deadlines still need a Studio comparison.
"""
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import math,time
from .syntax import FxError

VERSIONS={'2.0.0','2.0.1','2.1.0'}
DEFAULTS={'Duration':'=60000','Start':'=false','Repeat':'=false','Reset':'=false',
 'AutoStart':'=false','AutoPause':'=true','OnTimerStart':'=false','OnTimerEnd':'=false',
 'Text':'="Start / pause"','Fill':'=RGBA(15,108,189,1)','Color':'=Color.White','Width':'=160','Height':'=40','TabIndex':'=0'}
TYPES={'Duration':'Number','Value':'Number',**{n:'Boolean' for n in ('Start','Reset','Repeat','AutoStart','AutoPause')}}
MAX_MS=86_400_000

@dataclass
class Timer:
    value:float=0
    duration:float=60000
    running:bool=False
    completed:bool=False
    start:bool|None=None
    override:bool|None=None
    active:bool=False
    cycles:int=0
    generation:int=0
    suspended:bool=False


def validate(name,value):
    if name in ('Start','Reset','Repeat','AutoStart','AutoPause'):
        if not isinstance(value,bool):raise FxError(f'Timer.{name} requires a Boolean','Type')
    if name=='Duration':
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):
            raise FxError('Timer.Duration requires a finite Number','Type')
        if not 0<=value<=MAX_MS:raise FxError('Timer.Duration must be between zero and 86400000 milliseconds','Validation')


def number(value,label):
    if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)) or not 0<=value<=MAX_MS:
        raise ValueError(label+' must be a finite number between zero and 86400000 milliseconds')
    return float(value)


def init(runtime):
    runtime.timer_states={};runtime.timer_elapsed=0.0;runtime.timer_settling=False
    runtime.timer_advancing=False;runtime.timer_epoch=datetime.now(timezone.utc)
    runtime.timer_wall=None;runtime.timer_live=False;runtime.timer_playing=True
    # Browser events/pulses from a prior runtime cannot advance a replacement.
    from uuid import uuid4
    runtime.timer_token=uuid4().hex


def refs(runtime):return [r for r in runtime.refs.values() if r.family=='Timer' and r.control.version in VERSIONS]



def active_controls(runtime):
    from .galleries import keyed_rows,GalleryRecord
    result=[]
    for ref in refs(runtime):
        valid=True
        for ancestor in runtime.ancestors(ref):
            if ancestor.family!='Gallery':continue
            rows=keyed_rows(ancestor)
            found=next((row for key,row in rows if ref.path.startswith(ancestor.path+'/row:'+key+'/')),None)
            if found is None:valid=False;break
            if isinstance(ref.item,GalleryRecord) and ref.item.gallery is ancestor and ref.item!=found:
                ref.item=found;runtime.invalidate()
        if valid:result.append(ref)
    return result


def value(ref):
    v=ref.runtime.timer_states.get(ref.path,Timer()).value
    return Decimal(str(v)) if ref.runtime.environment.get('number_mode')=='decimal' else v


def reset(runtime,ref):
    old=runtime.timer_states.get(ref.path)
    runtime.timer_states[ref.path]=Timer(generation=(old.generation+1 if old else 1))


def clock(runtime):
    from .fx import date_value
    base=date_value(runtime.environment['clock']) if runtime.environment.get('clock') else runtime.timer_epoch
    return base+timedelta(milliseconds=runtime.timer_elapsed)


def available(runtime):return runtime.started and not (runtime.preview_screen or runtime.preview_component)


def settle(runtime):
    if runtime.timer_settling or not available(runtime):return False
    runtime.timer_settling=True;any_change=False;starts={}
    try:
        for _ in range(100):
            changed=False;controls=active_controls(runtime);paths={r.path for r in controls}
            runtime.timer_states={p:s for p,s in runtime.timer_states.items() if p in paths}
            for ref in controls:
                s=runtime.timer_states.setdefault(ref.path,Timer())
                try:
                    duration=float(ref.property('Duration'));start=ref.property('Start')
                    auto=ref.property('AutoStart');auto_pause=ref.property('AutoPause')
                    active=runtime.screen_for(ref)==runtime.active_screen
                    if s.start is None or s.start!=start:
                        if s.start is not None:s.override=start
                        s.start=start
                        if start:s.completed=False
                    if active and not s.active and auto:
                        if s.completed:s.value=0
                        s.override=True;s.completed=False
                    s.active=active
                    if s.duration!=duration:
                        s.duration=duration;s.value=min(s.value,duration);runtime.invalidate()
                    enabled=s.override if s.override is not None else start
                    running=bool(enabled and not s.completed and not s.suspended and (active or not auto_pause))
                    if running!=s.running:
                        s.running=running;changed=True;any_change=True;runtime.invalidate()
                        if running:
                            starts[ref.path]=starts.get(ref.path,0)+1
                            runtime.run_event(ref,'OnTimerStart')
                except FxError as error:
                    s.running=False
                    runtime.diagnostic(error,ref.control.source,ref.name+'.Duration')
            if not changed:return any_change
        for p,count in starts.items():
            if count>=100:
                s=runtime.timer_states[p];s.running=False;s.suspended=True
        runtime.diagnostic(FxError('Timer start/reset loop exceeded 100 events','Cycle'))
        return any_change
    finally:runtime.timer_settling=False


def toggle(runtime,ref):
    if ref not in active_controls(runtime):raise ValueError('Timer row no longer exists')
    settle(runtime);s=runtime.timer_states.setdefault(ref.path,Timer())
    if s.completed:s.value=0;s.completed=False
    s.override=not s.running;runtime.invalidate()
    runtime.run_event(ref,'OnSelect');runtime.drain_events()


def advance(runtime,milliseconds):
    delta=number(milliseconds,'Time advance')
    if runtime.timer_advancing:raise FxError('Cannot advance simulation time recursively','Cycle')
    if not available(runtime):return {'advanced_ms':0,'elapsed_ms':runtime.timer_elapsed,'events':0}
    runtime.timer_advancing=True;begin=runtime.timer_elapsed;target=begin+delta;events=0
    try:
        runtime.drain_events()
        while True:
            settle(runtime)
            active=[(r,runtime.timer_states[r.path]) for r in refs(runtime) if runtime.timer_states.get(r.path,Timer()).running]
            remaining=target-runtime.timer_elapsed
            if not active:
                step=remaining
            else:step=min(remaining,min(max(0,s.duration-s.value) for _,s in active))
            if step>0:
                runtime.timer_elapsed+=step
                for _,s in active:s.value=min(s.duration,s.value+step)
                runtime.store.clock=clock(runtime).isoformat()
                runtime.invalidate()
            due=[(r,s,s.generation) for r,s in active if s.running and s.value>=s.duration]
            if not due:break
            for ref,s,generation in due:
                if runtime.timer_states.get(ref.path) is not s or s.generation!=generation or not s.running:continue
                if events>=1000:
                    if s.duration==0:s.running=False;s.suspended=True
                    raise FxError('Timer replay exceeded 1000 end events; reduce the time advance','Cycle')
                s.running=False;s.completed=True;s.cycles+=1;events+=1;runtime.invalidate()
                runtime.trace_event('timer_end',path=ref.path,elapsed_ms=runtime.timer_elapsed,value=s.value)
                runtime.run_event(ref,'OnTimerEnd');runtime.drain_events()
                if runtime.timer_states.get(ref.path) is s and s.generation==generation and s.completed:
                    if ref.property('Repeat'):
                        s.value=0;s.completed=False;runtime.invalidate()
                settle(runtime)
            if runtime.timer_elapsed>=target:
                # A zero-duration repeating timer must be diagnosed, not spin forever.
                if not any(s.running and s.duration==0 for s in runtime.timer_states.values()):break
        return {'advanced_ms':runtime.timer_elapsed-begin,'elapsed_ms':runtime.timer_elapsed,'events':events}
    except FxError as error:
        runtime.diagnostic(error,member='Timers');raise
    finally:runtime.timer_advancing=False


def snapshot(runtime):
    return {'token':runtime.timer_token,'elapsed_ms':runtime.timer_elapsed,'playing':runtime.timer_playing,
     'controls':[{'path':p,'value':s.value,'duration':s.duration,'running':s.running,'completed':s.completed,'cycles':s.cycles,'suspended':s.suspended} for p,s in runtime.timer_states.items()]}


def pulse(runtime,token,playing,now=None):
    if not isinstance(token,str) or not isinstance(playing,bool):raise ValueError('Timer pulse needs a token and Boolean play state')
    if token!=runtime.timer_token:return False
    now=time.monotonic() if now is None else now
    prior=runtime.timer_wall;was_live=runtime.timer_live
    runtime.timer_wall=now;runtime.timer_live=playing and runtime.timer_playing and available(runtime)
    if prior is not None and was_live and runtime.timer_live:
        advance(runtime,min(MAX_MS,max(0,(now-prior)*1000)))
    return True

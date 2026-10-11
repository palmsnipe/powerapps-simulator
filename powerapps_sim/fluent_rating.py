"""Fluent V8's bound Value contract, recovered from a first-party archive.

Server-owned interaction, with React v8 star selection/keyboard conventions.
Native wrapper event timing and theme colors remain approximations.
"""
from functools import lru_cache
from pathlib import Path
from decimal import Decimal
import json, math
from .syntax import FxError
from .icons import glyph

FAMILY='FluentV8/Rating'
VERSION='1.5.1'

@lru_cache(maxsize=1)
def catalog():return json.loads((Path(__file__).parent/'static/fluent-rating.json').read_text())
DEFAULTS=catalog()['defaults']
TYPES=catalog()['types']
LAYOUT={'LayoutMinWidth','LayoutMinHeight','LayoutMaxWidth','LayoutMaxHeight','FillPortions','AlignInContainer'}
PROPERTIES=set(TYPES)|LAYOUT|{'OnChange','OnSelect','Name'}

def errors(control):
    if control.version!=VERSION:return {'Version':f'Unsupported {control.kind} version'}
    return {name:f'{control.kind} has no authored {name} property' for name in control.properties if name not in PROPERTIES or name=='Name'}

def number(raw,name):
    if isinstance(raw,bool) or not isinstance(raw,(int,float,Decimal)) or not math.isfinite(float(raw)):
        raise FxError(f'{FAMILY}.{name} requires a finite Number','Type')
    return raw

def validate(name,raw):
    typ=TYPES.get(name)
    if raw is None:return
    if typ=='Boolean' and not isinstance(raw,bool):raise FxError(f'{FAMILY}.{name} requires Boolean','Type')
    if typ=='Text' and not isinstance(raw,str):raise FxError(f'{FAMILY}.{name} requires Text','Type')
    if typ=='Number':
        number(raw,name)
        if name in ('Max','TabIndex') and raw!=int(raw):raise FxError(f'{FAMILY}.{name} requires an integer','Type')
        if name=='Max' and raw<1:raise FxError('Rating Max must be at least one','Validation')
        if name in ('Size','Width','Height','PaddingTop','PaddingBottom','PaddingStart','PaddingEnd') and raw<0:
            raise FxError(f'{FAMILY}.{name} cannot be negative','Validation')

def maximum(ref):
    raw=ref.property('Max');validate('Max',raw)
    if raw is None:raise FxError('Rating Max requires a Number','Type')
    return int(raw)

def value(ref,raw):
    return max(0,min(maximum(ref),number(0 if raw is None else raw,'Value')))

def behavior(runtime,ref,name):
    result=runtime.run_event(ref,name)
    if isinstance(result,FxError):runtime.diagnostic(result,ref.control.source,ref.name+'.'+name,ref.raw_property(name))

def event(runtime,ref,name,data,selection):
    if selection is not None or name not in ('OnChange','OnSelect'):raise ValueError('Unsupported Fluent V8 rating event')
    if name=='OnSelect' and data is None:
        behavior(runtime,ref,name);runtime.drain_events();return
    if not isinstance(data,dict) or set(data) not in ({'value','reset_token'},{'key','reset_token'}) or not isinstance(data['reset_token'],str):
        raise ValueError('Rating changes require a value and instance token')
    ref.sync_default('Value')
    if data['reset_token']!=runtime.scalar_token(ref):return
    max_value=maximum(ref);previous=ref.property('Value')
    if 'key' in data:
        if ref.property('AcceptsFocus') is False:return
        key=data['key'];current=max(1,math.ceil(previous))
        if key in ('ArrowRight','ArrowDown'):raw=min(max_value,current+1)
        elif key in ('ArrowLeft','ArrowUp'):raw=max(1,current-1)
        elif key in ('Home','PageUp'):raw=1
        elif key in ('End','PageDown'):raw=max_value
        else:raise ValueError('Unsupported rating keyboard operation')
    else:raw=number(data['value'],'Value')
    if raw!=int(raw) or not 1<=raw<=max_value:raise ValueError('Rating selection must be an integer from one to Max')
    # React v8 compares the selected star with ceil(rating): selecting the
    # currently indicated star leaves a fractional bound value unchanged.
    if math.ceil(previous)!=raw:
        baseline=value(ref,runtime.input_baselines[ref.path])
        ref.state.update(Value=raw,dirty=raw!=baseline)
        runtime.invalidate();behavior(runtime,ref,'OnChange')
    if name=='OnSelect':behavior(runtime,ref,'OnSelect')
    runtime.drain_events()

def render(ref,node):
    max_value=maximum(ref)
    if max_value>1000:raise FxError('Rating rendering above 1000 stars is unsupported','Unsupported')
    node['value']=float(ref.property('Value'))
    node['fluent_rating']={'max':max_value,'glyph':glyph('Star','Filled'),'bound_value':True}
    node['input_reset']=ref.runtime.scalar_token(ref)

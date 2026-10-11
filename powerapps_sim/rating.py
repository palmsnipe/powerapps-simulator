"""Documented ModernRating contract; interaction remains authoritative in Python."""
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING, localcontext
import math
from .syntax import FxError
from .enum_fx import consume
from .icons import glyph

DEFAULTS={'Default':'=3','Max':'=5','Step':'=RatingStep.Full','Icon':'="Star"',
          'Color':'=RGBA(15,108,189,1)','Width':'=200','Height':'=40'}
TYPES={'Default':'Number','Value':'Number','Max':'Number','Icon':'Text','Color':'Color'}

def number(value,name):
    if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):
        raise FxError(f'Rating {name} requires a finite Number','Type')
    return value

def validate(ref,name,value):
    if name=='Max':
        number(value,name)
        if value<=1 or value!=int(value):raise FxError('Rating Max requires a whole number greater than one','Validation')
    if name=='Default' and value is not None:number(value,name)
    if name=='Step' and consume(value,'RatingStep') not in ('Full','Half'):
        raise FxError('Rating Step requires RatingStep.Full or RatingStep.Half','Type')
    if name=='Icon':glyph(value,'Filled')

def contract(ref):
    maximum=ref.property('Max')
    return int(maximum),.5 if consume(ref.property('Step'),'RatingStep')=='Half' else 1

def value(ref,raw):
    maximum,_=contract(ref)
    return max(0,min(maximum,number(0 if raw is None else raw,'Value')))

def event(runtime,ref,name,data,selection):
    if name!='OnChange' or selection is not None or not isinstance(data,dict) or set(data) not in ({'value','reset_token'},{'key','reset_token'}) or not isinstance(data['reset_token'],str):
        raise ValueError('Rating changes require a numeric value and instance token')
    ref.sync_default('Value')
    if data['reset_token']!=runtime.scalar_token(ref):return
    maximum,step=contract(ref)
    previous=ref.property('Value')
    if 'key' in data:
        key=data['key']
        if not isinstance(key,str) or key not in ('Home','End','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'):
            raise ValueError('Unsupported rating keyboard operation')
        if key in ('Home','End'):raw=0 if key=='Home' else maximum
        else:
            direction=1 if key in ('ArrowRight','ArrowUp') else -1
            with localcontext() as ctx:
                ctx.prec=400
                unit=Decimal(str(step));position=Decimal(str(previous))/unit
                raw=max(0,min(maximum,(position.to_integral_value(rounding=ROUND_FLOOR if direction>0 else ROUND_CEILING)+direction)*unit))
    else:raw=number(data['value'],'Value')
    if not 0<=raw<=maximum or Decimal(str(raw))%Decimal(str(step)):
        raise ValueError('Rating value must be within Max and follow Step')
    if previous==raw:return
    baseline=value(ref,runtime.input_baselines[ref.path])
    ref.state.update(Value=raw,dirty=raw!=baseline)
    runtime.invalidate()
    result=runtime.run_event(ref,'OnChange')
    if isinstance(result,FxError):runtime.diagnostic(result,ref.control.source,ref.name+'.OnChange',ref.raw_property('OnChange'))
    runtime.drain_events()

def render(ref,node):
    maximum,step=contract(ref)
    # Avoid allocating an unbounded browser tree. Source and formulas survive.
    if maximum>1000:raise FxError('Rating rendering above 1000 icons is unsupported','Unsupported')
    node['value']=float(ref.property('Value'))
    node['rating']={'max':maximum,'step':step,'glyph':glyph(ref.property('Icon'),'Filled')}
    node['input_reset']=ref.runtime.scalar_token(ref)

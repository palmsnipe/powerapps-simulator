"""Real-valued Power Fx math; domain failures remain catchable language errors."""
from decimal import Decimal, ROUND_FLOOR, ROUND_DOWN
import math

from .numeric import decimal_value, float_value
from .syntax import FxError

INTEGER_FUNCTIONS = frozenset(('Int','Trunc'))
FLOAT_FUNCTIONS = frozenset(('Sqrt','Exp','Ln','Log','Power','Sin','Cos','Tan','Cot',
    'Asin','Acos','Atan','Acot','Degrees','Radians'))
SCALAR_FLOAT_FUNCTIONS = frozenset(('Pi','Atan2'))
MATH_FUNCTIONS = INTEGER_FUNCTIONS | FLOAT_FUNCTIONS | SCALAR_FLOAT_FUNCTIONS


def evaluate(name, values):
    if name=='Pi':return math.pi
    if name in INTEGER_FUNCTIONS:
        value=values[0]
        if isinstance(value,Decimal):
            return decimal_value(value.to_integral_value(rounding=ROUND_FLOOR if name=='Int' else ROUND_DOWN))
        return float_value(math.floor(value) if name=='Int' else math.trunc(value))
    args=[float_value(value) for value in values]
    value=args[0]
    try:
        if name=='Power':
            exponent=args[1]
            if value==0 and exponent<0:raise FxError('Power of zero with a negative exponent','Div0')
            result=math.pow(value,exponent)
        elif name=='Log':
            base=args[1] if len(args)>1 else 10.0
            if base==1:raise FxError('Log base cannot equal one','Div0')
            if base<=0 or value<=0:raise FxError('Log requires positive number and base','Numeric')
            result=math.log(value)/math.log(base)
        elif name=='Cot':
            tangent=math.tan(value)
            if tangent==0:raise FxError('Cot is undefined where Tan equals zero','Div0')
            result=1/tangent
        elif name=='Acot':result=math.pi/2-math.atan(value)
        elif name=='Atan2':
            if value==0 and args[1]==0:raise FxError('Atan2 requires a nonzero coordinate','Div0')
            # Canvas takes X, Y; Python takes Y, X.
            result=math.atan2(args[1],value)
        else:
            function={'Sqrt':math.sqrt,'Exp':math.exp,'Ln':math.log,'Sin':math.sin,
                'Cos':math.cos,'Tan':math.tan,'Asin':math.asin,'Acos':math.acos,
                'Atan':math.atan,'Degrees':lambda x:x*(180/math.pi),
                'Radians':lambda x:x*(math.pi/180)}[name]
            result=function(value)
        return float_value(result)
    except (ValueError,OverflowError):
        raise FxError(f'{name} result is outside the real finite numeric range','Numeric') from None

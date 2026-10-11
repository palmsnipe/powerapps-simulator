"""Volatile numeric and table functions; the runtime owns data-flow lifetime."""
from decimal import Decimal, localcontext
import math
from .numeric import decimal_value, float_value
from .syntax import FxError


def evaluate(name,values,fx):
    from .fx import observe,table
    if name=='Rand':
        # Rand is Float even in the Decimal host (pinned RandFunction).
        return fx.host.reactive.rng().random()
    if name=='Shuffle':
        value=observe(values[0])
        if value is None:
            fx.host.reactive.volatile()
            return None
        rows=list(table(value))
        fx.host.reactive.rng().shuffle(rows)
        return rows
    bottom,top=fx.numeric_arguments(values)
    if bottom>top:raise FxError('Lower value is greater than upper value','Numeric')
    low,high=math.ceil(bottom),math.floor(top)
    rng=fx.host.reactive.rng()
    # Excel/Power Fx returns Ceiling(bottom) if no integer fits between bounds.
    high=max(low,high)
    if isinstance(bottom,Decimal) and isinstance(top,Decimal):
        # Python's integer draw avoids overflowing a valid Decimal interval.
        # The seed is an simulator replay aid, not a Microsoft PRNG sequence.
        with localcontext() as context:
            context.prec=100
            return decimal_value(rng.randrange(low,high+1))
    return float_value(rng.randrange(low,high+1))

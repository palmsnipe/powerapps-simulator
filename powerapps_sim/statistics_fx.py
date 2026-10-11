"""Population statistics using the pinned Power Fx interpreter's Float algorithm."""
import math

from .numeric import float_value
from .syntax import FxError

FUNCTIONS = frozenset(('StdevP', 'VarP'))


def population(name, values):
    """Welford accumulation avoids cancellation from subtracting squared means."""
    count, mean, second_moment, overflow = 0, 0.0, 0.0, None
    for value in values:
        if value is None:
            continue
        value = float_value(value)
        count += 1
        if overflow is not None:
            continue
        delta = value - mean
        mean += delta / count
        second_moment += delta * (value - mean)
        # Power Fx numeric values must remain finite, including intermediates.
        if not math.isfinite(mean) or not math.isfinite(second_moment):
            # A later projection error takes precedence over an accumulated
            # nonfinite result in the pinned table interpreter.
            overflow = FxError(f'{name} accumulation exceeds the Float range', 'Numeric')
    if overflow is not None:
        raise overflow
    if not count:
        raise FxError(f'{name} requires at least one nonblank value', 'Div0')
    variance = second_moment / count
    try:
        return float_value(math.sqrt(variance) if name == 'StdevP' else variance)
    except ValueError:
        raise FxError(f'{name} result is outside the real numeric range', 'Numeric') from None


def evaluate(fx, name, args, ctx):
    # Import at call time: fx registers this module's function catalog.
    from .fx import capture, table
    from .store import DataSource
    source = fx.capture(args[0], ctx)
    typ = fx.node_types.get(id(args[0]))
    is_table = typ and typ.kind == 'Table' or isinstance(source, (list, DataSource))
    if is_table:
        if len(args) != 2:
            raise FxError(f'{name} table overload requires a table and one formula', 'Validation')
        if source is None:
            return None
        def values():
            for index,row in enumerate(fx.query_rows(args[0],source,ctx)):
                # An error row belongs to the record scope: the projection
                # can contain it with IfError before consuming its value.
                value = fx.query_row(args[0],row,args[1],ctx,index)
                yield None if value is None else fx.numeric_argument(value, 'float')
        # A table aggregate stops at the first consumed row/formula error.
        return population(name, values())
    values = [source] + [fx.capture(arg, ctx) for arg in args[1:]]
    converted = [capture(lambda: None if value is None else fx.numeric_argument(value, 'float')) for value in values]
    errors = [value for value in converted if isinstance(value, FxError)]
    if errors:
        raise FxError.combine(errors)
    return population(name, converted)

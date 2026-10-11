"""Scoped Sum/Average/Min/Max with pinned Power Fx aggregate semantics."""
from decimal import Decimal

from .numeric import calculate, float_value
from .syntax import FxError
from .temporal import TEMPORAL_KINDS, Temporal

FUNCTIONS = frozenset(('Sum', 'Average', 'Min', 'Max'))


def result_kind(name, input_kind, number_mode):
    # V1 Min/Max use the first scalar argument's type (or table projection).
    # Statistical numeric functions also choose their host from that argument.
    if name in ('Min', 'Max') and input_kind in TEMPORAL_KINDS:
        return input_kind
    return input_kind if input_kind in ('Number', 'Decimal') else 'Decimal' if number_mode == 'decimal' else 'Number'


def convert(fx, value, kind):
    from .fx import observe
    observe(value)
    if value is None:
        return None
    if kind in TEMPORAL_KINDS:
        original = value
        value = fx.temporal(value, kind)
        if value is None:
            return None
        instant = value.value
        if kind == 'Date' and not (isinstance(original, Temporal) and original.kind == 'Date'):
            instant = instant.replace(hour=0, minute=0, second=0, microsecond=0)
        # Date/DateTime-to-Time retains a duration from the epoch, including
        # its days. Comparing only clock parts changes negative durations.
        return Temporal(kind, instant)
    result = fx.numeric_argument(value, 'decimal' if kind == 'Decimal' else 'float')
    return float_value(result) if result is not None and kind == 'Number' else result


def aggregate(name, values, kind):
    count, total, best, overflow = 0, Decimal(0) if kind == 'Decimal' else 0.0, None, None
    for value in values:
        if value is None:
            continue
        count += 1
        if name in ('Min', 'Max'):
            key = value.value if isinstance(value, Temporal) else value
            prior = best.value if isinstance(best, Temporal) else best
            if best is None or (key < prior if name == 'Min' else key > prior):
                best = value
        elif overflow is None:
            try:
                total = calculate('+', total, value)
            except FxError as error:
                if error.kind != 'Numeric':
                    raise
                # The reference accumulator reports overflow after iteration;
                # a later consumed row error takes precedence.
                overflow = error
    if overflow is not None:
        raise overflow
    if not count:
        if name == 'Average':
            raise FxError('Average requires at least one nonblank value', 'Div0')
        return None
    if name in ('Min', 'Max'):
        return best
    return total if name == 'Sum' else calculate('/', total, Decimal(count) if kind == 'Decimal' else count)


def evaluate(fx, name, args, ctx):
    from .fx import capture, table
    from .store import DataSource
    source = fx.capture(args[0], ctx)
    typ = fx.node_types.get(id(args[0]))
    is_table = typ and typ.kind == 'Table' or isinstance(source, (list, DataSource))
    if is_table and len(args) != 2:
        raise FxError(f'{name} table overload requires a table and one formula', 'Validation')
    projection = fx.node_types.get(id(args[1])) if is_table else typ
    kind = result_kind(name, projection.kind if projection else None, fx.number_mode)
    if is_table:
        # A typed Blank table differs from a table containing zero rows.
        if source is None:
            return None
        def values():
            for index,row in enumerate(fx.query_rows(args[0],source,ctx)):
                # Formula-level IfError can handle an error row in its scope.
                yield convert(fx, fx.query_row(args[0],row,args[1],ctx,index), kind)
        return aggregate(name, values(), kind)
    values = [source] + [fx.capture(arg, ctx) for arg in args[1:]]
    converted = [capture(lambda: convert(fx, value, kind)) for value in values]
    errors = [value for value in converted if isinstance(value, FxError)]
    if errors:
        raise FxError.combine(errors)
    return aggregate(name, converted, kind)

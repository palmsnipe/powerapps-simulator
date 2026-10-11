"""Bounded base-ten arithmetic and explicit Float promotion for Power Fx hosts.

Decimal follows the .NET decimal coefficient/scale envelope. Host arithmetic
never uses Python's process-wide Decimal context. Wire values retain precision.
"""
from decimal import Decimal, DecimalException, localcontext, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_DOWN, ROUND_UP
import math

from .syntax import FxError

DECIMAL_MAX = Decimal('79228162514264337593543950335')
NUMBER_MODES = {'float', 'decimal'}
NUMBERS = (int, float, Decimal)


def decimal_value(value):
    try:
        with localcontext() as context:
            context.prec = 100
            if isinstance(value, float):
                # .NET's conversion from double retains up to 15 significant
                # decimal digits. Text-to-Decimal never goes through Float.
                value = format(value, '.15g')
            value = Decimal(value)
            if not value.is_finite() or value.copy_abs() > DECIMAL_MAX:
                raise FxError('Number is outside the supported Decimal range', 'Numeric')
            if not value or value.adjusted() < -29:
                return Decimal(0)
            scale = min(28, max(0, -value.as_tuple().exponent))
            while scale >= 0:
                rounded = value.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_EVEN)
                coefficient = abs(rounded).scaleb(scale)
                if coefficient <= DECIMAL_MAX:
                    return rounded
                scale -= 1
    except (DecimalException, ValueError, TypeError):
        raise FxError('Cannot convert value to Decimal', 'InvalidArgument') from None
    raise FxError('Number is outside the supported Decimal range', 'Numeric')


def float_value(value):
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        raise FxError('Cannot convert value to Float', 'InvalidArgument') from None
    if not math.isfinite(result):
        raise FxError('Number is outside the supported Float range', 'Numeric')
    return result


def decimal_text(value):
    result = format(value, 'f')
    if '.' in result:
        result = result.rstrip('0').rstrip('.')
    return '0' if value == 0 else result


def promote(a, b):
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return a, b
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        return float_value(a), float_value(b)
    return a, b


def calculate(operator, a, b):
    a, b = promote(a, b)
    try:
        with localcontext() as context:
            context.prec = 100
            if operator == '^':
                from .power_math import evaluate
                return evaluate('Power',[a,b])
            elif operator == 'mod':
                result = a % b
                if result and (result < 0) != (b < 0):
                    result += b
            else:
                result = {'+': lambda: a + b, '-': lambda: a - b, '*': lambda: a * b, '/': lambda: a / b}[operator]()
            if isinstance(result, Decimal):
                return decimal_value(result)
            if isinstance(result, complex):
                raise FxError('Operation has no real numeric result', 'Numeric')
            return float_value(result)
    except (ZeroDivisionError, DecimalException) as error:
        raise FxError('Division by zero' if b == 0 and operator in ('/', 'mod') else 'Decimal arithmetic failed',
                      'Div0' if b == 0 and operator in ('/', 'mod') else 'Numeric') from error
    except (OverflowError, ValueError):
        raise FxError('Operation is outside the supported numeric range', 'Numeric') from None


def rounded(value, digits, function):
    digits = int(digits)
    if isinstance(value, Decimal):
        if digits >= 28:
            return value
        if digits < -29:
            return Decimal(0)
        with localcontext() as context:
            context.prec = 100
            return decimal_value(value.quantize(Decimal(1).scaleb(-digits), rounding={
                'Round': ROUND_HALF_UP, 'RoundDown': ROUND_DOWN, 'RoundUp': ROUND_UP}[function]))
    if digits > 308:
        return value
    if digits < -308:
        return 0.0
    factor = 10.0 ** digits
    if factor == 0:
        return 0.0
    scaled = value * factor
    if not math.isfinite(scaled):
        return value
    rounding = math.floor(abs(scaled) + .5) if function == 'Round' else math.floor(abs(scaled)) if function == 'RoundDown' else math.ceil(abs(scaled))
    return float_value(math.copysign(rounding / factor, scaled))

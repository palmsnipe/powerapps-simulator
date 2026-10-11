"""Scalar calendar calculations with Power Fx start-of-week rules."""
from datetime import datetime
from calendar import monthrange
from decimal import Decimal
from math import floor

from .syntax import FxError
from .temporal import Temporal

# Python weekday indexes, independent of the output numbering convention.
WEEK_STARTS = {1: 6, 17: 6, 2: 0, 11: 0, 3: 0,
               12: 1, 13: 2, 14: 3, 15: 4, 16: 5}
CALENDAR_FUNCTIONS = {'Weekday', 'WeekNum', 'ISOWeekNum'}
MONTH_SHIFT_FUNCTIONS = {'EDate', 'EOMonth'}


def shift_months(name, instant, amount):
    """Pinned EDate/EOMonth contracts: truncate offsets and return midnight Date.

    Use an absolute month index rather than timedeltas, including at year 9999
    where computing the first day of the following month would overflow.
    """
    try:
        months = int(amount)
        if not -120000 <= months <= 120000:
            raise ValueError
        index = (instant.year - 1) * 12 + instant.month - 1 + months
        if not 0 <= index < 9999 * 12:
            raise ValueError
        year, month = index // 12 + 1, index % 12 + 1
        last_day = monthrange(year, month)[1]
        day = last_day if name == 'EOMonth' else min(instant.day, last_day)
        return Temporal('Date', datetime(year, month, day, tzinfo=instant.tzinfo))
    except (ValueError, OverflowError):
        raise FxError(f'{name}: date is outside the supported calendar range', 'InvalidArgument') from None


def calendar_number(name, instant, start=1, number_mode='float'):
    if name == 'ISOWeekNum':
        result = instant.isocalendar().week
    else:
        # Weekday floors the code; WeekNum requires an integer code.
        code = floor(start)
        if code not in WEEK_STARTS or (name == 'WeekNum' and start != code):
            raise FxError('Invalid start-of-week code', 'InvalidArgument')
        if name == 'Weekday':
            result = (instant.weekday() - WEEK_STARTS[code]) % 7 + (0 if code == 3 else 1)
        else:
            if code == 3:
                raise FxError('WeekNum does not support StartOfWeek.MondayZero', 'InvalidArgument')
            january = datetime(instant.year, 1, 1, tzinfo=instant.tzinfo).date()
            offset = (january.weekday() - WEEK_STARTS[code]) % 7
            result = ((instant.date() - january).days + offset) // 7 + 1
    return Decimal(result) if number_mode == 'decimal' else result

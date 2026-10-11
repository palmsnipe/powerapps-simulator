"""Calendar/Clock namespace functions backed by the pinned offline locale data.

These are ordinary pure Power Fx calls, not namespace records or enums.
CLDR names and time patterns approximate the Canvas host's culture information.
"""
import re

from babel.dates import get_time_format

from . import locale_data
from .locale_fx import locale
from .power_case import change_case
from .power_text import from_units, units


FUNCTIONS = frozenset({
    'Calendar.MonthsLong', 'Calendar.MonthsShort',
    'Calendar.WeekdaysLong', 'Calendar.WeekdaysShort',
    'Clock.AmPm', 'Clock.AmPmShort', 'Clock.IsClock24',
})


def evaluate(name, language):
    # Validate through the same language contract as Text/Value. Use CLDR's
    # stand-alone month names: selectors should not receive genitive names.
    tag = locale(language)['tag']
    profile = locale_data.profile(tag)
    if name.startswith('Calendar.'):
        width = 'abbreviated' if name.endswith('Short') else 'wide'
        months, days = locale_data.names(profile, width, 'stand-alone')
        values = months if '.Months' in name else [days[-1], *days[:-1]]
        return [{'Value': value} for value in values]
    # Ignore quoted literals before identifying the pattern's hour field.
    pattern = str(get_time_format('short', locale=profile['culture']))
    fields = re.sub(r"'(?:[^']|'')*'", '', pattern)
    clock24 = bool(re.search(r'[Hk]', fields))
    if name == 'Clock.IsClock24':
        return clock24
    values = [] if clock24 else [change_case(value, tag, upper=True)
                                for value in locale_data.periods(profile)]
    if name == 'Clock.AmPmShort':
        values = [from_units(units(value)[:1]) for value in values]
    return [{'Value': value} for value in values]

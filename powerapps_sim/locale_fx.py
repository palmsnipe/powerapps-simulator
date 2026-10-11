"""Deterministic Power Fx formatting using pinned offline CLDR locale data."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
import math
import re
import unicodedata
from . import locale_data

from .syntax import FxError
from .temporal import EPOCH, Temporal
from .numeric import decimal_value, float_value


MONTHS = {
    'en': 'January February March April May June July August September October November December'.split(),
    'fr': 'janvier février mars avril mai juin juillet août septembre octobre novembre décembre'.split(),
}
SHORT_MONTHS = {
    'en': 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(),
    'fr': 'janv. févr. mars avr. mai juin juil. août sept. oct. nov. déc.'.split(),
}
DAYS = {
    'en': 'Monday Tuesday Wednesday Thursday Friday Saturday Sunday'.split(),
    'fr': 'lundi mardi mercredi jeudi vendredi samedi dimanche'.split(),
}
SHORT_DAYS = {'en': 'Mon Tue Wed Thu Fri Sat Sun'.split(), 'fr': 'lun. mar. mer. jeu. ven. sam. dim.'.split()}


def locale(tag):
    tag = str(tag or 'en-US').replace('_', '-').lower()
    if not re.fullmatch(r'[a-z]{2,3}(?:-[a-z0-9]{2,8})*(?:-[a-z0-9](?:-[a-z0-9]{2,8})+)*', tag):
        raise FxError(f'Invalid language tag {tag!r}', 'BadLanguageCode')
    if tag not in ('en', 'en-us', 'en-ca', 'en-gb', 'fr', 'fr-fr', 'fr-ca'):
        return locale_data.profile(tag)
    french = tag.startswith('fr')
    return {'tag': tag, 'language': 'fr' if french else 'en', 'decimal': ',' if french else '.',
            'group': '\u00a0' if tag == 'fr-ca' else '\u202f' if french else ',',
            'currency': '$' if tag in ('en', 'en-us', 'en-ca', 'fr-ca') else '£' if tag == 'en-gb' else '€',
            'day_first': french or tag == 'en-gb'}


def parse_number(value, tag, temporal_mode='canvas-milliseconds', kind='float'):
    profile = locale(tag)
    conversion = decimal_value if kind == "decimal" else float_value
    if value is None or value == '':
        return None
    if isinstance(value, Temporal):
        return conversion(value.numeric(temporal_mode))
    if isinstance(value, (bool, int, float, Decimal)):
        return conversion(int(value) if isinstance(value, bool) else value)
    raw = str(value).strip()
    if 'culture' in profile:
        for symbol,replacement in ((profile['minus'],'-'),(profile['plus'],'+'),(profile['percent'],'%')):
            if symbol and symbol not in ('-','+','%'):raw=raw.replace(symbol,replacement)
    percent = '%' in raw
    currency = bool(profile['currency']) and profile['currency'] in raw
    if currency and percent or raw.count('%') > 1 or profile['currency'] and raw.count(profile['currency']) > 1:
        raise FxError('Invalid currency or percentage combination', 'InvalidArgument')
    accounting = raw.startswith('(') and raw.endswith(')')
    if accounting:
        raw = raw[1:-1].strip()
    if currency:
        symbol = re.escape(profile['currency'])
        match = re.match(rf'^([+-]?)\s*{symbol}\s*', raw)
        if match:
            raw = match[1] + raw[match.end():]
        elif raw.endswith(profile['currency']):
            raw = raw[:-len(profile['currency'])].strip()
    if percent:
        match = re.match(r'^([+-]?)\s*%\s*', raw)
        if match:
            raw = match[1] + raw[match.end():]
        elif raw.endswith('%'):
            raw = raw[:-1].strip()
    if raw.startswith('(') and raw.endswith(')'):
        accounting = True
        raw = raw[1:-1].strip()
    if accounting:
        if raw.startswith(('+', '-')):
            raise FxError('Accounting parentheses cannot contain a sign', 'InvalidArgument')
        raw = '-' + raw
    raw = re.sub(r'^([+-])\s+', r'\1', raw)
    if 'culture' in profile:
        group=profile['group']
        if group.isspace():raw=re.sub(r'(?<=\d)[ \u00a0\u202f](?=\d)','',raw)
        else:raw=raw.replace(group,'')
        raw=raw.replace(profile['decimal'],'.')
        raw=''.join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in raw)
    elif profile['language'] == 'fr':
        if '.' in raw:
            raise FxError(f'Cannot parse number {value!r}', 'InvalidArgument')
        raw = re.sub(r'(?<=\d)[ \u00a0\u202f](?=\d)', '', raw).replace(',', '.')
    else:
        raw = raw.replace(',', '')
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', raw):
        raise FxError(f'Cannot parse number {value!r}', 'InvalidArgument')
    if kind == 'decimal':
        # Scaling a percentage happens before Decimal range validation.
        from decimal import DecimalException
        try:
            with localcontext() as context:
                context.prec = max(100, len(raw))
                result = Decimal(raw).scaleb(-2) if percent else Decimal(raw)
            return decimal_value(result)
        except DecimalException:
            raise FxError('Number is outside the supported Decimal range', 'Numeric') from None
    return float_value(float_value(raw) / (100 if percent else 1))


def parse_datetime(value, tag):
    profile = locale(tag)
    if value is None or value == '':
        return None
    if isinstance(value, Temporal):
        return value.value
    raw = str(value).strip()
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc, microsecond=parsed.microsecond // 1000 * 1000)
    except ValueError:
        pass
    # Remove a localized weekday, then recognize numeric and named dates.
    language = profile['language']
    months,days=locale_data.names(profile) if 'culture' in profile else (MONTHS[language],DAYS[language])
    short_months,short_days=locale_data.names(profile,'abbreviated') if 'culture' in profile else (SHORT_MONTHS[language],SHORT_DAYS[language])
    weekday = '|'.join(re.escape(v) for v in sorted([*days,*short_days],key=len,reverse=True))
    raw = re.sub(rf'^(?:{weekday})(?=$|[\s,])[, ]*', '', raw, flags=re.I)
    if 'culture' in profile:raw=locale_data.normalize_time(raw,profile)
    time_match = re.search(r'(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d{1,7}))?)?\s*(AM|PM)?$', raw, re.I)
    clock = timedelta()
    if time_match:
        hour, minute, second = map(int, [time_match[1], time_match[2], time_match[3] or '0'])
        if time_match[5]:
            if not 1 <= hour <= 12:
                raise FxError('Invalid 12-hour time', 'InvalidArgument')
            hour = hour % 12 + (12 if time_match[5].upper() == 'PM' else 0)
        if hour > 23 or minute > 59 or second > 59:
            raise FxError('Invalid time', 'InvalidArgument')
        millis = int(((time_match[4] or '') + '000')[:3])
        clock = timedelta(hours=hour, minutes=minute, seconds=second, milliseconds=millis)
        raw = raw[:time_match.start()].strip().rstrip('T')
    if not raw and time_match:
        return EPOCH + clock
    if 'culture' in profile:
        parsed_fields=locale_data.parse_date_fields(raw,profile)
        if parsed_fields:
            try:return datetime(*parsed_fields,tzinfo=timezone.utc)+clock
            except (ValueError,OverflowError):raise FxError(f'Cannot parse date {value!r} in {profile["tag"]}', 'InvalidArgument') from None
    if 'culture' in profile:
        # Localized field-unit patterns (e.g. Japanese/Chinese/Korean) retain
        # explicit year/month/day ordering rather than relying on digit guesses.
        unit=re.fullmatch(r'(\d{4})\s*(?:年|년)\s*(\d{1,2})\s*(?:月|월)\s*(\d{1,2})\s*(?:日|일)',raw)
        if unit and profile['language'] in ('ja','zh','ko'):raw='/'.join(unit.groups())
        raw=raw.replace('\u200e','').replace('\u200f','')
    parts = re.split(r'[-/\s,]+', raw)
    if 'culture' in profile and not any(p.rstrip('.').casefold() in [m.rstrip('.').casefold() for m in months+short_months] for p in parts):
        parts=re.split(r'[-/.\s,]+',raw.rstrip('.'))
    try:
        if len(parts) != 3:
            raise ValueError()
        month_names = {name.rstrip('.').casefold(): i + 1 for names in (months, short_months) for i, name in enumerate(names)}
        named = next((i for i, part in enumerate(parts) if part.rstrip('.').casefold() in month_names), None)
        if named is not None:
            month = month_names[parts[named].rstrip('.').casefold()]
            day, year_text = (int(parts[1]), parts[2]) if named == 0 else (int(parts[0]), parts[2])
        elif len(parts[0]) == 4:
            year_text, month, day = parts[0], int(parts[1]), int(parts[2])
        else:
            first, second, year_text = int(parts[0]), int(parts[1]), parts[2]
            if 'culture' in profile and profile['order'].startswith('y'):
                year_text,month,day=parts[0],second,int(parts[2])
            else:day, month = (first, second) if profile['day_first'] else (second, first)
        year = int(year_text)
        if len(year_text) <= 2:
            year += 2000 if year <= 49 else 1900
        return datetime(year, month, day, tzinfo=timezone.utc) + clock
    except (ValueError, OverflowError):
        raise FxError(f'Cannot parse date {value!r} in {profile["tag"]}', 'InvalidArgument') from None


def parse_time(value, tag):
    profile=locale(tag)
    if value is None or value == '':
        return None
    if isinstance(value, Temporal):
        return Temporal('Time', EPOCH + timedelta(hours=value.value.hour, minutes=value.value.minute, seconds=value.value.second, microseconds=value.value.microsecond))
    raw = str(value).strip()
    if 'culture' in profile:raw=locale_data.normalize_time(raw,profile)
    match = re.search(r'(\d{1,3}):(\d{2})(?::(\d{2})(?:\.(\d{1,7}))?)?\s*(AM|PM)?(?:Z|[+-]\d{2}:\d{2})?$', raw, re.I)
    if not match:
        raise FxError(f'Cannot parse time {value!r}', 'InvalidArgument')
    hour, minute, second = int(match[1]), int(match[2]), int(match[3] or 0)
    if minute > 59 or second > 59 or match[5] and not 1 <= hour <= 12:
        raise FxError(f'Cannot parse time {value!r}', 'InvalidArgument')
    if match[5]:
        hour = hour % 12 + (12 if match[5].upper() == 'PM' else 0)
    millis = int(((match[4] or '') + '000')[:3])
    return Temporal('Time', EPOCH + timedelta(hours=hour % 24, minutes=minute, seconds=second, milliseconds=millis))


def make_date(year, month, day):
    """Canvas Date uses relative years below 1900 and permits overflowing parts."""
    try:
        year, month, day = int(year or 0), int(month or 0), int(day or 0)
        if year < 0 or year > 9999:
            raise ValueError()
        if year < 1900:
            year += 1900
        total = year * 12 + month - 1
        return datetime(total // 12, total % 12 + 1, 1, tzinfo=timezone.utc) + timedelta(days=day - 1)
    except (ValueError, OverflowError):
        raise FxError('Date is outside the supported calendar range', 'InvalidArgument') from None


def date_diff(start, end, unit):
    start, end = start or EPOCH, end or EPOCH
    if unit == 'Years':
        return end.year - start.year
    if unit == 'Months':
        return (end.year - start.year) * 12 + end.month - start.month
    if unit == 'Quarters':
        return (end.year - start.year) * 4 + (end.month - 1) // 3 - (start.month - 1) // 3
    # Power Fx counts unit boundaries, not a truncated elapsed duration.
    def truncate(value):
        if unit == 'Days':
            return value.replace(hour=0, minute=0, second=0, microsecond=0)
        if unit == 'Hours':
            return value.replace(minute=0, second=0, microsecond=0)
        if unit == 'Minutes':
            return value.replace(second=0, microsecond=0)
        if unit == 'Seconds':
            return value.replace(microsecond=0)
        if unit == 'Milliseconds':
            return value.replace(microsecond=value.microsecond // 1000 * 1000)
        raise FxError(f'Unsupported date unit {unit}', 'InvalidArgument')
    duration = truncate(end) - truncate(start)
    micros = (duration.days * 86400 + duration.seconds) * 1000000 + duration.microseconds
    return int(micros // {'Days': 86400000000, 'Hours': 3600000000, 'Minutes': 60000000, 'Seconds': 1000000, 'Milliseconds': 1000}[unit])


def format_number(value, fmt, result_tag):
    result = locale(result_tag)
    tags = re.findall(r'\[\$-([^]]+)\]', fmt)
    if len(tags) > 1:
        raise FxError('Text accepts one format language tag', 'InvalidArgument')
    source = locale(tags[0] if tags else 'en-US')
    fmt = re.sub(r'\[\$-[^]]+\]', '', fmt)
    separators=re.escape(source['decimal']+source['group'])
    match = re.search(r'[#0][#0., \u00a0\u202f'+separators+']*', fmt)
    if not match or ';' in fmt or '[' in fmt or 'E+' in fmt.upper():
        raise FxError('Unsupported numeric Text format', 'Unsupported')
    mask = match[0].rstrip()
    prefix, suffix = fmt[:match.start()], fmt[match.start() + len(mask):]
    if re.search(r'[#0]', prefix + suffix):
        raise FxError('Unsupported non-contiguous numeric Text placeholders', 'Unsupported')
    whole, separator, fraction = mask.partition(source['decimal'])
    if any(c not in '#0' for c in fraction):
        raise FxError('Unsupported fractional Text format', 'Unsupported')
    digits = len(fraction)
    with_percent = '%' in prefix + suffix
    try:
        from decimal import localcontext
        with localcontext() as context:
            context.prec = 100
            decimal = Decimal(str(value)) * (100 if with_percent else 1)
            rounded = decimal.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    except ArithmeticError:
        raise FxError('Numeric format exceeds supported precision', 'Numeric') from None
    out = f'{rounded.copy_abs():.{digits}f}'
    integer, _, decimals = out.partition('.')
    integer = integer.zfill(whole.count('0'))
    if '#' in whole and '0' not in whole and integer == '0':
        integer = ''
    grouping = any(c in whole for c in (source['group'], ',', '.', ' ', '\u00a0', '\u202f') if c != source['decimal'])
    if grouping and integer:
        primary,secondary=result.get('grouping',(3,3))
        if primary<100 and secondary<100:
            groups=[]
            while len(integer)>primary:
                groups.insert(0,integer[-primary:]);integer=integer[:-primary];primary=secondary
            integer=result['group'].join([integer,*groups])
    optional = len(fraction) - len(fraction.rstrip('#'))
    for _ in range(optional):
        if decimals.endswith('0'):
            decimals = decimals[:-1]
    out = integer + (result['decimal'] + decimals if decimals else '')
    return prefix + ('-' if rounded < 0 else '') + out + suffix


def format_date(value, fmt, tag):
    profile = locale(tag)
    language = profile['language']
    if fmt == 'UTC':
        return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    if 'culture' in profile:
        rendered=locale_data.enum_date(value,fmt,profile)
        if rendered is not None:return rendered
    short = 'yyyy-mm-dd' if profile['tag'] in ('en-ca', 'fr-ca') else 'dd/mm/yyyy' if profile['day_first'] else 'm/d/yyyy'
    long = 'dddd d mmmm yyyy' if language == 'fr' else 'dddd, d mmmm yyyy' if profile['day_first'] else 'dddd, mmmm d, yyyy'
    time = 'hh:mm:ss' if profile['day_first'] or profile['tag'] == 'en-ca' else 'h:mm:ss AM/PM'
    enums = {'ShortDate': short, 'LongDate': long, 'ShortDateTime': short + ' ' + time.replace(':ss', ''),
             'LongDateTime': long + ' ' + time, 'ShortTime': time.replace(':ss', ''), 'LongTime': time,
             'ShortTime24': 'hh:mm', 'LongTime24': 'hh:mm:ss', 'ShortDateTime24': short + ' hh:mm', 'LongDateTime24': long + ' hh:mm:ss'}
    fmt = enums.get(fmt, fmt)
    tags = re.findall(r'\[\$-([^]]+)\]', fmt)
    if len(tags) > 1:
        raise FxError('Text accepts one format language tag', 'InvalidArgument')
    if tags:
        locale(tags[0])
    fmt = re.sub(r'\[\$-[^]]+\]', '', fmt)
    tokens = list(re.finditer(r'"[^"]*"|AM/PM|A/P|yyyy|mmmm|dddd|mmm|ddd|yy|mm|dd|hh|ss|fff|ff|f|[mdhs]', fmt, re.I))
    months,days=locale_data.names(profile,context='format' if any(m[0].lower() in ('d','dd') for m in tokens) else 'stand-alone') if 'culture' in profile else (MONTHS[language],DAYS[language])
    short_months,short_days=locale_data.names(profile,'abbreviated') if 'culture' in profile else (SHORT_MONTHS[language],SHORT_DAYS[language])
    am,pm=locale_data.periods(profile) if 'culture' in profile else ('AM','PM')
    # Non-token characters remain literal; enum backing strings are not enum formats.
    ampm = any(m[0].lower() in ('am/pm', 'a/p') for m in tokens)
    out, end = [], 0
    for index, match in enumerate(tokens):
        out.append(fmt[end:match.start()])
        token = match[0].lower()
        previous = tokens[index - 1][0].lower() if index else ''
        following = tokens[index + 1][0].lower() if index + 1 < len(tokens) else ''
        minutes = token in ('m', 'mm') and (previous in ('h', 'hh') or following in ('s', 'ss'))
        hour = value.hour % 12 or 12 if ampm else value.hour
        values = {'yyyy': f'{value.year:04}', 'yy': f'{value.year % 100:02}',
                  'mmmm': months[value.month - 1], 'mmm': short_months[value.month - 1],
                  'dddd': days[value.weekday()], 'ddd': short_days[value.weekday()],
                  'd': str(value.day), 'dd': f'{value.day:02}', 'm': str(value.minute if minutes else value.month),
                  'mm': f'{value.minute if minutes else value.month:02}', 'h': str(hour), 'hh': f'{hour:02}',
                  's': str(value.second), 'ss': f'{value.second:02}', 'f': str(value.microsecond // 100000),
                  'ff': f'{value.microsecond // 10000:02}', 'fff': f'{value.microsecond // 1000:03}',
                  'am/pm': am if value.hour < 12 else pm, 'a/p': ('A' if value.hour < 12 else 'P') if match[0].isupper() else ('a' if value.hour < 12 else 'p')}
        out.append(match[0][1:-1] if match[0].startswith('"') else values[token])
        end = match.end()
    out.append(fmt[end:])
    return ''.join(out)

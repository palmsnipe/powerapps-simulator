"""Server contracts and presentation values for date and number inputs."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR, localcontext
import math
import re

from .classic_inputs import DATE_PICKERS
from .syntax import FxError
from .temporal import Temporal
from .locale_fx import locale, format_date, parse_number, MONTHS, SHORT_DAYS


def finite(value, name, blank=False):
    if value is None and blank:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(float(value)):
        raise FxError(f'Number input {name} requires a finite Number', 'Type')
    return float(value)


def number_contract(ref):
    low, high = finite(ref.property('Min'), 'Min', True), finite(ref.property('Max'), 'Max', True)
    step = finite(ref.property('Step'), 'Step')
    precision = ref.property('Precision')
    if low is not None and high is not None and low > high:
        raise FxError('Number input Min cannot exceed Max', 'Validation')
    if step <= 0:
        raise FxError('Number input Step must be greater than zero', 'Validation')
    if precision != 'Auto' and (isinstance(precision, bool) or not isinstance(precision, (int, float, Decimal)) or precision not in (0, 1, 2, 3)):
        raise FxError('Number input Precision requires Auto or 0–3', 'Type')
    return low, high, step, None if precision == 'Auto' else int(precision)


def number_value(ref, value, direction=None):
    low, high, step, precision = number_contract(ref)
    value = finite(value, 'Value', True)
    if direction is not None:
        value = float(Decimal(str(value or 0)) + Decimal(str(step)) * direction)
    if value is None:
        return None
    value = finite(value, 'Value')
    with localcontext() as ctx:
        ctx.prec = 400
        if precision is not None:
            quantum = Decimal(1).scaleb(-precision)
            value = float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))
            effective_low = float(Decimal(str(low)).quantize(quantum, rounding=ROUND_CEILING)) if low is not None else None
            effective_high = float(Decimal(str(high)).quantize(quantum, rounding=ROUND_FLOOR)) if high is not None else None
        else:
            effective_low, effective_high = low, high
    if effective_low is not None and effective_high is not None and effective_low > effective_high:
        raise FxError('Number input range contains no value at this Precision', 'Validation')
    if direction is not None:
        if effective_low is not None:value = max(effective_low, value)
        if effective_high is not None:value = min(effective_high, value)
    if effective_low is not None and value < effective_low or effective_high is not None and value > effective_high:
        raise FxError('Number input value is outside Min/Max', 'Validation')
    return finite(value, 'Value')


def number_text(ref, value):
    if value is None:return ''
    _, _, _, precision = number_contract(ref)
    result = format(value, f'.{precision}f') if precision is not None else str(value).removesuffix('.0')
    profile = locale(ref.property('ContentLanguage') or ref.runtime.environment['language'])
    return result.replace('.', profile['decimal'])


def parse_number_input(ref, value):
    if not isinstance(value, str):raise ValueError('Number input text requires Text')
    # Inputs accept ordinary locale numbers; currency/percent syntax belongs in Power Fx Value.
    if any(c in value for c in '$€£%()'):raise ValueError('Enter a number without currency or percent symbols')
    return parse_number(value, ref.property('ContentLanguage') or ref.runtime.environment['language'])


def date_language(ref):
    if ref.family == 'DatePicker':
        return ref.runtime.environment['language']
    return ref.property('Language' if ref.family=='Classic/DatePicker' else 'ContentLanguage') or ref.runtime.environment['language']


def date_value(ref, value):
    if value is None:return None
    is_day = isinstance(value, Temporal) and value.kind == 'Date' or isinstance(value, str) and ':' not in value and 'T' not in value
    parsed = ref.runtime.fx.temporal(value, 'DateTime', date_language(ref))
    if parsed is None:return None
    stamp = parsed.value
    zone = ref.property('DateTimeZone')
    if zone not in ('Local', 'UTC'):raise FxError('DateTimeZone requires Local or UTC', 'Type')
    if not is_day:
        from .fx import date_value as instant
        clock = ref.runtime.environment.get('clock')
        target = instant(clock).tzinfo if clock and zone == 'Local' else timezone.utc
        stamp = stamp.astimezone(target)
    return Temporal('Date', stamp.replace(hour=0, minute=0, second=0, microsecond=0))


def date_contract(ref):
    if ref.family=='Classic/DatePicker':
        first,last=ref.property('StartYear'),ref.property('EndYear')
        if first>last:raise FxError('Date picker StartYear cannot exceed EndYear','Validation')
        start=Temporal('Date',datetime(int(first),1,1));end=Temporal('Date',datetime(int(last),12,31))
    else:start, end = ref.property('StartDate'), ref.property('EndDate')
    if ref.family == 'DatePicker':
        start = start or Temporal('Date', datetime(1, 1, 1))
        end = end or Temporal('Date', datetime(9999, 12, 31))
    if start is None or end is None:raise FxError('Date picker StartDate and EndDate require dates', 'Type')
    if start.value.date() > end.value.date():raise FxError('Date picker StartDate cannot exceed EndDate', 'Validation')
    week = ref.property('StartOfWeek')
    if ref.family == 'DatePicker':
        days = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
        week = 'Sunday' if week is None else week
        if week not in days:raise FxError('DatePicker.StartOfWeek requires a weekday name', 'Type')
        return start.value.date(), end.value.date(), days.index(week)
    weekdays={1:6,2:0,3:0,12:1,13:2,14:3,15:4,16:5}
    from .enum_fx import EnumValue
    if isinstance(week,EnumValue):
        if week.namespace!='StartOfWeek':raise FxError('Date picker requires StartOfWeek enum','Type')
        week=week.backing
    if isinstance(week, bool) or week not in weekdays:raise FxError('Date picker StartOfWeek requires a weekday enum', 'Type')
    return start.value.date(), end.value.date(), weekdays[week]


def date_label(ref, value):
    if value is None:return ''
    tag = date_language(ref);profile = locale(tag)
    fmt = ref.property('Format')
    if not isinstance(fmt, str):raise FxError('Date picker Format requires Text', 'Type')
    formats = {'Short':'ShortDate','Long':'d mmmm yyyy' if profile['day_first'] else 'mmmm d, yyyy',
               'LongAbbreviated':'d mmm yyyy' if profile['day_first'] else 'mmm d, yyyy'}
    if ref.family == 'DatePicker':
        formats.update({'Long Abbreviated': formats['LongAbbreviated'], 'Year Month': 'mmmm yyyy'})
    return format_date(value.value, formats.get(fmt, fmt), tag)


def date_calendar(ref):
    start, end, week = date_contract(ref)
    selected = ref.property('SelectedDate')
    tag = date_language(ref);profile = locale(tag)
    current = selected.value.date() if selected else ref.runtime.fx.evaluate('Today()').value.date()
    current = min(end, max(start, current))
    month = ref.runtime.calendar_months.get(ref.path, current.replace(day=1))
    offset = (month.weekday() - week) % 7
    first_ordinal = month.toordinal() - offset
    cells = []
    for i in range(42):
        ordinal = first_ordinal + i
        if ordinal < 1 or ordinal > date.max.toordinal():
            cells.append({'date':None,'day':'','disabled':True});continue
        day = date.fromordinal(ordinal)
        cells.append({'date':day.isoformat(),'day':day.day,'outside':day.month!=month.month,
                      'disabled':not start<=day<=end,'selected':selected is not None and day==selected.value.date(),
                      'label':format_date(datetime.combine(day,datetime.min.time()),'LongDate',tag)})
    prev = (month-timedelta(days=1)).replace(day=1) if month>date.min else None
    nxt = month.replace(day=28)+timedelta(days=4) if month.year<9999 or month.month<12 else None
    nxt = nxt.replace(day=1) if nxt else None
    return {'month':month.isoformat()[:7],'title':MONTHS[profile['language']][month.month-1]+' '+str(month.year),
            'weekdays':[SHORT_DAYS[profile['language']][(week+i)%7] for i in range(7)],'days':cells,
            'previous':prev.isoformat()[:7] if prev and prev.year*12+prev.month>=start.year*12+start.month else None,
            'next':nxt.isoformat()[:7] if nxt and nxt.year*12+nxt.month<=end.year*12+end.month else None,
            'start':start.isoformat(),'end':end.isoformat(),'formatted':date_label(ref,selected)}


def parse_date_input(ref, value):
    if value is None or isinstance(value,str) and not value.strip():return None
    if not isinstance(value,str):raise ValueError('Date input requires Text')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):return value
    fmt=ref.property('Format');patterns={'dd-mm-yyyy':'%d-%m-%Y','yyyy-mm-dd':'%Y-%m-%d','dd/mm/yyyy':'%d/%m/%Y','mm/dd/yyyy':'%m/%d/%Y','dd-mm':'%d-%m'}
    if fmt in patterns:
        try:
            day=datetime.strptime(value,patterns[fmt]).date()
            if fmt=='dd-mm':day=day.replace(year=(ref.property('SelectedDate') or ref.runtime.fx.evaluate('Today()')).value.year)
            return day.isoformat()
        except ValueError:raise ValueError('Date does not match the configured Format') from None
    parsed=ref.runtime.fx.temporal(value,'Date',date_language(ref))
    return parsed.isoformat() if parsed else None


def input_event(runtime, ref, name, value):
    """Return True when a structured/legacy event has been fully handled."""
    if ref.family not in (*DATE_PICKERS,'ModernNumberInput') or name not in ('OnChange','OnCalendar'):
        return False
    key = runtime.input_property(ref);ref.sync_default(key)
    operation = 'commit';direction = None
    if isinstance(value, dict):
        if ref.family=='ModernNumberInput':
            expected={'text','operation','reset_token'} | ({'direction'} if value.get('operation')=='step' else set())
            valid=value.get('operation') in ('commit','step') and isinstance(value.get('text'),str)
        elif name=='OnCalendar':
            expected={'month','reset_token'};valid=isinstance(value.get('month'),str)
        else:
            expected={'value','source','reset_token'};valid=value.get('source') in ('typed','calendar','clear') and (value.get('value') is None or isinstance(value.get('value'),str))
        if set(value)!=expected or not valid:raise ValueError('Invalid input operation')
        if value.get('reset_token') != runtime.scalar_token(ref):
            if not isinstance(value.get('reset_token'),str):raise ValueError('Input event requires an instance token')
            return True
        if ref.family in DATE_PICKERS and name == 'OnCalendar':
            if set(value) != {'month','reset_token'} or not isinstance(value['month'],str) or not re.fullmatch(r'\d{4}-\d{2}',value['month']):
                raise ValueError('Calendar navigation requires an ISO month')
            try:month = date.fromisoformat(value['month']+'-01')
            except ValueError:raise ValueError('Calendar navigation requires an ISO month') from None
            start,end,_ = date_contract(ref)
            if not start.year*12+start.month<=month.year*12+month.month<=end.year*12+end.month:raise ValueError('Calendar month is outside StartDate/EndDate')
            runtime.calendar_months[ref.path]=month;runtime.invalidate();return True
        if ref.family == 'ModernNumberInput':
            operation = value.get('operation')
            if operation not in ('commit','step') or set(value) != ({'text','operation','reset_token'} if operation=='commit' else {'text','operation','direction','reset_token'}):
                raise ValueError('Invalid number input operation')
            if operation == 'step':
                direction = value['direction']
                if type(direction) is not int or direction not in (-1,1):raise ValueError('Step direction requires -1 or 1')
            value = parse_number_input(ref,value['text'])
        else:
            if set(value) != {'value','source','reset_token'} or value['source'] not in ('calendar','typed','clear'):
                raise ValueError('Invalid date input operation')
            if value['source']=='typed' and not ref.property('IsEditable'):raise ValueError('Date picker is not directly editable')
            value = parse_date_input(ref,value['value']) if value['source']=='typed' else value['value']
    elif name == 'OnCalendar':raise ValueError('Calendar navigation requires a structured event')
    if ref.family == 'ModernNumberInput':
        value = number_value(ref,value,direction)
    else:
        if value is None or value=='':value=None
        else:
            if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError('Date input requires an ISO calendar date')
            try:day=date.fromisoformat(value)
            except ValueError:raise ValueError('Date input requires an ISO calendar date') from None
            start,end,_=date_contract(ref)
            if not start<=day<=end:raise ValueError('Date is outside StartDate/EndDate')
            value=Temporal('Date',datetime.combine(day,datetime.min.time()))
    previous=ref.property(key)
    baseline=ref.runtime.input_baselines.get(ref.path)
    if ref.family in DATE_PICKERS:baseline=date_value(ref,baseline)
    else:baseline=number_value(ref,baseline)
    ref.state.update({key:value,'dirty':value!=baseline})
    if ref.family in DATE_PICKERS:runtime.calendar_months.pop(ref.path,None)
    runtime.invalidate()
    if value!=previous:
        if ref.family=='Classic/DatePicker':runtime.run_event(ref,'OnSelect')
        runtime.run_event(ref,'OnChange')
    runtime.drain_events();return True


def slider_event(runtime,ref,name,value):
    """Preview values are reactive; OnChange runs once when the drag commits."""
    ref.sync_default('Value')
    if ref.property('ReadOnly'):return
    if isinstance(value,dict):
        if set(value)!={'value','reset_token'} or not isinstance(value['reset_token'],str):raise ValueError('Invalid slider event')
        if value['reset_token']!=runtime.scalar_token(ref):return
        value=value['value']
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('Slider value requires a finite Number')
    low,high=ref.slider_bounds();value=max(low,min(high,value))
    previous=ref.property('Value');last=ref.state.get('slider_last_change',previous)
    baseline=max(low,min(high,runtime.input_baselines[ref.path]))
    ref.state.update(Value=value,dirty=value!=baseline,slider_last_change=last)
    runtime.invalidate()
    if name=='OnChange' and value!=last:
        ref.state['slider_last_change']=value
        runtime.run_event(ref,'OnChange')
    runtime.drain_events()

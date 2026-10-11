"""Archived DatePickerCanvas bindings, separate from ModernDatePicker defaults."""
from functools import lru_cache
from pathlib import Path
from decimal import Decimal
import hashlib
import json
import math

from .syntax import FxError
from .temporal import Temporal
from .canvas_inputs import LAYOUT


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent / 'static/canvas-dates.json').read_text())['DatePicker']


def spec(ref):
    try:
        return catalog()[ref.control.version]
    except KeyError:
        raise FxError(f'Unsupported DatePicker version {ref.control.version}', 'Unsupported') from None


def enum_values():
    props = next(iter(catalog().values()))['native_properties']
    return {p['Name']: {e['Name']: e['Value'] for e in p['EnumValues']}
        for p in props if p.get('EnumValues')}


def errors(control):
    if control.version not in catalog():
        return {'Version': f'Unsupported {control.kind} version'}
    s = catalog()[control.version]
    allowed = set(s['types']) | LAYOUT | {e['Name'] for e in s['events']}
    result = {p: f'{control.kind} has no supported authored {p} property' for p in control.properties if p not in allowed}
    if control.raw.get('Variant'):
        result['Variant'] = 'Native DatePicker variants are unsupported'
    return result


def guard(ref, name):
    s = spec(ref)
    findings = errors(ref.control)
    for p in ('Variant', name):
        if p in findings:
            raise FxError(findings[p], 'Unsupported')
    if name not in set(s['types']) | LAYOUT | {e['Name'] for e in s['events']} | {'Name', 'Reset'}:
        raise FxError(f'{ref.control.kind} has no supported {name} property', 'Unsupported')


def validate(ref, name, value):
    if value is None:
        return value
    s = spec(ref)
    typ = s['types'].get(name)
    if typ == 'Date':
        if not isinstance(value, Temporal) or value.kind not in ('Date', 'DateTime'):
            raise FxError(f'DatePicker.{name} requires Date or DateTime', 'Type')
        from .input_controls import date_value
        return date_value(ref, value)
    if typ == 'Text' and not isinstance(value, str):
        raise FxError(f'DatePicker.{name} requires Text', 'Type')
    if name in s['enum_values'] and value not in s['enum_values'][name]:
        raise FxError(f'DatePicker.{name} requires ' + ', '.join(s['enum_values'][name]), 'Type')
    if typ == 'Boolean' and not isinstance(value, bool):
        raise FxError(f'DatePicker.{name} requires Boolean', 'Type')
    if typ == 'Number':
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(float(value)):
            raise FxError(f'DatePicker.{name} requires a finite Number', 'Type')
        if name == 'TabIndex' and value != int(value):
            raise FxError('DatePicker.TabIndex requires an integer', 'Type')
        if name not in ('X', 'Y', 'TabIndex') and value < 0:
            raise FxError(f'DatePicker.{name} cannot be negative', 'Validation')
    return value


def token(ref):
    from .runtime import serial
    r = ref.runtime
    data = [r.text_generation, ref.path, r.scalar_resets.get(ref.path, 0), ref.control.kind,
        serial(ref.eval_raw('SelectedDate')), serial(ref.property('StartDate')), serial(ref.property('EndDate')),
        ref.property('Format'), ref.property('DateTimeZone'), ref.property('StartOfWeek'),
        ref.property('IsEditable'), r.environment['language'], r.environment.get('clock')]
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def event(ref, name, data, selection):
    if selection is not None or name not in ('OnChange', 'OnCalendar') or not isinstance(data, dict):
        raise ValueError('Native DatePicker requires a structured calendar or date event')
    from .input_controls import input_event
    input_event(ref.runtime, ref, name, data)


def render(ref, node):
    from .input_controls import date_calendar
    from .runtime import serial
    node['value'] = serial(ref.property('SelectedDate'))
    node['input_reset'] = token(ref)
    node['calendar'] = date_calendar(ref)
    node['canvas_date'] = {'version': ref.control.version, 'authored': sorted(ref.control.properties)}

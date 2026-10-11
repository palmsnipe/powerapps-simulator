"""Archived bound Slider and Toggle controls; Python owns values and events.

Drag preview and release callbacks, blank coercion and range clamping are local
models. Archive descriptors establish contracts, not native event timing.
"""
from functools import lru_cache
from pathlib import Path
from decimal import Decimal
import hashlib
import json
import math

from .syntax import FxError
from .canvas_inputs import LAYOUT

FAMILIES = frozenset(('Slider', 'Toggle'))


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent / 'static/canvas-scalars.json').read_text())


def spec(ref):
    try:
        return catalog()[ref.family][ref.control.version]
    except KeyError:
        raise FxError(f'Unsupported {ref.control.kind} version', 'Unsupported') from None


def enums(family):
    props = next(iter(catalog()[family].values()))['native_properties']
    return {p['Name']: {e['Name']: e['Value'] for e in p['EnumValues']}
        for p in props if p.get('EnumValues')}


def errors(control):
    if control.version not in catalog()[control.family]:
        return {'Version': f'Unsupported {control.kind} version'}
    s = catalog()[control.family][control.version]
    allowed = set(s['types']) | LAYOUT | {e['Name'] for e in s['events']}
    result = {p: f'{control.kind} has no supported authored {p} property'
        for p in control.properties if p not in allowed}
    if control.raw.get('Variant'):
        result['Variant'] = 'Native scalar variants are unsupported'
    return result


def guard(ref, name):
    s = spec(ref)
    findings = errors(ref.control)
    for key in ('Variant', name):
        if key in findings:
            raise FxError(findings[key], 'Unsupported')
    if name not in set(s['types']) | LAYOUT | {e['Name'] for e in s['events']} | {'Name', 'Reset'}:
        raise FxError(f'{ref.control.kind} has no supported {name} property', 'Unsupported')


def validate(ref, name, raw):
    if raw is None:
        return
    s = spec(ref)
    typ = s['types'].get(name)
    if typ == 'Text' and not isinstance(raw, str):
        raise FxError(f'{ref.family}.{name} requires Text', 'Type')
    if name in s['enum_values'] and raw not in s['enum_values'][name]:
        raise FxError(f'{ref.family}.{name} requires ' + ', '.join(s['enum_values'][name]), 'Type')
    if typ == 'Boolean' and not isinstance(raw, bool):
        raise FxError(f'{ref.family}.{name} requires Boolean', 'Type')
    if typ == 'Number':
        if isinstance(raw, bool) or not isinstance(raw, (int, float, Decimal)) or not math.isfinite(float(raw)):
            raise FxError(f'{ref.family}.{name} requires a finite Number', 'Type')
        if name == 'TabIndex' and raw != int(raw):
            raise FxError(f'{ref.family}.TabIndex requires an integer', 'Type')
        if name not in ('X', 'Y', 'TabIndex', 'Value', 'Min', 'Max') and raw < 0:
            raise FxError(f'{ref.family}.{name} cannot be negative', 'Validation')


def bounds(ref):
    low, high = ref.property('Min'), ref.property('Max')
    if low is None or high is None or low > high:
        raise FxError('Slider requires nonblank Min <= Max', 'Validation')
    return low, high


def value(ref, raw):
    prop = ref.runtime.input_property(ref)
    validate(ref, prop, raw)
    if ref.family == 'Toggle':
        return False if raw is None else raw
    low, high = bounds(ref)
    return max(low, min(high, low if raw is None else raw))


def token(ref):
    from .runtime import serial
    r = ref.runtime
    prop = r.input_property(ref)
    epoch = r.scalar_resets if ref.family == 'Slider' else r.selector_resets
    contract = ('Min', 'Max', 'Layout', 'Size') if ref.family == 'Slider' else ('LabelPosition', 'ToggleSize')
    data = [r.text_generation, ref.path, ref.control.kind, epoch.get(ref.path, 0),
        serial(ref.eval_raw(prop)), *[serial(ref.property(p)) for p in contract]]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def event(ref, name, data, selection):
    r = ref.runtime
    if selection is not None:
        raise ValueError('Native scalars do not accept row selections')
    if ref.family == 'Toggle' and name == 'OnSelect' and data is None:
        r.run_event(ref, name); r.drain_events(); return
    if name not in (('OnInput', 'OnChange') if ref.family == 'Slider' else ('OnSelect',)):
        raise ValueError('Unsupported native scalar event')
    prop = r.input_property(ref)
    ref.sync_default(prop)
    field = 'value' if ref.family == 'Slider' else 'checked'
    if not isinstance(data, dict) or set(data) != {field, 'reset_token'} or not isinstance(data['reset_token'], str):
        raise ValueError('Native scalar requires a value and instance token')
    if data['reset_token'] != token(ref):
        return
    raw = data[field]
    validate(ref, prop, raw)
    if raw is None:
        raise ValueError('User input requires a Number or Boolean')
    if ref.family == 'Slider':
        raw = r.fx.literal_number(str(raw))
    current = value(ref, raw)
    previous = ref.property(prop)
    baseline = value(ref, r.input_baselines[ref.path])
    last = ref.state.get('slider_last_change', baseline)
    ref.state.update({prop: current, 'dirty': current != baseline})
    r.invalidate()
    if ref.family == 'Toggle':
        if current != previous:
            r.run_event(ref, 'OnCheck' if current else 'OnUncheck')
        r.run_event(ref, 'OnSelect')
    elif name == 'OnChange' and current != last:
        ref.state['slider_last_change'] = current
        r.run_event(ref, 'OnChange')
    r.drain_events()


def render(ref, node):
    from .runtime import serial
    node['value'] = serial(ref.property(ref.runtime.input_property(ref)))
    node['input_reset'] = token(ref)
    node['canvas_scalar'] = {'family': ref.family, 'version': ref.control.version,
        'authored': sorted(ref.control.properties)}

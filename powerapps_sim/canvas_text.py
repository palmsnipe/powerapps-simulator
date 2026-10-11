"""Archived Text/Fluent labels, with descriptor contracts and local geometry."""
from functools import lru_cache
from pathlib import Path
from decimal import Decimal
import json
import math

from .syntax import FxError
from .canvas_inputs import LAYOUT

FAMILIES = frozenset(('Text', 'FluentV8/Label'))


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent / 'static/canvas-text.json').read_text())


def spec(ref):
    try:
        return catalog()[ref.family][ref.control.version]
    except KeyError:
        raise FxError(f'Unsupported {ref.control.kind} version', 'Unsupported') from None


def errors(control):
    s = catalog()[control.family].get(control.version)
    if s is None:
        return {'Version': f'Unsupported {control.kind} version'}
    allowed = set(s['types']) | LAYOUT | {e['Name'] for e in s['events']}
    findings = {p: f'{control.kind} has no supported authored {p} property'
                for p in control.properties if p not in allowed}
    if control.raw.get('Variant'):
        findings['Variant'] = 'Archived text variants are unsupported'
    return findings


def guard(ref, name):
    s = spec(ref)
    findings = errors(ref.control)
    for key in ('Variant', name):
        if key in findings:
            raise FxError(findings[key], 'Unsupported')
    if name not in set(s['types']) | LAYOUT | {e['Name'] for e in s['events']} | {'Name'}:
        raise FxError(f'{ref.control.kind} has no supported {name} property', 'Unsupported')


def validate(ref, name, value):
    s = spec(ref)
    if value is None:
        return
    kind = s['types'].get(name)
    if kind == 'Text' and not isinstance(value, str):
        raise FxError(f'{ref.family}.{name} requires Text', 'Type')
    if kind == 'Boolean' and not isinstance(value, bool):
        raise FxError(f'{ref.family}.{name} requires Boolean', 'Type')
    if kind == 'Number':
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(float(value)):
            raise FxError(f'{ref.family}.{name} requires a finite Number', 'Type')
        if name == 'TabIndex' and value != int(value):
            raise FxError('TabIndex requires an integer', 'Type')
        if name not in ('X', 'Y', 'TabIndex') and value < 0:
            raise FxError(f'{ref.family}.{name} cannot be negative', 'Validation')
    if name in s['enum_values'] and value not in s['enum_values'][name].values():
        raise FxError(f'{ref.family}.{name} requires ' + ', '.join(s['enum_values'][name].values()), 'Type')
    if name == 'DisplayMode' and value not in ('Edit', 'View', 'Disabled'):
        raise FxError('DisplayMode requires Edit, View or Disabled', 'Type')
    # These old Fluent properties are plain strings, with lowercase defaults
    # and uppercased built-in enum values in the recovered source.
    choices = {'Alignment': ('left', 'center', 'right', 'justify'),
               'VerticalAlignment': ('top', 'middle', 'bottom'),
               'FontWeight': ('normal', 'bold', 'semibold', 'lighter'),
               'BorderStyle': ('solid', 'dashed', 'dotted', 'none')}
    if name in choices and value and value.lower() not in choices[name]:
        raise FxError(f'{ref.family}.{name} requires ' + ', '.join(choices[name]), 'Type')


def inset(ref, dimension):
    if ref.family == 'FluentV8/Label':
        names = ('PaddingStart', 'PaddingEnd') if dimension == 'Width' else ('PaddingTop', 'PaddingBottom')
        border = 0
    else:
        names = ('PaddingLeft', 'PaddingRight') if dimension == 'Width' else ('PaddingTop', 'PaddingBottom')
        border = max(0, ref.property('BorderThickness') or 0)
    return tuple(max(0, ref.property(name) or 0) + border for name in names)


def auto_height(ref):
    """Approximate measurement; no browser-derived Power Fx property values."""
    r = ref.runtime
    base = ref.eval_raw('Height')
    validate(ref, 'Height', base)
    if any(a.property('Visible') is False for a in (ref, *r.ancestors(ref))):
        return r.label_heights.get(ref.path, base)
    text = ref.property('Text') or ''
    size = ref.property('FontSize' if ref.family == 'FluentV8/Label' else 'Size') or 0
    # The old Fluent descriptor is points, whereas TextCanvas uses pixels.
    pixels = float(size) * (4 / 3 if ref.family == 'FluentV8/Label' else 1)
    width = max(1, float(ref.property('Width') or 0) - sum(inset(ref, 'Width')))
    chars = max(1, int(width / max(1, pixels * .55)))
    lines = sum(max(1, math.ceil(len(line) / chars)) for line in text.split('\n')) if ref.property('Wrap') and text else int(bool(text))
    height = max(float(base or 0), math.ceil(lines * pixels * 1.45 + sum(inset(ref, 'Height'))))
    r.label_heights[ref.path] = height
    return height


def render(ref, node):
    s = spec(ref)
    role = node['props'].get('TextRole', 'Default')
    node['native_text'] = {'version': ref.control.version,
        'heading': int(role[-1]) if role and role.startswith('Heading') else None,
        'scroll': node['props'].get('Overflow') == 'Scroll' and not node['props'].get('AutoHeight'),
        'rtl': ref.runtime.environment.get('language', '').split('-')[0].lower() in ('ar','he','fa','ur'),
        'auto_disable': s['subscribed_functionalities'].get('autoDisabledViewState') == 'true',
        'busy': ref.path in ref.runtime.button_busy,
        'authored': sorted(ref.control.properties)}
    if ref.family == 'Text':
        node['selectable'] = False

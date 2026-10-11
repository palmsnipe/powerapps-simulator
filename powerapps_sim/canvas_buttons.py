"""Archived canvas Buttons; descriptors establish contracts, not native timing."""
from functools import lru_cache
from pathlib import Path
from decimal import Decimal
import json
import math

from .syntax import FxError
from .canvas_inputs import LAYOUT


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent / 'static/canvas-buttons.json').read_text())


def spec(ref):
    try:
        return catalog()[ref.control.version]
    except KeyError:
        raise FxError(f'Unsupported {ref.control.kind} version', 'Unsupported') from None


def errors(control):
    if control.version not in catalog():
        return {'Version': f'Unsupported {control.kind} version'}
    s = catalog()[control.version]
    allowed = set(s['types']) | LAYOUT | {e['Name'] for e in s['events']}
    result = {p: f'{control.kind} has no supported authored {p} property'
        for p in control.properties if p not in allowed}
    if control.raw.get('Variant'):
        result['Variant'] = 'Archived Button variants are unsupported'
    return result


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
    typ = s['types'].get(name)
    if name in s['enum_values'] and value not in s['enum_values'][name].values():
        raise FxError(f'Button.{name} requires ' + ', '.join(s['enum_values'][name].values()), 'Type')
    if typ == 'Text' and not isinstance(value, str):
        raise FxError(f'Button.{name} requires Text', 'Type')
    if typ == 'Boolean' and not isinstance(value, bool):
        raise FxError(f'Button.{name} requires Boolean', 'Type')
    if typ == 'Number':
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(float(value)):
            raise FxError(f'Button.{name} requires a finite Number', 'Type')
        if name == 'TabIndex' and value != int(value):
            raise FxError('Button.TabIndex requires an integer', 'Type')
        if name not in ('TabIndex', 'X', 'Y', 'IconRotation') and value < 0:
            raise FxError(f'Button.{name} cannot be negative', 'Validation')
    options = {
        'DisplayMode': ('Edit', 'View', 'Disabled'),
        'Align': ('Left', 'Center', 'Right', 'Justify'),
        'VerticalAlign': ('Top', 'Middle', 'Bottom'),
        'BorderStyle': ('Solid', 'Dashed', 'Dotted', 'None'),
    }
    if name in options and value not in ('', *options[name]):
        raise FxError(f'Button.{name} requires ' + ', '.join(options[name]), 'Type')


def render(ref, node):
    from .icons import glyph
    s = spec(ref)
    node['button_authored'] = sorted(ref.control.properties)
    node['canvas_button'] = {
        'version': ref.control.version,
        'auto_disable': s['subscribed_functionalities'].get('autoDisabledViewState') == 'true',
        'busy': ref.path in ref.runtime.button_busy,
    }
    try:
        node['icon'] = glyph(ref.property('Icon'), ref.property('IconStyle') or 'Outline')
    except FxError as error:
        name = 'IconStyle' if isinstance(ref.runtime.property_cache.get((ref.path, 'IconStyle')), FxError) else 'Icon'
        ref.runtime.render_error(ref, name, error)
        if not any(error.message in message for message in node['errors']):
            node['errors'].append(f'{name}: {error.message}')

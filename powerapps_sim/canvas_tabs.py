"""Archived TabList contracts, distinct from the newer ModernTabList.

Descriptors establish property names/types. Selection fallback, display-column
inference and callback ordering are explicit local models awaiting native traces.
"""
from functools import lru_cache
from pathlib import Path
from decimal import Decimal
import hashlib
import json
import math

from .syntax import FxError
from .store import DataSource
from .canvas_inputs import LAYOUT

OUTPUTS = frozenset(('Selected', 'SelectedItems'))


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent / 'static/canvas-tabs.json').read_text())


def spec(ref):
    try:
        return catalog()[ref.control.version]
    except KeyError:
        raise FxError(f'Unsupported {ref.control.kind} version', 'Unsupported') from None


def errors(control):
    if control.version not in catalog():
        return {'Version': f'Unsupported {control.kind} version'}
    s = catalog()[control.version]
    allowed = (set(s['types']) - OUTPUTS) | LAYOUT | {e['Name'] for e in s['events']}
    result = {p: f'{control.kind} has no supported authored {p} property'
        for p in control.properties if p not in allowed}
    if control.raw.get('Variant'):
        result['Variant'] = 'Archived TabList variants are unsupported'
    return result


def guard(ref, name):
    s = spec(ref)
    findings = errors(ref.control)
    for key in ('Variant', name):
        if key in findings:
            raise FxError(findings[key], 'Unsupported')
    if name not in set(s['types']) | LAYOUT | {e['Name'] for e in s['events']} | {'Name', 'Reset'}:
        raise FxError(f'{ref.control.kind} has no supported {name} property', 'Unsupported')


def validate(ref, name, value):
    s = spec(ref)
    if value is None:
        return
    typ = s['types'].get(name)
    if name in s['enum_values'] and value not in s['enum_values'][name].values():
        raise FxError(f'TabList.{name} requires ' + ', '.join(s['enum_values'][name]), 'Type')
    if typ == 'Text' and not isinstance(value, str):
        raise FxError(f'TabList.{name} requires Text', 'Type')
    if typ == 'Boolean' and not isinstance(value, bool):
        raise FxError(f'TabList.{name} requires Boolean', 'Type')
    if typ == 'Number':
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(float(value)):
            raise FxError(f'TabList.{name} requires a finite Number', 'Type')
        if name == 'TabIndex' and value != int(value):
            raise FxError('TabList.TabIndex requires an integer', 'Type')
        if name not in ('TabIndex', 'X', 'Y') and value < 0:
            raise FxError(f'TabList.{name} cannot be negative', 'Validation')
    if typ == 'Table':
        from .fx import table
        if not isinstance(value, (list, DataSource)):
            raise FxError(f'TabList.{name} requires a Table', 'Type')
        if any(not isinstance(row, (dict, FxError)) for row in table(value)):
            raise FxError(f'TabList.{name} requires record rows', 'Type')
    if name == 'DisplayMode' and value not in ('Edit', 'View', 'Disabled'):
        raise FxError('TabList.DisplayMode requires Edit, View or Disabled', 'Type')


def rows(ref):
    from .fx import table
    if ref.children:
        raise FxError('Archived TabList has no supported field-child contract', 'Unsupported')
    return table(ref.property('Items'))


def default_index(ref, items):
    from .fx import table
    defaults = table(ref.property('DefaultSelectedItems'))
    for default in defaults:
        if isinstance(default, FxError):
            raise default
        for i, row in enumerate(items):
            if not isinstance(row, FxError) and ref.runtime.same_item(row, default):
                return i
    if not defaults:
        return next((i for i, row in enumerate(items) if not isinstance(row, FxError)), None)
    return None


def selected_index(ref, items):
    from .data_table import row_keys
    ref.sync_default('Selected')
    key = ref.state.get('canvas_tab_key')
    keys = row_keys(items)
    if key in keys:
        return keys.index(key)
    return default_index(ref, items)


def output(ref, name):
    items = rows(ref)
    index = selected_index(ref, items)
    chosen = items[index] if index is not None else None
    return ([chosen] if chosen is not None else []) if name == 'SelectedItems' else chosen


def token(ref, items=None):
    from .runtime import serial
    ref.sync_default('Selected')
    items = rows(ref) if items is None else items
    snapshot = [ref.runtime.selection_epoch(ref), ref.control.kind,
        serial(ref.property('DefaultSelectedItems')), serial(items)]
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def event(ref, name, value, selection):
    from .data_table import row_keys
    r = ref.runtime
    spec(ref)
    if name == 'OnSelect' and value is None and selection is None:
        r.run_event(ref, name)
        r.drain_events()
        return
    if name != 'OnChange':
        raise ValueError('TabList accepts tab selection events')
    items = rows(ref)
    if isinstance(value, dict):
        if selection is not None or set(value) != {'indices', 'option_token'} or not isinstance(value['option_token'], str):
            raise ValueError('Invalid TabList selection operation')
        if value['option_token'] != token(ref, items):
            return
        selection = value['indices']
    elif value is not None:
        raise ValueError('Invalid TabList selection operation')
    if not isinstance(selection, list) or len(selection) != 1 or type(selection[0]) is not int or not 0 <= selection[0] < len(items):
        raise ValueError('TabList requires one valid integer item index')
    index = selection[0]
    if isinstance(items[index], FxError):
        raise items[index]
    previous = selected_index(ref, items)
    ref.state.update(canvas_tab_key=row_keys(items)[index], dirty=index != default_index(ref, items))
    r.invalidate()
    # Existing modern-tab local ordering: both callbacks see committed output.
    r.run_event(ref, 'OnSelect')
    if previous != index:
        r.run_event(ref, 'OnChange')
    r.drain_events()


def display_column(items):
    first = next((row for row in items if isinstance(row, dict)), {})
    names = [k for k in first if not k.startswith('_')]
    return next((k for k in names if k.casefold() == 'value'), None) or next(
        (k for k in names if isinstance(first[k], str)), None) or next(
        (k for k in names if not isinstance(first[k], (dict, list, FxError))), None)


def render(ref, node):
    from .fx import text
    items = rows(ref)
    column = display_column(items)
    node['options'] = []
    for i, row in enumerate(items):
        try:
            if isinstance(row, FxError):
                raise row
            if column is None:
                raise FxError('TabList has no scalar display column; native field binding is unverified', 'Unsupported')
            value = ref.runtime.fx.member(row, column, ref.context())
            if isinstance(value, FxError):
                raise value
            if isinstance(value, (dict, list)):
                raise FxError('TabList display column requires scalar values', 'Type')
            node['options'].append({'index': i, 'label': text(value)})
        except FxError as error:
            ref.runtime.render_error(ref, 'Items', error)
            node['errors'].append('Items: ' + error.message)
            node['options'].append({'index': i, 'label': 'Power Fx error: ' + error.message, 'disabled': True})
    index = selected_index(ref, items)
    node['selection'] = [index] if index is not None else []
    node['option_token'] = token(ref, items)
    node['tab_contract'] = {'family': ref.family, 'version': ref.control.version,
        'authored': sorted(ref.control.properties), 'display_column': column}

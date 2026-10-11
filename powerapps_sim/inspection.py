"""Read-only type metadata for values whose JSON representation loses identity.

Runtime types win over declared types. Binding supplies string-backed Color/GUID
identity and the shape of empty tables; that provenance stays explicit. No
properties, formulas, events, data sources or component baselines are evaluated.
"""
from .binding import BLANK, UNKNOWN, value_type
from .components import component_definition, access_app_scope


def schema(actual, declared=UNKNOWN, depth=0):
    if depth >= 24:
        return {'kind': actual.kind, 'truncated': True}
    result = {'kind': actual.kind}
    if actual.kind == 'Text' and declared.kind in ('Color', 'GUID'):
        return {'kind': declared.kind, 'origin': 'binding'}
    if actual.kind in ('Number', 'Decimal') and declared.kind == 'Currency':
        return {'kind': 'Currency', 'backing': actual.kind, 'origin': 'binding'}
    if actual.kind == 'Control' and declared.kind == 'Screen' and getattr(actual.control, 'family', None) == 'Screen':
        return {'kind': 'Screen', 'name': actual.name, 'origin': 'binding'}
    if actual.kind == 'Record':
        fields = actual.physical_fields()
        expected = declared.physical_fields() if declared.kind == 'Record' else {}
        if fields or expected:
            result['fields'] = {name: schema(fields.get(name, BLANK), expected.get(name, UNKNOWN), depth+1)
                for name in sorted(fields.keys() | expected.keys())}
        if actual.open:
            result['open'] = True
        if actual.aliases:
            result['aliases'] = dict(actual.aliases)
        if actual.virtual:
            result['virtual'] = {name: schema(typ, UNKNOWN, depth+1) for name,typ in actual.virtual.items()}
    elif actual.kind == 'Table':
        row = actual.row or UNKNOWN
        expected = declared.row or UNKNOWN if declared.kind == 'Table' else UNKNOWN
        if row.kind == 'Record' and not row.fields and expected.kind == 'Record' and expected.fields:
            result['row'] = {**schema(expected, expected, depth+1), 'origin': 'binding'}
        else:
            result['row'] = schema(row, expected, depth+1)
    elif actual.name:
        result['name'] = actual.name
    if actual.kind in ('Blank', 'Error', 'Unknown') and declared.kind not in ('Blank', 'Error', 'Unknown'):
        result['declared'] = declared.json()
    return result


def values(current, declared, collection=False):
    return {name: schema(value_type(current.get(name, [] if collection else None)), declared.get(name, UNKNOWN))
        for name in sorted(current.keys() | declared.keys())}


def observe(runtime):
    binder = runtime.binder
    contexts = {screen: values(runtime.screen_context.get(screen, {}), binder.context_variables.get(screen, {}))
        for screen in sorted(runtime.screen_context.keys() | binder.context_variables.keys())}
    components = {}
    paths = set(runtime.component_state)
    for path, ref in runtime.refs.items():
        if ref.family == 'CanvasComponent' or ref.control.kind == 'Component':
            if not access_app_scope(runtime.project, ref):
                paths.add(path)
    for path in sorted(paths):
        local = runtime.component_state.get(path, {})
        ref = runtime.refs.get(path)
        definition = component_definition(runtime.project, ref.control) if ref else None
        name = definition.name if definition else ''
        components[path] = {
            'variables': values(local.get('variables', {}), binder.component_variables.get(name, {})),
            'collections': values(local.get('collections', {}), binder.component_collections.get(name, {}), True)}
    return {'globals': values(runtime.globals, binder.variables),
        'collections': values(runtime.collections, binder.collections, True),
        'contexts': contexts, 'components': components}

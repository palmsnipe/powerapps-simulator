"""Bind and sample one staged Power Fx property in its disposable runtime."""
from .ai_authoring import resolve
from .binding import value_type
from .fx import table
from .inspection import schema
from .store import DataSource
from .syntax import FxError


def inspect_property(runtime, probe):
    if not isinstance(probe, dict) or not {'path', 'property'} <= probe.keys() or probe.keys() - {
        'path', 'property', 'source', 'instance_path'
    } or any(not isinstance(value, str) or not value.strip() for value in probe.values()):
        raise ValueError('Provide a control path and property, with optional source and instance_path')
    control = resolve(runtime.project, probe['path'], probe.get('source'))
    prop = probe['property']
    if prop not in control.properties:
        raise ValueError(f'No authored {prop} property on {probe["path"]}')
    formula = control.properties[prop]
    scope = runtime.binder.scope_for(control, prop)
    declared = runtime.binder.property_type(control, prop)
    result = {'path': probe['path'], 'property': prop, 'source': control.source, 'formula': formula}
    try:
        inferred = runtime.binder.bind(runtime.fx.parse(formula), scope) if isinstance(formula, str) else value_type(formula)
    except FxError as error:
        return {**result, 'status': 'error', 'type': schema(value_type(error), declared), 'error': error}
    result['type'] = schema(inferred, declared)
    if scope.behavior or scope.function_pure:
        return {**result, 'status': 'type_only', 'reason': 'Use an isolated workflow to exercise this rule with its event or arguments.'}

    runtime.restart()
    root = control
    while root.parent:
        root = root.parent
    if root.name in runtime.screens:
        runtime.preview_screen = root.name
    runtime.state()
    requested_instance = probe.get('instance_path')
    if requested_instance:
        ref = runtime.refs.get(requested_instance)
        if ref is None or ref.control is not control:
            raise ValueError('Instance path does not match a rendered instance of the authored control in the candidate')
    else:
        ref = next((ref for ref in runtime.refs.values() if ref.control is control), None)
    if ref is None:
        return {**result, 'status': 'type_only', 'reason': 'The initial preview has no instance to sample. Use an isolated workflow to create the needed state.'}

    result['instance_path'] = ref.path
    try:
        if prop == 'ItemDisplayText':
            from .row_rules import item_formula
            options = table(ref.property('Items'), limit=1)
            if not options:
                return {**result, 'status': 'type_only', 'reason': 'There are no initial selector items to sample.'}
            value = item_formula(ref, prop, options[0])
        else:
            value = ref.property(prop)
        if isinstance(value, DataSource):
            value = table(value, limit=6)
    except FxError as error:
        value = error
    if isinstance(value, FxError):
        return {**result, 'status': 'error', 'error': value}
    trimmed = isinstance(value, list) and len(value) > 5
    return {**result, 'status': 'ok', 'value': value[:5] if trimmed else value, 'truncated': trimmed}

"""Local safety limits for component input feedback; not native timing rules."""
from .components import component_definition, validate_kind
from .syntax import FxError


RESET_LIMIT = 100


def changed_inputs(runtime, reset_counts=None):
    from .runtime import serial
    from .store import DataSource

    changed = []
    for ref in list(runtime.refs.values()):
        if ref.family != 'CanvasComponent':
            continue
        definition = component_definition(runtime.project, ref.control)
        snapshots = {}
        input_changed = False
        for name, custom in (definition.raw.get('CustomProperties', {}) if definition else {}).items():
            if custom.get('RaiseOnReset') is not True:
                continue
            try:
                if validate_kind(custom) != 'Input':
                    continue
                value = ref.property(name)
            except FxError as error:
                runtime.observe_property_error(ref, name, error)
                continue
            runtime.app_errors.healthy(ref.path + '.' + name)
            snapshot = serial(value.rows() if isinstance(value, DataSource) else value)
            snapshots[name] = snapshot
            key = (ref.path, name)
            if key in runtime.component_input_baselines and runtime.component_input_baselines[key] != snapshot:
                input_changed = True
            runtime.component_input_baselines[key] = snapshot
        blocked = runtime.component_reset_blocks.get(ref.path)
        if blocked is not None:
            # Failed inputs retain their last healthy baseline and cannot rearm
            # a loop. A healthy changed input can.
            if snapshots and all(name in blocked and blocked[name] == value for name, value in snapshots.items()):
                continue
            if not snapshots and blocked:
                continue
            runtime.component_reset_blocks.pop(ref.path, None)
            if reset_counts is not None:
                reset_counts.pop(ref.path, None)
            runtime.app_errors.healthy(ref.path + '.OnReset')
            runtime.trace_event('component-feedback', control=ref.path, status='rearmed')
        if input_changed:
            changed.append(ref)
    return changed


def block_feedback(runtime, ref):
    from .expressions import mapped

    runtime.component_reset_blocks[ref.path] = {
        name: value for (path, name), value in runtime.component_input_baselines.items() if path == ref.path
    }
    definition = component_definition(runtime.project, ref.control)
    expression = mapped(definition.properties, 'OnReset', definition.source, ref.path + '.OnReset', ref.path)
    error = expression.locate(FxError(
        f'Component input reset feedback exceeded the simulator limit of {RESET_LIMIT} resets: {ref.path}. '
        'Automatic resets are suspended until a reset-triggering input changes or an explicit Reset runs.', 'Cycle'))
    runtime.observe_property_error(ref, 'OnReset', error)
    runtime.trace_event('component-feedback', control=ref.path, status='blocked', limit=RESET_LIMIT)


def rearm(runtime, ref):
    if runtime.component_reset_blocks.pop(ref.path, None) is not None:
        runtime.app_errors.healthy(ref.path + '.OnReset')
        runtime.trace_event('component-feedback', control=ref.path, status='rearmed')

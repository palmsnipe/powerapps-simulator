"""Canvas component property contracts shared by the binder and runtime."""
from .syntax import FxError


def property_kind(custom):
    kind = custom.get("PropertyKind", "Input")
    if kind == "Data":
        return custom.get("PropertyDefinition", custom.get("Direction", "Input"))
    return {"InputFunction": "Function", "OutputFunction": "Function"}.get(kind, kind)


def component_definition(project, control):
    if control.kind == "Component":
        return control
    if control.family == "CanvasComponent":
        return project.components.get(control.raw.get("ComponentName"))
    return None


def access_app_scope(project, instance):
    definition = component_definition(project, getattr(instance, "control", instance))
    raw = definition.raw if definition else {}
    value = raw.get("AccessAppScope", raw.get("Properties", {}).get("AccessAppScope", False))
    return value is True or str(value).casefold() in ("=true", "true")


def custom_parameters(custom):
    parameters = custom.get('Parameters', [])
    if not isinstance(parameters, list) or any(not isinstance(p, dict) or len(p) != 1 for p in parameters):
        raise FxError('Component Parameters must be a list of named parameter specifications', 'Type')
    result = [(name, spec) for parameter in parameters for name, spec in parameter.items()]
    if any(not isinstance(name, str) or not name or not isinstance(spec, dict) for name, spec in result):
        raise FxError('Component parameters require a name and a specification', 'Type')
    if len({name for name, _ in result}) != len(result):
        raise FxError('Component parameter names must be unique', 'Type')
    return result


def required_parameters(custom):
    return max((i + 1 for i, (_, spec) in enumerate(custom_parameters(custom)) if not optional_parameter(spec)), default=0)


def optional_parameter(spec):
    value = spec.get('IsOptional', False)
    if not isinstance(value, bool):
        raise FxError('Component parameter IsOptional must be Boolean', 'Type')
    return value


def arity_message(custom):
    minimum, maximum = required_parameters(custom), len(custom_parameters(custom))
    count = str(maximum) if minimum == maximum else f'{minimum}–{maximum}'
    return f'expects {count} arguments'


def result_type_name(custom):
    return custom.get('DataType') if property_kind(custom) in ('Input', 'Output') else custom.get('ReturnType', custom.get('DataType'))


def validate_kind(custom):
    kind = property_kind(custom)
    if kind not in ("Input", "Output", "Function", "Action", "Event"):
        raise FxError(f"Unsupported component property kind {kind}", "Unsupported")
    return kind


class ComponentCallable:
    def __init__(self, runtime, instance, name, custom):
        self.runtime, self.instance, self.name, self.custom = runtime, instance, name, custom
        self.behavior = validate_kind(custom) in ("Action", "Event")

    def __call__(self, values):
        return self.runtime.component_call(self.instance, self.name, self.custom, values, getattr(self, 'argument_types', None))

    def validate_arguments(self, types):
        from .binding import function_compatible
        specs = self.runtime.component_signature(self.name, self.custom,self.instance)
        if not required_parameters(self.custom) <= len(types) <= len(specs):
            raise FxError(f'Component {self.name} {arity_message(self.custom)}', 'Type')
        for actual, (_, spec) in zip(types, specs):
            expected = self.runtime.binder.parameter_type(spec)
            if actual and not function_compatible(actual, expected, restrictive=False):
                raise FxError(f'{self.name}: expected {expected.describe()}, received {actual.describe()} (incompatible component contract)', 'Type')
        self.argument_types = types

"""Component contracts and explicitly requested data-property observation.

Contract discovery never evaluates formulas. Data observation uses the same pure
property access as the control inspector; callable properties are never invoked.
"""
from .components import component_definition, access_app_scope, validate_kind, required_parameters, result_type_name, optional_parameter
from .inspection import schema
from .binding import value_type
from .syntax import FxError
from .expressions import parameter_expression


def describe(runtime, *, evaluate=False):
    from .runtime import serial
    instances = {}
    for path, ref in sorted(runtime.refs.items()):
        definition = component_definition(runtime.project, ref.control)
        if definition is None:
            continue
        properties = {}
        for name, custom in definition.raw.get('CustomProperties', {}).items():
            entry = {'description': custom.get('Description', ''), 'source': definition.source}
            properties[name] = entry
            try:
                kind = validate_kind(custom)
                specs = runtime.component_signature(name, custom,ref)
                input_function = custom.get('PropertyKind') == 'InputFunction' or custom.get('PropertyDefinition', custom.get('Direction', 'Output')) == 'Input'
                entry.update(kind=kind, declared_type=result_type_name(custom),
                    formula=serial(ref.raw_property(name)), default=serial(custom.get('Default')),
                    overridden=name in ref.control.properties and (kind in ('Input', 'Event') or kind == 'Function' and input_function))
                expression=ref.expression(name)
                entry.update(source=expression.source,line=expression.line,expression_member=expression.member)
                entry['parameter_origins']={param:dict(source=origin.source,line=origin.line,expression_member=origin.member)
                    for param,spec in specs if 'Default' in spec
                    for origin in [parameter_expression(ref,name,param,spec)]}
                if kind in ('Input', 'Output'):
                    declared = runtime.binder.component_type(ref.control, name)
                    entry['type'] = declared.json()
                    entry['raise_on_reset'] = custom.get('RaiseOnReset', False) is True
                    if evaluate:
                        try:
                            value = ref.property(name)
                        except FxError as error:
                            value = error
                        entry.update(value=serial(value), type=schema(value_type(value), declared))
                else:
                    required = required_parameters(custom)
                    entry.update(minimum_arguments=required,maximum_arguments=len(specs))
                    entry['parameters'] = [dict(name=param, type=runtime.binder.parameter_type(spec).json(),
                        required=not optional_parameter(spec), optional=optional_parameter(spec),
                        **({'default': serial(spec['Default'])} if 'Default' in spec else {}))
                        for index, (param, spec) in enumerate(specs)]
                    entry['type'] = runtime.fx.declared_contract(result_type_name(custom), component=True).json()
            except FxError as error:
                entry['error'] = serial(error)
        instances[path] = dict(name=ref.name, definition=definition.name, source=ref.control.source,
            access_app_scope=access_app_scope(runtime.project, ref), properties=properties)
    return instances

"""Pure metadata queries for local sources and metadata-free tables."""
from .syntax import FxError

COLUMN_INFO = {'DisplayName', 'MaxLength', 'MinValue', 'MaxValue', 'Required'}
SOURCE_INFO = {'AllowedValues', 'CreatePermission', 'DeletePermission', 'EditPermission', 'ReadPermission'}


def selector(node, legacy):
    if node.kind == 'member' and node.children[0].kind in ('name', 'global') and node.children[0].value == 'DataSourceInfo':
        return node.value
    if legacy and node.kind == 'literal' and isinstance(node.value, str):
        return node.value
    raise FxError('DataSourceInfo information must be a literal DataSourceInfo member', 'Unsupported', node.start, node.end)


def column(node):
    if node.kind == 'name' or node.kind == 'literal' and isinstance(node.value, str):
        return node.value
    raise FxError('DataSourceInfo column must be an identifier or literal column name', 'Type', node.start, node.end)


def contract(args, legacy):
    info = selector(args[1], legacy)
    if info not in COLUMN_INFO | SOURCE_INFO:
        raise FxError('Unknown DataSourceInfo information ' + info, 'Name', args[1].start, args[1].end)
    if info in COLUMN_INFO and len(args) != 3:
        raise FxError('DataSourceInfo.' + info + ' requires a column name', 'Type', args[1].start, args[1].end)
    if info in SOURCE_INFO and len(args) != 2:
        raise FxError('DataSourceInfo.' + info + ' does not accept a column name', 'Type', args[2].start, args[2].end)
    return info


def bind(binder, node, scope):
    from .binding import BOOLEAN, TEXT
    args = node.children[1:]
    source = binder.infer(args[0], scope)
    if source.kind not in ('Table', 'Unknown', 'Error'):
        binder.issue('DataSourceInfo requires a table or data source', args[0], 'Type')
    try:
        info = contract(args, binder.runtime.environment.get('enum_mode') != 'strong')
        if info in COLUMN_INFO:
            name = column(args[2])
            row = source.row
            if row and not row.open and name not in row.fields and row.aliases.get(name) not in row.fields:
                binder.issue('Unknown DataSourceInfo column ' + name, args[2], 'Name')
    except FxError as error:
        binder.issue(error.message, next((arg for arg in args if arg.start == error.start), args[1]), error.kind)
        return binder.default_number()
    return TEXT if info == 'DisplayName' else BOOLEAN if info in SOURCE_INFO | {'Required'} else binder.default_number()


def evaluate(fx, args, ctx):
    from .store import DataSource
    from .binding import schema_type
    info = contract(args, fx.host.environment.get('enum_mode') != 'strong')
    source = fx.eval(args[0], ctx)
    if not isinstance(source, (DataSource, list)):
        raise FxError('DataSourceInfo requires a table or data source', 'Type')
    definition = None
    if isinstance(source, DataSource):
        definition = fx.host.reactive.leaf(('datasource-info-schema', source.name), lambda: source.store.definitions[source.name])
    if info in SOURCE_INFO:
        # No inferred authentication: writable is the existing local write gate.
        return None if info == 'AllowedValues' else info == 'ReadPermission' or definition is None or definition.get('writable', True)
    name = column(args[2])
    if definition is None:
        typ = fx.node_types.get(id(args[0]))
        row = typ.row if typ else None
        if row and not row.open and name not in row.fields and row.aliases.get(name) not in row.fields:
            raise FxError('Unknown DataSourceInfo column ' + name, 'Name', args[2].start, args[2].end)
        # Collections and computed tables expose no connector constraints.
        return name if info == 'DisplayName' else False if info == 'Required' else None
    key = source.store.internal_name(source.name, name)
    if key not in definition['fields']:
        raise FxError('Unknown DataSourceInfo column ' + name, 'Name', args[2].start, args[2].end)
    field = definition['fields'][key]
    if info == 'DisplayName':
        return definition.get('mapping', {}).get(key, field.get('title', key))
    if info == 'Required':
        return key in definition.get('required', []) or field.get('required') is True
    kind = schema_type(field).kind
    limit = None
    if info == 'MaxLength' and kind == 'Text':
        limit = field.get('maxLength')
    elif info in ('MinValue', 'MaxValue') and kind in ('Number', 'Decimal'):
        limit = field.get('minimum' if info == 'MinValue' else 'maximum')
    return fx.numeric_argument(limit) if limit is not None else None

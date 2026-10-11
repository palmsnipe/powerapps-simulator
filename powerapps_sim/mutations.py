"""Record replacement and scoped conditional writes for local mutable tables."""
from .syntax import FxError, call_name
from .store import DataSource
from .tables import derived_record


_UNSET = object()


def target(runtime, node, ctx, fx, value=_UNSET):
    source = node.children[0] if node.kind == 'alias' else node
    value = fx.eval(source, ctx) if value is _UNSET else value
    name = call_name(source) if source.kind in ('name', 'global') else None
    collections = runtime.scope_values(ctx, 'collections')
    if source.kind == 'name' and any(name in frame for frame in ctx.frames):
        raise FxError('Mutation target is a read-only record scope or parameter', 'ReadOnlyValue')
    if isinstance(value, DataSource) and name:
        return value, None, None
    if name and (name in collections or name in runtime.known_collections and name not in runtime.known_globals):
        return None, collections, name
    raise FxError('Mutation requires a mutable collection or local data source', 'InvalidArgument')


def record_value(value, operation):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise FxError(f'{operation} requires a record', 'Type')
    return value


def matches(current, old):
    """Mutation matching keeps Blank separate from zero/empty text/false."""
    from .fx import observe
    observe(current); observe(old)
    if current is None or old is None:
        return current is old
    if isinstance(current, dict) or isinstance(old, dict):
        return isinstance(current, dict) and isinstance(old, dict) and current.keys() == old.keys() and all(matches(current[k], old[k]) for k in old)
    if isinstance(current, list) or isinstance(old, list):
        return isinstance(current, list) and isinstance(old, list) and len(current) == len(old) and all(matches(a, b) for a, b in zip(current, old))
    if isinstance(current, bool) or isinstance(old, bool):
        return type(current) is type(old) and current == old
    return current == old


def canonical_fields(value, template):
    aliases = {logical:display for display,logical in getattr(template, 'logical_names', {}).items()}
    result = {}
    for key, cell in value.items():
        canonical = key if key in template else aliases.get(key, key)
        if canonical in result:
            raise FxError(f'Duplicate aliases for update column {canonical}', 'InvalidArgument')
        result[canonical] = cell
    return result


def change_record(fx, raw, expected, actual=None):
    """Coerce only authored fields; partial updates must not blank other columns."""
    from .binding import UNKNOWN, function_compatible
    from .fx import capture
    if expected and expected.kind == 'Record':
        canonical = {key: key if key in expected.fields else expected.aliases.get(key, key) for key in raw}
        unknown = set(canonical.values()) - expected.fields.keys()
        if unknown and not expected.open:
            raise FxError(f'Unknown update column {next(iter(unknown))}', 'Name')
        for key in raw:
            typ = expected.fields.get(canonical[key], UNKNOWN)
            got = actual.fields.get(key, UNKNOWN) if actual and actual.kind == 'Record' else UNKNOWN
            if not function_compatible(got, typ):
                raise FxError(f'{key}: expected {typ.describe()}, received {got.describe()}', 'Type')
        return {key:capture(lambda: fx.coerce_function(value, expected.fields.get(canonical[key], UNKNOWN), actual.fields.get(key) if actual and actual.kind=='Record' else None)) for key,value in raw.items()}
    return dict(raw)


def execute(runtime, operation, args, ctx, fx):
    from .fx import truth, observe
    source, collections, name = target(runtime, args[0], ctx, fx)
    from contextlib import nullcontext
    from .data_errors import operation as data_operation
    with data_operation(runtime.store,source.name,capture=False) if source else nullcontext():
        try:
            return _execute_table(runtime,operation,args,ctx,fx,source,collections,name)
        finally:
            runtime.invalidate()


def _execute_table(runtime,operation,args,ctx,fx,source,collections,name):
    from .fx import truth, observe
    typ = fx.node_types.get(id(args[0]))
    expected = typ.row if typ and typ.kind == 'Table' else None
    if operation == 'Update':
        old = record_value(fx.eval(args[1], ctx), 'Update old record')
        raw = record_value(fx.eval(args[2], ctx), 'Update replacement')
        if source:
            if isinstance(runtime.store.internal(source.name, old).get('ID'), bool):
                raise FxError('Update identity requires an integer ID', 'Type')
        old = change_record(fx, old, expected, fx.node_types.get(id(args[1])))
        if source:
            identity = observe(runtime.store.internal(source.name, old).get('ID'))
        replacement = change_record(fx, raw, expected, fx.node_types.get(id(args[2])))
        all_copies = len(args) == 4
        if all_copies and fx.eval(args[3], ctx) != 'All':
            raise FxError('Update flag must be RemoveFlags.All', 'InvalidArgument')
    elif (len(args) - 1) % 2:
        raise FxError('UpdateIf requires condition/change-record pairs', 'InvalidArgument')
    if source:
        from .data_errors import operation as data_operation
        with data_operation(runtime.store,source.name,old if operation=='Update' else None):
            runtime.store.check_failure(source.name, 'write')
            if not runtime.store.definitions[source.name].get('writable', True):
                raise FxError(f'{source.name} is read-only', 'ReadOnlyValue')
        with data_operation(runtime.store,source.name,old if operation=='Update' else None):
            rows = source.rows()
    else:
        rows = list(collections.get(name, []))
    errors, found = [], False
    columns = set().union(*(row.keys() for row in rows if isinstance(row, dict))) if rows else set()
    for index, row in enumerate(rows):
        try:
            observe(row)
            if operation == 'Update':
                selected = runtime.store.internal(source.name, row).get('ID') == identity and identity is not None if source else matches(row, canonical_fields(old, row))
                if not selected:
                    continue
                found = True
                change = replacement
            else:
                row_ctx = fx.row_context(args[0], row, ctx)
                change = None
                for i in range(1, len(args), 2):
                    condition = fx.eval(args[i], row_ctx)
                    if condition is not None and not isinstance(condition, bool):
                        raise FxError('UpdateIf condition requires a Boolean', 'Type')
                    if truth(condition):
                        raw = record_value(fx.eval(args[i + 1], row_ctx), 'UpdateIf change')
                        change = change_record(fx, raw, expected, fx.node_types.get(id(args[i + 1])))
                        break
                if change is None:
                    continue
            change = canonical_fields(change, row)
            if source:
                if operation == 'Update':
                    runtime.store.replace(source.name, row, change)
                else:
                    internal = runtime.store.internal(source.name, change)
                    if 'ID' in internal:
                        if internal['ID'] != runtime.store.internal(source.name, row).get('ID'):
                            raise FxError('ID is read-only', 'ReadOnlyValue',column='ID')
                        change = {key:value for key,value in change.items() if runtime.store.internal_name(source.name,key) != 'ID'}
                    if any(key in internal for key in ('Created','Modified')):
                        raise FxError('Audit timestamps are read-only', 'ReadOnlyValue')
                    runtime.store.patch(source.name, row, change)
            else:
                current = collections.get(name, [])
                position = index if index < len(current) and current[index] is row else next((i for i, value in enumerate(current) if value is row), None)
                if position is None:
                    raise FxError('Collection record disappeared during update', 'NotFound')
                fields = {key:None for key in columns} if operation == 'Update' else dict(row)
                fields.update(change)
                current[position] = derived_record(row, fields)
            runtime.invalidate()
        except FxError as error:
            if source and error.column is not None:
                from .data_errors import note
                note(runtime.store,source.name,error,row)
            errors.append(error)
        if operation == 'Update' and found and not all_copies:
            break
    if operation == 'Update' and not found:
        error = FxError('Update record was not found', 'NotFound')
        if source:
            from .data_errors import note
            note(runtime.store,source.name,error,old)
        errors.append(error)
    if errors:
        raise FxError.combine(errors)
    return source.rows() if source else list(collections.get(name, []))

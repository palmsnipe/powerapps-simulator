"""Pure local data-source validation and shared declared range constraints."""
from datetime import date, datetime, timezone
from decimal import Decimal
import math

from .syntax import FxError


def bound_value(value, field):
    kind = field.get('type')
    if kind in ('number', 'integer'):
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(value):
            raise ValueError('a finite number is required')
        return value
    if kind == 'string' and field.get('format') == 'date':
        return date.fromisoformat(value)
    if kind == 'string' and field.get('format') == 'date-time':
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    raise ValueError('range constraints require a numeric or date field')


def validate_bounds(label, field):
    limits = {}
    for key in ('minimum', 'maximum'):
        if field.get(key) is not None:
            try:
                limits[key] = bound_value(field[key], field)
            except (ValueError, TypeError, AttributeError, OverflowError):
                raise FxError(f'{label}: invalid {key} constraint', 'Validation') from None
    if len(limits) == 2 and limits['minimum'] > limits['maximum']:
        raise FxError(f'{label}: minimum exceeds maximum', 'Validation')


def check_bounds(label, value, field):
    if value is None or all(field.get(key) is None for key in ('minimum', 'maximum')):
        return
    try:
        actual = bound_value(value, field)
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise FxError(f'{label} has an invalid range value', 'Validation') from None
    for key, relation in (('minimum', lambda a, b: a < b), ('maximum', lambda a, b: a > b)):
        if field.get(key) is not None and relation(actual, bound_value(field[key], field)):
            raise FxError(f'{label} is outside the allowed range ({key}: {field[key]})', 'Validation')


def bind(binder, node, scope):
    from .binding import TEXT
    from .patch import safe_field
    args = node.children[1:]
    source = binder.infer(args[0], scope)
    if source.kind not in ('Table', 'Unknown', 'Error'):
        binder.issue('Validate requires a table or data source', args[0], 'Type')
    row = source.row
    fields = row.fields if row else {}
    aliases = row.aliases if row else {}
    second = args[1]
    column = second.kind == 'literal' and isinstance(second.value, str) or second.kind == 'name' and aliases.get(second.value, second.value) in fields
    if column:
        key = aliases.get(second.value, second.value)
        wanted = fields.get(key)
        if wanted is None and row and not row.open:
            binder.issue('Unknown Validate column ' + second.value, second, 'Name')
        actual = binder.infer(args[2], scope)
        if wanted and not safe_field(actual, wanted):
            binder.issue(second.value + ': incompatible Validate field type; use an explicit conversion', args[2], 'Type')
    else:
        original = binder.infer(second, scope)
        updates = binder.infer(args[2], scope)
        for value, arg in ((original, second), (updates, args[2])):
            if value.kind not in ('Record', 'Blank', 'Unknown', 'Error'):
                binder.issue('Validate requires a column name or original and update records', arg, 'Type')
            for key, actual in value.fields.items():
                wanted = fields.get(aliases.get(key, key))
                if wanted is None and row and not row.open:
                    binder.issue('Unknown Validate record column ' + key, arg, 'Name')
                elif wanted and not safe_field(actual, wanted):
                    binder.issue(key + ': incompatible Validate record field type; use an explicit conversion', arg, 'Type')
    return TEXT


def evaluate(fx, args, ctx):
    from .store import DataSource, reject_errors
    source = fx.eval(args[0], ctx)
    if not isinstance(source, (DataSource, list)):
        raise FxError('Validate requires a table or data source', 'Type')
    second = args[1]
    if second.kind == 'name' and isinstance(source, DataSource):
        key = source.store.internal_name(source.name, second.value)
        column = key in source.store.definitions[source.name]['fields']
    elif second.kind == 'name' and isinstance(source, list):
        typ = fx.node_types.get(id(args[0]))
        row = typ.row if typ else None
        column = row is not None and row.aliases.get(second.value, second.value) in row.fields or any(isinstance(record, dict) and second.value in record for record in source)
        if not column:
            try:
                fx.eval(second, ctx)
            except FxError as error:
                if error.kind != 'Name':
                    raise
                column = True
    else:
        column = second.kind == 'literal' and isinstance(second.value, str)
    if column:
        name = second.value
        updates = {name: fx.capture(args[2], ctx)}
        original = {}
    else:
        original, updates = fx.eval(second, ctx), fx.eval(args[2], ctx)
        if any(value is not None and not isinstance(value, dict) for value in (original, updates)):
            raise FxError('Validate requires original and update records', 'Type')
    if isinstance(source, list):
        return None  # Collections have no connector validation metadata.
    store = source.store
    original = store.internal(source.name, original or {})
    updates = store.internal(source.name, updates or {})
    merged = {**original, **updates}
    reject_errors(merged)  # Formula errors remain errors, rather than validation text.
    for key in merged:
        if key not in store.definitions[source.name]['fields']:
            raise FxError('Unknown Validate column ' + key, 'Name')
    from .binding import schema_type, value_type
    from .patch import safe_field
    for record in (original, updates):
        for key, value in record.items():
            wanted = schema_type(store.definitions[source.name]['fields'][key])
            if not safe_field(value_type(value), wanted):
                raise FxError(key + ': incompatible Validate field type; use an explicit conversion', 'Type')
    merged = {key: fx.coerce_function(value, schema_type(store.definitions[source.name]['fields'][key]), value_type(value), restrictive=False) for key, value in merged.items()}
    # Metadata is a dependency even if there are no rows or the list cannot be read.
    fx.host.reactive.leaf(('validation-schema', source.name), lambda: store.definitions[source.name])
    # Relationship constraints can change after local writes to a lookup target.
    for target in set(store.definitions[source.name].get('lookups', {}).values()):
        fx.host.reactive.leaf(('validation-lookup', target), lambda target=target: [r[0] for r in store.db.execute('SELECT id FROM items WHERE list_name=? ORDER BY id', (target,))])
    try:
        store.validate(source.name, merged, fields=set(updates) if column else None)
    except FxError as error:
        if error.kind not in ('Validation', 'MissingRequired'):
            raise
        return error.message
    return None

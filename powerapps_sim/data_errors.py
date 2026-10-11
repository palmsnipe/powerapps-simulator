"""Session-local connector error tables, grouped by a single data operation."""
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps

from .syntax import FxError
from .errors import error_number


def clear(store, name=None):
    if name is None:
        store.operation_errors.clear()
        store.error_seen.clear()
    else:
        store.operation_errors[name] = []
        store.error_seen[name] = set()


def record_value(store, name, record):
    """Snapshot the failed existing row; failed creates have a Blank Record."""
    if not isinstance(record, dict):
        return None
    internal = store.internal(name, record)
    identity = internal.get('ID')
    if identity is None:
        return None
    from .numeric import NUMBERS
    if not isinstance(identity, bool) and isinstance(identity, NUMBERS):
        try:
            valid = int(identity) == identity and 0 < int(identity) <= 2**63-1
        except (ValueError, OverflowError):
            valid = False
        if valid:
            import json
            saved = store.db.execute('SELECT record FROM items WHERE list_name=? AND id=?', (name, int(identity))).fetchone()
            if saved:
                return deepcopy(store.source(name).record(store.display(name, json.loads(saved[0]))))
    return deepcopy(store.source(name).record(store.display(name, internal)))


def note(store, name, error, record=None):
    if error.errors:
        for child in error.errors:
            note(store, name, child, record)
        return
    seen = store.error_seen.setdefault(name, set())
    if id(error) in seen:
        return
    seen.add(id(error))
    # Retain exception objects for the operation: object IDs cannot be recycled
    # and mistaken for an already captured error while a batch is executing.
    store.operation_errors.setdefault(name, []).append((error, {
        'Record': record_value(store, name, record), 'Column': getattr(error, 'column', None),
        'Message': error.message, 'Error': error_number(error.kind)}))


@contextmanager
def operation(store, name, record=None, *, capture=True):
    outer = not store.operation_depth.get(name, 0)
    if outer:
        clear(store, name)
    store.operation_depth[name] = store.operation_depth.get(name, 0) + 1
    try:
        yield
    except FxError as error:
        if capture:
            note(store, name, error, record)
        raise
    finally:
        store.operation_depth[name] -= 1


def tracked_write(method):
    @wraps(method)
    def wrapped(store, name, *args, **kwargs):
        record = args[0] if args else kwargs.get('base',kwargs.get('record'))
        with operation(store, name, record):
            return method(store, name, *args, **kwargs)
    return wrapped


def rows(store, name, record=None, *, filtered=False):
    store.source(name)  # Validate source without reading or clearing its errors.
    result = [entry for _, entry in store.operation_errors.get(name, [])]
    if filtered:
        if record is not None and not isinstance(record, dict):
            raise FxError('Errors record must be a record or Blank', 'Type')
        origin = getattr(record, 'source_name', None)
        if origin and origin != name:
            raise FxError('Errors record must belong to the target data source', 'InvalidArgument')
        marker = getattr(record, 'defaults_for', None)
        if marker and marker != ('source', name):
            raise FxError('Errors Defaults must belong to the target data source', 'InvalidArgument')
        identity = store.internal(name, record).get('ID') if record is not None else None
        if isinstance(identity, FxError):
            raise identity
        if identity is not None:
            identity = store.remove_identity(name, record)
        result = [entry for entry in result if (entry['Record'] is None if identity is None else
            entry['Record'] is not None and store.internal(name, entry['Record']).get('ID') == identity)]
    return deepcopy(result)


def bind(binder, node, scope):
    from .binding import record, tabular, TEXT, NUMBER, OPEN_RECORD, compatible
    args = node.children[1:]
    source = binder.infer(args[0], scope)
    name = args[0].value if args[0].kind in ('name', 'global') else None
    from .components import access_app_scope
    local = scope.component and not access_app_scope(binder.runtime.project, scope.component)
    shadowed = args[0].kind == 'name' and any(name in frame for frame in scope.frames)
    if local or shadowed or name not in binder.runtime.store.definitions or source.kind != 'Table':
        binder.issue('Errors requires a direct local data source', args[0], 'Type')
    row = source.row or OPEN_RECORD
    if len(args) > 1:
        actual = binder.infer(args[1], scope)
        if actual.kind not in ('Record', 'Blank', 'Unknown', 'Error'):
            binder.issue('Errors record must be a record or Blank', args[1], 'Type')
        for key,field in actual.fields.items():
            canonical = row.aliases.get(key,key)
            wanted = row.fields.get(canonical)
            if wanted is None and not row.open:
                binder.issue('Unknown Errors record column '+key,args[1],'Name')
            elif wanted and not compatible(field,wanted):
                binder.issue(key+': incompatible Errors record field type',args[1],'Type')
    return tabular(record({'Record': row, 'Column': TEXT, 'Message': TEXT, 'Error': NUMBER}))

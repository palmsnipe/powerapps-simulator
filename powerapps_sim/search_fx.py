"""Search contracts and mapped-column resolution for local Power Fx tables."""
from .syntax import FxError
from .tables import column_name


def columns(fields, nodes, aliases=None, open_schema=False):
    aliases = aliases or {}
    result = []
    for node in nodes:
        name = column_name(node)
        physical = name if name in fields else aliases.get(name, name)
        if physical not in fields and not open_schema:
            raise FxError(f'Unknown column {name}', 'Name', node.start, node.end)
        result.append(physical)
    return result


def bind(binder, args, scope):
    from .binding import OPEN_RECORD, tabular
    source = binder.infer(args[0], scope)
    binder.require(source, tabular(), args[0], 'Search source')
    if source.kind in ('Dynamic', 'Blank'):
        binder.issue('Search source requires a table', args[0])
    query = binder.infer(args[1], scope)
    if query.kind not in ('Text', 'Blank', 'Error', 'Unknown'):
        binder.issue('Search string requires Text without coercion', args[1])
    row = source.row or OPEN_RECORD
    try:
        selected = columns(row.physical_fields(), args[2:], row.aliases, row.open)
    except FxError as error:
        binder.issue(error.message, next(n for n in args[2:] if n.start == error.start), error.kind)
        return source
    for name, node in zip(selected, args[2:]):
        typ = row.physical_fields().get(name)
        if typ and typ.kind not in ('Text', 'Unknown'):
            binder.issue(f'Search column {name} requires Text', node)
    return source


def evaluate(fx, args, ctx):
    from .fx import capture, observe, table
    from .store import DataSource
    # Search arguments are eager, even for a Blank source or empty query.
    source = capture(lambda: fx.eval(args[0], ctx))
    query = capture(lambda: fx.eval(args[1], ctx))
    errors = [value for value in (source, query) if isinstance(value, FxError)]
    if errors:
        raise FxError.combine(errors)
    if source is not None and not isinstance(source, (list, DataSource)):
        raise FxError('Search requires a table', 'Type', args[0].start, args[0].end)
    if query is not None and not isinstance(query, str):
        raise FxError('Search requires a Text search string', 'Type', args[1].start, args[1].end)
    rows = table(source)
    typ = fx.node_types.get(id(args[0]))
    if typ and typ.kind not in ('Table', 'Error', 'Unknown'):
        raise FxError('Search requires a typed table', 'Type', args[0].start, args[0].end)
    row_type = typ.row if typ and typ.kind == 'Table' else None
    fields = set(row_type.physical_fields()) if row_type else set()
    aliases = dict(row_type.aliases) if row_type else {}
    for row in rows:
        if isinstance(row, dict):
            fields.update(row)
            aliases.update({logical: display for display, logical in getattr(row, 'logical_names', {}).items()})
    selected = columns(fields, args[2:], aliases, bool(row_type and row_type.open))
    for name, node in zip(selected, args[2:]):
        field = row_type.physical_fields().get(name) if row_type else None
        if field and field.kind not in ('Text', 'Unknown'):
            raise FxError(f'Search column {name} requires Text', 'Type', node.start, node.end)
    if source is None:
        return None
    if not query:
        return rows
    language = str(fx.host.environment.get('language', 'en-CA')).lower().split('-')[0]
    def lower(value):
        return value.replace('I', 'ı').replace('İ', 'i').lower() if language in ('tr', 'az') else value.lower()
    query = lower(query)
    result = []
    for row in rows:
        observe(row)
        if row is None:
            continue
        for name, node in zip(selected, args[2:]):
            value = fx.member(row, name, ctx)
            if value is None:
                continue
            if not isinstance(value, str):
                raise FxError(f'Search column {name} requires Text', 'Type', node.start, node.end)
            if query in lower(value):
                result.append(row)
                break
    return result

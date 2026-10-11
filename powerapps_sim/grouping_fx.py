"""Canvas grouped tables with mapped names and preserved nested value metadata."""
from .syntax import FxError
from .tables import OrderedRecord, SourceRecord, derived_record, query_columns


def aliases_for(fields, *mappings):
    """Retain unambiguous logical names for physical fields that still exist."""
    targets = {}
    for mapping in mappings:
        for logical, physical in mapping.items():
            if physical in fields:
                targets.setdefault(logical, set()).add(physical)
    return {logical: next(iter(physical)) for logical, physical in targets.items() if len(physical) == 1}


def bind(binder, name, args, scope):
    from .binding import OPEN_RECORD, UNKNOWN, record, tabular
    source = binder.infer(args[0], scope)
    binder.require(source, tabular(), args[0], name)
    if source.kind in ('Dynamic', 'Blank'):
        binder.issue(f'{name} source requires a table', args[0])
    row = source.row or OPEN_RECORD
    fields = row.physical_fields()
    try:
        columns = query_columns(name, fields, args[1:], row.open, row.aliases)
    except FxError as error:
        binder.issue(error.message, next((n for n in args[1:] if n.start == error.start), args[0]), error.kind)
        return UNKNOWN
    if name == 'GroupBy':
        keys, nested = columns[:-1], columns[-1]
        remaining = {k: v for k, v in fields.items() if k not in keys}
        inner = record(remaining, row.open, aliases_for(remaining, row.aliases))
        outer = {**{k: fields.get(k, UNKNOWN) for k in keys}, nested: tabular(inner)}
        return tabular(record(outer, False, aliases_for(keys, row.aliases)))
    nested, = columns
    inner = fields.get(nested, UNKNOWN)
    binder.require(inner, tabular(), args[1], 'Ungroup column')
    inner_row = inner.row or OPEN_RECORD
    outer = {k: v for k, v in fields.items() if k != nested}
    if outer.keys() & inner_row.physical_fields().keys():
        binder.issue('Ungroup columns overlap outer record fields', args[1])
    merged = {**outer, **inner_row.physical_fields()}
    return tabular(record(merged, row.open or inner_row.open, aliases_for(merged, row.aliases, inner_row.aliases)))


def merged_record(outer, child, fields):
    # Child lineage restores grouped source order; parent metadata supplies keys.
    carrier = child if isinstance(child, (SourceRecord, OrderedRecord)) else outer
    result = derived_record(carrier, fields)
    aliases = aliases_for(fields, *({logical: physical for physical, logical in getattr(value, 'logical_names', {}).items()} for value in (outer, child)))
    logical_names = {physical: logical for logical, physical in aliases.items()}
    if hasattr(result, 'logical_names'):
        result.logical_names = logical_names
    elif logical_names:
        result = SourceRecord(result, logical_names)
    return result


def evaluate(fx, name, args, ctx):
    from .fx import observe, table
    from .store import DataSource
    source = fx.eval(args[0], ctx)
    if source is not None and not isinstance(source, (list, DataSource)):
        raise FxError(f'{name} requires a table', 'Type', args[0].start, args[0].end)
    typ = fx.node_types.get(id(args[0]))
    if typ and typ.kind not in ('Table', 'Error', 'Unknown'):
        raise FxError(f'{name} requires a typed table', 'Type', args[0].start, args[0].end)
    rows = table(source)
    row_type = typ.row if typ and typ.kind == 'Table' else None
    fields = set(row_type.physical_fields()) if row_type else set()
    aliases = dict(row_type.aliases) if row_type else {}
    for row in rows:
        if isinstance(row, dict):
            fields.update(row)
            aliases.update({logical: physical for physical, logical in getattr(row, 'logical_names', {}).items()})
    columns = query_columns(name, fields, args[1:], bool(row_type and row_type.open), aliases)
    if name == 'Ungroup' and row_type:
        field = row_type.physical_fields().get(columns[0])
        if field and field.kind not in ('Table', 'Blank', 'Unknown', 'Error'):
            raise FxError('Ungroup column requires a Table', 'Type', args[1].start, args[1].end)
        if field and field.row and (fields - set(columns)) & field.row.physical_fields().keys():
            raise FxError('Ungroup columns overlap outer record fields', 'Validation', args[1].start, args[1].end)
    if source is None:
        return None
    if name == 'GroupBy':
        keys, nested = columns[:-1], columns[-1]
        origin, groups = object(), []
        for index, row in enumerate(rows):
            observe(row)
            if row is None:
                continue
            values = {key: fx.member(row, key, ctx) for key in keys}
            group = next((g for g in groups if all((g[k] is None and values[k] is None) or (g[k] is not None and values[k] is not None and type(g[k]) is type(values[k]) and g[k] == values[k]) for k in keys)), None)
            if group is None:
                group = derived_record(row, {**values, nested: []})
                groups.append(group)
            remaining = derived_record(row, {k: v for k, v in row.items() if k not in keys})
            group[nested].append(OrderedRecord(remaining, (origin, index)))
        return groups
    nested, = columns
    result = []
    for row in rows:
        observe(row)
        if row is None:
            continue
        parent = {k: v for k, v in row.items() if k != nested}
        for child in table(fx.member(row, nested, ctx)):
            observe(child)
            if child is None:
                continue
            if not isinstance(child, dict):
                raise FxError('Ungroup requires record rows', 'Type', args[1].start, args[1].end)
            if parent.keys() & child.keys():
                raise FxError('Ungroup columns overlap outer record fields', 'Validation', args[1].start, args[1].end)
            result.append(merged_record(row, child, {**parent, **child}))
    if result and all(isinstance(row, OrderedRecord) and row.order[0] is result[0].order[0] for row in result):
        if len({row.order[1] for row in result}) == len(result):
            result.sort(key=lambda row: row.order[1])
    return result

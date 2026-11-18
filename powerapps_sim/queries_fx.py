"""Scoped Filter/LookUp queries, preserving Blank and error-valued rows."""
from .syntax import FxError
from .delegation import local_predicate

FUNCTIONS = frozenset(('Filter', 'LookUp'))
SCAN = object()


def _text_index(rows, column, shadow):
    index = {}
    for row in rows:
        # Blank or mixed keys can coerce or raise. A row field also takes
        # precedence over an outer function argument of the same name.
        if type(row) is not dict or shadow in row or type(row.get(column)) is not str:
            return None
        index.setdefault(row[column], row)
    return index


def _lookup_cached_text(fx, source_node, rows, predicate, ctx):
    cache = fx.host.formula_cache
    # Limit reuse to a named table that already belongs to the formula cache.
    # All its indexes share that cache's lifetime and invalidation.
    if (ctx.behavior or source_node.kind != 'name' or type(rows) is not list
            or not rows or cache.get(source_node.value) is not rows
            or predicate.kind != 'binary' or predicate.value != '='):
        return SCAN
    column, value = predicate.children
    if column.kind != 'name' or column.value == 'ThisRecord':
        return SCAN
    source_type = fx.node_types.get(id(source_node))
    row_type = source_type.row if source_type else None
    if row_type and row_type.aliases:
        return SCAN

    shadow = None
    if value.kind == 'literal' and value.numeric_literal is None:
        key = value.value
    elif value.kind == 'name':
        shadow = value.value
        if shadow == 'ThisRecord' or (row_type and shadow in row_type.fields):
            return SCAN
        frame = next((f for f in reversed(ctx.frames) if shadow in f), None)
        # User-defined function arguments are plain lexical values. Live row
        # frames and other scoped reads still use the normal dependency probes.
        if type(frame) is not dict:
            return SCAN
        key = frame[shadow]
        if ctx.item_probe and key is ctx.item:
            return SCAN
    else:
        return SCAN
    if type(key) is not str:
        return SCAN

    cache_key = ('text-lookup', source_node.value, column.value, shadow)
    stored_rows, index = cache.get(cache_key, (None, None))
    if stored_rows is not rows:
        index = _text_index(rows, column.value, shadow)
        cache[cache_key] = (rows, index)
    return index.get(key) if index is not None else SCAN


def evaluate(fx, name, args, ctx):
    from .fx import observe, truth
    from .store import DataSource
    arg = args[0]
    typ = fx.node_types.get(id(arg))
    if typ and typ.kind not in ('Table', 'Blank', 'Error', 'Unknown'):
        raise FxError(f'{name} requires a table', 'Type', arg.start, arg.end)
    source = fx.eval(arg, ctx)
    if source is None:
        return None
    if not isinstance(source, (list, DataSource)):
        raise FxError(f'{name} requires a table', 'Type', arg.start, arg.end)
    if name == 'LookUp' and len(args) == 2:
        row = _lookup_cached_text(fx, arg, source, args[1], ctx)
        if row is not SCAN:
            return row
    result = []
    predicates = args[1:2] if name == 'LookUp' else args[1:]
    local = local_predicate(source, arg, predicates)
    for index,row in enumerate(fx.query_rows(arg,source,ctx,local=local)):
        try:
            matches = all(truth(fx.query_row(arg,row,predicate,ctx,index)) for predicate in predicates)
        except FxError as error:
            if name == 'LookUp':
                raise
            result.append(error)
            continue
        if matches:
            if name == 'LookUp':
                observe(row)
                return fx.query_row(arg,row,args[2],ctx,index) if len(args) == 3 else row
            result.append(row)
    return None if name == 'LookUp' else result

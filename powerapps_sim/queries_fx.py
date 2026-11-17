"""Scoped Filter/LookUp queries, preserving Blank and error-valued rows."""
from .syntax import FxError
from .delegation import local_predicate

FUNCTIONS = frozenset(('Filter', 'LookUp'))


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

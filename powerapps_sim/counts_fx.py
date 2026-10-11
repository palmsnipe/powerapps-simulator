"""Counting contracts from the pinned Power Fx interpreter."""
from .syntax import FxError
from .numeric import NUMBERS
from .overloads import single_column,empty_table_literal

FUNCTIONS=frozenset(('Count','CountA','CountRows','CountIf'))

def bind(binder,name,args,scope):
    from .binding import OPEN_RECORD
    arg=args[0];typ=binder.infer(arg,scope)
    if typ.kind not in ('Table','Unknown'):
        binder.issue(f'{name} requires a single-column table',arg)
        return binder.default_number()
    row=typ.row or OPEN_RECORD
    try:
        column=single_column(row.fields,row.open and not empty_table_literal(arg),arg.start,arg.end)
        cell=row.fields.get(column)
        if name=='Count' and cell and cell.kind not in ('Number','Decimal','Blank','Error','Unknown'):
            binder.issue('Count requires a numeric column; CountA accepts other value types',arg)
    except FxError as error:binder.issue(error.message,arg,error.kind)
    return binder.default_number()

def evaluate(fx,name,args,ctx):
    from .fx import table
    from .store import DataSource
    from .json_fx import Dynamic
    from .fx import observe,truth
    arg=args[0];typ=fx.node_types.get(id(arg))
    if typ and typ.kind not in ('Table','Unknown','Blank','Error') and not (name=='CountRows' and typ.kind=='Dynamic'):
        raise FxError(f'{name} requires '+('a single-column table' if name in ('Count','CountA') else 'a table'),'Type',arg.start,arg.end)
    source=fx.eval(arg,ctx)
    if name=='CountRows' and isinstance(source,Dynamic):
        from .fx import dynamic_array
        return len(dynamic_array(source))
    if source is not None and not isinstance(source,(list,DataSource)):
        raise FxError(f'{name} requires '+('a single-column table' if name in ('Count','CountA') else 'a table'),'Type',arg.start,arg.end)
    if name=='CountRows':
        rows=fx.query_rows(arg,source,ctx)
        for row in rows:
            if isinstance(row,FxError):raise row
        return len(rows)
    if name=='CountIf':
        total=0
        for index,row in enumerate(fx.query_rows(arg,source,ctx)):
            for predicate in args[1:]:
                value=fx.query_row(arg,row,predicate,ctx,index)
                observe(value)
                if isinstance(value,NUMBERS) and not isinstance(value,bool):value=value!=0
                elif isinstance(value,str):
                    normalized=value.lower()
                    if normalized=='':value=None
                    elif normalized not in ('true','false'):
                        raise FxError('CountIf predicate cannot convert text to Boolean','InvalidArgument',predicate.start,predicate.end)
                    else:value=normalized=='true'
                if not truth(value):break
            else:total+=1
        return total
    row_type=typ.row if typ and typ.kind=='Table' else None
    fields=set(row_type.fields) if row_type else set()
    rows=fx.query_rows(arg,source,ctx)
    fields.update(key for row in rows if isinstance(row,dict) for key in row)
    column=single_column(fields,bool(row_type and row_type.open and not empty_table_literal(arg)),arg.start,arg.end)
    cell=row_type.fields.get(column) if row_type else None
    if name=='Count' and cell and cell.kind not in ('Number','Decimal','Blank','Error','Unknown'):
        raise FxError('Count requires a numeric column','Type',arg.start,arg.end)
    total=0
    for row in rows:
        if row is None:continue
        if isinstance(row,FxError):raise row
        if not isinstance(row,dict):raise FxError(f'{name} requires record rows','Type')
        value=row.get(column)
        if isinstance(value,FxError):raise value
        if value is not None and (name=='CountA' or isinstance(value,NUMBERS) and not isinstance(value,bool)):
            total+=1
    return total

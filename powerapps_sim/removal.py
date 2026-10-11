"""Canvas-style record/table removal with lexical ownership and planned matching."""
from dataclasses import replace

from .syntax import FxError
from .store import DataSource
from .patch import table_target, bind_target, snapshot
from .mutations import canonical_fields, matches
from .tables import SourceRecord, derived_record


def record_contract(raw, expected, actual=None):
    """Removal compares authored values; it never coerces or fills missing fields."""
    from .binding import compatible, value_type
    if not isinstance(raw, dict):
        raise FxError('Remove requires records or a table of records', 'Type')
    if expected and expected.kind=='Record':
        for key,value in raw.items():
            canonical = expected.aliases.get(key,key)
            field = expected.fields.get(canonical)
            if field is None:
                if not expected.open:
                    raise FxError('Unknown Remove column '+key,'Name')
                continue
            got = actual.fields.get(key) if actual and actual.kind=='Record' else None
            if got is None or got.kind=='Unknown':
                got = value_type(value)
            if not compatible(got,field):
                raise FxError(key+': incompatible Remove field type','Type')
        return derived_record(raw,canonical_fields(raw,SourceRecord({key:None for key in expected.physical_fields()},
            {display:internal for internal,display in expected.aliases.items()})))
    return raw


def record_matches(row, wanted):
    if not isinstance(row,dict):
        return False
    wanted_origin = getattr(wanted,'source_name',None)
    wanted = canonical_fields(wanted,row)
    origin = getattr(row,'source_name',None)
    if origin:
        if wanted_origin not in (None,origin):
            return False
        identity = next((display for display,internal in getattr(row,'logical_names',{}).items() if internal=='ID'),'ID')
        if wanted.get(identity) is None:
            return False
        try:
            return matches(row.get(identity),wanted[identity])
        except FxError:
            return False
    try:
        return matches(row,wanted)
    except FxError:
        # An embedded error is not a matching value. Top-level argument errors
        # propagate before planning; healthy fields/rows remain inspectable.
        return False


def execute(runtime,operation,args,ctx,fx):
    from .fx import table, observe
    # Record arguments can run actions. Resolve the mutation target only after
    # those actions, matching the upstream copy-on-write argument ordering.
    values = [snapshot(fx.capture(arg,ctx)) for arg in args[1:]] if operation=='Remove' else []
    errors = [value for value in values if isinstance(value,FxError)]
    if errors:
        raise FxError.combine(errors)
    value = fx.eval(args[0],ctx)
    source,container,key = table_target(runtime,args[0],ctx,value,operation,allow_blank=True)
    from contextlib import nullcontext
    from .data_errors import operation as data_operation
    operation_name = operation
    with data_operation(runtime.store,source.name,capture=False) if source else nullcontext():
        try:
            return _execute_table(runtime,operation_name,args,ctx,fx,value,source,container,key,values)
        finally:
            runtime.invalidate()


def _execute_table(runtime,operation,args,ctx,fx,value,source,container,key,values):
    from .fx import table, observe
    if value is None:
        return None
    if source:
        from .data_errors import operation as data_operation
        record = values[0] if operation=='Remove' and values and isinstance(values[0],dict) else None
        with data_operation(runtime.store,source.name,record):
            runtime.store.check_failure(source.name,'write')
            if not runtime.store.definitions[source.name].get('writable',True):
                raise FxError(source.name+' is read-only','ReadOnlyValue')
    if source:
        with data_operation(runtime.store,source.name,record):
            rows = list(source.rows())
    else:
        rows = list(container[key])
    typ = fx.node_types.get(id(args[0]))
    expected = typ.row if typ and typ.kind=='Table' else None
    if expected is None or expected.open and not expected.fields:
        from .binding import value_type
        typ = runtime.binder.globals.get(source.name) if source else value_type(rows)
        expected = typ.row if typ and typ.kind=='Table' else expected
    selected,errors = set(),[]
    if operation=='Remove':
        all_copies = len(values)>1 and isinstance(values[-1],str)
        if all_copies:
            if values[-1].upper()!='ALL':
                raise FxError('Remove flag must be RemoveFlags.All','InvalidArgument')
            values = values[:-1]
        table_args = [i for i,value in enumerate(values) if isinstance(value,(list,DataSource))]
        if table_args and (len(values)!=1 or table_args!=[0]):
            raise FxError('Remove accepts a single table or multiple records','Type')
        records = list(table(values[0])) if table_args else values
        argument = args[1] if table_args else None
        actual = fx.node_types.get(id(argument)) if argument else None
        actual = actual.row if actual and actual.kind=='Table' else actual
        candidates = []
        # Shapes/schema errors precede all removals; record-not-found errors are
        # accumulated alongside valid removals rather than rolling them back.
        for index,raw in enumerate(records):
            observe(raw)
            if raw is None:
                continue
            contract = actual if table_args else fx.node_types.get(id(args[index+1]))
            converted = record_contract(raw,expected,contract)
            candidates.append((raw,converted))
        for original,wanted in candidates:
            try:
                if source:
                    origin = getattr(original,'source_name',None)
                    marker = getattr(original,'defaults_for',None)
                    if origin and origin!=source.name or marker and marker!=('source',source.name):
                        raise FxError('Remove record must belong to the target data source','InvalidArgument')
                    identity = runtime.store.remove_identity(source.name,wanted)
                    found = [i for i,row in enumerate(rows) if runtime.store.internal(source.name,row).get('ID')==identity]
                else:
                    found = [i for i,row in enumerate(rows) if record_matches(row,wanted)]
                if not found:
                    raise FxError('Remove record was not found','NotFound')
                selected.update(found if all_copies else found[:1])
            except FxError as error:
                if source:
                    from .data_errors import note
                    note(runtime.store,source.name,error,original)
                errors.append(error)
    else:
        # Predicates read a stable table before writes. A failed predicate leaves
        # the table unchanged; no row is guessed to satisfy an errored condition.
        for index,row in enumerate(rows):
            try:
                observe(row)
                row_ctx = replace(fx.row_context(args[0],row,ctx),behavior=False)
                selected_row = True
                for predicate in args[1:]:
                    condition = fx.eval(predicate,row_ctx)
                    if condition is not None and not isinstance(condition,bool):
                        raise FxError('RemoveIf condition requires a Boolean','Type')
                    if condition is not True:
                        selected_row = False
                        break
                if selected_row:
                    selected.add(index)
            except FxError as error:
                errors.append(error)
        if errors:
            raise FxError.combine(errors)
    if source:
        for index in sorted(selected):
            try:
                runtime.store.remove(source.name,rows[index])
                runtime.invalidate()
            except FxError as error:
                errors.append(error)
    elif selected:
        container[key] = [row for i,row in enumerate(rows) if i not in selected]
        runtime.invalidate()
    if errors:
        raise FxError.combine(errors)
    return source.rows() if source else snapshot(container[key])


def bind(binder,node,scope,operation):
    from .binding import BOOLEAN,compatible,OPEN_RECORD
    args = node.children[1:]
    target = binder.infer(args[0],scope)
    bind_target(binder,args[0],scope,target,operation)
    row = target.row or OPEN_RECORD
    if scope.function_pure:
        binder.issue(operation+' requires a behavior formula',node)
    if operation=='RemoveIf':
        scoped = binder.row_scope(args[0],target,scope)
        scoped.behavior = False
        for arg in args[1:]:
            binder.require(binder.infer(arg,scoped),BOOLEAN,arg,'RemoveIf condition')
        return target
    types = [binder.infer(arg,scope) for arg in args[1:]]
    flag = len(types)>1 and types[-1].kind=='Text'
    if flag:
        last = args[-1]
        if last.kind=='literal' and isinstance(last.value,str) and last.value.upper()!='ALL':
            binder.issue('Remove flag must be RemoveFlags.All',last,'InvalidArgument')
        types = types[:-1]
    table_args = [i for i,typ in enumerate(types) if typ.kind=='Table']
    if table_args and (len(types)!=1 or table_args!=[0]):
        binder.issue('Remove accepts a single table or multiple records',node)
    for arg,typ in zip(args[1:],types):
        if typ.kind not in ('Record','Table','Blank','Error','Unknown'):
            binder.issue('Remove requires records or a table of records',arg)
        actual = typ.row or OPEN_RECORD if typ.kind=='Table' else typ
        for key,field in actual.fields.items():
            canonical = row.aliases.get(key,key)
            wanted = row.fields.get(canonical)
            if wanted is None and not row.open:
                binder.issue('Unknown Remove column '+key,arg,'Name')
            elif wanted and not compatible(field,wanted):
                binder.issue(key+': incompatible Remove field type',arg)
    return target

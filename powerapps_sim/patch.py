"""Pure record merging and ordered writes to local mutable tables."""
from .syntax import FxError, call_name
from .store import DataSource, storage_value, schema_value
from .tables import SourceRecord, derived_record
from .mutations import matches, canonical_fields, change_record, record_value


def snapshot(value):
    """Assignments own their table/record values, including connector records."""
    if isinstance(value, DataSource):
        value = value.rows()
    if isinstance(value, list):
        return [snapshot(cell) for cell in value]
    if isinstance(value, dict):
        return derived_record(value,{key:snapshot(cell) for key,cell in value.items()})
    return value


def root_path(node):
    node = node.children[0] if node.kind=='alias' else node
    parts = []
    while node.kind=='member':
        parts.insert(0,node.value)
        node = node.children[0]
    return node,parts


def table_target(runtime,node,ctx,value,operation='Patch',allow_blank=False):
    root, parts = root_path(node)
    if root.kind not in ('name','global') or root.kind=='name' and any(root.value in frame for frame in ctx.frames):
        raise FxError(operation+' target is a read-only expression or parameter', 'ReadOnlyValue')
    if isinstance(value,DataSource) and not parts:
        return value,None,None
    candidates = [runtime.scope_values(ctx,category) for category in ('variables','collections')]
    if root.kind=='name' and not ctx.component_ref:
        candidates.append(runtime.screen_context.get(runtime.screen_for(ctx.self_ref),{}))
    container = next((values for values in candidates if root.value in values),None)
    if container is None:
        raise FxError(operation+' requires a mutable collection or table variable', 'ReadOnlyValue')
    key = root.value
    for part in parts:
        container = container[key]
        if not isinstance(container,dict) or part not in container:
            raise FxError(operation+' target must be a table within a mutable record', 'ReadOnlyValue')
        key = part
    if not (isinstance(container[key],list) or allow_blank and container[key] is None) or value is not container[key]:
        raise FxError(operation+' target must be a mutable table', 'ReadOnlyValue')
    return None,container,key


def bind_target(binder,node,scope,typ,operation):
    """Shared lexical ownership checks for table mutation targets."""
    if typ.kind not in ('Table','Unknown','Error'):
        binder.issue(operation+' requires a mutable table',node)
    source,parts = root_path(node)
    name = call_name(source)
    from .components import access_app_scope
    local = scope.component and not access_app_scope(binder.runtime.project,scope.component)
    definition = binder.runtime.store.definitions.get(name) if not local and not parts else None
    containers = [binder.storage(scope,category) for category in ('variables','collections')]
    if source.kind=='name' and not scope.component:
        containers.append(binder.context_variables.get(scope.screen,{}))
    shadowed = source.kind=='name' and any(name in frame for frame in scope.frames)
    if source.kind not in ('name','global') or shadowed or not definition and not any(name in values for values in containers):
        binder.issue(operation+' requires a mutable collection, table variable or local data source',node,'ReadOnlyValue')
    return definition,name


def target_marker(node,ctx):
    root, parts = root_path(node)
    return ('table',ctx.component_ref.path if ctx.component_ref else None,root.value,*parts)


def safe_field(actual, expected):
    from .binding import function_compatible
    if actual.kind in ('Unknown','Blank','Error') or expected.kind in ('Unknown','Void'):
        return True
    if expected.kind=='Record':
        return actual.kind=='Record' and all(expected.open or key in expected.fields and safe_field(field,expected.fields[key]) for key,field in actual.fields.items())
    if expected.kind=='Table':
        return actual.kind=='Table' and safe_field(actual.row,expected.row)
    if actual.kind=='Text' and expected.kind not in ('Text','Image'):
        return False
    if actual.kind=='Number' and expected.kind=='Decimal':
        return False
    return function_compatible(actual,expected)


def patch_change(fx,raw,expected,actual=None):
    from .binding import UNKNOWN, value_type
    if expected and expected.kind=='Record':
        for key,value in raw.items():
            canonical = key if key in expected.fields else expected.aliases.get(key,key)
            wanted = expected.fields.get(canonical,UNKNOWN)
            got = actual.fields.get(key,UNKNOWN) if actual and actual.kind=='Record' else value_type(value)
            if got.kind=='Unknown':
                got = value_type(value)
            if not safe_field(got,wanted):
                raise FxError(f'{key}: incompatible Patch field type; use an explicit conversion', 'Type')
    return change_record(fx,raw,expected,actual)


def defaults(runtime, node, ctx, fx, value):
    if isinstance(value, DataSource):
        result = value.record(value.store.defaults(value.name))
        result.defaults_for = ('source', value.name)
        return result
    if not isinstance(value, list):
        raise FxError('Defaults requires a table or data source', 'Type')
    typ = fx.node_types.get(id(node))
    row_type = typ.row if typ and typ.kind == 'Table' else None
    logical = getattr(value[0], 'logical_names', {}) if value else {}
    aliases = {internal:display for display,internal in logical.items()}
    aliases.update(row_type.aliases if row_type else {})
    fields = {aliases.get(key,key):None for key in row_type.fields} if row_type else {}
    for row in value:
        if isinstance(row, dict):
            fields.update({key:None for key in row})
    try:
        table_target(runtime,node,ctx,value)
        lineage = target_marker(node,ctx)
    except FxError:
        lineage = None
    logical = logical or {display:internal for internal,display in aliases.items()}
    return SourceRecord(fields, logical, defaults_for=lineage)


def merge_records(values, types=None):
    from .binding import compatible, value_type
    if all(value is None for value in values):
        return None
    first = next((value for value in values if value is not None), {})
    first = record_value(first, 'Patch merge')
    first_index = next(i for i,value in enumerate(values) if value is not None)
    expected = types[first_index] if types and types[first_index] and types[first_index].kind=='Record' else value_type(first)
    result = {}
    for index,value in enumerate(values):
        raw = record_value(value, 'Patch merge')
        for key, cell in raw.items():
            field = expected.fields.get(key)
            actual = types[index].fields.get(key) if types and types[index] and types[index].kind=='Record' else None
            if field and not compatible(actual or value_type(cell), field):
                raise FxError(f'{key}: incompatible Patch merge field type', 'Type')
        if expected.aliases:
            raw = canonical_fields(raw,SourceRecord({key:None for key in expected.physical_fields()},{display:internal for internal,display in expected.aliases.items()}))
        result.update(raw)
    return derived_record(first, result)


def _source_write(runtime, source, base, changes, single):
    from .data_errors import operation
    with operation(runtime.store,source.name,base):
        return _write_source(runtime,source,base,changes,single)


def _write_source(runtime,source,base,changes,single):
    from .fx import observe
    store, name = runtime.store, source.name
    origin = getattr(base, 'source_name', None)
    marker = getattr(base, 'defaults_for', None)
    if origin and origin != name or marker and marker != ('source', name):
        raise FxError('Patch base record and Defaults must belong to the target data source', 'InvalidArgument')
    if single and origin != name:
        raise FxError('Key-and-update Patch requires a record derived from the target data source', 'Unsupported')
    internal = store.internal(name, base)
    item_id = observe(internal.get('ID'))
    if item_id is not None:
        from .numeric import NUMBERS
        try:
            if isinstance(item_id,bool) or not isinstance(item_id,NUMBERS) or int(item_id)!=item_id:
                raise ValueError()
            item_id = int(item_id)
        except (ValueError,OverflowError):
            raise FxError('Patch identity requires an integer ID', 'Type') from None
        if not 0 < item_id <= 2**63-1:
            raise FxError('Patch identity requires a positive ID', 'Type')
        base = {**base, 'ID':item_id}
    fields = store.definitions[name]['fields']
    updates = store.internal(name, changes)
    protected = {key for key,spec in fields.items() if key in ('ID','Created','Modified') or spec.get('x-ms-permission')=='read-only'}
    if single:
        saved = store.db.execute('SELECT record FROM items WHERE list_name=? AND id=?',(name,item_id)).fetchone() if item_id is not None else None
        import json
        previous = json.loads(saved[0]) if saved else {}
        for key in protected & updates.keys():
            if key == 'ID':
                continue
            actual = storage_value(updates[key], fields[key])
            old = storage_value(schema_value(previous.get(key),fields[key]),fields[key])
            if actual != old:
                raise FxError(f'{key} is read-only', 'ReadOnlyValue', column=key)
        updates = {key:value for key,value in updates.items() if key not in protected}
    elif protected & updates.keys():
        key = sorted(protected & updates.keys())[0]
        raise FxError(f'{key} is read-only', 'ReadOnlyValue', column=key)
    return source.record(store.patch(name, base, updates))


def _collection_write(collections, name, base, changes, single, marker_key):
    from .fx import observe
    marker = getattr(base, 'defaults_for', None)
    if marker and marker[0]=='table' and marker != marker_key:
        raise FxError('Patch Defaults must belong to the target collection', 'InvalidArgument')
    rows = collections.setdefault(name, [])
    origin = getattr(base,'source_name',None)
    if single and not origin:
        raise FxError('Key-and-update Patch requires a source-backed record; use a separate base and change record for collections', 'Unsupported')
    def selected(row):
        old = canonical_fields(base,row)
        id_field = next((display for display,logical in getattr(row,'logical_names',{}).items() if logical=='ID'), 'ID')
        if origin and getattr(row,'source_name',None)==origin and old.get(id_field) is not None:
            return observe(row.get(id_field))==observe(old[id_field])
        return matches(row,old)
    position = next((i for i,row in enumerate(rows) if isinstance(row,dict) and selected(row)), None) if not marker else None
    template = rows[position] if position is not None else rows[0] if rows else base
    updates = canonical_fields(changes, template)
    columns = set().union(*(row.keys() for row in rows if isinstance(row,dict))) if rows else set()
    if position is None:
        fields = {key:None for key in columns}
        if marker:
            fields.update(canonical_fields(base, template))
        fields.update(updates)
        result = derived_record(template, fields)
        if hasattr(result, 'defaults_for'):
            result.defaults_for = None
        rows.append(result)
    else:
        result = derived_record(rows[position], {**rows[position], **updates})
        rows[position] = result
    return result


def execute(runtime, args, ctx, fx):
    from .fx import table, observe
    source_value = fx.eval(args[0], ctx)
    if source_value is None or isinstance(source_value, dict):
        return merge_records([source_value, *(fx.eval(arg,ctx) for arg in args[1:])],[fx.node_types.get(id(arg)) for arg in args])
    fx.require_behavior(ctx)
    source, collections, name = table_target(runtime,args[0],ctx,source_value)
    from contextlib import nullcontext
    from .data_errors import operation
    with operation(runtime.store,source.name,capture=False) if source else nullcontext():
        try:
            return _execute_table(runtime,args,ctx,fx,source_value,source,collections,name)
        finally:
            runtime.invalidate()


def _execute_table(runtime,args,ctx,fx,source_value,source,collections,name):
    from .fx import table, observe
    runtime.trace_event('behavior',function='Patch',control=ctx.self_ref.path if ctx.self_ref else None)
    values = [fx.eval(arg,ctx) for arg in args[1:]]
    single = len(args)==2
    base_type = fx.node_types.get(id(args[1]))
    batch = isinstance(values[0], (list,DataSource)) or base_type and base_type.kind=='Table'
    if batch:
        bases = list(table(values[0]))
        changes = [list(table(value)) for value in values[1:]]
        if any(len(value)!=len(bases) for value in changes):
            raise FxError('Patch tables must have the same number of records', 'InvalidArgument')
    else:
        if values[0] is None:
            return None
        bases, changes = [values[0]], [[value] for value in values[1:]]
    # Argument shapes and table lengths fail before any record is written.
    for group in [bases, *changes]:
        for row in group:
            if row is not None and not isinstance(row,(dict,FxError)):
                raise FxError('Patch arguments must be records or corresponding tables', 'Type')
    typ = fx.node_types.get(id(args[0]))
    expected = typ.row if typ and typ.kind=='Table' else None
    if expected is None or expected.open and not expected.fields:
        from .binding import value_type
        inferred = runtime.binder.globals.get(source.name) if source else value_type(source_value)
        expected = inferred.row if inferred and inferred.kind=='Table' else expected
    template = source.record(runtime.store.defaults(source.name)) if source else next((row for row in collections.get(name,[]) if isinstance(row,dict)), None)
    marker_key = target_marker(args[0],ctx)
    output = []
    for index, base in enumerate(bases):
        observe(base)
        if base is None or batch and any(group[index] is None for group in changes):
            continue
        old = record_value(base, 'Patch base')
        base_actual = base_type.row if batch and base_type and base_type.kind=='Table' else base_type
        if source and isinstance(runtime.store.internal(source.name,old).get('ID'),bool):
            raise FxError('Patch identity requires an integer ID', 'Type')
        coerced = patch_change(fx,old,expected,base_actual)
        old = derived_record(base,canonical_fields(coerced,template) if template is not None else coerced)
        updates = {}
        groups = [(base,args[1],base_actual)] if single else [(group[index],arg,None) for group,arg in zip(changes,args[2:])]
        for raw, arg, actual in groups:
            observe(raw)
            actual = actual or fx.node_types.get(id(arg))
            actual = actual.row if actual and actual.kind=='Table' else actual
            converted = patch_change(fx,record_value(raw,'Patch update'),expected,actual)
            updates.update(canonical_fields(converted,template) if template is not None else converted)
        result = _source_write(runtime,source,old,updates,single) if source else _collection_write(collections,name,old,updates,single,marker_key)
        runtime.invalidate()
        output.append(result)
    return output if batch else output[0] if output else None


def bind(binder, node, scope):
    from .binding import record, tabular, compatible, merge, OPEN_RECORD, UNKNOWN, BLANK
    args = node.children[1:]
    types = [binder.infer(arg,scope) for arg in args]
    first = types[0]
    if first.kind in ('Record','Blank','Error'):
        expected = next((typ for typ in types if typ.kind=='Record'), OPEN_RECORD)
        result = record() if any(typ.kind=='Record' for typ in types) else BLANK
        for arg, typ in zip(args,types):
            if typ.kind not in ('Record','Blank','Error','Unknown'):
                binder.issue('Patch merge requires records',arg)
            for key,field in typ.fields.items():
                wanted = expected.fields.get(key)
                if wanted and not compatible(field,wanted):
                    binder.issue(key+': incompatible Patch merge field type',arg)
            if typ.kind=='Record':
                result = merge(result,typ)
        return result
    if not scope.behavior or scope.function_pure:
        binder.issue('Patch writes require a behavior formula',node)
    if first.kind not in ('Table','Unknown'):
        binder.issue('Patch requires records or a mutable table',args[0])
        return UNKNOWN
    definition,name = bind_target(binder,args[0],scope,first,'Patch')
    row = first.row or OPEN_RECORD
    batch = types[1].kind=='Table'
    single = len(args)==2
    for index,(arg,typ) in enumerate(zip(args[1:],types[1:]),1):
        expected_kind = 'Table' if batch else 'Record'
        if typ.kind not in (expected_kind,'Blank','Error','Unknown'):
            binder.issue('Patch requires corresponding '+expected_kind.lower()+' arguments',arg)
        actual = typ.row or OPEN_RECORD if typ.kind=='Table' else typ
        for key,field in actual.fields.items():
            canonical = key if key in row.fields else row.aliases.get(key,key)
            if canonical not in row.fields and not row.open:
                binder.issue('Unknown Patch column '+key,arg,'Name')
            elif canonical in row.fields and not safe_field(field,row.fields[canonical]):
                binder.issue(key+': incompatible Patch field type',arg)
            if definition and index>=2 and not single:
                internal = binder.runtime.store.internal_name(name,key)
                if internal in ('ID','Created','Modified') or definition['fields'].get(internal,{}).get('x-ms-permission')=='read-only':
                    binder.issue(key+' is read-only',arg,'ReadOnlyValue')
    return tabular(row) if batch else row

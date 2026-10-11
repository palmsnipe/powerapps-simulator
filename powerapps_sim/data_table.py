"""Classic read-only DataTable: source columns, row scopes and server selection.

Versions are verified against Microsoft's IssueReporting template manifest.
Omitted presentation defaults and text-based AutoWidth sizing are approximations.
"""
from dataclasses import replace
from decimal import Decimal
import hashlib,json,math
from .syntax import FxError

TYPES={'Items':'Table','FieldName':'Text','FieldDisplayName':'Text','DisplayName':'Text','Text':'Text',
       'AutoWidth':'Boolean','IsHyperlink':'Boolean','Order':'Number','Width':'Number',
       'HeadingColor':'Color','HeadingFill':'Color','HeadingFont':'Text','HeadingFontWeight':'Text',
       'HeadingSize':'Number','SelectedColor':'Color','SelectedFill':'Color','HoverColor':'Color',
       'HoverFill':'Color','NoDataText':'Text'}
DEFAULTS={'DataTable':{'Items':'=Table()','Width':'=640','Height':'=300','TabIndex':'=0',
    'Fill':'=Color.White','HeadingColor':'=Color.White','HeadingFill':'=RGBA(15,108,189,1)',
    'HeadingFont':"=Font.'Segoe UI'",'HeadingFontWeight':'=FontWeight.Semibold','HeadingSize':'=14',
    'SelectedColor':'=RGBA(36,36,36,1)','SelectedFill':'=RGBA(225,237,248,1)',
    'HoverColor':'=Self.Color','HoverFill':'=RGBA(242,242,242,1)','NoDataText':'="No records"'},
    'DataTableColumn':{'FieldName':'=""','FieldDisplayName':'=Self.FieldName','Text':'=Blank()',
    'Order':'=1','Width':'=180','AutoWidth':'=false','IsHyperlink':'=false'}}

def validate(ref,name,value):
    kind=TYPES.get(name)
    if kind=='Boolean' and not isinstance(value,bool):raise FxError(f'{ref.family}.{name} requires Boolean','Type')
    if kind=='Number':
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):raise FxError(f'{ref.family}.{name} requires a finite Number','Type')
        if value<0 or name=='Order' and (value<1 or value!=int(value)):raise FxError(f'{ref.family}.{name} requires '+('a positive integer' if name=='Order' else 'a nonnegative Number'),'Validation')
    if kind=='Text' and name not in ('Text',) and not isinstance(value,str):raise FxError(f'{ref.family}.{name} requires Text','Type')
    if name=='Items':
        from .fx import table
        if any(not isinstance(row,(dict,FxError)) for row in table(value)):raise FxError('DataTable.Items requires record rows','Type')

def row_keys(rows):
    from .runtime import serial
    counts={};keys=[]
    for row in rows:
        identity=next(({name:row[name]} for name in ('ID','Id') if isinstance(row,dict) and row.get(name) is not None),row)
        digest=hashlib.sha256(json.dumps(serial(identity),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        occurrence=counts.get(digest,0);counts[digest]=occurrence+1
        keys.append(f'{digest}:{occurrence}')
    return keys

def selected_index(ref):
    from .fx import table
    cache=(ref.path,'__table_selected_index__')
    if cache in ref.runtime.property_cache:return ref.runtime.property_cache[cache]
    rows=table(ref.property('Items'));saved=ref.state.get('TableSelected');key=ref.state.get('TableSelectedKey')
    keys=row_keys(rows)
    index=next((i for i,row in enumerate(rows) if not isinstance(row,FxError) and keys[i]==key and ref.runtime.same_item(row,saved)),None)
    if index is None:index=next((i for i,row in enumerate(rows) if not isinstance(row,FxError) and ref.runtime.same_item(row,saved)),None)
    if index is None:index=next((i for i,row in enumerate(rows) if not isinstance(row,FxError)),None)
    ref.runtime.property_cache[cache]=index
    return index

def selected(ref):
    from .fx import table
    index=selected_index(ref)
    return table(ref.property('Items'))[index] if index is not None else None

def columns(ref):
    return [child for child in ref.children if child.family=='DataTableColumn' and child.control.version=='1.0.1']

def token(ref,rows=None):
    from .fx import table
    from .runtime import serial
    rows=table(ref.property('Items')) if rows is None else rows
    # Selection does not alter row addresses. Source/data/restart changes do.
    values=[ref.runtime.text_generation,ref.runtime.selector_resets.get(ref.path,0),serial(rows),[(c.path,dict(c.control.properties)) for c in columns(ref)]]
    return hashlib.sha256(json.dumps(values,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()

def cell(ref,row,row_key=None):
    if row is None:return ''
    from .row_rules import evaluate,row_key as find_key
    key=row_key if row_key is not None else find_key(ref.parent,row)
    return evaluate(ref,'Text',row,key,lambda ctx:_cell(ref,row,ctx),parent=ref.parent)

def _cell(ref,row,ctx):
    row=ctx.item
    if row is None:return ''
    runtime=ref.runtime;key=(ref.path,'Text')
    if key in runtime.evaluating:raise FxError(f'Control property cycle: {ref.name}.Text','Cycle')
    runtime.evaluating.add(key)
    try:
        raw=ref.control.properties.get('Text')
        if raw is None:value=runtime.fx.member(row,ref.property('FieldName'),ctx)
        else:value=runtime.fx.evaluate(raw,ctx) if isinstance(raw,str) and raw.startswith('=') else raw
        if isinstance(value,(dict,list)):raise FxError('DataTable cells require scalar text; use an explicit Text or JSON formula for complex values','Type')
        if isinstance(value,FxError):raise value
        return runtime.fx.to_text(value)
    finally:runtime.evaluating.discard(key)

def event(ref,name,value,indices):
    from .fx import table
    if name!='OnSelect' or indices is not None or not isinstance(value,dict) or set(value)-{'index','column','items_token'}:raise ValueError('DataTable selection requires one row index and source token')
    rows=table(ref.property('Items'));i=value.get('index')
    if type(i) is not int or not 0<=i<len(rows):raise ValueError('DataTable requires a valid row index')
    if value.get('items_token')!=token(ref,rows):raise ValueError('DataTable source changed; refresh before selecting')
    if isinstance(rows[i],FxError):raise rows[i]
    column=None
    if 'column' in value:
        column=next((c for c in columns(ref) if c.path==value['column']),None)
        if column is None:raise ValueError('DataTable column does not belong to this table')
        if not column.property('Visible') or column.property('DisplayMode')!='Edit':return
    ref.state.update(TableSelected=rows[i],TableSelectedKey=row_keys(rows)[i]);ref.runtime.invalidate()
    # Explicit simulator timing policy: select the row before the column callback.
    if column is not None:ref.runtime.run_event(column,'OnSelect')
    ref.runtime.drain_events()

def render(ref,node):
    from .fx import table
    runtime=ref.runtime;rows=table(runtime.render_property(ref,'Items'));chosen_index=selected_index(ref);keys=row_keys(rows)
    node['columns']=[];node['rows']=[];node['items_token']=token(ref,rows)
    def issue(child,prop,error,observation=None):
        runtime.render_error(child,prop,error,observation)
        node['errors'].append(f'{child.name}.{prop}: {error.message}')
    for source_order,c in enumerate(columns(ref)):
        try:
            get=lambda name:runtime.render_property(c,name)
            if not get('Visible'):continue
            header=get('DisplayName') if 'DisplayName' in c.control.properties and 'FieldDisplayName' not in c.control.properties else get('FieldDisplayName')
            node['columns'].append({'path':c.path,'name':c.name,'header':header,'order':float(get('Order')),
                'width':float(get('Width')),'automatic':get('AutoWidth'),'hyperlink':get('IsHyperlink'),
                'source_order':source_order,'interactive':'OnSelect' in c.control.properties,'mode':get('DisplayMode')})
        except FxError as error:issue(c,'Column',error)
    node['columns'].sort(key=lambda c:(c['order'],c['source_order']))
    for index,row in enumerate(rows):
        result={'index':index,'selected':index==chosen_index,'cells':[]}
        if isinstance(row,FxError):
            issue(ref,'Items',row,ref.path+f'/row:{index}.Items');result['disabled']=True
        for spec in node['columns']:
            c=runtime.refs[spec['path']]
            observed=c.path+f'/row:{index}.Text'
            try:
                result['cells'].append({'text':cell(c,row,keys[index]) if not isinstance(row,FxError) else row.message})
                runtime.app_errors.healthy(observed)
            except FxError as error:
                issue(c,'Text',error,observed);result['cells'].append({'text':'Power Fx error: '+error.message,'error':True})
        node['rows'].append(result)
    for j,spec in enumerate(node['columns']):
        if spec['automatic']:
            longest=max([len(spec['header']),*[len(row['cells'][j]['text']) for row in node['rows']]])
            spec['width']=min(480,max(120,longest*float(node['props'].get('Size',14))*.6+32))

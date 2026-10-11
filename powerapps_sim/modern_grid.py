"""ModernDataGrid@1.1.0 and documented Textual columns.

Python owns search, order and selection. Browser windowing is presentation only.
Exact selection/default/callback ordering still needs measured Studio comparison.
"""
from dataclasses import replace
from decimal import Decimal
import hashlib,json,math
from .syntax import FxError
from .fx import table
from .data_table import row_keys

TYPES={'Searchable':'Boolean','Sortable':'Boolean','SelectMultiple':'Boolean','ShowHeaders':'Boolean',
       'ShowSelector':'Boolean','Required':'Boolean','ShowAIRowSummary':'Boolean','Items':'Table',
       'DefaultSelectedItems':'Table','SearchText':'Text','FieldDisplayName':'Text','Width':'Number'}
DEFAULTS={'ModernDataGrid':{'Items':'=Table()','DefaultSelectedItems':'=Table()','Searchable':'=false',
    'Sortable':'=false','SelectMultiple':'=false','ShowHeaders':'=true','ShowSelector':'=false',
    'Required':'=false','ShowAIRowSummary':'=false','Width':'=792','Height':'=475','Size':'=14',
    'BasePaletteColor':'=RGBA(15,108,189,1)'},
    'ModernDataGridColumn':{'FieldDisplayName':'=""','Width':'=150','Text':'=Blank()'}}

def validate(ref,name,value):
    kind=TYPES.get(name)
    if kind=='Boolean' and type(value) is not bool:raise FxError(f'{ref.family}.{name} requires Boolean','Type')
    if name in ('Items','DefaultSelectedItems'):
        if any(not isinstance(row,(dict,FxError)) for row in table(value)):
            raise FxError(f'{ref.family}.{name} requires record rows','Type')
    if name=='Width' and (isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)) or value<0):
        raise FxError(f'{ref.family}.Width requires a nonnegative finite Number','Validation')
    if name=='FieldDisplayName' and not isinstance(value,str):raise FxError('Column FieldDisplayName requires Text','Type')
    if name=='ShowAIRowSummary' and value:raise FxError('Dataverse AI row summaries require live services','Unsupported')

def columns(ref):
    return [c for c in ref.children if c.family=='ModernDataGridColumn' and c.control.version=='1.1.0' and c.control.raw.get('Variant','Textual')=='Textual']

def sync(ref):
    """Initialize defaults once; changing defaults takes effect on explicit Reset.

    Called while simulation settles, not by pure output/inspector evaluation.
    """
    state=ref.state;changed=False
    if 'GridDefaults' not in state:
        state['GridDefaults']=list(table(ref.property('DefaultSelectedItems')));changed=True
    searchable=ref.property('Searchable')
    if not searchable and state.get('GridSearch'):
        state.pop('GridSearch',None);changed=True
    if not ref.property('Sortable') and state.get('GridSort'):
        state.pop('GridSort',None);changed=True
    return changed

def default_indices(ref,rows):
    defaults=ref.state['GridDefaults'] if 'GridDefaults' in ref.state else table(ref.property('DefaultSelectedItems'))
    indices=[]
    for default in defaults:
        match=next((i for i,row in enumerate(rows) if i not in indices and not isinstance(row,FxError) and ref.runtime.same_item(row,default)),None)
        if match is not None:indices.append(match)
    indices.sort()
    return indices if ref.property('SelectMultiple') else indices[-1:]

def selection(ref):
    cache=(ref.path,'__grid_selection__')
    if cache in ref.runtime.property_cache:return ref.runtime.property_cache[cache]
    rows=table(ref.property('Items'));keys=row_keys(rows)
    chosen=ref.state.get('GridSelection')
    if chosen is None:indices=default_indices(ref,rows)
    else:
        chosen=set(chosen);indices=[i for i,row in enumerate(rows) if keys[i] in chosen and not isinstance(row,FxError)]
    if not ref.property('SelectMultiple'):indices=indices[-1:]
    latest=ref.state.get('GridLatest');index=next((i for i in indices if keys[i]==latest),indices[-1] if indices else None)
    result=(indices,index);ref.runtime.property_cache[cache]=result;return result


def output(ref,name):
    if name=='SearchText':return ref.state.get('GridSearch','') if ref.property('Searchable') else ''
    indices,latest=selection(ref);rows=table(ref.property('Items'))
    return rows[latest] if name=='Selected' and latest is not None else None if name=='Selected' else [rows[i] for i in indices]

def cell(column,row,row_key=None):
    from .row_rules import evaluate,row_key as find_key
    key=row_key if row_key is not None else find_key(column.parent,row)
    return evaluate(column,'Text',row,key,lambda ctx:_cell(column,ctx),parent=column.parent)

def _cell(column,ctx):
    runtime=column.runtime;key=(column.path,'Text')
    if key in runtime.evaluating:raise FxError(f'Control property cycle: {column.name}.Text','Cycle')
    runtime.evaluating.add(key)
    try:
        raw=column.raw_property('Text')
        value=runtime.fx.evaluate(raw,ctx) if isinstance(raw,str) and raw.startswith('=') else raw
        if isinstance(value,FxError):raise value
        if isinstance(value,list):
            values=[]
            for v in value:
                if isinstance(v,dict) and set(v)=={'Value'}:v=v['Value']
                if isinstance(v,(dict,list)):raise FxError('Grid choice cells require a single Value column','Type')
                values.append(runtime.fx.to_text(v))
            return ', '.join(values),None
        if isinstance(value,dict):raise FxError('Grid cells require scalar text or a single-column choice table','Type')
        return runtime.fx.to_text(value),value
    finally:runtime.evaluating.discard(key)

def token(ref):
    from .runtime import serial
    cache=(ref.path,'__grid_token__')
    if cache in ref.runtime.property_cache:return ref.runtime.property_cache[cache]
    values=[ref.runtime.text_generation,ref.runtime.selector_resets.get(ref.path,0),serial(table(ref.property('Items'))),
            dict(ref.control.properties),[(c.path,dict(c.control.properties)) for c in columns(ref)]]
    result=hashlib.sha256(json.dumps(values,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
    ref.runtime.property_cache[cache]=result;return result

def view(ref):
    cache=(ref.path,'__grid_view__')
    if cache in ref.runtime.property_cache:return ref.runtime.property_cache[cache]
    rows=table(ref.property('Items'));keys=row_keys(rows);specs=[];errors=[]
    for c in columns(ref):
        try:
            if c.property('Visible'):specs.append({'path':c.path,'name':c.name,'header':c.property('FieldDisplayName'),'width':float(c.property('Width'))})
        except FxError as error:errors.append((c,'Column',error))
    displayed=[];query=output(ref,'SearchText').casefold()
    for i,row in enumerate(rows):
        cells=[]
        if isinstance(row,FxError):errors.append((ref,'Items',row))
        for spec in specs:
            c=ref.runtime.refs[spec['path']]
            try:
                if isinstance(row,FxError):raise row
                text,value=cell(c,row,keys[i]);cells.append({'text':text,'value':value})
            except FxError as error:
                errors.append((c,'Text',error));cells.append({'text':error.message,'value':None,'error':True})
        if not query or any(query in c['text'].casefold() for c in cells if not c.get('error')):
            displayed.append({'index':i,'cells':cells,'disabled':isinstance(row,FxError)})
    sort=ref.state.get('GridSort') if ref.property('Sortable') else None
    j=next((i for i,c in enumerate(specs) if sort and c['path']==sort['column']),None)
    if j is not None:
        try:
            displayed=ref.runtime.fx.sort_rows(displayed,
                lambda row:row['cells'][j]['value'] if row['cells'][j]['value'] is not None else row['cells'][j]['text'] or None,
                'Descending' if sort['descending'] else 'Ascending')
        except FxError as error:errors.append((ref.runtime.refs[specs[j]['path']],'Sort',error))
    result=(specs,displayed,errors);ref.runtime.property_cache[cache]=result;return result

def event(ref,name,value,indices):
    if indices is not None or not isinstance(value,dict):raise ValueError('Grid operations require an operation and source token')
    if value.get('items_token')!=token(ref):raise ValueError('Grid source changed; refresh before interacting')
    if name=='OnSearch':
        if set(value)!={'items_token','query'} or not isinstance(value['query'],str):raise ValueError('Grid search requires Text')
        if not ref.property('Searchable'):raise ValueError('Grid search is disabled')
        ref.state['GridSearch']=value['query'];ref.runtime.invalidate();return
    if name=='OnSort':
        if set(value)!={'items_token','column','descending'} or type(value['descending']) is not bool:raise ValueError('Grid sorting requires one column and Boolean descending')
        if not ref.property('Sortable'):raise ValueError('Grid sorting is disabled')
        specs,_,_=view(ref)
        if value['column'] not in {c['path'] for c in specs}:raise ValueError('Sort column does not belong to the visible grid')
        ref.state['GridSort']={'column':value['column'],'descending':value['descending']};ref.runtime.invalidate();return
    if name!='OnChange' or set(value)-{'items_token','indices','toggle'} or 'indices' not in value:raise ValueError('Grid selection requires OnChange and item indices')
    ids=value['indices'];rows=table(ref.property('Items'));specs,visible,_=view(ref);allowed={r['index'] for r in visible if not r['disabled']}
    if not isinstance(ids,list) or any(type(i) is not int or i not in allowed for i in ids) or len(set(ids))!=len(ids):raise ValueError('Selection requires distinct visible row indices')
    if 'toggle' in value and type(value['toggle']) is not bool:raise ValueError('Grid toggle requires Boolean')
    if not ref.property('SelectMultiple') and (len(ids)>1 or value.get('toggle')):raise ValueError('Grid permits only one selection')
    current,_=selection(ref);keys=row_keys(rows);chosen=[keys[i] for i in current]
    if value.get('toggle'):
        for i in ids:
            key=keys[i]
            if key in chosen:chosen.remove(key)
            else:chosen.append(key)
    else:chosen=[keys[i] for i in ids]
    old=set(keys[i] for i in current)
    ref.state['GridSelection']=chosen
    ref.state['dirty']=set(chosen)!={keys[i] for i in default_indices(ref,rows)}
    if ids and keys[ids[-1]] in chosen:ref.state['GridLatest']=keys[ids[-1]]
    ref.runtime.invalidate()
    if old!=set(chosen):ref.runtime.run_event(ref,'OnChange')
    ref.runtime.drain_events()

def render(ref,node):
    specs,rows,errors=view(ref);chosen,latest=selection(ref);selected=set(chosen)
    node.update(columns=specs,rows=[{'index':r['index'],'selected':r['index'] in selected,'disabled':r['disabled'],
        'cells':[{'text':c['text'],'error':bool(c.get('error'))} for c in r['cells']]} for r in rows],
        items_token=token(ref),search=output(ref,'SearchText'),sort=ref.state.get('GridSort') if ref.property('Sortable') else None,
        latest=latest,grid_epoch=f'{ref.runtime.text_generation}:{ref.runtime.selector_resets.get(ref.path,0)}')
    for child,prop,error in errors:
        # A grid may consume several failures from the same column. Observe
        # the combined result once, rather than oscillating its error ledger.
        node['errors'].append(f'{child.name}.{prop}: {error.message}')
    grouped={}
    for child,prop,error in errors:grouped.setdefault((child.path,prop),[]).append(error)
    for spec in specs:
        key=(spec['path'],'Text')
        if key not in grouped:ref.runtime.app_errors.healthy(spec['path']+'.Text')
    for (path,prop),failures in grouped.items():
        ref.runtime.render_error(ref.runtime.refs[path],prop,FxError.combine(failures))

"""Classic ListBox records, scalar defaults and server-owned selection operations."""
from functools import lru_cache
from pathlib import Path
from decimal import Decimal
import json,math,hashlib
from .syntax import FxError

LISTBOXES=frozenset(('Classic/ListBox','ListBox'))
OUTPUTS=frozenset(('Selected','SelectedItems','SelectedText','SelectedItemsText'))
@lru_cache(maxsize=1)
def catalog():return json.loads((Path(__file__).parent/'static/listbox.json').read_text())

def validate(ref,name,value):
    kind=catalog()['types'].get(name)
    if kind=='Boolean' and not isinstance(value,bool):raise FxError(f'ListBox {name} requires Boolean','Type')
    if kind=='Number':
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):raise FxError(f'ListBox {name} requires a finite Number','Type')
        if name!='TabIndex' and value<0:raise FxError(f'ListBox {name} cannot be negative','Validation')
    if name=='Value' and (not isinstance(value,str) or not value):raise FxError('ListBox Value requires a display column name','Type')
    if name=='Default' and isinstance(value,(dict,list)):raise FxError('ListBox Default supports one scalar display value','Type')
    if name=='Items':
        from .fx import table
        if any(not isinstance(row,(dict,FxError)) for row in table(value)):raise FxError('ListBox Items requires record rows','Type')

def display(ref,row):
    if row is None:return ''
    if isinstance(row,FxError):raise row
    return ref.runtime.fx.to_text(ref.runtime.fx.member(row,ref.property('Value'),ref.context()))

def initial(ref,rows):
    default=ref.property('Default')
    if default is None:return []
    text=ref.runtime.fx.to_text(default)
    return [row for row in rows if not isinstance(row,FxError) and display(ref,row)==text][:1]

def selected(ref):
    ref.sync_default('Selected')
    from .fx import table
    rows=table(ref.property('Items'));saved=ref.state.get('SelectedItems')
    values=initial(ref,rows) if saved is None else [row for row in rows if any(ref.runtime.same_item(row,v) for v in saved)]
    if not ref.property('SelectMultiple'):values=values[:1]
    return values

def output(ref,name):
    values=selected(ref)
    if name=='SelectedItems':return values
    if name=='SelectedItemsText':return [{'Value':display(ref,row)} for row in values]
    latest=ref.state.get('ListLatest')
    chosen=next((v for v in values if ref.runtime.same_item(v,latest)),values[-1] if values else None)
    return display(ref,chosen) if name=='SelectedText' else chosen

def token(ref,rows=None):
    ref.sync_default('Selected')
    from .fx import table
    from .runtime import serial
    rows=table(ref.property('Items')) if rows is None else rows
    # Gestures address Items, not SelectedItems. Keep the token stable across
    # queued selections; the server applies each against its current anchor.
    values=[ref.runtime.selection_epoch(ref),serial(rows),ref.property('Value'),ref.property('Default'),ref.property('SelectMultiple')]
    return hashlib.sha256(json.dumps(values,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def event(ref,name,value,indices):
    from .fx import table
    runtime=ref.runtime
    if name=='OnSelect' and value is None and indices is None:
        runtime.run_event(ref,name);runtime.drain_events();return
    if name!='OnChange':raise ValueError('ListBox accepts selection changes and OnSelect')
    ref.sync_default('Selected');rows=table(ref.property('Items'));before=selected(ref);multiple=ref.property('SelectMultiple')
    previous=[i for i,row in enumerate(rows) if any(runtime.same_item(row,v) for v in before)]
    latest=None
    if isinstance(value,dict):
        if indices is not None or set(value)-{'operation','index','option_token'} or value.get('operation') not in ('toggle','replace','range','all','clear'):
            raise ValueError('Invalid ListBox selection operation')
        if value.get('option_token')!=token(ref,rows):raise ValueError('ListBox source or reset changed; refresh before selecting')
        operation=value['operation'];i=value.get('index')
        if operation in ('toggle','replace','range') and (type(i) is not int or not 0<=i<len(rows)):raise ValueError('ListBox requires a valid item index')
        if operation=='clear':indices=[]
        elif operation=='all':
            if not multiple:raise ValueError('ListBox allows only one selection')
            indices=[i for i,row in enumerate(rows) if not isinstance(row,FxError)]
        elif operation=='range':
            if not multiple:raise ValueError('Range requires a multiselect ListBox')
            anchor=ref.state.get('ListAnchor',previous[-1] if previous else 0)
            indices=list(range(min(anchor,i),max(anchor,i)+1));latest=i
        elif operation=='replace' or not multiple:indices=[i];latest=i
        else:indices=[j for j in previous if j!=i] if i in previous else previous+[i];latest=i if i in indices else None
        anchor_change=operation in ('toggle','replace')
    else:
        if value is not None:raise ValueError('ListBox selection uses item indices')
        anchor_change=True
    if not isinstance(indices,list) or any(type(i) is not int or not 0<=i<len(rows) for i in indices) or len(set(indices))!=len(indices):raise ValueError('ListBox requires distinct valid item indices')
    if not multiple and len(indices)>1:raise ValueError('ListBox allows only one selection')
    for i in indices:
        if isinstance(rows[i],FxError):raise rows[i]
    if latest is None:latest=indices[-1] if indices else None
    source_order=sorted(indices);baseline=initial(ref,rows)
    values=[rows[i] for i in source_order]
    dirty=len(values)!=len(baseline) or any(not runtime.same_item(a,b) for a,b in zip(values,baseline))
    ref.state.update(SelectedItems=values,ListLatest=rows[latest] if latest is not None else None,dirty=dirty)
    if anchor_change:ref.state['ListAnchor']=latest if latest is not None else 0
    runtime.invalidate();runtime.run_event(ref,'OnSelect')
    if source_order!=previous:runtime.run_event(ref,'OnChange')
    runtime.drain_events()

def render(ref,node):
    from .fx import table
    rows=table(ref.property('Items'));chosen=selected(ref);node['options']=[]
    for i,row in enumerate(rows):
        try:node['options'].append({'index':i,'label':display(ref,row)})
        except FxError as error:
            ref.runtime.diagnostic(error,ref.control.source,f'{ref.name}.Items',ref.raw_property('Items'))
            node['options'].append({'index':i,'label':'Power Fx error: '+error.message,'disabled':True})
    node['selection']=[i for i,row in enumerate(rows) if any(ref.runtime.same_item(row,v) for v in chosen)]
    node['option_token']=token(ref,rows);node['list_reset']=ref.runtime.selection_epoch(ref)

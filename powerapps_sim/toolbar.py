"""Toolbar@2.0.4 command tables, recovered from a first-party template.

Python owns selection and callbacks. Native field binding/theme and exact
selection/default/event timing still require wrapper observations.
"""
from functools import lru_cache
from pathlib import Path
from collections import Counter
from decimal import Decimal
import json,math
from .syntax import FxError
from .fx import table
from .store import DataSource
from .icons import glyph

VERSION='2.0.4'
@lru_cache(maxsize=1)
def catalog():return json.loads((Path(__file__).parent/'static/toolbar.json').read_text())
DEFAULTS=catalog()['defaults'];TYPES=catalog()['types'];ENUMS=catalog()['enum_values']
FIELDS=('ItemKey','ItemDisplayName','ItemIconName','ItemIconStyle','ItemAppearance','ItemTooltip','ItemVisible','ItemDisabled')
OUTPUTS={'Selected','SelectedItems'}
LAYOUT={'LayoutMinWidth','LayoutMinHeight','LayoutMaxWidth','LayoutMaxHeight','FillPortions','AlignInContainer'}
PROPERTIES=set(TYPES)|OUTPUTS|LAYOUT|{'OnSelect','Name'}

def errors(control):
    if control.version!=VERSION:return {'Version':f'Unsupported Toolbar version {control.version}'}
    result={p:f'Toolbar@{VERSION} has no supported authored {p} property' for p in control.properties if p not in PROPERTIES or p in OUTPUTS|{'Name'}}
    if control.raw.get('Variant'):result['Variant']='Toolbar variants are unsupported'
    return result

def validate(name,value):
    if value is None:return
    typ=TYPES.get(name)
    if name in ENUMS and value not in ENUMS[name]:raise FxError(f'Toolbar.{name} requires '+', '.join(ENUMS[name]),'Type')
    if typ=='Boolean' and not isinstance(value,bool):raise FxError(f'Toolbar.{name} requires Boolean','Type')
    if typ=='Text' and not isinstance(value,str):raise FxError(f'Toolbar.{name} requires Text','Type')
    if typ=='Number':
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):
            raise FxError(f'Toolbar.{name} requires a finite Number','Type')
        if name!='TabIndex' and value<0:raise FxError(f'Toolbar.{name} cannot be negative','Validation')
        if name=='TabIndex' and value!=int(value):raise FxError('Toolbar.TabIndex requires an integer','Type')
    if typ=='Table':
        if not isinstance(value,(list,DataSource)):raise FxError(f'Toolbar.{name} requires a table','Type')
        if any(not isinstance(row,(dict,FxError)) for row in table(value)):raise FxError(f'Toolbar.{name} requires record rows','Type')

def field(ref,row,name,default=None):
    try:value=ref.runtime.fx.member(row,name,ref.context())
    except FxError as error:
        if error.message==f'Unknown field {name}':return default
        raise
    if isinstance(value,FxError):raise value
    return default if value is None else value

def key(ref,row):
    value=field(ref,row,'ItemKey')
    if not isinstance(value,str) or not value:raise FxError('Toolbar ItemKey requires nonempty Text','Validation')
    return value

def commands(ref):
    rows=table(ref.property('Items'));counts=Counter()
    for row in rows:
        if isinstance(row,dict):
            try:counts[key(ref,row)]+=1
            except FxError:pass
    result=[]
    for index,row in enumerate(rows):
        try:
            if isinstance(row,FxError):raise row
            k=key(ref,row)
            if counts[k]>1:raise FxError(f'Duplicate Toolbar ItemKey {k}','Validation')
            values={n:field(ref,row,n) for n in FIELDS}
            for n in FIELDS:
                if n in ('ItemVisible','ItemDisabled'):
                    if values[n] is not None and not isinstance(values[n],bool):raise FxError(n+' requires Boolean','Type')
                elif values[n] is not None and not isinstance(values[n],str):raise FxError(n+' requires Text','Type')
            if values['ItemDisplayName'] is None:raise FxError('Toolbar ItemDisplayName is required','Validation')
            appearance=values['ItemAppearance'] or 'Subtle';style=values['ItemIconStyle'] or 'Regular'
            if appearance not in ('Primary','Secondary','Outline','Subtle','Transparent'):raise FxError('Unsupported Toolbar ItemAppearance '+appearance,'Unsupported')
            if style not in ('Regular','Filled'):raise FxError('Unsupported Toolbar ItemIconStyle '+style,'Unsupported')
            icon=glyph(values['ItemIconName'] or '',{'Regular':'Outline','Filled':'Filled'}[style])
            result.append({'index':index,'key':k,'label':values['ItemDisplayName'],'disabled':values['ItemDisabled'] is True,'visible':values['ItemVisible'] is not False,'appearance':appearance,'tooltip':values['ItemTooltip'] or '', 'icon':icon,'row':row})
        except FxError as error:result.append({'index':index,'invalid':True,'error':error,'disabled':True,'visible':True,'label':'Power Fx error: '+error.message,'key':'__error_'+str(index),'icon':None,'appearance':'Subtle','tooltip':error.message,'row':row})
    return result

def output(ref,name):
    ref.sync_default('Selected');items=commands(ref)
    desired=ref.state.get('SelectedItems',table(ref.property('DefaultSelectedItems')))
    selected=[]
    for row in desired:
        if isinstance(row,FxError):raise row
        k=key(ref,row);found=next((v for v in items if 'error' not in v and v['key']==k),None)
        if found and not any(key(ref,v)==k for v in selected):selected.append(found['row'])
    return selected if name=='SelectedItems' else selected[-1] if selected else None

def token(ref,items):
    import hashlib
    from .runtime import serial
    snapshot=[ref.runtime.selection_epoch(ref),serial(ref.property('Items')),serial(ref.property('DefaultSelectedItems'))]
    return hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def event(ref,name,data,selection):
    r=ref.runtime
    if name!='OnSelect' or selection is not None:raise ValueError('Toolbar accepts OnSelect only')
    if data is None:r.run_event(ref,name);r.drain_events();return
    ref.sync_default('Selected');items=commands(ref)
    if not isinstance(data,dict) or set(data)!={'key','option_token'} or not isinstance(data['key'],str) or not isinstance(data['option_token'],str):raise ValueError('Toolbar selection requires a key and option token')
    if data['option_token']!=token(ref,items):raise ValueError('Toolbar items changed; refresh before selecting')
    item=next((v for v in items if v['key']==data['key'] and 'error' not in v),None)
    if not item:raise ValueError('Toolbar command does not exist')
    if item['disabled'] or not item['visible']:return
    defaults=table(ref.property('DefaultSelectedItems'))
    ref.state.update(SelectedItems=[item['row']],dirty=[key(ref,v) for v in defaults]!=[item['key']])
    r.invalidate();r.run_event(ref,'OnSelect');r.drain_events()

def render(ref,node):
    items=commands(ref);node['commands']=[]
    for item in items:
        error=item.get('error')
        if error:
            ref.runtime.render_error(ref,'Items',error);node['errors'].append(error.message)
        if item['visible']:node['commands'].append({k:v for k,v in item.items() if k not in ('row','error','visible')})
    node['selection']=[key(ref,row) for row in output(ref,'SelectedItems')]
    node['option_token']=token(ref,items)

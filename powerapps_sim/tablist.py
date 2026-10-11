"""Versioned modern tab lists; Python owns selection and behavior execution."""
from dataclasses import replace
from .syntax import FxError
from .fx import table, text
from .modern_button import TYPES as BUTTON_TYPES, validate as style_validate
from .store import DataSource

# 1.0.2 values were recovered from the supplied Microsoft template. The new
# documentation's 1.0.0 uses a distinct positioning enum, not an orientation.
DEFAULTS={'Default':'=Blank()', 'Items':'=Table()', 'Height':'=60',
          'Width':'=300', 'Align':'=Align.Center', 'Appearance':'=TabListAppearance.Transparent'}
VERSION_DEFAULTS={'1.0.2':{'Alignment':'=LayoutDirection.Horizontal','TabSize':'=TabSize.Large'},
                  '1.0.0':{'Alignment':'=TabListAlignment.Center'}}
TYPES={p:t for p,t in BUTTON_TYPES.items() if p not in ('Icon','IconStyle','IconRotation','Layout')}
TYPES.update(Alignment='Text', TabSize='Text', ItemDisplayText='Text')
APPEARANCES={'1.0.2':('Transparent','Subtle','SubtleCircular','FilledCircular'),
             '1.0.0':('Transparent','Subtle','Underline','Filled')}

def validate(ref,name,value,actual=None):
    if ref.control.version not in VERSION_DEFAULTS and name in (*TYPES,'Items','Default'):
        raise FxError(f'Unsupported Tab List version {ref.control.version}','Unsupported')
    if name=='Appearance':
        if value is not None and value not in APPEARANCES[ref.control.version]:
            raise FxError(f'Tab List {name} does not support {value} in version {ref.control.version}','Type')
    elif name=='Alignment':
        values=('Horizontal','Vertical') if ref.control.version=='1.0.2' else ('Start','Center','End')
        if value is not None and value not in values:
            raise FxError('Tab List Alignment requires '+', '.join(values),'Type')
    elif name=='TabSize':
        if ref.control.version!='1.0.2':raise FxError('TabSize belongs to Tab List 1.0.2','Unsupported')
        if value is not None and value not in ('Small','Medium','Large'):raise FxError('TabSize requires Small, Medium or Large','Type')
    elif name=='Default':
        if isinstance(value,(list,DataSource)):raise FxError('Tab List Default requires one item, not a table','Type')
    elif name=='Items':
        rows=table(value)
        if any(not isinstance(row,(dict,FxError)) for row in rows):raise FxError('Tab List Items requires record rows','Type')
    elif name in TYPES and name!='ItemDisplayText':
        try:style_validate(name,value,actual)
        except FxError as error:raise FxError(error.message.replace('ModernButton','Tab List'),error.kind) from None

def default(ref,rows):
    chosen=ref.match_default(rows)
    # Omitted/Blank defaults retain the established first-tab fallback. Native
    # unmatched-default and reactive reset timing need a Studio recording.
    return chosen if chosen is not None else next((row for row in rows if not isinstance(row,FxError)),None) if ref.property('Default') is None else None

def selected(ref):
    if ref.control.version not in VERSION_DEFAULTS:
        raise FxError(f'Unsupported Tab List version {ref.control.version}','Unsupported')
    ref.sync_default('Selected')
    rows=table(ref.property('Items'))
    if 'Selected' in ref.state:
        chosen=next((row for row in rows if not isinstance(row,FxError) and ref.runtime.same_item(row,ref.state['Selected'])),None)
        if chosen is not None:return chosen
    return default(ref,rows)

def event(ref,name,value,selection):
    r=ref.runtime
    if name=='OnSelect' and value is None and selection is None:
        r.run_event(ref,name);r.drain_events();return
    if name!='OnChange':raise ValueError('Tab List accepts tab selection events')
    ref.sync_default('Selected')
    rows=table(ref.property('Items'))
    if isinstance(value,dict):
        if selection is not None or set(value)!={'indices','option_token'}:raise ValueError('Invalid tab selection operation')
        if value['option_token']!=r.selector_token(ref,rows):raise ValueError('Tabs changed; refresh before selecting')
        selection=value['indices']
    elif value is not None:raise ValueError('Invalid tab selection operation')
    if not isinstance(selection,list) or len(selection)!=1 or type(selection[0]) is not int or not 0<=selection[0]<len(rows):
        raise ValueError('Tab List requires one valid integer item index')
    chosen=rows[selection[0]]
    if isinstance(chosen,FxError):raise chosen
    previous=selected(ref)
    ref.state.update(Selected=chosen,dirty=not r.same_item(chosen,default(ref,rows)))
    r.invalidate()
    # Commit before either callback; the precise native callback ordering is
    # unverified. Repeated tab clicks always select, but do not change.
    r.run_event(ref,'OnSelect')
    if not r.same_item(previous,chosen):r.run_event(ref,'OnChange')
    r.drain_events()

def render(ref,node):
    r=ref.runtime; rows=table(ref.property('Items')); node['options']=[]
    for i,row in enumerate(rows):
        try:
            if isinstance(row,FxError):raise row
            raw=ref.raw_property('ItemDisplayText')
            from .row_rules import item_formula
            value=item_formula(ref,'ItemDisplayText',row) if raw else row.get('Value',row.get('Value1',row.get('Label',row.get('Title',''))))
            node['options'].append({'index':i,'label':text(value)})
        except FxError as error:
            r.render_error(ref,'ItemDisplayText',error)
            node['errors'].append(f'ItemDisplayText: {error.message}')
            node['options'].append({'index':i,'label':'Power Fx error: '+error.message,'disabled':True})
    chosen=None
    prop='Default'
    try:
        r.render_property(ref,prop)
        prop='Selected'
        chosen=r.render_property(ref,prop)
    except FxError as error:
        r.render_error(ref,prop,error);node['errors'].append(f'{prop}: {error.message}')
    node['selection']=[i for i,row in enumerate(rows) if not isinstance(row,FxError) and chosen is not None and r.same_item(row,chosen)][:1]
    node['option_token']=r.selector_token(ref,rows)
    node['tab_contract']={'version':ref.control.version,'authored':sorted(ref.control.properties)}

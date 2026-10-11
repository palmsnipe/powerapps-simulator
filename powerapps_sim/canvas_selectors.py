"""Archived canvas selectors. Native descriptors and local interaction models.

These families are distinct from ModernCombobox/ModernDropdown. Selection order,
search timing, retention across filtered Items, and reset behavior are local
models pending comparison with the archived controls in Power Apps.
"""
from functools import lru_cache
from pathlib import Path
from decimal import Decimal
import hashlib,json,math
from .syntax import FxError
from .canvas_inputs import LAYOUT

SELECTORS={'ComboBox','DropDown','Radio'}
FAMILIES=SELECTORS|{'ComboBoxDataField'}
OUTPUTS={'Selected','SelectedItems','SearchText'}
@lru_cache(maxsize=1)
def catalog():return json.loads((Path(__file__).parent/'static/canvas-selectors.json').read_text())
def radio_enums():
 props=next(iter(catalog()['Radio'].values()))['native_properties']
 return {p['Name']:{e['Name']:e['Value'] for e in p['EnumValues']} for p in props if p.get('EnumValues')}
def spec(ref):
 try:return catalog()[ref.family][ref.control.version]
 except KeyError:raise FxError(f'Unsupported {ref.family} version {ref.control.version}','Unsupported') from None

def errors(control):
 if control.version not in catalog()[control.family]:return {'Version':f'Unsupported {control.kind} version'}
 s=catalog()[control.family][control.version];allowed=(set(s['types'])-OUTPUTS)|LAYOUT|{e['Name'] for e in s['events']}
 result={p:f'{control.kind} has no supported authored {p} property' for p in control.properties if p not in allowed}
 variant=control.raw.get('Variant')
 if variant and not (control.family=='ComboBoxDataField' and variant=='textualColumn'):result['Variant']='Unsupported native selector variant'
 if control.family=='ComboBoxDataField' and (not control.parent or control.parent.family!='ComboBox'):result['Parent']='ComboBoxDataField requires a native ComboBox parent'
 return result

def guard(ref,name):
 s=spec(ref);findings=errors(ref.control)
 for p in ('Version','Variant','Parent',name):
  if p in findings:raise FxError(findings[p],'Unsupported')
 allowed=set(s['types'])|LAYOUT|{e['Name'] for e in s['events']}|{'Name'}
 if ref.family in SELECTORS:allowed.add('Reset')
 if name not in allowed:raise FxError(f'{ref.control.kind} has no supported {name} property','Unsupported')

def validate(ref,name,value):
 s=spec(ref);typ=s['types'].get(name)
 if value is None:return
 if name in s['enum_values'] and value not in s['enum_values'][name]:raise FxError(f'{ref.family}.{name} requires '+', '.join(s['enum_values'][name]),'Type')
 if typ=='Text' and not isinstance(value,str):raise FxError(f'{ref.family}.{name} requires Text','Type')
 if typ=='Boolean' and not isinstance(value,bool):raise FxError(f'{ref.family}.{name} requires Boolean','Type')
 if typ=='Number':
  if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):raise FxError(f'{ref.family}.{name} requires a finite Number','Type')
  if name in ('Order','TabIndex') and value!=int(value):raise FxError(f'{ref.family}.{name} requires an integer','Type')
  if name not in ('TabIndex','X','Y','ZIndex') and value<0:raise FxError(f'{ref.family}.{name} cannot be negative','Validation')
 if typ=='Table':
  if not isinstance(value,list):raise FxError(f'{ref.family}.{name} requires a Table','Type')
  if any(not isinstance(row,(dict,FxError)) for row in value):raise FxError(f'{ref.family}.{name} requires record rows','Type')
 if name=='DisplayMode' and value not in ('Edit','View','Disabled'):raise FxError('Selector.DisplayMode requires Edit, View or Disabled','Type')
 if name=='FieldType' and value not in ('s','l','d'):raise FxError('Unsupported ComboBoxDataField.FieldType '+str(value),'Unsupported')
 if name=='FieldVariantName' and value!='textualColumn':raise FxError('Unsupported ComboBoxDataField.FieldVariantName','Unsupported')

def fields(ref):
 children=ref.children
 if ref.family=='Radio':
  if children:raise FxError('Native Radio does not support metadata children','Unsupported')
  # The archive has no ItemDisplayText/field-child contract. Resolve a local
  # display column once per table: Value, first text field, first scalar field.
  # This keeps the archived multi-column fixture usable without changing source.
  first=next((row for row in rows(ref) if isinstance(row,dict)),{})
  names=[k for k in first if not k.startswith('_')]
  name=next((k for k in names if k.casefold()=='value'),None)
  if name is None:name=next((k for k in names if isinstance(first[k],str)),None)
  if name is None:name=next((k for k in names if not isinstance(first[k],(dict,list,FxError))),None)
  return [(0,name or 'Value',ref)]
 if any(c.family!='ComboBoxDataField' for c in children):raise FxError('Native selectors accept only ComboBoxDataField metadata children','Unsupported')
 result=[]
 for c in children:
  c.property('FieldType');c.property('FieldVariantName')
  name=c.property('FieldName')
  if not name:raise FxError('ComboBoxDataField.FieldName requires a nonempty field name','Validation')
  result.append((c.property('Order') or 0,name,c))
 return sorted(result,key=lambda x:x[0])

def label(ref,row,configured=None):
 if isinstance(row,FxError):raise row
 if not isinstance(row,dict):raise FxError('Selector items require records','Type')
 configured=fields(ref) if configured is None else configured
 names=[f[1] for f in configured] or ['Value']
 parts=[]
 for name in names:
  # Resolve display/internal SharePoint names using the authoritative member path.
  value=ref.runtime.fx.member(row,name,ref.context())
  if isinstance(value,FxError):raise value
  if isinstance(value,(dict,list)):raise FxError('Selector display fields require scalar values','Type')
  parts.append(ref.runtime.fx.to_text(value))
 return parts[0], ' · '.join(parts[1:])

def rows(ref):
 value=ref.property('Items');return [] if value is None else value

def multiple(ref):return ref.family=='ComboBox' and ref.property('SelectMultiple') is True

def selection(ref):
 ref.sync_default('Selected');items=rows(ref)
 from .data_table import row_keys
 keys=row_keys(items);chosen=ref.state.get('canvas_selection')
 if chosen is None:
  chosen=[];defaults=ref.property('DefaultSelectedItems') or []
  for default in defaults:
   if isinstance(default,FxError):raise default
   index=next((i for i,row in enumerate(items) if not isinstance(row,FxError) and keys[i] not in [c[0] for c in chosen] and ref.runtime.same_item(row,default)),None)
   if index is not None:chosen.append((keys[index],items[index]))
   if chosen and not multiple(ref):break
 if 'canvas_baseline' not in ref.state:ref.state['canvas_baseline']=list(chosen)
 # Retain records across filtered Items; refresh matching IDs without changing order.
 current=dict(zip(keys,items));chosen=[(key,current.get(key,row)) for key,row in chosen]
 return chosen if multiple(ref) else chosen[:1]

def output(ref,name):
 if name=='SearchText':return ref.state.get('canvas_search','') if ref.property('IsSearchable') is not False else ''
 selected=selection(ref)
 return [row for _,row in selected] if name=='SelectedItems' else selected[0][1] if selected else None

def search_token(ref):
 from .runtime import serial
 data=[ref.runtime.text_generation,ref.path,ref.runtime.combo_resets.get(ref.path,0),ref.control.kind,serial(ref.property('DefaultSelectedItems')),ref.property('IsSearchable'),ref.property('TriggerOutput'),[(c.path,dict(c.control.properties)) for c in ref.children]]
 return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()

def token(ref):
 from .runtime import serial
 data=[ref.runtime.text_generation,ref.path,ref.runtime.combo_resets.get(ref.path,0),ref.control.kind,serial(rows(ref)),serial(selection(ref)),multiple(ref),[(c.path,serial(c.property('FieldName')),serial(c.property('Order'))) for c in ref.children]]
 if ref.family=='ComboBox':data.extend([output(ref,'SearchText'),ref.property('IsSearchable'),ref.property('TriggerOutput')])
 return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()

def event(ref,name,data,indices):
 guard(ref,'Selected');ref.sync_default('Selected')
 if indices is not None:raise ValueError('Native selector events require an option token')
 if name=='OnSearch' and ref.family=='ComboBox':
  if not isinstance(data,dict) or set(data)!={'text','reset_token'} or not isinstance(data['text'],str) or not isinstance(data['reset_token'],str):raise ValueError('Search requires Text and an instance token')
  if data['reset_token']!=search_token(ref):return
  if ref.property('IsSearchable') is False:raise ValueError('Selector search is disabled')
  if data['text']!=output(ref,'SearchText'):ref.state['canvas_search']=data['text'];ref.runtime.invalidate()
  return
 if name!='OnChange' or not isinstance(data,dict):raise ValueError('Unsupported native selector event')
 if not isinstance(data.get('option_token'),str):raise ValueError('Selection requires an option token')
 if data['option_token']!=token(ref):return
 before=selection(ref);chosen=list(before);op=data.get('operation');items=rows(ref)
 from .data_table import row_keys
 keys=row_keys(items)
 if 'indices' in data:
  if set(data)!={'indices','option_token'}:raise ValueError('Unexpected selection payload')
  indexes=data['indices']
  if not isinstance(indexes,list) or any(type(i) is not int or not 0<=i<len(items) for i in indexes) or len(set(indexes))!=len(indexes):raise ValueError('Invalid row indices')
  if not multiple(ref) and len(indexes)>1:raise ValueError('Single selection requires at most one row')
  chosen=[(keys[i],items[i]) for i in indexes]
 elif op=='clear':
  if set(data)!={'operation','option_token'}:raise ValueError('Unexpected clear payload')
  chosen=[]
 elif op in ('toggle','remove'):
  if set(data)!={'operation','index','option_token'} or type(data['index']) is not int:raise ValueError('Selection requires an integer index')
  i=data['index']
  if op=='remove':
   if not 0<=i<len(chosen):raise ValueError('Invalid selected item index')
   chosen.pop(i)
  else:
   if not 0<=i<len(items):raise ValueError('Invalid option index')
   entry=(keys[i],items[i]);present=any(key==keys[i] for key,_ in chosen)
   chosen=[c for c in chosen if c[0]!=keys[i]] if present and multiple(ref) else chosen if present else chosen+[entry] if multiple(ref) else [entry]
 else:raise ValueError('Unsupported selection operation')
 configured=fields(ref)
 for _,row in chosen:label(ref,row,configured)
 if chosen==before:return
 ref.state['canvas_selection']=chosen
 baseline=ref.state.get('canvas_baseline',[])
 ref.state['dirty']=len(chosen)!=len(baseline) or any(not ref.runtime.same_item(a[1],b[1]) for a,b in zip(chosen,baseline))
 ref.runtime.invalidate();ref.runtime.run_event(ref,'OnChange');ref.runtime.drain_events()

def render(ref,node):
 spec(ref);configured=fields(ref);items=rows(ref);chosen=selection(ref)
 from .data_table import row_keys
 keys=row_keys(items);query=output(ref,'SearchText') if ref.family=='ComboBox' else ''
 options=[]
 for i,row in enumerate(items):
  try:
   text,secondary=label(ref,row,configured)
   if query and query.casefold() not in (text+' '+secondary).casefold():continue
   options.append({'index':i,'label':text,'secondary':secondary,'disabled':False})
  except FxError as error:
   target=configured[0][2] if configured else ref
   ref.runtime.render_error(target,'Items' if ref.family=='Radio' or not configured else 'FieldName',error)
   node['errors'].append(f'Item {i+1}: {error.message}')
   options.append({'index':i,'label':error.message,'disabled':True,'error':True})
 labels=[label(ref,row,configured)[0] for _,row in chosen]
 node.update(options=options,selection=[i for i,key in enumerate(keys) if key in [c[0] for c in chosen]],selected_labels=labels,option_token=token(ref))
 if ref.family=='ComboBox':node.update(search_text=query,search_reset=search_token(ref))
 else:node['selected']=chosen[0][1] if chosen else None

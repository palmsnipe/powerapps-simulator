"""Native TextInput and CheckBox contracts, kept distinct from modern aliases."""
from functools import lru_cache
from pathlib import Path
from decimal import Decimal
import json,math
from .syntax import FxError

FAMILIES={'TextInput','CheckBox'}
LAYOUT={'LayoutMinWidth','LayoutMinHeight','LayoutMaxWidth','LayoutMaxHeight','FillPortions','AlignInContainer'}
@lru_cache(maxsize=1)
def catalog():return json.loads((Path(__file__).parent/'static/canvas-inputs.json').read_text())
def spec(ref):
 try:return catalog()[ref.family][ref.control.version]
 except KeyError:raise FxError(f'Unsupported {ref.family} version {ref.control.version}','Unsupported') from None

def errors(control):
 if control.version not in catalog()[control.family]:return {'Version':f'Unsupported {control.kind} version'}
 s=catalog()[control.family][control.version];allowed=set(s['types'])|LAYOUT|{e['Name'] for e in s['events']}
 result={p:f'{control.kind} has no supported authored {p} property' for p in control.properties if p not in allowed}
 if control.raw.get('Variant'):result['Variant']='Native canvas input variants are unsupported'
 return result

def validate(ref,name,value):
 s=spec(ref);typ=s['types'].get(name)
 if value is None:return
 if name in s['enum_values'] and value not in s['enum_values'][name]:raise FxError(f'{ref.family}.{name} requires '+', '.join(s['enum_values'][name]),'Type')
 if typ=='Text' and not isinstance(value,str):raise FxError(f'{ref.family}.{name} requires Text','Type')
 if typ=='Boolean' and not isinstance(value,bool):raise FxError(f'{ref.family}.{name} requires Boolean','Type')
 if typ=='Number':
  if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):raise FxError(f'{ref.family}.{name} requires a finite Number','Type')
  if name in ('MaxLength','TabIndex') and value!=int(value):raise FxError(f'{ref.family}.{name} requires an integer','Type')
  if name=='MaxLength' and value<-1:raise FxError('TextInput.MaxLength must be -1 or greater','Validation')
  if name not in ('MaxLength','TabIndex','X','Y') and value<0:raise FxError(f'{ref.family}.{name} cannot be negative','Validation')

def value(ref,raw):
 name='Value' if ref.family=='TextInput' else 'Checked';validate(ref,name,raw)
 return raw if ref.family=='TextInput' else False if raw is None else raw

def token(ref):
 r=ref.runtime
 if ref.family=='CheckBox':return r.selection_epoch(ref)
 return r.text_token(ref)

def contract(ref):
 if ref.family=='TextInput' and ref.property('Mode')=='Multiline' and ref.property('Type')=='Password':
  raise FxError('Multiline password input is unsupported','Unsupported')

def event(ref,name,data,selection):
 r=ref.runtime;prop='Value' if ref.family=='TextInput' else 'Checked'
 if selection is not None:raise ValueError('Native canvas inputs do not accept row selections')
 if ref.family=='CheckBox' and name=='OnSelect' and data is None:r.run_event(ref,name);r.drain_events();return
 if name not in (('OnInput','OnChange') if ref.family=='TextInput' else ('OnSelect',)):raise ValueError('Unsupported native canvas input event')
 ref.sync_default(prop);contract(ref)
 field='text' if ref.family=='TextInput' else 'checked'
 if not isinstance(data,dict) or set(data)!={field,'reset_token'} or not isinstance(data['reset_token'],str):raise ValueError('Input requires a value and instance token')
 if data['reset_token']!=token(ref):return
 raw=data[field];validate(ref,prop,raw)
 if raw is None:raise ValueError('User input requires Text or Boolean')
 previous=ref.property(prop);baseline=r.input_baselines[ref.path]
 if ref.family=='CheckBox':baseline=value(ref,baseline)
 if ref.family=='TextInput':
  maximum=ref.property('MaxLength');maximum=-1 if maximum is None else maximum
  if maximum>=0 and len(raw.encode('utf-16-le',errors='surrogatepass'))//2>maximum:raise ValueError('TextInput exceeds MaxLength')
  if name=='OnInput' and ref.property('TriggerOutput')=='FocusOut':raise ValueError('FocusOut commits only on blur')
  previous='' if previous is None else previous;baseline='' if baseline is None else baseline
  if raw==previous:return
 ref.state.update({prop:raw,'dirty':raw!=baseline})
 r.invalidate()
 if ref.family=='CheckBox' and raw!=previous:r.run_event(ref,'OnCheck' if raw else 'OnUncheck')
 r.run_event(ref,'OnChange' if ref.family=='TextInput' else 'OnSelect');r.drain_events()

def render(ref,node):
 contract(ref);node['value']=value(ref,ref.property('Value' if ref.family=='TextInput' else 'Checked'))
 node['text_reset' if ref.family=='TextInput' else 'check_reset']=token(ref)
 node['canvas_input']={'family':ref.family,'version':ref.control.version,'authored':sorted(ref.control.properties)}

"""Classic ComboBox contracts: field-based display/search and last selection."""
from functools import lru_cache
from pathlib import Path
from decimal import Decimal
import json,math
from .syntax import FxError
def table(value):
    from .fx import table as rows
    return rows(value)

COMBOBOXES=frozenset(('ModernCombobox','Classic/ComboBox'))

@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent/'static/classic-combobox.json').read_text())

def selected_record(ref,rows):
    return rows[-1 if ref.family=='Classic/ComboBox' else 0] if rows else None

def validate(ref,name,value):
    if name in ('SelectMultiple','IsSearchable','Reset','UsePhoneLayout') and not isinstance(value,bool):
        raise FxError(f'Classic ComboBox {name} requires a Boolean','Type')
    if name=='UsePhoneLayout' and value is True:
        raise FxError('Classic ComboBox full-screen phone layout is not implemented','Unsupported')
    if name=='Template' and value not in ('Single','Double','Person'):
        raise FxError('ComboBox Template requires Single, Double or Person','Type')
    if name in ('DisplayFields','SearchFields','NavigateFields'):
        if not isinstance(value,list) or any(not isinstance(row,dict) or len(row)!=1 or not isinstance(next(iter(row.values())),str) or not next(iter(row.values())) for row in value):
            raise FxError(f'ComboBox {name} requires a single-column table of nonempty field names','Type')
    if name in ('Items','SearchItems','DefaultSelectedItems'):
        if value is not None and not isinstance(value,list) and not hasattr(value,'rows'):
            raise FxError(f'ComboBox {name} requires records','Type')
        if any(row is not None and not isinstance(row,(dict,FxError)) for row in table(value)):
            raise FxError(f'ComboBox {name} requires record rows','Type')
    kind=catalog()['types'].get(name)
    if kind=='Number' and (isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value))):
        raise FxError(f'ComboBox {name} requires a finite Number','Type')
    if kind=='Number' and value<0 and name!='TabIndex':raise FxError(f'ComboBox {name} cannot be negative','Validation')
    if kind=='Text' and value is not None and not isinstance(value,str):raise FxError(f'ComboBox {name} requires Text','Type')

def fields(ref,name):
    return [next(iter(row.values())) for row in ref.property(name)]

def display(ref,row):
    if row is None:return []
    if isinstance(row,FxError):raise row
    if not isinstance(row,dict):raise FxError('ComboBox Items requires records','Type')
    names=fields(ref,'DisplayFields')
    count=1 if ref.property('Template')=='Single' else 2
    return [ref.runtime.fx.to_text(ref.runtime.fx.member(row,n,ref.context())) for n in names[:count]]

def search_items(ref):
    rows=table(ref.property('Items'));query=ref.property('SearchText')
    if not ref.property('IsSearchable') or not query:return rows
    names=fields(ref,'SearchFields');result=[]
    for row in rows:
        if isinstance(row,FxError):result.append(row);continue
        matches=False
        for name in names:
            value=ref.runtime.fx.member(row,name,ref.context())
            if value is not None and not isinstance(value,str):raise FxError(f'ComboBox SearchFields column {name} must contain Text; convert numbers with Text','Type')
            matches|=query.casefold() in (value or '').casefold()
        if matches:result.append(row)
    return result

def decorate(ref,node,items,chosen):
    # Search options retain stable indices into Items, including custom SearchItems.
    shown=table(ref.property('SearchItems'))
    node['options']=[o for o in node['options'] if any(ref.runtime.same_item(items[o['index']],r) for r in shown)]
    for o in node['options']:
        if o.get('disabled'):continue
        row=items[o['index']];values=display(ref,row)
        o['secondary']=values[1] if len(values)>1 else ''
        o['person']=ref.property('Template')=='Person'
        o['navigable']=bool(fields(ref,'NavigateFields'))
    node['selected_labels']=[(display(ref,row) or [''])[0] for row in chosen if row is not None]

"""Canvas classic input contracts, separate from the modern/PCF families."""
from functools import lru_cache
from pathlib import Path
import json,math,re
from decimal import Decimal
from .syntax import FxError

TEXT_INPUTS=frozenset(('ModernTextInput','Classic/TextInput'))
CLASSIC_SELECTORS=frozenset(('Classic/DropDown','Classic/Radio'))
CLASSIC_BOOLEAN=frozenset(('Classic/CheckBox','Classic/Toggle'))
SLIDERS=frozenset(('ModernSlider','Classic/Slider'))
DATE_PICKERS=frozenset(('ModernDatePicker','Classic/DatePicker','DatePicker'))
CLASSIC_INPUTS=frozenset((*CLASSIC_SELECTORS,*CLASSIC_BOOLEAN,'Classic/TextInput','Classic/Slider','Classic/DatePicker'))

@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent/'static/classic-inputs.json').read_text(encoding='utf-8'))['controls']

def validate(ref,name,value,actual=None):
    if ref.family in ('Classic/Radio','Classic/Slider') and name=='Layout' and value not in ('Horizontal','Vertical'):
        raise FxError(f'{ref.family} Layout requires Horizontal or Vertical','Type')
    if ref.family=='Classic/Toggle' and name=='TextPosition' and value not in ('Left','Right'):
        raise FxError('Toggle TextPosition requires Left or Right','Type')
    if ref.family=='Classic/TextInput':
        enums={'Mode':('SingleLine','MultiLine','Password'),'Format':('Text','Number'),'VirtualKeyboardMode':('Auto','Text','Numeric')}
        if name in enums and value not in enums[name]:raise FxError(f'{name} requires '+', '.join(enums[name]),'Type')
    kind=catalog()[ref.family]['types'].get(name)
    if kind=='Boolean' and not isinstance(value,bool):raise FxError(f'{name} requires a Boolean','Type')
    if kind=='Color' and value is not None and (not isinstance(value,str) or actual and actual.kind not in ('Color','Blank','Unknown','Error')):
        raise FxError(f'{name} requires a Color','Type')
    if kind=='Number':
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):raise FxError(f'{name} requires a finite Number','Type')
        if name in ('MaxLength','TabIndex','StartYear','EndYear') and value!=int(value):raise FxError(f'{name} requires an integer','Type')
        if ref.family=='Classic/DatePicker' and name in ('StartYear','EndYear') and not 1000<=value<=9999:
            raise FxError(f'{name} requires a year from 1000 to 9999','Validation')
        if name!='TabIndex' and not (ref.family=='Classic/Slider' and name in ('Default','Value','Min','Max')) and value<0:raise FxError(f'{name} cannot be negative','Validation')
    if kind=='Text' and name not in ('Default','Text') and value is not None and not isinstance(value,str):raise FxError(f'{name} requires Text','Type')

def display(ref,row):
    """Resolve authored display/logical names; do not guess multi-column fields."""
    if row is None:return ''
    if isinstance(row,FxError):raise row
    if not isinstance(row,dict):raise FxError('Classic selection Items requires record rows','Type')
    field=ref.property('Value')
    if not field:raise FxError('Classic selection Value requires a display column','Validation')
    return ref.runtime.fx.to_text(ref.runtime.fx.member(row,field,ref.context()))

def match_default(ref,rows):
    if ref.family=='Classic/DropDown':rows=rows[:500]
    default=ref.property('Default')
    if isinstance(default,(dict,list)):raise FxError('Classic selection Default requires a scalar display value','Type')
    valid=[row for row in rows if not isinstance(row,FxError)]
    if default is not None:
        match=next((row for row in valid if ref.runtime.same_item(display(ref,row),ref.runtime.fx.to_text(default))),None)
        if match is not None:return match
    if ref.family=='Classic/Radio':return None
    return None if ref.property('AllowEmptySelection') else next(iter(valid),None)

def numeric_text(value):
    # Browser-language numeric symbol restrictions vary by platform. This is
    # the supported Latin input approximation; Text remains unparsed text.
    return re.fullmatch(r'[0-9+\-.,eE\s]*',value) is not None

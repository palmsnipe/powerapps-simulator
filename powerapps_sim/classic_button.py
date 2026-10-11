"""Audited classic button templates and presentation/interaction contracts."""
from functools import lru_cache
from pathlib import Path
from decimal import Decimal
import json
import math
from .syntax import FxError

@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent/'static/classic-buttons.json').read_text(encoding='utf-8'))

VERSIONS=frozenset(catalog()['versions'])
DEFAULTS={**catalog()['versions']['2.2.0']['defaults'],
    'Text':'="Button"','Pressed':'=false','AutoDisableOnSelect':'=true',
    'BorderStyle':'=BorderStyle.Solid','Italic':'=false','Underline':'=false','Strikethrough':'=false','TabIndex':'=0'}
# Shared-property defaults without values in the shipped template are explicit
# host fallbacks. Text localization and native theme replacement remain open.
ENUMS={'Align':('Left','Center','Right','Justify'),'VerticalAlign':('Top','Middle','Bottom'),
    'BorderStyle':('Solid','Dashed','Dotted','None'),'FontWeight':('Normal','Bold','Semibold','Lighter')}
TYPES={**{p:'Text' for p in ('Text','Font',*ENUMS)},
    **{p:'Number' for p in ('Size','BorderThickness','FocusedBorderThickness','TabIndex',
        'PaddingTop','PaddingBottom','PaddingLeft','PaddingRight','RadiusTopLeft','RadiusTopRight','RadiusBottomLeft','RadiusBottomRight')},
    **{p:'Boolean' for p in ('Pressed','AutoDisableOnSelect','Italic','Underline','Strikethrough')},
    **{p:'Color' for p in ('Color','Fill','BorderColor','DisabledColor','DisabledFill','DisabledBorderColor',
        'HoverColor','HoverFill','HoverBorderColor','PressedColor','PressedFill','PressedBorderColor','FocusedBorderColor')}}

def validate(ref,name,value,actual=None):
    if name in ENUMS and value is not None and value not in ENUMS[name]:raise FxError(f'Classic/Button.{name} requires '+', '.join(ENUMS[name]),'Type')
    kind=TYPES.get(name)
    if kind=='Number' and value is not None:
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):
            raise FxError(f'Classic/Button.{name} requires a finite Number','Type')
        if name=='TabIndex' and value!=int(value):raise FxError('TabIndex requires an integer','Type')
        if name!='TabIndex' and value<0:raise FxError(f'Classic/Button.{name} cannot be negative','Validation')
    if kind=='Boolean' and value is not None and not isinstance(value,bool):raise FxError(f'Classic/Button.{name} requires Boolean','Type')
    if kind=='Color' and value is not None and (not isinstance(value,str) or actual and actual.kind not in ('Color','Blank','Unknown','Error')):
        raise FxError(f'Classic/Button.{name} requires Color','Type')
    if kind=='Text' and name not in ('Text',*ENUMS) and value is not None and not isinstance(value,str):raise FxError(f'Classic/Button.{name} requires Text','Type')

def errors(control):
    from .controls import COMMON
    if control.version not in VERSIONS:return {'Version':f'Unsupported classic button version {control.kind}'}
    allowed=set(catalog()['versions'][control.version]['properties'])|set(COMMON)-{'OnChange'}
    allowed|={'LayoutMinWidth','LayoutMinHeight','LayoutMaxWidth','LayoutMaxHeight','FillPortions','AlignInContainer'}
    result={name:f'Classic/Button@{control.version} does not support authored {name}'
        for name in control.properties if name not in allowed or name=='Pressed'}
    if control.version in ('2.0.0','2.0.1') and 'ContentLanguage'in control.properties:
        result['ContentLanguage']='ContentLanguage was added after Classic/Button 2.0.1'
    return result

def variant(ref,name):
    profile=ref.runtime.project.config.get('form_factor')
    spec=catalog()['versions'].get(ref.control.version,{})
    return spec.get('variants',{}).get(profile,{}).get(name)

def render(ref,node):
    node['classic_button']={'auto_disable':bool(node['props'].get('AutoDisableOnSelect')),
        'pressed':bool(ref.state.get('Pressed',False)),'busy':ref.path in ref.runtime.button_busy}

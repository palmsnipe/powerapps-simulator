"""Offline glyph resolution and versioned modern/classic icon contracts."""
from functools import lru_cache
from pathlib import Path
import json,math
from decimal import Decimal
from .syntax import FxError,call_name

# Canvas classic names with different Fluent spellings. Unmapped names are
# resolved against the pinned catalog; unknown values are never placeholders.
CLASSIC={'Add':'Add','Cancel':'Dismiss','Check':'Checkmark','ChevronDown':'ChevronDown','ChevronLeft':'ChevronLeft','ChevronRight':'ChevronRight','ChevronUp':'ChevronUp','Delete':'Delete','Edit':'Edit','Home':'Home','Search':'Search','Settings':'Settings','Save':'Save','Filter':'Filter','Reload':'ArrowClockwise','Sync':'ArrowSync','Sort':'ArrowSort','BackArrow':'ArrowLeft','NextArrow':'ArrowRight','ArrowDown':'ArrowDown','ArrowLeft':'ArrowLeft','ArrowRight':'ArrowRight','ArrowUp':'ArrowUp','ShoppingCart':'Cart','Information':'Info','Warning':'Warning','Bell':'Alert','Blocked':'Prohibited','View':'Eye','Hide':'EyeOff','Lock':'LockClosed','Unlock':'LockOpen','Person':'Person','People':'People','Mail':'Mail','CalendarBlank':'Calendar','Document':'Document','Print':'Print','Download':'ArrowDownload','Upload':'ArrowUpload'}

@lru_cache(maxsize=1)
def classic_catalog():
    return json.loads((Path(__file__).parent/'static/classic-icons.json').read_text(encoding='utf-8'))

CLASSIC.update({key:spec['name'] for key,spec in classic_catalog()['icons'].items()})

class IconValue(str):
    """Retain enum identity with compatible serialized Fluent names.

    Type(Icon) is not introduced. Explicit Text conversion removes identity.
    """
    def __new__(cls, name):
        result=super().__new__(cls,CLASSIC[name])
        result.legacy_name=name
        return result

    def __eq__(self,other):return isinstance(other,IconValue) and self.legacy_name==other.legacy_name
    def __ne__(self,other):return not self.__eq__(other)
    def __hash__(self):return hash(self.legacy_name)
    def __reduce__(self):return (IconValue,(self.legacy_name,))

def classic_glyph(value):
    if value is None:return None
    if not isinstance(value,IconValue):raise FxError('Classic Icon requires an Icon enum value, such as Icon.Check','Type')
    spec=classic_catalog()['icons'].get(value.legacy_name)
    if spec is None:raise FxError(f'Classic Icon.{value.legacy_name} is not verified for version 2.5.0','Unsupported')
    return {**glyph(spec['name'],spec['style']),'legacy_name':value.legacy_name}

@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent/'static/fluent-icons.json').read_text(encoding='utf-8'))

@lru_cache(maxsize=1)
def names():return {name.casefold():name for name in catalog()['icons']}


def glyph(value,style='Outline'):
    if value is None or value=='':return None
    if not isinstance(value,str):raise FxError('Icon requires a Fluent icon name','Type')
    value=str(value)
    if style is not None and style not in ('Outline','Filled'):raise FxError('IconStyle requires Outline or Filled','Type')
    name=value if value in catalog()['icons'] else names().get(value.casefold()) or names().get(CLASSIC.get(value,value).casefold())
    if name is None:raise FxError(f'Unsupported Fluent icon {value}','Unsupported')
    if style is None:return {'name':name}
    symbol=catalog()['icons'][name].get(style)
    if symbol is None:raise FxError(f'Fluent icon {name} has no bundled {style} glyph','Unsupported')
    return {'name':name,'symbol':symbol,'style':style}


def active(ref):
    raw=ref.control.properties.get('OnSelect')
    if raw is None or raw=='':return False
    try:
        node=ref.runtime.fx.parse(raw)
        return node.kind!='literal' and not (node.kind=='call' and call_name(node.children[0])=='Blank' and len(node.children)==1)
    except FxError:
        return True  # Invalid authored formulas remain visible and inspectable.


PROPERTY_TYPES={**{p:'Color' for p in ('IconColor','BasePaletteColor','Fill','BorderColor')},**{p:'Text' for p in ('Icon','IconStyle','AccessibleLabel','Tooltip','BorderStyle')},**{p:'Number' for p in ('Rotation','X','Y','Width','Height','BorderThickness','RadiusTopLeft','RadiusTopRight','RadiusBottomLeft','RadiusBottomRight','PaddingTop','PaddingBottom','PaddingLeft','PaddingRight')}}

CLASSIC_PROPERTY_TYPES={**PROPERTY_TYPES,**{p:'Color' for p in ('Color','DisabledColor','HoverColor','PressedColor','DisabledFill','HoverFill','PressedFill','DisabledBorderColor','HoverBorderColor','PressedBorderColor','FocusedBorderColor')},'TabIndex':'Number','FocusedBorderThickness':'Number','PreserveAspectRatio':'Boolean'}
CLASSIC_PROPERTY_TYPES={p:t for p,t in CLASSIC_PROPERTY_TYPES.items() if p not in ('IconColor','IconStyle','BasePaletteColor')}
CLASSIC_PROPERTY_TYPES['Icon']='Icon'
CLASSIC_RENDER_PROPERTIES=set(CLASSIC_PROPERTY_TYPES)-set(PROPERTY_TYPES)

def validate_classic(name,value,actual=None):
    if name=='Icon':classic_glyph(value)
    elif name=='PreserveAspectRatio':
        if not isinstance(value,bool):raise FxError('PreserveAspectRatio requires a Boolean','Type')
    elif name in ('TabIndex','FocusedBorderThickness'):
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):
            raise FxError(f'{name} requires a finite Number','Type')
        if name=='TabIndex' and value!=int(value):raise FxError('TabIndex requires a finite integer','Type')
        if name=='FocusedBorderThickness' and value<0:raise FxError('FocusedBorderThickness cannot be negative','Validation')
    elif CLASSIC_PROPERTY_TYPES.get(name)=='Color' and value is not None:
        if not isinstance(value,str) or actual and actual.kind not in ('Color','Blank','Unknown','Error'):
            raise FxError(f'{name} requires a Color','Type')
    else:validate(name,value,actual)


def validate(name,value,actual=None):
    if name=='Icon':
        glyph(value,None)
    elif name=='IconStyle' and value not in ('Outline','Filled'):
        raise FxError('IconStyle requires Outline or Filled','Type')
    elif name in ('Rotation','Width','Height','BorderThickness','RadiusTopLeft','RadiusTopRight','RadiusBottomLeft','RadiusBottomRight') or name.startswith('Padding'):
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):
            raise FxError(f'Icon {name} requires a finite Number','Type')
        if name!='Rotation' and value<0:raise FxError(f'Icon {name} cannot be negative','Validation')
    elif PROPERTY_TYPES.get(name)=='Color' and value is not None:
        if not isinstance(value,str) or actual and actual.kind not in ('Color','Blank','Unknown','Error'):
            raise FxError(f'{name} requires a Color','Type')

"""ModernButton@1.0.0 contracts, including the imported Microsoft template.

Icon/Style/Rotation/Layout defaults are recovered from the sample template.
Theme-derived font/color/border defaults retain the simulator's approximation.
"""
import math
from decimal import Decimal
from .syntax import FxError

DEFAULTS={'Icon':'=""','IconStyle':'=IconStyle.Outline','IconRotation':'=0',
    'Layout':'=ButtonLayout.IconBefore'}
TYPES={**{p:'Text' for p in ('Icon','IconStyle','Layout','Appearance','Align','VerticalAlign','BorderStyle','FontWeight')},
    **{p:'Number' for p in ('IconRotation','Size','BorderThickness','RadiusTopLeft','RadiusTopRight','RadiusBottomLeft','RadiusBottomRight')},
    **{p:'Boolean' for p in ('Italic','Underline','Strikethrough')},'Color':'Color','BorderColor':'Color'}
ENUMS={'Layout':('IconBefore','IconAfter','TextOnly','IconOnly'),
    'IconStyle':('Outline','Filled'), 'Appearance':('Primary','Secondary','Outline','Subtle','Transparent'),
    'Align':('Left','Center','Right','Justify'),'VerticalAlign':('Top','Middle','Bottom'),
    'BorderStyle':('Solid','Dashed','Dotted','None'),'FontWeight':('Normal','Bold','Semibold','Lighter')}


def validate(name,value,actual=None):
    if name in ENUMS and value is not None and value not in ENUMS[name]:
        raise FxError(f'ModernButton.{name} requires '+', '.join(ENUMS[name]),'Type')
    if name=='Icon':
        from .icons import glyph
        glyph(value,None)
    elif TYPES.get(name)=='Number' and value is not None:
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):
            raise FxError(f'ModernButton.{name} requires a finite Number','Type')
        if name!='IconRotation' and value<0:raise FxError(f'ModernButton.{name} cannot be negative','Validation')
    elif TYPES.get(name)=='Boolean' and value is not None and not isinstance(value,bool):
        raise FxError(f'ModernButton.{name} requires a Boolean','Type')
    elif TYPES.get(name)=='Color' and value is not None:
        if not isinstance(value,str) or actual and actual.kind not in ('Color','Blank','Unknown','Error'):
            raise FxError(f'ModernButton.{name} requires a Color','Type')


def render(ref,node):
    """Resolve the requested style rather than substituting an outline glyph."""
    from .icons import glyph
    r=ref.runtime
    node['button_authored']=sorted(ref.control.properties)
    try:
        node['icon']=glyph(ref.property('Icon'),ref.property('IconStyle') or 'Outline')
    except FxError as error:
        # Identify the property responsible; do not turn a bad style into a
        # misleading Icon diagnostic or dispatch a handler twice.
        prop='IconStyle' if (ref.path,'IconStyle') in r.property_cache and isinstance(r.property_cache[ref.path,'IconStyle'],FxError) else 'Icon'
        if not any(error.message in message for message in node['errors']):
            r.render_error(ref,prop,error)
            node['errors'].append(f'{prop}: {error.message}')

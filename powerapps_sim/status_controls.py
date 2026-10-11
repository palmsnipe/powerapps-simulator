"""Documented 1.0.0 Badge/InformationButton contracts.

Semantic palette/font inheritance and flyout placement are visual approximations;
no undocumented enum ordinals or native HTML formatting dialect are invented.
"""
import math
from decimal import Decimal
from .syntax import FxError
from .enum_fx import consume, EnumValue

FAMILIES = ('ModernBadge', 'ModernInformationButton')
from .status_enums import BADGE_ENUMS
ENUM_PROPERTIES = {'Appearance': 'BadgeAppearance', 'Shape': 'BadgeShape',
                   'Intent': 'BadgeIntent', 'IconPosition': 'BadgeIconPosition'}
DEFAULTS = {
    'ModernBadge': {'Content': '="AB"', 'Icon': '=Blank()', 'Width': '=64', 'Height': '=32',
        'IconPosition': '=BadgeIconPosition.Before', 'Appearance': '=BadgeAppearance.Tint',
        'Shape': '=BadgeShape.Circular', 'Intent': '=BadgeIntent.Positive',
        'Align': '=Align.Center', 'VerticalAlign': '=VerticalAlign.Middle',
        'Size': '=Blank()', 'Color': '=Blank()', 'Fill': '=Blank()', 'BasePaletteColor': '=Blank()'},
    'ModernInformationButton': {'Content': '=""', 'Width': '=32', 'Height': '=32', 'Size': '=15',
        'IconColor': '=Coalesce(Self.BasePaletteColor,RGBA(66,66,66,1))', 'BasePaletteColor': '=Blank()'},
}
TYPES = {**{p: 'Number' for p in ('X','Y','Width','Height','Size','PaddingTop','PaddingBottom','PaddingLeft','PaddingRight','BorderThickness','RadiusTopLeft','RadiusTopRight','RadiusBottomLeft','RadiusBottomRight')},
         **{p: 'Text' for p in ('Font','FontWeight','Align','VerticalAlign','BorderStyle','AccessibleLabel','Tooltip','ContentLanguage')},
         **{p: 'Boolean' for p in ('Italic','Underline','Strikethrough')},
         **{p: 'Color' for p in ('Color','Fill','BorderColor','BasePaletteColor','IconColor')}, 'Icon': 'Text'}
REMOVED = ('FontColor','FontSize','FontItalic','FontUnderline','FontStrikethrough','ThemeColor','AcceptsFocus','TabIndex')


def validate(ref, name, value, actual=None):
    family = ref.family
    if family == 'ModernBadge' and name in ENUM_PROPERTIES:
        namespace = ENUM_PROPERTIES[name]
        if ref.runtime.environment.get('enum_mode')=='strong' and not isinstance(value,EnumValue):
            raise FxError(f'{family}.{name} requires {namespace}', 'Type')
        if consume(value, namespace) not in BADGE_ENUMS[namespace]:
            raise FxError(f'{family}.{name} requires {namespace}', 'Type')
        return
    if name == 'Content':
        valid = value is None or isinstance(value,str) or (family == 'ModernBadge' and isinstance(value,(int,float,Decimal)) and not isinstance(value,bool) and math.isfinite(float(value)))
        if not valid:raise FxError(f'{family}.Content requires '+('Text or Number' if family=='ModernBadge' else 'Text'),'Type')
    kind = TYPES.get(name)
    if kind == 'Number' and value is not None:
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)):
            raise FxError(f'{family}.{name} requires a finite Number','Type')
        if name not in ('X','Y') and value < 0:raise FxError(f'{family}.{name} cannot be negative','Validation')
    if kind == 'Text' and value is not None and not isinstance(value,str):raise FxError(f'{family}.{name} requires Text','Type')
    if kind == 'Boolean' and value is not None and not isinstance(value,bool):raise FxError(f'{family}.{name} requires Boolean','Type')
    if kind == 'Color' and value is not None and (not isinstance(value,str) or actual and actual.kind not in ('Color','Blank','Unknown','Error')):
        raise FxError(f'{family}.{name} requires Color','Type')
    if name == 'Icon' and family == 'ModernBadge':
        from .icons import glyph
        glyph(value,'Outline')
    choices={'Align':('Left','Center','Right','Justify'),'VerticalAlign':('Top','Middle','Bottom'),
             'FontWeight':('Normal','Bold','Semibold','Lighter'),'BorderStyle':('Solid','Dashed','Dotted','None')}
    if name in choices and value is not None and value not in choices[name]:raise FxError(f'{family}.{name} requires '+', '.join(choices[name]),'Type')


def render(ref, node):
    from .icons import glyph, active
    node['status_authored'] = sorted(ref.control.properties)
    if ref.family == 'ModernBadge':
        node['selectable'] = active(ref)
        node['badge_text'] = ref.runtime.fx.to_text(ref.property('Content')) if 'Content' in node['props'] else ''
        for name,namespace in ENUM_PROPERTIES.items():
            if name in node['props']:node['props'][name] = consume(ref.property(name), namespace)
        try:node['icon'] = glyph(ref.property('Icon'),'Outline')
        except FxError as error:
            ref.runtime.render_error(ref,'Icon',error)
            if not any(error.message in message for message in node['errors']):node['errors'].append('Icon: '+error.message)
    else:
        from .html_controls import fragment
        node['icon'] = glyph('Info','Outline')
        safe = fragment(node['props'].get('Content') or '')
        node['info_html'] = safe['html']
        for message in safe['issues']:
            node['errors'].append(message)
            ref.runtime.diagnostic(FxError(message,'Unsupported'),ref.control.source,ref.name+'.Content',ref.raw_property('Content'))

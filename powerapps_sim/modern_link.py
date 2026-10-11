"""Documented ModernLink@1.0.0 properties and locally validated destinations."""
import math
from decimal import Decimal
from urllib.parse import urlsplit
from .syntax import FxError
from .enum_fx import EnumValue, consume

DEFAULTS = {'Text':'="Link"', 'URL':'=""', 'Type':'=LinkAppearance.Default',
    'Wrap':'=true', 'AutoHeight':'=false', 'Width':'=150', 'Height':'=32', 'Size':'=15',
    'Align':'=Align.Left', 'VerticalAlign':'=VerticalAlign.Middle',
    'PaddingTop':'=5', 'PaddingBottom':'=5', 'PaddingLeft':'=5', 'PaddingRight':'=5',
    'Italic':'=false', 'Underline':'=true', 'Strikethrough':'=false',
    'Color':'=Blank()', 'BasePaletteColor':'=Blank()', 'BorderColor':'=Color.Transparent',
    'BorderStyle':'=BorderStyle.Solid', 'RadiusTopRight':'=0', 'RadiusBottomLeft':'=0', 'RadiusBottomRight':'=0'}
TYPES = {**{p:'Number' for p in ('X','Y','Width','Height','Size','PaddingTop','PaddingBottom','PaddingLeft','PaddingRight','BorderThickness','RadiusTopLeft','RadiusTopRight','RadiusBottomLeft','RadiusBottomRight','LayoutMinWidth','LayoutMinHeight','LayoutMaxWidth','LayoutMaxHeight','FillPortions')},
    **{p:'Text' for p in ('Text','URL','Url','Type','Font','FontWeight','Align','VerticalAlign','BorderStyle','AccessibleLabel','ContentLanguage','AlignInContainer','DisplayMode','Name')},
    **{p:'Boolean' for p in ('Visible','Wrap','AutoHeight','Italic','Underline','Strikethrough')},
    **{p:'Color' for p in ('Color','Fill','BorderColor','BasePaletteColor')}}
PROPERTIES = frozenset(TYPES)


def errors(control):
    findings = {p:f'{control.kind} does not support {p}' for p in control.properties if p not in PROPERTIES}
    if control.version != '1.0.0': findings['Version'] = f'Unsupported ModernLink version {control.version}'
    if control.raw.get('Variant'): findings['Variant'] = 'ModernLink has no verified Variant contract'
    if 'URL' in control.properties and 'Url' in control.properties:
        findings['URL'] = 'ModernLink has both URL and Url; author one spelling'
    return findings


def source_property(ref, name):
    return 'Url' if name in ('URL','Url') and 'Url' in ref.control.properties and 'URL' not in ref.control.properties else 'URL' if name == 'Url' else name


def destination(value):
    if value is None or value.strip() == '': return None
    if any(ord(c)<32 or ord(c)==127 for c in value) or '\\' in value:
        raise FxError('Link URL contains invalid characters', 'Validation')
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() in ('mailto','tel'):
            if not parsed.path and not parsed.query: raise ValueError()
            return value.strip()
        if parsed.scheme.lower() not in ('http','https'):
            if parsed.scheme.lower() in ('javascript','vbscript','data','file','blob'):
                raise FxError('Link URL uses an unsafe protocol', 'Validation')
            raise FxError('Link URL protocol is unsupported; use HTTP, HTTPS, mailto or tel', 'Unsupported')
        if not parsed.hostname or any(c.isspace() for c in parsed.netloc): raise ValueError()
        parsed.hostname.encode('idna')
        parsed.port  # Check malformed and out-of-range ports without connecting.
    except (ValueError, UnicodeError):
        raise FxError('Link URL requires a valid web address', 'Validation') from None
    return value.strip()


def validate(ref, name, value, actual=None):
    if name == 'Type':
        if ref.runtime.environment.get('enum_mode') == 'strong' and not isinstance(value,EnumValue):
            raise FxError('ModernLink.Type requires LinkAppearance', 'Type')
        if consume(value,'LinkAppearance') not in ('Default','Subtle'):
            raise FxError('ModernLink.Type requires LinkAppearance.Default or Subtle', 'Type')
        return
    kind = TYPES.get(name)
    if kind == 'Text' and value is not None and not isinstance(value,str):
        raise FxError(f'ModernLink.{name} requires Text', 'Type')
    if kind == 'Number' and value is not None:
        if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(value):
            raise FxError(f'ModernLink.{name} requires a finite Number', 'Type')
        if name not in ('X','Y') and value < 0: raise FxError(f'ModernLink.{name} cannot be negative', 'Validation')
    if kind == 'Boolean' and value is not None and not isinstance(value,bool):
        raise FxError(f'ModernLink.{name} requires Boolean', 'Type')
    if kind == 'Color' and value is not None and (not isinstance(value,str) or actual and actual.kind not in ('Color','Blank','Unknown','Error')):
        raise FxError(f'ModernLink.{name} requires Color', 'Type')
    if name in ('URL','Url'): destination(value)
    allowed = {'Align':('Left','Center','Right','Justify'), 'VerticalAlign':('Top','Middle','Bottom'),
        'BorderStyle':('Solid','Dashed','Dotted','None'), 'FontWeight':('Normal','Bold','Semibold','Lighter')}
    if name in allowed and value is not None and value not in allowed[name]:
        raise FxError(f'ModernLink.{name} requires '+', '.join(allowed[name]), 'Type')


def auto_height(ref):
    base = ref.eval_raw('Height')
    validate(ref,'Height',base)
    size = ref.property('Size') or 0
    width = max(1,(ref.property('Width') or 0)-(ref.property('PaddingLeft') or 0)-(ref.property('PaddingRight') or 0))
    content = ref.property('Text') or ''
    chars = max(1,int(width/max(1,size*.55)))
    lines = sum(max(1,math.ceil(len(line)/chars)) for line in content.split('\n')) if content and ref.property('Wrap') else int(bool(content))
    return max(base or 0,math.ceil(lines*size*1.45+(ref.property('PaddingTop') or 0)+(ref.property('PaddingBottom') or 0)))


def render(ref,node):
    node['selectable'] = False
    node['link_url'] = None
    node['tab_stop'] = False
    if 'URL' in node['props']:
        node['link_url'] = destination(node['props']['URL'])
        node['tab_stop'] = bool(node['link_url']) and node['props'].get('DisplayMode') == 'Edit'
    if 'Type' in node['props']: node['props']['Type'] = consume(ref.property('Type'),'LinkAppearance')

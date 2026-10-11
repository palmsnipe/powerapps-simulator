"""Documented Canvas color names and color decoding, with no runtime network."""
from functools import lru_cache
import json, math, re
from pathlib import Path
from .syntax import FxError

@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent/'static/colors.json').read_text(encoding='utf-8'))['colors']

@lru_cache(maxsize=1)
def names():return {name.casefold():value for name,value in catalog().items()}

def color_value(value):
    if not isinstance(value,str):raise FxError('ColorValue requires Text','Type')
    if re.fullmatch(r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?',value):return value.lower()
    result=names().get(value.casefold())
    if result is None:raise FxError(f'Invalid color name or format {value}','InvalidArgument')
    return result

def components(value):
    if not isinstance(value,str):raise FxError('Color requires a color value','Type')
    match=re.fullmatch(r'rgba\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)',value)
    if match:
        result=tuple(map(float,match.groups()))
        if all(math.isfinite(v) for v in result) and all(0<=v<=255 for v in result[:3]) and 0<=result[3]<=1:return result
        raise FxError('RGBA components are out of range','InvalidArgument')
    value=color_value(value)
    if value.startswith('rgba('):return components(value)
    return (*[int(value[i:i+2],16) for i in (1,3,5)],int(value[7:9],16)/255 if len(value)==9 else 1)

def fade(value,amount):
    r,g,b,alpha=components(value)
    amount=float(amount)  # Color channels are presentation values in either host.
    if not math.isfinite(float(amount)) or not -1<=amount<=1:raise FxError('ColorFade amount must be between -1 and 1','InvalidArgument')
    rgb=[v+(255-v)*amount if amount>=0 else v*(1+amount) for v in (r,g,b)]
    return f'rgba({rgb[0]:g},{rgb[1]:g},{rgb[2]:g},{alpha:g})'

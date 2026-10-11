"""Scalar HTML/text functions following pinned Power Fx LibraryText.cs.

PlainText tag replacements are adapted from Microsoft's MIT-licensed
LibraryText.cs, revision df4ceba5e08220db670c25afead342ce699c50b5.
The notice/license is included in conformance_cases/MICROSOFT-LICENSE.txt.
PlainText follows the upstream replacement order; it is not a renderer or
sanitizer. CRLF is the Canvas/Windows contract on both simulator platforms.
"""
import re
from html.entities import name2codepoint
from urllib.parse import quote
from .power_text import units, from_units

FUNCTIONS = frozenset(('EncodeHTML', 'EncodeUrl', 'PlainText'))
_WS = '\t\n\v\f\r\u0085\u0020\u00a0\u1680\u2028\u2029\u202f\u205f\u3000' + ''.join(chr(n) for n in range(0x2000,0x200b))
_ENTITIES = {**name2codepoint, 'apos': 39}


def decode_entities(source):
    def replace(match):
        entity = match[1]
        try:
            code = int(entity[2:], 16) if entity.startswith(('#x', '#X')) else int(entity[1:]) if entity.startswith('#') else _ENTITIES[entity]
            return chr(code) if 0 <= code <= 0x10ffff and not 0xd800 <= code <= 0xdfff else match[0]
        except (ValueError, KeyError):
            return match[0]
    return re.sub(r'&(#(?:[xX][0-9a-fA-F]+|[0-9]+)|[A-Za-z][A-Za-z0-9]*);', replace, source)


def encode_html(source):
    # Normalize valid UTF-16 pairs while replacing unpaired surrogates, as
    # HttpUtility.HtmlEncode does; ordinary non-Latin-1 BMP text is retained.
    source = from_units(units(source)).encode('utf-16-le', errors='surrogatepass').decode('utf-16-le', errors='replace')
    escapes = {'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}
    return ''.join(escapes.get(c, f'&#{ord(c)};' if 160 <= ord(c) <= 255 or ord(c) > 65535 else c) for c in source)


def plain_text(source):
    value = source.strip(_WS)
    for tag in ('header', 'script', 'style'):
        value = re.sub(r'<\s*(' + tag + r')[\s\S]*?>[\s\S]*?<\s*/\s*(' + tag + r')\s*>', '', value, flags=re.I)
    value = re.sub(r'<!--[\s\S]*?--\s*>', '', value)
    value = re.sub(r'<\s*(td)[\s\S]*?/{0,1}>', '', value, flags=re.I)
    value = re.sub(r'<\s*(br|li)((\s+[\s\S]*?)|(\s*/\s*))?>', '\r\n', value, flags=re.I)
    value = re.sub(r'<\s*(div|p|tr)((\s+[\s\S]*?)|(\s*/\s*))?>', '\r\n\r\n', value, flags=re.I)
    value = re.sub(r'<[^>]*>', '', value)
    return decode_entities(value).strip(_WS)


def evaluate(name, source):
    return encode_html(source) if name == 'EncodeHTML' else plain_text(source) if name == 'PlainText' else quote(source, safe='-._~', errors='replace')

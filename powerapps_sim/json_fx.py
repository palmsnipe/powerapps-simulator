"""JSON values retain dynamic identity and exact numeric lexemes."""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import math
import re
import base64
import mimetypes
from pathlib import Path

from .numeric import decimal_value, float_value, decimal_text
from .syntax import FxError
from .temporal import Temporal
from .locale_fx import EPOCH, parse_number


@dataclass(frozen=True)
class JsonNumber:
    lexeme: str


@dataclass(frozen=True)
class Dynamic:
    value: object


def media_kind(uri):
    """Classify local asset metadata without reading files or fetching URLs."""
    mime = uri[5:].split(';', 1)[0].split(',', 1)[0] if uri.startswith('data:') else mimetypes.guess_type(uri.split('?', 1)[0])[0]
    return 'Media' if mime and mime.startswith(('audio/', 'video/')) else 'Image'


class Media(str):
    """Media identity survives formulas; ordinary Text URLs stay Text."""
    def __new__(cls, uri, asset_root=None, *, kind=None):
        value = super().__new__(cls,uri)
        value.asset_root = asset_root
        value.media_kind = kind or media_kind(uri)
        return value


def dynamic(value):
    return None if value is None else Dynamic(value)


def parse_json(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise FxError('ParseJSON requires Text', 'Type')
    def invalid_constant(token):
        raise ValueError(f'Invalid JSON number {token}')
    try:
        return dynamic(json.loads(value, parse_int=JsonNumber, parse_float=JsonNumber, parse_constant=invalid_constant))
    except (ValueError, RecursionError) as error:
        raise FxError(f'Invalid JSON: {error}', 'InvalidJSON') from None


def array(value):
    if not isinstance(value, Dynamic) or not isinstance(value.value, list):
        raise FxError('Expected a Dynamic array', 'InvalidArgument')
    return [dynamic(item) for item in value.value]


def field(value, name):
    if value is None:
        return None
    if not isinstance(value, Dynamic) or not isinstance(value.value, dict):
        raise FxError('Expected a Dynamic object', 'InvalidArgument')
    return dynamic(value.value.get(name))


def iso_temporal(value, kind):
    if not isinstance(value, str):
        raise FxError(f'Expected an ISO {kind} string', 'InvalidArgument')
    try:
        if kind == 'Time':
            if not re.fullmatch(r'\d{2}:\d{2}:\d{2}(?:\.\d{1,7})?', value):
                raise ValueError()
            parsed = datetime.fromisoformat('1970-01-01T' + value)
            return Temporal('Time', EPOCH.replace(hour=parsed.hour, minute=parsed.minute, second=parsed.second, microsecond=parsed.microsecond))
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d{1,7})?(?:Z|[+-]\d{2}:\d{2})?)?', value):
            raise ValueError()
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        parsed = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        if kind == 'Date':
            parsed = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
        return Temporal(kind, parsed)
    except ValueError:
        raise FxError(f'Invalid ISO {kind} value', 'InvalidArgument') from None


def convert_scalar(value, kind, fx, language=None):
    """Explicit Dynamic constructors permit scalar conversions, never objects."""
    raw = value.value if isinstance(value, Dynamic) else value
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        raise FxError(f'Cannot convert a Dynamic object/array to {kind}', 'InvalidArgument')
    if kind == 'Text':
        if isinstance(raw, JsonNumber):
            return raw.lexeme
        return 'true' if raw is True else 'false' if raw is False else str(raw)
    if kind in ('Number', 'Decimal', 'Float'):
        mode = 'decimal' if kind == 'Decimal' else 'float' if kind == 'Float' else fx.number_mode
        if isinstance(raw, JsonNumber):
            return (decimal_value if mode == 'decimal' else float_value)(raw.lexeme)
        return parse_number(raw, language or fx.host.environment['language'], fx.numeric_mode, mode)
    if kind == 'Boolean':
        if isinstance(raw, JsonNumber):
            return decimal_value(raw.lexeme) != 0
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.casefold() in ('true', 'false'):
            return raw.casefold() == 'true'
        raise FxError('Invalid Dynamic Boolean', 'InvalidArgument')
    if kind in ('Date', 'DateTime', 'Time'):
        return iso_temporal(raw, kind)
    if not isinstance(raw, str):
        raise FxError(f'Expected a Dynamic string for {kind}', 'InvalidArgument')
    return raw


def validate_json_type(typ):
    if typ.kind == 'Record':
        if typ.open:
            raise FxError('JSON requires a declared record shape', 'Type')
        for child in typ.fields.values():
            validate_json_type(child)
    elif typ.kind == 'Table':
        validate_json_type(typ.row)
    elif typ.kind not in ('Text', 'Number', 'Decimal', 'Boolean', 'Date', 'DateTime', 'Time', 'Dynamic'):
        raise FxError(f'Unsupported JSON type {typ.describe()}', 'Type')


def typed(value, typ, fx, path='$'):
    """Typed JSON projects fields and checks JSON kinds without loose coercion."""
    if value is None:
        return None
    if not isinstance(value, Dynamic):
        raise FxError('AsType/IsType require a Dynamic value; Dataverse record references are unsupported', 'Unsupported')
    raw = value.value
    if typ.kind == 'Dynamic':
        return value
    if typ.kind == 'Record' and isinstance(raw, dict):
        return {name: typed(dynamic(raw.get(name)), child, fx, path+'.'+name) for name, child in typ.fields.items()}
    if typ.kind == 'Table' and isinstance(raw, list):
        row = typ.row
        scalar_column = list(row.fields) == ['Value']
        return [typed(dynamic(item if isinstance(item, dict) or not scalar_column else {'Value':item}), row, fx, f'{path}[{index}]') for index,item in enumerate(raw)]
    if typ.kind in ('Number', 'Decimal') and isinstance(raw, JsonNumber):
        return (decimal_value if typ.kind == 'Decimal' else float_value)(raw.lexeme)
    if typ.kind == 'Text' and isinstance(raw, str) or typ.kind == 'Boolean' and isinstance(raw, bool):
        return raw
    if typ.kind in ('Date', 'DateTime', 'Time') and isinstance(raw, str):
        return iso_temporal(raw, typ.kind)
    raise FxError(f'JSON value at {path} does not match {typ.describe()}', 'InvalidArgument')


OMIT = object()


def json_text(value, flags='', type_hint=None):
    """Encode supported Power Fx values, preserving Decimal precision."""
    if not isinstance(flags, str) or set(flags) - set('c4BGI_') or 'B' in flags and 'G' in flags:
        raise FxError('Invalid or conflicting JSONFormat flags', 'InvalidArgument')
    def prepare(v, typ=None):
        from .enum_fx import EnumValue
        if isinstance(v,EnumValue):
            return prepare(v.backing)
        from .icons import IconValue
        if isinstance(v,IconValue):
            if 'I' in flags:return OMIT
            raise FxError('JSON encoding of Icon enums has not been verified; convert explicitly with Text','Unsupported')
        if isinstance(v, FxError):
            raise v
        if isinstance(v, Dynamic):
            return prepare(v.value)
        if isinstance(v, Media):
            if 'G' in flags:
                return OMIT
            if v.startswith(('https:','http:')):
                return str(v)
            if 'B' not in flags:
                raise FxError('JSON media requires IncludeBinaryData or IgnoreBinaryData', 'InvalidArgument')
            if v.startswith('data:'):
                return str(v)
            if v.startswith('/api/asset/Assets/') and v.asset_root:
                root = Path(v.asset_root).resolve()
                target = (root / v.removeprefix('/api/asset/Assets/')).resolve()
                if not target.is_relative_to(root) or not target.is_file():
                    raise FxError('JSON media asset is unavailable', 'InvalidArgument')
                mime = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
                return 'data:'+mime+';base64,'+base64.b64encode(target.read_bytes()).decode('ascii')
            raise FxError('JSON encoding of this media reference is unsupported', 'Unsupported')
        if isinstance(v, Temporal):
            if v.kind == 'Date':
                return v.value.strftime('%Y-%m-%d')
            if v.kind == 'Time':
                return v.value.strftime('%H:%M:%S.') + f'{v.value.microsecond // 1000:03d}'
            return v.value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
        if v is None or isinstance(v, (str, bool, int, Decimal, JsonNumber)):
            if isinstance(v,str) and typ and typ.kind == 'Color':
                if re.fullmatch(r'#[0-9a-fA-F]{6}',v):
                    return v.lower()+'ff'
                if re.fullmatch(r'#[0-9a-fA-F]{8}',v):
                    return v.lower()
                match = re.fullmatch(r'rgba\((\d+),(\d+),(\d+),([\d.]+)\)',v.replace(' ',''))
                if match:
                    return '#'+''.join(f'{int(match[i]):02x}' for i in (1,2,3))+f'{round(float(match[4])*255):02x}'
            return v
        if isinstance(v, float):
            if not math.isfinite(v):
                raise FxError('JSON cannot encode a non-finite number', 'InvalidArgument')
            return v
        if isinstance(v, dict):
            result = {}
            mapping = getattr(v, 'logical_names', {})
            fields = typ.fields if typ and typ.kind == 'Record' else {}
            for k in set(v) | set(fields):
                encoded = prepare(v.get(k), fields.get(k))
                if encoded is not OMIT:
                    result[mapping.get(k,k)] = encoded
            return dict(sorted(result.items(),key=lambda pair:pair[0].encode('utf-16-be',errors='surrogatepass')))
        if isinstance(v, list):
            row_type = typ.row if typ and typ.kind == 'Table' else None
            flat = '_' in flags and ((row_type and list(row_type.fields) == ['Value']) or v and all(isinstance(row,dict) and list(row)==['Value'] for row in v))
            rows = [prepare(row.get('Value') if flat and isinstance(row,dict) else row, row_type.fields.get('Value') if flat and row_type else row_type) for row in v]
            return [row for row in rows if row is not OMIT]
        if 'I' in flags:
            return OMIT
        raise FxError('JSON encountered an unsupported value', 'Unsupported')
    def encode(v, level=0):
        if isinstance(v, JsonNumber):
            return v.lexeme
        if isinstance(v, Decimal):
            if not v.is_finite():
                raise FxError('JSON cannot encode a non-finite Decimal', 'InvalidArgument')
            return decimal_text(v)
        if isinstance(v, (dict,list)):
            entries = [json.dumps(k,ensure_ascii=False)+(': ' if '4' in flags else ':')+encode(cell,level+1) for k,cell in v.items()] if isinstance(v,dict) else [encode(cell,level+1) for cell in v]
            start,end = ('{','}') if isinstance(v,dict) else ('[',']')
            if '4' in flags and entries:
                return start+'\n'+'    '*(level+1)+(',\n'+'    '*(level+1)).join(entries)+'\n'+'    '*level+end
            return start+','.join(entries)+end
        if isinstance(v,float) and v.is_integer():
            return str(int(v))
        return json.dumps(v,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    prepared = prepare(value,type_hint)
    return encode(None if prepared is OMIT else prepared).encode('utf-8', errors='backslashreplace').decode('utf-8')

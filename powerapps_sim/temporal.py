"""Immutable Power Fx temporal values and their wire/storage boundaries."""
from __future__ import annotations

from decimal import Decimal
from .numeric import decimal_value, decimal_text, float_value
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .syntax import FxError


EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)
UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
TEMPORAL_KINDS = {'Date', 'DateTime', 'Time'}
NUMERIC_MODES = {'canvas-milliseconds', 'powerfx-days'}
DAY_MS = 86400000


@dataclass(frozen=True)
class Temporal:
    kind: str
    value: datetime

    def __post_init__(self):
        if self.kind not in TEMPORAL_KINDS:
            raise ValueError(f'Invalid temporal kind {self.kind}')
        instant = self.value.replace(tzinfo=self.value.tzinfo or timezone.utc)
        object.__setattr__(self, 'value', instant)

    def isoformat(self):
        if self.kind == 'Date':
            return self.value.date().isoformat()
        if self.kind == 'Time':
            return self.value.time().isoformat()
        return self.value.isoformat()

    def days(self):
        return (self.value - EPOCH).total_seconds() / 86400

    def numeric(self, mode):
        if mode == 'powerfx-days':
            return self.days()
        if mode != 'canvas-milliseconds':
            raise FxError(f'Unsupported date numeric mode {mode}', 'Unsupported')
        base = EPOCH if self.kind == 'Time' else UNIX_EPOCH
        return (self.value - base).total_seconds() * 1000

    @classmethod
    def from_number(cls, number, kind='DateTime', mode='powerfx-days'):
        if mode not in NUMERIC_MODES:
            raise FxError(f'Unsupported date numeric mode {mode}', 'Unsupported')
        try:
            base = EPOCH if mode == 'powerfx-days' or kind == 'Time' else UNIX_EPOCH
            delta = timedelta(days=float(number)) if mode == 'powerfx-days' else timedelta(milliseconds=float(number))
            return cls(kind, base + delta)
        except (OverflowError, ValueError):
            raise FxError('Date/time is outside the supported calendar range', 'InvalidArgument') from None


def storage_value(value, schema=None):
    """Serialize temporal cells explicitly; no arbitrary object stringification."""
    schema = schema or {}
    if isinstance(value, FxError):
        raise value
    if isinstance(value, float) and schema.get('type') == 'integer':
        if not value.is_integer():
            raise FxError('Expected an integral list value', 'Validation')
        return int(value)
    if isinstance(value, Decimal):
        if schema.get('type') == 'integer':
            if not value.is_finite() or value != value.to_integral_value():
                raise FxError('Expected an integral list value', 'Validation')
            return int(value)
        if schema.get('type') not in (None, 'number'):
            raise FxError('Decimal list values require a numeric column; use Text for text columns', 'Validation')
        return {'$decimal': decimal_text(decimal_value(value))} if schema.get('format') == 'decimal' or not schema else float_value(value)
    if isinstance(value, Temporal):
        expected = {'date': 'Date', 'date-time': 'DateTime', 'time': 'Time'}.get(schema.get('format'))
        if expected:
            if value.kind == 'Time' and expected != 'Time' or expected == 'Time' and value.kind != 'Time':
                raise FxError(f'Expected {expected} list value', 'Validation')
            if expected == 'Date':
                return value.value.date().isoformat()
            if expected == 'DateTime':
                return value.value.isoformat()
        elif schema.get('type') and schema.get('type') != 'string':
            raise FxError(f'Cannot store {value.kind} in a {schema["type"]} column', 'Validation')
        return value.isoformat()
    if isinstance(value, dict):
        return {k: storage_value(v, schema.get('properties', {}).get(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [storage_value(v, schema.get('items')) for v in value]
    return value


def schema_value(value, schema):
    """Hydrate connector date columns, retaining malformed cells as errors."""
    if value is None or isinstance(value, (Temporal, FxError)):
        return value
    if isinstance(value, dict) and set(value) == {'$decimal'} and schema.get('type') == 'number' and schema.get('format') == 'decimal':
        try:
            return decimal_value(value['$decimal'])
        except FxError as error:
            return error
    if isinstance(value, dict):
        return {k: schema_value(v, schema.get('properties', {}).get(k, {})) for k, v in value.items()}
    if isinstance(value, list):
        return [schema_value(v, schema.get('items', {})) for v in value]
    if schema.get('type') == 'number' and schema.get('format') == 'decimal':
        try:
            return decimal_value(value)
        except FxError as error:
            return error
    kind = {'date': 'Date', 'date-time': 'DateTime', 'time': 'Time'}.get(schema.get('format'))
    if kind:
        try:
            raw = str(value).replace('Z', '+00:00')
            parsed = datetime.fromisoformat('1899-12-30T' + raw if kind == 'Time' else raw)
            return Temporal(kind, parsed)
        except (ValueError, TypeError):
            return FxError(f'Invalid {kind} connector value {value!r}', 'Validation')
    return value

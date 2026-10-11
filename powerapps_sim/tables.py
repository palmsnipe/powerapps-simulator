"""Shared static column contracts for record/table shaping functions."""
from .syntax import FxError

SHAPING_FUNCTIONS = {'AddColumns', 'ShowColumns', 'DropColumns', 'RenameColumns'}
QUERY_FUNCTIONS = {'Search', 'GroupBy', 'Ungroup'}


class SourceRecord(dict):
    """List display names retain their logical names as value metadata."""
    def __init__(self, fields, logical_names, source_name=None, defaults_for=None):
        super().__init__(fields)
        self.logical_names = logical_names
        self.source_name, self.defaults_for = source_name, defaults_for

    def copy(self):
        return SourceRecord(self,self.logical_names,self.source_name,self.defaults_for)


class OrderedRecord(dict):
    """GroupBy lineage is value metadata, never a Power Fx record field."""
    def __init__(self, fields, order, logical_names=None):
        super().__init__(fields)
        self.order = order
        self.logical_names = logical_names if logical_names is not None else getattr(fields,'logical_names',{})
        self.source_name = getattr(fields,'source_name',None)
        self.defaults_for = getattr(fields,'defaults_for',None)

    def copy(self):
        return OrderedRecord(self, self.order, self.logical_names)


def derived_record(source, fields):
    if hasattr(source, 'gallery_derivative'):
        return source.gallery_derivative(fields)
    if isinstance(source, SourceRecord):
        return SourceRecord(fields, source.logical_names, source.source_name, source.defaults_for)
    if isinstance(source, OrderedRecord):
        result = OrderedRecord(fields, source.order, source.logical_names)
        result.source_name, result.defaults_for = source.source_name, source.defaults_for
        return result
    return fields


def query_columns(function, fields, nodes, open_schema=False, aliases=None):
    aliases = aliases or {}
    columns = [column_name(node) for node in nodes]
    existing = columns[:-1] if function == 'GroupBy' else columns
    resolved = []
    for col, node in zip(existing, nodes):
        physical = col if col in fields else aliases.get(col, col)
        if physical not in fields and not open_schema:
            raise FxError(f'Unknown column {col}', 'Name', node.start, node.end)
        resolved.append(physical)
    if function == 'GroupBy':
        nested = columns[-1]
        if len(set(resolved)) != len(resolved):
            raise FxError('GroupBy requires distinct column names', 'Validation', nodes[-1].start, nodes[-1].end)
        if nested in fields or aliases.get(nested) in fields or nested in resolved:
            raise FxError(f'Column {nested} already exists', 'Validation', nodes[-1].start, nodes[-1].end)
        resolved.append(nested)
    return resolved


def column_name(node):
    # Identifier syntax and legacy literal strings are both retained on import.
    if node.kind not in ('name', 'literal') or not isinstance(node.value, str) or not node.value.strip():
        raise FxError('Expected a column identifier or nonempty literal name', 'Validation', node.start, node.end)
    return node.value


def shape_columns(function, fields, nodes, open_schema=False, aliases=None):
    """Return (old,new) field operations, validating before row evaluation."""
    aliases = {logical: physical for logical, physical in (aliases or {}).items() if physical in fields}
    logical_names = {physical: logical for logical, physical in aliases.items()}
    columns = [column_name(node) for node in nodes]
    available = set(fields)
    seen, added, operations = set(), set(), []
    if function == 'RenameColumns' and len(columns) % 2:
        raise FxError('RenameColumns expects old/new column pairs', 'Validation')
    for i in range(0, len(columns), 2 if function == 'RenameColumns' else 1):
        authored = columns[i]
        old = authored if function == 'AddColumns' or authored in available else aliases.get(authored, authored)
        new = columns[i + 1] if function == 'RenameColumns' else old
        node = nodes[i]
        if function == 'AddColumns':
            if old in available or aliases.get(old) in available or old in added:
                raise FxError(f'Column {old} already exists', 'Validation', node.start, node.end)
            added.add(old)
        else:
            if (old not in available and not open_schema) or (old in seen and function in ('DropColumns', 'RenameColumns')):
                raise FxError(f'Unknown column {authored}', 'Name', node.start, node.end)
            # Native RenameColumns compares its resolved logical old name with
            # the literal new name. Storage here uses display keys, so a logical
            # self-rename must keep that physical key and its metadata.
            if function == 'RenameColumns' and new == logical_names.get(old, old):
                new = old
            elif function == 'RenameColumns':
                if new in available or aliases.get(new) in available or new in added:
                    raise FxError(f'Column {new} already exists', 'Validation', nodes[i + 1].start, nodes[i + 1].end)
                added.add(new)
                seen.add(old)
            elif function == 'DropColumns':
                seen.add(old)
        operations.append((old, new))
    return operations


def shaped_record(source, fields, operations, function):
    """Copy transformed values without reviving removed source-name aliases."""
    result = derived_record(source, fields)
    removed = {old for old, new in operations if function == 'DropColumns' or function == 'RenameColumns' and old != new}
    if hasattr(result, 'logical_names'):
        result.logical_names = {physical: logical for physical, logical in getattr(source, 'logical_names', {}).items()
                                if physical in fields and physical not in removed}
    return result

"""Contracts shared by scalar functions and their single-column table overloads."""
from .syntax import FxError
from .power_math import INTEGER_FUNCTIONS,FLOAT_FUNCTIONS
from .power_text import TEXT_OPERATIONS

TEXT_OVERLOADS = {'Len', 'Lower', 'Upper', 'Proper', 'Trim', 'TrimEnds'} | (TEXT_OPERATIONS - {'Split'})
ROUND_OVERLOADS = {'Round', 'RoundDown', 'RoundUp'}
NUMERIC_OVERLOADS = ROUND_OVERLOADS | {'Abs'} | INTEGER_FUNCTIONS | FLOAT_FUNCTIONS
CALENDAR_OVERLOADS = {'WeekNum', 'ISOWeekNum'}
SINGLE_COLUMN_OVERLOADS = TEXT_OVERLOADS | NUMERIC_OVERLOADS | CALENDAR_OVERLOADS
ROUND_TABLE_MODES = {'canvas-zero', 'powerfx-errors'}


def empty_table_literal(node):
    from .syntax import call_name
    if node.kind == 'alias':
        return empty_table_literal(node.children[0])
    return ((node.kind == 'table' and not node.children) or
            (node.kind == 'call' and call_name(node.children[0]) == 'Table' and len(node.children) == 1))


def single_column(fields, open_schema=False, start=0, end=0):
    if len(fields) == 1:
        return next(iter(fields))
    if not fields and open_schema:
        return None
    raise FxError('Expected a single-column table; use ShowColumns to select one field', 'Type', start, end)

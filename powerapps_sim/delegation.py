"""Local row limits for a subset of nondelegable SharePoint list reads."""

from .syntax import call_name, walk

DEFAULT_DATA_ROW_LIMIT = 500
MAX_DATA_ROW_LIMIT = 10_000
CLIENT_PREDICATE_FUNCTIONS = frozenset((
    'Lower', 'Upper', 'Len', 'Left', 'Right', 'Mid', 'Trim', 'Text', 'Value', 'IsBlank',
))


def validate_data_row_limit(value):
    if type(value) is not int or not 1 <= value <= MAX_DATA_ROW_LIMIT:
        raise ValueError(f'Data row limit must be a whole number from 1 to {MAX_DATA_ROW_LIMIT:,}')


def data_row_limit(runtime):
    return runtime.reactive.leaf(
        ('environment', 'data_row_limit'),
        lambda: runtime.environment.get('data_row_limit', DEFAULT_DATA_ROW_LIMIT),
    )


def local_predicate(source, source_expression, predicates):
    """Recognize column-dependent client functions without capping plain filters."""
    from .store import DataSource

    if not isinstance(source, DataSource):
        return False
    schema = source.store.definitions[source.name]
    columns = set(schema['fields']) | set(schema['mapping'].values()) | {'ThisRecord'}
    if source_expression.kind == 'alias':
        columns = {source_expression.children[1].value}
    for predicate in predicates:
        for node in walk(predicate):
            if node.kind == 'call' and call_name(node.children[0]) in CLIENT_PREDICATE_FUNCTIONS:
                if any(part.kind == 'name' and part.value in columns
                       for argument in node.children[1:] for part in walk(argument)):
                    return True
    return False

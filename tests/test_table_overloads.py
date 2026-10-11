from decimal import Decimal
import pytest

from powerapps_sim.binding import BindScope
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError


@pytest.mark.parametrize('expression, expected', [
    ('AddColumns({a: 3} As r, b, r.a * 2)', {'a':3, 'b':6}),
    ('ShowColumns({a: 1, b: 2}, b)', {'b':2}),
    ('DropColumns({a: 1, b: 2}, a)', {'b':2}),
    ('RenameColumns({a: 1, b: 2}, b, \'Display name\')', {'a':1, 'Display name':2}),
    ('RenameColumns({a: 1, b: 2}, a, a)', {'a':1, 'b':2}),
    ('RenameColumns(DropColumns([{a:1,b:2},{a:3,b:4}], a), b, a)', [{'a':2},{'a':4}]),
    ('ShowColumns(AddColumns({a:3}, b, a * 2), b)', {'b':6}),
    ('AddColumns(If(false, [{a: 1}]), b, a * 2)', None),
    ('RenameColumns(If(false, {a: 1}), a, b)', None),
    ('ShowColumns(If(false, {a: 1}), a)', None),
    ('DropColumns(If(false, {a: 1}), a)', None),
    ('FirstN([1,2,3], Blank())', []),
    ('LastN([1,2,3], Blank())', []),
    ('FirstN(Blank(), 2)', None),
    ('Index(Blank(), 2)', None),
    ('Index([1,2,3], "2.8")', {'Value':2}),
    ('LastN([1,2,3], true)', [{'Value':3}]),
    ('Sort([3,Blank(),1], Value)', [{'Value':1},{'Value':3},{'Value':None}]),
    ('Sort([3,Blank(),1], Value, SortOrder.Descending)', [{'Value':3},{'Value':1},{'Value':None}]),
    ('Sort(["B","a","A","b"], Value)', [{'Value':'a'},{'Value':'A'},{'Value':'b'},{'Value':'B'}]),
    ('SortByColumns(["Draft","Other",Blank(),"Review","Draft"], "Value", ["Review","Draft",Blank()])', [{'Value':'Review'},{'Value':'Draft'},{'Value':'Draft'},{'Value':'Other'},{'Value':None}]),
    ('SortByColumns([3,1,2], "Value", [])', [{'Value':3},{'Value':1},{'Value':2}]),
    ('With({column: "Value"}, SortByColumns([3,1,2], column))', [{'Value':1},{'Value':2},{'Value':3}]),
    ('SortByColumns([3,1,2], Left("Value123", 5), [2,3,1])', [{'Value':2},{'Value':3},{'Value':1}]),
    ('SortByColumns(If(false, [1,2]), "Value", [2,1])', None),
])
def test_record_shaping_blank_counts_and_ordered_sort(runtime, expression, expected):
    assert runtime.fx.evaluate(expression) == expected


@pytest.mark.parametrize('expression, kind', [
    ('AddColumns({}, a, 1, a, 2)', 'Validation'),
    ('RenameColumns({a:1,b:2}, a, b)', 'Validation'),
    ('RenameColumns({a:1,b:2}, a, c, b, c)', 'Validation'),
    ('DropColumns({a:1}, a, a)', 'Name'),
    ('ShowColumns(FirstN([{a:1}], 0), missing)', 'Name'),
    ('AddColumns([1], "", 2)', 'Validation'),
    ('AddColumns({}, 3, 2)', 'Validation'),
    ('RenameColumns({a:1}, a, b, b)', 'Validation'),
    ('SortByColumns([1,2], "Value", [1,1])', 'InvalidArgument'),
    ('SortByColumns([1,2], "Value", [1,1/0])', 'Div0'),
    ('SortByColumns([1,2], Left("missing", 7))', 'InvalidFunctionUsage'),
    ('Index([1,2], 0)', 'InvalidArgument'),
    ('FirstN([1,2], "not a number")', 'InvalidArgument'),
    ('Sort([1,2], {N: Value})', 'Validation'),
])
def test_table_argument_errors_have_source_spans(runtime, expression, kind):
    with pytest.raises(FxError) as error:
        runtime.fx.evaluate(expression)
    assert error.value.kind == kind
    assert error.value.end > error.value.start


def test_shaping_and_sort_preserve_unobserved_errors_and_source(runtime):
    ctx = Context(runtime, behavior=True)
    runtime.fx.evaluate('Set(original, {Bad:1/0, Good:2})', ctx)
    assert runtime.fx.evaluate('DropColumns(original, Bad)') == {'Good':2}
    assert runtime.fx.evaluate('RenameColumns(original, Bad, Broken).Good') == 2
    assert runtime.fx.evaluate('With({original: {Bad:1/0, Good:2}}, IfError(RenameColumns(original, Bad, Broken).Broken, FirstError.Kind))') == 13
    assert runtime.fx.evaluate('original.Good') == 2
    assert isinstance(runtime.globals['original']['Bad'], FxError)
    assert runtime.fx.evaluate('IfError(CountRows(Sort([0,1,0], 1/Value)), CountRows(AllErrors))') == 2
    result = runtime.fx.evaluate('SortByColumns([{N:2,Bad:1/0},{N:1,Bad:1/0}], "N", [1,2])')
    assert [row['N'] for row in result] == [1,2]
    assert all(isinstance(row['Bad'], FxError) for row in result)


def test_shaping_types_closed_empty_tables_and_original_scopes(runtime):
    expressions = [
        ('ShowColumns({a:1,b:"x"}, b)', 'Record', {'b':'Text'}),
        ('RenameColumns(FirstN([{a:1,b:"x"}], 0), a, N)', 'Table', {'N':'Number','b':'Text'}),
        ('DropColumns([{a:1,b:"x"}], a)', 'Table', {'b':'Text'}),
    ]
    for expression, kind, fields in expressions:
        runtime.binder.errors.clear()
        typ = runtime.binder.bind(runtime.fx.parse(expression), BindScope())
        assert not runtime.binder.errors
        assert typ.kind == kind
        row = typ.row if kind == 'Table' else typ
        assert {key:t.kind for key,t in row.fields.items()} == fields
        assert not row.open
    for expression in ['AddColumns({a:1}, b, 2, c, b + 1)', 'SortByColumns([1], "Value", [{A:1,B:2}])', 'Sort([1], {N: Value})']:
        runtime.binder.errors.clear()
        runtime.binder.bind(runtime.fx.parse(expression), BindScope())
        assert runtime.binder.errors


def test_runtime_columns_validate_incomplete_record_and_table_schemas(runtime):
    ctx = Context(runtime, behavior=True)
    runtime.fx.evaluate('Set(dynamicRecord, {a:1,b:2}); Set(dynamicRows, [{a:2,b:4},{a:1,b:3}])', ctx)
    for expression, kind in [
        ('AddColumns(dynamicRecord, a, 99)', 'Validation'),
        ('RenameColumns(dynamicRecord, a, b)', 'Validation'),
        ('DropColumns(dynamicRecord, missing)', 'Name'),
        ('AddColumns(dynamicRows, a, 99)', 'Validation'),
        ('RenameColumns(dynamicRows, a, b)', 'Validation'),
        ('SortByColumns(dynamicRows, "missing")', 'InvalidFunctionUsage'),
    ]:
        with pytest.raises(FxError) as error:
            runtime.fx.evaluate(expression)
        assert error.value.kind == kind
    assert runtime.fx.evaluate('SortByColumns(dynamicRows, "a")') == [{'a':1,'b':3},{'a':2,'b':4}]
    assert runtime.globals['dynamicRecord'] == {'a':1,'b':2}
    assert runtime.globals['dynamicRows'] == [{'a':2,'b':4},{'a':1,'b':3}]


def test_sort_preserves_decimal_precision_and_temporal_values(runtime):
    runtime.environment['number_mode'] = 'decimal'
    result = runtime.fx.evaluate('SortByColumns([9007199254740993.25,9007199254740993.1], "Value")')
    assert [row['Value'] for row in result] == [Decimal('9007199254740993.1'), Decimal('9007199254740993.25')]
    assert runtime.fx.evaluate('First(Sort([Date(2026,3,1), Date(2026,1,1)], Value)).Value').isoformat() == '2026-01-01'


@pytest.fixture
def queues(tmp_path):
    from powerapps_sim.fixtures import tables_project
    from powerapps_sim.runtime import Runtime
    runtime = Runtime(tables_project(tmp_path / 'queues'))
    runtime.restart(); runtime.state()
    yield runtime
    runtime.close()


def test_component_table_input_record_function_callback_and_reactive_sqlite(queues):
    assert not queues.diagnostics
    assert [row['ID'] for row in queues.fx.evaluate('LeftQueue.View')] == [2,1,3,4]
    assert [row['ID'] for row in queues.fx.evaluate('RightQueue.View')] == [1,2,3,4]
    assert queues.fx.evaluate('LeftQueue.Prepare(First(Drafts))')['Preview amount'] == 200
    left = queues.global_refs['LeftQueue']
    gallery = next(child for child in left.children if child.name == 'QueueGallery')
    button = next(ref for ref in queues.refs.values() if ref.name == 'ProjectButton' and ref.parent is gallery and ref.item['ID'] == 2)
    original_path = button.path
    queues.event(button.path, 'OnSelect'); queues.state()
    assert queues.globals['pickedProject']['Project title'] == 'Fictional wetland study'
    assert queues.globals['pickedProject']['Preview amount'] == 400
    assert 'rightPicked' not in queues.globals
    queues.event('Queues/ChangeOrder', 'OnSelect'); queues.state()
    assert [row['ID'] for row in queues.fx.evaluate('LeftQueue.View')] == [1,2,3,4]
    assert gallery.property('Selected')['ID'] == 2
    assert original_path in queues.refs
    queues.event('Queues/RaiseAmount', 'OnSelect'); queues.state()
    assert queues.store.rows('Drafts')[1]['Amount'] == 210
    assert queues.globals['pickedProject']['Preview amount'] == 420
    assert gallery.property('Selected')['Preview amount'] == 420
    assert queues.fx.evaluate('LookUp(RightQueue.View, ID = 2).\'Preview amount\'') == 420
    assert not queues.diagnostics


def test_component_filter_isolated_and_exports_source_without_schema(queues):
    from io import BytesIO
    from zipfile import ZipFile
    from powerapps_sim.fixtures import tables_project
    queues.event('Queues/SearchInput', 'OnChange', 'river'); queues.state()
    assert [row['ID'] for row in queues.fx.evaluate('LeftQueue.View')] == [1]
    assert [row['ID'] for row in queues.fx.evaluate('RightQueue.View')] == [1,2,3,4]
    assert not queues.diagnostics
    source = queues.project.documents['Src/tables.pa.yaml']
    assert 'DropColumns' in source and 'RenameColumns' in source
    assert 'records' not in source and 'sqlite' not in source.lower()
    with ZipFile(BytesIO(queues.project.export())) as archive:
        assert archive.read('Src/tables.pa.yaml').decode('utf-8') == source
        assert all(name.startswith(('Src/', 'assets/')) for name in archive.namelist())
    with pytest.raises(ValueError, match='existing projects'):
        tables_project(queues.project.root)

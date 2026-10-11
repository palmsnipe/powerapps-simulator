import pytest

from powerapps_sim.binding import value_type
from powerapps_sim.fx import Context
from powerapps_sim.runtime import serial
from powerapps_sim.syntax import FxError


@pytest.mark.parametrize('expression, expected', [
    ('{bad: 1/0, good: "usable"}.good', 'usable'),
    ('IsError({bad: 1/0})', False),
    ('IsError({bad: 1/0}.bad)', True),
    ('With({bad: 1/0, good: 42}, good)', 42),
    ('IfError({bad: 1/0, good: 42}, {bad: 0, good: 0}).good', 42),
    ('IsError(Index([1, 1/0, 3], 2))', False),
    ('IfError(Index([1, 1/0, 3], 2).Value, FirstError.Kind)', 13),
    ('IfError(CountRows(Filter([1, 0, 2], 1/Value > 0)), FirstError.Kind)', 13),
    ('IsError(Index(Filter([1, 0, 2], 1/Value > 0), 2))', True),
    ('Index(Filter([1, 0, 2], 1/Value > 0), 3).Value', 2),
    ('With({rows: AddColumns([1, 0, 2], Reciprocal, 1/Value)}, Sum(rows, Value))', 3),
    ('With({rows: AddColumns([1, 0, 2], Reciprocal, 1/Value)}, IsError(Index(rows, 2)))', False),
    ('With({rows: AddColumns([1, 0, 2], Reciprocal, 1/Value)}, IsError(Index(rows, 2).Reciprocal))', True),
    ('With({rows: Table({a: 1/0, b: 1}, {a: 2, b: 3})}, Sum(ShowColumns(rows, b), b))', 4),
    ('With({rows: Table({a: 1/0, b: 1}, {a: 2, b: 3})}, CountRows(rows.a))', 2),
    ('ForAll(Table({a: 1}, Error({Kind: ErrorKind.Div0}), {a: 3}), {b: IfError(a, -FirstError.Kind)})', [{'b': 1}, {'b': -13}, {'b': 3}]),
    ('IfError(CountIf([0, 1, 0], 1/Value > 0), CountRows(AllErrors))', 1),
    ('IfError(CountRows(ForAll([0, 1, 0], 1/Value)), CountRows(AllErrors))', 2),
    ('IsError(ForAll([0, 1], {bad: 1/Value, good: Value}))', False),
    ('IfError(CountRows(Table({a: 1}, Error({Kind: ErrorKind.Div0}), {a: 3})), FirstError.Kind)', 13),
    ('IsError(Table({a: 1}, If(1/0 < 2, [{a: 2}]), {a: 3}))', True),
    ('IfError(CountRows(Table({a: 1}, If(1/0 < 2, {a: 2}), {a: 3})), FirstError.Kind)', 13),
    ('IfError(Error(Table({Kind: ErrorKind.Div0}, {Kind: ErrorKind.Custom})), CountRows(AllErrors))', 2),
    ('IfError(1/0, Error(AllErrors))', None),
])
def test_cell_observation_and_error_rows(runtime, expression, expected):
    if expected is None:
        with pytest.raises(FxError) as error:
            runtime.fx.evaluate(expression)
        assert error.value.kind == 'Div0'
    else:
        assert runtime.fx.evaluate(expression) == expected


def test_error_coercion_preserves_other_cells(runtime):
    rows = runtime.fx.evaluate('Table([42], ["everything"])')
    assert rows[0] == {'Value': 42}
    assert isinstance(rows[1]['Value'], FxError)
    assert rows[1]['Value'].kind == 'InvalidArgument'
    assert serial(rows)[1]['Value']['$error']['Kind'] == 25
    assert value_type(rows[1]['Value']).kind == 'Error'


def test_behavior_chains_continue_and_iferror_stops_later_actions(runtime):
    ctx = Context(runtime, behavior=True)
    assert runtime.fx.evaluate('IfError((1/0; Set(later, 42); 2/0), CountRows(AllErrors))', ctx) == 2
    assert runtime.globals['later'] == 42
    runtime.fx.evaluate('IfError(1/0, Set(failure, true), Set(later, 99))', ctx)
    assert runtime.globals['failure'] is True
    assert runtime.globals['later'] == 42


def test_forall_runs_all_side_effects_and_rethrows_all_errors(runtime):
    ctx = Context(runtime, behavior=True)
    value = runtime.fx.evaluate('IfError(CountRows(ForAll([1, 0, 2, 0, 3], If(1/Value > 0, Collect(good, Value)))), CountRows(AllErrors))', ctx)
    assert value == 2
    assert runtime.collections['good'] == [{'Value': 1}, {'Value': 2}, {'Value': 3}]


def test_set_stores_unobserved_errors_and_reacts_after_correction(runtime):
    ctx = Context(runtime, behavior=True)
    assert runtime.fx.evaluate('Set(bad, 1/0); Set(healthy, 42)', ctx) is None
    assert isinstance(runtime.globals['bad'], FxError)
    assert not runtime.diagnostics
    assert runtime.fx.evaluate('IfError(bad, FirstError.Kind)') == 13
    runtime.fx.evaluate('Set(bad, 5)', ctx)
    assert runtime.fx.evaluate('bad + healthy') == 47


def test_failed_list_write_keeps_persistent_values(runtime):
    before = runtime.store.rows('Projects')
    ctx = Context(runtime, behavior=True)
    assert runtime.fx.evaluate('IfError(Patch(Projects, First(Projects), {Title: "Do not save", Amount: 1/0}), {ID: FirstError.Kind}).ID', ctx) == 13
    assert runtime.store.rows('Projects') == before
    assert runtime.fx.evaluate('IfError(Patch(Projects, First(Projects), {Status: {Value: 1/0}}), {ID: FirstError.Kind}).ID', ctx) == 13
    assert runtime.store.rows('Projects') == before


def test_gallery_error_rows_and_cells_do_not_hide_healthy_controls(runtime):
    gallery = runtime.global_refs['ProjectGallery']
    gallery.control.properties['Items'] = '=Filter(Projects, 1/(ID - 2) <> 0)'
    runtime.invalidate()
    tree = runtime.render(gallery)
    assert len(tree['rows']) == 3
    assert tree['rows'][1]['error']['Kind'] == 13
    assert tree['rows'][0]['children'] and tree['rows'][2]['children']
    assert any(d['member'] == 'ProjectGallery.Items' for d in runtime.diagnostics)
    gallery.control.properties['Items'] = '=AddColumns(Projects, Reciprocal, 1/(ID - 2))'
    runtime.invalidate()
    tree = runtime.render(gallery)
    assert len(tree['rows']) == 3
    assert all('error' not in row for row in tree['rows'])
    assert all(row['children'] for row in tree['rows'])


def test_selector_isolates_error_options_and_rejects_selecting_error_rows(runtime):
    selector = runtime.global_refs['StatusInput']
    selector.control.properties['Items'] = '=Table({Value: "Draft"}, Error({Kind: ErrorKind.Div0}), {Value: 1/0}, {Value: "Approved"})'
    selector.control.properties['DefaultSelectedItems'] = '=Blank()'
    runtime.invalidate()
    node = runtime.render(selector)
    assert [option['label'] for option in node['options'] if not option.get('disabled')] == ['Draft', 'Approved']
    assert len([option for option in node['options'] if option.get('disabled')]) == 2
    with pytest.raises(FxError) as error:
        runtime.event(selector.path, 'OnChange', selection=[1])
    assert error.value.kind == 'Div0'
    runtime.event(selector.path, 'OnChange', selection=[3])
    assert selector.property('Selected')['Value'] == 'Approved'

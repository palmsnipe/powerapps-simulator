import pytest

from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError, Parser, walk, call_name


@pytest.mark.parametrize("formula,expected", [
    ('1 + 2 * 3', 7), ('-2^2', -4), ('2^3^2', 512), ('50%', .5),
    ('"quote ""inside"""', 'quote "inside"'), ('/* x */ If(true, 4, 1/0) // y', 4),
    ('false && 1/0 = 1', False), ('true || 1/0 = 1', True),
    ('Switch(2, 1, 1/0, 2, 8, 0)', 8), ('Coalesce(Blank(), "", "ok")', 'ok'),
    ('IsBlank(Blank())', True), ('IsEmpty([])', True), ('IsError(1/0)', True),
    ('IfError(1/0, FirstError.Kind, 999)', 13),
    ('IfError(1, "bad", 2, "bad", "default")', 'default'),
    ('And(true, true, !false)', True), ('Or(false, true)', True), ('Not(false)', True),
    ('"ab" & Text(12)', 'ab12'), ('"A" in "cat"', True), ('"A" exactin "cat"', False),
    ('2 in [1,2,3]', True), ('CountRows([1,2])', 2),
    ('Filter([1,2,3] As r, r.Value > 1)', [{'Value': 2}, {'Value': 3}]),
    ('LookUp(Table({Name: "A", N: 1}, {Name: "B", N: 2}), Name = "B", N)', 2),
    ('With({base: 3}, base * 2)', 6), ('ForAll([1,2] As r, {N: r.Value * 2})', [{'N': 2}, {'N': 4}]),
    ('AddColumns([1,2], Twice, Value * 2)', [{'Value': 1, 'Twice': 2}, {'Value': 2, 'Twice': 4}]),
    ('ShowColumns(Table({A: 1, B: 2}), A)', [{'A': 1}]),
    ('SortByColumns(Table({N: 2}, {N: 1}), "N", SortOrder.Ascending)', [{'N': 1}, {'N': 2}]),
    ('CountIf([1,2,3], Value > 1)', 2), ('First([4,5]).Value', 4), ('FirstN([4,5], 1)', [{'Value': 4}]),
    ('Index([4,5], 2).Value', 5), ('Distinct([1,1,2], Value)', [{'Value': 1}, {'Value': 2}]),
    ('Sum([1,2], Value)', 3), ('Min(4,2,5)', 2), ('Max([1,4], Value)', 4),
    ('Lower("ABC")', 'abc'), ('TrimEnds("  a  b  ")', 'a  b'), ('Trim("  a  b  ")', 'a b'),
    ('Left("abcd", 2)', 'ab'), ('StartsWith("Alpha", "al")', True), ('Substitute("aba", "a", "x")', 'xbx'),
    ('Text(7, "00", "en-US")', '07'), ('Text(1234.5, "$#,##0.00", "en-US")', '$1,234.50'),
    ('Round(1.25, 1)', 1.3), ('Mod(2026,100)', 26), ('IsNumeric("12")', True), ('Char(10)', '\n'),
    ('Year("2026-10-09")', 2026), ('Month("2026-10-09")', 10),
    ('RGBA(15,108,189,1)', 'rgba(15,108,189,1)'),
    ('DataSourceInfo(Projects, DataSourceInfo.MaxLength, Title)', 255),
    ('Choices(Projects.Status)', [{'Value': 'Draft'}, {'Value': 'Submitted'}, {'Value': 'Approved'}]),
    ('T("title", [])', 'Project workspace'), ('Arg("x")', {'Value': 'x'}),
])
def test_supported_expressions(runtime, formula, expected):
    assert runtime.fx.evaluate(formula) == expected


def test_environment_functions(runtime):
    runtime.environment.update(clock='2026-10-09T14:30:00+00:00', language='fr-CA', parameters={'id': '123'})
    assert runtime.fx.evaluate('Today()').isoformat() == '2026-10-09'
    assert runtime.fx.evaluate('Now()').isoformat() == '2026-10-09T14:30:00+00:00'
    assert runtime.fx.evaluate('User().Email') == 'admin@example.test'
    assert runtime.fx.evaluate('Language()') == 'fr-CA'
    assert runtime.fx.evaluate('Param("id")') == '123'
    assert len(runtime.fx.evaluate('GUID()')) == 36
    assert runtime.fx.evaluate('Defaults(Projects).Amount') == 0


def test_typed_function_and_table_contract(runtime):
    assert runtime.fx.evaluate('T("title", [Arg("x")])') == 'Project workspace'
    assert runtime.fx.evaluate('Arg(1)') == {'Value': '1'}
    with pytest.raises(FxError, match='incompatible function schema'):
        runtime.fx.evaluate('T("title", [{Other: "x"}])')


def test_ordered_behavior_and_pure_property_protection(runtime):
    with pytest.raises(FxError, match='Behavior functions'):
        runtime.fx.evaluate('Set(x, 1)')
    assert 'x' not in runtime.globals
    ctx = Context(runtime, behavior=True)
    runtime.fx.evaluate('Set(x, 1); Set(x, x + 2); ClearCollect(items, [x, 4]); Collect(items, {Value: 5})', ctx)
    assert runtime.globals['x'] == 3
    assert runtime.collections['items'] == [{'Value': 3}, {'Value': 4}, {'Value': 5}]
    runtime.fx.evaluate('Clear(items)', ctx)
    assert runtime.collections['items'] == []


def test_nested_record_scopes_and_global_disambiguation(runtime):
    runtime.globals['Value'] = 10
    assert runtime.fx.evaluate('ForAll([1,2] As outer, LookUp([2,3] As inner, inner.Value > outer.Value, inner.Value + [@Value]))') == [{'Value': 12}, {'Value': 13}]
    assert runtime.fx.evaluate('ForAll(Projects, Projects[@Title])')[0]['Value'] == 'Wetland monitoring'


def test_formula_cycles_and_error_locality(runtime):
    runtime.fx.set_definitions('=A = B + 1; B = A + 1; C = 7;')
    with pytest.raises(FxError, match='dependency cycle'):
        runtime.fx.evaluate('A')
    assert runtime.fx.evaluate('C') == 7
    assert runtime.fx.evaluate('IfError(A, 99)') == 99


def test_parser_recovers_other_named_formulas():
    definitions, errors = Parser('=Good = 1; Bad = ; Later = 3;').definitions()
    assert len(errors) == 1
    assert set(definitions) == {'Good', 'Later'}


@pytest.mark.parametrize('formula', ['"unterminated', '/* open', '{A:}', 'Unexpected(1)', '[1,,]', 'UnknownControl.Text'])
def test_invalid_formulas_are_errors(runtime, formula):
    with pytest.raises(FxError):
        runtime.fx.evaluate(formula)


def test_wrong_arity_and_forall_restrictions(runtime):
    with pytest.raises(FxError, match='expects'):
        runtime.fx.evaluate('If()')
    with pytest.raises(FxError, match='not allowed within ForAll'):
        runtime.fx.evaluate('ForAll([1,2], ClearCollect(items, ThisRecord))', Context(runtime, behavior=True))
    assert runtime.fx.evaluate('IsError(Error({Kind: ErrorKind.Conflict, Message: "Conflict"}))') is True


def test_quoted_identifiers_and_projection(runtime):
    assert runtime.fx.evaluate("With({'Display Name': 7}, 'Display Name')") == 7
    assert runtime.fx.evaluate('Table({N: 1}, {N: 2}).N') == [{'N': 1}, {'N': 2}]


def test_nested_queries_preserve_gallery_thisitem(runtime):
    ctx = Context(runtime, item={"Role": {"Value": "Reviewer"}})
    assert runtime.fx.evaluate(
        'LookUp(Table({Value: "Reviewer", Label: "Review"}, {Value: "Admin", Label: "Manage"}), '
        'ThisRecord.Value = ThisItem.Role.Value, Label)', ctx) == "Review"
    assert runtime.fx.evaluate(
        'ForAll([1,2] As outer, LookUp([3,4] As inner, inner.Value > outer.Value, '
        '{GalleryRole: ThisItem.Role.Value, Outer: outer.Value, Inner: inner.Value}))', ctx) == [
            {"GalleryRole": "Reviewer", "Outer": 1, "Inner": 3},
            {"GalleryRole": "Reviewer", "Outer": 2, "Inner": 3}]


def test_table_unifies_columns_and_retains_blank_records(runtime):
    # Microsoft's Table contract adds Blank for fields omitted from a record.
    assert runtime.fx.evaluate('Table({A: 1}, {B: 2}, Blank())') == [
        {"A": 1, "B": None}, {"A": None, "B": 2}, None]
    assert runtime.fx.evaluate('CountRows(Table(Blank(), Blank()))') == 2
    assert runtime.fx.evaluate('First(Table(Blank())).DisplayName') is None
    with pytest.raises(FxError, match="Table expects"):
        runtime.fx.evaluate('Table(42)')

from decimal import Decimal, localcontext
from io import BytesIO
import json
from zipfile import ZipFile

import pytest

from powerapps_sim.binding import BindScope, value_type
from powerapps_sim.conformance import run_case
from powerapps_sim.fx import Context
from powerapps_sim.numeric import DECIMAL_MAX, decimal_value
from powerapps_sim.runtime import Runtime, serial
from powerapps_sim.source import Project
from powerapps_sim.syntax import FxError, Parser


@pytest.fixture
def decimal_runtime(runtime):
    runtime.environment['number_mode'] = 'decimal'
    runtime.binder.nodes.clear(); runtime.binder.aliases.clear(); runtime.binder.named.clear()
    yield runtime


@pytest.mark.parametrize('expression, expected', [
    ('0.1 + 0.2', '0.3'),
    ('1.0000000000000000000000000001 * 2', '2.0000000000000000000000000002'),
    ('9007199254740993 + 1', '9007199254740994'),
    ('79228162514264337593543950335 - 1', '79228162514264337593543950334'),
    ('1 / 3', '0.3333333333333333333333333333'),
    ('1 / 6', '0.1666666666666666666666666667'),
    ('100.25%', '1.0025'),
    ('Decimal("1.23456789012345678901234567895")', '1.234567890123456789012345679'),
    ('Decimal("0.00000000000000000000000000005")', '0'),
    ('Decimal("0.00000000000000000000000000006")', '0.0000000000000000000000000001'),
    ('Value("1 234,56", "fr-CA")', '1234.56'),
    ('Value("$- 123.45")', '-123.45'),
    ('Round(3 * 0.415, 2)', '1.25'),
    ('Round(-1.25, 1)', '-1.3'),
    ('RoundDown(-1.29, 1)', '-1.2'),
    ('RoundUp(-1.21, 1)', '-1.3'),
    ('Round(.123456789123456789, Float(2))', '.12'),
    ('Mod(-5.2, 2)', '0.8'),
    ('Mod(5.2, -2)', '-0.8'),
    ('Abs(-1.0000000000000000000000000001)', '1.0000000000000000000000000001'),
    ('Sum(Table({N: .1}, {N: .2}), N)', '.3'),
    ('Average(Table({N: .1}, {N: .2}), N)', '.15'),
    ('Min(.1, .2)', '.1'),
    ('CountRows(Table({N: .1}, {N: .2}))', '2'),
    ('CountIf(Table({N: .1}, {N: .2}), N > 0)', '2'),
    ('Max(.1, .2)', '.2'),
    ('"12.3" + true', '13.3'),
    ('If(false, 1/0, .1 + .2)', '.3'),
    ('IfError(1/0, "0.3")', '.3'),
])
def test_exact_decimal_arithmetic_and_coercions(decimal_runtime, expression, expected):
    result = decimal_runtime.fx.evaluate(expression)
    assert isinstance(result, Decimal)
    assert result == Decimal(expected)
    assert value_type(result).kind == 'Decimal'


@pytest.mark.parametrize('expression, kind', [
    ('79228162514264337593543950335 + 1', 'Numeric'),
    ('Decimal("79228162514264337593543950336")', 'Numeric'),
    ('Decimal("1e1000000")', 'Numeric'),
    ('Decimal("1e1000000%")', 'Numeric'),
    ('Decimal("abc")', 'InvalidArgument'),
    ('1 / 0', 'Div0'),
    ('Mod(1, 0)', 'Div0'),
    ('Round("wrong", "also wrong")', 'InvalidArgument'),
])
def test_numeric_errors_keep_kind_and_source_span(decimal_runtime, expression, kind):
    with pytest.raises(FxError) as error:
        decimal_runtime.fx.evaluate(expression)
    assert error.value.kind == kind
    assert error.value.end > error.value.start
    if 'also wrong' in expression:
        assert len(error.value.records()) == 2


def test_mixed_float_promotion_and_canvas_default(runtime, decimal_runtime):
    assert decimal_runtime.fx.evaluate('1.0000000000000000000000000001 * Float(2)') == 2.0
    assert isinstance(decimal_runtime.fx.evaluate('1.0000000000000000000000000001 * Float(2)'), float)
    assert isinstance(decimal_runtime.fx.evaluate('If(true, .1, Float(.2))'), float)
    assert decimal_runtime.fx.evaluate('.1 = Float(.1)') is True
    assert decimal_runtime.fx.evaluate('Decimal(Float("10000000000.0000000001"))') == Decimal('10000000000')
    decimal_runtime.environment['number_mode'] = 'float'
    assert decimal_runtime.fx.evaluate('.1 + .2') == .1 + .2
    assert isinstance(decimal_runtime.fx.evaluate('Value(".3")'), float)
    with pytest.raises(FxError, match='optional Decimal host'):
        decimal_runtime.fx.evaluate('Decimal(".3")')
    decimal_runtime.binder.errors.clear()
    decimal_runtime.binder.bind(decimal_runtime.fx.parse('Decimal(".3")'), BindScope())
    assert any(error.kind == 'Unsupported' for _, error in decimal_runtime.binder.errors)


def test_max_precision_text_and_decimal_context_are_deterministic(decimal_runtime):
    with localcontext() as context:
        context.prec = 3
        assert decimal_runtime.fx.evaluate('Text(79228162514264337593543950335, "0")') == '79228162514264337593543950335'
        assert decimal_runtime.fx.evaluate('1.0000000000000000000000000001 * 2') == Decimal('2.0000000000000000000000000002')
    decimal_runtime.environment['language'] = 'fr-CA'
    assert decimal_runtime.fx.evaluate('Text(.3)') == '0,3'
    assert decimal_runtime.fx.evaluate('Text(1234.56, "#,##0.00")') == '1\u00a0234,56'
    assert decimal_value(DECIMAL_MAX) == DECIMAL_MAX


def test_typed_functions_aliases_and_conditional_cells(decimal_runtime):
    decimal_runtime.fx.set_definitions('=Row := Type({N: Decimal}); Double(row: Row): Decimal = row.N * 2; AsFloat(n: Decimal): Float = Float(n);')
    assert decimal_runtime.fx.evaluate('Double({N: .1})') == Decimal('.2')
    assert isinstance(decimal_runtime.fx.evaluate('AsFloat(.1)'), float)
    with pytest.raises(FxError, match='Cannot parse number'):
        decimal_runtime.fx.evaluate('Double({N: "text"})')
    value = decimal_runtime.fx.evaluate('If(true, {N: .1, Bad: Error({Kind: ErrorKind.Div0})}, {N: Float(.2), Bad: 1})')
    assert isinstance(value['N'], float)
    assert isinstance(value['Bad'], FxError)
    assert decimal_runtime.fx.evaluate('IfError(.3, Value("not a number"))') == Decimal('.3')
    assert [row['Value'] for row in decimal_runtime.fx.evaluate('Sequence(3, .1, .1)')] == [Decimal('.1'), Decimal('.2'), Decimal('.3')]


def test_literal_lexemes_and_profile_specific_types(runtime):
    node = Parser('1.0000000000000000000000000001').parse()
    assert node.numeric_literal == '1.0000000000000000000000000001'
    for mode, kind in [('float', 'Number'), ('decimal', 'Decimal'), ('float', 'Number')]:
        runtime.environment['number_mode'] = mode
        assert value_type(runtime.fx.evaluate('.1')).kind == kind
        assert runtime.binder.bind(runtime.fx.parse('.1'), BindScope()).kind == kind
    runtime.environment['number_mode'] = 'decimal'
    runtime.binder.errors.clear()
    runtime.binder.bind(runtime.fx.parse('1e100'), BindScope())
    assert any(error.kind == 'Numeric' for _, error in runtime.binder.errors)


def test_lossless_sqlite_decimal_columns_and_float_connector_boundary(decimal_runtime):
    store = decimal_runtime.store
    store.add_list('Exact', {'fields': {'ID': {'type': 'integer'}, 'Amount': {'type': 'number', 'format': 'decimal'}, 'Approximate': {'type': 'number'}}, 'mapping': {'ID':'ID', 'Amount':'Exact amount', 'Approximate':'Approximate'}})
    result = store.patch('Exact', {}, {'Exact amount': Decimal('9007199254740993.25'), 'Approximate': Decimal('.1')})
    assert result['Exact amount'] == {'$decimal':'9007199254740993.25'}
    assert result['Approximate'] == .1
    hydrated = store.source('Exact').rows()[0]
    assert hydrated['Exact amount'] == Decimal('9007199254740993.25')
    assert isinstance(hydrated['Approximate'], float)
    store.import_rows('Exact', [{'ID':2,'Exact amount':{'$decimal':'0.123456789123456789'}}])
    assert store.source('Exact').rows()[1]['Exact amount'] == Decimal('0.123456789123456789')
    exported = store.export_csv('Exact')
    assert '$decimal' in exported and '9007199254740993.25' in exported
    with pytest.raises(FxError):
        store.patch('Exact', {}, {'Exact amount':{'$decimal':'1e100'}})
    assert len(store.rows('Exact')) == 2
    reopened = Runtime(Project(decimal_runtime.project.root))
    try:
        assert reopened.store.source('Exact').rows()[0]['Exact amount'] == Decimal('9007199254740993.25')
    finally:
        reopened.close()


def test_reference_report_restores_host_and_precision(runtime):
    original = runtime.environment
    result = run_case(runtime, {'expression':'.1 + .2', 'expected':{'$decimal':'0.3'}, 'environment':{'number_mode':'decimal'}})
    assert result['status'] == 'passed'
    assert runtime.environment is original
    assert runtime.fx.evaluate('.1 + .2') == .1 + .2
    assert json.loads(json.dumps(serial(Decimal('9007199254740993.25')))) == {'$decimal':'9007199254740993.25'}


def test_number_settings_validation_and_rebinding(post, runtime):
    before = dict(runtime.environment)
    assert post('/api/scenario', {'environment':{**before,'number_mode':'guess'}}).status_code == 400
    assert runtime.environment == before
    runtime.fx.set_definitions('=Amount = .1 + .2;')
    assert runtime.fx.evaluate('Amount') == .1 + .2
    assert post('/api/scenario', {'environment':{**before,'number_mode':'decimal'}}).status_code == 200
    assert runtime.fx.evaluate('Amount') == Decimal('.3')
    assert runtime.binder.named['Amount'].kind == 'Decimal'


@pytest.fixture
def numbers(tmp_path):
    from powerapps_sim.fixtures import numeric_project
    runtime = Runtime(numeric_project(tmp_path / 'numbers'))
    runtime.restart()
    yield runtime
    runtime.close()


def test_decimal_components_preserve_typed_callbacks_and_instance_state(numbers):
    state = numbers.state()
    assert not numbers.diagnostics
    assert numbers.fx.evaluate('SampleTotal') == Decimal('.3')
    assert numbers.fx.evaluate('LineTotal(.415, 3)') == Decimal('1.245')
    numbers.event('Numbers/LeftMoney/Advance', 'OnSelect')
    numbers.event('Numbers/LeftMoney/Advance', 'OnSelect')
    assert numbers.fx.evaluate('LeftMoney.Total') == Decimal('.3')
    assert numbers.fx.evaluate('RightMoney.Total') == Decimal('.2')
    assert numbers.globals['leftChanged'] == Decimal('.3')
    assert 'localTotal' not in numbers.globals
    assert numbers.fx.evaluate('LeftMoney.Caption(9007199254740993.25)') == 'Total 9007199254740993.25'
    numbers.event('Numbers/ResetLeft', 'OnSelect')
    assert numbers.fx.evaluate('LeftMoney.Total') == Decimal('.1')
    assert numbers.fx.evaluate('RightMoney.Total') == Decimal('.2')
    # Geometry stays Float while custom component Number data remains Decimal.
    assert isinstance(numbers.global_refs['LeftMoney'].property('Width'), float)
    assert isinstance(numbers.fx.evaluate('LeftMoney.Total'), Decimal)
    json.dumps(state)
    assert not numbers.diagnostics


def test_decimal_form_failed_save_persistence_and_last_submit(numbers):
    form = numbers.global_refs['AmountForm']; inp = numbers.global_refs['AmountInput']
    assert inp.property('Text') == '0.123456789123456789'
    precise = '9007199254740993.25'
    numbers.event(inp.path, 'OnChange', precise)
    assert form.property('Updates')['Amount'] == Decimal(precise)
    numbers.store.failures['Ledger'] = 'write'
    numbers.submit_form(form)
    assert 'Simulated write failure' in form.property('Error')
    assert numbers.store.rows('Ledger') == []
    assert inp.property('Text') == precise and form.property('Unsaved')
    numbers.store.failures.clear()
    numbers.submit_form(form)
    assert form.property('LastSubmit')['Amount'] == Decimal(precise)
    assert numbers.globals['savedAmount'] == Decimal(precise)
    assert numbers.store.rows('Ledger')[0]['Amount'] == {'$decimal':precise}
    assert numbers.global_refs['SavedCaption'].property('Text') == 'Saved exactly: ' + precise
    assert not form.property('Unsaved')
    reopened = Runtime(Project(numbers.project.root))
    try:
        assert reopened.fx.evaluate('First(Ledger).Amount') == Decimal(precise)
    finally:
        reopened.close()


def test_decimal_fixture_exports_source_only_and_refuses_overwrite(numbers):
    from powerapps_sim.fixtures import numeric_project
    source = numbers.project.documents['Src/numeric.pa.yaml']
    assert 'MoneyPanel' in source and 'Value(AmountInput.Text)' in source
    assert 'number_mode' not in source and '$decimal' not in source
    with ZipFile(BytesIO(numbers.project.export())) as archive:
        assert all(name.startswith(('Src/', 'assets/')) for name in archive.namelist())
        assert archive.read('Src/numeric.pa.yaml').decode('utf-8') == source
    with pytest.raises(ValueError, match='existing projects'):
        numeric_project(numbers.project.root)

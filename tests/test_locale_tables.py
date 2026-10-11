"""Documented namespace contracts and locale-isolated reactive values."""
from copy import deepcopy
import pytest

from powerapps_sim.binding import BindScope
from powerapps_sim.fx import Context
from powerapps_sim.locale_tables import FUNCTIONS
from powerapps_sim.runtime import serial
from powerapps_sim.syntax import FxError


# Literal tables from Microsoft Learn's en-US Calendar/Clock examples.
EXAMPLES = {
    'Calendar.MonthsLong': 'January February March April May June July August September October November December'.split(),
    'Calendar.MonthsShort': 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(),
    'Calendar.WeekdaysLong': 'Sunday Monday Tuesday Wednesday Thursday Friday Saturday'.split(),
    'Calendar.WeekdaysShort': 'Sun Mon Tue Wed Thu Fri Sat'.split(),
    'Clock.AmPm': ['AM', 'PM'], 'Clock.AmPmShort': ['A', 'P'],
    'Clock.IsClock24': False,
}


@pytest.mark.parametrize('mode', ['float', 'decimal'])
@pytest.mark.parametrize('name,expected', EXAMPLES.items())
def test_microsoft_en_us_examples_and_types(runtime, mode, name, expected):
    runtime.environment.update(language='en-US', number_mode=mode)
    formula = name + '()'
    runtime.binder.errors.clear()
    typ = runtime.binder.bind(runtime.fx.parse(formula), BindScope())
    assert not runtime.binder.errors
    assert serial(runtime.fx.evaluate(formula)) == (
        expected if isinstance(expected, bool) else [{'Value': v} for v in expected])
    if isinstance(expected, bool):
        assert typ.kind == 'Boolean'
    else:
        assert typ.row.fields['Value'].kind == 'Text' and not typ.row.open


@pytest.mark.parametrize('name', sorted(FUNCTIONS))
@pytest.mark.parametrize('argument', ['Blank()', 'Set(unexpected,1)'])
def test_zero_argument_contract_does_not_run_arguments(runtime, name, argument):
    formula = name + '(' + argument + ')'
    runtime.binder.errors.clear()
    runtime.binder.bind(runtime.fx.parse(formula), BindScope(behavior=True))
    assert runtime.binder.errors
    with pytest.raises(FxError, match='expects 0 arguments'):
        runtime.fx.evaluate(formula, Context(runtime, behavior=True))
    assert 'unexpected' not in runtime.globals


@pytest.mark.parametrize('language,first_month,sunday,clock24', [
    ('en-US', 'January', 'Sunday', False), ('en-GB', 'January', 'Sunday', True),
    ('fr-CA', 'janvier', 'dimanche', True), ('es-ES', 'enero', 'domingo', True),
    ('de-DE', 'Januar', 'Sonntag', True), ('ru-RU', 'январь', 'воскресенье', True),
    ('ja-JP', '1月', '日曜日', True), ('ar-EG', 'يناير', 'الأحد', False),
])
def test_pinned_locale_names_sunday_order_and_clock_consistency(runtime, language, first_month, sunday, clock24):
    runtime.environment['language'] = language
    assert runtime.fx.evaluate('First(Calendar.MonthsLong()).Value') == first_month
    assert runtime.fx.evaluate('First(Calendar.WeekdaysLong()).Value') == sunday
    assert runtime.fx.evaluate('CountRows(Calendar.MonthsLong())') == 12
    assert runtime.fx.evaluate('CountRows(Calendar.WeekdaysLong())') == 7
    assert runtime.fx.evaluate('Clock.IsClock24()') is clock24
    assert runtime.fx.evaluate('CountRows(Clock.AmPm())') == (0 if clock24 else 2)
    assert runtime.fx.evaluate('CountRows(Clock.AmPmShort())') == (0 if clock24 else 2)


def test_interleaved_locales_do_not_share_resolved_cldr_aliases(runtime):
    # This order exposed Japanese names leaking into French/Arabic through
    # Babel 2.18's inherited stand-alone aliases.
    expected = {'fr-CA': 'janvier', 'ja-JP': '1月', 'ar-EG': 'يناير', 'ru-RU': 'январь'}
    for language in ('fr-CA', 'ja-JP', 'ar-EG', 'ru-RU', 'fr-CA', 'ja-JP', 'ar-EG'):
        runtime.environment['language'] = language
        runtime.invalidate()
        assert runtime.fx.evaluate('First(Calendar.MonthsLong()).Value') == expected[language]
        assert runtime.fx.evaluate('Text(Date(2024,1,1),"mmmm")') == expected[language]


def test_month_names_are_standalone_not_genitive(runtime):
    runtime.environment['language'] = 'ru-RU'
    assert runtime.fx.evaluate('First(Calendar.MonthsLong()).Value') == 'январь'
    assert runtime.fx.evaluate('Text(Date(2024,1,1),"d mmmm")') == '1 января'


def test_empty_clock_tables_retain_schema_in_typed_functions(runtime):
    runtime.environment['language'] = 'fr-CA'
    runtime.fx.set_definitions('=Labels := Type([{Value:Text}]); Identity(values:Labels):Labels=values;')
    runtime.binder.errors.clear()
    formula = 'Identity(Clock.AmPm())'
    typ = runtime.binder.bind(runtime.fx.parse(formula), BindScope())
    assert not runtime.binder.errors and typ.row.fields['Value'].kind == 'Text'
    assert serial(runtime.fx.evaluate(formula)) == []


@pytest.mark.parametrize('language,kind', [('bad!tag', 'BadLanguageCode'), ('zz-ZZ', 'Unsupported')])
def test_locale_errors_are_catchable_and_lazy(runtime, language, kind):
    runtime.environment['language'] = language
    with pytest.raises(FxError) as error:
        runtime.fx.evaluate('Calendar.MonthsLong()')
    assert error.value.kind == kind
    assert runtime.fx.evaluate('IfError(IsEmpty(Calendar.MonthsLong()),false)') is False
    assert runtime.fx.evaluate('If(false,Clock.IsClock24(),true)') is True


def test_tables_are_fresh_and_queries_preserve_value_scope(runtime):
    rows = runtime.fx.evaluate('Calendar.MonthsLong()')
    rows[0]['Value'] = 'changed locally'
    assert runtime.fx.evaluate('First(Calendar.MonthsLong()).Value') == 'January'
    assert runtime.fx.evaluate('Concat(Filter(Calendar.MonthsShort() As M,StartsWith(M.Value,"J")),Value,",")') == 'Jan,Jun,Jul'
    assert runtime.fx.evaluate('With({Calendar:{MonthsLong:"local field"}},First(Calendar.MonthsLong()).Value)') == 'January'
    # Bare namespace/member access is not fabricated as an enum or record.
    with pytest.raises(FxError):
        runtime.fx.evaluate('Calendar.MonthsLong')


def test_reactive_properties_follow_locale_but_collection_snapshots_do_not(runtime):
    from powerapps_sim.source import Control
    definition = Control('LocaleProbe', 'ModernText@1.0.0', {'Properties': {
        'Text': '=First(Calendar.MonthsLong()).Value & If(Clock.IsClock24(),"24","12")'}}, 'Src/locale-probe.pa.yaml')
    probe = runtime.build(definition, 'Home/LocaleProbe')
    assert probe.property('Text') == 'January12'
    runtime.execute('ClearCollect(snapshot,Calendar.MonthsLong())', Context(runtime, behavior=True))
    original = deepcopy(runtime.collections['snapshot'])
    runtime.environment['language'] = 'fr-CA'
    runtime.invalidate()
    assert probe.property('Text') == 'janvier24'
    assert runtime.collections['snapshot'] == original

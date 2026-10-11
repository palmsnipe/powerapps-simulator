import pytest

from powerapps_sim.syntax import FxError
from powerapps_sim.runtime import serial


@pytest.mark.parametrize('expression, expected', [
    ('Date(80, 1, 2)', '1980-01-02'),
    ('Date(2000, 25, 69)', '2002-03-10'),
    ('Date(2000, 2, -1)', '2000-01-30'),
    ('Date(1933, 0, 25)', '1932-12-25'),
    ('DateAdd(Date(2024, 1, 31), 1, TimeUnit.Months)', '2024-02-29'),
    ('DateAdd(Date(2024, 2, 29), 1, TimeUnit.Years)', '2025-02-28'),
    ('DateAdd(Date(2024, 1, 31), 1, TimeUnit.Quarters)', '2024-04-30'),
    ('DateAdd(Date(2024, 1, 1), 2, TimeUnit.Hours)', '2024-01-01'),
    ('DateDiff("2024-01-31", "2024-02-01", TimeUnit.Months)', 1),
    ('DateDiff("2024-02-01", "2024-01-31", TimeUnit.Months)', -1),
    ('DateDiff("2024-12-31T23:59:59.999", "2025-01-01", TimeUnit.Years)', 1),
    ('DateDiff("2024-12-31T23:59:59.999", "2025-01-01", TimeUnit.Days)', 1),
    ('DateDiff("2024-01-01T09:45:00", "2024-01-01T10:15:36", TimeUnit.Hours)', 1),
    ('DateDiff("2024-01-01T10:15:36", "2024-01-01T09:45:00", TimeUnit.Hours)', -1),
    ('DateDiff("2024-01-01T09:45:00", "2024-01-01T09:45:00.003", TimeUnit.Milliseconds)', 3),
    ('DateValue("10/1/1920", "en-US")', '1920-10-01'),
    ('DateValue("10/1/1920", "fr-CA")', '1920-01-10'),
    ('DateValue("February 14, 2001", "en")', '2001-02-14'),
    ('DateTimeValue("jeudi 21 juillet 2022 19:34:03", "fr-FR")', '2022-07-21T19:34:03+00:00'),
    ('DateTimeValue("10/11/2014 1:50:24.765 PM", "en-US")', '2014-10-11T13:50:24.765000+00:00'),
    ('DateTimeValue("12:34:56")', '1899-12-30T12:34:56+00:00'),
    ('DateValue(Blank())', None),
    ('DateValue("")', None),
    ('Text(DateValue("2016-01-31"), "dddd mmmm d", "fr-CA")', 'dimanche janvier 31'),
    ('Text(DateValue("2016-01-31"), DateTimeFormat.LongDate, "en-US")', 'Sunday, January 31, 2016'),
    ('Text(DateValue("2016-01-31"), DateTimeFormat.LongDate, "fr-FR")', 'dimanche 31 janvier 2016'),
    ('Text(DateTimeValue("2024-03-07T17:34:05.231"), "d-mmm-yy hh:mm:ss.fff AM/PM")', '7-Mar-24 05:34:05.231 PM'),
    ('Text(DateTimeValue("2024-03-07T17:34:05"), "yyyy-mm-dd hh:mm:ss")', '2024-03-07 17:34:05'),
    ('Text(DateTimeValue("2024-03-07T17:34:05-04:00"), DateTimeFormat.UTC)', '2024-03-07T21:34:05.000Z'),
    ('Text(DateTimeValue("2024-03-07T17:34:05"), """At: ""hh:mm A/P")', 'At: 05:34 P'),
    ('Text(12, "#.0#")', '12.0'),
    ('Text(8.9, "#.000")', '8.900'),
    ('Text(1234.568, "#.0#")', '1234.57'),
    ('Text(1234567.89, "[$-fr-FR]# ###,## €", "fr-CA")', '1\u00a0234\u00a0567,89 €'),
    ('Value("$ 12.34")', 12.34),
    ('Value("12.34%")', .1234),
    ('Value("%10")', .1),
    ('Value("1\u202f234,56", "fr-FR")', 1234.56),
    ('Value("1\u00a0234,56", "fr-CA")', 1234.56),
    ('Value(true)', 1),
])
def test_dates_and_locales(runtime, expression, expected):
    assert serial(runtime.fx.evaluate(expression)) == expected


def test_environment_locale_is_used_and_explicit_locale_overrides_it(runtime):
    runtime.environment['language'] = 'fr-CA'
    runtime.invalidate()
    assert runtime.fx.evaluate('Value("1 234,56")') == 1234.56
    assert runtime.fx.evaluate('IsNumeric("1 234,56")') is True
    assert runtime.fx.evaluate('IsNumeric("not a number")') is False
    assert runtime.fx.evaluate('Value("1,234.56", "en-US")') == 1234.56
    assert serial(runtime.fx.evaluate('DateValue("10/1/1920")')) == '1920-01-10'
    assert runtime.fx.evaluate('Text(Date(2016, 1, 31), "dddd mmmm d")') == 'dimanche janvier 31'
    assert runtime.fx.evaluate('Text(1234.5, "[$-en-US]#,##0.00")') == '1\u00a0234,50'


@pytest.mark.parametrize('expression, kind', [
    ('Date(-1, 1, 1)', 'InvalidArgument'),
    ('Date(9999, 13, 1)', 'InvalidArgument'),
    ('DateValue("2024-02-30")', 'InvalidArgument'),
    ('DateTimeValue("24:00")', 'InvalidArgument'),
    ('DateValue("2024-01-01", "invalid")', 'BadLanguageCode'),
    ('DateValue("2024-01-01", "zz-ZZ")', 'Unsupported'),
    ('Text(Date(2024, 1, 1), "dddd", "zz-ZZ")', 'Unsupported'),
    ('Value("1e999")', 'Numeric'),
    ('Value("$ 12%")', 'InvalidArgument'),
    ('Value("1.23", "fr-CA")', 'InvalidArgument'),
    ('Text(123, "0.0E+0")', 'Unsupported'),
])
def test_invalid_or_unsupported_formats_are_visible(runtime, expression, kind):
    with pytest.raises(FxError) as error:
        runtime.fx.evaluate(expression)
    assert error.value.kind == kind

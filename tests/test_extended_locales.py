from decimal import Decimal
import pytest
from powerapps_sim.runtime import serial
from powerapps_sim.syntax import FxError
from powerapps_sim.locale_fx import locale,parse_number,parse_datetime
from powerapps_sim.conformance import run_case
from pathlib import Path
import json

CASES=[
 ('Value("123,456","es-ES")',123.456),
 ('Value("123.456","es-ES")',123456),
 ('Value("1.234,56","de-DE")',1234.56),
 ('Value("1.234,56 €","de-DE")',1234.56),
 ('Value("12,5%","pt-BR")',.125),
 ('Value("R$ 12,50","pt-BR")',12.5),
 ('Value("(1.234,56)","es-ES")',-1234.56),
 ('Value("١٢٣٬٤٥٦٫٧٨","ar-EG")',123456.78),
 ('Value("१,२३४.५","hi-IN")',1234.5),
 ('Value("1’234.5","de-CH")',1234.5),
 ('Value("1 234,5","ru-RU")',1234.5),
 ('Value("1,25e3","it-IT")',1250),
 ('Value("12,5","eo")',12.5),
 ('Text(Date(2016,1,31),"dddd mmmm d","es-ES")','domingo enero 31'),
 ('Text(Date(2024,3,7),"dddd mmmm d","de-DE")','Donnerstag März 7'),
 ('Text(Date(2024,3,7),"dddd mmmm d","pt-BR")','quinta-feira março 7'),
 ('Text(Date(2024,3,7),"dddd mmmm d","ja-JP")','木曜日 3月 7'),
 ('Text(Date(2024,3,7),"yyyy-mm-dd","zh-Hans-CN")','2024-03-07'),
 ('Text(Date(2024,3,7),"d mmmm yyyy","ru-RU")','7 марта 2024'),
 ('Text(Date(2024,3,7),"mmmm","ru-RU")','март'),
 ('Text(1234.5,"[$-de-DE]#.##0,00","es-ES")','1.234,50'),
 ('Text(1234567.89,"[$-en-US]#,##0.00","hi-IN")','12,34,567.89'),
 ('Text(1234.5,"[$-de-CH]#’##0.00","de-CH")','1’234.50'),
 ('Text(1234.5,"[$-en-US]#,##0.00","ar-EG")','1٬234٫50'),
 ('DateValue("7.3.2024","de-DE")','2024-03-07'),
 ('DateValue("07/03/2024","es-ES")','2024-03-07'),
 ('DateValue("31 de enero de 2016","es-ES")','2016-01-31'),
 ('DateValue("7 марта 2024 г.","ru-RU")','2024-03-07'),
 ('DateTimeValue("2022年07月28日 19:34:03","ja-JP")','2022-07-28T19:34:03+00:00'),
 ('DateValue("2024년 3월 7일","ko-KR")','2024-03-07'),
 ('DateValue("2024年3月7日","zh-CN")','2024-03-07'),
 ('DateTimeValue("2024/03/07 午後1:30","ja-JP")','2024-03-07T13:30:00+00:00'),
 ('TimeValue("午後1:30","ja-JP")','13:30:00'),
 ('TimeValue("١:٣٠ م","ar-EG")','13:30:00'),
 ('Text(Time(13,30,0),"h:mm AM/PM","ja-JP")','1:30 午後'),
 ('Text(Date(2024,3,7),DateTimeFormat.ShortDate,"de-DE")','07.03.2024'),
 ('Text(Date(2024,3,7),DateTimeFormat.LongDate,"es-ES")','jueves, 7 de marzo de 2024'),
 ('Text(Time(13,30,0),DateTimeFormat.ShortTime24,"ar-EG")','13:30'),
]

@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('formula,expected',CASES)
def test_offline_localized_powerfx(runtime,mode,formula,expected):
 runtime.environment['number_mode']=mode;runtime.invalidate()
 value=runtime.fx.evaluate(formula)
 if isinstance(expected,(int,float)):
  assert value==pytest.approx(Decimal(str(expected)) if mode=='decimal' else expected)
 else:assert serial(value)==expected

@pytest.mark.parametrize('tag',['en-AU','en-IN','fr-CH','es-MX','pt-PT','de-AT','it-IT','nl-NL','sv-SE','pl-PL','uk-UA','tr-TR','vi-VN','id-ID','he-IL','ar-SA','fa-IR','hi-IN','bn-BD','th-TH','zh-Hant-TW'])
def test_regional_profiles_have_real_local_data(tag):
 p=locale(tag)
 assert p['tag']==tag.lower() and p['decimal']!=p['group']
 assert p['language']==tag.split('-')[0]
 assert parse_number('123',tag)==123
 assert parse_datetime('2024-03-07',tag).year==2024

@pytest.mark.parametrize('formula',[
 'Value("$ 12,50","de-DE")','Value("€ 12,50%","es-ES")',
 'Value("1,2,3","de-DE")','DateValue("30.2.2024","de-DE")',
 'DateValue("2024年13月7日","ja-JP")','TimeValue("午後13:30","ja-JP")',
])
def test_localized_invalid_values_are_errors(runtime,formula):
 with pytest.raises(FxError):runtime.fx.evaluate(formula)

@pytest.mark.parametrize('tag,kind',[('bad!tag','BadLanguageCode'),('zz-ZZ','Unsupported'),('en-US-u-ca-japanese','Unsupported')])
def test_unknown_tags_do_not_fall_back(runtime,tag,kind):
 with pytest.raises(FxError) as e:runtime.fx.evaluate(f'Value("123","{tag}")')
 assert e.value.kind==kind


def test_environment_language_is_reactive_and_override_is_independent(runtime):
 runtime.environment['language']='es-ES';runtime.invalidate()
 assert runtime.fx.evaluate('Value("123,456")')==123.456
 assert runtime.fx.evaluate('Value("123,456","en-US")')==123456
 assert runtime.fx.evaluate('Text(Date(2016,1,31),"dddd")')=='domingo'
 runtime.environment['language']='de-DE';runtime.invalidate()
 assert runtime.fx.evaluate('Text(Date(2016,1,31),"dddd")')=='Sonntag'


def test_three_original_locale_reference_gaps_now_pass(runtime):
 wanted={'datevalue-extended-72','text-extended-265','value-extended-466'}
 results=[run_case(runtime,c) for p in Path('powerapps_sim/conformance_cases').glob('*.json') for c in json.loads(p.read_text())['cases'] if c['id'] in wanted]
 assert len(results)==3 and all(c['status']=='passed' for c in results),results


@pytest.mark.parametrize('tag',['en-US','fr-CA','de-DE','es-ES','ja-JP'])
@pytest.mark.parametrize('year,expected',[(0,2000),(29,2029),(30,2030),(49,2049),(50,1950),(99,1999)])
def test_pinned_powerfx_two_digit_year_window(runtime,tag,year,expected):
 # GetAdjustedCultureInfo at the pinned Microsoft revision sets 2049.
 text=f'{year:02}/03/07' if tag=='ja-JP' else f'03/07/{year:02}'
 value=runtime.fx.evaluate(f'DateValue("{text}","{tag}")')
 assert value.value.year==expected


def test_localized_abbreviated_weekday_is_not_part_of_the_date(runtime):
 assert serial(runtime.fx.evaluate('DateValue("Do. 7 März 2024","de-DE")'))=='2024-03-07'


@pytest.mark.parametrize('language',['tr-TR','az-Latn-AZ','az-Cyrl-AZ'])
@pytest.mark.parametrize('formula,expected',[
 ('Lower("I İ i ı")','ı i i ı'),('Upper("I İ i ı")','I İ İ I'),
 ('Proper("İSTANBUL IĞDIR izmir ışık")','İstanbul Iğdır İzmir Işık'),
 ('Lower(["I",Blank(),"İ"])',[{'Value':'ı'},{'Value':''},{'Value':'i'}]),
 ('Upper(["i","ı"])',[{'Value':'İ'},{'Value':'I'}]),
])
def test_turkic_simple_casing_and_table_overloads(runtime,language,formula,expected):
 runtime.environment['language']=language;runtime.invalidate()
 assert serial(runtime.fx.evaluate(formula))==expected

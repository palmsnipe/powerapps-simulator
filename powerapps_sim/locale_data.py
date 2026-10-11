"""Pinned CLDR profiles, with no dependency on the OS locale or current clock."""
from functools import lru_cache
from copy import deepcopy
import re
from babel import Locale, UnknownLocaleError
from babel.core import get_global
from babel.dates import get_month_names,get_day_names,get_period_names,get_date_format,get_time_format,format_datetime,format_date,format_time
from babel.numbers import get_decimal_symbol,get_group_symbol,get_currency_symbol
from .syntax import FxError


@lru_cache(maxsize=512)
def profile(tag):
    try:
        culture=Locale.parse(tag,sep='-')
    except (ValueError,UnknownLocaleError):
        raise FxError(f'Locale {tag} is not supported by the bundled locale data','Unsupported') from None
    # Babel 2.18.0 memoizes resolved aliases into dictionaries shared by
    # inherited locales. Isolate its backing data before reading any fields:
    # otherwise loading Japanese stand-alone months can change French/Arabic
    # month names. This pinned-version adapter is covered by interleaving tests.
    culture._Locale__data = deepcopy(culture._data)
    territory=culture.territory
    if not territory:
        likely=get_global('likely_subtags').get(str(culture),get_global('likely_subtags').get(culture.language,''))
        territory=likely.split('_')[-1] if likely else ''
    currencies=get_global('territory_currencies').get(territory,[])
    currency=next((code for code,start,end,tender in currencies if end is None and tender),None)
    symbols=culture.number_symbols.get(culture.default_numbering_system,culture.number_symbols['latn'])
    pattern=str(get_date_format('short',locale=culture))
    # Ordering is taken from CLDR fields, excluding quoted literal text.
    fields=re.findall(r'[yMd]+',re.sub(r"'[^']*'",'',pattern))
    order=''.join(dict.fromkeys(field[0] for field in fields))
    return {'tag':tag,'language':culture.language,'culture':culture,
        'decimal':get_decimal_symbol(culture,numbering_system='default'),
        'group':get_group_symbol(culture,numbering_system='default'),
        'currency':get_currency_symbol(currency,locale=culture) if currency else '',
        'percent':symbols.get('percentSign','%'),'minus':symbols.get('minusSign','-'),
        'plus':symbols.get('plusSign','+'),'order':order,'day_first':order.startswith('d'),
        'grouping':culture.decimal_formats[None].grouping}


def names(p,width='wide',context='format'):
    c=p['culture']
    return ([get_month_names(width,context,locale=c)[i] for i in range(1,13)],
        [get_day_names(width,context,locale=c)[i] for i in range(7)])


def periods(p):
    values=get_period_names('abbreviated',context='format',locale=p['culture'])
    return values.get('am','AM'),values.get('pm','PM')


def enum_date(value,fmt,p):
    """CLDR enum rendering; Power Fx custom masks remain in locale_fx."""
    culture=p['culture'];short=str(get_date_format('short',locale=culture))
    short=re.sub(r'y+', 'yyyy',short)
    long=str(get_date_format('full',locale=culture))
    short_time=str(get_time_format('short',locale=culture))
    long_time=str(get_time_format('medium',locale=culture))
    if fmt=='ShortDate':return format_date(value,short,locale=culture)
    if fmt=='LongDate':return format_date(value,long,locale=culture)
    if fmt in ('ShortTime','LongTime'):return format_time(value,short_time if fmt=='ShortTime' else long_time,locale=culture)
    if fmt in ('ShortTime24','LongTime24'):return format_time(value,'HH:mm' if fmt=='ShortTime24' else 'HH:mm:ss',locale=culture)
    if fmt in ('ShortDateTime','LongDateTime','ShortDateTime24','LongDateTime24'):
        pattern=(short if fmt.startswith('Short') else long)+' '+('HH:mm' if fmt.startswith('Short') else 'HH:mm:ss') if fmt.endswith('24') else (short if fmt.startswith('Short') else long)+' '+(short_time if fmt.startswith('Short') else long_time)
        return format_datetime(value,pattern,locale=culture)
    return None


def parse_date_fields(raw,p):
    """Match Gregorian CLDR date patterns; never guess an unknown calendar."""
    months={name.casefold():i+1 for context in ('format','stand-alone') for width in ('wide','abbreviated')
        for i,name in enumerate(names(p,width,context)[0])}
    days=[name for width in ('wide','abbreviated') for name in names(p,width)[1]]
    for length in ('full','long','medium','short'):
        pattern=str(get_date_format(length,locale=p['culture']))
        tokens=re.findall(r"'[^']*'|[a-zA-Z]+|[^a-zA-Z']+",pattern)
        pieces=[];fields=set();valid=True
        for token in tokens:
            if token.startswith("'"):
                pieces.append(re.escape(token[1:-1]));continue
            kind=token[0]
            if kind=='y':pieces.append(r'(?P<year>\d{2,4})');fields.add('year')
            elif kind=='d':pieces.append(r'(?P<day>\d{1,2})');fields.add('day')
            elif kind in ('M','L'):
                pieces.append(r'(?P<month>\d{1,2})' if len(token)<3 else '(?P<month_name>'+ '|'.join(re.escape(n) for n in sorted(months,key=len,reverse=True))+')');fields.add('month')
            elif kind in ('E','e','c'):pieces.append('(?:'+'|'.join(re.escape(n) for n in sorted(days,key=len,reverse=True))+')')
            elif kind.isascii() and kind.isalpha():valid=False;break
            else:pieces.append(re.escape(token))
        if not valid or fields!={'year','month','day'}:continue
        regex=''.join(pieces).replace(r'\ ',r'\s+').replace('\u202f',r'\s+').replace('\u00a0',r'\s+')
        match=re.fullmatch(regex,raw,flags=re.I)
        if match:
            values=match.groupdict();year_text=values['year'];year=int(year_text)
            if len(year_text)<=2:year+=2000 if year<=49 else 1900
            return year,int(values['month']) if values.get('month') else months[values['month_name'].casefold()],int(values['day'])
    return None


def normalize_time(raw,p):
    am,pm=periods(p)
    for localized,ascii_period in ((am,'AM'),(pm,'PM')):
        if localized.casefold() in ('am','pm'):continue
        if raw.casefold().endswith(localized.casefold()):raw=raw[:-len(localized)].rstrip()+' '+ascii_period
        elif raw.casefold().startswith(localized.casefold()):raw=raw[len(localized):].lstrip()+' '+ascii_period
        else:
            raw=re.sub(re.escape(localized)+r'\s*(?=\d{1,2}:)', '',raw,flags=re.I)+' '+ascii_period if re.search(re.escape(localized)+r'\s*\d{1,2}:',raw,flags=re.I) else raw
    return raw

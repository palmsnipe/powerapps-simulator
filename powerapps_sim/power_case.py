"""Proper follows the pinned interpreter's lowercase-then-TextInfo word scan.

Unicode casing tables may differ from a particular Studio/ICU version. Keep
simple (one scalar) mappings: Python str.title expands letters and treats an
ASCII apostrophe as a new word, which does not match TextInfo.
"""
import unicodedata

from .locale_fx import locale
from .power_text import from_units, units


def simple_case(char, upper=False, turkic=False):
    if turkic:
        special = {'i': 'İ', 'ı': 'I'} if upper else {'I': 'ı', 'İ': 'i'}
        if char in special:
            return special[char]
    mapped = char.upper() if upper else char.lower()
    # Default non-Turkic simple lowercase mapping, retaining one scalar.
    if not upper and char == '\u0130':
        return 'i'
    if len(mapped) == 1:
        return mapped
    # Some Greek letters with an iota subscript have a simple uppercase
    # mapping available as their one-scalar titlecase mapping.
    titled = char.title() if upper else char
    return titled if len(titled) == 1 else char


def change_case(value, language, upper=False):
    profile = locale(language)
    turkic = profile['language'] in ('tr', 'az')
    return ''.join(simple_case(char, upper, turkic) for char in from_units(units(value)))


def proper(value, language):
    profile = locale(language)  # No silent fallback for unsupported culture profiles.
    turkic = profile['language'] in ('tr', 'az')
    source = from_units(units(value))
    lowered = ''.join(simple_case(char, turkic=turkic) for char in source)
    result, inside_word = [], False
    for char in lowered:
        category = unicodedata.category(char)
        if category.startswith('L') and not inside_word:
            # TextInfo's four compatibility digraph groups use titlecase.
            result.append(char.title() if char in '\u01c6\u01c9\u01cc\u01f3' else simple_case(char, upper=True, turkic=turkic))
            inside_word = True
        else:
            result.append(char)
            if char != "'" and (category[0] in 'ZPS' or category in ('Cc', 'Cf')):
                inside_word = False
    return ''.join(result)

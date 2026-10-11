"""Portable regex options/classes from pinned Power Fx Match.cs contracts.

Execution remains in regex_fx; this scanner prevents Python engine extensions
from changing Power Fx authoring semantics. Microsoft source revision df4ceba5;
MIT attribution/license accompanies conformance_cases/MICROSOFT-LICENSE.txt.
"""
import regex
from .regex_groups import invalid

WORD=r'\p{Ll}\p{Lu}\p{Lt}\p{Lo}\p{Lm}\p{Mn}\p{Nd}\p{Pc}'
SPACE=r'\p{Z}\x09-\x0d\x85'
CATEGORIES={'L','Lu','Ll','Lt','Lm','Lo','M','Mn','Mc','Me','N','Nd','Nl','No','P','Pc','Pd','Ps','Pe','Pi','Pf','Po','S','Sm','Sc','Sk','So','Z','Zs','Zl','Zp','Cc','Cf'}
ESCAPED=r'\^$.|?*+()[]{} /#'
CLASS_ESCAPED='&-!%,;:<=>@`~'
RESERVED_PAIRS={'<<','==','>>','::','@@','``','~~','%%','&&',';;',',,','!!','||','##','$$','**','++','..','??','^^','--'}


def inline_options(pattern, options):
    match=regex.match(r'^\(\?([imnsx]+)\)',pattern)
    if match:
        flags=match.group(1)
        if len(set(flags))!=len(flags):invalid('repeated inline option')
        if 'n' in flags and 'N' in options:invalid('inline n conflicts with NumberedSubMatches')
        return options+''.join(flag for flag in flags if flag!='n'),match.end()
    return options,0


def _escape(pattern, start, negative):
    """Return (rendered atom, literal endpoint or None, complement, end)."""
    i=start+1
    if i==len(pattern):invalid('incomplete escape')
    char=pattern[i];i+=1
    if char in 'dDsSwW':
        category={'d':r'\p{Nd}','w':WORD,'s':SPACE}[char.lower()]
        if char.isupper():
            if negative:invalid('complement escape inside a negative character class')
            return '[^'+category+']',None,True,i
        return category,None,False,i
    if char in 'pP':
        match=regex.match(r'\{([\w=:-]+)\}',pattern[i:])
        if not match or match.group(1) not in CATEGORIES:invalid('invalid Unicode category')
        if char=='P' and negative:invalid('complement category inside a negative character class')
        return '\\'+char+'{'+match.group(1)+'}',None,False,i+match.end()
    if char in 'xu':
        braced=char=='u' and pattern[i:i+1]=='{'
        match=regex.match(r'\{([0-9a-fA-F]{1,8})\}' if braced else r'[0-9a-fA-F]{'+('2' if char=='x' else '4')+'}',pattern[i:])
        if not match:invalid('invalid hexadecimal escape')
        number=int(match.group(1) if braced else match.group(),16);i+=match.end()
        if number>0xffff:invalid('supplementary characters inside character classes are not supported by the portable dialect')
        if 0xd800<=number<=0xdfff:invalid('surrogate or supplementary character inside character class')
        return regex.escape(chr(number)),number,False,i
    if char in 'fnrt':
        value={'f':'\f','n':'\n','r':'\r','t':'\t'}[char]
        return regex.escape(value),ord(value),False,i
    if char not in ESCAPED+CLASS_ESCAPED:invalid('invalid character-class escape: \\'+char)
    return regex.escape(char),ord(char),False,i


def character_class(pattern, start):
    i=start+1;negative=pattern[i:i+1]=='^'
    if negative:i+=1
    atoms=[]
    while i<len(pattern) and pattern[i]!=']':
        char=pattern[i]
        if char=='\\':
            rendered,point,complement,i=_escape(pattern,i,negative)
            atoms.append((rendered,point,complement,False));continue
        if char in '/|{}()[]^':invalid('reserved character in character class must be escaped: '+char)
        if pattern[i:i+2] in RESERVED_PAIRS:invalid('reserved repeated punctuation in character class')
        if ord(char)>0xffff or 0xd800<=ord(char)<=0xdfff:invalid('surrogate or supplementary character inside character class')
        atoms.append((regex.escape(char),ord(char),False,char=='-'));i+=1
    if i==len(pattern):invalid('unterminated character class')
    if not atoms:invalid('empty character class')
    pieces=[];complements=[];previous_point=None;range_end=False;j=0
    while j<len(atoms):
        rendered,point,complement,hyphen=atoms[j]
        if hyphen:
            if j==0 or j+1==len(atoms) or range_end:invalid('literal hyphen in character class must be escaped')
            after,endpoint,after_complement,after_hyphen=atoms[j+1]
            if previous_point is None or endpoint is None or complement or after_complement:invalid('character-class categories cannot be range endpoints')
            if after_hyphen:invalid('literal hyphen in character class must be escaped')
            if endpoint<previous_point:invalid('reversed character-class range')
            pieces[-1]+='-'+after
            previous_point=endpoint;range_end=True;j+=2;continue
        if complement:complements.append(rendered)
        else:pieces.append(rendered)
        previous_point=point;range_end=False;j+=1
    expression='['+('^' if negative else '')+''.join(pieces)+']' if pieces else None
    if complements:
        expressions=([expression] if expression else [])+complements
        expression='(?:'+'|'.join(expressions)+')'
    return expression,i+1

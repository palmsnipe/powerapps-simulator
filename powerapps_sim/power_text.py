"""Positional text operations use UTF-16 units, as Canvas/.NET strings do."""
import math
import re
from .syntax import FxError

POSITIONAL_FUNCTIONS = frozenset(('Left','Right','Mid','Replace','Substitute','Concatenate'))
TEXT_OPERATIONS = POSITIONAL_FUNCTIONS | {'Find','Split','Char','UniChar','Hex2Dec','Dec2Hex'}
NUMERIC_ARGUMENTS = {'Left':{1},'Right':{1},'Mid':{1,2},'Replace':{1,2},'Substitute':{3},'Find':{2},'Char':{0},'UniChar':{0},'Dec2Hex':{0,1}}


def units(value):
    encoded=value.encode('utf-16-le',errors='surrogatepass')
    return ''.join(chr(encoded[i] | encoded[i+1]<<8) for i in range(0,len(encoded),2))


def from_units(value):
    return value.encode('utf-16-le',errors='surrogatepass').decode('utf-16-le',errors='surrogatepass')


def evaluate(name,values):
    if name in ('Char','UniChar'):
        code=values[0]
        if name=='Char':
            if code<1 or code>=256:raise FxError('Char code must be between 1 and 255','InvalidArgument')
            return chr(int(code))
        code=math.floor(code)
        if code<1 or code>0x10ffff:raise FxError('UniChar code is outside the Unicode range','InvalidArgument')
        if 0xd800<=code<=0xdfff:raise FxError('UniChar requires a complete Unicode scalar','NotApplicable')
        return chr(code)
    if name=='Dec2Hex':
        number=int(values[0])  # Canvas documentation specifies Trunc, including negatives.
        places=int(values[1]) if len(values)>1 else None
        if number<-(1<<39) or number>(1<<39)-1:
            raise FxError('Dec2Hex number is outside the signed 40-bit range','Numeric')
        if places is not None and not 1<=places<=10:
            raise FxError('Dec2Hex places must be between 1 and 10','Numeric')
        if number<0:return format(number+(1<<40),'010X')
        result=format(number,'X')
        if places is not None:
            if len(result)>places:raise FxError('Dec2Hex result does not fit the requested places','Numeric')
            result=result.zfill(places)
        return result
    if name=='Hex2Dec':
        source=values[0]
        if source=='':return 0
        if len(source)>10 or not re.fullmatch(r'[0-9a-fA-F]+',source.strip()):
            raise FxError('Hex2Dec requires up to ten hexadecimal characters','Numeric')
        number=int(source.strip(),16)
        return number-(1<<40) if number>=(1<<39) else number
    if name=='Split':
        source,separator=map(units,values)
        parts=list(source) if not separator else source.split(separator)
        return [{'Value':from_units(part)} for part in parts]
    if name=='Find':
        needle,source=units(values[0]),units(values[1])
        start=int(values[2]) if len(values)>2 else 1
        if start<1 or start>len(source)+1:
            raise FxError('Find starting position must be within the text or at its end','InvalidArgument')
        position=source.find(needle,start-1)
        return position+1 if position>=0 else None
    if name=='Concatenate':return from_units(''.join(units(value) for value in values))
    source=units(values[0])
    if name in ('Left','Right'):
        count=int(values[1])  # The reference IR truncates before validation.
        if count<0:raise FxError('Character count must be nonnegative','InvalidArgument')
        result=source[:count] if name=='Left' else source[-count:] if count else ''
    elif name in ('Mid','Replace'):
        start=int(values[1]);count=values[2] if len(values)>2 else len(source)
        errors=[]
        if start<1:errors.append(FxError('Starting position must be at least one','InvalidArgument'))
        if count<0:errors.append(FxError('Character count must be nonnegative','InvalidArgument'))
        if errors:raise FxError.combine(errors)
        count=int(count)
        result=source[start-1:start-1+count] if name=='Mid' else source[:start-1]+units(values[3])+source[start-1+count:]
    else:
        old,new=units(values[1]),units(values[2])
        occurrence=int(values[3]) if len(values)>3 else None
        if occurrence is not None and occurrence<1:
            raise FxError('Instance number must be at least one','InvalidArgument')
        if not old:result=source
        elif occurrence is None:result=source.replace(old,new)
        else:
            # Nonoverlapping matches; replacement text is never rescanned.
            cursor=0;position=-1
            for _ in range(min(occurrence,len(source)+1)):
                position=source.find(old,cursor)
                if position<0:break
                cursor=position+len(old)
            result=source if position<0 or occurrence>len(source) else source[:position]+new+source[cursor:]
    return from_units(result)

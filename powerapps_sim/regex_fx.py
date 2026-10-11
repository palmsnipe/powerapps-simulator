"""Canvas/.NET shaped regex values; Power Fx formulas stay on the AST interpreter.

Contracts pinned to Microsoft's Power-Fx df4ceba5 (Match.cs/LibraryRegEx.cs).
The modern portable dialect is intentionally a subset: unsupported constructs
raise diagnostics rather than adopting extra features of Python's regex engine.
"""
from dataclasses import dataclass
from functools import lru_cache
import regex
import unicodedata
from .syntax import FxError, call_name
from .enum_fx import EnumValue
from .power_text import units, from_units

FUNCTIONS={'IsMatch','Match','MatchAll'}
MODES={'canvas','powerfx-legacy','powerfx-v1'}
from .regex_constants import MATCH_OPTIONS as OPTIONS, MATCH_MEMBERS as MEMBERS
WORD=r'\p{Ll}\p{Lu}\p{Lt}\p{Lo}\p{Lm}\p{Mn}\p{Nd}\p{Pc}'
SPACE=r'\p{Z}\x09-\x0d\x85'
NEWLINES=r'\r\n\x0b\x0c\x85\u2028\u2029'
TIMEOUT=1.0

def mode(environment):
    result=environment.get('regex_mode','canvas')
    if result not in MODES:raise FxError('Unknown regex compatibility profile','Unsupported')
    return result

def members(environment):
    result=dict(MEMBERS)
    if mode(environment)!='powerfx-v1':result.update(Email=r'.+@.+\.[^.]{2,}',Hyphen=r'\-')
    return result

def constant(node, runtime, *, legacy=False):
    """Authoring-time strings only, matching BinderUtils.TryGetConstantValue.

    The legacy IsMatch binder also accepts pure constant expressions. Prove
    those contain no dynamic references before using the ordinary evaluator.
    """
    if node.kind=='literal' and isinstance(node.value,str):return node.value
    if node.kind=='member' and node.children[0].kind=='name':
        ns=node.children[0].value
        if ns=='Match':values=members(runtime.environment)
        elif ns=='MatchOptions':values=OPTIONS
        else:
            from .enum_fx import CATALOG
            values=CATALOG.get(ns,{}).get('members',{})
        if isinstance(values.get(node.value),str):return values[node.value]
    if node.kind=='binary' and node.value=='&':
        return constant(node.children[0],runtime,legacy=legacy)+constant(node.children[1],runtime,legacy=legacy)
    if node.kind=='interpolate':
        try:return ''.join(constant(part,runtime) for part in node.children)
        except FxError:
            if not legacy:raise
    if node.kind=='call':
        name=call_name(node.children[0]);args=node.children[1:]
        if name=='Concatenate':return ''.join(constant(arg,runtime,legacy=legacy) for arg in args)
        if name in ('Char','UniChar') and len(args)==1:
            arg=args[0]
            if arg.kind=='literal' and arg.numeric_literal is not None:
                number=int(runtime.fx.literal_number(arg.numeric_literal))
            elif arg.kind=='call' and call_name(arg.children[0])=='Hex2Dec' and len(arg.children)==2 and arg.children[1].kind=='literal' and isinstance(arg.children[1].value,str) and len(arg.children[1].value)<=10:
                number=int(arg.children[1].value,16)
            else:raise FxError('Regular expression must be a constant value','Type')
            if 1<=number<=(255 if name=='Char' else 0x10ffff) and not 0xd800<=number<=0xdfff:return chr(number)
    if legacy:
        from .fx import PURE_FUNCTIONS,ENUMS
        def pure(part):
            if part.kind in ('literal','binary','unary','interpolate'):return all(pure(c) for c in part.children)
            if part.kind=='member':return part.children[0].kind=='name' and part.children[0].value in ENUMS
            if part.kind=='call':
                name=call_name(part.children[0])
                return name in PURE_FUNCTIONS-{'User','Language','Param','Now','Today','GUID','Defaults','Choices','DataSourceInfo','Errors'}-FUNCTIONS and all(pure(c) for c in part.children[1:])
            return False
        if pure(node):
            value=runtime.fx.eval(node,__import__('powerapps_sim.fx',fromlist=['Context']).Context(runtime))
            if isinstance(value,EnumValue):value=value.backing
            if isinstance(value,str):return value
    raise FxError('Regular expression must be a constant value','Type')

@dataclass(frozen=True)
class Pattern:
    compiled:object
    captures:tuple
    numbered:bool
    modern:bool
    @property
    def names(self):return tuple(name for _,name in self.captures if name is not None)

def unsupported(message):raise FxError('Regex: '+message,'Unsupported')

def _translate(pattern, options, modern):
    """Lex escapes/classes/groups, mapping .NET group numbering explicitly."""
    out=[];captures=[];unnamed=[];named=[];backrefs=[];i=0;in_class=False;class_start=0;stack=[]
    explicit=modern and 'N' not in options
    free='x' in options
    from .regex_groups import GroupTracker
    from .regex_syntax import character_class
    tracker=GroupTracker() if modern else None
    while i<len(pattern):
        char=pattern[i]
        if not in_class and free and char=='#':
            end=i+1
            while end<len(pattern) and pattern[end] not in '\r\n\v\f\x85\u2028\u2029':end+=1
            i=end;continue
        if not in_class and free and (char in '\t\n\v\f\r\x85' or unicodedata.category(char).startswith('Z')):i+=1;continue
        if modern and char=='[':
            expression,end=character_class(pattern,i)
            if 'i' in options:
                sensitive=regex.compile(expression,regex.VERSION0).fullmatch('ſ') is not None
                folded=regex.compile(expression,regex.VERSION0|regex.IGNORECASE).fullmatch('ſ') is not None
                if folded and not sensitive:expression='(?!(?-i:ſ))'+expression
                elif sensitive and not folded:expression='(?:(?-i:ſ)|'+expression+')'
            tracker.atom();out.append(expression);i=end;continue
        if modern and char==']':raise FxError('Regex: unescaped closing square bracket','Type')
        if char=='\\':
            if i+1==len(pattern):raise FxError('Regex: incomplete escape','Type')
            esc=pattern[i+1];i+=2
            if modern and esc in 'aAeGzZv0':raise FxError('Regex: invalid portable escape \\'+esc,'Type')
            if tracker and not in_class and esc not in 'bBk123456789':tracker.atom()
            if esc in 'dDsSwW':
                category={'d':r'\p{Nd}','w':WORD,'s':SPACE}[esc.lower()]
                if in_class:
                    if esc.isupper():unsupported('complement escapes inside character classes are not implemented')
                    out.append(category)
                else:out.append('['+('^' if esc.isupper() else '')+category+']')
            elif esc in 'bB' and not in_class:
                w='['+WORD+']'
                boundary=f'(?:(?<!{w})(?={w})|(?<={w})(?!{w}))'
                out.append(boundary if esc=='b' else f'(?!{boundary})')
            elif esc=='k':
                match=regex.match(r"(?:<([\w]+)>|'([\w]+)')",pattern[i:])
                if not match:raise FxError('Regex: invalid named backreference','Type')
                if modern and (in_class or 'N' in options or match.group(2) is not None):raise FxError('Regex: invalid named backreference in this profile','Type')
                if tracker:tracker.reference(match.group(1))
                backrefs.append((len(out),match.group(1) or match.group(2)));out.append('');i+=match.end()
            elif esc in '123456789' and not in_class:
                match=regex.match(r'\d*',pattern[i:]);value=esc+match.group();i+=match.end()
                if modern and 'N' not in options:raise FxError('Regex: numbered references require NumberedSubMatches','Type')
                if tracker:tracker.reference(value)
                backrefs.append((len(out),int(value)));out.append('')
            elif esc in 'pP':
                match=regex.match(r'\{([A-Za-z0-9_]+)\}',pattern[i:])
                if not match:raise FxError('Regex: invalid Unicode category','Type')
                category=match.group(1);i+=match.end()
                if modern:
                    from .regex_syntax import CATEGORIES
                    if category not in CATEGORIES:raise FxError('Regex: invalid Unicode category','Type')
                if category not in {'L','Lu','Ll','Lt','Lm','Lo','M','Mn','Mc','Me','N','Nd','Nl','No','P','Pc','Pd','Ps','Pe','Pi','Pf','Po','S','Sm','Sc','Sk','So','Z','Zs','Zl','Zp','C','Cc','Cf','Cs','Co','Cn'}:unsupported('Unicode blocks and non-category properties are not implemented')
                out.append('\\'+esc+'{'+category+'}')
            elif esc in 'xu':
                braced=esc=='u' and pattern[i:i+1]=='{'
                match=regex.match(r'\{([0-9a-fA-F]{1,8})\}' if braced else r'[0-9a-fA-F]{'+('2' if esc=='x' else '4')+'}',pattern[i:])
                if not match:raise FxError('Regex: invalid hexadecimal escape','Type')
                if braced and not modern:raise FxError('Regex: braced Unicode escapes require Power Fx V1','Type')
                number=int(match.group(1) if braced else match.group(),16);i+=match.end()
                if modern and braced and 0xd800<=number<=0xdfff:raise FxError('Regex: invalid Unicode scalar','Type')
                if modern and 0xd800<=number<=0xdbff:
                    pair=regex.match(r'\\u([dD][c-fC-F][0-9a-fA-F]{2})',pattern[i:])
                    if not pair:raise FxError('Regex: unpaired Unicode surrogate','Type')
                    number=0x10000+(number-0xd800)*1024+int(pair.group(1),16)-0xdc00;i+=pair.end()
                if number>0x10ffff or modern and 0xd800<=number<=0xdfff:raise FxError('Regex: invalid Unicode scalar','Type')
                if tracker and not in_class and number>0xffff:
                    # Upstream portable limits count supplementary literals in UTF-16.
                    tracker.stack[-1].minimum+=1;tracker.stack[-1].maximum+=1
                    tracker.target.minimum=tracker.target.maximum=2
                out.append(('(?!(?-i:ſ))' if 'i' in options and number in (83,115) else '')+regex.escape(chr(number)))
            elif esc=='0':unsupported('octal escapes are not implemented')
            elif esc.isalpha() and esc not in 'fnrtvaAbBZzG':raise FxError('Regex: unsupported escape \\'+esc,'Type')
            elif esc in 'AGZz':unsupported('engine-specific anchors are not implemented')
            elif modern and esc=='a':raise FxError('Regex: unsupported escape \\a','Type')
            elif modern and not esc.isalpha() and esc not in r'\^$.|?*+()[]{} /#' and not (in_class and esc in '-&!%:,;<=>@`~'):raise FxError('Regex: invalid escaped punctuation','Type')
            else:out.append('\\'+esc)
            continue
        if char=='[' and not in_class:
            in_class=True;class_start=len(out)
            if modern and pattern[i+1:i+2] in ('',']'):raise FxError('Regex: empty character class','Type')
            out.append(char);i+=1;continue
        if char==']' and in_class:
            in_class=False;out.append(char)
            if tracker:tracker.atom()
            if 'i' in options:
                expression=''.join(out[class_start:])
                try:
                    sensitive=regex.compile(expression,regex.VERSION0).fullmatch('ſ') is not None
                    folded=regex.compile(expression,regex.VERSION0|regex.IGNORECASE).fullmatch('ſ') is not None
                    if folded and not sensitive:out[class_start:]=['(?!(?-i:ſ))'+expression]
                    elif sensitive and not folded:out[class_start:]=['(?:(?-i:ſ)|'+expression+')']
                except regex.error:pass # The final compiler emits the error.
            i+=1;continue
        if in_class:
            if char=='[' or pattern[i:i+2] in ('&&','--'):unsupported('character class subtraction/intersection is not implemented')
            out.append(char);i+=1;continue
        if pattern.startswith('(?#',i):
            end=pattern.find(')',i+3)
            if end<0:raise FxError('Regex: unterminated comment','Type')
            i=end+1;continue
        if char=='(':
            name_match=regex.match(r"\(\?<([\w]+)>|\(\?'([\w]+)'",pattern[i:])
            if name_match:
                name=name_match.group(1) or name_match.group(2)
                if modern and (name_match.group(2) is not None or not regex.fullmatch(r'[_\p{L}][_\p{L}\p{Nd}]*',name)):raise FxError('Regex: invalid portable capture name','Type')
                if name.isdigit():unsupported('explicit numeric group names are not implemented')
                if modern and ('N' in options or any(n==name for _,n in named)):raise FxError('Regex: named captures cannot be combined with NumberedSubMatches or repeated','Type')
                key=next((k for k,n in named if n==name),f'fxg{len(captures)+1}')
                if not any(k==key for k,_ in captures):captures.append((key,name));named.append((key,name))
                if tracker:tracker.open(name)
                out.append(f'(?P<{key}>');stack.append((True,i+name_match.end(),explicit));i+=name_match.end();continue
            if pattern.startswith('(?<=',i) or pattern.startswith('(?<!',i):
                if not modern:unsupported('legacy lookbehind is not implemented in this compatibility subset')
                tracker.open(behind=True)
                out.append(pattern[i:i+4]);stack.append((False,i+4,explicit));i+=4;continue
            if pattern.startswith('(?:',i) or pattern.startswith('(?=',i) or pattern.startswith('(?!',i):
                if tracker:tracker.open(ahead=not pattern.startswith('(?:',i))
                out.append(pattern[i:i+3]);stack.append((False,i+3,explicit));i+=3;continue
            flag=regex.match(r'\(\?([imsnx]*)(?:-([imsnx]+))?([:)])',pattern[i:])
            if flag:
                enabled,disabled,terminator=flag.group(1),flag.group(2) or '',flag.group(3)
                previous_explicit=explicit
                if modern:
                    if i!=0 or disabled or terminator!=')' or not enabled:raise FxError('Regex: inline options must appear once at the start','Type')
                    i+=flag.end();continue
                if 'x' in enabled or 's' in enabled:unsupported('legacy inline DotAll/FreeSpacing is not implemented')
                if 'n' in enabled:explicit=True
                if 'n' in disabled:explicit=False
                flags=''.join(x for x in enabled if x!='n');disable=''.join(x for x in disabled if x!='n')
                if flags or disable:out.append('(?'+flags+('-'+disable if disable else '')+terminator)
                elif terminator==':':out.append('(?:')
                if terminator==':':stack.append((False,i+flag.end(),previous_explicit))
                i+=flag.end();continue
            if modern and (pattern.startswith('(?<',i) or pattern.startswith("(?'",i)):raise FxError('Regex: invalid portable capture name','Type')
            if modern and pattern.startswith('(?',i):raise FxError('Regex: group syntax is not part of the portable dialect','Type')
            if pattern.startswith('(?',i):unsupported('atomic, conditional, balancing, recursive, and engine-specific groups are not implemented')
            if tracker:tracker.open(str(len(unnamed)+1) if not explicit else None)
            if explicit:out.append('(?:');stack.append((False,i+1,explicit))
            else:
                key=f'fxg{len(captures)+1}';captures.append((key,None));unnamed.append((key,None));out.append(f'(?P<{key}>');stack.append((True,i+1,explicit))
            i+=1;continue
        if char==')':
            if not stack:raise FxError('Regex: unmatched closing parenthesis','Type')
            captured,group_start,explicit=stack.pop()
            if tracker:tracker.close()
            out.append(char);i+=1;continue
        if tracker and char=='|':
            tracker.alternate();out.append(char);i+=1;continue
        if tracker and char in '*+?':
            bounds={'*':(0,-1),'+':(1,-1),'?':(0,1)}[char]
            tracker.quantifier(*bounds)
            out.append(char);i+=1
            if pattern[i:i+1]=='?':out.append('?');i+=1
            if pattern[i:i+1] in ('*','+','?') and i<len(pattern):raise FxError('Regex: invalid quantifier','Type')
            continue
        if pattern[i:i+2] in ('*+','++','?+'):raise FxError('Regex: possessive quantifiers are not supported','Type')
        if not modern and char=='{' and not regex.match(r'\{\d+(?:,\d*)?\}',pattern[i:]):out.append(r'\{');i+=1;continue
        if modern and (pattern[i:i+2] in ('*+','++','?+','**','+*','?*') or char in '{}'):
            quant=regex.match(r'\{\d+(?:,\d*)?\}\??',pattern[i:])
            if char=='{' and quant:
                if pattern[i+quant.end():i+quant.end()+1] in ('+','*'):raise FxError('Regex: invalid quantifier','Type')
                bounds=regex.fullmatch(r'\{(\d+)(?:,(\d*))?\}\??',quant.group())
                if bounds.group(2) is None and quant.group().endswith('?'):raise FxError('Regex: exact quantifiers cannot be lazy','Type')
                low=int(bounds.group(1));high=(-1 if bounds.group(2)=='' else int(bounds.group(2))) if bounds.group(2) is not None else low
                if low>2147483647 or high>2147483647:raise FxError('Regex: quantifier integer overflow','Type')
                tracker.quantifier(low,high)
                out.append(quant.group());i+=quant.end();continue
            raise FxError('Regex: invalid quantifier','Type')
        if modern and 0xd800<=ord(char)<=0xdfff:raise FxError('Regex: unpaired Unicode surrogate','Type')
        if tracker and char not in '^$':tracker.atom(2,2) if ord(char)>0xffff else tracker.atom()
        if char=='.':out.append('.' if 's' in options else '[^'+(NEWLINES if modern else r'\n')+']')
        elif char in '^$' and modern:
            if char=='^':out.append(r'(?:(?<=\n)|(?<=[\x0b\x0c\x85\u2028\u2029])|(?<=\r)(?!\n)|\A)' if 'm' in options else r'\A')
            else:out.append(r'(?=\r\n|(?<!\r)\n|[\x0b\x0c\x85\u2028\u2029]|\r(?!\n)|\Z)' if 'm' in options else r'(?=\r\n\Z|(?<!\r)\n\Z|[\x0b\x0c\x85\u2028\u2029]\Z|\r\Z|\Z)')
        elif char in 'sS' and 'i' in options:out.append('(?!(?-i:ſ))'+char)
        else:out.append(char)
        i+=1
    if in_class or stack:raise FxError('Regex: unterminated character class or group','Type')
    if tracker:tracker.complete()
    ordered=unnamed+named
    for index,reference in backrefs:
        key=ordered[reference-1][0] if isinstance(reference,int) and 1<=reference<=len(ordered) else next((k for k,n in named if n==reference),None)
        if key is None:raise FxError('Regex: undefined backreference','Type')
        out[index]=f'(?P={key})'
    return ''.join(out),tuple(ordered)

@lru_cache(maxsize=512)
def compile_pattern(pattern, options, profile):
    modern=profile=='powerfx-v1'
    if not modern and any(flag in options for flag in 'sx'):raise FxError('DotAll and FreeSpacing require Power Fx V1','Type')
    numbered=not modern or 'N' in options
    if not modern:pattern=units(pattern)
    else:pattern=from_units(units(pattern))
    if modern:
        from .regex_syntax import inline_options
        options,_=inline_options(pattern,options)
    translated,captures=_translate(pattern,options,modern)
    # Validate the source before adding option anchors: synthetic groups must
    # not consume the portable nesting budget or change capture scope.
    if '^' in options:translated=_translate('^',options,modern)[0]+'(?:'+translated+')'
    if '$' in options:translated='(?:'+translated+')'+_translate('$',options,modern)[0]
    flags=regex.VERSION0
    if 'i' in options:flags|=regex.IGNORECASE
    if 'm' in options:flags|=regex.MULTILINE
    if 's' in options:flags|=regex.DOTALL
    try:compiled=regex.compile(translated,flags)
    except regex.error as error:raise FxError('Invalid regular expression: '+str(error),'Type') from error
    return Pattern(compiled,captures,numbered,modern)

def options_for(name, environment, value=None):
    if value is None:return '^c$' if name=='IsMatch' and mode(environment)=='canvas' else 'c'
    if isinstance(value,EnumValue):
        if value.namespace!='MatchOptions':raise FxError('Expected MatchOptions','Type')
        value=value.backing
    if not isinstance(value,str):raise FxError('Expected constant MatchOptions text','Type')
    return value

def bind(binder,node,scope):
    from .binding import TEXT,BOOLEAN,NUMBER,record,tabular,UNKNOWN
    args=node.children[1:];name=call_name(node.children[0]);profile=mode(binder.runtime.environment)
    input_type=binder.infer(args[0],scope)
    if input_type.kind not in ('Text','Number','Decimal','Boolean','Date','DateTime','Time','Blank','Error','Dynamic'):binder.require(input_type,TEXT,args[0],name)
    for arg in args[1:]:binder.infer(arg,scope)
    if binder.runtime.environment.get('enum_mode')=='strong':
        pattern_type=binder.nodes.get(id(args[1]))
        if pattern_type and pattern_type.kind=='Enum' and pattern_type.name!='Match':binder.issue('Expected Match pattern or Text',args[1])
        if len(args)>2:binder.require_enum(binder.nodes.get(id(args[2])),'MatchOptions',args[2],'Match options')
    try:
        pattern=constant(args[1],binder.runtime,legacy=name=='IsMatch' and profile!='powerfx-v1')
        options=options_for(name,binder.runtime.environment)
        if len(args)>2:
            try:options=constant(args[2],binder.runtime)
            except FxError:
                if profile=='powerfx-v1':raise FxError('MatchOptions must be a constant value','Type',args[2].start,args[2].end)
                options='c'
        compiled=compile_pattern(pattern,options,profile)
    except (FxError,ValueError,OverflowError) as error:
        if not isinstance(error,FxError):error=FxError('Regular expression must be a constant value','Type')
        location=args[2] if error.start and len(args)>2 else args[1]
        binder.issue(error.message,location,error.kind)
        return BOOLEAN if name=='IsMatch' else (tabular(record({})) if name=='MatchAll' else record({}))
    fields={'FullMatch':TEXT,'StartMatch':NUMBER}
    if compiled.numbered:fields['SubMatches']=tabular(record({'Value':TEXT}))
    fields.update({key:TEXT for key in compiled.names})
    return BOOLEAN if name=='IsMatch' else tabular(record(fields)) if name=='MatchAll' else record(fields)

def evaluate(evaluator,name,args,context):
    env=evaluator.host.environment;profile=mode(env)
    if env.get('enum_mode')=='strong':
        typ=evaluator.node_types.get(id(args[1]))
        if typ and typ.kind=='Enum' and typ.name!='Match':raise FxError('Expected Match pattern or Text','Type')
    pattern=constant(args[1],evaluator.host,legacy=name=='IsMatch' and profile!='powerfx-v1')
    # Guard direct execution too, including authoring-time options in V1.
    options=options_for(name,env)
    if len(args)>2:
        if profile=='powerfx-v1':constant(args[2],evaluator.host)
        option_value=evaluator.eval(args[2],context)
        if env.get('enum_mode')=='strong' and option_value is not None and not isinstance(option_value,EnumValue):raise FxError('Expected MatchOptions enum value','Type')
        options=options_for(name,env,option_value)
    compiled=compile_pattern(pattern,options,profile)
    value=evaluator.eval(args[0],context)
    if isinstance(value,(dict,list)):raise FxError('Regex input must be text','Type')
    text=evaluator.to_text(value);original=text
    if not compiled.modern:text=units(text)
    positions=None
    def decode(start,end):
        return original[start:end] if compiled.modern else from_units(text[start:end])
    def match_record(match):
        nonlocal positions
        start=match.start()
        if compiled.modern and positions is None:
            # Build once for MatchAll; repeated prefix encodes are quadratic.
            positions=[0]
            for char in original:positions.append(positions[-1]+(2 if ord(char)>0xffff else 1))
        result={'FullMatch':decode(start,match.end()),'StartMatch':(positions[start] if compiled.modern else start)+1}
        sub=[]
        for key,field in compiled.captures:
            a,b=match.span(key);value=None if a<0 else decode(a,b)
            if field is not None:result[field]=value
            sub.append({'Value':value})
        if compiled.numbered and 'SubMatches' not in compiled.names:result['SubMatches']=sub
        return result
    try:
        if name=='IsMatch':return compiled.compiled.search(text,timeout=TIMEOUT) is not None
        if name=='Match':
            found=compiled.compiled.search(text,timeout=TIMEOUT)
            return match_record(found) if found else None
        # .NET advances after an empty match; regex.finditer also yields a
        # nonempty match at that same position. Enforce the .NET progression.
        result=[];next_position=0
        for found in compiled.compiled.finditer(text,timeout=TIMEOUT):
            if found.start()<next_position:continue
            result.append(match_record(found));next_position=found.end()+(found.start()==found.end())
        return result
    except TimeoutError as error:raise FxError('Regular expression exceeded the one-second timeout','Timeout') from error

"""Power Fx lexer and Pratt parser. No source is executed as host-language code."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from .errors import error_number


class FxError(Exception):
    def __init__(self, message, kind="Validation", start=0, end=0, errors=None, *, column=None, source="", observed="", details=None):
        super().__init__(message)
        self.message, self.kind, self.start, self.end = message, kind, start, end
        self.errors = tuple(errors or ())
        self.column = column
        self.source,self.observed,self.details=source,observed,details
        self.span_source=source if end else ''
        self.expression_origin=None

    def record(self):
        if self.errors:return self.errors[0].record()
        record={"Kind":error_number(self.kind),"Message":self.message,"Source":self.source,"Observed":self.observed}
        if self.details is not None:
            from copy import deepcopy
            record['Details']=deepcopy(self.details)
        return record

    def located(self,source='',observed=None):
        """Copy provenance rather than mutating cached/stored error values."""
        from copy import copy
        result=copy(self)
        result.source=self.source or source
        result.observed=self.observed if observed is None else observed
        if self.errors:result.errors=tuple(error.located(source,observed) for error in self.errors)
        return result

    def records(self):
        return [record for error in self.errors for record in error.records()] if self.errors else [self.record()]

    @classmethod
    def combine(cls, errors):
        first = errors[0]
        result=cls(first.message, first.kind, first.start, first.end, errors=errors)
        result.span_source=first.span_source
        result.expression_origin=first.expression_origin
        return result


@dataclass
class Token:
    kind: str
    value: object
    start: int
    end: int
    numeric_literal: str | None = None
    quoted: bool = False


@dataclass
class Node:
    kind: str
    value: object = None
    children: list = field(default_factory=list)
    start: int = 0
    end: int = 0
    numeric_literal: str | None = None


@dataclass
class Definition:
    name: str
    body: Node
    params: list | None = None
    returns: str | None = None
    alias: bool = False
    behavior: bool = False


NUMBER = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
IDENT = re.compile(r"[^\W\d]\w*", re.UNICODE)


def tokenize(source: str) -> list[Token]:
    tokens, i = [], 0
    # Formula/text/island modes share the original source and its offsets.
    # Nested interpolations suspend the enclosing island's record depth.
    modes = [{'kind':'formula'}]
    def flush_text(frame, end):
        if frame['text']:
            tokens.append(Token('string', ''.join(frame['text']), frame['segment'], end))
            frame['text'].clear()
    while i < len(source):
        c = source[i]
        frame = modes[-1]
        if frame['kind']=='text':
            if c in ('"','{','}') and source[i:i+2]==c*2:
                frame['text'].append(c);i+=2;continue
            if c=='"':
                flush_text(frame,i);tokens.append(Token('interpolation_end',c,i,i+1))
                modes.pop();i+=1;continue
            if c=='{':
                flush_text(frame,i);tokens.append(Token('island_start',c,i,i+1))
                modes.append({'kind':'island','start':i,'depth':0});i+=1;continue
            if c=='}':raise FxError('A literal closing brace must be doubled in an interpolated string',start=i,end=i+1)
            frame['text'].append(c);i+=1;continue
        if source.startswith('$"',i):
            tokens.append(Token('interpolation_start','$"',i,i+2))
            modes.append({'kind':'text','start':i,'segment':i+2,'text':[]});i+=2;continue
        if frame['kind']=='island' and c=='}' and frame['depth']==0:
            tokens.append(Token('island_end',c,i,i+1));modes.pop();i+=1
            modes[-1]['segment']=i;continue
        if c.isspace():
            i += 1
            continue
        if source.startswith("//", i):
            j = source.find("\n", i)
            i = len(source) if j < 0 else j + 1
            continue
        if source.startswith("/*", i):
            j = source.find("*/", i + 2)
            if j < 0:
                raise FxError("Unterminated comment", start=i, end=len(source))
            i = j + 2
            continue
        if c in "\"'":
            quote, start, value = c, i, ""
            i += 1
            while i < len(source):
                if source[i] == quote:
                    if i + 1 < len(source) and source[i + 1] == quote:
                        value += quote
                        i += 2
                    else:
                        i += 1
                        break
                else:
                    value += source[i]
                    i += 1
            else:
                raise FxError("Unterminated string or identifier", start=start, end=i)
            tokens.append(Token("string" if quote == '"' else "id", value, start, i, quoted=quote=="'"))
            continue
        m = NUMBER.match(source, i)
        if m:
            raw = m.group()
            tokens.append(Token("number", float(raw) if any(x in raw for x in ".eE") else int(raw), i, m.end(), raw))
            i = m.end()
            continue
        m = IDENT.match(source, i)
        if m:
            raw = m.group()
            tokens.append(Token("id", raw, i, m.end()))
            i = m.end()
            continue
        op = next((s for s in [":=", "<=", ">=", "<>", "&&", "||"] if source.startswith(s, i)), c)
        if op not in [":=", "<=", ">=", "<>", "&&", "||"] and c not in "()[]{},;:.@!+-*/^%&=<>":
            raise FxError(f"Unsupported syntax {c!r}", "Unsupported", i, i + 1)
        if frame['kind']=='island':
            if op=='{':frame['depth']+=1
            elif op=='}':frame['depth']-=1
        tokens.append(Token(op, op, i, i + len(op)))
        i += len(op)
    if len(modes)>1:
        frame=modes[-1]
        message='Unterminated interpolated string' if frame['kind']=='text' else 'Unterminated expression inside an interpolated string'
        raise FxError(message,start=frame['start'],end=len(source))
    tokens.append(Token("eof", "", len(source), len(source)))
    return tokens


PRECEDENCE = {";": 1, "as": 2, "or": 3, "||": 3, "and": 4, "&&": 4,
              "=": 5, "<>": 5, "<": 5, ">": 5, "<=": 5, ">=": 5, "in": 5, "exactin": 5,
              "&": 6, "+": 7, "-": 7, "*": 8, "/": 8, "^": 9}


class Parser:
    def __init__(self, source):
        self.source = source
        self.tokens = tokenize(source)
        self.i = 0

    @property
    def token(self):
        return self.tokens[self.i]

    def take(self, kind=None):
        t = self.token
        if kind and t.kind != kind:
            raise FxError(f"Expected {kind}, found {t.value or 'end of formula'}", start=t.start, end=t.end)
        self.i += 1
        return t

    def accept(self, kind):
        if self.token.kind == kind:
            return self.take()
        return None

    def expression(self, minimum=1):
        t = self.take()
        if t.kind in ("number", "string"):
            left = Node("literal", t.value, start=t.start, end=t.end, numeric_literal=t.numeric_literal)
        elif t.kind=='interpolation_start':
            parts=[]
            while self.token.kind!='interpolation_end':
                if self.token.kind=='string':
                    segment=self.take()
                    parts.append(Node('literal',segment.value,start=segment.start,end=segment.end))
                else:
                    self.take('island_start')
                    if self.token.kind=='island_end':
                        raise FxError('Empty expressions cannot appear inside an interpolated string',start=self.token.start,end=self.token.end)
                    parts.append(self.expression())
                    self.take('island_end')
            left=Node('interpolate',children=parts,start=t.start,end=self.take('interpolation_end').end)
        elif t.kind == "id" and not t.quoted and str(t.value).lower() in ("true", "false"):
            left = Node("literal", str(t.value).lower() == "true", start=t.start, end=t.end)
        elif t.kind in ("!", "-", "+") or (t.kind == "id" and not t.quoted and str(t.value).lower() == "not"):
            operand = self.expression(9)
            left = Node("unary", str(t.value).lower(), [operand], t.start, operand.end)
        elif t.kind == "id":
            left = Node("name", t.value, start=t.start, end=t.end)
        elif t.kind == "(":
            left = self.expression()
            self.take(")")
        elif t.kind == "[":
            if self.accept("@"):
                name = self.take("id")
                left = Node("global", name.value, start=t.start, end=self.take("]").end)
            else:
                values = []
                if self.token.kind != "]":
                    while True:
                        values.append(self.expression())
                        if not self.accept(",") or self.token.kind == "]":
                            break
                left = Node("table", children=values, start=t.start, end=self.take("]").end)
        elif t.kind == "{":
            pairs = []
            if self.token.kind != "}":
                while True:
                    key = self.take("id")
                    self.take(":")
                    pairs.append((key.value, self.expression()))
                    if not self.accept(","):
                        break
            left = Node("record", pairs, start=t.start, end=self.take("}").end)
        else:
            raise FxError(f"Expected expression, found {t.value or 'end of formula'}", start=t.start, end=t.end)
        while True:
            t = self.token
            if t.kind in (".", "!"):
                self.take()
                name = self.take("id")
                left = Node("member", name.value, [left], left.start, name.end)
            elif t.kind == "[" and self.tokens[self.i + 1].kind == "@":
                self.take(); self.take()
                name = self.take("id")
                left = Node("disambiguate", name.value, [left], left.start, self.take("]").end)
            elif t.kind == "(":
                self.take()
                args = []
                if self.token.kind != ")":
                    while True:
                        args.append(self.expression())
                        if not self.accept(","):
                            break
                left = Node("call", children=[left, *args], start=left.start, end=self.take(")").end)
            elif t.kind == "%":
                self.take()
                left = Node("unary", "%", [left], left.start, t.end)
            else:
                op = "" if t.quoted else str(t.value).lower()
                p = PRECEDENCE.get(op, 0)
                if p < minimum:
                    break
                self.take()
                if op == ";" and self.token.kind in ("eof", ")", ",", "}", "]", "island_end"):
                    break
                right = self.expression(p if op == "^" else p + 1)
                left = Node("alias" if op == "as" else "binary", op, [left, right], left.start, right.end)
        return left

    def parse(self):
        self.accept("=")
        n = self.expression()
        self.take("eof")
        return n

    def definitions(self):
        """Recover at top-level statement boundaries so one bad definition stays local."""
        self.accept("=")
        definitions, errors = {}, []
        while self.token.kind != "eof":
            begin = self.i
            try:
                name = self.take("id").value
                alias = bool(self.accept(":="))
                params, returns = None, None
                if not alias and self.accept("("):
                    params = []
                    if self.token.kind != ")":
                        while True:
                            pname = self.take("id").value
                            self.take(":")
                            ptype = self.take("id").value
                            params.append((pname, ptype))
                            if not self.accept(","):
                                break
                    self.take(")"); self.take(":")
                    returns = self.take("id").value
                implicit_block = params is not None and self.token.kind == "{"
                if not alias and not implicit_block:
                    self.take("=")
                # A record-valued UDF remains pure. Only a non-record curly
                # body introduces a behavior block (the Microsoft parser uses
                # the same empty-record / identifier-colon lookahead).
                behavior = implicit_block or params is not None and self.token.kind == "{" and not (
                    self.tokens[self.i + 1].kind == "}" or
                    self.tokens[self.i + 1].kind == "id" and self.tokens[self.i + 2].kind == ":")
                if behavior:
                    self.take("{")
                    body = self.expression()
                    self.take("}")
                else:
                    body = self.expression(2)
                if self.token.kind != "eof":
                    self.take(";")
                if name in definitions:
                    raise FxError(f"Duplicate formula {name}", start=body.start, end=body.end)
                definitions[name] = Definition(name, body, params, returns, alias, behavior)
            except FxError as error:
                errors.append(error)
                self.i = begin
                depth = 0
                while self.token.kind != "eof":
                    t = self.take()
                    if t.kind in ("(", "[", "{", "interpolation_start", "island_start"):
                        depth += 1
                    elif t.kind in (")", "]", "}", "interpolation_end", "island_end"):
                        depth -= 1
                    elif t.kind == ";" and depth <= 0:
                        break
        return definitions, errors


def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)
    if node.kind == "record":
        for _, child in node.value:
            yield from walk(child)


def call_name(node):
    if node.kind in ("name", "global"):
        return node.value
    if node.kind == "member":
        base = call_name(node.children[0])
        return f"{base}.{node.value}" if base else None
    return None

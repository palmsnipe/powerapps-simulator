"""Portable Power Fx capture analysis, independent of the regex execution engine.

Adapted from Microsoft's MIT-licensed GroupTracker/GroupInfo in Match.cs,
revision df4ceba5e08220db670c25afead342ce699c50b5. The upstream license is
included in conformance_cases/MICROSOFT-LICENSE.txt. Only the V1 profile uses
these restrictions; Canvas retains its legacy capture behavior.
"""
from dataclasses import dataclass
from .syntax import FxError


def invalid(message):
    raise FxError('Regex: ' + message, 'Type')


@dataclass(eq=False)
class Group:
    parent: object = None
    noncapture: bool = True
    lookaround: bool = False
    actual: bool = False
    closed: bool = False
    error_quant: bool = False
    error_look_quant: bool = False
    zero_quant: bool = False
    alternation: bool = False
    contains_capture: bool = False
    minimum: int = 0
    maximum: int = 0

    def atom(self, minimum, maximum):
        self.minimum += minimum
        self.maximum += maximum
        return Group(minimum=minimum, maximum=maximum)

    def quantifier(self, target, low, high):
        if high != -1 and high < low:
            invalid('quantifier maximum is less than its minimum')
        if target.actual:
            if target.error_look_quant:
                invalid('lookarounds and groups containing lookarounds cannot be quantified')
            if target.error_quant:
                invalid('quantified group contains ambiguous optional, empty, or alternating captures')
            target.zero_quant = low == 0
            if (low == 0 or (low > 0 and (target.minimum == 0 or target.contains_capture))) and (not target.noncapture or target.contains_capture):
                self.error_quant = True
        self.maximum = -1 if self.maximum == -1 or high == -1 else self.maximum + target.maximum * (high - 1)
        self.minimum += target.minimum * (low - 1)

    def end(self):
        if self.minimum == 0 or self.alternation and self.contains_capture:
            self.error_quant = True

    def end_branch(self):
        parent = self.parent
        if parent.alternation:
            parent.maximum = max(parent.maximum, self.maximum)
            parent.minimum = min(parent.minimum, self.minimum)
        else:
            parent.maximum, parent.minimum = self.maximum, self.minimum
        self.end()
        parent.error_quant |= self.error_quant
        parent.error_look_quant |= self.error_look_quant
        parent.contains_capture |= self.contains_capture

    def close(self):
        self.end()
        self.closed = True
        parent = self.parent
        parent.error_quant |= self.error_quant
        parent.error_look_quant |= self.error_look_quant
        if not self.noncapture:
            parent.contains_capture = True
        if not self.lookaround:
            parent.maximum = -1 if parent.maximum == -1 or self.maximum == -1 else parent.maximum + self.maximum
            parent.minimum += self.minimum

    def blocked_reference(self, stop=None):
        if self.zero_quant or self.minimum == 0:
            return 'backreference capture may be empty or absent'
        parent = self.parent
        while parent is not None and parent is not stop:
            if parent.zero_quant or parent.alternation or parent.minimum == 0:
                return 'backreference capture may be absent through alternation or an optional group'
            if parent.lookaround:
                return 'backreference capture is inside a lookaround'
            parent = parent.parent
        if stop is not None and parent is not stop:
            return 'backreference is outside its capture scope'
        return None


class GroupTracker:
    def __init__(self):
        self.stack = []
        self.target = None
        self.behind = None
        self.captures = {}
        self.references = set()
        self.open()

    def open(self, name=None, *, behind=False, ahead=False):
        if len(self.stack) >= 64:
            invalid('maximum nested group depth is 31')
        if self.behind is not None and behind:
            invalid('nested lookbehind is not allowed')
        group = Group(parent=self.stack[-1] if self.stack else None,
                      noncapture=name is None, actual=True, lookaround=behind or ahead)
        if name is not None:
            if self.behind is not None:
                invalid('captures inside lookbehind are not allowed')
            if name in self.captures:
                invalid('duplicate capture name')
            if len(name.encode('utf-16-le', 'surrogatepass')) // 2 > 62:
                invalid('capture name exceeds 62 UTF-16 units')
            self.captures[name] = group
        if behind:
            self.behind = group
        self.stack.extend((group, Group(parent=group)))
        self.target = None

    def alternate(self):
        self.target = None
        branch = self.stack.pop()
        branch.end_branch()
        branch.parent.alternation = True
        self.stack.append(Group(parent=branch.parent))

    def atom(self, minimum=1, maximum=1):
        self.target = self.stack[-1].atom(minimum, maximum)

    def quantifier(self, minimum, maximum):
        if self.behind is not None and maximum == -1:
            invalid('unbounded quantifier inside lookbehind')
        if self.target is None:
            invalid('quantifier has no preceding atom or group')
        self.stack[-1].quantifier(self.target, minimum, maximum)
        self.target = None

    def close(self):
        if len(self.stack) <= 2:
            invalid('unmatched closing parenthesis')
        self.stack.pop().end_branch()
        self.target = self.stack.pop()
        if self.target is self.behind:
            if self.target.maximum > 250:
                invalid('lookbehind exceeds 250 UTF-16 units')
            self.behind = None
        if self.target.lookaround:
            self.target.error_look_quant = True
        self.target.close()

    def reference(self, name):
        group = self.captures.get(str(name))
        if group is None:
            invalid('backreference must refer to an earlier capture')
        if not group.closed:
            invalid('backreference cannot refer to its own open capture')
        if self.behind is not None and group.maximum == -1:
            invalid('unbounded backreference inside lookbehind')
        self.atom(group.minimum, group.maximum)
        if group.blocked_reference(self.stack[-1]):
            self.references.add(str(name))

    def complete(self):
        if len(self.stack) != 2:
            invalid('unterminated group')
        self.stack.pop().end_branch()
        self.stack.pop().end()
        for name in sorted(self.references):
            message = self.captures[name].blocked_reference()
            if message:
                invalid(message + ': ' + name)

"""Reuse independent presentation values on passive display controls."""
from dataclasses import dataclass, field

from .fx import ENUMS
from .syntax import FxError


DISPLAY_FAMILIES = frozenset(('Label', 'ModernText', 'Rectangle', 'Circle', 'Star'))


@dataclass
class DisplayProperties:
    signature: tuple
    reusable: set
    values: dict = field(default_factory=dict)


def _independent(ref, raw, *, allow_self=True):
    if not isinstance(raw, str) or not raw.startswith('='):
        return isinstance(raw, (str, int, float, bool))
    try:
        expression = ref.runtime.fx.parse(raw)
    except FxError:
        return False

    def stable(node):
        if node.kind == 'literal':
            return True
        if node.kind == 'unary':
            return stable(node.children[0])
        if node.kind == 'binary' and node.value in ('&', '+', '-', '*', '/', '^'):
            return all(stable(child) for child in node.children)
        if node.kind == 'member' and node.children[0].kind == 'name':
            owner = node.children[0].value
            if owner in ENUMS:
                return True
            # Classic display defaults derive their colors from these paints.
            if allow_self and owner == 'Self' and node.value in ('Fill', 'Color', 'BorderColor'):
                return _independent(ref, ref.raw_property(node.value), allow_self=False)
        if node.kind == 'call':
            callee, *arguments = node.children
            if callee.kind == 'name' and callee.value in ('Blank', 'RGBA', 'Language'):
                return all(stable(argument) for argument in arguments)
            if callee.kind == 'name' and callee.value == 'Text' and len(arguments) == 1:
                return stable(arguments[0])
        return False

    return stable(expression)


def display_properties(ref, names):
    runtime = ref.runtime
    if ref.family not in DISPLAY_FAMILIES or ref.frames or ref.component or runtime.control_state.get(ref.path):
        return None
    # Evaluating a property's context can settle form data or table selection.
    if any(parent.family in ('Form', 'DataTable', 'ModernDataGrid') for parent in runtime.ancestors(ref)):
        return None

    control = ref.control
    automatic = bool(ref.automatic_parent)
    authored = tuple((name, type(value), value) for name, value in control.properties.items())
    signature = (control.kind, control.raw.get('Variant'), authored,
                 automatic, runtime.reactive.profile(), runtime.project.config.get('form_factor'))
    cached = runtime._preview_property_cache.get(ref.path)
    if cached is not None and cached.signature == signature:
        return cached

    layout = {'X', 'Y', 'Width', 'Height'} if automatic else set()
    if ref.family in ('Label', 'ModernText') and ref.raw_property('AutoHeight') != '=false':
        layout.add('Height')
    reusable = {name for name in names if name not in layout and _independent(ref, ref.raw_property(name))}
    cached = DisplayProperties(signature, reusable)
    runtime._preview_property_cache[ref.path] = cached
    return cached

"""Canvas focus contracts; requests are authoritative, DOM focus is presentation."""
import math
from decimal import Decimal
from .syntax import FxError

SET_FOCUS = frozenset(('Button','TextInput','ModernButton', 'Classic/Button', 'ModernTextInput','Classic/TextInput', 'ModernText', 'Label', 'Image'))
BOUNDARIES = frozenset(('Gallery', 'Form', 'CanvasComponent', 'Component', 'GroupContainer'))
INTERACTIVE = SET_FOCUS | frozenset(('TabList','Slider','Radio','ComboBox','DropDown','TextInput','CheckBox','Toolbar','ModernBadge','ModernInformationButton','ModernRating','FluentV8/Rating','ModernDataGrid','DataTable','ListBox','Classic/ListBox','Classic/ComboBox','Timer','Audio','Video','RichTextEditor','Classic/Toggle','Classic/Slider','Classic/DatePicker','Classic/CheckBox','Classic/Radio','Classic/DropDown','ModernNumberInput', 'ModernDatePicker', 'ModernDropdown', 'ModernRadio', 'ModernCombobox', 'ModernTabList', 'Toggle', 'ModernCheckbox', 'ModernSlider', 'ModernIcon', 'Classic/Icon', 'Gallery','Rectangle','Circle','Star'))


def validate_target(control):
    if control.family not in SET_FOCUS:
        raise FxError(f'SetFocus does not support {control.family}', 'Unsupported')
    if control.family == "Button":
        from .canvas_buttons import catalog
        s = catalog().get(control.version, {})
        if s.get("subscribed_functionalities", {}).get("supportSetFocus") != "true":
            raise FxError(f"SetFocus does not support {control.kind}", "Unsupported")
    parent = control.parent
    while parent:
        if parent.family in BOUNDARIES:
            raise FxError(f'SetFocus cannot target a control inside {parent.family}', 'Validation')
        parent = parent.parent


def available(runtime, ref):
    if ref.family == "Button" and ref.property("AcceptsFocus") is False:
        return False
    return all(a.property('Visible') is not False and a.property('DisplayMode') != 'Disabled'
               for a in [ref, *runtime.ancestors(ref)])


def tab_stop(ref):
    control = ref.control
    if ref.family in ('Text', 'FluentV8/Label'):
        value = ref.property('TabIndex')
        return value is not None and value >= 0
    if ref.family not in INTERACTIVE and ref.family != 'DatePicker':
        return False
    if ref.family in ('ModernIcon','ModernBadge'):
        from .icons import active
        return active(ref) and ref.property('DisplayMode') == 'Edit'
    if ref.family=='ModernInformationButton':return ref.property('DisplayMode')=='Edit'
    if ref.family=='FluentV8/Rating' and ref.property('AcceptsFocus') is False:return False
    if ref.family == 'Button' and ref.property('AcceptsFocus') is False:return False
    default = ref.family not in ('ModernText', 'Label', 'Image') or 'OnSelect' in control.properties or ref.raw_property('OnSelect') == '=Select(Parent)'
    if ref.family.startswith('Modern') and 'AcceptsFocus' in control.properties:
        value = ref.property('AcceptsFocus')
        if not isinstance(value, bool):
            raise FxError('AcceptsFocus requires a Boolean', 'Type')
        return value
    if 'TabIndex' in control.properties or ref.family in ('Classic/Icon','Label','Rectangle','Circle','Star'):
        value = ref.property('TabIndex')
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(float(value)) or value != int(value):
            raise FxError('TabIndex requires a finite integer', 'Type')
        return value >= 0  # Positive custom indices are retired and treated as zero.
    return default


def ordered_nodes(runtime, nodes, parent=None):
    """Keep the initial visual sequence while leaving paint order unchanged."""
    for i, node in enumerate(nodes):
        props = node.get('props', {})
        def coordinate(name):
            value = props.get(name, 0)
            return value if isinstance(value, (int, float)) and math.isfinite(value) else 0
        runtime.navigation_positions.setdefault(node['path'], (coordinate('Y'), coordinate('X'), i))
        node['paint_order'] = i
    if parent and parent.family == 'GroupContainer' and parent.control.raw.get('Variant') == 'AutoLayout':
        return nodes  # Flex layout determines visual order, including restored hidden children.
    return sorted(nodes, key=lambda node: runtime.navigation_positions[node['path']])

"""Power Fx interpreter for the supported canvas patterns.

Blank is None; language errors are FxError, never silently substituted for Blank.
Tables contain records, including a Value column for scalar table literals.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, DecimalException
from datetime import date, datetime, timezone, timedelta
import math
import re
import uuid

from .tables import SHAPING_FUNCTIONS, QUERY_FUNCTIONS, shape_columns, shaped_record, OrderedRecord, SourceRecord, derived_record
from .scopes import ScopeFrame
from .overloads import SINGLE_COLUMN_OVERLOADS, TEXT_OVERLOADS, ROUND_OVERLOADS, CALENDAR_OVERLOADS, single_column, empty_table_literal
from .numeric import NUMBERS, calculate, decimal_value, float_value, decimal_text, promote, rounded
from .power_math import MATH_FUNCTIONS,SCALAR_FLOAT_FUNCTIONS,FLOAT_FUNCTIONS,evaluate as math_evaluate
from .power_text import TEXT_OPERATIONS,NUMERIC_ARGUMENTS,from_units,evaluate as text_evaluate
from .temporal import Temporal, TEMPORAL_KINDS
from .store import DataSource
from .syntax import FxError, Node, Parser, call_name, walk
from .errors import ERROR_KINDS, error_name
from .locale_fx import EPOCH, date_diff, format_date, format_number, make_date, parse_datetime, parse_number, parse_time
from .json_fx import Dynamic, JsonNumber, parse_json, typed as typed_json, validate_json_type, convert_scalar, array as dynamic_array, field as dynamic_field, json_text


from .calendar_fx import CALENDAR_FUNCTIONS, MONTH_SHIFT_FUNCTIONS, calendar_number, shift_months
from .locale_tables import FUNCTIONS as LOCALE_TABLE_FUNCTIONS, evaluate as locale_table_evaluate

PURE_FUNCTIONS = set("If Switch IfError IsError IsBlankOrError Error Blank IsBlank IsEmpty Coalesce And Or Not Table Filter LookUp With ForAll AddColumns ShowColumns DropColumns RenameColumns SortByColumns Sort CountRows CountIf First Last FirstN LastN Index Distinct Sum Average Min Max Lower Upper Trim TrimEnds Left Right Mid Len StartsWith EndsWith Substitute Concatenate Concat Text Value Decimal Float IsNumeric Round RoundDown RoundUp Mod Abs Char GUID Today Now Year Month Day Weekday WeekNum ISOWeekNum Date DateAdd DateDiff DateValue DateTimeValue DateTime Time TimeValue Hour Minute Second User Language Param RGBA ColorValue ColorFade Defaults Choices Errors DataSourceInfo Type Sequence Find Split Boolean".split())
PURE_FUNCTIONS.add('Validate')
BEHAVIOR_FUNCTIONS = set("Set UpdateContext Clear ClearCollect Collect Patch Refresh Navigate Back Notify Reset Select SetFocus NewForm EditForm ViewForm ResetForm SubmitForm Remove RemoveIf Update UpdateIf".split())
BUILTINS = PURE_FUNCTIONS | BEHAVIOR_FUNCTIONS
PURE_FUNCTIONS.update(QUERY_FUNCTIONS | {"RecordOf"})
BUILTINS.update(QUERY_FUNCTIONS | {"RecordOf"})
PURE_FUNCTIONS.update({'ParseJSON','AsType','IsType','Column','ColumnNames'})
BEHAVIOR_FUNCTIONS.add('JSON')
BUILTINS.update(PURE_FUNCTIONS | BEHAVIOR_FUNCTIONS)
PURE_FUNCTIONS.update(MATH_FUNCTIONS)
BUILTINS.update(MATH_FUNCTIONS)
PURE_FUNCTIONS.update(TEXT_OPERATIONS)
BUILTINS.update(TEXT_OPERATIONS)
from .regex_fx import FUNCTIONS as REGEX_FUNCTIONS
PURE_FUNCTIONS.update(REGEX_FUNCTIONS)
BUILTINS.update(REGEX_FUNCTIONS)
from .html_fx import FUNCTIONS as HTML_FUNCTIONS, evaluate as html_evaluate
PURE_FUNCTIONS.update(HTML_FUNCTIONS)
BUILTINS.update(HTML_FUNCTIONS)
from .statistics_fx import FUNCTIONS as STATISTICS_FUNCTIONS, evaluate as statistics_evaluate
from .aggregates_fx import FUNCTIONS as AGGREGATE_FUNCTIONS, evaluate as aggregates_evaluate
PURE_FUNCTIONS.update(STATISTICS_FUNCTIONS)
BUILTINS.update(STATISTICS_FUNCTIONS)
from .counts_fx import FUNCTIONS as COUNT_FUNCTIONS, evaluate as counts_evaluate
PURE_FUNCTIONS.update(COUNT_FUNCTIONS)
BUILTINS.update(COUNT_FUNCTIONS)
PURE_FUNCTIONS.add('Proper')
BUILTINS.add('Proper')
PURE_FUNCTIONS.update({'Rand','RandBetween','Shuffle'})
BUILTINS.update({'Rand','RandBetween','Shuffle'})
PURE_FUNCTIONS.update(LOCALE_TABLE_FUNCTIONS)
BUILTINS.update(LOCALE_TABLE_FUNCTIONS)
PURE_FUNCTIONS.update(MONTH_SHIFT_FUNCTIONS)
BUILTINS.update(MONTH_SHIFT_FUNCTIONS)
ARITY = {
    'Rand':(0,0),'RandBetween':(2,2),'Shuffle':(1,1),
    'Count':(1,1),'CountA':(1,1),'CountRows':(1,1),
    "EncodeHTML":(1,1), "EncodeUrl":(1,1), "PlainText":(1,1),
    'IsMatch':(2,3),'Match':(2,3),'MatchAll':(2,3),
    'Dec2Hex':(1,2),'Pi':(0,0),'Atan2':(2,2),'Power':(2,2),'Log':(1,2),'Trunc':(1,1),
    'Type': (1, 1), 'RecordOf': (1, 1),
    'ParseJSON': (1,2), 'AsType': (2,2), 'IsType': (2,2), 'JSON': (1,2), 'Column': (2,2), 'ColumnNames': (1,1),
    'Search': (3, None), 'GroupBy': (3, None), 'Ungroup': (2, 2),
    "If": (2, None), "Switch": (3, None), "IfError": (2, None), "Coalesce": (1, None),
    "And": (1, None), "Or": (1, None), "Table": (0, None), "Filter": (2, None), "LookUp": (2, 3),
    "With": (2, 2), "ForAll": (2, 2), "AddColumns": (3, None), "ShowColumns": (2, None), "DropColumns": (2, None), "RenameColumns": (3, None), "SortByColumns": (2, None),
    "Sort": (2, 3), "CountIf": (2, None), "FirstN": (1, 2), "LastN": (1, 2), "Index": (2, 2),
    "Distinct": (2, 2), "Sum": (1, None), "Average": (1, None), "Min": (1, None), "Max": (1, None),
    "StdevP": (1, None), "VarP": (1, None),
    "Left": (2, 2), "Right": (2, 2), "Mid": (2, 3), "StartsWith": (2, 2), "EndsWith": (2, 2),
    "Substitute": (3, 4), "Replace": (4, 4), "Concatenate": (1, None), "Concat": (2, 3), "Text": (1, 3), "Value": (1, 2), "Decimal": (1, 2), "Float": (1, 2),
    "Round": (2, 2), "RoundDown": (2, 2), "RoundUp": (2, 2), "Mod": (2, 2), "GUID": (0, 1),
    "Today": (0, 0), "Now": (0, 0), "User": (0, 0), "Language": (0, 0), "Blank": (0, 0),
    "RGBA": (4, 4), "ColorFade": (2, 2), "Date": (3, 3), "DateAdd": (2, 3), "DateDiff": (2, 3), "Weekday": (1, 2), "WeekNum": (1, 2), "ISOWeekNum": (1, 1),
    "DateTime": (6, 7), "Time": (3, 4), "TimeValue": (1, 2), "DateValue": (1, 2), "DateTimeValue": (1, 2), "DataSourceInfo": (2, 3), "Choices": (1, 2), "Errors": (1, 2), "Validate": (3, 3),
    "Sequence": (1, 3), "Find": (2, 3), "Split": (2, 2), "Set": (2, 2), "UpdateContext": (1, 1),
    "Clear": (1, 1), "ClearCollect": (2, None), "Collect": (2, None), "Patch": (2, None), "Update": (3, 4), "UpdateIf": (3, None),
    "Navigate": (1, 3), "Back": (0, 1), "Notify": (1, 3), "Select": (1, 3), "SetFocus": (1, 1), "Remove": (2, None), "RemoveIf": (2, None),
}
ARITY.update({name: (0, 0) for name in LOCALE_TABLE_FUNCTIONS})
ARITY.update({name: (2, 2) for name in MONTH_SHIFT_FUNCTIONS})

from .enum_fx import EnumValue,VALUES as ENUM_VALUES,numeric as enum_numeric,consume as enum_consume,comparison as enum_comparison,concatenate_namespace,concatenated,namespace_values

# Enumerated values are data, not freely accepted namespace members.
ENUMS = {
    "RatingStep": ["Full", "Half"],
    "TabSize": ["Small", "Medium", "Large"],
    "TabListAlignment": ["Start", "Center", "End"],
    "TabListAppearance": ["Transparent", "Subtle", "SubtleCircular", "FilledCircular", "Underline", "Filled"],
    'Match': {k:v.backing for k,v in ENUM_VALUES['Match'].items()},
    'MatchOptions':{k:v.backing for k,v in ENUM_VALUES['MatchOptions'].items()},
    "RemoveFlags": {"All":"All"},
    'JSONFormat': {'Compact':'c','IndentFour':'4','IncludeBinaryData':'B','IgnoreBinaryData':'G','IgnoreUnsupportedTypes':'I','FlattenValueTables':'_'},
    "DecimalPrecision": {"Auto":"Auto", "0":0, "1":1, "2":2, "3":3},
    "DatePickerFormat": ["LongAbbreviated", "Short", "Long"],
    "DateTimeZone": ["Local", "UTC"],
    "StartOfWeek": {"Sunday":1,"Monday":2,"MondayZero":3,"Tuesday":12,"Wednesday":13,"Thursday":14,"Friday":15,"Saturday":16},
    "Appearance": ["Filled", "FilledDarker", "FilledLighter", "Outline", "Primary", "Inverted"],
    "SpinnerLabelPosition": ["Before", "After", "Above", "Below"],
    "ProgressColor": ["Brand", "Success", "Warning", "Error"],
    "ProgressThickness": ["Medium", "Large"], "ProgressShape": ["Rounded", "Square"],
    "SliderSize": ["Small", "Medium", "Large"],
    "DisplayMode": ["Edit", "Disabled", "View"], "FormMode": ["Edit", "New", "View"],
    "NotificationType": ["Error", "Success", "Warning", "Information"],
    "ScreenTransition": ["None", "Fade", "Cover", "UnCover", "CoverRight", "UnCoverRight"],
    "Font": ["Segoe UI", "Arial", "Calibri", "Verdana", "Georgia", "Open Sans", "Lato"],
    "FontWeight": ["Normal", "Semibold", "Bold", "Lighter"],
    "Align": ["Left", "Center", "Right", "Justify"], "VerticalAlign": ["Top", "Middle", "Bottom"],
    "LayoutDirection": ["Horizontal", "Vertical"], "Layout": ["Horizontal", "Vertical"],
    "LayoutAlignItems": ["Start", "Center", "End", "Stretch"],
    "LayoutJustifyContent": ["Start", "Center", "End", "SpaceBetween", "SpaceAround", "SpaceEvenly"],
    "LayoutOverflow": ["Hide", "Scroll"], "DropShadow": ["None", "Light", "Regular", "Semibold", "Bold", "ExtraBold"],
    "AlignInContainer": ["SetByContainer", "Start", "Center", "End", "Stretch"],
    "ValidationState": ["None", "Error"],
    "ButtonAppearance": ["Primary", "Secondary", "Outline", "Transparent", "Subtle"],
    "ButtonLayout": ["IconOnly", "TextOnly", "IconBefore", "IconAfter"],
    "TextMode": ["SingleLine", "MultiLine", "Password"], "TextInputType": ["Text", "SingleLine", "Multiline", "Password", "Search", "Email", "Telephone", "URL"],
    "TriggerOutput": ["Keypress", "FocusOut", "Delayed"],
    "TextInputCanvas": {"Type": {"Text": "Text", "Password": "Password", "Search": "Search"}},
    "ImagePosition": ["Fit", "Fill", "Stretch", "Center", "Tile"],
    "LoadingSpinner": ["None", "Controls", "Data"], "SortOrder": ["Ascending", "Descending"],
    "LinkAppearance": ['Default', 'Subtle'],
    "DataSourceInfo": ["MaxLength", "DisplayName", "Required", "MinValue", "MaxValue", "EditPermission", "CreatePermission", "DeletePermission", "ReadPermission", "AllowedValues"],
    "ErrorKind": ERROR_KINDS,
    "TimeUnit": ["Days", "Hours", "Minutes", "Seconds", "Milliseconds", "Months", "Quarters", "Years"],
    "DateTimeFormat": ["ShortDate", "LongDate", "ShortDateTime", "LongDateTime", "ShortDateTime24", "LongDateTime24", "ShortTime", "LongTime", "ShortTime24", "LongTime24", "UTC"],
    "Color": {"Transparent": "rgba(0,0,0,0)", "White": "#ffffff", "Black": "#000000", "Red": "#ff0000", "Blue": "#0000ff", "Gray": "#808080", "LightGray": "#d3d3d3"},
    "Live": ["Off","Polite","Assertive"], "Overflow": ["Hidden","Scroll"],
    "TextRole": ["Default","Heading1","Heading2","Heading3","Heading4"],
    "BorderStyle": ["None", "Solid", "Dashed", "Dotted"],
}
from .icons import CLASSIC as CLASSIC_ICONS, IconValue
from .colors import catalog as color_catalog
from .status_enums import BADGE_ENUMS
ENUMS.update({namespace:list(members) for namespace,members in BADGE_ENUMS.items()})
ENUMS['Color']=color_catalog()
ENUMS['Icon']={name:IconValue(name) for name in CLASSIC_ICONS}
ENUMS['IconStyle']=['Outline','Filled']
ENUMS['TextFormat']=['Text','Number']
from .canvas_dates import enum_values as canvas_date_enums
ENUMS['DatePickerCanvas'] = canvas_date_enums()
from .canvas_selectors import radio_enums
ENUMS['RadioGroupCanvas'] = radio_enums()
from .canvas_scalars import enums as scalar_enums
ENUMS['Slider'] = scalar_enums('Slider')
ENUMS['Toggle'] = scalar_enums('Toggle')
from .canvas_buttons import catalog as canvas_button_catalog
ENUMS['ButtonCanvas'] = next(iter(canvas_button_catalog().values()))['enum_values']
from .canvas_text import catalog as canvas_text_catalog
ENUMS['TextCanvas'] = canvas_text_catalog()['Text']['0.0.47']['enum_values']
from .canvas_tabs import catalog as canvas_tab_catalog
ENUMS['TabList'] = next(iter(canvas_tab_catalog().values()))['enum_values']
ENUMS['ListItemTemplate']=['Single','Double','Person']
ENUMS['VirtualKeyboardMode']=['Auto','Text','Numeric']
ENUMS = {k: ({v: v for v in values} if isinstance(values, list) else values) for k, values in ENUMS.items()}


@dataclass
class Context:
    host: object
    frames: list = field(default_factory=list)
    self_ref: object = None
    parent_ref: object = None
    item: dict | None = None
    behavior: bool = False
    stack: tuple = ()
    control_scope: dict = field(default_factory=dict)
    forall_depth: int = 0
    component_ref: object = None
    function_pure: bool = False
    parameter_types: dict = field(default_factory=dict)
    error_source: str = ""
    item_probe: object = None
    item_key: tuple | None = None
    query_scope: object = None
    formula_source: str = ""
    formula_origin: object = None

    def scope(self, values, **kwargs):
        if 'item' in kwargs and 'item_probe' not in kwargs:
            kwargs.update(item_probe=None,item_key=None)
        return replace(self, frames=[*self.frames, values], **kwargs)


def observe(value):
    """Consume a scalar/row error without inspecting unrelated record cells."""
    if isinstance(value, FxError):
        raise value
    return value


def capture(action):
    """Keep a language error as a cell value, preserving its source span."""
    try:
        return action()
    except FxError as error:
        return error


def table(value):
    observe(value)
    if isinstance(value, DataSource):
        return value.rows()
    if value is None:
        return []
    if not isinstance(value, list):
        raise FxError("Expected a table", "Validation")
    return value


def scalar(value):
    observe(value)
    return value.get("Value") if isinstance(value, dict) and len(value) == 1 and "Value" in value else value


def text(value):
    observe(value)
    if isinstance(value,EnumValue):return value.text()
    if isinstance(value, Dynamic):
        raw = value.value
        if isinstance(raw, (dict,list)):
            raise FxError('Cannot convert a Dynamic object/array to Text', 'InvalidArgument')
        return raw.lexeme if isinstance(raw,JsonNumber) else text(raw)
    if value is None:
        return ""
    if isinstance(value, Temporal):
        return format_date(value.value, {"Date": "ShortDate", "DateTime": "ShortDateTime", "Time": "ShortTime"}[value.kind], "en-US")
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (dict, list, DataSource)):
        raise FxError("Cannot convert a record or table to text")
    return str(value)


def number(value):
    observe(value)
    value=enum_numeric(value)
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, NUMBERS):
        raise FxError("Expected a number")
    return value


def truth(value):
    if isinstance(value,EnumValue):raise FxError("Enum values cannot be used as Boolean conditions","Type")
    observe(value)
    if isinstance(value, Dynamic):
        raw = value.value
        if isinstance(raw,bool):
            return raw
        if isinstance(raw,str) and raw.casefold() in ('true','false'):
            return raw.casefold() == 'true'
        if isinstance(raw,JsonNumber):
            return decimal_value(raw.lexeme) != 0
        raise FxError('Expected a Dynamic Boolean', 'InvalidArgument')
    if value is None:
        return False
    if not isinstance(value, bool):
        raise FxError("Expected a Boolean")
    return value


def date_value(value):
    observe(value)
    if isinstance(value, Temporal):
        return value.value
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), timezone.utc)
    try:
        v = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(v)
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)
    except ValueError:
        raise FxError(f"Invalid date {value!r}") from None


class Evaluator:
    def __init__(self, host):
        self.host = host
        self.cache = {}
        self.definitions = {}
        self.parse_errors = []
        self.node_types = {}

    def parse(self, source, scope_key=None):
        key = (source, scope_key, self.number_mode, self.host.environment.get("enum_mode","legacy"),self.host.environment.get("regex_mode","canvas"))
        if key not in self.cache:
            self.cache[key] = Parser(source).parse()
        return self.cache[key]

    def set_definitions(self, source):
        self.definition_source=source
        try:
            self.definitions, self.parse_errors = Parser(source or "").definitions()
        except FxError as error:
            self.definitions, self.parse_errors = {}, [error]
        functions = {n:d for n,d in self.definitions.items() if d.params is not None}
        calls = {n:{call_name(node.children[0]) for node in walk(d.body) if node.kind == "call"} & functions.keys() for n,d in functions.items()}
        def recursive(start, current, seen):
            return any(target == start or target not in seen and recursive(start, target, seen | {target}) for target in calls[current])
        self.recursive_functions = {n for n in functions if recursive(n, n, {n})}
        binder = getattr(self.host, "binder", None)
        if binder:
            binder.named.clear()
            binder.aliases.clear()
            binder.type_errors.clear()
            binder.nodes.clear()
            binder.node_refs.clear()
            binder.expression_owners.clear()
            binder.expression_roots.clear()
            self.node_types = binder.nodes
            self.host.invalidate()

    def bound_node(self, source, context=None):
        ctx = context or Context(self.host)
        # Equal source text can bind to different Parent/ThisItem/component
        # schemas. Keep its typed AST separate for each control/argument scope.
        from .binding import value_type
        frame_types = tuple((tuple((k, ctx.parameter_types.get(k, value_type(v)).cache_key()) for k, v in frame.items()),
                             tuple((k, value_type(v).cache_key()) for k, v in getattr(frame, 'sources', {}).items()),
                             getattr(frame, 'aliased', False), getattr(frame, 'open_schema', False)) for frame in ctx.frames)
        item_type = value_type(ctx.item)
        item_key = item_type.cache_key() if ctx.item is not None else None
        screen = self.host.screen_for(ctx.self_ref) if hasattr(self.host, 'screen_for') else ''
        scope_key = (getattr(ctx.self_ref, "path", None), frame_types, ctx.function_pure, item_key, screen) if ctx.self_ref or ctx.frames or ctx.function_pure or ctx.item is not None or screen else None
        node = self.parse(source, scope_key)
        binder = getattr(self.host, "binder", None)
        if binder and id(node) not in self.node_types:
            from .binding import BindScope, value_type, FxType
            def typed(v):
                if isinstance(v, DataSource):
                    return binder.globals.get(v.name, value_type(v))
                if hasattr(v, "control"):
                    return FxType("Control", name=v.name, control=v.control)
                return value_type(v)
            def typed_frame(frame):
                convert = lambda name, value: ctx.parameter_types.get(name, typed(value))
                return frame.typed(convert) if isinstance(frame, ScopeFrame) else {k: convert(k, v) for k, v in frame.items()}
            scope = BindScope(frames=[typed_frame(frame) for frame in ctx.frames],
                self_control=ctx.self_ref.control if ctx.self_ref else None,
                item=value_type(ctx.item), behavior=ctx.behavior, function_pure=ctx.function_pure,
                component=ctx.component_ref.control if ctx.component_ref else None, screen=screen)
            if ctx.control_scope:
                scope.frames.insert(0, {k: typed(v) for k, v in ctx.control_scope.items()})
            binder.infer(node, scope)
            self.node_types = binder.nodes
        return node

    def app_definition_origin(self,name):
        from .expressions import app_expression
        origin=app_expression(self.host,'Formulas','App.Formulas.'+name)
        return replace(origin,formula=self.definition_source,line=origin.line if origin.formula==self.definition_source else None)

    def evaluate(self, source, context=None):
        ctx = replace(context or Context(self.host),formula_source=source)
        try:return self.eval(self.bound_node(source, ctx), ctx)
        except FxError as error:
            raise ctx.formula_origin.locate(error) if ctx.formula_origin else error

    def resolve(self, name, ctx, global_only=False):
        if not global_only:
            for frame in reversed(ctx.frames):
                if name in frame:
                    if getattr(frame,'probe',None):
                        return self.host.reactive.leaf(('query-field',frame.probe_key,name),lambda:frame.probe(name),isolated=True)
                    if ctx.item_probe and frame[name] is ctx.item:
                        return self.host.reactive.leaf(ctx.item_key,ctx.item_probe,isolated=True)
                    return frame[name]
        if ctx.function_pure and name not in ENUMS:
            raise FxError(f"Component functions require {name} to be passed as an argument", "Name")
        if name == "Self":
            return ctx.self_ref
        if name == "Parent":
            return ctx.parent_ref
        if name == "ThisItem":
            return self.host.reactive.leaf(ctx.item_key,ctx.item_probe,isolated=True) if ctx.item_probe else ctx.item
        if name == "ThisRecord" and not any(getattr(frame, 'aliased', False) for frame in ctx.frames):
            if ctx.frames:
                frame=ctx.frames[-1]
                if getattr(frame,'probe',None):return self.host.reactive.leaf(('query-record',frame.probe_key),lambda:frame.probe('ThisRecord'),isolated=True)
                return frame.get('ThisRecord')
            return self.host.reactive.leaf(ctx.item_key,ctx.item_probe,isolated=True) if ctx.item_probe else ctx.item
        if name in ENUMS:
            return namespace_values(name,self.host.environment,ENUMS[name])
        if name in self.definitions:
            if ctx.component_ref:
                from .components import access_app_scope
                if not access_app_scope(self.host.project, ctx.component_ref):
                    return self.host.resolve(name, ctx, global_only)
            definition = self.definitions[name]
            if definition.alias:
                raise FxError(f"Type {name} cannot be used as a runtime value", "Type")
            if definition.params is not None:
                return definition
            if name in ctx.stack:
                raise FxError("Formula dependency cycle: " + " → ".join((*ctx.stack, name)), "Cycle")
            def load():
                if name in self.host.formula_cache:
                    return observe(self.host.formula_cache[name])
                try:
                    value = self.eval(definition.body, Context(self.host, stack=(*ctx.stack, name),error_source="App.Formulas."+name,formula_source=self.definition_source,formula_origin=self.app_definition_origin(name)))
                    self.host.formula_cache[name] = value
                    return value
                except FxError as error:
                    self.host.formula_cache[name] = error
                    raise
            return self.host.reactive.unit(('named',name),load,lambda:repr(definition.body),
                lambda:self.host.formula_cache.pop(name,None))
        return self.host.resolve(name, ctx, global_only)

    def member(self, base, name, ctx):
        observe(base)
        if isinstance(base, Dynamic):
            return dynamic_field(base,name)
        if base is None:
            return None
        if hasattr(base, "property"):
            return base.property(name, ctx)
        if isinstance(base, DataSource):
            base = base.rows()
        if hasattr(base, 'gallery_member'):
            try:
                return base.gallery_member(name)
            except KeyError:
                pass
        if isinstance(base, dict):
            if name in base:
                return observe(base[name])
            display = next((key for key, logical in getattr(base, 'logical_names', {}).items() if logical == name), None)
            if display in base:
                return observe(base[display])
            raise FxError(f"Unknown field {name}")
        if isinstance(base, list):
            return [row if isinstance(row, FxError) else {name: capture(lambda: self.member(row, name, ctx))} for row in base]
        raise FxError(f"Cannot access {name} on {type(base).__name__}")

    def eval(self, node, ctx):
        if node.kind=='table' and not ctx.behavior:
            from .query_reactivity import evaluate
            return observe(evaluate(self,node,ctx,lambda call_ctx:self._eval(node,call_ctx)))
        if node.kind=='call' and call_name(node.children[0]) not in BUILTINS and not ctx.behavior and self.host.reactive.frames:
            owner=ctx.self_ref.path if ctx.self_ref else ctx.component_ref.path if ctx.component_ref else ctx.formula_origin.owner if ctx.formula_origin else 'App'
            from .query_reactivity import identity
            key=('function-result',owner,call_name(node.children[0]),node.start,node.end,identity(self.host.reactive.frames[-1].key))
            return observe(self.host.reactive.project(key,lambda:self._eval(node,ctx)))
        return observe(self._eval(node, ctx))

    def capture(self, node, ctx):
        return capture(lambda: self.eval(node, ctx))

    def _eval(self, node, ctx):
        k, v, c = node.kind, node.value, node.children
        try:
            if k == "literal":
                return self.literal_number(node.numeric_literal) if node.numeric_literal is not None else v
            if k=='interpolate':
                typ=self.node_types.get(id(node))
                namespace=typ.name if typ and typ.kind=='Enum' else None
                values=[self.capture(child,ctx) for child in c]
                for child,value in zip(c,values):
                    child_type=self.node_types.get(id(child))
                    if child_type and child_type.kind in ('Record','Table','Control','Callable','Void','Icon') or isinstance(value,(dict,list,DataSource,IconValue)) or hasattr(value,'control') or callable(value):
                        raise FxError('Interpolation requires a text-coercible scalar','Type',child.start,child.end)
                if len(values)==1:
                    value=observe(values[0])
                    # Microsoft's IR returns a single interpolated child
                    # directly, retaining typed Blank and enum member identity.
                    return value if value is None or isinstance(value,EnumValue) and namespace else self.to_text(value)
                return self.scalar_overload('Concatenate',values,namespace)
            if k in ("name", "global"):
                return self.resolve(v, ctx, k == "global")
            if k == "member":
                typ = self.node_types.get(id(c[0]))
                if typ and typ.kind == 'Record' and not typ.open and v not in typ.fields and typ.aliases.get(v) not in typ.fields and v not in typ.virtual:
                    raise FxError(f'Unknown field {v}', 'Name')
                root=node;members=[]
                while root.kind=='member':
                    members.insert(0,root.value);root=root.children[0]
                if not ctx.behavior and root.kind in ('name','global','call'):
                    owner=ctx.self_ref.path if ctx.self_ref else ctx.component_ref.path if ctx.component_ref else ctx.formula_origin.owner if ctx.formula_origin else 'App'
                    root_name=call_name(root.children[0])+'(...)' if root.kind=='call' else root.value
                    scope_key=next((getattr(frame,'probe_key',None) for frame in reversed(ctx.frames) if root_name in frame),None)
                    key=('field',owner,root.kind,root_name,tuple(members),ctx.item_key)
                    if scope_key is not None:key+=('query-scope',scope_key)
                    if root.kind=='call':key+=(root.start,root.end,ctx.query_scope.key if ctx.query_scope else self.host.reactive.frames[-1].key if self.host.reactive.frames else None)
                    return self.host.reactive.project(key,lambda:self.member(self.eval(c[0],ctx),v,ctx))
                return self.member(self.eval(c[0], ctx), v, ctx)
            if k == "disambiguate":
                scope = call_name(c[0])
                for frame in reversed(ctx.frames):
                    if scope in getattr(frame, 'sources', {}):
                        probes=getattr(frame,'source_probes',{})
                        if scope in probes and not ctx.behavior:
                            probe,key=probes[scope]
                            return self.host.reactive.project(('query-disambiguation',key,v),lambda:self.member(probe(),v,ctx))
                        return self.member(frame.sources[scope], v, ctx)
                raise FxError(f"No record scope for {scope}[@{v}]")
            if k == "record":
                if len({name for name, _ in v}) != len(v):
                    raise FxError("Duplicate record field")
                return {name: self.capture(body, ctx) for name, body in v}
            if k == "table":
                result = []
                typ = self.node_types.get(id(node))
                for child in c:
                    value = self.capture(child, ctx)
                    child_type = self.node_types.get(id(child))
                    row = value if isinstance(value, dict) or child_type and child_type.kind == "Record" else {"Value": value}
                    result.append(capture(lambda: self.coerce(row, typ.row)) if typ and typ.row else row)
                return result
            if k == "unary":
                value = self.eval(c[0], ctx)
                if isinstance(value, Temporal) and v in ("-", "+"):
                    return value if v == "+" else Temporal(value.kind, EPOCH - (value.value - EPOCH))
                return {"!": lambda: not truth(value), "not": lambda: not truth(value),
                        "-": lambda: calculate("*", self.numeric_argument(value), Decimal(-1) if isinstance(value, Decimal) else -1), "+": lambda: self.numeric_argument(value), "%": lambda: calculate("/", self.numeric_argument(value), Decimal(100) if isinstance(value, Decimal) else 100)}[v]()
            if k == "alias":
                return self.eval(c[0], ctx)
            if k == "binary":
                if v == ";":
                    self.require_behavior(ctx)
                    a, b = self.capture(c[0], ctx), self.capture(c[1], ctx)
                    errors = [value for value in (a, b) if isinstance(value, FxError)]
                    if errors:
                        raise FxError.combine(errors)
                    return b
                a = self.eval(c[0], ctx)
                if v in ("and", "&&"):
                    return truth(a) and truth(self.eval(c[1], ctx))
                if v in ("or", "||"):
                    return truth(a) or truth(self.eval(c[1], ctx))
                b = self.eval(c[1], ctx)
                if v == "&":
                    typ=self.node_types.get(id(node));namespace=typ.name if typ and typ.kind=='Enum' else None
                    return concatenated(namespace,from_units(self.to_text(a)+self.to_text(b)))
                if v in ("in", "exactin"):
                    if isinstance(b, (DataSource, list)):
                        return any(self.equal(a, scalar(r)) for r in table(b))
                    return text(a) in text(b) if v == "exactin" else text(a).casefold() in text(b).casefold()
                if v == "=":
                    return self.equal(a, b)
                if v == "<>":
                    return not self.equal(a, b)
                if v in ("<", ">", "<=", ">="):
                    a, b = self.compare_values(a, b)
                    return {"<": lambda: a < b, ">": lambda: a > b, "<=": lambda: a <= b, ">=": lambda: a >= b}[v]()
                if v in ("+", "-") and (isinstance(a, Temporal) or isinstance(b, Temporal)):
                    return self.temporal_arithmetic(a, b, v, c)
                a, b = self.numeric_arguments([a, b])
                return calculate(v, a, b)
            if k == "call":
                name = call_name(c[0])
                if name in BUILTINS:
                    def load(call_ctx):
                        result = self.call(name, c[1:], call_ctx)
                        typ = self.node_types.get(id(node))
                        return self.coerce(result, typ) if typ and (typ.kind == 'Decimal' or name in ('If', 'Switch', 'Coalesce') and typ.kind in TEMPORAL_KINDS | {'Number', 'Decimal', 'Currency', 'Boolean', 'Text', 'Record', 'Table','Enum'}) else result
                    from .query_reactivity import FUNCTIONS,evaluate as query_result
                    return query_result(self,node,ctx,load) if name in FUNCTIONS else load(ctx)
                if name in self.definitions and self.definitions[name].params is not None:
                    d = self.definitions[name]
                    if name in self.recursive_functions:
                        raise FxError(f"Recursive function {name} is unsupported", "Unsupported")
                    if d.behavior:
                        self.require_behavior(ctx)
                        if ctx.function_pure:
                            raise FxError(f"Behavior function {name} is not allowed in a component function", "Validation")
                    if ctx.component_ref:
                        from .components import access_app_scope
                        if not access_app_scope(self.host.project, ctx.component_ref):
                            raise FxError(f"Component cannot access app function {name}; enable AccessAppScope or pass an event", "Name")
                    if d.returns == "Void" and not d.behavior:
                        raise FxError(f"{name}: Void requires a behavior function body", "Type")
                    if len({p for p, _ in d.params}) != len(d.params) or any(t in ("Void", "None") for _, t in d.params):
                        raise FxError(f"{name} has an invalid parameter signature", "Type")
                    if len(c) - 1 != len(d.params):
                        raise FxError(f"{name} expects {len(d.params)} arguments")
                    for typename in [t for _, t in d.params] + [d.returns]:
                        self.declared_contract(typename)
                    from .binding import function_compatible
                    for arg, (_, ptype) in zip(c[1:], d.params):
                        actual = self.node_types.get(id(arg))
                        expected = self.host.binder.declared_type(ptype)
                        if actual and not function_compatible(actual, expected):
                            raise FxError(f"{name}: expected {expected.describe()}, received {actual.describe()} (incompatible function schema)", 'Type')
                    values = [self.eval(n, ctx) for n in c[1:]]
                    for i, ((_, ptype), value) in enumerate(zip(d.params, values)):
                        values[i] = self.coerce_function(value, self.host.binder.declared_type(ptype), self.node_types.get(id(c[i + 1])))
                    if name in ctx.stack:
                        raise FxError(f"Recursive function {name} is unsupported", "Unsupported")
                    frame = dict(zip((p[0] for p in d.params), values))
                    if id(d.body) not in self.node_types:
                        from .binding import BindScope
                        self.host.binder.infer(d.body, BindScope(frames=[{p:self.host.binder.declared_type(t) for p,t in d.params}], behavior=d.behavior, function_pure=ctx.function_pure))
                    result = self.eval(d.body, Context(self.host, frames=[frame], stack=(*ctx.stack, name), behavior=d.behavior, function_pure=ctx.function_pure, forall_depth=ctx.forall_depth,error_source="App.Formulas."+name,formula_source=self.definition_source,formula_origin=self.app_definition_origin(name)))
                    if d.returns == "Void":
                        return None
                    return self.coerce_function(result, self.host.binder.declared_type(d.returns), self.node_types.get(id(d.body)))
                callback = self.eval(c[0], ctx)
                if callable(callback):
                    if getattr(callback, "behavior", True):
                        self.require_behavior(ctx)
                    if hasattr(callback, 'validate_arguments'):
                        callback.validate_arguments([self.node_types.get(id(arg)) for arg in c[1:]])
                    return callback([self.eval(n, ctx) for n in c[1:]])
                raise FxError(f"Unsupported function {name or '<expression>'}", "Unsupported")
            raise FxError(f"Unsupported AST node {k}", "Unsupported")
        except FxError as error:
            error=error.located(ctx.error_source)
            if not error.end:
                error.start,error.end=node.start,node.end
                error.span_source=ctx.error_source
            if ctx.formula_origin:error=ctx.formula_origin.locate(error)
            raise error from None
        except (ValueError, TypeError, IndexError, KeyError, OverflowError, ZeroDivisionError, AttributeError, DecimalException) as error:
            result=FxError(str(error), "Div0" if isinstance(error, ZeroDivisionError) else "Validation", node.start, node.end,source=ctx.error_source)
            raise ctx.formula_origin.locate(result) if ctx.formula_origin else result from None

    def equal(self, a, b):
        observe(a); observe(b)
        a,b=enum_comparison(a,b)
        if isinstance(a,Dynamic) or isinstance(b,Dynamic):
            from .binding import value_type
            if isinstance(a,Dynamic) and isinstance(b,Dynamic):
                a,b = a.value,b.value
                a = float_value(a.lexeme) if isinstance(a,JsonNumber) else a
                b = float_value(b.lexeme) if isinstance(b,JsonNumber) else b
                if isinstance(a,(dict,list)) or isinstance(b,(dict,list)):
                    raise FxError('Dynamic object equality requires typed conversion','InvalidArgument')
            else:
                target = value_type(b if isinstance(a,Dynamic) else a).kind
                if target in ('Blank','Error'):
                    target = 'Text'
                if isinstance(a,Dynamic):
                    a = convert_scalar(a,target,self)
                else:
                    b = convert_scalar(b,target,self)
        if isinstance(a, Temporal) or isinstance(b, Temporal):
            a, b = self.compare_values(a, b)
            return a == b
        if a is None:
            return b is None or b == "" or type(b) in NUMBERS and b == 0 or b is False
        if b is None:
            return self.equal(b, a)
        if type(a) is bool or type(b) is bool:
            if type(a) is not type(b):
                raise FxError("Incompatible types for equality")
        if isinstance(a, NUMBERS) and not isinstance(a, bool) and isinstance(b, NUMBERS) and not isinstance(b, bool):
            a, b = promote(a, b)
        return a == b

    @property
    def number_mode(self):
        return self.host.environment.get('number_mode', 'float')

    def literal_number(self, lexeme):
        if self.number_mode == 'decimal':
            return decimal_value(lexeme)
        # Keep exact small integer IDs while enforcing the Float range.
        value = float_value(lexeme)
        return int(lexeme) if not any(c in lexeme for c in '.eE') and abs(value) <= 2 ** 53 else value

    def enum_argument(self,value,namespace):
        from .enum_fx import CATALOG
        if self.host.environment.get('enum_mode')=='strong' and value is not None and not isinstance(value,EnumValue) and not CATALOG[namespace]['from_backing']:
            raise FxError(f'Expected {namespace} enum value','Type')
        return enum_consume(value,namespace)

    def numeric_argument(self, value, kind=None):
        observe(value)
        value=enum_numeric(value)
        kind = kind or self.number_mode
        if isinstance(value, Dynamic):
            return convert_scalar(value,'Decimal' if kind == 'decimal' else 'Float',self)
        if value is None:
            return Decimal(0) if kind == 'decimal' else 0.0
        if isinstance(value, NUMBERS) and not isinstance(value, bool) and kind == self.number_mode:
            return value
        return parse_number(enum_numeric(value), self.host.environment['language'], self.numeric_mode, kind)

    def numeric_arguments(self, values, promote_values=True):
        results = [capture(lambda: self.numeric_argument(value)) for value in values]
        errors = [value for value in results if isinstance(value, FxError)]
        if errors:
            raise FxError.combine(errors)
        if promote_values and any(isinstance(value, float) for value in results) and any(isinstance(value, Decimal) for value in results):
            return [float_value(value) for value in results]
        return results

    @property
    def numeric_mode(self):
        return self.host.environment.get('date_numeric_mode', 'canvas-milliseconds')

    def temporal(self, value, kind='DateTime', locale=None):
        observe(value)
        if value is None:
            return None
        locale = locale or self.host.environment['language']
        if isinstance(value, Temporal):
            return Temporal(kind, value.value)
        if isinstance(value, bool):
            raise FxError('A Boolean is not a date/time', 'InvalidArgument')
        if isinstance(value, NUMBERS):
            return Temporal.from_number(value, kind, self.numeric_mode)
        if kind == 'Time':
            return parse_time(value, locale)
        parsed = parse_datetime(value, locale)
        if parsed is None:
            return None
        if kind == 'Date':
            parsed = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
        return Temporal(kind, parsed)

    def to_text(self, value):
        if isinstance(value,EnumValue):return value.text()
        if isinstance(value, NUMBERS) and not isinstance(value, bool):
            from .locale_fx import locale
            return text(value).replace(".", locale(self.host.environment["language"])["decimal"])
        if isinstance(value, Temporal):
            return format_date(value.value, {'Date': 'ShortDate', 'DateTime': 'ShortDateTime', 'Time': 'ShortTime'}[value.kind], self.host.environment['language'])
        return text(value)

    def temporal_arithmetic(self, a, b, operator, nodes):
        # Arithmetic offsets are days in both profiles. Numeric conversion
        # functions use the host's explicit canvas/engine compatibility mode.
        for i, value in enumerate((a, b)):
            typ = self.node_types.get(id(nodes[i]))
            if value is None and typ and typ.kind in TEMPORAL_KINDS:
                if i == 0:
                    a = Temporal(typ.kind, EPOCH)
                else:
                    b = Temporal(typ.kind, EPOCH)
        if isinstance(a, Temporal) and isinstance(b, Temporal):
            if operator == '-':
                if a.kind == 'Time' and b.kind != 'Time':
                    raise FxError('Cannot subtract a date from a time')
                return (a.value - b.value).total_seconds() / 86400
            if a.kind != 'Time' and b.kind != 'Time':
                raise FxError('Cannot add two dates')
            kind = 'Time' if a.kind == b.kind == 'Time' else 'DateTime'
            return Temporal(kind, a.value + (b.value - EPOCH))
        if isinstance(a, Temporal):
            return Temporal(a.kind, a.value + timedelta(days=float(number(b)) * (1 if operator == '+' else -1)))
        if operator == '-':
            raise FxError('Subtracting a date/time from a number is unsupported', 'NotSupported')
        return Temporal(b.kind, b.value + timedelta(days=float(number(a))))

    def compare_values(self, a, b):
        observe(a); observe(b)
        a,b=enum_comparison(a,b,ordered=True)
        if isinstance(a,Dynamic):
            a = convert_scalar(a,'Text' if isinstance(b,str) else 'Number',self)
        if isinstance(b,Dynamic):
            b = convert_scalar(b,'Text' if isinstance(a,str) else 'Number',self)
        if isinstance(a, Temporal) or isinstance(b, Temporal):
            temporal = a if isinstance(a, Temporal) else b
            a = Temporal(temporal.kind, EPOCH) if a is None else a if isinstance(a, Temporal) else self.temporal(a, temporal.kind)
            b = Temporal(temporal.kind, EPOCH) if b is None else b if isinstance(b, Temporal) else self.temporal(b, temporal.kind)
            return a.value, b.value
        if a is None:
            a = "" if isinstance(b, str) else 0
        if b is None:
            b = "" if isinstance(a, str) else 0
        if isinstance(a, str) and isinstance(b, str):
            return a, b
        if isinstance(a, (date, datetime)) or isinstance(b, (date, datetime)):
            return date_value(a), date_value(b)
        return promote(number(a), number(b))

    def require_behavior(self, ctx):
        if not ctx.behavior:
            raise FxError("Behavior functions are not allowed in a value property", "Validation")

    def column(self, node, ctx):
        if node.kind in ("name", "global"):
            return node.value
        value = self.eval(node, ctx)
        if not isinstance(value, str):
            raise FxError("Expected column name")
        return value

    def query_rows(self,node,source,ctx):
        from .query_reactivity import rows
        return rows(self,node,source,ctx)

    def query_row(self,source,row,formula,ctx,index=None):
        from .query_reactivity import row_formula
        return row_formula(self,source,row,formula,ctx,index)

    def row_context(self, node, row, ctx):
        source_type = self.node_types.get(id(node))
        row_type = source_type.row if source_type and source_type.kind == 'Table' else source_type if source_type and source_type.kind == 'Record' else None
        fields = row_type.fields if row_type else {}
        aliases = {alias:row.get(display) for alias,display in row_type.aliases.items()} if isinstance(row,dict) and row_type else {}
        if isinstance(row,dict):
            aliases.update({internal: row.get(display) for display, internal in getattr(row, 'logical_names', {}).items()})
        frame = ScopeFrame({**{k: row if isinstance(row, FxError) else None for k in fields}, **aliases, **(row if isinstance(row, dict) else {}), "ThisRecord": row})
        if node.kind == "alias":
            frame = ScopeFrame({self.column(node.children[1], ctx): row}, aliased=True)
            node = node.children[0]
        source = call_name(node)
        previous = next((f.sources for f in reversed(ctx.frames) if getattr(f, 'sources', None)), {})
        frame.sources = {**previous, **({source: row} if source else {})}
        # Query functions establish ThisRecord, while ThisItem continues to
        # identify the surrounding gallery/form item even inside nested LookUp.
        return ctx.scope(frame)

    def check_type(self, value, typename, ctx):
        if typename in self.definitions and self.definitions[typename].alias:
            self.check_function_contract(value, self.declared_contract(typename), ctx)
            return
        if value is None or isinstance(value, FxError) or typename in (None, "None", "Void"):
            return
        if typename in TEMPORAL_KINDS:
            if not isinstance(value, Temporal) or value.kind != typename and not (typename == 'DateTime' and value.kind in ('Date', 'Time')):
                raise FxError(f"Expected {typename}")
            return
        types = {"Text": str, "Boolean": bool, "Number": NUMBERS, "Decimal": NUMBERS, "Float": NUMBERS,
                 "Date": (str, date), "DateTime": (str, datetime), "GUID": str, "Color": str, "Image": str}
        types.update({"Table": (list, DataSource), "Record": dict, "Dynamic":Dynamic})
        if typename in types:
            if not isinstance(value, types[typename]) or typename in ("Number", "Decimal", "Float") and isinstance(value, bool):
                raise FxError(f"Expected {typename}")
            return
        raise FxError(f"Unsupported type {typename}", "Unsupported")

    def declared_contract(self, typename, *, component=False):
        typ = (self.host.binder.component_declared_type if component else self.host.binder.declared_type)(typename)
        def incomplete(t):
            return t.kind == "Unknown" or any(incomplete(v) for v in t.fields.values()) or t.row is not None and incomplete(t.row)
        if incomplete(typ):
            error=self.host.binder.type_errors.get(typename)
            if error:raise self.app_definition_origin(typename).locate(error)
            raise FxError(f"Invalid type {typename}", "Type")
        return typ

    def check_function_contract(self, value, typ, ctx):
        if value is None or isinstance(value, FxError):
            return
        if typ.kind == "Record":
            if not isinstance(value, dict):
                raise FxError("Expected a record")
            for name, field in value.items():
                if name not in typ.fields:
                    if not typ.open:
                        raise FxError(f"Unexpected typed field {name}", "Type")
                else:
                    self.check_function_contract(field, typ.fields[name], ctx)
        elif typ.kind == "Table":
            for row in table(value):
                self.check_function_contract(row, typ.row or self.host.binder.declared_type('Record'), ctx)
        else:
            self.check_type(value, typ.kind, ctx)

    def mapped_record(self, value, typ):
        if not typ.aliases:
            return value
        from .mutations import canonical_fields
        logical = {display:internal for internal,display in typ.aliases.items()}
        normalized = canonical_fields(value,SourceRecord({key:None for key in typ.physical_fields()},logical))
        return derived_record(value,normalized) if isinstance(value,(SourceRecord,OrderedRecord)) else SourceRecord(normalized,logical)

    def coerce(self, value, typ):
        if typ and typ.kind=="Enum":
            if value is None or isinstance(value,FxError):return value
            if isinstance(value,EnumValue) and value.namespace==typ.name:return value
            from .enum_fx import CATALOG
            if CATALOG[typ.name]["from_backing"] and isinstance(value,str):return EnumValue(typ.name,"CalculatedOptionSetValue",value)
            raise FxError(f"Cannot coerce to {typ.name}","Type")
        observe(value)
        if value is None or typ is None or typ.kind in ("Blank", "Unknown", "Error", "Void"):
            return value
        if isinstance(value,Dynamic) and typ.kind in ('Text','Number','Decimal','Boolean'):
            return convert_scalar(value,typ.kind,self)
        if typ.kind == "Record":
            if not isinstance(value, dict):
                raise FxError("Cannot coerce value to a record", "InvalidArgument")
            value = self.mapped_record(value,typ)
            return derived_record(value, {**value, **{key: capture(lambda: self.coerce(value.get(key), field)) for key, field in typ.physical_fields().items()}})
        if typ.kind == "Table":
            return [capture(lambda: self.coerce(row, typ.row)) for row in table(value)]
        if typ.kind == "Text":
            return self.to_text(value)
        if typ.kind in TEMPORAL_KINDS:
            return self.temporal(value, typ.kind)
        if typ.kind in ('Number', 'Decimal', 'Currency'):
            kind = self.number_mode if typ.kind == 'Currency' else 'decimal' if typ.kind == 'Decimal' else 'float'
            return parse_number(enum_numeric(value), self.host.environment['language'], self.numeric_mode, kind)
        if typ.kind == "Boolean":
            if type(value) in NUMBERS:
                return value != 0
            if isinstance(value, str) and value.casefold() in ("true", "false"):
                return value.casefold() == "true"
            return truth(value)
        return value

    def coerce_function(self, value, typ, actual=None, *, restrictive=True):
        """Normalize callable/data contracts without observing aggregate cells.

        Record-to-table conversion and missing fields are supported, while
        extra fields remain errors for app functions. Scalar failures in records
        and tables stay in their cells until the function reads those cells.
        """
        from .binding import function_compatible, value_type
        if actual and not function_compatible(actual, typ, restrictive):
            policy = 'function schema' if restrictive else 'component contract'
            raise FxError(f"Expected {typ.describe()}, received {actual.describe()} (incompatible {policy})", 'Type')
        observe(value)
        if value is None:
            return None
        if typ.kind == 'Record':
            if not isinstance(value, dict):
                raise FxError('Expected a record', 'Type')
            value = self.mapped_record(value,typ)
            fields = typ.physical_fields()
            extra = set(value) - fields.keys()
            if extra and not typ.open and restrictive:
                raise FxError(f'Unexpected typed field {next(iter(extra))}', 'Type')
            return derived_record(value, {**value, **{
                key: capture(lambda: self.coerce_function(value.get(key), field, actual.fields.get(key) if actual else None, restrictive=restrictive))
                for key, field in fields.items()
            }})
        if typ.kind == 'Table':
            if not isinstance(value, (list, dict, DataSource)):
                raise FxError('Expected a table or record', 'Type')
            row_type = actual.row if actual and actual.kind == 'Table' else actual
            return [capture(lambda: self.coerce_function(row, typ.row, row_type, restrictive=restrictive)) for row in ([value] if isinstance(value, dict) else table(value))]
        if isinstance(value, Dynamic) and typ.kind != 'Dynamic':
            return convert_scalar(value, typ.kind, self)
        if typ.kind == 'Date' and isinstance(value, Temporal) and value.kind != 'Date':
            return Temporal('Date', value.value.replace(hour=0, minute=0, second=0, microsecond=0))
        # GUID and Color use string payloads in this runtime. Their bound type
        # distinguishes a Color from arbitrary text; GUID/Text is a V1 identity
        # conversion (explicit GUID() remains the validating constructor).
        if typ.kind in ('Image', 'Media') and isinstance(value,str):
            from .json_fx import Media
            if isinstance(value, Media) and value.media_kind != typ.kind:
                raise FxError(f'Expected {typ.describe()}, received {value.media_kind}', 'Type')
            return value if isinstance(value,Media) else Media(value, kind=typ.kind)
        if typ.kind == 'Screen':
            if not hasattr(value, 'control') or value.control.family != 'Screen':
                raise FxError('Expected a Screen reference', 'Type')
            return value
        if typ.kind in ('GUID', 'Color') and isinstance(value, str):
            if typ.kind == 'GUID' or actual and actual.kind == 'Color':
                return value
        if not function_compatible(value_type(value), typ, restrictive):
            raise FxError(f'Expected {typ.describe()}, received {value_type(value).describe()}', 'Type')
        return self.coerce(value, typ)

    def check_contract(self, value, typ):
        if value is None or isinstance(value, FxError) or typ.kind in ("Unknown", "Blank", "Void"):
            return
        if typ.kind == "Record":
            if not isinstance(value, dict):
                raise FxError("Expected a record")
            for name, field in typ.physical_fields().items():
                if name not in value:
                    raise FxError(f"Missing typed field {name}")
                self.check_contract(value[name], field)
        elif typ.kind == "Table":
            for row in table(value):
                self.check_contract(row, typ.row)
        else:
            self.check_type(value, typ.kind, Context(self.host))

    def call(self, name, args, ctx):
        e = lambda i: self.eval(args[i], ctx)
        n = len(args)
        minimum, maximum = ARITY.get(name, (1, 1))
        if n < minimum or maximum is not None and n > maximum:
            raise FxError(f"{name} expects {minimum}" + (f"–{maximum}" if maximum != minimum and maximum else "+" if maximum is None else "") + " arguments")
        if name in LOCALE_TABLE_FUNCTIONS:
            language = self.host.reactive.leaf(('environment', 'language'),
                lambda: self.host.environment['language'])
            return locale_table_evaluate(name, language)
        if name in REGEX_FUNCTIONS:
            from .regex_fx import evaluate
            return evaluate(self,name,args,ctx)
        if name in ('ParseJSON','AsType','IsType'):
            typ = self.host.binder.type_spec(args[1]) if n > 1 else None
            if typ:
                validate_json_type(typ)
            value = parse_json(e(0)) if name == 'ParseJSON' else e(0)
            if name == 'IsType':
                if value is None:
                    return False
                try:
                    typed_json(value,typ,self)
                    return True
                except FxError as error:
                    if error.kind == 'InvalidArgument':
                        return False
                    raise
            return typed_json(value,typ,self) if typ else value
        if name in ('Column','ColumnNames'):
            value = e(0)
            if value is None:
                return None
            if name == 'Column':
                column = e(1)
                if not isinstance(column,str):
                    raise FxError('Column requires a Text field name','Type')
                return dynamic_field(value,column)
            if not isinstance(value,Dynamic) or not isinstance(value.value,dict):
                raise FxError('ColumnNames requires a Dynamic object','InvalidArgument')
            return [{'Value':key} for key in value.value]
        if name == 'JSON':
            self.require_behavior(ctx)
            value = e(0)
            if isinstance(value,DataSource):
                value = table(value)
            flags=e(1) if n>1 else ''
            if isinstance(flags,EnumValue):
                if flags.namespace!='JSONFormat':raise FxError('Expected JSONFormat enum value','Type')
                flags=flags.backing
            elif self.host.environment.get('enum_mode')=='strong' and flags is not None and n>1:raise FxError('Expected JSONFormat enum value','Type')
            return json_text(value,'' if flags is None else flags,self.node_types.get(id(args[0])))
        if name == 'Patch':
            from .patch import execute
            result = execute(self.host, args, ctx, self)
            if ctx.behavior:
                self.host.sync_reset_properties()
            return result
        if name in BEHAVIOR_FUNCTIONS:
            self.require_behavior(ctx)
            if ctx.forall_depth and name in ("UpdateContext", "Clear", "ClearCollect"):
                raise FxError(f"{name} is not allowed within ForAll")
            result = self.host.behavior(name, args, ctx, self)
            observer = getattr(self.host, 'sync_reset_properties', None)
            if observer:
                observer()
            return result
        if name == "If":
            for i in range(0, n - 1, 2):
                condition = e(i)
                if isinstance(condition, NUMBERS) and not isinstance(condition, bool):
                    condition = condition != 0
                if truth(condition):
                    return e(i + 1)
            return e(n - 1) if n % 2 else None
        if name == "Switch":
            value = e(0)
            for i in range(1, n - 1, 2):
                if self.equal(value, e(i)):
                    return e(i + 1)
            return e(n - 1) if n % 2 == 0 else None
        if name == "IfError":
            result = None
            typ = self.node_types.get(id(args[n - 1 if n % 2 else n - 2]))
            for i in range(0, n - 1, 2):
                try:
                    result = e(i)
                except FxError as error:
                    from .app_errors import scope_records
                    rows=scope_records(error,ctx.error_source)
                    return self.coerce(self.eval(args[i + 1], ctx.scope({"FirstError":rows[0],"AllErrors":rows})), typ)
            return self.coerce(e(n - 1) if n % 2 else result, typ)
        if name in ("IsError", "IsBlankOrError"):
            try:
                result = e(0)
                return result is None or result == "" if name == "IsBlankOrError" else False
            except FxError:
                return True
        if name == "Error":
            error = e(0)
            records = error if isinstance(error, list) else [error]
            if any(not isinstance(record, dict) for record in records):
                raise FxError("Error requires an error record or table")
            records=[row for row in records if row]
            if not records:return None
            errors=[]
            for record in records:
                kind=enum_numeric(observe(record.get('Kind')))
                if isinstance(kind,bool) or not isinstance(kind,(int,float,Decimal)) or not math.isfinite(float(kind)) or kind!=int(kind):
                    raise FxError('Error requires an integer numeric Kind','InvalidArgument')
                source,observed=observe(record.get('Source')),observe(record.get('Observed'))
                if any(value is not None and not isinstance(value,str) for value in (source,observed)):
                    raise FxError('Error Source and Observed require Text','InvalidArgument')
                details=observe(record.get('Details'))
                if details is not None and not isinstance(details,dict):raise FxError('Error Details requires a Record','InvalidArgument')
                errors.append(FxError(text(record.get('Message','Power Fx error')),error_name(int(kind)),source=source or '',observed=observed or '',details=details))
            raise FxError.combine(errors)
        if name == "Blank":
            return None
        if name == "IsBlank":
            value = e(0)
            return value is None or value == ""
        if name == "IsEmpty":
            value = e(0)
            return len(dynamic_array(value) if isinstance(value,Dynamic) else table(value)) == 0
        if name == "Coalesce":
            for i in range(n):
                value = e(i)
                if value is not None and value != "":
                    return value
            return None
        if name == "And":
            return all(truth(e(i)) for i in range(n))
        if name == "Or":
            return any(truth(e(i)) for i in range(n))
        if name == "Not":
            return not truth(e(0))
        if name == "With":
            record = e(0)
            if record is not None and not isinstance(record, dict):
                raise FxError("With expects a record")
            return self.eval(args[1], self.row_context(args[0], record, ctx))
        if name == "Table":
            if n == 1 and self.node_types.get(id(args[0])) and self.node_types[id(args[0])].kind == 'Dynamic':
                value = e(0)
                if isinstance(value,Dynamic):
                    return [{'Value':item} for item in dynamic_array(value)]
            result = []
            binder = getattr(self.host, "binder", None)
            from .binding import BLANK, OPEN_RECORD
            row_type = BLANK
            if binder:
                for arg in args:
                    typ = self.node_types.get(id(arg), BLANK)
                    row_type = binder.table_union(row_type, typ.row or OPEN_RECORD if typ.kind == "Table" else typ, arg)
            for i in range(n):
                value = self.capture(args[i], ctx)
                if isinstance(value, FxError):
                    typ = self.node_types.get(id(args[i]))
                    if typ and typ.kind == "Table":
                        raise value
                    result.append(value)
                    continue
                if isinstance(value, (list, DataSource)):
                    result.extend(table(value))
                elif isinstance(value, dict):
                    result.append(value)
                elif value is None:
                    typ = self.node_types.get(id(args[i]))
                    if not typ or typ.kind != "Table":
                        result.append(None)  # Typed blank tables contribute zero rows.
                else:
                    raise FxError("Table expects records or tables")
            columns = {k for row in result if isinstance(row, dict) for k in row}
            return [self.coerce(derived_record(row,{k: row.get(k) for k in columns}), row_type) if isinstance(row, dict) else row for row in result]
        if name in SHAPING_FUNCTIONS:
            source = e(0)
            if name in ('AddColumns', 'RenameColumns') and n % 2 == 0:
                raise FxError(f'{name} expects column/formula pairs' if name == 'AddColumns' else 'RenameColumns expects old/new column pairs', 'Validation')
            is_record = isinstance(source, dict)
            rows = [source] if is_record else self.query_rows(args[0],source,ctx)
            typ = self.node_types.get(id(args[0]))
            row_type = typ.row if typ and typ.kind == 'Table' else typ if typ and typ.kind == 'Record' else None
            concrete_rows = [row for row in rows if isinstance(row, dict)]
            fields = (set(row_type.physical_fields()) if row_type else set()) | {key for row in concrete_rows for key in row}
            from .grouping_fx import aliases_for
            aliases = aliases_for(fields, row_type.aliases if row_type else {},
                                  *({logical: physical for physical, logical in getattr(row, 'logical_names', {}).items()}
                                    for row in concrete_rows))
            names = args[1::2] if name == 'AddColumns' else args[1:]
            operations = shape_columns(name, fields, names, bool(row_type and row_type.open and not concrete_rows), aliases)
            if source is None:
                return None
            output = []
            for index,row in enumerate(rows):
                if row is None or isinstance(row, FxError):
                    output.append(row)
                    continue
                if not isinstance(row, dict):
                    raise FxError('Expected record rows', 'Validation')
                if name == 'AddColumns':
                    new = row.copy()
                    row_ctx = self.row_context(args[0], row, ctx)
                    for (_, col), formula in zip(operations, args[2::2]):
                        new[col] = capture(lambda:self.query_row(args[0],row,formula,ctx,index))
                elif name == 'ShowColumns':
                    new = {old: capture(lambda: self.member(row, old, ctx)) for old, _ in operations}
                elif name == 'DropColumns':
                    dropped = {old for old, _ in operations}
                    new = {key: value for key, value in row.items() if key not in dropped}
                else:
                    renamed = dict(operations)
                    new = {renamed.get(key, key): value for key, value in row.items()}
                output.append(shaped_record(row, new, operations, name))
            return output[0] if is_record else output
        if name == 'Search':
            from .search_fx import evaluate
            return evaluate(self, args, ctx)
        if name in ('GroupBy', 'Ungroup'):
            from .grouping_fx import evaluate
            return evaluate(self, name, args, ctx)
        if name in STATISTICS_FUNCTIONS:
            return statistics_evaluate(self, name, args, ctx)
        if name in AGGREGATE_FUNCTIONS:
            return aggregates_evaluate(self, name, args, ctx)
        if name in COUNT_FUNCTIONS:
            return counts_evaluate(self,name,args,ctx)
        if name in ('Filter', 'LookUp'):
            from .queries_fx import evaluate
            return evaluate(self, name, args, ctx)
        if name in ("ForAll", "Concat", "Distinct", "Sort"):
            source = e(0)
            rows = dynamic_array(source) if name == 'ForAll' and isinstance(source,Dynamic) else self.query_rows(args[0],source,ctx)
            if name == "Sort":
                direction = self.enum_argument(e(2),"SortOrder") if n > 2 else "Ascending"
                if source is None:
                    return None
                return [row for _,row in self.sort_rows(list(enumerate(rows)), lambda pair: self.query_row(args[0],pair[1],args[1],ctx,pair[0]), direction)]
            iteration_ctx = replace(ctx, forall_depth=ctx.forall_depth + 1) if name == "ForAll" else ctx
            values = [capture(lambda: self.query_row(args[0],row,args[1],iteration_ctx,index)) for index,row in enumerate(rows)]
            errors = [value for value in values if isinstance(value, FxError)]
            if errors:
                raise FxError.combine(errors)
            if name == "ForAll":
                errors=[value for value in values if isinstance(value,FxError)]
                if errors:raise FxError.combine(errors)
                result = []
                for value in values:
                    if value is None:
                        continue
                    result.extend(value if isinstance(value, list) else [value if isinstance(value, dict) else {"Value": value}])
                return result
            if name == "Distinct":
                result = []
                for value in values:
                    if not any(self.equal(value, scalar(row)) for row in result):
                        result.append({"Value": value})
                return result
            if name == "Concat":
                return from_units((text(e(2)) if n > 2 else "").join(text(v) for v in values))
        if name == "SortByColumns":
            source = e(0)
            rows = table(source).copy()
            if n == 3:
                order = e(2)
                typ = self.node_types.get(id(args[2]))
                if isinstance(order, (list, DataSource)) or typ and typ.kind == 'Table':
                    column = self.sort_column(args[1], ctx, args[0], rows)
                    values = []
                    for row in table(order):
                        observe(row)
                        if row is None:
                            continue
                        if not isinstance(row, dict) or len(row) != 1:
                            raise FxError('Sort order must be a single-column table', 'Validation')
                        value = observe(next(iter(row.values())))
                        if value is None:
                            continue
                        self.sort_key(value)
                        if any(self.equal(value, prior) for prior in values):
                            raise FxError('Sort order table contains duplicate values', 'InvalidArgument')
                        values.append(value)
                    if source is None:
                        return None
                    return self.sort_rows(rows, lambda row: self.member(row, column, ctx), order_values=values)
            pairs, i = [], 1
            while i < n:
                column = self.sort_column(args[i], ctx, args[0], rows)
                direction = e(i + 1) if i + 1 < n else "Ascending"
                if isinstance(direction, (list, dict, DataSource)):
                    raise FxError('Sort order tables require exactly one column', 'Validation')
                pairs.append((column, self.enum_argument(direction,"SortOrder") if i+1<n else direction)); i += 2
            if source is None:
                return None
            for column, direction in reversed(pairs):
                rows = self.sort_rows(rows, lambda row: self.member(row, column, ctx), direction)
            return rows
        if name in ("First", "Last", "FirstN", "LastN", "Index"):
            source = e(0)
            count = int(self.numeric_argument(e(1))) if n > 1 else 1
            if source is None:
                return None
            is_dynamic = isinstance(source,Dynamic)
            rows = dynamic_array(source) if is_dynamic else table(source)
            if name == "First":
                return rows[0] if rows else None
            if name == "Last":
                return rows[-1] if rows else None
            if name == "Index":
                if count < 1 or count > len(rows):
                    raise FxError("Index is outside the table", "InvalidArgument")
                return rows[count - 1]
            result = rows[:max(count, 0)] if name == "FirstN" else rows[-count:] if count > 0 else []
            return Dynamic([row.value if isinstance(row,Dynamic) else None for row in result]) if is_dynamic else result
        if name == 'Errors':
            source = e(0)
            if not isinstance(source, DataSource) or args[0].kind not in ('name','global'):
                raise FxError('Errors requires a direct local data source', 'Type')
            from .data_errors import rows
            return rows(source.store, source.name, e(1) if n > 1 else None, filtered=n > 1)
        if name == 'Choices':
            if args[0].kind != 'member' or args[0].children[0].kind not in ('name', 'global') or args[0].children[0].value not in self.host.store.definitions:
                raise FxError('Choices requires a direct data source column', 'Validation')
            source = self.eval(args[0].children[0], ctx)
            if not isinstance(source, DataSource):
                raise FxError("Choices requires a data source column")
            rows = source.store.choices(source.name, args[0].value, self.host.people)
            if n == 2:
                query = e(1)
                if query is not None and not isinstance(query, str):
                    raise FxError('Choices text filter requires Text', 'Type')
                if query:
                    rows = [row for row in rows if text(row.get('DisplayName', row.get('Value', ''))).lower().startswith(query.lower())]
            return rows
        if name == 'Validate':
            from .validation import evaluate
            return evaluate(self, args, ctx)
        if name == 'DataSourceInfo':
            from .datasource_info import evaluate
            return evaluate(self, args, ctx)
        if name == 'Defaults':
            source = e(0)
            from .patch import defaults
            return defaults(self.host, args[0], ctx, self, source)
        if name in ("User", "Language", "Param", "Today", "Now"):
            env = self.host.environment
            if name == "User":
                return self.host.reactive.leaf(('environment','user'),lambda:self.host.environment['user'])
            if name == "Language":
                return self.host.reactive.leaf(('environment','language'),lambda:self.host.environment['language'])
            if name == "Param":
                key=text(e(0))
                return self.host.reactive.leaf(('parameter',key),lambda:self.host.environment.get('parameters',{}).get(key))
            self.host.reactive.volatile()
            self.host.reactive.leaf(('environment','clock'),lambda:(self.host.environment.get('clock'),getattr(self.host,'timer_elapsed',0)))
            from .timers import clock as timer_clock
            clock = timer_clock(self.host) if getattr(self.host,"timer_elapsed",0)>0 else date_value(env["clock"]) if env.get("clock") else datetime.now(timezone.utc)
            return Temporal("Date", clock.replace(hour=0, minute=0, second=0, microsecond=0)) if name == "Today" else Temporal("DateTime", clock)
        if name in ('Rand','RandBetween','Shuffle'):
            from .volatile_fx import evaluate
            return evaluate(name,[self.capture(arg,ctx) for arg in args],self)
        if name in ("Type", "RecordOf"):
            raise FxError(f"{name} is only valid in a type declaration")
        if name in SINGLE_COLUMN_OVERLOADS:
            return self.single_column_call(name, args, ctx)
        if name in HTML_FUNCTIONS:
            return self.scalar_overload(name,[self.capture(arg,ctx) for arg in args])
        if name == 'Split':
            return self.scalar_overload(name,[self.capture(arg,ctx) for arg in args])
        if name in SCALAR_FLOAT_FUNCTIONS:
            return self.scalar_overload(name,[self.capture(arg,ctx) for arg in args])
        if name in MONTH_SHIFT_FUNCTIONS:
            from .binding import DATETIME, NUMBER, function_compatible
            for arg, expected in zip(args, (DATETIME, NUMBER)):
                actual = self.node_types.get(id(arg))
                if actual and not function_compatible(actual, expected):
                    raise FxError(f'{name}: expected {expected.describe()}, received {actual.describe()}',
                                  'Type', arg.start, arg.end)
            values = [self.capture(arg, ctx) for arg in args]
            def instant():
                observe(values[0])
                value = values[0]
                if isinstance(value, Dynamic):
                    value = convert_scalar(value, 'DateTime', self)
                result = self.temporal(value)
                return result.value if result is not None else EPOCH
            converted = [capture(instant), capture(lambda: self.numeric_argument(values[1], 'float'))]
            errors = [value for value in converted if isinstance(value, FxError)]
            if errors:
                raise FxError.combine(errors)
            return shift_months(name, converted[0], converted[1] or 0)
        if name in ('Value', 'Decimal', 'Float', 'Mod'):
            values = [self.capture(arg, ctx) for arg in args]
            errors = [value for value in values if isinstance(value, FxError)]
            if errors:
                raise FxError.combine(errors)
        else:
            values = [e(i) for i in range(n)]
        a = values[0] if values else None
        constructors = {'Text':'Text','Value':'Number','Float':'Float','Decimal':'Decimal','Boolean':'Boolean','GUID':'GUID','ColorValue':'Color','DateValue':'Date','DateTimeValue':'DateTime','TimeValue':'Time'}
        if name in constructors and isinstance(a,Dynamic):
            if name == 'Decimal' and self.number_mode != 'decimal':
                raise FxError('Decimal requires the optional Decimal host mode; canvas apps use Float numbers', 'Unsupported')
            converted = convert_scalar(a,constructors[name],self,text(values[1]) if n > 1 and name in ('Value','Float','Decimal') else None)
            if name == 'Text' and n > 1:
                converted = convert_scalar(a,'Number',self) if isinstance(a.value,JsonNumber) else converted
                return self.format_text([converted,*values[1:]])
            if name in ('Text','Value','Float','Decimal','Boolean','DateValue','DateTimeValue','TimeValue'):
                return converted
            values[0] = a = converted
        if name == 'Text' and n == 1 and a is None and self.node_types.get(id(args[0])) and self.node_types[id(args[0])].kind == 'Dynamic':
            return None
        if name == "Text":
            return self.format_text(values)
        if name in ('Value', 'Decimal', 'Float'):
            if name == 'Decimal' and self.number_mode != 'decimal':
                raise FxError('Decimal requires the optional Decimal host mode; canvas apps use Float numbers', 'Unsupported')
            kind = 'decimal' if name == 'Decimal' else 'float' if name == 'Float' else self.number_mode
            return parse_number(enum_numeric(a,explicit=True), text(values[1]) if n > 1 else self.host.environment['language'], self.numeric_mode, kind)
        if name == "Boolean":
            if isinstance(a,EnumValue):raise FxError("Boolean does not accept enum values","Type")
            if a is None:
                return None
            if isinstance(a, NUMBERS) and not isinstance(a, bool):
                return a != 0
            if isinstance(a, bool):
                return a
            if text(a).lower() in ("true", "false"):
                return text(a).lower() == "true"
            raise FxError("Invalid Boolean")
        if name == "IsNumeric":
            if isinstance(a, bool) or a is None:
                return False
            try:
                return parse_number(a, self.host.environment['language'], self.numeric_mode) is not None
            except FxError as error:
                if error.kind in ('Unsupported', 'BadLanguageCode'):
                    raise
                return False
        if name in ("StartsWith", "EndsWith"):
            return text(a).casefold().startswith(text(values[1]).casefold()) if name == "StartsWith" else text(a).casefold().endswith(text(values[1]).casefold())
        if name == "GUID":
            if not values:self.host.reactive.volatile()
            return str(uuid.UUID(text(a))) if values else str(uuid.uuid4())
        if name == 'Mod':
            value, divisor = self.numeric_arguments(values)
            return calculate('mod', value, divisor)
        if name in CALENDAR_FUNCTIONS:
            return self.calendar_scalar(name, values)
        if name in ("Year", "Month", "Day", "Hour", "Minute", "Second"):
            kind = 'Time' if name in ('Hour', 'Minute', 'Second') and isinstance(a, str) and not re.search(r'\d{4}[-/]', a) else 'DateTime'
            temporal = self.temporal(a, kind)
            d = temporal.value if temporal is not None else EPOCH
            return {'Year': d.year, 'Month': d.month, 'Day': d.day, 'Hour': d.hour, 'Minute': d.minute, 'Second': d.second}[name]
        if name in ("DateValue", "DateTimeValue", "TimeValue"):
            if name == 'TimeValue':
                return parse_time(a, text(values[1]) if n > 1 else self.host.environment['language'])
            result = self.temporal(a, {'DateValue': 'Date', 'DateTimeValue': 'DateTime'}[name], text(values[1]) if n > 1 else None)
            return Temporal('Date', result.value.replace(hour=0, minute=0, second=0, microsecond=0)) if name == 'DateValue' and result is not None else result
        if name in ('Date', 'DateTime', 'Time'):
            parts = [int(v) if isinstance(v, bool) else parse_number(v, self.host.environment['language']) or 0 for v in values]
            try:
                if name == 'Time':
                    d = EPOCH + timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2], milliseconds=parts[3] if n == 4 else 0)
                else:
                    d = make_date(*parts[:3])
                    if name == 'DateTime':
                        d += timedelta(hours=parts[3], minutes=parts[4], seconds=parts[5], milliseconds=parts[6] if n == 7 else 0)
                return Temporal(name, d)
            except (ValueError, OverflowError):
                raise FxError('Date/time is outside the supported calendar range', 'InvalidArgument') from None
        if name == "DateAdd":
            d, delta, unit = self.temporal(a).value if a is not None else EPOCH, float(number(values[1])), self.enum_argument(values[2],"TimeUnit") or "Days" if n > 2 else "Days"
            if unit in ("Months", "Quarters", "Years"):
                total = d.year * 12 + d.month - 1 + int(delta) * {"Months": 1, "Quarters": 3, "Years": 12}[unit]
                import calendar
                d = d.replace(year=total // 12, month=total % 12 + 1, day=min(d.day, calendar.monthrange(total // 12, total % 12 + 1)[1]))
            else:
                if unit not in ("Days", "Hours", "Minutes", "Seconds", "Milliseconds"):
                    raise FxError(f"Unsupported date unit {unit}", "InvalidArgument")
                d += timedelta(**{unit.lower(): delta})
            input_type = self.node_types.get(id(args[0]))
            return Temporal(input_type.kind if input_type and input_type.kind in TEMPORAL_KINDS else 'DateTime', d)
        if name == "DateDiff":
            return date_diff(self.temporal(a).value if a is not None else None, self.temporal(values[1]).value if values[1] is not None else None, self.enum_argument(values[2],"TimeUnit") or "Days" if n > 2 else "Days")
        if name == "RGBA":
            return f"rgba({number(a):g},{number(values[1]):g},{number(values[2]):g},{number(values[3]):g})"
        if name == "ColorValue":
            from .colors import color_value
            return color_value(text(a))
        if name == "ColorFade":
            from .colors import fade
            return fade(a,number(values[1]))
        if name == "Sequence":
            count = int(number(a)); start = values[1] if n > 1 else self.numeric_argument(None) + 1; step = values[2] if n > 2 else self.numeric_argument(None) + 1
            if count < 0 or count > 50000:
                raise FxError("Sequence count must be between 0 and 50000")
            return [{"Value": calculate("+", start, calculate("*", Decimal(i) if isinstance(step, Decimal) else i, step))} for i in range(count)]
        raise FxError(f"Unsupported function {name}", "Unsupported")

    def calendar_scalar(self, name, values):
        a = values[0]
        if isinstance(a, (list, dict, DataSource, EnumValue)):
            raise FxError(f'{name}: expected a scalar date/time value', 'Type')
        temporal = self.temporal(a)
        instant = temporal.value if temporal is not None else EPOCH
        start = 1
        if len(values) > 1:
            value = values[1]
            if isinstance(value, EnumValue):
                self.enum_argument(value, 'StartOfWeek')
                start = value.backing
            else:
                self.enum_argument(value, 'StartOfWeek')
                # WeekNum replaces Blank with Sunday; Weekday coerces it to zero.
                start = 1 if value is None and name == 'WeekNum' else self.numeric_argument(value)
                if start is None:
                    start = 0
        return calendar_number(name, instant, start, self.number_mode)

    def scalar_overload(self, name, values, enum_namespace=None):
        errors = [value for value in values if isinstance(value, FxError)]
        if errors:
            raise FxError.combine(errors)
        if name=='Concatenate' and enum_namespace:
            return concatenated(enum_namespace,from_units(''.join(self.to_text(value) for value in values)))
        if name in CALENDAR_OVERLOADS:
            return self.calendar_scalar(name, values)
        if name in HTML_FUNCTIONS:
            return html_evaluate(name,self.to_text(values[0]))
        if name in TEXT_OPERATIONS:
            numeric=NUMERIC_ARGUMENTS.get(name,set())
            converted=[capture(lambda i=i,value=value:self.numeric_argument(value,'float') if i in numeric else self.to_text(value)) for i,value in enumerate(values)]
            errors=[value for value in converted if isinstance(value,FxError)]
            if errors:raise FxError.combine(errors)
            converted=[0 if value is None and i in numeric else value for i,value in enumerate(converted)]
            result=text_evaluate(name,converted)
            return Decimal(result) if name=='Hex2Dec' and self.number_mode=='decimal' else result
        if name in MATH_FUNCTIONS:
            # Transcendental functions coerce to Float even in Decimal hosts.
            converted=[capture(lambda value=value:self.numeric_argument(value,'float' if name in FLOAT_FUNCTIONS|SCALAR_FLOAT_FUNCTIONS else None)) for value in values]
            errors=[value for value in converted if isinstance(value,FxError)]
            if errors:raise FxError.combine(errors)
            return math_evaluate(name,converted)
        if name in TEXT_OVERLOADS:
            s = self.to_text(values[0])
            if name == 'Proper':
                from .power_case import proper
                return proper(s, self.host.environment.get('language', 'en-US'))
            if name in ('Lower', 'Upper'):
                from .power_case import change_case
                return change_case(s, self.host.environment.get('language', 'en-US'), upper=name == 'Upper')
            if name == 'Len':
                # Power Fx strings use UTF-16 code units, including surrogate pairs.
                length = len(s.encode('utf-16-le', errors='surrogatepass')) // 2
                return Decimal(length) if self.number_mode == 'decimal' else length
            return {'Lower': lambda: s.lower(), 'Upper': lambda: s.upper(),
                    'Trim': lambda: re.sub(r'[^\S\u00a0\n\v\f\r]+', ' ', s).strip(),
                    'TrimEnds': lambda: s.strip()}[name]()
        if name in ROUND_OVERLOADS:
            value, digits = self.numeric_arguments(values, promote_values=False)
            return rounded(value, digits, name)
        value = self.numeric_argument(values[0])
        return value.copy_abs() if isinstance(value, Decimal) else abs(value)

    def single_column_call(self, name, args, ctx):
        values = [self.capture(arg, ctx) for arg in args]
        types = [self.node_types.get(id(arg)) for arg in args]
        flags = [isinstance(value, (list, DataSource)) or bool(typ and typ.kind == 'Table')
                 for value, typ in zip(values, types)]
        if name in CALENDAR_OVERLOADS and len(flags) > 1 and flags[1]:
            raise FxError('StartOfWeek requires a scalar value', 'Type', args[1].start, args[1].end)
        if name in CALENDAR_OVERLOADS and types[0] and types[0].kind == 'Table' and types[0].row:
            for field in types[0].row.fields.values():
                if field.kind not in TEMPORAL_KINDS | {'Text', 'Number', 'Decimal', 'Blank', 'Error', 'Unknown'}:
                    raise FxError(f'{name}: expected a date/time column', 'Type', args[0].start, args[0].end)
        namespace=concatenate_namespace([typ.row.fields[next(iter(typ.row.fields))] if typ and typ.kind=='Table' and typ.row and len(typ.row.fields)==1 else typ for typ in types]) if name=='Concatenate' else None
        if not any(flags):
            return self.scalar_overload(name, values, namespace)
        for arg, typ in zip(args, types):
            if typ and typ.kind == 'Table' and typ.row:
                single_column(typ.row.fields, typ.row.open and not empty_table_literal(arg), arg.start, arg.end)
        # Blank/error TABLE arguments determine the entire result. Scalar errors
        # become per-cell errors and an empty table never consumes those cells.
        for value, flag in zip(values, flags):
            if flag and (value is None or isinstance(value, FxError)):
                observe(value)
                return None
        columns, row_sets = {}, {}
        for i, (value, typ, flag) in enumerate(zip(values, types, flags)):
            if not flag:
                continue
            rows = table(value)
            row_type = typ.row if typ and typ.kind == 'Table' else None
            fields = (set(row_type.fields) if row_type else set()) | {key for row in rows if isinstance(row, dict) for key in row}
            columns[i] = single_column(fields, bool(row_type and row_type.open and not empty_table_literal(args[i])), args[i].start, args[i].end)
            row_sets[i] = rows
        size = max(map(len, row_sets.values()))
        output = []
        for index in range(size):
            row_values, error_row, blank_row, missing = [], None, False, False
            for i, value in enumerate(values):
                if i not in row_sets:
                    row_values.append(value)
                    continue
                if index >= len(row_sets[i]):
                    if name in ROUND_OVERLOADS and i == 1 and self.host.environment.get('round_table_mode', 'canvas-zero') == 'canvas-zero':
                        row_values.append(None)
                    else:
                        missing = True
                    continue
                row = row_sets[i][index]
                if isinstance(row, FxError):
                    if error_row is None:
                        error_row = row
                elif row is None:
                    blank_row = True
                    row_values.append(None)
                elif isinstance(row, dict):
                    row_values.append(row.get(columns[i]))
                else:
                    raise FxError('Expected record rows in a single-column table', 'Type', args[i].start, args[i].end)
            if missing:
                output.append({'Value': FxError('Table arguments have different lengths', 'NotApplicable', args[0].start, args[-1].end)})
            elif error_row is not None:
                output.append(error_row)
            elif blank_row and len(args) == 1:
                output.append(None)  # Blank rows remain distinct from blank cells.
            else:
                def compute():
                    try:
                        return self.scalar_overload(name, row_values, namespace)
                    except FxError as error:
                        if error.end <= error.start:
                            error.start, error.end = args[0].start, args[-1].end
                        raise
                output.append({'Value': capture(compute)})
        return output

    def sort_column(self, node, ctx, source_node, rows):
        typ = self.node_types.get(id(source_node))
        row_type = typ.row if typ and typ.kind == 'Table' else None
        concrete_rows = [row for row in rows if isinstance(row, dict)]
        fields = (set(row_type.fields) if row_type else set()) | {key for row in concrete_rows for key in row}
        if node.kind == 'name' and node.value in fields:
            value = node.value
        elif node.kind == 'name':
            try:
                value = self.eval(node, ctx)
            except FxError as error:
                if error.kind != 'Name':
                    raise
                value = node.value
        else:
            value = self.eval(node, ctx)
        if not isinstance(value, str) or not value:
            raise FxError('SortByColumns requires a column name', 'InvalidArgument')
        if value not in fields and not (row_type and row_type.open and not concrete_rows):
            raise FxError(f'Unknown sort column {value}', 'InvalidFunctionUsage')
        return value

    def sort_rows(self, rows, key, direction="Ascending", order_values=None):
        decorated = [(row, capture(lambda: key(row))) for row in rows]
        errors = [value for _, value in decorated if isinstance(value, FxError)]
        if errors:
            raise FxError.combine(errors)
        present = [(row, value) for row, value in decorated if value is not None]
        blanks = [row for row, value in decorated if value is None]
        if order_values is not None:
            rank = lambda value: next((i for i, target in enumerate(order_values) if self.equal(value, target)), len(order_values))
            present.sort(key=lambda pair: rank(pair[1]))
        else:
            observe(direction)
            if direction is not None and not isinstance(direction, str):
                raise FxError('Sort order must be Ascending or Descending', 'Validation')
            try:
                present.sort(key=lambda pair: self.sort_key(pair[1]), reverse=str(direction).casefold() == 'descending')
            except TypeError:
                raise FxError('Sort keys have incompatible types', 'Validation') from None
        return [row for row, _ in present] + blanks

    def sort_key(self, value):
        observe(value)
        if isinstance(value,EnumValue):value=value.backing
        if isinstance(value, Temporal):
            return value.value
        if isinstance(value, str):
            # Deterministic basic English ordering with lowercase before
            # uppercase at a case-only tie. Complete ICU collation is not claimed.
            return value.casefold(), tuple(char.isupper() for char in value), value
        if value is None or isinstance(value, (bool, *NUMBERS)):
            return value
        raise FxError('Sort keys must be scalar values', 'Validation')

    def format_text(self, values):
        value = values[0]
        if len(values) == 1:
            return self.to_text(value)
        fmt = self.enum_argument(values[1],"DateTimeFormat")
        fmt = text(fmt)
        locale = text(values[2]) if len(values) > 2 else self.host.environment['language']
        if isinstance(value, NUMBERS) and not isinstance(value, bool):
            tokens = re.sub(r'\[.*?\]|"[^"]*"', '', fmt)
            if fmt in ENUMS['DateTimeFormat'] or re.search(r'[dhy]|ss|mm|AM/PM|A/P', tokens, re.I):
                return format_date(Temporal.from_number(value, mode=self.numeric_mode).value, fmt, locale)
            return format_number(value, fmt, locale)
        if value is None:
            return ""
        return format_date(date_value(value), fmt, locale)

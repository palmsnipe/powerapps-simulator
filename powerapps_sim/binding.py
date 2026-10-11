"""Lexical Power Fx binding and schema/type inference, independent of evaluation.

Unknown denotes incomplete metadata, not Blank. Inferred types accompany AST
nodes, including expressions whose runtime value is Blank. No app events run
while binding.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal

from .tables import SHAPING_FUNCTIONS, column_name, shape_columns
from .scopes import ScopeFrame
from .overloads import SINGLE_COLUMN_OVERLOADS, TEXT_OVERLOADS, single_column, empty_table_literal
from .power_math import FLOAT_FUNCTIONS,SCALAR_FLOAT_FUNCTIONS
from .power_text import NUMERIC_ARGUMENTS
from .controls import NUMERIC_CONTROL_PROPERTIES
from .classic_inputs import TEXT_INPUTS,CLASSIC_INPUTS
from .syntax import FxError, call_name, walk
from .temporal import Temporal, TEMPORAL_KINDS
from .enum_fx import EnumValue,CATALOG as ENUM_CATALOG,VALUES as ENUM_VALUES,concatenate_namespace,namespace_values


@dataclass(eq=True)
class FxType:
    kind: str
    fields: dict = field(default_factory=dict)
    row: FxType | None = None
    name: str = ""
    open: bool = False
    control: object = field(default=None, compare=False, repr=False)
    aliases: dict = field(default_factory=dict, compare=False, repr=False)
    virtual: dict = field(default_factory=dict, compare=False, repr=False)

    def describe(self):
        if self.kind == "Record":
            return "{" + ", ".join(f"{k}: {v.describe()}" for k, v in self.fields.items()) + (" …" if self.open else "") + "}"
        if self.kind == "Table":
            return "[" + (self.row or UNKNOWN).describe() + "]"
        return self.name or self.kind

    def json(self):
        result = {"kind": self.kind}
        if self.fields:
            result["fields"] = {k: v.json() for k, v in self.fields.items()}
        if self.virtual:
            result['virtual'] = {k: v.json() for k, v in self.virtual.items()}
        if self.row:
            result["row"] = self.row.json()
        if self.name:
            result["name"] = self.name
        if self.open:
            result["open"] = True
        if self.aliases:
            result['aliases'] = dict(self.aliases)
        return result

    def cache_key(self):
        """Include logical-name metadata at every record/table depth."""
        return (self.kind, self.name, self.open, tuple(sorted(self.aliases.items())),
                tuple((k, v.cache_key()) for k, v in sorted(self.virtual.items())),
                tuple((key, value.cache_key()) for key, value in self.fields.items()),
                self.row.cache_key() if self.row else None)

    def physical_fields(self):
        return {self.aliases.get(key,key):value for key,value in self.fields.items()}


UNKNOWN = FxType("Unknown")
BLANK = FxType("Blank")
ERROR = FxType("Error")
TEXT = FxType("Text")
NUMBER = FxType("Number")
DECIMAL = FxType("Decimal")
BOOLEAN = FxType("Boolean")
DATE = FxType("Date")
DATETIME = FxType("DateTime")
TIME = FxType("Time")
COLOR = FxType("Color")
VOID = FxType("Void")
OPEN_RECORD = FxType("Record", open=True)


def record(fields=None, open=False, aliases=None):
    return FxType("Record", dict(fields or {}), open=open, aliases=dict(aliases or {}))


def tabular(row=None):
    return FxType("Table", row=row or OPEN_RECORD)


def merge(a, b):
    if a.kind in ("Blank", "Error", "Unknown"):
        return b
    if b.kind in ("Blank", "Error", "Unknown"):
        return a
    if a.kind=='Enum':
        if b.kind=='Enum' and a.name==b.name:return a
        if b.kind==ENUM_CATALOG[a.name]['kind'] and ENUM_CATALOG[a.name]['from_backing']:return a
        return UNKNOWN
    if b.kind=='Enum':
        if a.kind=='Text' or a.kind in ('Number','Decimal') and ENUM_CATALOG[b.name]['to_backing']:return a
        return UNKNOWN
    if a.kind == b.kind == "Record":
        aliases = {k:v for k,v in {**a.aliases, **b.aliases}.items() if k not in a.aliases or k not in b.aliases or a.aliases[k] == b.aliases[k]}
        return record({k: merge(a.fields.get(k, BLANK), b.fields.get(k, BLANK)) for k in a.fields.keys() | b.fields.keys()}, a.open or b.open, aliases)
    if a.kind == b.kind == "Table":
        return tabular(merge(a.row or OPEN_RECORD, b.row or OPEN_RECORD))
    if a.kind == b.kind:
        return a if a.name == b.name else FxType(a.kind)
    if {a.kind, b.kind} <= TEMPORAL_KINDS:
        return DATETIME
    # Power Fx permits scalar coercions in table/conditional result unification.
    if "Text" in (a.kind, b.kind) and a.kind not in ("Record", "Table", "Control", "Screen") and b.kind not in ("Record", "Table", "Control", "Screen"):
        return TEXT
    if {a.kind, b.kind} <= {"Number", "Decimal", "Boolean", "Currency"}:
        return NUMBER if "Number" in (a.kind, b.kind) else DECIMAL if "Decimal" in (a.kind, b.kind) else NUMBER
    return UNKNOWN


def compatible(actual, expected):
    if actual.kind in ("Unknown", "Blank", "Error") or expected.kind in ("Unknown", "Void"):
        return True
    if actual.kind=='Enum':
        if expected.kind=='Enum':return actual.name==expected.name
        return expected.kind=='Text' or expected.kind in ('Number','Decimal') and ENUM_CATALOG[actual.name]['to_backing']
    if expected.kind=='Enum':return actual.kind==ENUM_CATALOG[expected.name]['kind'] and ENUM_CATALOG[expected.name]['from_backing']
    if expected.kind == 'Screen':
        return actual.kind == 'Screen' or actual.kind == 'Control' and (actual.control is None or getattr(actual.control, 'family', None) == 'Screen')
    if actual.kind == 'Currency' and expected.kind in ('Number', 'Decimal'):
        return True
    if expected.kind == "Table":
        return actual.kind == "Table" and compatible(actual.row or OPEN_RECORD, expected.row or OPEN_RECORD)
    if expected.kind == "Record":
        return actual.kind == "Record" and all(
            k in actual.fields and compatible(actual.fields[k], t) or actual.open
            for k, t in expected.fields.items())
    if actual.kind in ("Number", "Decimal") and expected.kind in ("Number", "Decimal"):
        return True
    return actual.kind == expected.kind or actual.kind in ("Date", "Time") and expected.kind == "DateTime"


def function_compatible(actual, expected, restrictive=True):
    """UDF coercions use restrictive aggregates and the V1 scalar rules.

    A conversion being bindable does not imply its value can convert: invalid
    text fails at runtime. This mirrors UserDefinedFunction.CheckTypes and
    DType.CoercesTo rather than widening ordinary schema compatibility.
    """
    if actual.kind in ("Unknown", "Blank", "Error") or expected.kind in ("Unknown", "Void"):
        return True
    if expected.kind == "Table":
        return actual.kind in ("Table", "Record") and function_compatible(
            actual.row or OPEN_RECORD if actual.kind == "Table" else actual,
            expected.row or OPEN_RECORD, restrictive)
    if expected.kind == "Record":
        if actual.kind != 'Record':
            return False
        # Logical-name aliases describe the same fields, not extra UDF fields.
        actual_fields, expected_fields = actual.physical_fields(), expected.physical_fields()
        if restrictive:
            return all(expected.open or name in expected_fields and function_compatible(field, expected_fields[name], restrictive)
                for name, field in actual_fields.items())
        return all(name not in actual_fields or function_compatible(actual_fields[name], field, restrictive)
            for name, field in expected_fields.items())
    if actual.kind=='Enum' or expected.kind=='Enum':return compatible(actual,expected)
    if expected.kind == 'Screen':
        return compatible(actual, expected)
    if actual.kind == 'Dynamic':
        return expected.kind in {'Dynamic', 'Text', 'Number', 'Decimal', 'Boolean', 'GUID', 'Color'} | TEMPORAL_KINDS
    scalars = {
        'Number': {'Number', 'Decimal', 'Currency', 'Text', 'Boolean'} | TEMPORAL_KINDS,
        'Decimal': {'Number', 'Decimal', 'Currency', 'Text', 'Boolean'} | TEMPORAL_KINDS,
        'Currency': {'Currency', 'Number', 'Decimal', 'Text', 'Boolean'},
        'Boolean': {'Boolean', 'Number', 'Decimal', 'Currency', 'Text'},
        'Text': {'Text', 'Boolean', 'Number', 'Decimal', 'Currency', 'GUID', 'Image', 'Media'} | TEMPORAL_KINDS,
        'GUID': {'GUID', 'Text'},
        'Image': {'Image', 'Text'},
        'Media': {'Media', 'Text'},
        **{kind: {'Number', 'Decimal', 'Text'} | TEMPORAL_KINDS for kind in TEMPORAL_KINDS},
    }
    return actual.kind in scalars.get(expected.kind, {expected.kind})


def schema_type(schema):
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        return record({k: schema_type(v) for k, v in schema.get("properties", {}).items()}, not bool(schema.get("properties")))
    if kind == "array":
        return tabular(schema_type(schema.get("items", {})))
    if kind == "string":
        return DATE if schema.get("format") == "date" else DATETIME if schema.get("format") == "date-time" else TIME if schema.get("format") == "time" else TEXT
    if kind == "number" and schema.get("format") == "decimal":
        return DECIMAL
    return {"integer": NUMBER, "number": NUMBER, "boolean": BOOLEAN}.get(kind, UNKNOWN)


def value_type(value):
    if isinstance(value,EnumValue):return FxType("Enum",name=value.namespace)
    from .icons import IconValue
    if isinstance(value,IconValue):
        return FxType('Icon')
    from .json_fx import Dynamic, Media
    if isinstance(value,Dynamic):
        return FxType('Dynamic')
    if isinstance(value,Media):
        return FxType(value.media_kind)
    from datetime import date, datetime
    if isinstance(value, FxError):
        return ERROR
    if value is None:
        return BLANK
    if isinstance(value, bool):
        return BOOLEAN
    if isinstance(value, Decimal):
        return DECIMAL
    if isinstance(value, (int, float)):
        return NUMBER
    if isinstance(value, Temporal):
        return {"Date": DATE, "DateTime": DATETIME, "Time": TIME}[value.kind]
    if isinstance(value, datetime):
        return DATETIME
    if isinstance(value, date):
        return DATE
    if isinstance(value, str):
        return TEXT
    if hasattr(value, 'control') and hasattr(value, 'property'):
        return FxType('Control', name=value.name, control=value.control)
    if isinstance(value, dict):
        typ = record({k: value_type(v) for k, v in value.items()}, aliases={logical:display for display,logical in getattr(value,'logical_names',{}).items() if display in value})
        from .galleries import GalleryRecord
        return replace(typ, virtual={'IsSelected': BOOLEAN}) if isinstance(value, GalleryRecord) else typ
    if isinstance(value, list):
        row = BLANK
        for item in value:
            if isinstance(item, FxError):
                continue
            t = value_type(item)
            row = merge(row, t if t.kind == "Record" else record({"Value": t}))
        return tabular(row if row.kind != "Blank" else OPEN_RECORD)
    return UNKNOWN


@dataclass
class BindScope:
    frames: list = field(default_factory=list)
    self_control: object = None
    item: FxType = field(default_factory=lambda: OPEN_RECORD)
    behavior: bool = False
    screen: str = ""
    component: object = None
    function_pure: bool = False

    def child(self, frame, **kwargs):
        from dataclasses import replace
        return replace(self, frames=[*self.frames, frame], **kwargs)


class Binder:
    def __init__(self, runtime):
        from .fx import ENUMS
        self.runtime = runtime
        self.nodes, self.errors, self.dependencies = {}, [], {}
        self.node_refs = {}
        self.variables, self.collections, self.context_variables = {}, {}, {}
        self.component_variables, self.component_collections = {}, {}
        self.named, self.aliases, self.active, self.props_active = {}, {}, set(), set()
        self.type_errors = {}
        self.controls = {n: cs[0] for n, cs in runtime.project.controls.items()}
        self.globals = {n: FxType("Control", name=n, control=r.control) for n, r in runtime.global_refs.items()}
        for name, d in runtime.store.definitions.items():
            fields = {k: schema_type(v) for k, v in d["fields"].items()}
            fields.update({display: fields[internal] for internal, display in d["mapping"].items() if internal in fields})
            self.globals[name] = tabular(record(fields, aliases={internal:display for internal,display in d['mapping'].items() if internal!=display}))
        self.globals.update({k: value_type(namespace_values(k,runtime.environment,v)) for k, v in ENUMS.items()})
        self.globals['Color'] = record({name:COLOR for name in ENUMS['Color']})
        self.globals.update(App=FxType("Control", name="App"), PowerAppsTheme=OPEN_RECORD,
            CustomGallerySample=tabular(), ComboBoxSample=tabular())
        from .json_fx import media_kind
        self.globals.update({r["Name"]: FxType(media_kind(r.get('Path', ''))) if r.get('ResourceKind') == 'LocalFile' else TEXT for r in runtime.project.config.get("resource_metadata", []) if r.get("Name")})
        self.owner = None
        self.expression_owners = {}
        self.expression_roots = set()
        self.reporting = False
        self.inferring_assignments = False

    def issue(self, message, node, kind="Type"):
        if self.reporting:
            owner=self.expression_owners.get(id(node),self.owner) if self.owner in self.expression_roots else self.owner
            key = (owner, message, node.start, node.end)
            if not any(e[0] == key for e in self.errors):
                self.errors.append((key, FxError(message, kind, node.start, node.end)))

    def default_number(self):
        return DECIMAL if self.runtime.fx.number_mode == 'decimal' else NUMBER

    def numeric_result(self, types):
        numeric = [t if t.kind in ('Number', 'Decimal') else self.default_number() for t in types]
        return NUMBER if any(t.kind == 'Number' for t in numeric) else DECIMAL if any(t.kind == 'Decimal' for t in numeric) else self.default_number()

    def require_enum(self,typ,namespace,node,what):
        if self.runtime.environment.get('enum_mode')!='strong':
            return self.require(typ,TEXT if ENUM_CATALOG[namespace]['kind']=='Text' else NUMBER,node,what)
        if not compatible(typ,FxType('Enum',name=namespace)):
            self.issue(f'{what}: expected {namespace}, received {typ.describe()}',node)

    def require_numeric(self, typ, node, what):
        if typ.kind=='Enum':
            if not ENUM_CATALOG[typ.name]['to_backing'] or ENUM_CATALOG[typ.name]['kind']!='Number':
                self.issue(f'{what}: {typ.name} cannot convert implicitly to a number',node)
            return
        if typ.kind not in {'Number', 'Decimal', 'Currency', 'Text', 'Boolean', 'Blank', 'Error', 'Unknown', 'Dynamic'} | TEMPORAL_KINDS:
            self.issue(f'{what}: expected a numeric scalar, received {typ.describe()}', node)

    def declared_type(self, name, active=None):
        primitive = {"Text": TEXT, "Boolean": BOOLEAN, "Number": self.default_number(), "Float": NUMBER, "Decimal": DECIMAL,
            "Date": DATE, "DateTime": DATETIME, "Time": TIME, "GUID": FxType("GUID"), "Color": COLOR, "Image": FxType("Image"),
            "Table": tabular(), "Record": OPEN_RECORD, "Dynamic": FxType('Dynamic'), "None": VOID, "Void": VOID}
        if name in primitive:
            return primitive[name]
        active = active or set()
        if name in active:
            raise FxError(f"Recursive type {name}", "Type")
        if name in self.aliases:
            return self.aliases[name]
        d = self.runtime.fx.definitions.get(name)
        if not d or not d.alias:
            return UNKNOWN
        def shape(n):
            if n.kind == "call" and call_name(n.children[0]) == "RecordOf":
                args = n.children[1:]
                target = self.runtime.fx.definitions.get(call_name(args[0])) if len(args) == 1 else None
                if not target or not target.alias or args[0].kind != "name":
                    raise FxError("RecordOf requires one named table type", "Type", n.start, n.end)
                typ = self.declared_type(args[0].value, active | {name})
                if typ.kind != "Table":
                    raise FxError("RecordOf requires a table type", "Type", n.start, n.end)
                return typ.row or OPEN_RECORD
            if n.kind == "record":
                if len({k for k,_ in n.value}) != len(n.value):
                    raise FxError("Duplicate type field", "Type", n.start, n.end)
                return record({k: shape(v) for k, v in n.value})
            if n.kind == "table":
                if len(n.children) != 1:
                    raise FxError("A table type must contain exactly one type specification", "Type", n.start, n.end)
                row = shape(n.children[0])
                if row.kind == "Table":
                    raise FxError("A table type requires record or scalar rows", "Type", n.start, n.end)
                return tabular(row if row.kind == "Record" else record({"Value":row}))
            if n.kind != "name":
                raise FxError("Expected a type name or record/table type specification", "Type", n.start, n.end)
            typ = self.declared_type(n.value, active | {name})
            if typ.kind == 'Image':
                raise FxError('Type specifications do not support Image; use an Image component property', 'Unsupported', n.start, n.end)
            if typ.kind in ("Unknown", "Void"):
                raise FxError(f"Unknown or invalid field type {n.value}", "Type", n.start, n.end)
            return typ
        try:
            if d.body.kind != "call" or call_name(d.body.children[0]) != "Type" or len(d.body.children) != 2:
                raise FxError("A type declaration requires Type with one specification", "Type", d.body.start, d.body.end)
            result = shape(d.body.children[1])
        except FxError as error:
            self.type_errors[name] = error
            result = UNKNOWN
        self.aliases[name] = result
        return result

    def type_spec(self, node):
        """Type arguments are syntax, never formulas evaluated as app values."""
        if node.kind == 'call' and call_name(node.children[0]) == 'Type' and len(node.children) == 2:
            return self.type_spec(node.children[1])
        if node.kind == 'call' and call_name(node.children[0]) == 'RecordOf' and len(node.children) == 2:
            arg = node.children[1]
            if arg.kind != 'name' or not self.runtime.fx.definitions.get(arg.value) or not self.runtime.fx.definitions[arg.value].alias:
                raise FxError('RecordOf requires one named table type', 'Type', node.start, node.end)
            target = self.type_spec(arg)
            if target.kind != 'Table':
                raise FxError('RecordOf requires a table type', 'Type', node.start, node.end)
            return target.row
        if node.kind == 'record':
            if len({k for k,_ in node.value}) != len(node.value):
                raise FxError('Duplicate type field', 'Type', node.start, node.end)
            return record({k:self.type_spec(v) for k,v in node.value})
        if node.kind == 'table' and len(node.children) == 1:
            row = self.type_spec(node.children[0])
            if row.kind != 'Table':
                return tabular(row if row.kind == 'Record' else record({'Value':row}))
        if node.kind == 'name':
            result = self.declared_type(node.value)
            if result.kind == 'Image':
                raise FxError('Type specifications do not support Image; use an Image component property', 'Unsupported', node.start, node.end)
            if result.kind not in ('Unknown','Void'):
                return result
        raise FxError('Expected a valid type name or inline Type specification', 'Type', node.start, node.end)

    def component_declared_type(self, name):
        # Clipboard property enums are distinct from App.Formulas type names.
        native = {'DateAndTime': DATETIME, 'Currency': FxType('Currency'),
            'Screen': FxType('Screen'), 'VideoOrAudio': FxType('Media')}
        return native[name] if name in native else self.declared_type(name)

    def parameter_type(self, spec):
        declared = self.component_declared_type(spec.get("DataType"))
        if declared.fields or declared.row and declared.row.fields:
            return declared
        raw = spec.get("Default")
        if raw is not None and declared.kind in ("Record", "Table"):
            try:
                reporting=self.reporting
                self.reporting=False
                try:inferred = self.infer(self.runtime.fx.parse(raw), BindScope(function_pure=True)) if isinstance(raw, str) and raw.startswith('=') else value_type(raw)
                finally:self.reporting=reporting
                if inferred.kind == declared.kind:
                    return inferred
            except FxError:
                pass
        return declared

    def component_type(self, control, prop):
        """The definition supplies aggregate schemas, never an instance override."""
        from .components import component_definition, result_type_name
        definition = component_definition(self.runtime.project, control)
        custom = definition.raw.get('CustomProperties', {}).get(prop, {}) if definition else {}
        declared = self.component_declared_type(result_type_name(custom))
        if declared.kind not in ('Record', 'Table') or declared.fields or declared.row and declared.row.fields:
            return declared
        key = (id(definition), '__contract__' + prop)
        if key in self.props_active:
            return declared
        self.props_active.add(key)
        try:
            raw = definition.properties.get(prop, custom.get('Default'))
            if isinstance(raw, str) and raw.startswith('='):
                reporting=self.reporting
                self.reporting=False
                try:inferred = self.infer(self.runtime.fx.parse(raw), self.scope_for(definition, prop))
                finally:self.reporting=reporting
            else:
                inferred = value_type(raw)
            return inferred if inferred.kind == declared.kind else declared
        finally:
            self.props_active.remove(key)

    def definition(self, name):
        d = self.runtime.fx.definitions[name]
        if d.alias:
            return self.declared_type(name)
        if d.params is not None:
            return self.declared_type(d.returns)
        if name in self.named:
            return self.named[name]
        if name in self.active:
            self.issue(f"Formula dependency cycle involving {name}", d.body, "Cycle")
            return UNKNOWN
        self.active.add(name)
        result = self.infer(d.body, BindScope())
        self.active.remove(name)
        self.named[name] = result
        return result

    def scope_for(self, control=None, prop=""):
        from .components import property_kind, component_definition, custom_parameters
        component = control
        while component and component.kind != "Component" and component.family != "CanvasComponent":
            component = component.parent
        scope = BindScope(self_control=control, behavior=prop.startswith("On"), component=component)
        root = control
        while root and root.parent:
            root = root.parent
        if root:
            scope.screen = root.name
        ancestor = control.parent if control and control.family == 'Gallery' and prop not in ('OnSelect', 'TemplateFill', 'ItemAccessibleLabel') else control
        while ancestor:
            if ancestor.family == "Gallery":
                row = self.property_type(ancestor, "Items").row or OPEN_RECORD
                scope.item = replace(row, virtual={'IsSelected': BOOLEAN})
                siblings = {}
                for cs in self.runtime.project.controls.values():
                    for candidate in cs:
                        parent = candidate.parent
                        while parent and parent.family != "Gallery":
                            parent = parent.parent
                        if parent is ancestor:
                            siblings[candidate.name] = FxType("Control", name=candidate.name, control=candidate)
                scope.frames.append(siblings)
                break
            if ancestor.family in ("DataTable","ModernDataGrid") and control is not ancestor:
                scope.item = self.property_type(ancestor,"Items").row or OPEN_RECORD
                break
            if ancestor.family == "Form":
                scope.item = self.property_type(ancestor, "DataSource").row or OPEN_RECORD
                break
            ancestor = ancestor.parent
        # Each nested gallery contributes its own alias. Outer aliases remain
        # visible; nearer aliases shadow them without replacing ThisItem's type.
        from .galleries import item_alias
        ancestor=control.parent if control and control.family=='Gallery' and prop not in ('OnSelect','TemplateFill','ItemAccessibleLabel') else control
        galleries=[]
        while ancestor:
            if ancestor.family=='Gallery':galleries.append(ancestor)
            ancestor=ancestor.parent
        for gallery in reversed(galleries):
            row=replace(self.property_type(gallery,'Items').row or OPEN_RECORD,virtual={'IsSelected':BOOLEAN})
            frame={'ThisRecord':row};alias=item_alias(self.runtime,gallery)
            if alias:frame[alias]=row
            scope.frames.append(frame)
        if control and control.family in ("ModernCombobox", "ModernTabList", "ModernDropdown", "ModernRadio") and prop == "ItemDisplayText":
            scope.item = self.property_type(control, "Items").row or OPEN_RECORD
        # Custom event/action arguments live only in their own callback expression.
        if control:
            definition = component_definition(self.runtime.project, control)
            custom = definition.raw.get("CustomProperties", {}).get(prop, {}) if definition else {}
            if custom:
                scope.behavior = property_kind(custom) in ("Event", "Action")
                scope.function_pure = property_kind(custom) == "Function"
                if control.family == "CanvasComponent" and property_kind(custom) in ("Input", "Event"):
                    scope.component = control.parent
                    while scope.component and scope.component.family != "CanvasComponent" and scope.component.kind != "Component":
                        scope.component = scope.component.parent
                try:
                    params = custom_parameters(custom)
                except FxError:
                    params = []
                scope.frames.append({k: self.parameter_type(v) for k, v in params})
            elif control.family == "CanvasComponent" and prop in control.properties:
                scope.component = control.parent
                while scope.component and scope.component.family != "CanvasComponent" and scope.component.kind != "Component":
                    scope.component = scope.component.parent
        return scope

    def storage(self, scope, category):
        from .components import access_app_scope, component_definition
        if scope.component and not access_app_scope(self.runtime.project, scope.component):
            definition = component_definition(self.runtime.project, scope.component)
            name = definition.name if definition else scope.component.name
            container = self.component_variables if category == "variables" else self.component_collections
            return container.setdefault(name, {})
        return self.variables if category == "variables" else self.collections

    def property_type(self, control, prop):
        if control and control.family=="DataTableColumn" and prop=="Text":return TEXT
        from .components import component_definition, property_kind
        if control is None:
            return UNKNOWN
        if control.family in ('Text', 'FluentV8/Label'):
            from .canvas_text import catalog
            if prop == 'DisplayMode':return FxType('Enum', name='DisplayMode') if self.runtime.environment.get('enum_mode') == 'strong' else TEXT
            kind = catalog()[control.family].get(control.version, {}).get('types', {}).get(prop)
            if kind:return FxType(kind)
        if control.family == 'Button':
            from .canvas_buttons import catalog
            if prop == 'DisplayMode':return FxType('Enum', name='DisplayMode') if self.runtime.environment.get('enum_mode') == 'strong' else TEXT
            kind = catalog().get(control.version, {}).get('types', {}).get(prop)
            if kind:return FxType(kind)
        if control.family == 'TabList':
            from .canvas_tabs import catalog
            if prop == 'DisplayMode':return FxType('Enum', name='DisplayMode') if self.runtime.environment.get('enum_mode') == 'strong' else TEXT
            if prop == 'Selected':return self.property_type(control, 'Items').row or OPEN_RECORD
            if prop in ('SelectedItems', 'DefaultSelectedItems'):return tabular(self.property_type(control, 'Items').row or OPEN_RECORD)
            kind = catalog().get(control.version, {}).get('types', {}).get(prop)
            if kind and prop != 'Items':return FxType(kind)
        if control.family in ('Slider','Toggle'):
            from .canvas_scalars import catalog
            if prop=='DisplayMode':return FxType('Enum',name='DisplayMode') if self.runtime.environment.get('enum_mode')=='strong' else TEXT
            kind=catalog()[control.family].get(control.version,{}).get('types',{}).get(prop)
            if kind:return FxType(kind)
        if control.family == 'DatePicker':
            from .canvas_dates import catalog
            if prop == 'DisplayMode':return FxType('Enum', name='DisplayMode') if self.runtime.environment.get('enum_mode') == 'strong' else TEXT
            kind = catalog().get(control.version, {}).get('types', {}).get(prop)
            if kind:return FxType(kind)
        if control.family in ('ComboBox','DropDown','Radio','ComboBoxDataField'):
            from .canvas_selectors import catalog
            if prop=='DisplayMode':return FxType('Enum',name='DisplayMode') if self.runtime.environment.get('enum_mode')=='strong' else TEXT
            if prop=='Selected':return self.property_type(control,'Items').row or OPEN_RECORD
            if prop in ('SelectedItems','DefaultSelectedItems'):return tabular(self.property_type(control,'Items').row or OPEN_RECORD)
            kind=catalog()[control.family].get(control.version,{}).get('types',{}).get(prop)
            if kind and prop!='Items':return FxType(kind)
        if control.family in ('TextInput','CheckBox'):
            from .canvas_inputs import catalog
            if prop=='DisplayMode':return FxType('Enum',name='DisplayMode') if self.runtime.environment.get('enum_mode')=='strong' else TEXT
            kind=catalog()[control.family].get(control.version,{}).get('types',{}).get(prop)
            if kind:return FxType(kind)
        if control.family=='Toolbar':
            from .toolbar import TYPES
            if prop=='Selected':return self.property_type(control,'Items').row or OPEN_RECORD
            if prop=='SelectedItems':return tabular(self.property_type(control,'Items').row or OPEN_RECORD)
            if prop in TYPES and prop not in ('Items','DefaultSelectedItems'):return FxType(TYPES[prop])
        if control.family == 'ModernLink':
            from .modern_link import TYPES
            if prop == 'Type' and self.runtime.environment.get('enum_mode') == 'strong': return FxType('Enum', name='LinkAppearance')
            if prop in TYPES: return FxType(TYPES[prop])
        if control.family == 'ModernTabList':
            from .tablist import TYPES
            if prop in TYPES:return FxType(TYPES[prop])
            if prop=='Selected':return self.property_type(control,'Items').row or OPEN_RECORD
        if control.family in ('ModernBadge','ModernInformationButton'):
            from .status_controls import TYPES, ENUM_PROPERTIES
            if control.family=='ModernBadge' and prop in ENUM_PROPERTIES:
                return FxType('Enum',name=ENUM_PROPERTIES[prop]) if self.runtime.environment.get('enum_mode')=='strong' else TEXT
            if prop=='Content' and control.family=='ModernInformationButton':return TEXT
            if prop in TYPES:return FxType(TYPES[prop])
        if control.family == 'ModernButton':
            from .modern_button import TYPES
            if prop in TYPES:return FxType(TYPES[prop])
        if control.family=='FluentV8/Rating':
            from .fluent_rating import TYPES
            if prop=='DisplayMode':return FxType('Enum',name='DisplayMode') if self.runtime.environment.get('enum_mode')=='strong' else TEXT
            if prop in TYPES:return FxType(TYPES[prop])
        if control.family == "ModernRating":
            from .rating import TYPES
            if prop=="Step":return FxType("Enum",name="RatingStep") if self.runtime.environment.get("enum_mode")=="strong" else TEXT
            if prop in TYPES:return FxType(TYPES[prop])
        if control.family == "Timer":
            from .timers import TYPES
            if prop in TYPES:return FxType(TYPES[prop])
        if control.family in ('Audio','Video'):
            from .media_controls import TYPES
            if prop in TYPES:return FxType(TYPES[prop])
        if control.family in ('Label','Rectangle','Circle','Star'):
            from .classic_display import TYPES
            if prop in TYPES[control.family]:return FxType(TYPES[control.family][prop])
        if control.family=='Classic/Button':
            from .classic_button import TYPES
            if prop in TYPES:return FxType(TYPES[prop])
        if control.family == "RichTextEditor":
            from .rich_text import TYPES
            if prop in TYPES:return FxType(TYPES[prop])
        if control.family == "HtmlViewer":
            from .html_controls import TYPES
            if prop in TYPES:return FxType(TYPES[prop])
        if control.family=='Classic/DropDown' and prop=='SelectedText':return record({'Value':TEXT})
        if control.family=='Classic/Radio' and prop in ('Value','SelectedText'):return TEXT
        if control.family in ('Classic/CheckBox','Classic/Toggle') and prop in ('Value','Default'):return BOOLEAN
        key = (id(control), prop)
        if key in self.props_active:
            return UNKNOWN
        definition = component_definition(self.runtime.project, control)
        custom = definition.raw.get("CustomProperties", {}).get(prop) if definition else None
        if custom:
            if property_kind(custom) in ("Function", "Action", "Event"):
                return FxType("Callable", name=control.name + "." + prop, control=control)
            return self.component_type(control, prop)
        if control.family=='ModernDataGrid' and prop in ('Selected','SelectedItems'):
            items=self.property_type(control,'Items')
            return items.row or OPEN_RECORD if prop=='Selected' else items
        if control.family in ('ModernDataGrid','ModernDataGridColumn'):
            from .modern_grid import TYPES
            if prop in TYPES and prop not in ('Items','DefaultSelectedItems'):return FxType(TYPES[prop])
        if control.family=='ModernDataGridColumn' and prop=='Text':return TEXT
        if control.family == 'Gallery' and prop == 'AllItems':
            from .galleries import all_items_type
            self.props_active.add(key)
            try:
                return all_items_type(self, control)
            finally:
                self.props_active.remove(key)
        if control.family == 'Gallery' and prop == 'AllItemsCount':
            return NUMBER
        if control.family == 'Gallery' and prop == 'Selected':
            row = self.property_type(control, 'Items').row or OPEN_RECORD
            return replace(row, virtual={'IsSelected': BOOLEAN})
        if prop in NUMERIC_CONTROL_PROPERTIES or control.family == 'ModernNumberInput' and prop in ('Value', 'Default'):
            return NUMBER
        if prop == 'Text' and control.family in ('ModernText', 'Label', 'ModernButton', 'Classic/Button', *TEXT_INPUTS) or prop == 'Default' and control.family in TEXT_INPUTS:
            return TEXT
        self.props_active.add(key)
        try:
            raw = control.properties.get(prop)
            if raw is None and custom:
                raw = custom.get("Default")
            if raw is None and definition:
                raw = definition.properties.get(prop)
            if isinstance(raw, str) and raw.startswith("="):
                try:
                    reporting = self.reporting
                    self.reporting = False
                    try:
                        return self.infer(self.runtime.fx.parse(raw), self.scope_for(control, prop))
                    finally:
                        self.reporting = reporting
                except FxError:
                    return UNKNOWN
            if raw is not None:
                return value_type(raw)
            if control.family in ("DataTable","DataTableColumn"):
                from .data_table import TYPES
                kind=TYPES.get(prop)
                if kind:return FxType(kind)
            if control.family in ("ListBox","Classic/ListBox"):
                if prop=="SelectedText":return TEXT
                if prop=="SelectedItems":return tabular(self.property_type(control,"Items").row or OPEN_RECORD)
                if prop=="SelectedItemsText":return tabular(record({"Value":TEXT}))
                from .listbox import catalog
                kind=catalog()["types"].get(prop)
                if kind:return FxType(kind)
            if prop in ("Items", "AllItems", "SelectedItems", "DefaultSelectedItems"):
                return tabular()
            if prop == "Selected":
                return self.property_type(control, "Items").row or OPEN_RECORD
            if prop in ("Item", "LastSubmit", "Updates") and control.family == "Form":
                return self.property_type(control, "DataSource").row or OPEN_RECORD
            if prop == "Default" and control.family == "TypedDataCard" and control.parent:
                row = self.property_type(control.parent, "DataSource").row or OPEN_RECORD
                raw_field = control.properties.get("DataField", "")
                field = str(raw_field).removeprefix("=").strip('"')
                return row.fields.get(field, UNKNOWN)
            if prop in ("Default","NavigateItem") and control.family in ("ModernCombobox","Classic/ComboBox"):
                return OPEN_RECORD
            if prop in ("Default", "Text") and control.family in TEXT_INPUTS:
                return self.property_type(control, "Default") if prop == "Text" else TEXT
            if prop in ("Value", "Default") and control.family in ("ModernNumberInput", "ModernSlider"):
                return NUMBER
            if prop in ("DefaultDate", "SelectedDate", "StartDate", "EndDate"):
                return DATE
            if prop in ("Checked", "Valid", "Unsaved", "Visible", "Required", "IsSelected", "Reset", "Pressed", "IsEditable", "AcceptsFocus", "WidthFit", "Selectable", "ShowScrollbar", "DelayItemLoading"):
                return BOOLEAN
            if prop == "ErrorKind":
                return NUMBER
            if prop in ("Error", "DisplayMode", "Mode", "Name", "Text", "SearchText", "DataField", "DisplayName", "Font", "Tooltip"):
                return TEXT
            if prop in ("Default", "Update") and control.family == "TypedDataCard":
                return self.property_type(control, "Default")
            if control.family=='Classic/ComboBox':
                from .classic_combobox import catalog
                kind=catalog()['types'].get(prop)
                if kind:return FxType(kind)
            if control.family in CLASSIC_INPUTS:
                from .classic_inputs import catalog
                kind=catalog()[control.family]['types'].get(prop)
                if kind:return FxType(kind)
            if control.family=='Classic/Icon':
                from .icons import CLASSIC_PROPERTY_TYPES
                kind=CLASSIC_PROPERTY_TYPES.get(prop)
                if kind:return FxType(kind)
            if prop in ("Color", "Fill", "BorderColor", "BasePaletteColor", "LoadingSpinnerColor", "IconColor"):
                return COLOR
            if prop in ("X", "Y", "Width", "Height", "Rotation", "TemplateWidth", "TemplateHeight", "TemplateSize", "Size", "MaxLength") or prop.startswith(("Padding", "LayoutMin")):
                return NUMBER
            return UNKNOWN
        finally:
            self.props_active.remove(key)

    def lookup(self, name, scope, node, global_only=False):
        from .fx import ENUMS
        from .components import access_app_scope
        if not global_only:
            for frame in reversed(scope.frames):
                if name in frame:
                    return frame[name]
        if scope.function_pure and name not in ENUMS:
            self.issue(f"Component functions require {name} to be passed as an argument", node, "Name")
            return UNKNOWN
        if not global_only:
            if name == "ThisItem":
                return scope.item
            if name == "ThisRecord" and not any(getattr(frame, 'aliased', False) for frame in scope.frames):
                return scope.frames[-1].get("ThisRecord", UNKNOWN) if scope.frames else scope.item
            if name in ("Self", "Parent"):
                c = scope.self_control if name == "Self" else scope.self_control.parent if scope.self_control else None
                return FxType("Control", name=c.name, control=c) if c else UNKNOWN
            if name in self.context_variables.get(scope.screen, {}):
                return self.context_variables[scope.screen][name]
            if scope.component:
                definition = self.runtime.project.components.get(scope.component.raw.get("ComponentName")) if scope.component.family == "CanvasComponent" else scope.component
                if definition and name == definition.name:
                    return FxType("Control", name=scope.component.name, control=scope.component)
                # Component internals are visible only within the definition.
                for c in self.runtime.project.controls.get(name, []):
                    root = c
                    while root and root.parent:
                        root = root.parent
                    if definition and root is definition:
                        return FxType("Control", name=name, control=c)
        if scope.component and not access_app_scope(self.runtime.project, scope.component) and name not in ENUMS:
            for category in ("variables", "collections"):
                values = self.storage(scope, category)
                if name in values:
                    return values[name]
            if not global_only and any(getattr(frame, 'open_schema', False) for frame in scope.frames):
                return UNKNOWN
            self.issue(f"Component cannot access app identifier {name}; enable AccessAppScope or pass an input", node, "Name")
            return UNKNOWN
        if name in self.runtime.fx.definitions:
            if self.runtime.fx.definitions[name].alias:
                self.issue(f"Type {name} cannot be used as a runtime value", node)
                return UNKNOWN
            if self.owner:
                self.dependencies.setdefault(self.owner, set()).add(name)
            return self.definition(name)
        if name in self.variables:
            return self.variables[name]
        if name in self.collections:
            return self.collections[name]
        if name in self.globals:
            return self.globals[name]
        # An unknown row schema can resolve a field only inside that record scope.
        if not global_only and any(getattr(frame, 'open_schema', False) for frame in scope.frames):
            return UNKNOWN
        self.issue(f"Unknown identifier {name}", node, "Name")
        return UNKNOWN

    def require(self, actual, expected, node, what="value"):
        if actual.kind != 'Dynamic' or expected.kind not in ('Text','Number','Decimal','Boolean'):
            if not compatible(actual, expected):
                self.issue(f"{what}: expected {expected.describe()}, received {actual.describe()}", node)

    def require_function(self, actual, expected, node, what="value"):
        if not function_compatible(actual, expected):
            self.issue(f"{what}: expected {expected.describe()}, received {actual.describe()} (incompatible function schema)", node)

    def require_component(self, actual, expected, node, what='value'):
        if not function_compatible(actual, expected, restrictive=False):
            self.issue(f'{what}: expected {expected.describe()}, received {actual.describe()} (incompatible component contract)', node)

    def table_union(self, a, b, node):
        if a.kind in ("Unknown", "Blank", "Error"):
            return b
        if b.kind in ("Unknown", "Blank", "Error"):
            return a
        if a.kind=='Enum' or b.kind=='Enum':
            result=merge(a,b)
            if result.kind=='Unknown':self.issue('Incompatible enum table column types',node)
            return result
        if a.kind == b.kind == "Record":
            aliases = {key:value for key,value in {**a.aliases,**b.aliases}.items() if key not in a.aliases or key not in b.aliases or a.aliases[key]==b.aliases[key]}
            return record({k: self.table_union(a.fields.get(k, BLANK), b.fields.get(k, BLANK), node) for k in a.fields.keys() | b.fields.keys()}, a.open or b.open, aliases)
        if a.kind == b.kind == "Table":
            return tabular(self.table_union(a.row or OPEN_RECORD, b.row or OPEN_RECORD, node))
        if a.kind == b.kind:
            return a
        if {a.kind, b.kind} <= TEMPORAL_KINDS:
            return DATETIME
        if {a.kind, b.kind} <= {"Number", "Decimal", "Currency"}:
            return NUMBER
        if a.kind == b.kind or {a.kind, b.kind} <= {"Text", "Number", "Decimal", "Currency", "Boolean"} or (a.kind in TEMPORAL_KINDS and b.kind in ("Number", "Decimal")) or (b.kind in TEMPORAL_KINDS and a.kind in ("Number", "Decimal")):
            return a
        self.issue(f"Incompatible table column types: {a.describe()} and {b.describe()}", node)
        return UNKNOWN

    def infer(self, node, scope):
        # Retain the AST behind each id. CPython can otherwise reuse an id
        # after definitions are replaced and attach a stale inferred type.
        self.node_refs[id(node)] = node
        t = self._infer(node, scope)
        self.nodes[id(node)] = t
        return t

    def _infer(self, node, scope):
        k, v, c = node.kind, node.value, node.children
        if k == 'literal':
            if node.numeric_literal is not None:
                try:
                    return value_type(self.runtime.fx.literal_number(node.numeric_literal))
                except FxError as error:
                    self.issue(error.message, node, error.kind)
                    return self.default_number()
            return value_type(v)
        if k=='interpolate':
            types=[self.infer(child,scope) for child in c]
            for child,typ in zip(c,types):
                if typ.kind in ('Record','Table','Control','Screen','Callable','Void','Icon'):
                    self.issue(f'Interpolation requires a text-coercible scalar, received {typ.describe()}',child)
            namespace=concatenate_namespace(types)
            return FxType('Enum',name=namespace) if namespace else TEXT
        if k in ("name", "global"):
            return self.lookup(v, scope, node, k == "global")
        if k == "record":
            return record({n: self.infer(body, scope) for n, body in v})
        if k == "table":
            row = BLANK
            for child in c:
                t = self.infer(child, scope)
                incoming=t if t.kind=="Record" else record({"Value":t})
                row=self.table_union(row,incoming,child)
            return tabular(row if row.kind != "Blank" else OPEN_RECORD)
        if k == "alias":
            return self.infer(c[0], scope)
        if k in ("member", "disambiguate"):
            base = self.infer(c[0], scope)
            if base.kind == 'Dynamic':
                return FxType('Dynamic')
            if k == "disambiguate":
                source = call_name(c[0])
                for frame in reversed(scope.frames):
                    if source in getattr(frame, 'sources', {}):
                        base = frame.sources[source]
                        break
            if base.kind == 'Screen':
                screen_types = {'Width': NUMBER, 'Height': NUMBER, 'Fill': COLOR, 'Size': NUMBER,
                    'Orientation': TEXT, 'LoadingSpinnerColor': COLOR, 'BackgroundImage': FxType('Image')}
                if v not in screen_types:
                    self.issue(f'Unsupported Screen property {v}', node, 'Unsupported')
                return screen_types.get(v, UNKNOWN)
            if base.kind == "Control":
                if base.name == "App":
                    return {"Width": NUMBER, "Height": NUMBER, "ActiveScreen": FxType("Control"), "SizeBreakpoints": tabular(record({"Value": NUMBER})),
                        "Theme": OPEN_RECORD}.get(v, UNKNOWN)
                return self.property_type(base.control or self.controls.get(base.name), v)
            if base.kind == "Table":
                row = base.row or OPEN_RECORD
                if v not in row.fields and v not in row.virtual and not row.open:
                    self.issue(f"Unknown field {v}", node, "Name")
                return tabular(record({v: row.fields.get(v, row.virtual.get(v, UNKNOWN))}))
            if base.kind == "Record":
                key = v if v in base.fields else base.aliases.get(v, v)
                if key not in base.fields and key not in base.virtual and not base.open:
                    self.issue(f"Unknown field {v}", node, "Name")
                return base.fields.get(key, base.virtual.get(key, UNKNOWN))
            if base.kind not in ("Blank", "Error", "Unknown"):
                self.issue(f"Cannot access {v} on {base.describe()}", node)
            return UNKNOWN
        if k == "unary":
            t = self.infer(c[0], scope)
            if t.kind in TEMPORAL_KINDS and v in ("-", "+"):
                return t
            if v in ('!', 'not'):
                self.require(t, BOOLEAN, c[0], v)
                return BOOLEAN
            self.require_numeric(t, c[0], v)
            return self.numeric_result([t])
        if k == "binary":
            a, b = self.infer(c[0], scope), self.infer(c[1], scope)
            if v == ";":
                if not scope.behavior:
                    self.issue("Behavior chains are not allowed in value formulas", node)
                return b
            if v in ("and", "or", "&&", "||"):
                self.require(a, BOOLEAN, c[0], v); self.require(b, BOOLEAN, c[1], v)
                return BOOLEAN
            if v in ("=", "<>", "<", ">", "<=", ">=", "in", "exactin"):
                enum=a if a.kind=='Enum' else b if b.kind=='Enum' else None
                other=b if enum is a else a
                if enum and v not in ('in','exactin'):
                    spec=ENUM_CATALOG[enum.name]
                    if other.kind=='Enum' and other.name!=enum.name or other.kind not in ('Enum','Blank','Error','Unknown') and (not (spec['to_backing'] or spec['from_backing']) or other.kind not in ({'Number','Decimal'} if spec['kind']=='Number' else {'Text'})):
                        self.issue('Incompatible enum comparison',node)
                    if v in ('<','>','<=','>=') and not spec['compare']:self.issue(f'{enum.name} does not support ordered comparisons',node)
                return BOOLEAN
            if v == "&":
                for t in (a, b):
                    if t.kind in ("Record", "Table", "Control", "Screen"):
                        self.issue("Cannot concatenate a record, table or control", node)
                namespace=concatenate_namespace((a,b))
                return FxType('Enum',name=namespace) if namespace else TEXT
            if v in ('+', '-') and (a.kind in TEMPORAL_KINDS or b.kind in TEMPORAL_KINDS):
                if a.kind in TEMPORAL_KINDS and b.kind in TEMPORAL_KINDS:
                    if v == '-':
                        if a.kind == 'Time' and b.kind != 'Time':
                            self.issue('Cannot subtract a date from a time', node)
                        return NUMBER
                    if a.kind != 'Time' and b.kind != 'Time':
                        self.issue('Cannot add two dates', node)
                    return TIME if a.kind == b.kind == 'Time' else DATETIME
                self.require(b if a.kind in TEMPORAL_KINDS else a, NUMBER, c[1] if a.kind in TEMPORAL_KINDS else c[0], v)
                return a if a.kind in TEMPORAL_KINDS else b
            self.require_numeric(a, c[0], v); self.require_numeric(b, c[1], v)
            return NUMBER if v == "^" else self.numeric_result([a, b])
        if k == "call":
            return self.call(node, scope)
        return UNKNOWN

    def row_scope(self, source_node, t, scope):
        row = t.row if t.kind == "Table" else t if t.kind == "Record" else OPEN_RECORD
        row = row or OPEN_RECORD
        frame = ScopeFrame({**{logical:row.fields[display] for logical,display in row.aliases.items() if display in row.fields}, **row.fields, "ThisRecord": t if t.kind == 'Dynamic' else row}, open_schema=row.open)
        source = source_node
        if source.kind == "alias":
            frame = ScopeFrame({call_name(source.children[1]): t if t.kind == 'Dynamic' else row}, aliased=True)
            source = source.children[0]
        frame.sources = {call_name(source): row}
        return scope.child(frame)

    def call(self, node, scope):
        from .fx import ARITY, BEHAVIOR_FUNCTIONS, BUILTINS
        name = call_name(node.children[0])
        args = node.children[1:]
        n = len(args)
        e = lambda i, s=scope: self.infer(args[i], s) if i < n else BLANK
        if name in self.runtime.fx.definitions and self.runtime.fx.definitions[name].params is not None:
            d = self.runtime.fx.definitions[name]
            if d.behavior and (not scope.behavior or scope.function_pure):
                self.issue(f"Behavior function {name} requires a behavior formula", node)
            if scope.component:
                from .components import access_app_scope
                if not access_app_scope(self.runtime.project, scope.component):
                    self.issue(f"Component cannot access app function {name}; enable AccessAppScope or pass an event", node, "Name")
            if n != len(d.params):
                self.issue(f"{name} expects {len(d.params)} arguments", node)
            for arg, (_, typ) in zip(args, d.params):
                self.require_function(self.infer(arg, scope), self.declared_type(typ), arg, name)
            return self.declared_type(d.returns)
        if name not in BUILTINS:
            if "." in (name or ""):
                callback = self.infer(node.children[0], scope)
                for arg in args:
                    self.infer(arg, scope)
                if callback.kind != "Callable":
                    self.issue(f"Unsupported function {name}", node, "Unsupported")
                    return UNKNOWN
                from .components import component_definition, custom_parameters, property_kind, required_parameters, arity_message
                control_name, prop = callback.name.rsplit(".", 1)
                definition = component_definition(self.runtime.project, callback.control or self.controls[control_name])
                custom = definition.raw["CustomProperties"][prop]
                try:
                    params = custom_parameters(custom)
                    minimum = required_parameters(custom)
                except FxError as error:
                    self.issue(error.message, node, error.kind)
                    return UNKNOWN
                if not minimum <= len(args) <= len(params):
                    self.issue(f"{name} {arity_message(custom)}", node)
                for arg, (_, spec) in zip(args, params):
                    self.require_component(self.infer(arg, scope), self.parameter_type(spec), arg, name)
                if property_kind(custom) in ("Event", "Action") and not scope.behavior:
                    self.issue("Component actions and events require a behavior formula", node)
                return self.component_type(callback.control or self.controls[control_name], prop)
            self.issue(f"Unsupported function {name}", node, "Unsupported")
            return UNKNOWN
        minimum, maximum = ARITY.get(name, (1, 1))
        if n < minimum or maximum is not None and n > maximum:
            self.issue(f"{name} expects {minimum}" + (f"–{maximum}" if maximum != minimum else "") + " arguments", node)
            return UNKNOWN
        from .locale_tables import FUNCTIONS as LOCALE_TABLE_FUNCTIONS
        if name in LOCALE_TABLE_FUNCTIONS:
            return BOOLEAN if name == 'Clock.IsClock24' else tabular(record({'Value': TEXT}))
        if name in ('IsMatch','Match','MatchAll'):
            from .regex_fx import bind
            return bind(self,node,scope)
        if name in ('ParseJSON','AsType','IsType'):
            self.require(e(0), TEXT if name == 'ParseJSON' else FxType('Dynamic'), args[0], name)
            if n == 1:
                return FxType('Dynamic')
            try:
                result = self.type_spec(args[1])
                from .json_fx import validate_json_type
                validate_json_type(result)
            except FxError as error:
                self.issue(error.message, args[1], error.kind)
                return UNKNOWN
            return BOOLEAN if name == 'IsType' else result
        if name in ('ColumnNames','Column'):
            self.require(e(0), FxType('Dynamic'), args[0], name)
            if n > 1:
                self.require(e(1), TEXT, args[1], name)
            return tabular(record({'Value':TEXT})) if name == 'ColumnNames' else FxType('Dynamic')
        if name == 'JSON':
            if not scope.behavior:
                self.issue('JSON is only allowed in behavior formulas', node)
            for arg in args:
                self.infer(arg, scope)
            if n>1 and self.runtime.environment.get('enum_mode')=='strong':self.require_enum(e(1),'JSONFormat',args[1],'JSON options')
            return TEXT
        if name in ("Type", "RecordOf"):
            self.issue(f"{name} is only valid in a type declaration", node)
            return UNKNOWN
        if name == 'Decimal' and self.runtime.fx.number_mode != 'decimal':
            self.issue('Decimal requires the optional Decimal host mode; canvas apps use Float numbers', node, 'Unsupported')
        if name == 'Patch':
            from .patch import bind
            return bind(self,node,scope)
        if name in BEHAVIOR_FUNCTIONS and not scope.behavior:
            self.issue("Behavior functions are not allowed in a value property", node)
        if name in ('Remove','RemoveIf'):
            from .removal import bind
            return bind(self,node,scope,name)
        if name == 'SetFocus':
            from .focus import validate_target
            target_type = e(0)
            if target_type.kind not in ('Control', 'Unknown'):
                self.issue('SetFocus requires a control', args[0])
            target = target_type.control if target_type.kind == 'Control' else None
            if target:
                try:
                    validate_target(target)
                    root = target
                    while root.parent:
                        root = root.parent
                    if scope.screen and root.name != scope.screen and not scope.component:
                        self.issue('SetFocus cannot target a control on another screen', args[0], 'Validation')
                except FxError as error:
                    self.issue(error.message, args[0], error.kind)
            return VOID
        if name == "Select":
            target_type = e(0)
            target = target_type.control or self.controls.get(target_type.name) if target_type.kind == "Control" else None
            if target_type.kind not in ("Control", "Unknown"):
                self.issue("Select requires a control", args[0])
            if target and target.family == 'ModernLink':
                self.issue('Select does not support ModernLink', args[0], 'Unsupported')
            if n > 1:
                self.require(e(1), NUMBER, args[1], "Select gallery row")
                if target and target.family != "Gallery":
                    self.issue("Select row arguments require a gallery", args[0])
            if n > 2 and args[2].kind == "name" and target:
                def contains(control):
                    return any(c.name == args[2].value or contains(c) for c in control.children)
                if not contains(target):
                    self.issue("Select child must belong to the requested gallery template", args[2], "Name")
            elif n > 2:
                e(2)
            return VOID
        if name in ("Set", "Collect", "ClearCollect", "Clear"):
            target = call_name(args[0])
            for arg in args[1:]:
                self.infer(arg, scope)
            if name == "Set" and n > 1:
                values = self.storage(scope, "variables")
                if self.inferring_assignments:
                    values[target] = merge(values.get(target, UNKNOWN), e(1))
                else:
                    self.require(e(1), values.get(target, UNKNOWN), args[1], f"Set({target})")
            if name in ("Collect", "ClearCollect") and self.inferring_assignments:
                rows = BLANK
                for arg in args[1:]:
                    t = self.infer(arg, scope)
                    rows = merge(rows, t.row or OPEN_RECORD if t.kind == "Table" else t if t.kind == "Record" else record({"Value": t}))
                values = self.storage(scope, "collections")
                values[target] = merge(values.get(target, tabular()), tabular(rows))
            return self.storage(scope, "collections").get(target, VOID) if name in ("Collect", "ClearCollect") else VOID
        if name == "UpdateContext":
            if scope.component:
                self.issue("UpdateContext is not supported inside components", node)
            e(0)
            return VOID
        if name in ("If", "Switch", "IfError", "Coalesce"):
            results = []
            if name == "Coalesce":
                results = [e(i) for i in range(n)]
            elif name == "If":
                for i in range(0, n - 1, 2):
                    if e(i).kind not in ('Number', 'Decimal'):
                        self.require(e(i), BOOLEAN, args[i], "If condition")
                    results.append(e(i + 1))
                if n % 2:
                    results.append(e(n - 1))
            elif name == "Switch":
                e(0)
                for i in range(1, n - 1, 2):
                    e(i); results.append(e(i + 1))
                if n % 2 == 0:
                    results.append(e(n - 1))
            else:
                from .app_errors import scope_type
                error_scope=scope.child(scope_type())
                for i in range(0, n - 1, 2):
                    results.extend([e(i), e(i + 1, error_scope)])
                if n % 2:
                    results.append(e(n - 1))
                # The final success/default expression determines the result
                # type; error replacements are coerced only if executed.
                result = e(n - 1 if n % 2 else n - 2)
                if result.kind not in ("Error", "Blank", "Unknown"):
                    return result
            result = BLANK
            for t in results:
                merged=merge(result,t)
                if merged.kind=='Unknown' and 'Enum' in (result.kind,t.kind):self.issue('Incompatible enum branch types',node)
                result=merged
            return result
        if name in ('Update', 'UpdateIf'):
            target = e(0)
            if target.kind not in ('Table', 'Unknown'):
                self.issue(name + ' requires a mutable table', args[0])
            row = target.row or OPEN_RECORD
            source = args[0].children[0] if args[0].kind == 'alias' else args[0]
            source_name = call_name(source)
            collections = self.storage(scope, 'collections')
            from .components import access_app_scope
            local = scope.component and not access_app_scope(self.runtime.project, scope.component)
            definition = self.runtime.store.definitions.get(source_name) if not local else None
            if source.kind not in ('name', 'global') or not definition and source_name not in collections:
                self.issue(name + ' requires a mutable collection or local data source', args[0], 'InvalidArgument')
            def check_change(index, scoped):
                change = e(index, scoped)
                if change.kind not in ('Record', 'Blank', 'Error', 'Unknown'):
                    self.issue(name + ' requires a record', args[index])
                for key, field in change.fields.items():
                    canonical = key if key in row.fields else row.aliases.get(key, key)
                    if canonical not in row.fields and not row.open:
                        self.issue('Unknown update column ' + key, args[index], 'Name')
                    elif canonical in row.fields and not function_compatible(field, row.fields[canonical]):
                        self.issue(key + ': incompatible update field type', args[index])
                    if definition:
                        internal = self.runtime.store.internal_name(source_name, key)
                        if name == 'UpdateIf':
                            if internal in ('ID','Created','Modified') or definition['fields'].get(internal, {}).get('x-ms-permission') == 'read-only':
                                self.issue(key + ' is read-only', args[index], 'ReadOnlyValue')
            if name == 'Update':
                self.require(e(1), OPEN_RECORD, args[1], 'Update old record')
                check_change(1, scope)
                check_change(2, scope)
                if n == 4:
                    self.require(e(3), TEXT, args[3], 'Update flag')
            else:
                if (n - 1) % 2:
                    self.issue('UpdateIf requires condition/change-record pairs', node)
                scoped = self.row_scope(args[0], target, scope)
                for index in range(1, n - 1, 2):
                    self.require(e(index, scoped), BOOLEAN, args[index], 'UpdateIf condition')
                    check_change(index + 1, scoped)
            return target
        if name == "With":
            rec = e(0)
            self.require(rec, OPEN_RECORD, args[0], "With")
            return e(1, self.row_scope(args[0], rec, scope))
        if name == "Table":
            if n == 1 and e(0).kind == 'Dynamic':
                return tabular(record({'Value':FxType('Dynamic')}))
            row = BLANK
            for i in range(n):
                t = e(i)
                if t.kind == "Table":
                    t = t.row or OPEN_RECORD
                elif t.kind not in ("Record", "Blank", "Unknown", "Error"):
                    self.issue("Table expects records or tables", args[i])
                row = self.table_union(row, t, args[i])
            return tabular(row if row.kind == "Record" else OPEN_RECORD)
        if name in SHAPING_FUNCTIONS:
            t = e(0)
            if t.kind not in ('Record', 'Table', 'Blank', 'Unknown', 'Error'):
                self.issue(f'{name} expects a record or table', args[0])
            row = t.row if t.kind == 'Table' else t if t.kind == 'Record' else OPEN_RECORD
            row = row or OPEN_RECORD
            if name in ('AddColumns', 'RenameColumns') and n % 2 == 0:
                self.issue(f'{name} expects column pairs', node, 'Validation')
                return UNKNOWN
            names = args[1::2] if name == 'AddColumns' else args[1:]
            try:
                operations = shape_columns(name, row.physical_fields(), names, row.open, row.aliases)
            except FxError as error:
                invalid = next((arg for arg in names if arg.start == error.start), node)
                if invalid.kind == 'member':
                    # Static column parameters bind outside the row scope. An
                    # invalid member expression can therefore also contain an
                    # unknown identifier, as in native AddColumns(..., b.d,...).
                    self.infer(invalid, scope)
                self.issue(error.message, invalid, error.kind)
                return UNKNOWN
            fields = row.physical_fields()
            if name == 'AddColumns':
                row_scope = self.row_scope(args[0], t, scope)
                for (_, col), formula in zip(operations, args[2::2]):
                    fields[col] = self.infer(formula, row_scope)
            elif name == 'ShowColumns':
                fields = {old: fields.get(old, UNKNOWN) for old, _ in operations}
            elif name == 'DropColumns':
                fields = {key: value for key, value in fields.items() if key not in dict(operations)}
            else:
                renamed = dict(operations)
                fields = {renamed.get(key, key): value for key, value in fields.items()}
            # Keep aliases only while their physical field still exists.
            # Renamed/dropped columns must not resolve through stale source metadata.
            aliases = {logical: physical for logical, physical in row.aliases.items() if physical in fields}
            result = record(fields, row.open and name != 'ShowColumns', aliases)
            return result if t.kind == 'Record' else tabular(result)
        if name == 'Search':
            from .search_fx import bind
            return bind(self, args, scope)
        if name in ('GroupBy', 'Ungroup'):
            from .grouping_fx import bind
            return bind(self, name, args, scope)
        if name=='Shuffle':
            typ=e(0)
            self.require(typ,tabular(),args[0],name)
            return typ if typ.kind=='Table' else tabular()
        if name=='Rand':return NUMBER
        if name=='RandBetween':
            types=[e(i) for i in range(n)]
            for i,typ in enumerate(types):self.require_numeric(typ,args[i],name)
            return self.numeric_result(types)
        scoped = {"Filter", "LookUp", "ForAll", "CountIf", "Sum", "Average", "Min", "Max", "StdevP", "VarP", "Concat", "Distinct", "Sort"}
        if name in scoped:
            t = e(0)
            statistics = name in ('StdevP', 'VarP')
            aggregates = name in ('Sum', 'Average', 'Min', 'Max')
            from .aggregates_fx import result_kind
            if name in ("Sum", "Average", "Min", "Max", "StdevP", "VarP") and t.kind != "Table":
                result = FxType(result_kind(name, t.kind, self.runtime.fx.number_mode)) if aggregates else NUMBER
                for i in range(n):
                    if result.kind in TEMPORAL_KINDS:
                        self.require_function(e(i), result, args[i], name)
                    else:
                        self.require_numeric(e(i), args[i], name)
                return result
            if (statistics or aggregates) and n != 2:
                self.issue(f'{name} table overload requires a table and one formula', node)
                return NUMBER
            if not (name == 'ForAll' and t.kind == 'Dynamic'):
                self.require(t, tabular(), args[0], name)
            row_scope = self.row_scope(args[0], t, scope)
            row = t.row or OPEN_RECORD
            result = e(1, row_scope)
            if name in ("Filter", "LookUp", "CountIf"):
                for i in range(1, 2 if name == "LookUp" else n):
                    predicate_type=e(i,row_scope)
                    if name=='CountIf' and predicate_type.kind in ('Text','Number','Decimal'):
                        continue
                    self.require(predicate_type, BOOLEAN, args[i], name + " predicate")
                return e(2, row_scope) if name == "LookUp" and n == 3 else row if name == "LookUp" else self.default_number() if name == "CountIf" else t
            if name == "ForAll":
                return tabular(result if result.kind == "Record" else result.row if result.kind == "Table" else record({"Value": result}))
            if name == "Distinct":
                return tabular(record({"Value": result}))
            if name == "Concat":
                if n > 2:
                    e(2)
                return TEXT
            if name == "Sort":
                if result.kind in ('Record', 'Table', 'Control', 'Screen', 'Callable'):
                    self.issue('Sort keys must be scalar values', args[1])
                if n > 2:
                    self.require_enum(e(2), 'SortOrder', args[2], 'Sort order')
                return t
            if statistics:
                self.require_numeric(result, args[1], name)
                return NUMBER
            self.require_numeric(result, args[1], name)
            return FxType(result_kind(name, result.kind, self.runtime.fx.number_mode))
        if name in ('Count','CountA'):
            from .counts_fx import bind
            return bind(self,name,args,scope)
        if name in ("First", "Last", "Index", "FirstN", "LastN", "CountRows", "IsEmpty", "SortByColumns"):
            t = e(0)
            if t.kind == 'Dynamic' and name != 'SortByColumns':
                for i in range(1,n):
                    self.require_numeric(e(i), args[i], name)
                return self.default_number() if name == 'CountRows' else BOOLEAN if name == 'IsEmpty' else t
            self.require(t, tabular(), args[0], name)
            row = t.row or OPEN_RECORD
            if name == "SortByColumns":
                for i in range(1, n, 2):
                    arg = args[i]
                    col = None
                    dynamic_name = arg.kind == 'name' and arg.value not in row.fields and (any(arg.value in frame and frame[arg.value].kind == 'Text' for frame in scope.frames) or self.variables.get(arg.value, self.globals.get(arg.value, UNKNOWN)).kind == 'Text')
                    if arg.kind == 'name' and not dynamic_name or arg.kind == 'literal' and isinstance(arg.value, str):
                        try:
                            col = column_name(arg)
                        except FxError as error:
                            self.issue(error.message, arg, error.kind)
                        if col not in row.fields and not row.open:
                            self.issue(f"Unknown column {col}", arg, "Name")
                    else:
                        self.require(e(i), TEXT, arg, 'Sort column')
                    if col in row.fields and row.fields[col].kind in ('Record', 'Table', 'Control', 'Screen', 'Callable'):
                        self.issue('Sort keys must be scalar values', arg)
                    if i + 1 < n:
                        order = e(i + 1)
                        if order.kind == 'Table':
                            if n != 3:
                                self.issue('Sort order tables require exactly one column', args[i + 1])
                            order_row = order.row or OPEN_RECORD
                            if len(order_row.fields) != 1 and not order_row.open:
                                self.issue('Sort order must be a single-column table', args[i + 1])
                            if len(order_row.fields) == 1:
                                order_type = next(iter(order_row.fields.values()))
                                if order_type.kind in ('Record', 'Table', 'Control', 'Screen', 'Callable'):
                                    self.issue('Sort order values must be scalar', args[i + 1])
                                if col in row.fields:
                                    self.require(order_type, row.fields[col], args[i + 1], 'Sort order values')
                        else:
                            self.require_enum(order, 'SortOrder', args[i + 1], 'Sort order')
                return t
            for i in range(1, n):
                self.require_numeric(e(i), args[i], name)
            return row if name in ("First", "Last", "Index") else self.default_number() if name == "CountRows" else BOOLEAN if name == "IsEmpty" else t
        if name == "Errors":
            from .data_errors import bind
            return bind(self,node,scope)
        if name == "Choices":
            arg = args[0]
            if arg.kind == 'member' and arg.children[0].kind in ('name', 'global') and arg.children[0].value in self.runtime.store.definitions:
                source = self.infer(arg.children[0], scope)
                row = source.row or OPEN_RECORD
                if arg.value not in row.fields and not row.open:
                    self.issue(f'Unknown column {arg.value}', arg, 'Name')
                if n == 2:
                    self.require(e(1), TEXT, args[1], 'Choices text filter')
                t = row.fields.get(arg.value, OPEN_RECORD)
                return t if t.kind == "Table" else tabular(t if t.kind == "Record" else record({"Value": TEXT}))
            self.issue('Choices requires a direct data source column', arg)
            return tabular()
        if name == "Defaults":
            typ = e(0)
            if typ.kind not in ('Table','Unknown'):
                self.issue('Defaults requires a table or data source',args[0])
            return typ.row or OPEN_RECORD
        if name == 'Validate':
            from .validation import bind
            return bind(self, node, scope)
        if name == "DataSourceInfo":
            from .datasource_info import bind
            return bind(self, node, scope)
        if name=='Boolean' and n and e(0).kind=='Enum':
            self.issue('Boolean does not accept enum values',args[0])
            return BOOLEAN
        if name=='Text' and n>1 and e(1).kind=='Enum':self.require_enum(e(1),'DateTimeFormat',args[1],'Text format')
        if name in ('Weekday', 'WeekNum', 'ISOWeekNum'):
            date_type = e(0)
            table_input = date_type.kind == 'Table' and name != 'Weekday'
            if table_input:
                row = date_type.row or OPEN_RECORD
                try:
                    column = single_column(row.fields, row.open and not empty_table_literal(args[0]), args[0].start, args[0].end)
                except FxError as error:
                    self.issue(error.message, args[0], error.kind)
                    column = None
                date_type = row.fields.get(column, UNKNOWN)
            if date_type.kind not in TEMPORAL_KINDS | {'Text', 'Number', 'Decimal', 'Blank', 'Error', 'Unknown'}:
                self.issue(f'{name}: expected a date/time value', args[0])
            if n > 1:
                if self.runtime.environment.get('enum_mode') == 'strong':
                    self.require_enum(e(1), 'StartOfWeek', args[1], name + ' start of week')
                else:
                    self.require_numeric(e(1), args[1], name + ' start of week')
            result = self.default_number()
            return tabular(record({'Value': result})) if table_input else result
        if name in ('EDate', 'EOMonth'):
            self.require_function(e(0), DATETIME, args[0], name + ' date/time')
            self.require_numeric(e(1), args[1], name + ' months')
            return DATE
        if name=='DateAdd' and n>1:self.require_numeric(e(1),args[1],name+' amount')
        if name in ('DateAdd','DateDiff') and n>2:self.require_enum(e(2),'TimeUnit',args[2],name+' unit')
        if name in ("EncodeHTML", "EncodeUrl", "PlainText"):
            actual=e(0)
            if actual.kind in ("Record","Table","Control","Screen","Callable","Void"):
                self.issue(f"{name}: expected a text-coercible scalar, received {actual.describe()}",args[0])
            return TEXT
        if name in SINGLE_COLUMN_OVERLOADS:
            types = [e(i) for i in range(n)]
            elements = []
            for i, typ in enumerate(types):
                element = typ
                if typ.kind == 'Table':
                    row = typ.row or OPEN_RECORD
                    try:
                        column = single_column(row.fields, row.open and not empty_table_literal(args[i]), args[i].start, args[i].end)
                    except FxError as error:
                        self.issue(error.message, args[i], error.kind)
                        column = None
                    element = row.fields.get(column, UNKNOWN)
                if name in TEXT_OVERLOADS and i not in NUMERIC_ARGUMENTS.get(name,set()):
                    if element.kind in ('Record', 'Table', 'Control', 'Screen', 'Callable', 'Void'):
                        self.issue(f'{name}: expected a text-coercible scalar, received {element.describe()}', args[i])
                else:
                    self.require_numeric(element, args[i], name)
                elements.append(element)
            result = NUMBER if name in FLOAT_FUNCTIONS or name=='Find' else self.default_number() if name in ('Len','Hex2Dec') else TEXT if name in TEXT_OVERLOADS else self.numeric_result(elements[:1])
            if name=='Concatenate':
                namespace=concatenate_namespace(elements)
                if namespace:result=FxType('Enum',name=namespace)
            return tabular(record({'Value': result})) if any(typ.kind == 'Table' for typ in types) else result
        if name in SCALAR_FLOAT_FUNCTIONS:
            for i in range(n):self.require_numeric(e(i),args[i],name)
            return NUMBER
        for i in range(n):
            e(i)
        if name in ("Blank",):
            return BLANK
        if name == "Error":
            return ERROR
        if name in ("IsBlank", "IsBlankOrError", "IsError", "IsNumeric", "And", "Or", "Not", "Boolean", "StartsWith", "EndsWith"):
            if name in ("And", "Or", "Not"):
                for i in range(n):
                    self.require(e(i), BOOLEAN, args[i], name)
            return BOOLEAN
        if name in ("Text", "Left", "Right", "Mid", "Substitute", "Concatenate", "Char", "Language", "Param", "GUID"):
            if name in ("Left", "Right", "Mid", "Substitute"):
                self.require(e(0), TEXT, args[0], name)
            return FxType("GUID") if name == "GUID" else TEXT
        if name in ('Decimal', 'Float', 'Value'):
            if e(0).kind=='Enum' and ENUM_CATALOG[e(0).name]['kind']=='Number':pass
            else:self.require_numeric(e(0), args[0], name)
            return DECIMAL if name == 'Decimal' else NUMBER if name == 'Float' else self.default_number()
        if name == 'Mod':
            for i in range(n):
                self.require_numeric(e(i), args[i], name)
            return self.numeric_result([e(i) for i in range(n)])
        if name in ('Year', 'Month', 'Day', 'Hour', 'Minute', 'Second', 'DateDiff', 'Find'):
            if name in ('Year', 'Month', 'Day', 'Hour', 'Minute', 'Second') and e(0).kind not in TEMPORAL_KINDS | {'Text', 'Number', 'Decimal', 'Blank', 'Error', 'Unknown'}:
                self.issue(f'{name}: expected a date/time value', args[0])
            return self.default_number()
        if name in ("Today", "Date", "DateValue"):
            return DATE
        if name in ("Time", "TimeValue"):
            return TIME
        if name == 'DateAdd':
            self.require_function(e(0), DATETIME, args[0], name + ' date/time')
            return e(0) if e(0).kind in TEMPORAL_KINDS else DATETIME
        if name in ("Now", "DateTime", "DateTimeValue"):
            return DATETIME
        if name in ("RGBA", "ColorValue", "ColorFade"):
            return COLOR
        if name == "User":
            return record({"Email": TEXT, "FullName": TEXT, "Image": TEXT, "EntraObjectId": FxType("GUID")})
        if name == "Sequence":
            return tabular(record({"Value": self.default_number()}))
        if name == "Split":
            for i in range(n):
                if e(i).kind in ('Record','Table','Control','Screen','Callable','Void'):
                    self.issue('Split requires text-coercible scalar arguments',args[i])
            return tabular(record({"Value": TEXT}))
        if name == 'Navigate' and n:
            target = e(0)
            if not compatible(target, FxType('Screen')):
                self.issue(f'Navigate requires a Screen, received {target.describe()}', args[0])
        if name in ("Navigate", "Back", "Notify"):
            return BOOLEAN
        return VOID if name in BEHAVIOR_FUNCTIONS else UNKNOWN

    def prepare(self, formulas):
        # All definitions/assignments are registered before resolution. Inference
        # uses bounded fixed-point passes, never app startup or list reads.
        for _, _, node, scope in formulas:
            for n in walk(node):
                if n.kind != "call":
                    continue
                name, args = call_name(n.children[0]), n.children[1:]
                if name == "Set" and args:
                    self.storage(scope, "variables").setdefault(call_name(args[0]), UNKNOWN)
                if name in ("Collect", "ClearCollect", "Clear") and args:
                    self.storage(scope, "collections").setdefault(call_name(args[0]), tabular())
                if name == "UpdateContext" and args and args[0].kind == "record":
                    self.context_variables.setdefault(scope.screen, {}).update({k: UNKNOWN for k, _ in args[0].value})
        for _ in range(5):
            self.named.clear()
            for _, _, node, scope in formulas:
                self.inferring_assignments = True
                try:
                    self.infer(node, scope)
                finally:
                    self.inferring_assignments = False
                for n in walk(node):
                    if n.kind != "call":
                        continue
                    name, args = call_name(n.children[0]), n.children[1:]
                    if name == "Set" and len(args) == 2:
                        target = call_name(args[0])
                        variables = self.storage(scope, "variables")
                        variables[target] = merge(variables.get(target, UNKNOWN), self.infer(args[1], scope))
                    if name in ("Collect", "ClearCollect") and len(args) > 1:
                        target = call_name(args[0])
                        t = BLANK
                        for arg in args[1:]:
                            t = merge(t, self.infer(arg, scope))
                        if t.kind != "Table":
                            t = tabular(t if t.kind == "Record" else record({"Value": t}))
                        collections = self.storage(scope, "collections")
                        collections[target] = merge(collections[target], t)
                    if name == "UpdateContext" and args and args[0].kind == "record":
                        for key, body in args[0].value:
                            self.context_variables[scope.screen][key] = merge(self.context_variables[scope.screen][key], self.infer(body, scope))
        self.named.clear()

    def bind(self, node, scope=None, owner=None):
        self.owner, self.reporting = owner, True
        try:
            return self.infer(node, scope or BindScope())
        finally:
            self.reporting, self.owner = False, None

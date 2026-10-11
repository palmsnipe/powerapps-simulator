"""Canvas runtime: control scopes, events, reactive values, forms, diagnostics."""
from __future__ import annotations

from decimal import Decimal
from .numeric import decimal_text
from dataclasses import replace
from datetime import date, datetime
import json
import math
import hashlib
from uuid import uuid4

from .temporal import Temporal
from .controls import COMMON, DEFAULTS, RENDER_PROPERTIES, SUPPORTED, RESETTABLE, SINGLE_SELECT, NUMERIC_CONTROL_PROPERTIES, responsive_default, contract_errors
from .classic_inputs import TEXT_INPUTS,CLASSIC_INPUTS,CLASSIC_SELECTORS,CLASSIC_BOOLEAN,SLIDERS,DATE_PICKERS
from .classic_combobox import COMBOBOXES, selected_record
from .listbox import LISTBOXES,OUTPUTS as LIST_OUTPUTS
from .components import ComponentCallable, access_app_scope, component_definition, custom_parameters, required_parameters, validate_kind, result_type_name
from .errors import error_number
from .fx import BUILTINS, Context, Evaluator, ENUMS, table, text, truth
from .source import Control
from .store import DataSource, ListStore
from .syntax import FxError, call_name, walk


def serial(value):
    from .enum_fx import EnumValue
    if isinstance(value,EnumValue):return value.json()
    from .json_fx import Dynamic, JsonNumber, json_text
    if isinstance(value,Dynamic):
        return {'$dynamic':serial(value.value),'$json':json_text(value)}
    if isinstance(value,JsonNumber):
        return {'$jsonNumber':value.lexeme}
    if isinstance(value, Decimal):
        return {"$decimal": decimal_text(value)}
    if isinstance(value, FxError):
        return {"$error": serial(value.record())}
    if isinstance(value, DataSource):
        return {"$datasource": value.name}
    if isinstance(value, Ref):
        return {"$control": value.name, "path": value.path}
    if isinstance(value, AppRef):
        return {"$app": True}
    if isinstance(value, (date, datetime, Temporal)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: serial(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serial(v) for v in value]
    if callable(value):
        return "<event>"
    return value


# Fluent Web Light brand slots, mapped to the canvas theme property names.
# https://microsoft.github.io/fluentui-design-tokens/ (Global-Color-Brand-10..160)
# This is the built-in fallback, not a recovered custom app palette.
THEME_COLORS = dict(zip(
    [f"Darker{n}" for n in range(70, 0, -10)] + ["Primary"] +
    [f"Lighter{n}" for n in range(10, 90, 10)],
    ["#061724", "#082338", "#0a2e4a", "#0c3b5e", "#0e4775", "#0f548c", "#115ea3", "#0f6cbd",
     "#2886de", "#479ef5", "#62abf5", "#77b7f7", "#96c6fa", "#b4d6fa", "#cfe4fa", "#ebf3fc"]))


def default_theme():
    return {"Name": "PowerAppsTheme", "Colors": dict(THEME_COLORS), "Font": "Segoe UI"}


class AppRef:
    def __init__(self, runtime):
        self.runtime = runtime

    def property(self, name, ctx):
        return self.runtime.reactive.unit(('app',name),lambda:self._property(name,ctx),
            lambda:self.runtime.project.app.get(name))

    def _property(self, name, ctx):
        r = self.runtime
        values = {"Width": r.viewport["width"], "Height": r.viewport["height"],
            "ActiveScreen": r.screens.get(r.active_screen), "SizeBreakpoints": [{"Value": n} for n in [600, 900, 1200]]}
        if name in values:
            return values[name]
        if name in r.project.app:
            key = ("App", name)
            if key in r.evaluating:
                raise FxError(f"App property cycle: App.{name}", "Cycle")
            r.evaluating.add(key)
            try:
                from .expressions import app_expression
                return r.fx.evaluate(r.project.app[name], app_expression(r,name).context(ctx))
            finally:
                r.evaluating.discard(key)
        if name == "Theme":
            return default_theme()
        raise FxError(f"Unknown App property {name}")


class Ref:
    def __init__(self, runtime, control, path, parent=None, item=None, frames=None, scope=None, component=None):
        self.runtime, self.control, self.path, self.parent = runtime, control, path, parent
        self.item, self.frames = item, frames or []
        self.scope, self.component = scope if scope is not None else {}, component
        self.children = []
        self.component_error = None
        runtime.refs[path] = self

    @property
    def name(self):
        return self.control.name

    @property
    def family(self):
        return self.control.family

    @property
    def state(self):
        from .reactivity import ControlState
        value=self.runtime.control_state.get(self.path)
        if not isinstance(value,ControlState):
            value=ControlState(self.runtime,self.path,value or {})
            self.runtime.control_state[self.path]=value
        return value

    def context(self, behavior=False):
        item, frames = self.item, self.frames
        probe=None;item_key=('item',self.path)
        if item is not None:
            probe=lambda:self.runtime.refs.get(self.path,self).item
        if behavior and self.family == "Gallery":
            # Select(Parent) queues the gallery's OnSelect after a template
            # child has selected its row. That event must see the selected item.
            item = self.property("Selected")
            from .galleries import row_frames
            frames = row_frames(self,item)
            probe=lambda:self.property("Selected")
        if item is None:
            ancestor = self.parent
            while ancestor:
                if ancestor.family in ("DataTable","ModernDataGrid"):
                    with self.runtime.reactive.untracked():item = ancestor.property("Selected")
                    probe=lambda ancestor=ancestor:ancestor.property('Selected')
                    break
                if ancestor.family == "Form":
                    with self.runtime.reactive.untracked():item = ancestor.property("Item", Context(self.runtime))
                    probe=lambda ancestor=ancestor:ancestor.property('Item',Context(self.runtime))
                    break
                ancestor = ancestor.parent
        return Context(self.runtime, frames=frames, self_ref=self, parent_ref=self.parent,
            item=item, behavior=behavior, control_scope=self.scope,
            component_ref=self if self.family == "CanvasComponent" else self.component,
            item_probe=probe,item_key=item_key)

    def host_context(self, behavior=False):
        # Input expressions and event callbacks belong to the consuming app.
        # Nested component hosts inherit their containing component's scope.
        return replace(self.context(behavior), component_ref=self.component,
            control_scope=self.parent.scope if self.parent else {})

    def expression(self,name):
        if self.family == 'ModernLink':
            from .modern_link import source_property
            name = source_property(self,name)
        from .expressions import property_expression
        return property_expression(self,name)

    def eval_raw(self,name,ctx=None):
        ctx=self.expression(name).context(ctx or self.context())
        def load():
            raw=self.raw_property(name)
            return self.runtime.fx.evaluate(str(raw),ctx) if isinstance(raw,str) and raw.startswith('=') else raw
        return self.runtime.reactive.unit(('formula',self.path,name),load,
            lambda:repr(self.raw_property(name)))

    def raw_property(self, name):
        if self.family == 'ModernLink' and name in ('URL','Url'):
            from .modern_link import source_property
            return self.control.properties.get(source_property(self,name), DEFAULTS['ModernLink']['URL'])
        definition = component_definition(self.runtime.project, self.control)
        custom = definition.raw.get("CustomProperties", {}).get(name) if definition else None
        if custom and validate_kind(custom) in ("Output", "Action"):
            return definition.properties.get(name, custom.get("Default", "=Blank()"))
        if custom and validate_kind(custom) == "Function" and custom.get("PropertyDefinition", custom.get("Direction", "Output")) != "Input" and custom.get("PropertyKind") != "InputFunction":
            return definition.properties.get(name, custom.get("Default", "=Blank()"))
        if name in self.control.properties:
            return self.control.properties[name]
        if self.family in ('Label','Rectangle','Circle','Star'):
            from .classic_display import default
            value=default(self,name)
            if value is not None:return value
        if self.family=='Classic/Button':
            from .classic_button import variant
            value=variant(self,name)
            if value is not None:return value
        if self.family=='ModernBadge' and self.control.version=='1.0.0' and self.runtime.project.config.get('form_factor')=='phone':
            if name in ('Width','LayoutMinWidth'):return '=88'
            if name in ('Height','LayoutMinHeight'):return '=44'
        if self.family == "CanvasComponent":
            definition = self.runtime.project.components.get(self.control.raw.get("ComponentName"))
            if definition:
                prop = definition.raw.get("CustomProperties", {}).get(name)
                if prop:
                    return prop.get("Default", "=Blank()")
                if name in definition.properties:
                    return definition.properties[name]
        if self.family in ('ComboBox','DropDown','Radio','ComboBoxDataField'):
            from .canvas_selectors import catalog
            versions=catalog()[self.family];defaults=versions.get(self.control.version,next(iter(versions.values())))['defaults']
            return defaults.get(name, '=false' if name=='Reset' else COMMON.get(name))
        if self.family in ('Text', 'FluentV8/Label'):
            from .canvas_text import catalog, LAYOUT
            versions = catalog()[self.family]
            defaults = versions.get(self.control.version, next(iter(versions.values())))['defaults']
            if self.family == 'FluentV8/Label' and name == 'OnSelect':
                from .galleries import implicit_select
                if implicit_select(self):return '=Select(Parent)'
            if self.automatic_parent:
                responsive = responsive_default(self.control, name)
                if responsive is not None:return responsive
            return defaults.get(name, COMMON.get(name) if name in LAYOUT else None)
        if self.family == 'Button':
            from .canvas_buttons import catalog
            versions = catalog();defaults = versions.get(self.control.version, next(iter(versions.values())))['defaults']
            if self.automatic_parent:
                responsive = responsive_default(self.control, name)
                if responsive is not None:return responsive
            return defaults.get(name, COMMON.get(name) if name in {'LayoutMinWidth','LayoutMinHeight','LayoutMaxWidth','LayoutMaxHeight','FillPortions','AlignInContainer'} else None)
        if self.family == 'TabList':
            from .canvas_tabs import catalog
            versions = catalog();defaults = versions.get(self.control.version, next(iter(versions.values())))['defaults']
            return defaults.get(name, '=false' if name == 'Reset' else COMMON.get(name))
        if self.family in ('Slider','Toggle'):
            from .canvas_scalars import catalog
            versions=catalog()[self.family];defaults=versions.get(self.control.version,next(iter(versions.values())))['defaults']
            return defaults.get(name, '=false' if name=='Reset' else COMMON.get(name))
        if self.family in ('TextInput','CheckBox'):
            from .canvas_inputs import catalog
            versions=catalog()[self.family];defaults=versions.get(self.control.version,next(iter(versions.values())))['defaults']
            return defaults.get(name, '=false' if name=='Reset' else COMMON.get(name))
        if self.family == 'DatePicker':
            from .canvas_dates import catalog
            versions = catalog();defaults = versions.get(self.control.version, next(iter(versions.values())))['defaults']
            return defaults.get(name, '=false' if name == 'Reset' else COMMON.get(name))
        if name in ('OnSelect', 'AcceptsFocus', 'TabIndex'):
            from .galleries import implicit_select
            if implicit_select(self):
                if name == 'OnSelect':
                    return '=Select(Parent)'
                if name == 'AcceptsFocus' and self.family.startswith('Modern'):
                    return '=true'
                if name == 'TabIndex' and self.family in ('Classic/Button', 'Label', 'Image', 'Toggle'):
                    return '=0'
        if self.family == 'ModernTextInput':
            if name == 'TriggerOutput' and any(a.family == 'Form' for a in self.runtime.ancestors(self)):
                return '=TriggerOutput.Delayed'
            if self.control.version == '1.0.0' and name == 'Type':
                return '=TextInputType.SingleLine'
        if self.family=='TypedDataCard' and self.parent and self.parent.family=='Form' and name=='Width':
            return '=Parent.Width/Max(1,Parent.NumberOfColumns)'
        if self.automatic_parent:
            responsive = responsive_default(self.control, name)
            if responsive is not None:
                return responsive
        if self.family=='ModernTabList':
            from .tablist import VERSION_DEFAULTS
            if name in VERSION_DEFAULTS.get(self.control.version,{}):return VERSION_DEFAULTS[self.control.version][name]
        if self.family=='Classic/ComboBox':
            from .classic_combobox import catalog
            override=catalog().get('version_default_overrides',{}).get(self.control.version,{})
            if name in override:return override[name]
        return DEFAULTS.get(self.family, {}).get(name, COMMON.get(name))

    @property
    def automatic_parent(self):
        return self.parent and self.parent.family == "GroupContainer" and self.parent.control.raw.get("Variant") == "AutoLayout"

    def intrinsic_dimension(self, name):
        key = (self.path, name)
        if key in self.runtime.intrinsic_measuring:
            raise FxError(f"Control property cycle: {self.name}.{name}", "Cycle")
        self.runtime.intrinsic_measuring.add(key)
        try:
            value = self._intrinsic_dimension(name)
            if value is None:
                return 0.0
            if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(float(value)):
                raise FxError(f"{self.name}.{name} requires a finite Number", "Type")
            return float(value)  # Layout pixels use Float in both numeric hosts.
        finally:
            self.runtime.intrinsic_measuring.remove(key)

    def _intrinsic_dimension(self, name):
        if name == 'Height' and self.family in ('Text', 'FluentV8/Label') and self.property('AutoHeight'):
            from .canvas_text import auto_height
            return auto_height(self)
        if name == 'Height' and self.family == 'ModernLink' and self.property('AutoHeight'):
            from .modern_link import auto_height
            return auto_height(self)
        if name=="Height" and self.family=="Label" and self.property("AutoHeight"):
            from .classic_display import auto_height
            return auto_height(self)
        if name == "Height" and self.family == "ModernText" and self.property("AutoHeight"):
            label = text(self.property("Text"))
            if not label:return self.property("PaddingTop")+self.property("PaddingBottom")
            width = max(1, self.property("Width") - self.property("PaddingLeft") - self.property("PaddingRight"))
            font_size = self.property("Size")
            chars = max(1, int(width / max(1, font_size * .55)))
            lines = sum(max(1, math.ceil(len(line) / chars)) for line in label.split("\n")) if self.property("Wrap") else 1
            return max(24, math.ceil(lines * font_size * 1.45 + self.property("PaddingTop") + self.property("PaddingBottom")))
        raw = self.raw_property(name)
        if name == "Height" and self.family == "HtmlViewer" and self.property("AutoHeight"):
            from .html_controls import auto_height,validate
            ctx = self.context()
            base = self.eval_raw(name,ctx)
            validate("Height",base)
            return auto_height(self,base)
        ctx = self.host_context() if self.family == "CanvasComponent" and name in self.control.properties else self.context()
        return self.eval_raw(name,ctx)

    def property(self,name,ctx=None):
        if '/row:' in self.path and self.runtime.refs.get(self.path) is not self:
            raise FxError('Gallery control instance no longer exists','Validation').located(self.path+'.'+name)
        from .reactivity import fingerprint
        def signature():
            # Gallery/template and grid caller records are explicit inputs to
            # an instance. Keeping their full value is conservative for now.
            current=self.runtime.refs.get(self.path,self)
            return (repr(current.raw_property(name)),fingerprint(current.item),
                    fingerprint(ctx.item) if ctx and self.family.endswith('Column') else None)
        def load():
            current=self.runtime.refs.get(self.path,self)
            return current._get_property(name,ctx)
        try:return self.runtime.reactive.unit(('property',self.path,name),load,signature,
            lambda:self.runtime.property_cache.pop((self.path,name),None))
        except FxError as error:raise error.located(self.path+'.'+name) from None

    def _get_property(self, name, ctx=None):
        if '/row:' in self.path and self.runtime.refs.get(self.path) is not self:
            raise FxError('Gallery control instance no longer exists', 'Validation')
        if self.component_error:
            raise self.component_error
        r = self.runtime
        if self.family in ('Text', 'FluentV8/Label'):
            from .canvas_text import guard
            guard(self, name)
        if self.family == 'Button':
            from .canvas_buttons import guard
            guard(self, name)
        if self.family == 'TabList':
            from .canvas_tabs import guard
            guard(self, name)
        if self.family in ('Slider','Toggle'):
            from .canvas_scalars import guard
            guard(self,name)
        if self.family == 'DatePicker':
            from .canvas_dates import guard
            guard(self, name)
        if self.family in ('ComboBox','DropDown','Radio','ComboBoxDataField'):
            from .canvas_selectors import guard
            guard(self,name)
        if self.family in ('TextInput','CheckBox'):
            from .canvas_inputs import spec,errors,LAYOUT
            s=spec(self);findings=errors(self.control)
            for p in ('Variant',name):
                if p in findings:raise FxError(findings[p],'Unsupported')
            allowed=set(s['types'])|LAYOUT|{e['Name'] for e in s['events']}|{'Reset','Name'}
            if name not in allowed:raise FxError(f'{self.control.kind} has no supported {name} property','Unsupported')
        if self.family=='Toolbar':
            from .toolbar import PROPERTIES,errors
            findings=errors(self.control)
            if findings.get('Version'):raise FxError(findings['Version'],'Unsupported')
            if name in findings:raise FxError(findings[name],'Unsupported')
            if name not in PROPERTIES | {'Reset'}:raise FxError(f'Toolbar has no supported {name} property','Unsupported')
        if self.family == 'FluentV8/Rating':
            from .fluent_rating import PROPERTIES, errors
            findings = errors(self.control)
            if findings.get('Version'):raise FxError(findings['Version'],'Unsupported')
            if name in findings:raise FxError(findings[name],'Unsupported')
            if name not in PROPERTIES | {'Reset'}:raise FxError(f'{self.control.kind} has no {name} property','Unsupported')
        if self.family == 'ModernLink':
            from .modern_link import PROPERTIES, errors
            findings = errors(self.control)
            for key in ('Version','Variant','URL' if name == 'Url' else name):
                if key in findings: raise FxError(findings[key],'Unsupported')
            if name not in PROPERTIES: raise FxError(f'{self.control.kind} has no {name} property','Unsupported')
        if self.family in ('Label','Rectangle','Circle','Star'):
            from .classic_display import VERSIONS,properties as display_properties
            if self.control.version not in VERSIONS[self.family] or 'Variant'in contract_errors(self.control):raise FxError(f'Unsupported {self.control.kind} version/variant','Unsupported')
            if name in contract_errors(self.control):raise FxError(contract_errors(self.control)[name],'Unsupported')
            if name!='Name' and name not in display_properties(self.control):raise FxError(f'{self.control.kind} has no {name} property','Unsupported')
        if self.family=='Classic/Button':
            from .classic_button import VERSIONS
            if self.control.version not in VERSIONS:raise FxError(f'Unsupported classic button version {self.control.kind}','Unsupported')
            if name in contract_errors(self.control):raise FxError(contract_errors(self.control)[name],'Unsupported')
        if self.family in ('ModernBadge','ModernInformationButton') and name in self.control.properties and name in contract_errors(self.control):
            raise FxError(contract_errors(self.control)[name],'Unsupported')
        if self.family == "ModernRating" and name in self.control.properties and name in contract_errors(self.control):
            raise FxError(contract_errors(self.control)[name], "Unsupported")
        if self.family == "ModernRating" and name == "Value" and name in self.control.properties:
            raise FxError("ModernRating.Value is an output; author Default", "Unsupported")
        if self.family == "Timer" and name == "Value" and name in self.control.properties:
            raise FxError("Timer.Value is an output; author Duration and Start", "Unsupported")
        if self.family in ('Audio','Video'):
            from .media_controls import VERSIONS
            if self.control.version not in VERSIONS[self.family]:raise FxError(f'Unsupported media control version {self.control.kind}', 'Unsupported')
            if name in contract_errors(self.control):raise FxError(contract_errors(self.control)[name], 'Unsupported')
            from .media_controls import OUTPUTS, output
            if name in OUTPUTS:return output(self, name)
        if self.family == "RichTextEditor" and name == "HtmlText" and name in self.control.properties:
            raise FxError("RichTextEditor.HtmlText is an output; author Default", "Unsupported")
        if self.family in (*CLASSIC_BOOLEAN,'Classic/Slider') and name=='Value' and name in self.control.properties:
            raise FxError(f'{self.family}.Value is an output; author Default','Unsupported')
        if self.family=='Classic/DatePicker' and name=='SelectedDate' and name in self.control.properties:
            raise FxError('Classic/DatePicker.SelectedDate is an output; author DefaultDate','Unsupported')
        if self.family in CLASSIC_SELECTORS and name=='SelectedText' and name in self.control.properties:
            raise FxError(f'{self.family}.SelectedText is an output','Unsupported')
        if self.family=='Classic/TextInput' and name=='Text' and name in self.control.properties:
            raise FxError('Classic/TextInput.Text is an output; author Default','Unsupported')
        if self.family == 'ModernTextInput' and self.control.version == '1.0.0' and name == 'Text' and name in self.control.properties:
            raise FxError('ModernTextInput.Text is an output; author Default', 'Unsupported')
        if self.family in ('ModernNumberInput','ModernDatePicker') and self.control.version == '1.0.0' and name == ('Value' if self.family=='ModernNumberInput' else 'SelectedDate') and name in self.control.properties:
            raise FxError(f'{self.family}.{name} is an output', 'Unsupported')
        if self.family in COMBOBOXES and name == 'SearchText' and (self.path, 'Items') in r.evaluating:
            r.combo_search_items.add(self.path)
        if self.family in COMBOBOXES and name in ('Selected', 'SelectedItems', 'SearchText') and name in self.control.properties:
            raise FxError(f'{self.family}.{name} is an output', 'Unsupported')
        if self.family=='Classic/ComboBox' and name=='NavigateItem' and name in self.control.properties:
            raise FxError('Classic/ComboBox.NavigateItem is an output','Unsupported')
        if self.family in LISTBOXES and name in LIST_OUTPUTS and name in self.control.properties:
            raise FxError(f'{self.family}.{name} is an output','Unsupported')
        if self.family == "ModernDataGridColumn" and name == "Text":
            from .modern_grid import cell
            if not self.parent or self.parent.family!='ModernDataGrid':return None
            caller=ctx.self_ref if ctx else None
            row=ctx.item if caller and caller.family=='ModernDataGridColumn' and caller.parent is self.parent else self.parent.property('Selected')
            return cell(self,row)[0] if row is not None else ''
        if self.family == "ModernDataGrid" and name in ('Selected','SelectedItems','SearchText'):
            if name in self.control.properties:raise FxError(f'ModernDataGrid.{name} is an output','Unsupported')
            from .modern_grid import output
            return output(self,name)
        if self.family == "DataTableColumn" and name == "Text":
            from .data_table import cell
            if not self.parent or self.parent.family!="DataTable":return None
            caller=ctx.self_ref if ctx else None
            row=ctx.item if caller and caller.family=="DataTableColumn" and caller.parent is self.parent else self.parent.property("Selected")
            return cell(self,row)
        if self.family == "DataTable" and name == "Selected":
            if name in self.control.properties:raise FxError("DataTable.Selected is an output","Unsupported")
            from .data_table import selected
            return selected(self)
        if self.family == 'Form' and name in ('Item', 'Updates', 'Unsaved', 'Valid'):
            self.sync_form_item()
        if self.family=='Toolbar' and name in ('Selected','SelectedItems'):
            from .toolbar import output
            return output(self,name)
        if self.family == 'TabList' and name in ('Selected', 'SelectedItems'):
            from .canvas_tabs import output
            return output(self, name)
        if self.family=='ModernTabList' and name in ('Selected','SelectedItems'):
            if name=='SelectedItems' or name in self.control.properties:
                raise FxError(f'ModernTabList.{name} is an output or unsupported; author Default','Unsupported')
            from .tablist import selected
            return selected(self)
        if self.family in ('ComboBox','DropDown','Radio') and name in ('Selected','SelectedItems','SearchText'):
            from .canvas_selectors import output
            return output(self,name)
        input_property = r.input_property(self)
        if input_property and name in (input_property, "SelectedItems"):
            self.sync_default(input_property)
        if self.family in LISTBOXES and name in LIST_OUTPUTS:
            self.sync_default('Selected')
            from .listbox import output
            return output(self,name)
        if self.family == 'Gallery' and name in ('Selected', 'SelectedItems'):
            from .galleries import selected
            row = selected(self)[1]
            return row if name == 'Selected' else ([] if row is None else [row])
        if name == "Name":
            return self.name
        if name == 'AllItems' and self.family == 'Gallery':
            from .galleries import all_items
            return all_items(self)
        if name == "AllItemsCount" and self.family == "Gallery":
            from .gallery_loading import count
            return count(self)
        if name == "TemplateWidth" and self.family == "Gallery":
            return max(1, self.property("TemplateSize")) if self.control.raw.get("Variant") == "Horizontal" else self.property("Width") / max(1, self.property("WrapCount"))
        if name == "TemplateHeight" and self.family == "Gallery":
            return self.property("Height") / max(1, self.property("WrapCount")) if self.control.raw.get("Variant") == "Horizontal" else max(1, self.property("TemplateSize"))
        if name == "IsSelected":
            ancestor = self.parent
            while ancestor:
                if ancestor.family == "Gallery":
                    from .galleries import GalleryRecord, selected
                    return selected(ancestor)[0] == self.item.key if isinstance(self.item, GalleryRecord) and self.item.gallery is ancestor else self.item == ancestor.property('Selected')
                ancestor = ancestor.parent
            return False
        if self.family == "CanvasComponent":
            definition = r.project.components.get(self.control.raw.get("ComponentName"))
            custom = definition.raw.get("CustomProperties", {}).get(name) if definition else None
            if custom and validate_kind(custom) in ("Event", "Action", "Function"):
                return ComponentCallable(r, self, name, custom)
        if name in self.state and self.family in ('Slider','Toggle') and name==r.input_property(self):
            from .canvas_scalars import value
            return value(self,self.state[name])
        if name in self.state and self.family in ('TextInput','CheckBox') and name==r.input_property(self):
            from .canvas_inputs import value
            return value(self,self.state[name])
        if name in self.state and not (self.family in SINGLE_SELECT and name == 'Selected'):
            if self.family in COMBOBOXES and name in ('Selected', 'SelectedItems'):
                rows = table(self.property('Items'))
                selected = self.state.get('SelectedItems', [])
                selected = [next((row for row in rows if isinstance(row, dict) and r.same_item(row, chosen)), chosen) for chosen in selected]
                if not self.property('SelectMultiple'):
                    selected = selected[:1]
                return selected_record(self,selected) if name == 'Selected' else selected
            if self.family in ("ModernRating",'FluentV8/Rating') and name == "Value":
                if self.family=='FluentV8/Rating':
                    from .fluent_rating import value
                else:
                    from .rating import value
                return value(self,self.state[name])
            if self.family in SLIDERS and name == "Value":
                minimum, maximum = self.slider_bounds()
                return max(minimum, min(maximum, self.state[name]))
            return self.state[name]
        key = (self.path, name)
        if key in r.property_cache:
            cached = r.property_cache[key]
            if isinstance(cached, FxError):
                raise cached
            return cached
        if key in r.evaluating:
            allocated = r.layout_cache.get(("wrap", self.parent.path), {}).get(self.path, {}) if self.automatic_parent else {}
            if name in ("Width", "Height") and name in allocated:
                return allocated[name]
            if name in ("Width", "Height") and self.automatic_parent and ((self.parent.path, name) in r.evaluating or (self.parent.path, name) in r.intrinsic_measuring):
                from . import layout
                cross = "Height" if self.parent.property("LayoutDirection") == "Horizontal" else "Width"
                if name == cross and layout.alignment(self) == "Stretch":
                    return layout.bounded(self.intrinsic_dimension(name), *layout.limits(self, name))
            raise FxError(f"Control property cycle: {self.name}.{name}", "Cycle")
        r.evaluating.add(key)
        if self.family in COMBOBOXES and name == 'Items':
            r.combo_search_items.discard(self.path)
        try:
            value = self._property(name)
            if self.family=='Classic/Slider' and value is None and name in ('Min','Max','Default'):
                from .classic_inputs import catalog
                value=catalog()[self.family]['null_defaults'][name]
            if self.family == "Timer":
                from .timers import validate
                if value is None and name=="Duration":value=0
                if value is None and name in ("Start","Repeat","Reset"):value=False
                validate(name,value)
            if self.family in ('Audio','Video'):
                from .media_controls import validate
                validate(name,value)
            if self.family == "RichTextEditor":
                from .rich_text import validate
                if name == "Default" and value is not None:
                    from .binding import value_type,TEXT,function_compatible
                    if not function_compatible(value_type(value),TEXT,restrictive=False):raise FxError("RichTextEditor.Default requires a text-coercible scalar","Type")
                    value=r.fx.to_text(value)
                validate(name,value)
            if self.family == "HtmlViewer":
                from .html_controls import validate
                if name == "HtmlText" and value is not None:
                    from .binding import value_type,TEXT,function_compatible
                    if not function_compatible(value_type(value),TEXT,restrictive=False):
                        raise FxError("HtmlViewer.HtmlText requires text-coercible scalar values", "Type")
                    value=r.fx.to_text(value)
                validate(name,value)
            if self.family=='Classic/ComboBox':
                from .classic_combobox import validate
                if name=='DefaultSelectedItems':value=[] if value is None else [value] if isinstance(value,dict) else value
                validate(self,name,value)
            if self.family in ('ComboBox','DropDown','Radio','ComboBoxDataField'):
                from .canvas_selectors import validate
                validate(self,name,value)
            if self.family in ('Slider','Toggle'):
                from .canvas_scalars import validate,value as scalar_value
                validate(self,name,value)
                if name==r.input_property(self):value=scalar_value(self,value)
            if self.family in ('TextInput','CheckBox'):
                from .canvas_inputs import validate,value as input_value
                validate(self,name,value)
                if name==r.input_property(self):value=input_value(self,value)
            if self.family == 'DatePicker':
                from .canvas_dates import validate
                value = validate(self, name, value)
            if self.family=='Toolbar':
                from .toolbar import validate
                validate(name,value)
            if self.family=='FluentV8/Rating':
                from .fluent_rating import validate
                validate(name,value)
                if name=='Value':
                    from .fluent_rating import value as rating_value
                    value=rating_value(self,value)
            if self.family == 'ModernRating':
                from .rating import validate
                validate(self,name,value)
            if self.family in ('ModernDataGrid','ModernDataGridColumn'):
                from .modern_grid import validate
                validate(self,name,value)
            if self.family in ('DataTable','DataTableColumn'):
                from .data_table import validate
                validate(self,name,value)
            if self.family in LISTBOXES:
                from .listbox import validate
                validate(self,name,value)
            if self.family in ('Form','TypedDataCard'):
                from .form_layout import validate
                validate(self,name,value)
            if self.family in CLASSIC_INPUTS:
                from .classic_inputs import validate
                raw=self.raw_property(name)
                actual=r.fx.node_types.get(id(r.fx.bound_node(raw,ctx))) if isinstance(raw,str) and raw.startswith('=') else None
                validate(self,name,value,actual)
            if self.family == 'ModernCombobox' and name in ('IsSearchable', 'SelectMultiple', 'DelayOutput') and not isinstance(value, bool):
                raise FxError(f'Combobox {name} requires a Boolean', 'Type')
            if self.family in SINGLE_SELECT or self.family in COMBOBOXES:
                if name == 'Required' and not isinstance(value, bool):
                    raise FxError('Selection Required requires a Boolean', 'Type')
                if name == 'ValidationState' and self.family != 'ModernRadio' and value not in ('None', 'Error'):
                    raise FxError('Selection ValidationState requires None or Error', 'Type')
                if name == 'Layout' and self.family == 'ModernRadio' and value not in ('Horizontal', 'Vertical'):
                    raise FxError('Radio Layout requires Horizontal or Vertical', 'Type')
                if name in ('MultiValueDelimiter', 'InputTextPlaceholder') and value is not None and not isinstance(value, str):
                    raise FxError(f'Selection {name} requires Text', 'Type')
            if self.family in TEXT_INPUTS:
                if name == 'MaxLength' and value is None:
                    value = 0
                if self.family=='ModernTextInput' and name == 'TriggerOutput' and value not in ('Keypress', 'FocusOut', 'Delayed'):
                    raise FxError('Text input TriggerOutput requires Keypress, FocusOut or Delayed', 'Type')
                if self.family=='ModernTextInput' and name == 'Required' and not isinstance(value,bool):
                    raise FxError('Text input Required requires a Boolean', 'Type')
                if self.family=='ModernTextInput' and name == 'ValidationState' and value not in ('None','Error'):
                    raise FxError('Text input ValidationState requires None or Error', 'Type')
                if self.family=='ModernTextInput' and name == 'Type' and value not in ('Text','SingleLine','Multiline','Password','Search','Email','Telephone','URL'):
                    raise FxError('Unsupported text input Type', 'Unsupported')
                if name == 'MaxLength' and (isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or not math.isfinite(float(value)) or value < 0 or value != int(value)):
                    raise FxError('Text input MaxLength requires a nonnegative integer', 'Type')
            if self.family == "CanvasComponent":
                definition = r.project.components.get(self.control.raw.get("ComponentName"))
                custom = definition.raw.get("CustomProperties", {}).get(name) if definition else None
                if custom and validate_kind(custom) in ("Input", "Output"):
                    r.component_signature(name, custom,self)
                    ctx = self.host_context() if validate_kind(custom) == 'Input' and name in self.control.properties else self.context()
                    try:value = r.component_value(value, self.raw_property(name), ctx, r.binder.component_type(self.control, name))
                    except FxError as error:raise self.expression(name).locate(error)
            if self.family == "ModernCheckbox" and name == "Checked" and value is not None and not isinstance(value, bool):
                raise FxError("Checkbox Checked requires a Boolean", "Type")
            if self.family == "ModernProgressBar":
                if name == 'Indeterminate' and not isinstance(value, bool):
                    raise FxError('Progress Indeterminate requires a Boolean', 'Type')
                if name in ('Value', 'Max'):
                    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(float(value)):
                        raise FxError('Progress Value and Max require finite Numbers', 'Type')
                    if name == 'Max' and value <= 0:
                        raise FxError('Progress Max must be greater than zero', 'Validation')
            if self.family in ('ModernIcon','Classic/Icon'):
                from .icons import validate,validate_classic
                raw=self.raw_property(name)
                actual=r.fx.node_types.get(id(r.fx.bound_node(raw,ctx))) if isinstance(raw,str) and raw.startswith('=') else None
                (validate_classic if self.family=='Classic/Icon' else validate)(name,value,actual)
            if self.family in ('Text', 'FluentV8/Label'):
                from .canvas_text import validate
                validate(self, name, value)
            if self.family == 'Button':
                from .canvas_buttons import validate
                validate(self, name, value)
            if self.family == 'TabList':
                from .canvas_tabs import validate
                validate(self, name, value)
            if self.family=='ModernTabList':
                from .tablist import TYPES,validate
                raw=self.raw_property(name)
                actual=r.fx.node_types.get(id(r.fx.bound_node(raw,ctx or self.context()))) if TYPES.get(name)=='Color' and isinstance(raw,str) and raw.startswith('=') else None
                validate(self,name,value,actual)
            if self.family in ('ModernBadge','ModernInformationButton'):
                from .status_controls import TYPES,validate
                raw=self.raw_property(name)
                actual=r.fx.node_types.get(id(r.fx.bound_node(raw,ctx or self.context()))) if TYPES.get(name)=='Color' and isinstance(raw,str) and raw.startswith('=') else None
                validate(self,name,value,actual)
            if self.family == 'ModernButton':
                from .modern_button import TYPES,validate
                if name in TYPES:
                    raw=self.raw_property(name)
                    actual=r.fx.node_types.get(id(r.fx.bound_node(raw,ctx or self.context()))) if TYPES[name]=='Color' and isinstance(raw,str) and raw.startswith('=') else None
                    validate(name,value,actual)
            if self.family == 'ModernLink':
                from .modern_link import validate, TYPES
                if name == 'Text' and value is not None:
                    from .binding import value_type, TEXT, function_compatible
                    if not function_compatible(value_type(value),TEXT,restrictive=False):
                        raise FxError('ModernLink.Text requires a text-coercible scalar','Type')
                    value = r.fx.to_text(value)
                raw = self.raw_property(name)
                actual = r.fx.node_types.get(id(r.fx.bound_node(raw,ctx or self.context()))) if TYPES.get(name) == 'Color' and isinstance(raw,str) and raw.startswith('=') else None
                validate(self,name,value,actual)
            if self.family in ('Label','Rectangle','Circle','Star'):
                from .classic_display import TYPES,validate
                kind=TYPES[self.family].get(name)
                if kind:
                    raw=self.raw_property(name)
                    actual=r.fx.node_types.get(id(r.fx.bound_node(raw,ctx or self.context()))) if kind=='Color' and isinstance(raw,str) and raw.startswith('=') else None
                    validate(self,name,value,actual)
            if self.family=='Classic/Button':
                from .classic_button import TYPES,validate
                if name in TYPES:
                    raw=self.raw_property(name)
                    actual=r.fx.node_types.get(id(r.fx.bound_node(raw,ctx or self.context()))) if TYPES[name]=='Color' and isinstance(raw,str) and raw.startswith('=') else None
                    validate(self,name,value,actual)
            if self.family == 'ModernNumberInput':
                from .input_controls import number_value, finite
                if name in ('Value','Default'):value = number_value(self,value)
                if name in ('Min','Max','Step'):value = finite(value,name,name!='Step')
                if name == 'Precision' and (value != 'Auto' and (isinstance(value,bool) or not isinstance(value,(int,float,Decimal)) or value not in (0,1,2,3))):
                    raise FxError('Number input Precision requires Auto or 0–3','Type')
            if self.family in DATE_PICKERS:
                from .input_controls import date_value
                if name in ('DefaultDate','SelectedDate','StartDate','EndDate'):value = date_value(self,value)
                if name == 'IsEditable' and not isinstance(value,bool):raise FxError('Date picker IsEditable requires a Boolean','Type')
                if name == 'DateTimeZone' and value not in ('UTC','Local'):raise FxError('DateTimeZone requires Local or UTC','Type')
            if self.family in ('ModernDatePicker','ModernNumberInput') and name == 'ValidationState' and value not in ('None','Error'):
                raise FxError('Input ValidationState requires None or Error','Type')
            if (name == 'Text' or name == 'Default' and self.family in TEXT_INPUTS) and self.family in ('ModernText', 'Label', 'ModernButton', 'Classic/Button', *TEXT_INPUTS):
                value = r.fx.to_text(value)
            if isinstance(value, Decimal) and (name in NUMERIC_CONTROL_PROPERTIES or self.family=='ModernButton' and name=='IconRotation' or self.family in ('ModernNumberInput', *SLIDERS) and name in ('Value', 'Default')):
                value = float(value)
            if not (name in ("Width", "Height") and self.automatic_parent and ((self.parent.path, name) in r.evaluating or (self.parent.path, name) in r.intrinsic_measuring)):
                r.property_cache[key] = value
            return value
        except FxError as error:
            r.property_cache[key] = error
            # Compatibility findings remain visible even if a formula catches
            # the failed value. They do not dispatch the app's error handler.
            if error.kind in ('Unsupported','Cycle'):
                r.diagnostic(error,self.control.source,f'{self.name}.{name}',self.raw_property(name),category='unsupported' if error.kind=='Unsupported' else 'binding')
            raise
        finally:
            r.evaluating.discard(key)

    def slider_bounds(self):
        minimum, maximum = self.property("Min"), self.property("Max")
        if any(isinstance(v, bool) or not isinstance(v, (int, float, Decimal)) or not math.isfinite(float(v)) for v in (minimum, maximum)):
            raise FxError("Slider limits require finite Numbers", "Type")
        if minimum > maximum:
            raise FxError("Slider Min cannot exceed Max", "Validation")
        return minimum, maximum

    def sync_default(self, value_property):
        if getattr(self, "syncing_default", False):
            return
        r = self.runtime
        self.syncing_default = True
        try:
            default = "DefaultSelectedItems" if self.family in ("TabList","Toolbar","ComboBox","DropDown","Radio") else "Value" if self.family=='FluentV8/Rating' else "DefaultSelectedItems" if self.family in COMBOBOXES else "DefaultDate" if self.family in DATE_PICKERS else "Checked" if self.family == "ModernCheckbox" else "Default"
            if value_property in self.control.properties and self.family not in SLIDERS and self.family not in CLASSIC_BOOLEAN and self.family not in SINGLE_SELECT:
                raw = self.control.properties[value_property]
                baseline = self.eval_raw(value_property)
            else:
                baseline = self.eval_raw(value_property) if self.family in ('Slider','Toggle','TextInput','CheckBox','FluentV8/Rating','DatePicker') else self.property(default)
            if self.path in r.input_baselines and r.input_baselines[self.path] != baseline:
                for key in (value_property, "SelectedItems", "Selected", "dirty", "slider_last_change", "canvas_tab_key"):
                    self.state.pop(key, None)
                if self.family in ('ModernRating','FluentV8/Rating','ModernNumberInput',*DATE_PICKERS,'Classic/Slider','Slider'):
                    r.scalar_resets[self.path] = r.scalar_resets.get(self.path, 0) + 1
                    r.calendar_months.pop(self.path, None)
                if self.family in SINGLE_SELECT or self.family in CLASSIC_BOOLEAN or self.family in ('TabList','ModernTabList','Toolbar','CheckBox','Toggle'):
                    r.selector_resets[self.path] = r.selector_resets.get(self.path, 0) + 1
                if self.family in LISTBOXES:
                    self.state.pop('ListLatest',None);self.state.pop('ListAnchor',None)
                    r.combo_resets[self.path]=r.combo_resets.get(self.path,0)+1
                if self.family in ('ComboBox','DropDown','Radio'):
                    self.state.pop('canvas_selection',None);self.state.pop('canvas_search',None);self.state.pop('canvas_baseline',None)
                    r.combo_resets[self.path]=r.combo_resets.get(self.path,0)+1
                if self.family in COMBOBOXES:
                    self.state.pop('SearchText', None)
                    r.combo_resets[self.path] = r.combo_resets.get(self.path, 0) + 1
                if self.family in TEXT_INPUTS or self.family in ("RichTextEditor","TextInput"):
                    self.state.pop('text_last_change', None)
                    if self.family == 'RichTextEditor':self.state.pop('rich_issues', None)
                    r.text_resets[self.path] = r.text_resets.get(self.path, 0) + 1
                r.invalidate()
            r.input_baselines[self.path] = baseline
        finally:
            self.syncing_default = False

    def sync_form_item(self):
        if getattr(self, 'syncing_form_item', False):
            return
        self.syncing_form_item = True
        r = self.runtime
        try:
            raw = self.raw_property('Item')
            item = self.eval_raw('Item')
            snapshot = serial(item)
            if self.path in r.form_item_baselines and r.form_item_baselines[self.path] != snapshot:
                for child in r.descendants(self):
                    r.clear_control_state(child)
                self.state.pop('Item', None)
                r.invalidate()
            r.form_item_baselines[self.path] = snapshot
        finally:
            self.syncing_form_item = False

    def _property(self, name):
        r = self.runtime
        if self.family=='Classic/ComboBox':
            if name=='NavigateItem':return None
            if name=='SearchItems' and name not in self.control.properties:
                from .classic_combobox import search_items
                return search_items(self)
            if name=='DefaultSelectedItems' and name not in self.control.properties and 'Default' in self.control.properties:
                return self.property('Default')
        if self.family in CLASSIC_BOOLEAN and name=='Value':
            return self.property('Default')
        if self.family in CLASSIC_SELECTORS and name=='SelectedText':
            from .classic_inputs import display
            chosen=self.property('Selected')
            return (display(self,chosen) if self.family=='Classic/Radio' else {'Value':display(self,chosen)}) if chosen is not None else None
        if self.family in COMBOBOXES and name == 'SearchText':
            return ''
        if self.family in SINGLE_SELECT and name == 'Selected':
            if name in self.control.properties:
                raise FxError(f'{self.family}.Selected is an output; author Default', 'Unsupported')
            rows = table(self.property('Items'))
            if 'Selected' in self.state:
                chosen=next((row for row in rows if not isinstance(row, FxError) and r.same_item(row, self.state['Selected'])), None)
                if chosen is not None or self.family not in CLASSIC_SELECTORS or self.state['Selected'] is None and (self.family=='Classic/Radio' or self.property('AllowEmptySelection')):return chosen
            return self.match_default(rows)
        if name in ("X", "Y", "Width", "Height") and self.automatic_parent:
            from . import layout
            if not self.parent.property("LayoutWrap"):
                return layout.dimension(self, name) if name in ("Width", "Height") else layout.position(self, name)
            return layout.wrapped_property(self, name)
        if name == "DisplayMode" and name not in self.control.properties:
            if self.family == "Form":
                return "View" if self.property("Mode") == "View" else "Edit"
            if self.family == "TypedDataCard" and self.parent:
                return self.parent.property("DisplayMode")
        if name in ("Width", "Height"):
            return self.intrinsic_dimension(name)
        if name == "Value" and self.family == "ModernRating":
            from .rating import value
            return value(self,self.property("Default"))
        if name == "Value" and self.family == "Timer":
            from .timers import value
            return value(self)
        if name == "HtmlText" and self.family == "RichTextEditor":
            from .rich_text import clean_value
            return clean_value(self,self.property("Default"))
        if name == "Text" and self.family in TEXT_INPUTS and name not in self.control.properties:
            return self.property("Default")
        if name == "Value" and self.family in SLIDERS:
            if name in self.control.properties:
                raise FxError("ModernSlider.Value is an output; author the Default property", "Unsupported")
            minimum, maximum = self.slider_bounds()
            value = self.property("Default")
            if value is None:
                value = minimum
            if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(float(value)):
                raise FxError("Slider Default requires a finite Number", "Type")
            return max(minimum, min(maximum, value))
        if name == "Value" and self.family == "ModernNumberInput" and name not in self.control.properties:
            return self.property("Default")
        if name == "SelectedDate" and self.family in DATE_PICKERS - {'DatePicker'} and name not in self.control.properties:
            return self.property("DefaultDate")
        if name in ("Selected", "SelectedItems") and self.family in ("Gallery", *COMBOBOXES):
            if self.family == "Gallery":
                default = self.property("Default")
                items = table(self.property("Items"))
                selected = next((row for row in items if r.same_item(row, default)), items[0] if items else None)
                return selected if name == "Selected" else [selected] if selected else []
            selected = self.state.get("SelectedItems")
            if selected is None:
                selected = table(self.property("DefaultSelectedItems"))
            if self.family in COMBOBOXES and not self.property('SelectMultiple'):
                selected = selected[:1]
            return selected_record(self,selected) if name == "Selected" else selected
        if self.family == "Form":
            if name == "Mode":
                return self.property("DefaultMode")
            if name == "Item" and self.property("Mode") == "New":
                ds = self.property("DataSource")
                return ds.record(r.store.defaults(ds.name))
            if name == "Updates":
                return {child.property("DataField"): child.property("Update") for child in self.children if child.family == "TypedDataCard" and child.property("DataField")}
            if name == "Valid":
                return all(truth(child.property("Valid")) for child in self.children if child.family == "TypedDataCard")
            if name == "Unsaved":
                for ref in r.descendants(self):
                    prop = r.input_property(ref)
                    if prop:
                        ref.property(prop)  # Settle reactive defaults before checking dirty state.
                return any(ref.state.get("dirty", False) for ref in r.descendants(self))
            if name in ("Error", "ErrorKind", "LastSubmit"):
                return "" if name == "Error" else 0 if name == "ErrorKind" else None
        if self.family == "TypedDataCard":
            if name == "Valid":
                return not self.validation_error()
            if name == "Error":
                # Field errors are populated on SubmitForm, never fabricated
                # as an unknown property or shown before a validation attempt.
                return ""
        raw = self.raw_property(name)
        if raw is None:
            raise FxError(f"Unknown property {self.name}.{name}")
        ctx = self.context()
        if self.family=="Gallery" and name in ("TemplateFill","ItemAccessibleLabel"):
            from .galleries import selected
            from .row_rules import gallery_formula
            key,row=selected(self)
            return gallery_formula(self,name,row,key)
        definition = component_definition(r.project, self.control)
        custom = definition.raw.get("CustomProperties", {}).get(name) if definition else None
        if self.family == "CanvasComponent" and name in self.control.properties and (not custom or validate_kind(custom) == "Input"):
            ctx = self.host_context()
        return self.eval_raw(name,ctx)

    def match_default(self, rows):
        """Modern single-selection defaults accept a record or single-column scalar."""
        if self.family in CLASSIC_SELECTORS:
            from .classic_inputs import match_default
            return match_default(self,rows)
        value = self.property('Default')
        if value is None:
            return None
        if isinstance(value, (list, DataSource)):
            raise FxError('Default requires one item, not a table', 'Type')
        for row in rows:
            if isinstance(row, FxError):
                continue
            candidate = row if isinstance(value, dict) else row.get('Value', row.get('Value1'))
            if self.runtime.same_item(candidate, value):
                return row
        return None

    def validation_error(self):
        field = self.property("DataField")
        if not field:
            return ""  # Unbound cards do not participate in form validation.
        value = self.property("Update")
        if self.property("Required") and (value is None or value == "" or value == []):
            return f"{field} is required"
        maximum = self.raw_property("MaxLength")
        if isinstance(value, str) and maximum and len(value) > (self.property("MaxLength") or float("inf")):
            return f"{field} exceeds maximum length"
        if self.parent and self.parent.family == "Form":
            source = self.parent.property("DataSource")
            if isinstance(source, DataSource):
                record = self.runtime.store.internal(source.name, {field: value})
                try:
                    self.runtime.store.validate(source.name, record, fields=set(record))
                except FxError as error:
                    return error.message
        return ""


class Runtime:
    def __init__(self, project):
        self.project = project
        self.store = ListStore(project.root / "data.sqlite", project.read_json("metadata/datasources.json", {}), project.root / 'lists')
        if project.config.get("demo"):
            from .scenarios import demo_definitions
            demo_definitions(self.store)
        self.environment = project.config["environment"]
        from .reactivity import ReactiveValues
        self.reactive = ReactiveValues(self)
        self.store.reactive = self.reactive
        self.viewport = dict(project.config["viewport"])
        self.people = project.config.get("people", [])
        self.store.actor = self.current_person
        self.fx = Evaluator(self)
        self.fx.set_definitions(str(project.app.get("Formulas", "")))
        self.refs, self.screens, self.global_refs = {}, {}, {}
        self.control_state, self.globals, self.collections, self.screen_context = {}, {}, {}, {}
        self.component_state = {}
        self.gallery_loading, self.gallery_rows_cache, self.gallery_syncing = {}, {}, set()
        self.combo_resets = {}
        self.selector_resets = {}
        self.scalar_resets = {}
        self.calendar_months = {}
        self.text_resets = {}
        self.text_contract_baselines = {}
        self.text_generation = uuid4().hex
        self.combo_search_items = set()
        self.component_call_stack = set()
        self.input_baselines = {}
        self.form_item_baselines = {}
        self.reset_property_baselines = {}
        self.syncing_resets = False
        self.component_input_baselines = {}
        self.component_reset_blocks = {}
        self.active_event_stack = []
        self.active_event_chain = ()
        self.resetting = set()
        self.layout_cache = {}
        self.intrinsic_measuring = set()
        self.formula_cache, self.property_cache, self.evaluating = {}, {}, set()
        self.diagnostics, self.notifications, self.history, self.event_queue = [], [], [], []
        from .app_errors import AppErrors
        self.app_errors=AppErrors(self)
        self.focus_request = None
        self.navigation_positions = {}
        self.trace = None  # Enabled only by an isolated workflow run.
        self.trace_limit = 1000
        self.trace_truncated = False
        self.active_screen = next(iter(project.screens), None)
        self.preview_screen = None
        self.preview_component = None
        self.started, self.pending_source = False, False
        self.app_ref = AppRef(self)
        self.known_globals, self.known_collections = set(), set()
        self.bind_diagnostics = []
        for name, control in project.screens.items():
            ref = self.build(control, name)
            self.screens[name] = ref
        from .timers import init
        init(self)
        from .media_controls import init as media_init
        media_init(self)
        self.button_busy=set()
        self.label_heights={}
        self.analyze()

    def current_person(self):
        """Local connector-managed audit identity, never Microsoft authentication."""
        user = self.environment.get("user", {})
        email = str(user.get("Email", "")).strip().lower()
        if not email:
            return None
        from .scenarios import person
        result = person(email, user.get("FullName", email))
        directory = next((p for p in self.people if str(p.get("Email", "")).lower() == email), {})
        for key in ("Department", "JobTitle", "Picture"):
            result[key] = directory.get(key, result[key])
        return result

    def close(self):
        try:
            self.store.close()
        finally:
            if getattr(self, 'workspace_lease', None):
                self.workspace_lease.close()
                self.workspace_lease = None

    def build(self, control, path, parent=None, item=None, frames=None, scope=None, component=None):
        ref = Ref(self, control, path, parent, item, frames, scope, component)
        if scope is not None:
            scope[control.name] = ref
        elif item is None and component is None:
            self.global_refs.setdefault(control.name, ref)
        if control.family == "CanvasComponent":
            definition = self.project.components.get(control.raw.get("ComponentName"))
            ancestors = list(self.ancestors(ref))
            if not definition:
                ref.component_error = FxError(f"Missing component definition {control.raw.get('ComponentName', control.name)}", 'Name')
                return ref
            if any(a.family == 'CanvasComponent' and a.control.raw.get('ComponentName') == definition.name for a in ancestors):
                ref.component_error = FxError(f"Component definition cycle involving {definition.name}", 'Cycle')
                return ref
            if sum(a.family == 'CanvasComponent' for a in ancestors) >= 30:
                ref.component_error = FxError('Nested component limit exceeded', 'Unsupported')
                return ref
            if definition:
                component_scope = {definition.name: ref}
                ref.scope = component_scope
                ref.children = [self.build(c, f"{path}/{c.name}", ref, item, frames, component_scope, ref) for c in definition.children]
        elif control.family != "Gallery":
            ref.children = [self.build(c, f"{path}/{c.name}", ref, item, frames, scope, component) for c in control.children]
        return ref

    def invalidate(self):
        self.reactive.invalidate()
        self.gallery_rows_cache.clear()
        self.formula_cache.clear()
        self.property_cache.clear()
        self.layout_cache.clear()

    @staticmethod
    def same_item(a, b):
        if isinstance(a, dict) and isinstance(b, dict):
            if isinstance(a.get('Claims'), str) and a['Claims'].strip() and isinstance(b.get('Claims'), str) and b['Claims'].strip():
                return a['Claims'].casefold() == b['Claims'].casefold()
            for key in ("ID", "Id"):
                if a.get(key) is not None and b.get(key) is not None:
                    return a[key] == b[key]
        return a == b

    def resolve(self, name, ctx, global_only=False):
        key=('identifier',name,global_only,self.screen_for(ctx.self_ref),getattr(ctx.component_ref,'path',None))
        return self.reactive.leaf(key,lambda:self._resolve(name,ctx,global_only))

    def _resolve(self, name, ctx, global_only=False):
        if not global_only and name in ctx.control_scope:
            return ctx.control_scope[name]
        if ctx.component_ref and not access_app_scope(self.project, ctx.component_ref):
            local = self.component_state.setdefault(ctx.component_ref.path, {"variables": {}, "collections": {}})
            if name in local["variables"]:
                return local["variables"][name]
            if name in local["collections"]:
                return local["collections"][name]
            definition = component_definition(self.project, ctx.component_ref.control)
            key = definition.name if definition else ctx.component_ref.name
            if name in getattr(self, "binder", None).component_variables.get(key, {}):
                return None
            if name in self.binder.component_collections.get(key, {}):
                return []
            raise FxError(f"Component cannot access app identifier {name}; enable AccessAppScope or pass an input", "Name")
        if name == "App":
            return self.app_ref
        if name == "PowerAppsTheme":
            return default_theme()
        for resource in self.project.config.get("resource_metadata", []):
            if resource.get("Name") == name and resource.get("ResourceKind") == "LocalFile":
                from .json_fx import Media
                return Media("/api/asset/" + resource["Path"].replace("\\", "/"), self.project.root/'Assets')
        if name in self.globals:
            return self.globals[name]
        if name in self.collections:
            return self.collections[name]
        screen = self.screen_for(ctx.self_ref)
        if not global_only and name in self.screen_context.get(screen, {}):
            return self.screen_context[screen][name]
        if name in self.global_refs:
            return self.global_refs[name]
        if name in self.store.definitions:
            return self.store.source(name)
        if name in self.known_globals:
            return None
        if name in self.known_collections:
            return []
        if name == "CustomGallerySample" or name == "ComboBoxSample":
            return []
        raise FxError(f"Unknown identifier {name}", "Name")

    def screen_for(self, ref):
        if ref:
            return ref.path.split("/")[0]
        return self.active_screen

    def scope_values(self, ctx, category):
        if ctx.component_ref and not access_app_scope(self.project, ctx.component_ref):
            return self.component_state.setdefault(ctx.component_ref.path, {"variables": {}, "collections": {}})[category]
        return self.globals if category == "variables" else self.collections

    def diagnostic(self, error, source="", member="", formula=None, category=None):
        # A stored error retains offsets into its originating rule, even when
        # another control observes it later. Never apply those offsets to the
        # consuming formula's text.
        origin=error.record().get('Source','')
        span_source=error.span_source or origin
        if category not in ('binding','historical') and span_source:
            if span_source.startswith('App.Formulas.'):
                source,formula=self.app_source(),self.project.app.get('Formulas')
            elif span_source.startswith('App.') and span_source[4:] in self.project.app:
                source,formula=self.app_source(),self.project.app[span_source[4:]]
            elif '.' in span_source:
                path,prop=span_source.rsplit('.',1)
                ref=self.refs.get(path)
                if ref:
                    source,formula=ref.control.source,ref.raw_property(prop)
        if formula is None and member.startswith("App."):
            formula = self.project.app.get(member[4:])
        elif formula is None and "." in member:
            control, prop = member.rsplit(".", 1)
            candidates = self.project.controls.get(control, [])
            if candidates:
                candidate = next((c for c in candidates if c.source == source), candidates[0])
                formula = candidate.properties.get(prop, candidate.raw.get("CustomProperties", {}).get(prop, {}).get("Default"))
        expression=getattr(error,'expression_origin',None)
        if expression is not None and category!='historical':
            source,formula=expression.source,expression.formula
        formula = str(formula or "")
        document = self.project.documents.get(source, "")
        needle = formula.splitlines()[0] if formula else ""
        offset = document.find(needle) if needle else -1
        line = document[:max(offset, 0)].count("\n") + formula[:error.start].count("\n") + 1
        if expression is not None and expression.line is not None and category!='historical':
            line=expression.line_at(error.start)
        entry = {"category": category or ("unsupported" if error.kind == "Unsupported" else "runtime"),
            "severity": "error", "message": error.message, "kind": error.kind,
            "source": source, "member": member, "line": line, "start": error.start, "end": error.end}
        if expression is not None:entry['expression_member']=expression.member
        if origin:entry['error_source']=origin
        if error.record().get('Observed'):entry['observed']=error.record()['Observed']
        def identity(d):
            key=(d['category'],d.get('source'),d.get('member'),d['message'])
            # Distinct declarations/occurrences remain actionable findings.
            if d['category']=='binding':key+=(d.get('expression_member'),d.get('start'),d.get('end'))
            return key
        if not any(identity(d)==identity(entry) for d in self.diagnostics):
            self.diagnostics.append(entry)

    def analyze(self):
        self.diagnostics = list(self.project.source_errors)
        from .expressions import app_expression,authored_property,authored_parameter,contract_expression
        origins={id(d.body):self.fx.app_definition_origin(name) for name,d in self.fx.definitions.items()}
        for ref in self.refs.values():
            if ref.component_error:
                self.diagnostic(ref.component_error, ref.control.source, ref.name, category='binding')
        for error in self.fx.parse_errors:
            self.diagnostic(app_expression(self,'Formulas').locate(error), self.app_source(), "App.Formulas", self.project.app.get("Formulas"), "binding")
        formulas = [("App.Formulas", self.app_source(), d.body) for d in self.fx.definitions.values() if not d.alias]
        formula_controls = {}
        for name, raw in self.project.app.items():
            if name == "Formulas" or not isinstance(raw, str) or not raw.startswith("="):
                continue
            try:
                node=self.fx.parse(raw)
                origins[id(node)]=app_expression(self,name)
                formulas.append((f"App.{name}", self.app_source(), node))
            except FxError as error:
                self.diagnostic(app_expression(self,name).locate(error), self.app_source(), f"App.{name}", raw, "binding")
        for controls in self.project.controls.values():
            for control in controls:
                family, version = control.family, control.version
                if family == 'CanvasComponent':
                    ancestor = control.parent
                    while ancestor:
                        if ancestor.family in ('Gallery', 'Form'):
                            self.diagnostic(FxError('Power Apps does not support canvas components inside galleries or forms', 'Unsupported'), control.source, control.name, category='binding')
                            break
                        ancestor = ancestor.parent
                if family not in SUPPORTED or version not in SUPPORTED[family]:
                    self.diagnostic(FxError(f"Unsupported control version {control.kind}", "Unsupported"), control.source, control.name)
                for prop, message in contract_errors(control).items():
                    self.diagnostic(FxError(message, 'Unsupported'), control.source, f'{control.name}.{prop}', control.properties.get(prop))
                source_properties = dict(control.properties)
                if control.kind == "Component":
                    for name, custom in control.raw.get("CustomProperties", {}).items():
                        try:
                            validate_kind(custom)
                        except FxError as error:
                            self.diagnostic(contract_expression(control,name,error).locate(error), control.source, f"{control.name}.{name}")
                    source_properties.update({name: custom.get("Default") for name, custom in control.raw.get("CustomProperties", {}).items() if name not in source_properties})
                for name, raw in source_properties.items():
                    if isinstance(raw, str) and raw.startswith("="):
                        try:
                            node = self.fx.parse(raw, ('source', id(control), name))
                            formula_controls[id(node)] = control
                            origins[id(node)]=authored_property(control,name)
                            formulas.append((f"{control.name}.{name}", control.source, node))
                        except FxError as error:
                            self.diagnostic(authored_property(control,name).locate(error), control.source, f"{control.name}.{name}", raw, "binding")
        self.functions_used = set()
        for member, source, node in formulas:
            for n in walk(node):
                if n.kind == "call":
                    name = call_name(n.children[0])
                    self.functions_used.add(name)
                    if name in ("Set", "ClearCollect", "Clear", "Collect") and len(n.children) > 1:
                        target = call_name(n.children[1])
                        if target:
                            (self.known_globals if name == "Set" else self.known_collections).add(target)
                    if name and "." not in name and name not in BUILTINS and name not in self.fx.definitions:
                        self.diagnostic(origins[id(node)].locate(FxError(f"Unsupported function {name}", "Unsupported", n.start, n.end)), source, member)
        from .binding import Binder, BindScope
        self.binder = Binder(self)
        parameter_defaults = {}
        def incomplete(t):
            return t.kind == "Unknown" or any(incomplete(v) for v in t.fields.values()) or t.row is not None and incomplete(t.row)
        for name, d in self.fx.definitions.items():
            if d.params is not None:
                if name in self.fx.recursive_functions:
                    self.diagnostic(origins[id(d.body)].locate(FxError(f"Recursive function {name} is unsupported", "Unsupported", d.body.start, d.body.end)), self.app_source(), "App.Formulas", category="binding")
                if d.returns == "Void" and not d.behavior:
                    self.diagnostic(origins[id(d.body)].locate(FxError(f"{name}: Void requires a behavior function body", "Type", d.body.start, d.body.end)), self.app_source(), "App.Formulas", category="binding")
                if len({p for p, _ in d.params}) != len(d.params):
                    self.diagnostic(origins[id(d.body)].locate(FxError(f"{name} has duplicate parameters", "Type", d.body.start, d.body.end)), self.app_source(), "App.Formulas", category="binding")
                if any(t in ("Void", "None") for _, t in d.params):
                    self.diagnostic(origins[id(d.body)].locate(FxError(f"{name}: Void is not a parameter type", "Type", d.body.start, d.body.end)), self.app_source(), "App.Formulas", category="binding")
            signature = [name] if d.alias else [t for _, t in d.params or []] + ([d.returns] if d.params is not None else [])
            for typename in signature:
                if incomplete(self.binder.declared_type(typename)):
                    self.diagnostic(origins[id(d.body)].locate(FxError(f"{name} uses an unknown or recursive type {typename}", "Type", d.body.start, d.body.end)), self.app_source(), "App.Formulas", category="binding")
        for name, error in self.binder.type_errors.items():
            self.diagnostic(self.fx.app_definition_origin(name).locate(error), self.app_source(), f"App.Formulas.{name}", self.project.app.get("Formulas"), category="binding")
        bound = []
        definitions = {id(d.body): d for d in self.fx.definitions.values()}
        for member, source, node in formulas:
            if member == "App.Formulas":
                d = definitions.get(id(node))
                scope = BindScope(frames=[{k: self.binder.declared_type(t) for k, t in d.params or []}], behavior=d.behavior)
            elif member.startswith("App."):
                scope = BindScope(behavior=member != "App.StartScreen")
                if member=='App.OnError':
                    from .app_errors import scope_type
                    scope=scope.child(scope_type())
            else:
                cname, prop = member.rsplit(".", 1)
                control = formula_controls[id(node)]
                scope = self.binder.scope_for(control, prop)
            bound.append((member, source, node, scope))
        # Parameter defaults are separate pure expressions. Binding them must
        # neither execute actions nor capture another parameter or host state.
        from .binding import value_type, function_compatible
        for control in self.project.components.values():
            for name, custom in control.raw.get('CustomProperties', {}).items():
                try:
                    specs = self.component_signature(name, custom)
                except FxError as error:
                    self.diagnostic(contract_expression(control,name,error).locate(error), control.source, f'{control.name}.{name}', category='binding')
                    continue
                for param, spec in specs:
                    if 'Default' not in spec:
                        continue
                    raw = spec['Default']
                    expected = self.binder.parameter_type(spec)
                    member = f'{control.name}.{name}.{param}.Default'
                    if isinstance(raw, str) and raw.startswith('='):
                        try:
                            node = self.fx.parse(raw, ('parameter-default', id(control), name, param))
                            parameter_defaults[id(node)] = expected
                            origins[id(node)]=authored_parameter(control,name,param,spec)
                            bound.append((member, control.source, node, BindScope(function_pure=True)))
                        except FxError as error:
                            self.diagnostic(authored_parameter(control,name,param,spec).locate(error), control.source, member, raw, 'binding')
                    elif not function_compatible(value_type(raw), expected, restrictive=False):
                        self.diagnostic(authored_parameter(control,name,param,spec).locate(FxError(f'{member}: expected {expected.describe()}', 'Type')), control.source, member, category='binding')
        self.binder.expression_owners={id(child):(member,source,id(node))
            for member,source,node,scope in bound for child in walk(node)}
        self.binder.expression_roots={(member,source,id(node)) for member,source,node,scope in bound}
        self.binder.prepare(bound)
        for member, source, node, scope in bound:
            inferred = self.binder.bind(node, scope, (member, source, id(node)))
            d = definitions.get(id(node)) if member == "App.Formulas" else None
            if id(node) in parameter_defaults:
                self.binder.owner, self.binder.reporting = (member, source, id(node)), True
                self.binder.require_component(inferred, parameter_defaults[id(node)], node, member)
                self.binder.owner, self.binder.reporting = None, False
            elif d and d.params is not None:
                self.binder.owner, self.binder.reporting = (member, source, id(node)), True
                self.binder.require_function(inferred, self.binder.declared_type(d.returns), node, f"{d.name} return value")
                self.binder.owner, self.binder.reporting = None, False
            elif not member.startswith("App."):
                cname, prop = member.rsplit(".", 1)
                control = formula_controls[id(node)]
                if control.family in ('ModernIcon','Classic/Icon'):
                    from .icons import PROPERTY_TYPES,CLASSIC_PROPERTY_TYPES
                    PROPERTY_TYPES=CLASSIC_PROPERTY_TYPES if control.family=='Classic/Icon' else PROPERTY_TYPES
                    if prop in PROPERTY_TYPES:
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        from .binding import FxType
                        expected=FxType('Icon') if PROPERTY_TYPES[prop]=='Icon' else self.binder.declared_type(PROPERTY_TYPES[prop])
                        if not (control.family=='ModernIcon' and prop=='Icon' and inferred.kind=='Icon'):
                            self.binder.require(inferred,expected,node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family in ('ModernBadge','ModernInformationButton'):
                    from .status_controls import TYPES,ENUM_PROPERTIES
                    if prop in TYPES or prop in ENUM_PROPERTIES and control.family=='ModernBadge' or prop=='Content' and control.family=='ModernInformationButton':
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        self.binder.require(inferred,self.binder.property_type(control,prop),node,member)
                        self.binder.owner,self.binder.reporting=None,False
                    elif prop=='Content' and inferred.kind not in ('Text','Number','Decimal','Blank','Unknown','Error'):
                        self.diagnostic(origins[id(node)].locate(FxError(f'{member} requires Text or Number','Type')),source,member,control.properties.get(prop),category='binding')
                if control.family in ('ComboBox','DropDown','Radio','ComboBoxDataField'):
                    from .canvas_selectors import catalog
                    types=catalog()[control.family].get(control.version,{}).get('types',{})
                    if prop in types and prop not in ('DisplayMode','Items','DefaultSelectedItems') and not (control.family=='Radio' and prop in ('BasePaletteColor','FontColor') and inferred.kind=='Color'):
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        self.binder.require(inferred,self.binder.property_type(control,prop),node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family in ('Text', 'FluentV8/Label'):
                    from .canvas_text import catalog
                    types = catalog()[control.family].get(control.version, {}).get('types', {})
                    if prop in types and prop != 'DisplayMode' and not (prop in ('Color','FontColor','Fill','BorderColor') and inferred.kind == 'Color'):
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        self.binder.require(inferred,self.binder.property_type(control,prop),node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family == 'Button':
                    from .canvas_buttons import catalog
                    types = catalog().get(control.version, {}).get('types', {})
                    if prop in types and prop != 'DisplayMode' and not (prop in ('BasePaletteColor','FontColor','BorderColor') and inferred.kind == 'Color'):
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        self.binder.require(inferred,self.binder.property_type(control,prop),node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family == 'TabList':
                    from .canvas_tabs import catalog
                    types = catalog().get(control.version, {}).get('types', {})
                    if prop in types and prop not in ('DisplayMode','Items','DefaultSelectedItems') and not (prop in ('BasePaletteColor','FontColor') and inferred.kind == 'Color'):
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        self.binder.require(inferred,self.binder.property_type(control,prop),node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family in ('Slider','Toggle'):
                    from .canvas_scalars import catalog
                    types=catalog()[control.family].get(control.version,{}).get('types',{})
                    if prop in types and prop!='DisplayMode' and not (prop in ('BasePaletteColor','FontColor') and inferred.kind=='Color'):
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        self.binder.require(inferred,self.binder.property_type(control,prop),node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family in ('TextInput','CheckBox'):
                    from .canvas_inputs import catalog
                    types=catalog()[control.family].get(control.version,{}).get('types',{})
                    if prop in types and prop!='DisplayMode':
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        self.binder.require(inferred,self.binder.property_type(control,prop),node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family == 'DatePicker':
                    from .canvas_dates import catalog
                    types = catalog().get(control.version, {}).get('types', {})
                    converted = types.get(prop) == 'Date' and inferred.kind == 'DateTime' or prop in ('BasePaletteColor','Fill','BorderColor','FontColor') and inferred.kind == 'Color'
                    if prop in types and prop != 'DisplayMode' and not converted:
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        self.binder.require(inferred,self.binder.property_type(control,prop),node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family=='Toolbar':
                    from .toolbar import TYPES
                    if prop in TYPES and prop not in ('DisplayMode','Items','DefaultSelectedItems'):
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        self.binder.require(inferred,self.binder.property_type(control,prop),node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family=='FluentV8/Rating':
                    from .fluent_rating import TYPES
                    if prop in TYPES and prop!='DisplayMode':
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        self.binder.require(inferred,self.binder.property_type(control,prop),node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family == "ModernRating":
                    from .rating import TYPES
                    if prop in TYPES or prop=='Step':
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        expected=self.binder.property_type(control,prop)
                        (self.binder.require_function if prop=='Default' else self.binder.require)(inferred,expected,node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family in ('Label','Rectangle','Circle','Star'):
                    from .classic_display import TYPES
                    if prop in TYPES[control.family]:
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        self.binder.require(inferred,self.binder.declared_type(TYPES[control.family][prop]),node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family=='Classic/Button':
                    from .classic_button import TYPES
                    if prop in TYPES:
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        self.binder.require(inferred,self.binder.declared_type(TYPES[prop]),node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family == "Timer":
                    from .timers import TYPES
                    if prop in TYPES:
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        self.binder.require(inferred,self.binder.declared_type(TYPES[prop]),node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family in ('Audio','Video'):
                    from .media_controls import TYPES
                    if prop in TYPES:
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        expected=self.binder.property_type(control,prop)
                        (self.binder.require_component if prop=='Media' else self.binder.require)(inferred,expected,node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family == "RichTextEditor":
                    from .rich_text import TYPES
                    if prop in TYPES:
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        (self.binder.require_function if prop=="Default" else self.binder.require)(inferred,self.binder.declared_type(TYPES[prop]),node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family == "HtmlViewer":
                    from .html_controls import TYPES
                    if prop in TYPES:
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        (self.binder.require_function if prop=="HtmlText" else self.binder.require)(inferred,self.binder.declared_type(TYPES[prop]),node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family in ('ModernDataGrid','ModernDataGridColumn'):
                    from .modern_grid import TYPES
                    if prop in TYPES:
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        self.binder.require(inferred,self.binder.declared_type(TYPES[prop]),node,member)
                        self.binder.owner,self.binder.reporting=None,False
                if control.family in CLASSIC_INPUTS:
                    from .classic_inputs import catalog
                    expected_kind=catalog()[control.family]['types'].get(prop)
                    if expected_kind:
                        self.binder.owner,self.binder.reporting=(member,source,id(node)),True
                        expected=self.binder.declared_type(expected_kind)
                        (self.binder.require_function if prop in ('Default','DefaultDate') and control.family not in CLASSIC_BOOLEAN else self.binder.require)(inferred,expected,node,member)
                        self.binder.owner,self.binder.reporting=None,False
                definition = component_definition(self.project, control)
                custom = definition.raw.get("CustomProperties", {}).get(prop) if definition else None
                if custom:
                    try:
                        kind = validate_kind(custom)
                    except FxError:
                        continue
                    output_function = kind == 'Function' and custom.get('PropertyDefinition', custom.get('Direction', 'Output')) != 'Input' and custom.get('PropertyKind') != 'InputFunction'
                    if control.family == "CanvasComponent" and (kind in ("Output", "Action") or output_function):
                        self.diagnostic(origins[id(node)].locate(FxError(f"{member} is defined by its component and cannot be overridden by the host", "Type")), source, member, category="binding")
                    expected = self.binder.component_type(control, prop)
                    if kind not in ("Event", "Action") or expected.kind != 'Void':
                        self.binder.owner, self.binder.reporting = (member, source, id(node)), True
                        self.binder.require_component(inferred, expected, node, f"{member} value")
                        self.binder.owner, self.binder.reporting = None, False
        for (member, source, node_id), error in [(key[0], error) for key, error in self.binder.errors]:
            origin=origins.get(node_id)
            self.diagnostic(origin.locate(error) if origin else error, source, member, category="binding")
        self.fx.node_types = self.binder.nodes
        self.bind_diagnostics = list(self.diagnostics)

    def app_source(self):
        # Project's accepted model selects the last App declaration. Locate the
        # actual property mapping rather than an unrelated earlier document.
        documents=list(self.project.parsed.items())
        return next((n for n,d in reversed(documents) if d.get('App',{}).get('Properties') is self.project.app),
            next((n for n,d in reversed(documents) if 'App' in d),'Src/App.pa.yaml'))

    def restart(self):
        self.trace_event('restart')
        self.reactive.reset()
        from .timers import init
        init(self)
        from .media_controls import init as media_init
        media_init(self)
        self.button_busy=set()
        self.label_heights={}
        from .data_errors import clear
        clear(self.store)
        self.focus_request = None
        self.navigation_positions.clear()
        self.gallery_loading.clear()
        for path, ref in self.refs.items():
            if ref.family in ('ModernRating','FluentV8/Rating','ModernNumberInput',*DATE_PICKERS,'Classic/Slider','Slider'):
                self.scalar_resets[path] = self.scalar_resets.get(path, 0) + 1
            if ref.family in SINGLE_SELECT or ref.family in ('Gallery','DataTable','ModernDataGrid','TabList','Toolbar','CheckBox','Toggle',*CLASSIC_BOOLEAN):
                self.selector_resets[path] = self.selector_resets.get(path, 0) + 1
            if ref.family in COMBOBOXES|LISTBOXES|{'ComboBox','DropDown','Radio'}:
                self.combo_resets[path] = self.combo_resets.get(path, 0) + 1
            if ref.family in TEXT_INPUTS or ref.family in ("RichTextEditor","TextInput"):
                self.text_resets[path] = self.text_resets.get(path, 0) + 1
        self.calendar_months.clear()
        self.globals, self.collections, self.control_state, self.screen_context = {}, {}, {}, {}
        self.component_state = {}
        self.input_baselines = {}
        self.form_item_baselines = {}
        self.reset_property_baselines = {}
        self.component_input_baselines = {}
        self.component_reset_blocks = {}
        self.active_event_stack = []
        self.active_event_chain = ()
        self.resetting.clear()
        self.notifications, self.history, self.event_queue = [], [], []
        self.app_errors.reset()
        self.diagnostics = list(self.bind_diagnostics)
        self.invalidate()
        self.started = True
        self.active_screen = next(iter(self.screens), None)
        self.preview_screen = None
        self.preview_component = None
        self.sync_reset_properties()
        self.store.clock = self.environment.get("clock")
        if self.project.app.get("StartScreen"):
            try:
                from .expressions import app_expression
                screen = self.fx.evaluate(self.project.app["StartScreen"], app_expression(self,'StartScreen').context(Context(self)))
                if not isinstance(screen, Ref) or screen.family != "Screen":
                    raise FxError("StartScreen must evaluate to a screen")
                self.active_screen = screen.name
            except FxError as error:
                self.diagnostic(error, self.app_source(), "App.StartScreen", self.project.app["StartScreen"])
                self.app_errors.observe(error,'App.StartScreen',self.app_source(),'App.StartScreen',self.project.app['StartScreen'])
        if self.project.app.get("OnStart"):
            self.execute(self.project.app["OnStart"], Context(self, behavior=True), self.app_source(), "App.OnStart")
        self.changed_component_inputs()  # Establish defaults before visibility events.
        if self.active_screen:
            self.run_event(self.screens[self.active_screen], "OnVisible")
        self.drain_events()
        self.pending_source = False

    def execute(self, formula, ctx, source="", member="", *, observe_errors=True):
        if not formula:
            return None
        self.trace_event('formula', source=source, member=member, formula=str(formula))
        from .expressions import Expression,app_expression
        origin=ctx.formula_origin
        if origin is None and member.startswith('App.') and self.project.app.get(member[4:])==formula:
            origin=app_expression(self,member[4:])
        if origin is None or str(origin.formula)!=str(formula) or origin.source!=source:
            origin=Expression(formula,source,ctx.error_source or member,ctx.self_ref.path if ctx.self_ref else ctx.component_ref.path if ctx.component_ref else 'App')
        ctx=replace(ctx,error_source=ctx.error_source or member,formula_origin=origin)
        try:
            result = self.fx.evaluate(str(formula), ctx)
        except FxError as error:
            result=origin.locate(error).located(ctx.error_source,ctx.error_source)
            if observe_errors:
                self.diagnostic(result,source,member,formula)
                self.app_errors.observe(result,ctx.error_source,source,member,formula)
        if self.trace is not None:
            self.trace_event('result', member=member, value=serial(result))
        return result

    def trace_event(self, kind, **values):
        if self.trace is not None:
            if len(self.trace) < self.trace_limit:
                self.trace.append({'sequence': len(self.trace) + 1, 'kind': kind, **values})
            else:
                self.trace_truncated = True

    def run_event(self, ref, name, values=None, lineage=None):
        if ref.family in ('Label','Rectangle','Circle','Star'):
            from .classic_display import errors as display_errors
            findings=display_errors(ref.control)
            for member in ('Version','Variant',name):
                if member in findings:
                    self.observe_property_error(ref,member,FxError(findings[member],'Unsupported'))
                    return
        if ref.family in ('Text', 'FluentV8/Label'):
            from .canvas_text import guard
            try:guard(ref, name)
            except FxError as error:
                self.observe_property_error(ref, name, error);return
        if ref.family == 'Button':
            from .canvas_buttons import guard
            try:guard(ref, name)
            except FxError as error:
                self.observe_property_error(ref, name, error);return
        auto_button=ref.family in ('Button','Classic/Button','FluentV8/Label') and name=='OnSelect'
        if auto_button:
            if ref.path in self.button_busy:return
            try:
                if ref.family == 'Button':
                    from .canvas_buttons import spec
                    auto_button=spec(ref)['subscribed_functionalities'].get('autoDisabledViewState') == 'true'
                elif ref.family == 'FluentV8/Label':
                    from .canvas_text import spec
                    auto_button=spec(ref)['subscribed_functionalities'].get('autoDisabledViewState') == 'true'
                else:auto_button=bool(ref.property('AutoDisableOnSelect'))
            except FxError as error:
                self.observe_property_error(ref,'AutoDisableOnSelect',error);return
        if name == 'OnSelect':
            from .galleries import GalleryRecord, choose
            if isinstance(ref.item, GalleryRecord):
                # Select(child) and native child events use the same row path.
                choose(ref.item.gallery, ref.item.key, interactive=True)
        raw = ref.raw_property(name)
        if raw:
            token = (ref.path, name)
            if token in self.active_event_stack:
                raise FxError(f"Event callback cycle: {ref.path}.{name}", "Cycle")
            expression=ref.expression(name)
            ctx = expression.context(ref.context(True))
            if values:
                ctx = ctx.scope(values)
            previous = self.active_event_chain
            self.active_event_chain = (*(previous if lineage is None else lineage), ref.path)
            self.active_event_stack.append(token)
            if auto_button:self.button_busy.add(ref.path)
            try:
                return self.execute(raw, ctx, expression.source, f"{ref.name}.{name}")
            finally:
                if auto_button:self.button_busy.discard(ref.path)
                self.active_event_stack.pop()
                self.active_event_chain = previous

    def component_signature(self, name, custom, instance=None):
        if instance is not None:
            try:return self.component_signature(name,custom)
            except FxError as error:
                from .expressions import contract_expression
                definition=component_definition(self.project,instance.control)
                raise contract_expression(definition,name,error,owner=instance.path).locate(error)
        kind = validate_kind(custom)
        try:specs = custom_parameters(custom)
        except FxError as error:
            error=error.located();error.component_declaration=(None,'Parameters');raise error
        for param, spec in specs:
            from .components import optional_parameter
            try:optional_parameter(spec)
            except FxError as error:
                error=error.located();error.component_declaration=(param,'IsOptional');raise error
            try:
                typ = self.fx.declared_contract(spec.get('DataType'), component=True)
                if typ.kind == 'Void':
                    raise FxError(f'{name}.{param}: Void is not a parameter type', 'Type')
            except FxError as error:
                error=error.located();error.component_declaration=(param,'DataType');raise error
        try:
            result = self.fx.declared_contract(result_type_name(custom), component=True)
            if kind not in ('Action', 'Event') and result.kind == 'Void':
                raise FxError(f'{name}: {kind} requires a value return type', 'Type')
        except FxError as error:
            error=error.located();error.component_declaration=(None,'ReturnType' if 'ReturnType' in custom else 'DataType');raise error
        return specs

    def component_value(self, value, raw, ctx, expected):
        from .binding import value_type
        actual = self.fx.node_types.get(id(self.fx.bound_node(raw, ctx))) if isinstance(raw, str) and raw.startswith('=') else value_type(raw)
        return self.fx.coerce_function(value, expected, actual, restrictive=False)

    def component_call(self, instance, name, custom, values, argument_types=None):
        kind = validate_kind(custom)
        specs = self.component_signature(name, custom,instance)
        params = [p for p, _ in specs]
        if not required_parameters(custom) <= len(values) <= len(params):
            from .components import arity_message
            raise FxError(f"Component {kind.lower()} {name} {arity_message(custom)}",'Type')
        values = list(values)
        argument_types = list(argument_types or [None] * len(values))
        default_origins={}
        from .expressions import parameter_expression
        for param, spec in specs[len(values):]:
            raw = spec.get('Default', '=Blank()')
            origin=parameter_expression(instance,name,param,spec)
            default_origins[len(values)]=origin
            default_ctx = origin.context(Context(self, function_pure=True))
            default = self.fx.evaluate(raw, default_ctx) if isinstance(raw, str) and raw.startswith('=') else raw
            from .binding import value_type
            values.append(default)
            argument_types.append(self.fx.node_types.get(id(self.fx.bound_node(raw, default_ctx))) if isinstance(raw, str) and raw.startswith('=') else value_type(raw))
        for i, ((_, spec), value) in enumerate(zip(specs, values)):
            try:values[i] = self.fx.coerce_function(value, self.binder.parameter_type(spec), argument_types[i], restrictive=False)
            except FxError as error:
                raise default_origins[i].locate(error) if i in default_origins else error
        if kind == "Function":
            ctx = Context(self, function_pure=True)
        else:
            ctx = instance.host_context(True) if kind == "Event" else instance.context(True)
        token = f"{instance.path}.{name}"
        expression=instance.expression(name)
        ctx=expression.context(ctx)
        if token in self.component_call_stack:
            raise FxError(f"Component call cycle: {token}", "Cycle")
        self.component_call_stack.add(token)
        try:
            parameter_types = {param:self.binder.parameter_type(spec) for param,spec in specs}
            ctx = ctx.scope(dict(zip(params, values)), parameter_types=parameter_types)
            result = self.execute(instance.raw_property(name), ctx, expression.source, f"{instance.name}.{name}", observe_errors=False)
        finally:
            self.component_call_stack.remove(token)
        if isinstance(result, FxError):
            raise result
        expected = self.binder.component_type(instance.control, name)
        if expected.kind == 'Void':
            return None
        try:return self.component_value(result, instance.raw_property(name), ctx, expected)
        except FxError as error:raise expression.locate(error)

    def behavior(self, name, args, ctx, fx):
        self.trace_event('behavior', function=name, control=ctx.self_ref.path if ctx.self_ref else None)
        e = lambda i: fx.eval(args[i], ctx)
        if name == "Set":
            target = fx.column(args[0], ctx)
            from .patch import snapshot
            self.scope_values(ctx, "variables")[target] = snapshot(fx.capture(args[1], ctx)); self.invalidate(); return None
        if name == "UpdateContext":
            if ctx.component_ref:
                raise FxError("UpdateContext is not supported inside components", "Validation")
            from .patch import snapshot
            self.screen_context.setdefault(self.screen_for(ctx.self_ref), {}).update(snapshot(e(0))); self.invalidate(); return None
        if name in ("Clear", "Collect", "ClearCollect"):
            target = fx.column(args[0], ctx)
            local = ctx.component_ref and not access_app_scope(self.project, ctx.component_ref)
            if target in self.store.definitions and not local:
                if name != "Collect":
                    raise FxError(f"{name} cannot clear a connected data source")
                from .data_errors import operation
                result = []
                with operation(self.store,target,capture=False):
                    try:
                        for i in range(1, len(args)):
                            value = e(i)
                            for row in table(value) if isinstance(value,(list,DataSource)) else [value]:
                                result.append(self.store.source(target).record(self.store.patch(target, {}, row)))
                        return result
                    finally:
                        self.invalidate()
            values = []
            for i in range(1, len(args)):
                value = e(i)
                values.extend(table(value) if isinstance(value, (DataSource, list)) else [value if isinstance(value, dict) else {"Value": value}])
            collections = self.scope_values(ctx, "collections")
            from .patch import snapshot
            values = snapshot(values)
            if name in ("Clear", "ClearCollect"):
                collections[target] = []
            collections.setdefault(target, []).extend(values)
            self.invalidate(); return collections[target] if name != "Clear" else None
        if name in ("Update", "UpdateIf"):
            from .mutations import execute
            return execute(self, name, args, ctx, fx)
        if name == "Patch":
            from .patch import execute
            return execute(self, args, ctx, fx)
        if name == "Refresh":
            source = e(0)
            if not isinstance(source, DataSource):
                raise FxError("Refresh requires a data source")
            from .data_errors import operation
            try:
                with operation(self.store,source.name):
                    source.rows()
            finally:
                self.invalidate()
            return None
        if name == "Navigate":
            target = e(0)
            if not isinstance(target, Ref) or target.family != "Screen":
                raise FxError("Navigate requires a screen")
            if len(args) > 1:
                e(1)
            if len(args) > 2:
                from .patch import snapshot
                self.screen_context.setdefault(target.name, {}).update(snapshot(e(2)))
            self.navigate(target.name); return True
        if name == "Back":
            if self.history:
                target = self.history.pop()
                self.navigate(target, push=False); return True
            return False
        if name == "Notify":
            self.notifications.append({"message": text(e(0)), "tone": e(1) if len(args) > 1 else "Information"})
            return True
        if name == 'SetFocus':
            from .focus import validate_target, available
            ref = e(0)
            if not isinstance(ref, Ref):
                raise FxError('SetFocus requires a control', 'Type')
            validate_target(ref.control)
            if self.screen_for(ref) != self.screen_for(ctx.self_ref):
                raise FxError('SetFocus cannot target a control on another screen', 'Validation')
            if self.screen_for(ref) != self.active_screen or not available(self, ref):
                return None
            self.focus_request = {'id': uuid4().hex, 'path': ref.path, 'screen': self.active_screen}
            self.trace_event('focus', path=ref.path)
            return None
        if name in ("Reset", "Select", "NewForm", "EditForm", "ViewForm", "ResetForm", "SubmitForm"):
            ref = e(0)
            if not isinstance(ref, Ref):
                raise FxError(f"{name} requires a control")
            if name == "Select":
                if self.screen_for(ref) != self.screen_for(ctx.self_ref):
                    raise FxError("Select cannot target a control on another screen", "Validation")
                target = ref
                if len(args) > 1:
                    if ref.family != "Gallery":
                        raise FxError("Select row arguments require a gallery", "Validation")
                    rows, index = table(ref.property("Items")), e(1)
                    if isinstance(index, bool) or not isinstance(index, (int, float, Decimal)) or not math.isfinite(float(index)) or index != int(index) or not 1 <= index <= len(rows):
                        raise FxError("Select gallery row must be a whole number from 1 through CountRows(Items)", "Validation")
                    from .galleries import keyed_rows
                    row_key, row = keyed_rows(ref)[int(index) - 1]
                    if isinstance(row, FxError):
                        raise row
                    from .gallery_loading import ensure
                    ensure(ref,int(index)-1)
                    if len(args) > 2:
                        child_name = call_name(args[2])
                        if args[2].kind != "name":
                            child = e(2)
                            child_name = child.name if isinstance(child, Ref) else None
                        self.render(ref)  # Materialize stable template instances, even before preview.
                        target = next((c for c in self.descendants(ref) if c.name == child_name and c.path.startswith(f"{ref.path}/row:{row_key}/")
                            and next((a for a in self.ancestors(c) if a.family == "Gallery"), None) is ref), None)
                        if target is None:
                            raise FxError("Select child must belong to the requested gallery template", "Validation")
                lineage = self.active_event_chain or ((ctx.self_ref.path,) if ctx.self_ref else ())
                if target.family in ('Text', 'FluentV8/Label'):
                    from .canvas_text import guard
                    guard(target, 'OnSelect')
                if target.family in ('ModernProgressBar', 'ModernSpinner','DataTable','ModernLink'):
                    raise FxError('Select requires a control with an OnSelect property', 'Validation')
                if target.path in lineage:
                    raise FxError("A control cannot Select itself directly or indirectly", "Cycle")
                if target.family in ("Screen", "Form", "TypedDataCard", "CanvasComponent", "Component") and "OnSelect" not in target.control.properties:
                    raise FxError("Select requires a control with an OnSelect property", "Validation")
                from .galleries import GalleryRecord, choose
                if len(args) > 1:
                    choose(ref, row_key)
                elif ref.family == 'Gallery' and isinstance(ctx.item, GalleryRecord) and ctx.item.gallery is ref:
                    # Explicit Select(Parent) is programmatic selection, including
                    # galleries whose background selection is disabled.
                    choose(ref, ctx.item.key)
                self.event_queue.append((target, "OnSelect", lineage))
                return None
            if name == "Reset":
                if ref.family in ('Text', 'FluentV8/Label'):
                    raise FxError(f'Reset does not support {ref.family}', 'Unsupported')
                if ref.family == 'ModernLink':
                    raise FxError('Reset does not support ModernLink','Unsupported')
                if ref.family in ("DataTable","DataTableColumn"):
                    raise FxError(f"Reset does not support {ref.family}","Validation")
                if ref.family == "HtmlViewer":
                    raise FxError("Reset does not support HtmlViewer", "Validation")
                boundary = next((a for a in self.ancestors(ref) if a.family in ("Gallery", "Form")), None)
                if boundary and ctx.self_ref is not boundary and boundary not in list(self.ancestors(ctx.self_ref)):
                    raise FxError("Reset must run within the same gallery or form; use ResetForm for a form", "Validation")
                self.reset_ref(ref); return None
            if ref.family != "Form":
                raise FxError(f"{name} requires a form")
            if name == "SubmitForm":
                self.submit_form(ref); return None
            self.form_operation(ref, name); return None
        if name in ("Remove", "RemoveIf"):
            from .removal import execute
            return execute(self,name,args,ctx,fx)
        raise FxError(f"Unsupported behavior {name}", "Unsupported")

    def navigate(self, target, push=True):
        self.trace_event('navigation', previous=self.active_screen, target=target)
        if self.active_screen:
            self.run_event(self.screens[self.active_screen], "OnHidden")
            if push and target != self.active_screen:
                self.history.append(self.active_screen)
        self.focus_request = None
        self.active_screen = target
        self.preview_screen = None
        self.preview_component = None
        self.invalidate()
        # Observe each transition, including Away/Home in one behavior chain.
        # Queued playback callbacks still drain in the normal event order.
        from .media_controls import settle as settle_media
        settle_media(self)
        self.run_event(self.screens[target], "OnVisible")

    def descendants(self, ref):
        children = ref.children if ref.family != "Gallery" else [c for c in self.refs.values() if c.parent is ref]
        for child in children:
            yield child
            yield from self.descendants(child)

    def ancestors(self, ref):
        current = ref.parent if ref else None
        while current:
            yield current
            current = current.parent

    def clear_control_state(self, ref):
        if ref.family == 'Gallery' and ref.path in self.gallery_loading:
            self.gallery_loading[ref.path].offset = 0
        ref.state.clear()
        if ref.family == "Timer":
            from .timers import reset
            reset(self,ref)
        if ref.family in ('Audio','Video'):
            from .media_controls import reset
            reset(self,ref)
        if ref.family in ('ModernRating','FluentV8/Rating','ModernNumberInput',*DATE_PICKERS,'Classic/Slider','Slider'):
            self.scalar_resets[ref.path] = self.scalar_resets.get(ref.path, 0) + 1
            self.calendar_months.pop(ref.path, None)
        if ref.family in SINGLE_SELECT or ref.family in ('Gallery','ModernDataGrid','TabList','ModernTabList','Toolbar','CheckBox','Toggle',*CLASSIC_BOOLEAN):
            self.selector_resets[ref.path] = self.selector_resets.get(ref.path, 0) + 1
        if ref.family in COMBOBOXES|LISTBOXES|{'ComboBox','DropDown','Radio'}:
            self.combo_resets[ref.path] = self.combo_resets.get(ref.path, 0) + 1
        if ref.family in TEXT_INPUTS or ref.family in ("RichTextEditor","TextInput"):
            self.text_resets[ref.path] = self.text_resets.get(ref.path, 0) + 1

    def reset_ref(self, ref, *, automatic=False):
        if ref.component_error:
            raise ref.component_error
        if ref.path in self.resetting:
            raise FxError("Component OnReset cannot reset itself recursively", "Cycle")
        if not automatic:
            from .component_lifecycle import rearm
            rearm(self, ref)
        self.clear_control_state(ref)
        if ref.family == "CanvasComponent":
            for child in self.descendants(ref):
                self.clear_control_state(child)
        self.invalidate()
        if ref.family == "CanvasComponent":
            definition = component_definition(self.project, ref.control)
            if definition and definition.properties.get("OnReset"):
                self.resetting.add(ref.path)
                try:
                    from .expressions import mapped
                    expression=mapped(definition.properties,'OnReset',definition.source,ref.path+'.OnReset',ref.path)
                    self.execute(expression.formula, expression.context(ref.context(True)), definition.source, f"{definition.name}.OnReset")
                finally:
                    self.resetting.remove(ref.path)

    def sync_reset_properties(self):
        """Observe rising edges after each behavior primitive, including short pulses."""
        if self.syncing_resets:
            return False
        self.syncing_resets = True
        changed = False
        try:
            for ref in list(self.refs.values()):
                if ref.family not in RESETTABLE:
                    continue
                try:
                    value = ref.property('Reset')
                    if value is not None and not isinstance(value, bool):
                        raise FxError(f'{ref.name}.Reset requires a Boolean', 'Type')
                    value = bool(value)
                except FxError as error:
                    self.observe_property_error(ref,'Reset',error)
                    continue
                self.app_errors.healthy(ref.path+'.Reset')
                previous = self.reset_property_baselines.get(ref.path, False)
                self.reset_property_baselines[ref.path] = value
                if value and not previous:
                    self.reset_ref(ref)
                    changed = True
        finally:
            self.syncing_resets = False
        return changed

    def form_operation(self, form, operation):
        mode = form.property('Mode')
        if operation == 'ResetForm' and mode == 'View':
            return
        if operation == 'ResetForm' and form.path in self.resetting:
            raise FxError('Form OnReset cannot reset itself recursively', 'Cycle')
        target = {'NewForm': 'New', 'EditForm': 'Edit', 'ViewForm': 'View', 'ResetForm': 'Edit'}[operation]
        if operation in ('NewForm', 'ResetForm') or mode == 'New' and target == 'Edit':
            for child in self.descendants(form):
                self.clear_control_state(child)
            form.state.pop('Item', None)
        form.state['Mode'] = target
        if operation in ('EditForm', 'ResetForm'):
            form.state.update(Error='', ErrorKind=0)
        self.invalidate()
        if operation == 'ResetForm':
            self.resetting.add(form.path)
            try:
                self.run_event(form, 'OnReset')
            finally:
                self.resetting.remove(form.path)

    def changed_component_inputs(self, *, reset_counts=None):
        """Observe input changes without executing behavior in property evaluation."""
        from .component_lifecycle import changed_inputs
        return changed_inputs(self, reset_counts)

    def submit_form(self, form):
        if form.property('Mode') == 'View':
            return
        from .data_errors import operation, note
        try:
            form.sync_form_item()
            source = form.property('DataSource')
            if not isinstance(source,DataSource):
                raise FxError('SubmitForm requires a local data source','Type')
            base = {} if form.property('Mode') == 'New' else form.property('Item')
            # Finish the operation before callbacks: a callback's own data
            # function starts a new operation and clears this source's history.
            with operation(self.store,source.name,capture=False):
                errors = []
                for card in form.children:
                    if card.family == 'TypedDataCard':
                        message = card.validation_error()
                        card.state['Error'] = message
                        if message:
                            field = self.store.internal_name(source.name,card.property('DataField'))
                            value = card.property('Update')
                            required = card.property('Required') and (value is None or value == '' or value == [])
                            error = FxError(message,'MissingRequired' if required else 'Validation',column=field)
                            note(self.store,source.name,error,base)
                            errors.append(error)
                self.invalidate()
                if errors:
                    raise FxError.combine(errors)
                if not form.property('Valid'):
                    error = FxError('Required fields or field constraints are not satisfied','Validation')
                    note(self.store,source.name,error,base)
                    raise error
                result = source.record(self.store.patch(source.name,base,form.property('Updates')))
            for child in self.descendants(form):
                self.clear_control_state(child)
            form.state.update({'LastSubmit':result,'Item':result,'Error':'','ErrorKind':0,'Mode':'Edit'})
            self.invalidate()
            self.run_event(form,'OnSuccess')
        except FxError as error:
            form.state.update({'Error':error.message,'ErrorKind':error_number(error.kind)})
            self.invalidate()
            self.run_event(form,'OnFailure')

    def event(self, path, name, value=None, selection=None):
        ref = self.refs.get(path)
        if not ref:
            raise ValueError("Control no longer exists; refresh the preview")
        if ref.family == 'ModernLink':
            raise ValueError('ModernLink navigates through its evaluated URL; Power Fx interaction events are unsupported')
        if ref.family in ('Audio','Video'):
            if name!='OnMedia':raise ValueError('Media controls only accept validated playback observations')
            from .media_controls import observe
            observe(ref,value,selection);return
        if name=='OnMedia':raise ValueError('Playback observations require an Audio or Video control')
        if name == 'OnViewport':
            if ref.family != 'Gallery' or selection is not None:
                raise ValueError('Viewport loading requires a gallery')
            visible_screen = self.preview_screen or self.active_screen
            displayed = (ref.path.startswith(self.preview_component.path + '/') if self.preview_component else self.screen_for(ref) == visible_screen)
            if not displayed:
                raise ValueError('Gallery is not on the displayed screen')
            if any(a.property('Visible') is False for a in [ref,*self.ancestors(ref)]):
                return
            from .gallery_loading import viewport
            viewport(ref,value)
            return
        if ref.family == "Timer" and (name != "OnSelect" or value is not None or selection is not None):
            raise ValueError("Timer only accepts OnSelect interaction; time is advanced by Python")
        if ref.family == "RichTextEditor" and name not in ("OnChange","OnEditorIssue"):
            raise ValueError("Rich text editor only accepts value changes")
        if ref.family == "HtmlViewer" and name != "OnSelect":
            raise ValueError("HTML text only accepts OnSelect interaction events")
        if ref.family in ('ModernBadge','ModernInformationButton'):
            from .icons import active
            if name!='OnSelect' or ref.family=='ModernBadge' and not active(ref):
                raise ValueError('This control does not accept this interaction event')
        if ref.family == 'ModernIcon':
            from .icons import active
            if name != 'OnSelect' or not active(ref):
                raise ValueError('Decorative icons do not accept interaction events')
        if ref.family in ('Label','Rectangle','Circle','Star') and name!='OnSelect':
            raise ValueError('Classic display controls only accept OnSelect interactions')
        if ref.family in ('Text', 'FluentV8/Label'):
            from .canvas_text import spec
            if name not in {e['Name'] for e in spec(ref)['events']} or value is not None or selection is not None:
                raise ValueError('Archived text only accepts recovered selection events without values or selections')
        if ref.family == 'Button' and (name != 'OnSelect' or value is not None or selection is not None):
            raise ValueError('Archived Buttons only accept OnSelect interactions without values or selections')
        if ref.family=='Classic/Button' and name not in ('OnSelect','Pressed'):
            raise ValueError('Classic buttons only accept OnSelect and Pressed interactions')
        if ref.family == 'Classic/Icon' and name!='OnSelect':
            raise ValueError('Classic icons only accept OnSelect interaction events')
        if ref.family in ('ModernProgressBar', 'ModernSpinner'):
            raise ValueError('This control is display-only')
        if ref.family in SINGLE_SELECT and name == 'OnChange' and selection is None and not isinstance(value, dict):
            raise ValueError('Selection event requires item indices')
        if ref.family in CLASSIC_BOOLEAN and name=='OnChange':
            if selection is not None:
                raise ValueError('Checkbox event requires a Boolean value')
            ref.sync_default('Value')
            if isinstance(value,dict):
                if set(value)!={'checked','reset_token'} or not isinstance(value['checked'],bool) or not isinstance(value['reset_token'],str):
                    raise ValueError('Invalid checkbox event')
                if value['reset_token']!=self.selection_epoch(ref):return
                value=value['checked']
            if not isinstance(value,bool):raise ValueError('Checkbox requires a Boolean')
        if name not in ("OnSelect", "OnChange", "OnSort", "OnEditorIssue", 'Pressed', 'OnSearch', 'OnInput', 'OnCalendar', 'OnNavigate'):
            raise ValueError("Unsupported browser event")
        if name == 'OnEditorIssue' and ref.family != 'RichTextEditor':
            raise ValueError('Editor formatting diagnostics require a rich text editor')
        if name == 'OnCalendar' and ref.family not in DATE_PICKERS:
            raise ValueError('Calendar navigation requires a date picker')
        if name == 'OnInput' and ref.family not in TEXT_INPUTS and ref.family not in ('Slider','Classic/Slider','TextInput'):
            raise ValueError('Input output events require a supported text input or slider')
        if name == 'OnSearch' and (ref.family not in (*COMBOBOXES,'ModernDataGrid','ComboBox') or not isinstance(value, (str, dict))):
            raise ValueError('Search requires a combobox and Text value')
        if name=='OnSort' and ref.family!='ModernDataGrid':raise ValueError('Sorting requires a modern grid')
        if name=='OnNavigate':
            if ref.family!='Classic/ComboBox' or selection is not None or not isinstance(value,dict) or set(value)!={'index','option_token'}:
                raise ValueError('Navigate requires a classic ComboBox row and option token')
        if name == 'Pressed':
            if ref.family not in ('ModernButton', 'Classic/Button') or not isinstance(value, bool):
                raise ValueError('Pressed requires a button and Boolean value')
            if not value:
                ref.state['Pressed'] = False
                self.invalidate(); self.sync_reset_properties(); self.drain_events()
                return
        ancestor = ref
        while ancestor:
            if not ancestor.property("Visible") or ancestor.property("DisplayMode") != "Edit":
                return
            ancestor = ancestor.parent
        if ref.family in ('ComboBox','DropDown','Radio','ComboBoxDataField'):
            from .canvas_selectors import event
            if ref.family=='ComboBoxDataField':raise ValueError('Selector fields are metadata')
            event(ref,name,value,selection);return
        if ref.family in ('Slider','Toggle'):
            from .canvas_scalars import event
            event(ref,name,value,selection);return
        if ref.family in ('TextInput','CheckBox'):
            from .canvas_inputs import event
            event(ref,name,value,selection);return
        if ref.family == 'DatePicker':
            from .canvas_dates import event
            event(ref, name, value, selection);return
        if ref.family=="Toolbar":
            from .toolbar import event as toolbar_event
            toolbar_event(ref,name,value,selection);return
        if ref.family == 'TabList':
            from .canvas_tabs import event
            event(ref, name, value, selection);return
        if ref.family=="ModernTabList":
            from .tablist import event as tabs_event
            tabs_event(ref,name,value,selection);return
        if ref.family=='FluentV8/Rating':
            from .fluent_rating import event as rating_event
            rating_event(self,ref,name,value,selection);return
        if ref.family == "ModernRating":
            from .rating import event as rating_event
            rating_event(self,ref,name,value,selection);return
        if ref.family == "ModernDataGrid":
            from .modern_grid import event as grid_event,sync
            if sync(ref):self.invalidate()
            grid_event(ref,name,value,selection);return
        if ref.family == "ModernDataGridColumn":raise ValueError('Select grid rows through their parent grid')
        if ref.family == "DataTable":
            from .data_table import event as table_event
            table_event(ref,name,value,selection);return
        if ref.family == "DataTableColumn":
            raise ValueError("Select a DataTable row through its parent table")
        if ref.family in LISTBOXES:
            from .listbox import event as list_event
            list_event(ref,name,value,selection);return
        if ref.family == "Timer":
            from .timers import toggle
            toggle(self,ref);return
        if ref.family == "RichTextEditor":
            from .rich_text import event as rich_event
            rich_event(self,ref,name,value);return
        if ref.family=='Classic/Slider' and name in ('OnInput','OnChange'):
            from .input_controls import slider_event
            slider_event(self,ref,name,value);return
        if ref.family=='Classic/Slider' and ref.property('ReadOnly'):return
        from .input_controls import input_event
        if input_event(self,ref,name,value):return
        if ref.family in TEXT_INPUTS and name in ('OnInput', 'OnChange'):
            ref.sync_default('Text')
            if isinstance(value, dict):
                if set(value) != {'text','reset_token'} or not isinstance(value['reset_token'],str):
                    raise ValueError('Invalid text input event')
                if value['reset_token'] != self.text_token(ref):
                    return  # Reset/default changes invalidate pending browser edits.
                value = value['text']
            if value is None:
                value = ''
            if not isinstance(value, str):
                raise ValueError('Text input requires Text')
            if ref.family=='Classic/TextInput' and ref.property('Format')=='Number':
                from .classic_inputs import numeric_text
                if not numeric_text(value):raise ValueError('Numeric text input contains unsupported numeric symbols')
            if name == 'OnInput' and ref.family=='ModernTextInput' and ref.property('TriggerOutput') == 'FocusOut':
                raise ValueError('FocusOut output updates only on blur')
            maximum = ref.property('MaxLength')
            if maximum and len(value.encode('utf-16-le', errors='surrogatepass')) // 2 > maximum:
                raise ValueError('Text input exceeds MaxLength')
            previous = ref.property('Text')
            last = ref.state.get('text_last_change', previous)
            baseline = self.input_baselines.get(ref.path)
            ref.state.update(Text=value, dirty=value != text(baseline), text_last_change=last)
            self.invalidate()
            if name == 'OnChange':
                ref.state['text_last_change'] = value
                if value != last:
                    self.run_event(ref, 'OnChange')
            self.drain_events()
            return
        if name=='OnNavigate':
            from .classic_combobox import fields
            rows=table(ref.property('Items'))
            if value['option_token']!=self.combo_token(ref,rows):raise ValueError('Choices changed; refresh before navigating')
            i=value['index']
            if type(i) is not int or not 0<=i<len(rows):raise ValueError('Navigate requires a valid row index')
            if not fields(ref,'NavigateFields'):raise ValueError('ComboBox has no NavigateFields configured')
            if isinstance(rows[i],FxError):raise rows[i]
            if not any(self.same_item(rows[i],r) for r in table(ref.property('SearchItems'))):raise ValueError('Navigate row is not in the current search results')
            ref.state['NavigateItem']=rows[i];self.invalidate();self.run_event(ref,'OnNavigate');self.drain_events();return
        if name == 'OnSearch':
            ref.sync_default('Selected')
            if isinstance(value, dict):
                if set(value) != {'text', 'reset_token'} or not isinstance(value['text'], str) or not isinstance(value['reset_token'], str):
                    raise ValueError('Search requires Text and an instance token')
                if value['reset_token'] != self.selection_epoch(ref):
                    return
                value = value['text']
            if not ref.property('IsSearchable'):
                raise ValueError('Search is disabled for this combobox')
            # Capture defaults before filtering Items by Self.SearchText. Searching
            # is not a selection change and does not dirty a form or fire OnChange.
            selected = list(ref.property('SelectedItems'))
            ref.state.update({'SearchText': value, 'SelectedItems': selected, 'Selected': selected_record(ref,selected)})
            self.invalidate()
            self.drain_events()
            return
        if ref.family in COMBOBOXES and name == 'OnChange' and isinstance(value, dict):
            if set(value) - {'operation', 'index', 'option_token'} or value.get('operation') not in (('toggle','clear','remove') if ref.family=='Classic/ComboBox' else ('toggle','clear')):
                raise ValueError('Invalid combobox selection operation')
            ref.sync_default('Selected')
            rows = table(ref.property('Items'))
            if value.get('option_token') != self.combo_token(ref, rows):
                raise ValueError('Choices changed; refresh the preview before selecting')
            previous = list(ref.property('SelectedItems'))
            selected = list(previous)
            if value['operation'] == 'clear':
                selected = []
            elif value['operation']=='remove':
                i=value.get('index')
                if type(i) is not int or not 0<=i<len(selected):raise ValueError('Selected tag no longer exists')
                selected.pop(i)
            else:
                i = value.get('index')
                if type(i) is not int or not 0 <= i < len(rows):
                    raise ValueError('Selected item no longer exists; refresh the preview')
                chosen = rows[i]
                if ref.family=='Classic/ComboBox' and not any(self.same_item(chosen,r) for r in table(ref.property('SearchItems'))):
                    raise ValueError('Selected row is not in the current search results')
                if isinstance(chosen, FxError):
                    raise chosen
                if not isinstance(chosen, dict):
                    raise ValueError('Combobox items require records')
                found = next((i for i, row in enumerate(selected) if self.same_item(row, chosen)), None)
                if found is not None:
                    selected.pop(found)
                elif ref.property('SelectMultiple'):
                    selected.append(chosen)
                else:
                    selected = [chosen]
            self.commit_combo_selection(ref, selected)
            self.invalidate()
            if selected != previous:
                self.run_event(ref, 'OnChange')
                self.drain_events()
            return
        if name == 'Pressed':
            ref.state['Pressed'] = True
            self.invalidate(); self.sync_reset_properties(); self.drain_events()
            return
        if ref.family in SINGLE_SELECT and name == 'OnChange' and isinstance(value, dict):
            if selection is not None or set(value) != {'indices', 'option_token'}:
                raise ValueError('Invalid selection operation')
            ref.sync_default('Selected')
            rows = table(ref.property('Items'))
            if value['option_token'] != self.selector_token(ref, rows):
                raise ValueError('Choices changed; refresh the preview before selecting')
            selection = value['indices']
            if not isinstance(selection, list):
                raise ValueError('Selection requires zero or one integer item index')
        if ref.family == 'Gallery' and name == 'OnSelect':
            from .galleries import choose, token, keyed_rows
            if isinstance(value, dict):
                if selection is not None or set(value) != {'row_key', 'items_token'}:
                    raise ValueError('Invalid gallery selection operation')
                if value['items_token'] != token(ref):
                    raise ValueError('Gallery items changed; refresh the preview before selecting')
                choose(ref, value['row_key'], interactive=True)
            elif selection is not None:
                rows = keyed_rows(ref)
                if not isinstance(selection, list) or len(selection) != 1 or type(selection[0]) is not int or not 0 <= selection[0] < len(rows):
                    raise ValueError('Gallery selection requires one valid row index')
                choose(ref, rows[selection[0]][0], interactive=True)
            self.invalidate()
            self.run_event(ref, name)
            self.drain_events()
            return
        if selection is not None:
            if ref.family in SINGLE_SELECT:
                if not isinstance(selection, list) or len(selection) > 1 or any(type(i) is not int for i in selection):
                    raise ValueError('Selection requires zero or one integer item index')
                ref.sync_default('Selected')
                rows = table(ref.property('Items'))
                if selection and not 0 <= selection[0] < len(rows):
                    raise ValueError('Selected item no longer exists; refresh the preview')
                chosen = rows[selection[0]] if selection else None
                if ref.family=='Classic/DropDown':
                    if selection and selection[0]>=500:raise ValueError('Classic DropDown displays at most 500 items')
                    if not selection and rows and not ref.property('AllowEmptySelection'):raise ValueError('Classic DropDown does not allow an empty selection')
                if isinstance(chosen, FxError):
                    raise chosen
                previous = ref.property('Selected')
                ref.state.update({'Selected': chosen, 'dirty': not self.same_item(chosen, ref.match_default(rows))})
                self.invalidate()
                if ref.family=='Classic/Radio' and name=='OnChange':self.run_event(ref,'OnSelect')
                if not self.same_item(previous, chosen):
                    self.run_event(ref, name)
                self.drain_events()
                return
            if ref.family in COMBOBOXES:
                ref.sync_default("Selected")
            rows = table(ref.property("Items"))
            if not isinstance(selection, list) or any(type(i) is not int or not 0 <= i < len(rows) for i in selection) or len(set(selection)) != len(selection):
                raise ValueError('Selection requires distinct valid integer item indices')
            if ref.family in COMBOBOXES and not ref.property('SelectMultiple') and len(selection) > 1:
                raise ValueError('This combobox permits one selected item')
            selected = [rows[i] for i in selection if 0 <= i < len(rows)]
            for row in selected:
                if isinstance(row, FxError):
                    raise row
            previous = list(ref.property("SelectedItems"))
            baseline = table(self.input_baselines.get(ref.path))
            dirty = len(selected) != len(baseline) or any(not self.same_item(a, b) for a, b in zip(selected, baseline))
            ref.state.update({"SelectedItems": selected, "Selected": selected_record(ref,selected), "dirty": dirty})
            if name == 'OnChange' and ref.family in COMBOBOXES:
                self.invalidate()
                if len(previous) != len(selected) or any(not self.same_item(a, b) for a, b in zip(previous, selected)):
                    self.run_event(ref, name)
                self.drain_events()
                return
        elif name == "OnChange":
            prop = self.input_property(ref)
            if prop is None:
                raise ValueError("Control does not accept value changes")
            if ref.family in CLASSIC_BOOLEAN:
                previous=ref.property('Value')
            if prop == "Value" and ref.family not in CLASSIC_BOOLEAN and value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)):
                raise ValueError("Number input requires a number")
            if prop == "Checked" and not isinstance(value, bool):
                raise ValueError("Toggle requires a Boolean")
            if prop == "SelectedDate" and value:
                try:
                    parsed = date.fromisoformat(value)
                    value = Temporal("Date", datetime.combine(parsed, datetime.min.time()))
                except (TypeError, ValueError):
                    raise ValueError("Date input requires an ISO calendar date") from None
            if prop == "SelectedDate" and value == "":
                value = None
            if ref.family == 'ModernSlider':
                minimum, maximum = ref.slider_bounds()
                if value is None or not math.isfinite(value):
                    raise ValueError('Slider value requires a finite number')
                value = max(minimum, min(maximum, value))
            ref.sync_default(prop)
            baseline = self.input_baselines.get(ref.path)
            comparable = lambda v: text(v) if prop == 'Text' else bool(v) if prop == 'Checked' or ref.family in CLASSIC_BOOLEAN else v
            ref.state.update({prop: value, "dirty": comparable(value) != comparable(baseline)})
        self.invalidate()
        if ref.family in ('ModernCheckbox',*CLASSIC_BOOLEAN) and name == 'OnChange':
            # Both callbacks see the committed value. Exact Studio callback
            # ordering remains a comparison point in the clean fixture.
            self.run_event(ref, 'OnSelect')
            if ref.family=='ModernCheckbox' or previous!=value:
                self.run_event(ref, 'OnCheck' if value else 'OnUncheck')
                if ref.family=='Classic/Toggle':self.run_event(ref,'OnChange')
        else:
            self.run_event(ref, name)
        self.drain_events()

    def selection_epoch(self, ref):
        epochs = self.selector_resets if ref.family in SINGLE_SELECT or ref.family in CLASSIC_BOOLEAN or ref.family in ('TabList','ModernTabList','Toolbar','CheckBox','Toggle') else self.combo_resets
        return f'{self.text_generation}:{ref.path}:{epochs.get(ref.path, 0)}'

    def selector_token(self, ref, rows):
        snapshot = [self.selection_epoch(ref), serial(rows)]
        if ref.family in CLASSIC_SELECTORS:snapshot.append(ref.property('Value'))
        if ref.family=='Classic/DropDown':snapshot.append(ref.property('AllowEmptySelection'))
        return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def combo_token(self, ref, rows):
        snapshot = [self.selection_epoch(ref), serial(rows), ref.property('SearchText'), ref.property('SelectMultiple')]
        if ref.family=='Classic/ComboBox':snapshot.extend([serial(ref.property(p)) for p in ('SearchItems','SearchFields','DisplayFields','Template','NavigateFields','SelectedItems')])
        return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def scalar_token(self, ref):
        if ref.family == 'DatePicker':
            from .canvas_dates import token
            return token(ref)
        fields=('Max','AcceptsFocus') if ref.family=='FluentV8/Rating' else ('Max','Step') if ref.family=='ModernRating' else ('Min','Max','ReadOnly') if ref.family=='Classic/Slider' else ('StartYear','EndYear','Format','DateTimeZone','IsEditable','StartOfWeek','Language') if ref.family=='Classic/DatePicker' else ('Min','Max','Step','Precision','ContentLanguage') if ref.family=='ModernNumberInput' else ('StartDate','EndDate','Format','DateTimeZone','IsEditable','StartOfWeek','ContentLanguage')
        contract=[serial(ref.property(k)) for k in fields]
        digest=hashlib.sha256(json.dumps(contract,sort_keys=True).encode()).hexdigest()
        return f'{self.text_generation}:{ref.path}:{self.scalar_resets.get(ref.path, 0)}:{digest}'

    def text_token(self, ref):
        from .text_input_state import token
        return token(ref)

    def commit_combo_selection(self, ref, selected):
        baseline = table(self.input_baselines.get(ref.path))
        dirty = len(selected) != len(baseline) or any(not self.same_item(a, b) for a, b in zip(selected, baseline))
        ref.state.update({'SelectedItems': selected, 'Selected': selected_record(ref,selected), 'dirty': dirty})

    def drain_events(self, *, component_changes=()):
        from .component_lifecycle import RESET_LIMIT, block_feedback
        self.sync_reset_properties()
        reset_counts = {}
        event_steps = settle_steps = 0
        while True:
            changes = component_changes or self.changed_component_inputs(reset_counts=reset_counts)
            component_changes = ()
            for ref in changes:
                count = reset_counts.get(ref.path, 0)
                if count >= RESET_LIMIT:
                    block_feedback(self, ref)
                    continue
                reset_counts[ref.path] = count + 1
                self.reset_ref(ref, automatic=True)
            if self.event_queue:
                if event_steps >= 100:
                    self.event_queue.clear()
                    self.diagnostic(FxError("Select event loop exceeded the simulator limit of 100 events", "Cycle"))
                    return
                target, event, lineage = self.event_queue.pop(0)
                self.run_event(target, event, lineage=lineage)
                event_steps += 1
            elif not changes:
                from .timers import settle
                timer_changed=settle(self)
                from .media_controls import settle as settle_media
                media_changed=settle_media(self)
                error_changed=self.app_errors.drain()
                if self.event_queue or timer_changed or media_changed or error_changed:
                    settle_steps += 1
                    if settle_steps >= 100:
                        self.diagnostic(FxError("Event settling exceeded the simulator limit of 100 passes", "Cycle"))
                        return
                    continue
                return

    @staticmethod
    def input_property(ref):
        return {'TabList':'Selected','Slider':'Value','DatePicker':'SelectedDate','ComboBox':'Selected','DropDown':'Selected','Radio':'Selected','TextInput':'Value','CheckBox':'Checked','Toolbar':'Selected','FluentV8/Rating':'Value','ModernRating':'Value','ListBox':'Selected','Classic/ListBox':'Selected','RichTextEditor':'HtmlText','Classic/Toggle':'Value','Classic/Slider':'Value','Classic/DatePicker':'SelectedDate','Classic/CheckBox':'Value','Classic/Radio':'Selected','Classic/TextInput':'Text','Classic/DropDown':'Selected','ModernDropdown': 'Selected', 'ModernRadio': 'Selected', 'ModernCheckbox': 'Checked', 'ModernSlider': 'Value', 'ModernTextInput': 'Text', 'ModernNumberInput': 'Value', 'Toggle': 'Checked',
            'ModernDatePicker': 'SelectedDate', 'Classic/ComboBox':'Selected', 'ModernCombobox': 'Selected', 'ModernTabList': 'Selected'}.get(ref.family)

    def render_property(self,ref,name):
        observed=ref.path+'.'+name
        try:
            value=ref.property(name);self.app_errors.healthy(observed);return value
        except FxError as error:
            self.render_error(ref,name,error)
            raise

    def render_error(self,ref,name,error,observation=None):
        """Observe only values consumed by the preview, after formula catches."""
        self.observe_property_error(ref,name,error,observation)

    def observe_property_error(self,ref,name,error,observation=None):
        """Defer an error consumed by a visual or lifecycle rule boundary."""
        observed=observation or ref.path+'.'+name
        error=error.located(ref.path+'.'+name,observed)
        self.diagnostic(error,ref.control.source,ref.name+'.'+name,ref.raw_property(name))
        self.app_errors.observe(error,observed,ref.control.source,ref.name+'.'+name,ref.raw_property(name),property=True)

    def render(self, ref, depth=0):
        if depth > 30:
            return {"path": ref.path, "name": ref.name, "family": "Unsupported", "errors": ["Nested control limit exceeded"], "props": {}, "children": []}
        props, errors, gate_error = {}, [], False
        if ref.component_error:
            self.diagnostic(ref.component_error, ref.control.source, ref.name)
            return {'path':ref.path,'name':ref.name,'family':'Unsupported','version':ref.control.version,
                    'props':{},'errors':[ref.component_error.message],'children':[]}
        from .icons import CLASSIC_RENDER_PROPERTIES
        render_properties=RENDER_PROPERTIES+sorted(CLASSIC_RENDER_PROPERTIES-set(RENDER_PROPERTIES)) if ref.family=='Classic/Icon' else RENDER_PROPERTIES
        if ref.family in ('ComboBox','DropDown','Radio','ComboBoxDataField'):
            from .canvas_selectors import catalog,LAYOUT
            versions=catalog()[ref.family];types=versions.get(ref.control.version,next(iter(versions.values())))['types']
            render_properties=sorted((set(types)|LAYOUT)-{'Selected','SelectedItems','SearchText','Items','DefaultSelectedItems'})
        if ref.family in ('Text', 'FluentV8/Label'):
            from .canvas_text import catalog, LAYOUT
            versions = catalog()[ref.family]
            types = versions.get(ref.control.version, next(iter(versions.values())))['types']
            render_properties = sorted(set(types) | LAYOUT)
        if ref.family == 'Button':
            from .canvas_buttons import catalog, LAYOUT
            versions = catalog();types = versions.get(ref.control.version, next(iter(versions.values())))['types']
            render_properties = sorted(set(types) | LAYOUT)
        if ref.family == 'TabList':
            from .canvas_tabs import catalog, LAYOUT
            versions = catalog();types = versions.get(ref.control.version, next(iter(versions.values())))['types']
            render_properties = sorted((set(types) | LAYOUT) - {'Selected','SelectedItems','Items','DefaultSelectedItems'})
        if ref.family in ('Slider','Toggle'):
            from .canvas_scalars import catalog,LAYOUT
            versions=catalog()[ref.family];types=versions.get(ref.control.version,next(iter(versions.values())))['types']
            render_properties=sorted((set(types)|LAYOUT)-{'Value','Checked'})
        if ref.family in ('TextInput','CheckBox'):
            from .canvas_inputs import catalog,LAYOUT
            versions=catalog()[ref.family];types=versions.get(ref.control.version,next(iter(versions.values())))['types']
            render_properties=sorted((set(types)|LAYOUT)-{'Value','Checked'})
        if ref.family == 'DatePicker':
            from .canvas_dates import catalog, LAYOUT
            versions = catalog();types = versions.get(ref.control.version, next(iter(versions.values())))['types']
            render_properties = sorted((set(types) | LAYOUT) - {'SelectedDate'})
        if ref.family=='Toolbar':
            from .toolbar import TYPES
            render_properties=sorted(set(TYPES)-{'Items','DefaultSelectedItems'})
        if ref.family=='FluentV8/Rating':
            from .fluent_rating import TYPES
            render_properties=sorted(set(TYPES)-{'Value'})
        if ref.family == "Timer":
            from .timers import TYPES
            render_properties=RENDER_PROPERTIES+sorted(set(TYPES)-set(RENDER_PROPERTIES))
        if ref.family in ('Audio','Video'):
            from .media_controls import TYPES
            render_properties=RENDER_PROPERTIES+sorted(set(TYPES)-set(RENDER_PROPERTIES))
        if ref.family == "RichTextEditor":
            from .rich_text import TYPES
            render_properties=RENDER_PROPERTIES+sorted(set(TYPES)-set(RENDER_PROPERTIES)-{"Default"})
        if ref.family == "HtmlViewer":
            from .html_controls import TYPES
            render_properties=RENDER_PROPERTIES+sorted(set(TYPES)-set(RENDER_PROPERTIES))
        if ref.family=='Classic/ComboBox':
            from .classic_combobox import catalog
            render_properties=RENDER_PROPERTIES+sorted(set(catalog()['types'])-set(RENDER_PROPERTIES)-{'SearchText'})+['Template','DisplayFields','SearchFields','NavigateFields','NoSelectionText']
        if ref.family in LISTBOXES:
            from .listbox import catalog
            render_properties=RENDER_PROPERTIES+sorted(set(catalog()['types'])-set(RENDER_PROPERTIES))
        if ref.family in CLASSIC_INPUTS:
            from .classic_inputs import catalog
            render_properties=RENDER_PROPERTIES+sorted(set(catalog()[ref.family]['types'])-set(RENDER_PROPERTIES))
        if ref.family == "ModernDataGrid":
            from .modern_grid import TYPES
            render_properties=RENDER_PROPERTIES+sorted(set(TYPES)-set(RENDER_PROPERTIES)-{'Items','DefaultSelectedItems','SearchText','FieldDisplayName'})
        if ref.family == "ModernTabList":
            from .tablist import TYPES
            render_properties=RENDER_PROPERTIES+sorted(set(TYPES)-set(RENDER_PROPERTIES)-{'ItemDisplayText'})
        if ref.family == "DataTable":
            from .data_table import TYPES
            render_properties=RENDER_PROPERTIES+sorted(set(TYPES)-set(RENDER_PROPERTIES)-{"Items","Text","FieldName","FieldDisplayName","DisplayName","AutoWidth","IsHyperlink","Order"})
        if ref.family in ('ModernBadge','ModernInformationButton'):
            from .status_controls import TYPES,ENUM_PROPERTIES
            render_properties=RENDER_PROPERTIES+sorted((set(TYPES)|{'Content'}|set(ENUM_PROPERTIES))-set(RENDER_PROPERTIES))
        if ref.family == 'ModernButton':
            from .modern_button import TYPES
            render_properties=RENDER_PROPERTIES+sorted(set(TYPES)-set(RENDER_PROPERTIES))
        if ref.family == 'ModernLink':
            from .modern_link import TYPES
            render_properties = sorted((set(TYPES) | set(ref.control.properties))-{'Url','Name'})
        if ref.family in ('Label','Rectangle','Circle','Star'):
            from .classic_display import TYPES,properties as display_properties
            allowed=display_properties(ref.control)
            render_properties=[n for n in RENDER_PROPERTIES if n in allowed or n in ref.control.properties]+sorted(set(TYPES[ref.family])-set(RENDER_PROPERTIES))
        if ref.family=='Classic/Button':
            from .classic_button import TYPES
            render_properties=RENDER_PROPERTIES+sorted(set(TYPES)-set(RENDER_PROPERTIES))
        for name in render_properties:
            if ref.family == 'ModernProgressBar' and name == 'Max':
                continue  # Indeterminate rendering must not observe Value/Max errors.
            if ref.raw_property(name) is not None:
                try:
                    value = self.render_property(ref,name)
                    props[name] = float(value) if isinstance(value, Decimal) else serial(value)
                except FxError as error:
                    errors.append(f"{name}: {error.message}")
                    if name in ("DisplayMode", "Visible"):
                        gate_error = True
        if gate_error:
            props["DisplayMode"] = "Disabled"
        node = {"path": ref.path, "name": ref.name, "family": ref.family, "version": ref.control.version,
            "selectable": "OnSelect" in ref.control.properties or ref.raw_property("OnSelect") == "=Select(Parent)",
            "variant": ref.control.raw.get("Variant", ""), "props": props, "errors": errors, "children": []}
        from .focus import tab_stop
        try:
            node['tab_stop'] = tab_stop(ref)
        except FxError as error:
            node['tab_stop'] = False
            errors.append(error.message)
            self.diagnostic(error, ref.control.source, ref.name + '.Focus')
        for prop, message in contract_errors(ref.control).items():
            self.diagnostic(FxError(message, 'Unsupported'), ref.control.source, f'{ref.name}.{prop}', ref.raw_property(prop))
            errors.append(message)
        if ref.family in ('Text', 'FluentV8/Label'):
            from .canvas_text import render as render_text
            try:render_text(ref, node)
            except FxError as error:errors.append(error.message)
        if ref.family in ('ModernBadge','ModernInformationButton'):
            from .status_controls import render as render_status
            render_status(ref,node)
        if ref.family == 'Button':
            try:
                from .canvas_buttons import render as render_button
                render_button(ref, node)
            except FxError as error:
                self.render_error(ref, 'Icon', error);errors.append(error.message)
        if ref.family == 'ModernButton':
            from .modern_button import render as render_button
            render_button(ref,node)
        if ref.family == 'ModernLink':
            from .modern_link import render as render_link
            render_link(ref,node)
        if ref.family in ('Label','Rectangle','Circle','Star'):
            from .classic_display import render as render_display
            render_display(ref,node)
        if ref.family=='Classic/Button':
            from .classic_button import render as render_classic_button
            render_classic_button(ref,node)
        if ref.family in ('ModernIcon','Classic/Icon'):
            from .icons import glyph,active,classic_glyph
            if ref.family == 'ModernIcon':node['selectable']=active(ref)
            if ref.family == 'Classic/Icon':
                node['selectable']=active(ref) or ref.raw_property('OnSelect')=='=Select(Parent)'
            try:node['icon']=classic_glyph(ref.property('Icon')) if ref.family=='Classic/Icon' else glyph(ref.property('Icon'),ref.property('IconStyle') if ref.family=='ModernIcon' else 'Outline')
            except FxError as error:
                errors.append(error.message)
                self.diagnostic(error,ref.control.source,f'{ref.name}.Icon',ref.raw_property('Icon'))
        if ref.family == "RichTextEditor":
            from .rich_text import sanitize,issues
            try:
                result=sanitize(ref.property("Default") or "")
                messages=tuple(sorted(set(result["issues"])|set(ref.state.get("rich_issues",()))))
                issues(self,ref,messages);errors.extend(messages)
            except (FxError,ValueError) as error:
                errors.append(str(error))
                self.diagnostic(error if isinstance(error,FxError) else FxError(str(error),"Validation"),ref.control.source,ref.name+".Default",ref.raw_property("Default"))
        if ref.family == "HtmlViewer":
            from .html_controls import fragment
            safe=fragment(props.get("HtmlText") or "")
            node["html"]=safe["html"]
            for message in safe["issues"]:
                errors.append(message)
                self.diagnostic(FxError(message,"Unsupported"),ref.control.source,ref.name+".HtmlText",ref.raw_property("HtmlText"))
        if ref.family == "Timer":
            from .timers import snapshot
            node["timer"]=next((s for s in snapshot(self)["controls"] if s["path"]==ref.path),{"running":False,"value":0})
        if ref.family in ('Audio','Video'):
            from .media_controls import snapshot
            node['media']=snapshot(ref)
        if props.get("Visible") is False:
            return node
        if ref.family == "Gallery":
            try:
                rows = table(self.render_property(ref,"Items"))
                node["selected"] = serial(self.render_property(ref,"Selected"))
                node["rows"] = []
                from .galleries import materialize, selected, token, row_frames
                selected_key = selected(ref)[0]
                node['items_token'] = token(ref)
                node['reset_token'] = f'{self.text_generation}:{self.selector_resets.get(ref.path, 0)}'
                from .gallery_loading import metadata,sync
                node['loading']=metadata(ref)
                state,all_rows,_,start,end,_=sync(ref)
                indices={key:index for index,(key,_) in enumerate(all_rows)}
                for row_key,row,children in materialize(ref):
                    index=indices[row_key]
                    if not start<=index<end:
                        continue
                    row_path = f"{ref.path}/row:{row_key}"
                    if isinstance(row, FxError):
                        self.render_error(ref,'Items',row,row_path+'.Items')
                        node["rows"].append({"index": index, "key": row_key, "item": serial(row), "children": [], "error": row.record()})
                        continue
                    from .focus import ordered_nodes
                    row_children = ordered_nodes(self, [self.render(child, depth + 1) for child in children], ref)
                    row_props = {}
                    for prop in ('TemplateFill', 'ItemAccessibleLabel'):
                        try:
                            from .row_rules import gallery_formula
                            row_props[prop] = serial(gallery_formula(ref,prop,row,row_key))
                            self.app_errors.healthy(row_path+'.'+prop)
                        except FxError as error:
                            self.render_error(ref,prop,error,row_path+'.'+prop)
                            errors.append(f'{prop}: {error.message}')
                    node["rows"].append({"index": index, "key": row_key, "item": serial(row), "selected": row_key == selected_key, "props": row_props, "children": row_children})

            except FxError as error:
                errors.append(error.message)
        elif ref.family in ('ComboBox','DropDown','Radio'):
            try:
                from .canvas_selectors import render
                render(ref,node)
            except FxError as error:
                self.render_error(ref,'Items',error);errors.append(error.message)
        elif ref.family=='ComboBoxDataField':
            node['metadata']=True
        elif ref.family in ('Slider','Toggle'):
            try:
                from .canvas_scalars import render
                render(ref,node)
            except FxError as error:
                self.render_error(ref,self.input_property(ref),error);errors.append(error.message)
        elif ref.family in ('TextInput','CheckBox'):
            try:
                from .canvas_inputs import render
                render(ref,node)
            except FxError as error:
                self.render_error(ref,self.input_property(ref),error);errors.append(error.message)
        elif ref.family == 'DatePicker':
            try:
                from .canvas_dates import render
                render(ref, node)
            except FxError as error:
                self.render_error(ref, 'SelectedDate', error);errors.append(error.message)
        elif ref.family=='Toolbar':
            try:
                from .toolbar import render as toolbar_render
                toolbar_render(ref,node)
            except FxError as error:
                self.render_error(ref,'Items',error);errors.append(error.message)
        elif ref.family=='FluentV8/Rating':
            try:
                from .fluent_rating import render as rating_render
                rating_render(ref,node)
            except FxError as error:
                self.render_error(ref,'Value',error);errors.append(error.message)
        elif ref.family == "ModernRating":
            try:
                from .rating import render as rating_render
                rating_render(ref,node)
            except FxError as error:
                self.render_error(ref,"Value",error);errors.append(error.message)
        elif ref.family == "ModernDataGrid":
            try:
                from .modern_grid import render as grid_render
                grid_render(ref,node)
            except FxError as error:
                self.render_error(ref,'Items',error);errors.append(error.message)
        elif ref.family == "DataTable":
            try:
                from .data_table import render as table_render
                table_render(ref,node)
            except FxError as error:
                self.render_error(ref,"Items",error);errors.append(error.message)
        elif ref.family in LISTBOXES:
            try:
                from .listbox import render as list_render
                list_render(ref,node)
            except FxError as error:
                self.render_error(ref,'Items',error);errors.append(error.message)
        elif ref.family == 'TabList':
            try:
                from .canvas_tabs import render
                render(ref, node)
            except FxError as error:
                self.render_error(ref, 'Selected', error);errors.append(error.message)
        elif ref.family=='ModernTabList':
            try:
                from .tablist import render as tabs_render
                tabs_render(ref,node)
            except FxError as error:
                self.render_error(ref,'Items',error);errors.append(error.message)
        elif ref.family in ("Classic/Radio","Classic/DropDown",*COMBOBOXES, "ModernDropdown", "ModernRadio"):
            error_property = 'Items'
            try:
                items = table(self.render_property(ref,"Items"))
                if ref.family in COMBOBOXES and any(row is not None and not isinstance(row, (dict, FxError)) for row in items):
                    raise FxError('Combobox Items requires record rows', 'Type')
                node["options"] = []
                for index, row in enumerate(items[:500] if ref.family=='Classic/DropDown' else items):
                    try:
                        if isinstance(row, FxError):
                            raise row
                        label_formula = ref.raw_property("ItemDisplayText")
                        if ref.family=='Classic/ComboBox':
                            from .classic_combobox import display
                            label=(display(ref,row) or [''])[0]
                        elif ref.family in CLASSIC_SELECTORS:
                            from .classic_inputs import display
                            label=display(ref,row)
                        else:
                            from .row_rules import item_formula
                            label = item_formula(ref,"ItemDisplayText",row) if label_formula else row.get("Label", row.get("Value", row.get("Value1", row.get("Title", row.get("DisplayName", str(row))))))
                        node["options"].append({"index": index, "label": text(label)})
                    except FxError as error:
                        self.render_error(ref,"ItemDisplayText",error,ref.path+f"/option:{index}.ItemDisplayText")
                        node["options"].append({"index": index, "label": "Power Fx error: " + error.message, "disabled": True})
                error_property = 'Default' if ref.family in SINGLE_SELECT else 'DefaultSelectedItems'
                if ref.family in SINGLE_SELECT:
                    selected = self.render_property(ref,'Selected')
                    chosen = [selected] if selected is not None else []
                    node['option_token'] = self.selector_token(ref, items)
                else:
                    chosen = self.render_property(ref,"SelectedItems")
                node["selection"] = [i for i, row in enumerate(items) if any(self.same_item(row, selected) for selected in chosen)]
                if ref.family in COMBOBOXES:
                    query = ref.property('SearchText')
                    node['search_text'] = query
                    node['search_reset'] = self.selection_epoch(ref)
                    node['option_token'] = self.combo_token(ref, items)
                    node['selected_labels'] = []
                    for row in chosen:
                        if row is None:
                            continue
                        if isinstance(row, FxError):
                            raise row
                        if not isinstance(row, dict):
                            raise FxError('Combobox SelectedItems requires record rows', 'Type')
                        label_formula = ref.raw_property('ItemDisplayText')
                        if ref.family=='Classic/ComboBox':
                            from .classic_combobox import display
                            node['selected_labels'].append((display(ref,row) or [''])[0]);continue
                        from .row_rules import item_formula
                        label = item_formula(ref,"ItemDisplayText",row) if label_formula else row.get('Label', row.get('Value', row.get('Value1', row.get('Title', row.get('DisplayName', str(row))))))
                        node['selected_labels'].append(text(label))
                    if ref.family=='Classic/ComboBox':
                        from .classic_combobox import decorate
                        decorate(ref,node,items,chosen)
                    elif ref.property('IsSearchable') and query and ref.path not in self.combo_search_items:
                        # Display filtering is also server-owned, retaining indices
                        # into authored Items for selection and custom Search queries.
                        node['options'] = [o for o in node['options'] if query.lower() in o['label'].lower()]
            except FxError as error:
                self.render_error(ref,error_property,error)
                errors.append(error.message)
        elif ref.family in ("RichTextEditor","Classic/Toggle","Classic/Slider","Classic/DatePicker","Classic/CheckBox","Classic/TextInput","ModernCheckbox", "ModernSlider", "ModernTextInput", "ModernNumberInput", "Toggle", "ModernDatePicker"):
            key = self.input_property(ref)
            try:
                node["value"] = serial(self.render_property(ref,key))
                if ref.family in CLASSIC_BOOLEAN:node['check_reset']=self.selection_epoch(ref)
                if ref.family in (*DATE_PICKERS,'ModernNumberInput','Classic/Slider'):
                    from .input_controls import date_calendar, number_text
                    node['input_reset'] = self.scalar_token(ref)
                    if ref.family in DATE_PICKERS:node['calendar'] = date_calendar(ref)
                    elif ref.family=='ModernNumberInput':node['formatted_value'] = number_text(ref,ref.property(key))
                if ref.family in TEXT_INPUTS or ref.family == "RichTextEditor":
                    node['text_reset'] = self.text_token(ref)
            except FxError as error:
                errors.append(error.message)
        elif ref.family == 'ModernProgressBar':
            try:
                if ref.property('Indeterminate'):
                    node['progress'] = {'indeterminate': True}
                else:
                    maximum, value = self.render_property(ref,'Max'), self.render_property(ref,'Value')
                    node['progress'] = {'indeterminate': False, 'max': float(maximum), 'value': float(max(0, min(maximum, value)))}
            except FxError as error:
                errors.append(error.message)
        if ref.family not in ("Gallery","DataTable","ModernDataGrid"):
            from .focus import ordered_nodes
            node["children"] = ordered_nodes(self, [self.render(child, depth + 1) for child in ref.children], ref)
        if ref.family == "Form":
            for key in ("Mode", "Unsaved", "Valid", "Error", "LastSubmit", "NumberOfColumns"):
                try:
                    props[key] = serial(self.render_property(ref,key))
                except FxError as error:
                    errors.append(error.message)
        if ref.family == "Form":
            from .form_layout import decorate
            decorate(ref,node)
        return node

    def state(self):
        from .media_controls import snapshots as media_snapshots
        self.drain_events()
        shown = self.preview_screen or self.active_screen
        root = self.render(self.preview_component) if self.preview_component else self.render(self.screens[shown]) if shown in self.screens else None
        from .timers import settle
        timer_changed=settle(self)
        if timer_changed:self.drain_events()
        from .media_controls import settle as settle_media
        if settle_media(self):self.drain_events()
        reset_changed = self.sync_reset_properties()
        from .modern_grid import sync as grid_sync
        for ref in list(self.refs.values()):
            if ref.family=='ModernDataGrid':
                try:
                    if grid_sync(ref):reset_changed=True;self.invalidate()
                except FxError as error:self.diagnostic(error,ref.control.source,f'{ref.name}.Defaults',ref.raw_property('DefaultSelectedItems'))
        # Gallery templates can create instances or refresh their ThisItem only
        # while rendering. Establish baselines, then settle changed row inputs.
        changes = self.changed_component_inputs()
        if changes or reset_changed or timer_changed:
            self.drain_events(component_changes=changes)
            shown=self.preview_screen or self.active_screen
            root = self.render(self.preview_component) if self.preview_component else self.render(self.screens[shown]) if shown in self.screens else None
        for _ in range(4):
            if not self.app_errors.pending:break
            self.drain_events()
            shown=self.preview_screen or self.active_screen
            root=self.render(self.preview_component) if self.preview_component else self.render(self.screens[shown]) if shown in self.screens else None
        focus = self.focus_request
        if focus:
            from .focus import available
            ref = self.refs.get(focus['path'])
            try:
                if self.preview_component or self.preview_screen or focus['screen'] != self.active_screen or not ref or not available(self, ref):
                    focus = None
            except FxError:
                focus = None
        from .timers import refs,snapshot
        timer_info=snapshot(self) if refs(self) else None
        return {"error_reports":serial(self.app_errors.reports),"timers":timer_info,"focus_request": focus, "screen": self.preview_component.name if self.preview_component else shown, "active_screen": self.active_screen,
            "inspection": bool(self.preview_screen or self.preview_component), "component_preview": bool(self.preview_component),
            "started": self.started, "pending_source": self.pending_source, "viewport": self.viewport,
            **({'media': media_snapshots(self)} if self.media_states else {}), "tree": root, "gallery_instances": {path:sorted(value.keys) for path,value in self.gallery_loading.items()}, "globals": serial(self.globals), "collections": serial(self.collections),
            "data_errors": serial({name: [row for _,row in entries] for name,entries in self.store.operation_errors.items() if entries}),
            "contexts": serial(self.screen_context),
            "components": serial(self.component_state), "types": self.inspector_types(),
            "notifications": self.notifications[-5:], "diagnostics": self.diagnostics}

    def inspector_types(self):
        from .inspection import observe
        return observe(self)

    def analysis(self):
        binder = self.binder
        def info(t):
            return {"display": t.describe(), "schema": t.json()}
        named = {}
        for name, d in self.fx.definitions.items():
            refs = sorted({n.value for n in walk(d.body) if n.kind in ("name", "global") and n.value in self.fx.definitions})
            named[name] = {**info(binder.definition(name)), "kind": "type" if d.alias else "behavior function" if d.behavior else "function" if d.params is not None else "formula", "dependencies": refs}
        return {"named": named, "variables": {n: info(t) for n, t in binder.variables.items()},
            "collections": {n: info(t) for n, t in binder.collections.items()},
            "component_variables": {c: {n: info(t) for n, t in values.items()} for c, values in binder.component_variables.items()},
            "component_collections": {c: {n: info(t) for n, t in values.items()} for c, values in binder.component_collections.items()},
            "note": "Unknown types or open record schemas indicate incomplete inference or metadata; this report is not a Studio checker result."}

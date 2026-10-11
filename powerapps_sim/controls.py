"""Versioned renderer contracts and default properties."""

SUPPORTED = {
    "Button": {"0.0.43", "0.0.44"},
    "TabList": {"2.2.29"},
    "Radio": {"0.0.23","0.0.24"},
    'DatePicker': {'0.0.38', '0.0.42'},
    "ComboBox": {"0.0.48","0.0.49"}, "DropDown": {"0.0.44"}, "ComboBoxDataField": {"1.5.0"},
    "TextInput": {"0.0.51", "0.0.53"}, "CheckBox": {"0.0.26", "0.0.27", "0.0.30"},
    "Toolbar": {"2.0.4"},
    'FluentV8/Rating': {'1.5.1'},
    'ModernLink': {'1.0.0'},
    'Audio': {'', '2.1.0'}, 'Video': {''},
    "ModernBadge": {"1.0.0"}, "ModernInformationButton": {"1.0.0"},
    "ModernRating": {"1.0.0"},
    "ModernDataGrid":{"1.1.0"},"ModernDataGridColumn":{"1.1.0"},
    "DataTable":{"1.0.2"},"DataTableColumn":{"1.0.1"},
    "Classic/ListBox":{"2.2.0"},"ListBox":{"2.2.0"},
    "Classic/ComboBox": {"2.3.0","2.3.1","2.4.0"},
    "Timer": {"2.0.0","2.0.1","2.1.0"},
    "RichTextEditor": {"2.3.0", "2.5.0", "2.6.0"},
    "HtmlViewer": {"2.0.0", "2.1.0"},
    "ModernIcon": {"1.1.0"},
    "Classic/Icon": {"2.5.0"},
    "Classic/TextInput": {"2.3.2"}, "Classic/DropDown": {"2.3.1"},
    "Classic/Toggle": {"2.1.0"}, "Classic/Slider": {"2.0.1","2.1.0"}, "Classic/DatePicker": {"2.6.0"},
    "Classic/CheckBox": {"2.0.1", "2.1.0"}, "Classic/Radio": {"2.3.0"},
    "ModernDropdown": {"1.0.0"}, "ModernRadio": {"1.0.0"},
    "ModernProgressBar": {"1.0.0"}, "ModernSpinner": {"1.1.0"},
    "ModernCheckbox": {"1.0.0"}, "ModernSlider": {"1.0.0"},
    "ModernText": {"1.0.0"}, "ModernButton": {"1.0.0"}, "ModernCombobox": {"1.0.0", "1.1.2"},
    "ModernTextInput": {"1.0.0", "1.1.2"}, "ModernNumberInput": {"1.0.0", "1.1.2"}, "ModernDatePicker": {"1.0.0", "1.0.2"},
    "ModernTabList": {"1.0.0", "1.0.2"}, "Toggle": {"1.1.2","1.1.4","1.1.5"}, "Slider": {"1.0.29","1.0.31"}, "Label": {"2.5.1"},
    "Classic/Button": {"2.0.0","2.0.1","2.2.0"}, "Rectangle": {"2.3.0"}, "Image": {"2.2.3"},
    "GroupContainer": {"1.5.0"}, "Gallery": {"2.15.0"}, "Form": {"2.4.4"},
    "TypedDataCard": {"1.0.7"}, "CanvasComponent": {""}, "Screen": {""}, "Component": {""},
}

from .canvas_text import catalog as canvas_text_catalog
SUPPORTED.update({f: set(v) for f, v in canvas_text_catalog().items()})
from .classic_display import VERSIONS as DISPLAY_VERSIONS,defaults as display_defaults
SUPPORTED.update({f:set(v) for f,v in DISPLAY_VERSIONS.items()})

COMMON = {"X": "=0", "Y": "=0", "Visible": "=true", "DisplayMode": "=DisplayMode.Edit",
          "Width": "=160", "Height": "=40", "Fill": "=Color.Transparent", "Color": "=RGBA(36,36,36,1)",
          "Font": "=Font.'Segoe UI'", "Size": "=14", "FontWeight": "=FontWeight.Normal",
          "PaddingTop": "=0", "PaddingBottom": "=0", "PaddingLeft": "=0", "PaddingRight": "=0",
          "BorderThickness": "=0", "RadiusTopLeft": "=0", "LayoutMinWidth": "=0", "LayoutMinHeight": "=0",
          "LayoutMaxWidth": "=0", "LayoutMaxHeight": "=0", "FillPortions": "=0", "AlignInContainer": "=AlignInContainer.SetByContainer",
          "ContentLanguage": "=Language()", "AccessibleLabel": '=""', "Tooltip": '=""', "OnSelect": "=Blank()", "OnChange": "=Blank()"}
DEFAULTS = {
    # Verified template defaults from Microsoft's TestEngine sample. Common
    # border defaults are simulator approximations, not recovered theme data.
    "Classic/Icon": {"Icon":"=Icon.ArrowDown", "Rotation":"=0", "Width":"=64", "Height":"=64", "TabIndex":"=-1", "PreserveAspectRatio":"=true", "Color":"=RGBA(0,0,0,1)", "DisabledColor":"=RGBA(119,119,119,1)", "HoverColor":"=ColorFade(Self.Color,20%)", "PressedColor":"=ColorFade(Self.Color,-20%)", "Fill":"=RGBA(0,0,0,0)", "DisabledFill":"=Self.Fill", "HoverFill":"=Self.Fill", "PressedFill":"=Self.Fill", "BorderColor":"=RGBA(0,0,0,1)", "DisabledBorderColor":"=RGBA(56,56,56,1)", "HoverBorderColor":"=ColorFade(Self.BorderColor,20%)", "PressedBorderColor":"=ColorFade(Self.BorderColor,-20%)", "FocusedBorderColor":"=Self.BorderColor", "FocusedBorderThickness":"=4"},
    "ModernIcon": {"Icon": '="Add"', "IconStyle": "=IconStyle.Outline", "IconColor": "=Coalesce(Self.BasePaletteColor,Self.Color)", "BasePaletteColor": "=Blank()", "Rotation": "=0", "Width": "=32", "Height": "=32", "BorderColor": "=Color.Transparent", "BorderStyle": "=BorderStyle.Solid", "RadiusTopRight": "=0", "RadiusBottomLeft": "=0", "RadiusBottomRight": "=0"},
    "ModernDropdown": {"Items": "=Table()", "Default": "=Blank()", "Required": "=false", "ValidationState": "=ValidationState.None", "Appearance": "=Appearance.FilledDarker", "Width": "=320", "Height": "=32"},
    "ModernRadio": {"Items": "=Table()", "Default": "=Blank()", "Required": "=false", "Layout": "=Layout.Vertical", "Width": "=320", "Height": "=Max(32, If(Self.Layout = Layout.Horizontal, Self.LineHeight, CountRows(Self.Items) * Self.LineHeight)) + Self.PaddingTop + Self.PaddingBottom", "LineHeight": "=32", "RadioSize": "=16"},
    "ModernProgressBar": {"Value": "=50", "Max": "=100", "Indeterminate": "=false", "ProgressColor": "=ProgressColor.Brand", "Thickness": "=ProgressThickness.Medium", "Shape": "=ProgressShape.Rounded", "Width": "=200", "Height": "=8"},
    "ModernSpinner": {"Label": '=""', "LabelPosition": "=SpinnerLabelPosition.After", "Appearance": "=Appearance.Primary", "Width": "=200", "Height": "=40"},
    "Screen": {"Width": "=App.Width", "Height": "=App.Height", "Fill": "=Color.White"},
    "GroupContainer": {"Width": "=500", "Height": "=200", "LayoutDirection": "=LayoutDirection.Vertical",
        "LayoutAlignItems": "=LayoutAlignItems.Start", "LayoutJustifyContent": "=LayoutJustifyContent.Start", "LayoutGap": "=0",
        "LayoutOverflowX": "=LayoutOverflow.Hide", "LayoutOverflowY": "=LayoutOverflow.Hide", "LayoutWrap": "=false"},
    "ModernText": {"Text": '=""', "Wrap": "=true", "AutoHeight": "=false", "Height": "=32", "Width": "=150", "Size": "=15"},
    "Label": {"Text": '=""', "Wrap": "=true", "AutoHeight": "=false", "Size": "=13"},
    "ModernButton": {"Text": '="Button"', "Appearance": "=ButtonAppearance.Primary", "BasePaletteColor": "=RGBA(15,108,189,1)", "Width": "=96", "Height": "=32"},
    "Classic/Button": {"Text": '="Button"', "Fill": "=RGBA(15,108,189,1)", "Color": "=Color.White"},
    "ModernTextInput": {"Default": '=""', "Type": "=TextInputType.Text", "Mode": "=TextMode.SingleLine", "MaxLength": "=0", "Width": "=320", "Height": "=32", "TriggerOutput": "=TriggerOutput.Keypress", "Required": "=false", "ValidationState": "=ValidationState.None", "Appearance": "=Appearance.FilledDarker"},
    "ModernNumberInput": {"Default": "=Blank()", "Min": "=Blank()", "Max": "=Blank()", "Precision": "=DecimalPrecision.Auto", "Step": "=1", "HintText": '=""', "ValidationState": "=ValidationState.None", "Appearance": "=Appearance.FilledDarker", "Width": "=320", "Height": "=32"},
    "ModernCheckbox": {"Checked": "=false", "Label": '="Checkbox"', "Width": "=160", "Height": "=32", "OnCheck": "=Blank()", "OnUncheck": "=Blank()"},
    "ModernSlider": {"Default": "=50", "Min": "=0", "Max": "=100", "Width": "=200", "Height": "=35", "LayoutDirection": "=LayoutDirection.Horizontal", "Size": "=SliderSize.Medium"},
    "Toggle": {"Default": "=false", "Label": '=""', "Width": "=113"},
    "ModernCombobox": {"Items": "=Table()", "DefaultSelectedItems": "=Table()", "SelectMultiple": "=true", "IsSearchable": "=true", "DelayOutput": "=false", "MultiValueDelimiter": '=", "', "InputTextPlaceholder": '="Find items"', "Required": "=false", "ValidationState": "=ValidationState.None", "Appearance": "=Appearance.FilledDarker", "Width": "=320", "Height": "=32"},
    "ModernTabList": {"Items": "=Table()", "DefaultSelectedItems": "=Table()", "SelectMultiple": "=false", "Height": "=60"},
    "ModernDatePicker": {"DefaultDate": "=Blank()", "Height": "=32", "Width": "=320", "Placeholder": '="Select a date"', "Format": "=DatePickerFormat.LongAbbreviated", "DateTimeZone": "=DateTimeZone.Local", "IsEditable": "=false", "StartDate": "=Date(1900,1,1)", "EndDate": "=Date(Year(Today())+100,12,31)", "StartOfWeek": "=StartOfWeek.Sunday", "ValidationState": "=ValidationState.None", "Appearance": "=Appearance.FilledDarker"},
    "Gallery": {"Items": "=Table()", "TemplateSize": "=100", "TemplatePadding": "=5", "Width": "=640", "Height": "=300",
        "TemplateFill": "=Color.Transparent", "Default": "=Blank()", "WrapCount": "=1", "Selectable": "=true", "ItemAccessibleLabel": '=""', "ShowScrollbar": "=true", "DelayItemLoading": "=false", "LoadingSpinner": "=LoadingSpinner.None", "BorderColor": "=RGBA(0,18,107,1)", "LoadingSpinnerColor": "=Self.BorderColor"},
    "Form": {"DefaultMode": "=FormMode.Edit", "Item": "=Blank()", "NumberOfColumns": "=1", "Width": "=800", "Height": "=500"},
    "TypedDataCard": { "WidthFit": "=false", "Default": "=Blank()", "Required": "=false", "DataField": '=""', "Update": "=Self.Default", "Height": "=70"},
    "Rectangle": {"Fill": "=RGBA(15,108,189,1)"},
    "Image": {"Image": '=""', "ImagePosition": "=ImagePosition.Fit"},
}

DEFAULTS.update({f:display_defaults(f) for f in DISPLAY_VERSIONS})
DEFAULTS.update({f:dict(next(iter(v.values()))['defaults']) for f,v in canvas_text_catalog().items()})
from .modern_link import DEFAULTS as LINK_DEFAULTS
DEFAULTS['ModernLink'] = dict(LINK_DEFAULTS)

from .rich_text import DEFAULTS as RICH_DEFAULTS
DEFAULTS["RichTextEditor"] = dict(RICH_DEFAULTS)

from .timers import DEFAULTS as TIMER_DEFAULTS
DEFAULTS["Timer"] = dict(TIMER_DEFAULTS)
from .media_controls import DEFAULTS as MEDIA_DEFAULTS
DEFAULTS['Audio'] = dict(MEDIA_DEFAULTS)
DEFAULTS['Video'] = {**MEDIA_DEFAULTS, 'Height':'=180', 'ClosedCaptionsUrl':'=""'}

from .html_controls import DEFAULTS as HTML_DEFAULTS
DEFAULTS["HtmlViewer"] = dict(HTML_DEFAULTS)

from .classic_inputs import catalog as classic_input_catalog
DEFAULTS.update({family:dict(spec['defaults']) for family,spec in classic_input_catalog().items()})
from .classic_combobox import catalog as classic_combo_catalog
DEFAULTS['Classic/ComboBox']=dict(classic_combo_catalog()['defaults'])
from .listbox import catalog as listbox_catalog,LISTBOXES
DEFAULTS.update({family:dict(listbox_catalog()['defaults']) for family in LISTBOXES})
from .data_table import DEFAULTS as DATA_TABLE_DEFAULTS
DEFAULTS.update(DATA_TABLE_DEFAULTS)
from .modern_grid import DEFAULTS as GRID_DEFAULTS
DEFAULTS.update(GRID_DEFAULTS)
from .rating import DEFAULTS as RATING_DEFAULTS
DEFAULTS["ModernRating"]=dict(RATING_DEFAULTS)
from .fluent_rating import DEFAULTS as FLUENT_RATING_DEFAULTS
DEFAULTS['FluentV8/Rating']=dict(FLUENT_RATING_DEFAULTS)
from .modern_button import DEFAULTS as BUTTON_DEFAULTS
DEFAULTS['ModernButton'].update(BUTTON_DEFAULTS)
from .classic_button import DEFAULTS as CLASSIC_BUTTON_DEFAULTS
DEFAULTS['Classic/Button']=dict(CLASSIC_BUTTON_DEFAULTS)
from .tablist import DEFAULTS as TAB_DEFAULTS
DEFAULTS['ModernTabList']=dict(TAB_DEFAULTS)
from .status_controls import DEFAULTS as STATUS_DEFAULTS
DEFAULTS.update(STATUS_DEFAULTS)
from .toolbar import DEFAULTS as TOOLBAR_DEFAULTS
DEFAULTS['Toolbar']=dict(TOOLBAR_DEFAULTS)
from .canvas_inputs import catalog as canvas_input_catalog
DEFAULTS.update({f:dict(next(iter(v.values()))['defaults']) for f,v in canvas_input_catalog().items()})
from .canvas_selectors import catalog as canvas_selector_catalog
DEFAULTS.update({f:dict(next(iter(v.values()))["defaults"]) for f,v in canvas_selector_catalog().items()})
from .canvas_dates import catalog as canvas_date_catalog
DEFAULTS['DatePicker'] = dict(next(iter(canvas_date_catalog().values()))['defaults'])
from .canvas_buttons import catalog as canvas_button_catalog
DEFAULTS['Button'] = dict(next(iter(canvas_button_catalog().values()))['defaults'])
from .canvas_tabs import catalog as canvas_tab_catalog
DEFAULTS['TabList'] = dict(next(iter(canvas_tab_catalog().values()))['defaults'])
from .canvas_scalars import catalog as canvas_scalar_catalog
DEFAULTS.update({f:dict(next(iter(v.values()))['defaults']) for f,v in canvas_scalar_catalog().items()})
SINGLE_SELECT = frozenset(('ModernDropdown', 'ModernRadio','Classic/DropDown','Classic/Radio'))


def contract_errors(control):
    if control.family in ('Text', 'FluentV8/Label'):
        from .canvas_text import errors
        return errors(control)
    if control.family == "Button":
        from .canvas_buttons import errors
        return errors(control)
    if control.family == "TabList":
        from .canvas_tabs import errors
        return errors(control)
    if control.family in ('Slider','Toggle'):
        from .canvas_scalars import errors
        return errors(control)
    if control.family == 'DatePicker':
        from .canvas_dates import errors
        return errors(control)
    if control.family in ("ComboBox","DropDown","Radio","ComboBoxDataField"):
        from .canvas_selectors import errors
        return errors(control)
    if control.family in ("TextInput", "CheckBox"):
        from .canvas_inputs import errors
        return errors(control)
    if control.family=='Toolbar':
        from .toolbar import errors
        return errors(control)
    if control.family == 'FluentV8/Rating':
        from .fluent_rating import errors
        return errors(control)
    if control.family == 'ModernLink':
        from .modern_link import errors
        return errors(control)
    if control.family in DISPLAY_VERSIONS:
        from .classic_display import errors
        return errors(control)
    """Known unsupported contracts remain visible even on hidden controls."""
    props, family = control.properties, control.family
    errors = {}
    if family=='Classic/Button':
        from .classic_button import errors as button_errors
        errors.update(button_errors(control))
    if family in ('Audio','Video'):
        from .media_controls import OUTPUTS
        for name in OUTPUTS | {'OnStart','OnChange','Volume','PlaybackRate'}:
            if name in props:errors[name]=f'{family}.{name} is an output or unsupported property'
        if family=='Audio' and 'ClosedCaptionsUrl' in props:
            errors['ClosedCaptionsUrl']='ClosedCaptionsUrl belongs to Video'
    if family in ("ModernBadge", "ModernInformationButton"):
        from .status_controls import REMOVED
        unsupported=set(REMOVED)|{'OnChange','OnInput','Reset','Text','IconStyle','IconRotation','Rotation'}
        if family=='ModernInformationButton':unsupported.update({'Icon','IconPosition','Intent','Appearance','Shape'})
        for name in sorted(unsupported):
            if name in props:errors[name]=f"{family}@1.0.0 does not support {name}; use its current property contract"
    if family == 'ModernTabList':
        for name in ('Selected','SelectedItems','DefaultSelectedItems','SelectMultiple','OnInput','OnSearch'):
            if name in props:errors[name]=f'ModernTabList.{name} is unsupported or an output; author Default and OnSelect/OnChange'
        if control.version=='1.0.0' and 'TabSize' in props:
            errors['TabSize']='TabSize belongs to Tab List 1.0.2'
    if family == "ModernRating":
        for name in ("Value","OnSelect","OnInput","Reset","Min","Required","AcceptsFocus","TabIndex","IconStyle"):
            if name in props:errors[name]=f"ModernRating.{name} is unsupported or an output; author Default and OnChange"
    if family == "ModernDataGrid":
        for name in ('Selected','SelectedItems','SearchText','OnSelect','OnInput','OnSearch','OnSort','RowHeight','SearchHintText','Fields','Columns','Reset'):
            if name in props:errors[name]=f'ModernDataGrid.{name} is unsupported or an output; selection uses OnChange'
    if family == "ModernDataGridColumn":
        if not control.parent or control.parent.family!='ModernDataGrid':errors['Placement']='ModernDataGridColumn must belong to ModernDataGrid'
        if control.raw.get('Variant','Textual')!='Textual':errors['Variant']='Only the documented Textual column variant is verified; this variant is unsupported'
        for name in ('Color','Size','Font','FontWeight','OnSelect','OnChange','Image','Icon','RowHeight','Wrap'):
            if name in props:errors[name]=f'ModernDataGridColumn.{name} is unsupported for the documented Textual variant'
    if family == "DataTable":
        for name in ("Selected","SelectedItems","Default","OnChange","OnSelect","Reset","RowHeight","SelectMultiple","SearchText","EnableSorting"):
            if name in props:errors[name]=f"DataTable does not support authored {name}; selection is an output and cells are read-only"
        ancestor=control.parent
        while ancestor:
            if ancestor.family in ("Gallery","Form","CanvasComponent","Component") or ancestor.family=="GroupContainer" and ancestor.raw.get("Variant")=="AutoLayout":
                errors["Placement"]=f"Power Apps does not support DataTable inside {ancestor.family}"
                break
            ancestor=ancestor.parent
    if family == "DataTableColumn":
        for name in ("Color","Fill","Font","FontWeight","Size","Height","OnChange","Reset"):
            if name in props:errors[name]=f"DataTableColumn.{name} is unsupported; style the parent table"
    if family == "DataTableColumn" and (not control.parent or control.parent.family!="DataTable"):
        errors["Placement"]="DataTableColumn must be a direct child of DataTable"
    if family == "Timer":
        for name in ("Value","Running","OnChange","OnInput","AcceptsFocus"):
            if name in props:errors[name]=f"Timer.{name} is unsupported; Value is an output and Start controls playback"
    if family == "RichTextEditor":
        for name in ("HtmlText", "Text", "OnInput", "OnSelect", "DelayOutput", "TriggerOutput", "ReadOnly", "AutoHeight", "MaxLength", "Font", "AcceptsFocus"):
            if name in props:errors[name]=f"RichTextEditor.{name} is unsupported; author Default and OnChange; HtmlText is an output"
    if family == "HtmlViewer":
        for name in ("TabIndex", "AcceptsFocus", "OnChange", "OnInput", "Reset", "Text"):
            if name in props:errors[name]=f"HtmlViewer does not support {name}; author HtmlText and OnSelect"
    if family in ('Classic/Toggle','Classic/Slider','Classic/DatePicker'):
        output='SelectedDate' if family=='Classic/DatePicker' else 'Value'
        unsupported={'AcceptsFocus','Required','ValidationState','BasePaletteColor',output}
        unsupported.update({'Checked','Label'} if family=='Classic/Toggle' else {'Step','LayoutDirection','OnInput'} if family=='Classic/Slider' else {'StartDate','EndDate','Placeholder','HideCalendar','CalendarCellHeight','CalendarWidth','CalendarDateFontSize','DateFontSize','CurrentDateFill','WeekColor','DayColor','CalendarPlaceholderWidth'})
        for name in unsupported:
            if name in props:errors[name]=f'{family}.{name} is unsupported; use its classic property contract'
    if family=='Classic/CheckBox':
        for name in ('Value','Checked','Label','OnChange','Required','ValidationState','AcceptsFocus','BasePaletteColor'):
            if name in props:errors[name]=f'Classic/CheckBox.{name} is unsupported; author Default, Text, OnCheck or OnUncheck'
    if family=='Classic/Radio':
        for name in ('SelectedText','ItemDisplayText','SelectMultiple','IsSearchable','AcceptsFocus','Required','ValidationState','BasePaletteColor','AllowEmptySelection'):
            if name in props:errors[name]=f'Classic/Radio does not support authored {name}'
    if family=='Classic/TextInput':
        for name in ('Text','TriggerOutput','Type','Placeholder','OnInput','Required','ValidationState','AcceptsFocus'):
            if name in props:errors[name]=f'Classic/TextInput@2.3.2 does not support authored {name}; use its classic property contract'
    if family=='Classic/DropDown':
        for name in ('SelectedText','ItemDisplayText','SelectMultiple','IsSearchable','AcceptsFocus','Required','ValidationState'):
            if name in props:errors[name]=f'Classic/DropDown@2.3.1 does not support authored {name}'
    if family == 'ModernTextInput' and control.version == '1.0.0' and 'Text' in props:
        errors['Text'] = 'ModernTextInput.Text is an output; author Default'
    if family == 'ModernTextInput' and 'OnInput' in props:
        errors['OnInput'] = 'ModernTextInput has no OnInput property; use OnChange'
    if family in ('ModernNumberInput','ModernDatePicker'):
        output = 'Value' if family == 'ModernNumberInput' else 'SelectedDate'
        if control.version == '1.0.0' and output in props:
            errors[output] = f'{family}.{output} is an output; author its default'
        if family == 'ModernNumberInput' and 'TriggerOutput' in props:
            errors['TriggerOutput'] = 'Number input TriggerOutput is not implemented; OnChange runs on blur/step'
        if family == 'ModernDatePicker' and control.version == '1.0.0' and 'Required' in props:
            errors['Required'] = 'Date picker Required was removed; use ValidationState and card validation'
    if family in ('ModernCombobox','Classic/ComboBox'):
        for name in ('SearchText', 'Selected', 'SelectedItems'):
            if name in props:
                errors[name] = f'{family}.{name} is an output'
    if family=='Classic/ComboBox':
        for name in ('ItemDisplayText','DelayOutput','TriggerOutput','Required','ValidationState','Appearance','BasePaletteColor','AcceptsFocus','SelectedText','Layout'):
            if name in props:errors[name]=f'Classic/ComboBox does not support {name}; author DisplayFields, SearchFields and Template'
        if 'NavigateItem' in props:errors['NavigateItem']='Classic/ComboBox.NavigateItem is an output'
    if family in LISTBOXES:
        for name in ('Selected','SelectedItems','SelectedText','SelectedItemsText'):
            if name in props:errors[name]=f'{family}.{name} is an output'
        for name in ('DefaultSelectedItems','ItemDisplayText','DisplayFields','SearchFields','IsSearchable','Required','ValidationState','Appearance','AcceptsFocus'):
            if name in props:errors[name]=f'{family} does not support {name}; author Default and Value'
    if family in SINGLE_SELECT:
        if 'Selected' in props:
            errors['Selected'] = f'{family}.Selected is an output; author Default'
        for name in ('DefaultSelectedItems', 'SelectedItems', 'TriggerOutput'):
            if name in props:
                errors[name] = f'{family}.{name} is not implemented for this control version'
    if family == 'ModernIcon' and control.version == '1.1.0':
        for name in ('Style','TabIndex','AcceptsFocus'):
            if name in props:errors[name]=f'ModernIcon@1.1.0 does not support {name}; focus follows OnSelect and Style was renamed IconStyle'
    if family == 'Classic/Icon':
        for name in ('IconStyle','IconColor','AcceptsFocus','BasePaletteColor','Style'):
            if name in props:errors[name]=f'Classic/Icon@2.5.0 does not support {name}'
    if family == 'ModernSpinner'  and str(props.get('OnChange', '=Blank()')).strip() not in ('=Blank()', ''):
        errors['OnChange'] = 'Spinner property-change OnChange timing is not implemented'
    return errors


RESETTABLE = frozenset(('TabList','Slider','DatePicker','ComboBox','DropDown','Radio','TextInput','CheckBox','Toolbar',"ModernRating",'FluentV8/Rating','ModernDataGrid',*LISTBOXES,'Classic/ComboBox','Timer','Audio','Video','RichTextEditor','Classic/Toggle','Classic/Slider','Classic/DatePicker','Classic/CheckBox','Classic/Radio','Classic/TextInput','Classic/DropDown','ModernDropdown', 'ModernRadio', 'ModernCheckbox', 'ModernSlider', 'ModernTextInput', 'ModernNumberInput', 'ModernDatePicker',
    'ModernCombobox', 'ModernTabList', 'Toggle', 'Gallery'))
for _family in RESETTABLE:
    DEFAULTS[_family]['Reset'] = '=false'
for _family in ('ModernButton', 'Classic/Button'):
    DEFAULTS[_family]['Pressed'] = '=false'

# Only presentation properties are evaluated for drawing. Others remain inspectable.
RENDER_PROPERTIES = "AcceptsFocus TabIndex X Y Width Height Visible DisplayMode Fill Color Font FontColor FontWeight FontSize Size Align VerticalAlign Wrap AutoHeight HtmlText Text Label Icon IconStyle IconColor Rotation Layout Appearance BasePaletteColor LayoutDirection LayoutAlignItems LayoutJustifyContent LayoutGap LayoutOverflowX LayoutOverflowY LayoutWrap LayoutMinWidth LayoutMinHeight LayoutMaxWidth LayoutMaxHeight FillPortions AlignInContainer PaddingTop PaddingBottom PaddingLeft PaddingRight BorderThickness BorderColor BorderStyle RadiusTopLeft RadiusTopRight RadiusBottomLeft RadiusBottomRight AccessibleLabel Tooltip InputTextPlaceholder Placeholder HintText Format DateTimeZone IsEditable StartDate EndDate StartOfWeek Mode Type MaxLength Min Max Step Precision DelayItemLoading LoadingSpinner LoadingSpinnerColor Selectable ShowScrollbar TemplateSize TemplatePadding WrapCount Image ImagePosition IsSearchable SelectMultiple DelayOutput TriggerOutput MultiValueDelimiter Required ValidationState Indeterminate ProgressColor Thickness Shape LabelPosition LineHeight RadioSize Italic Underline Strikethrough ContentLanguage WidthFit".split()


def responsive_default(control, name):
    """Responsive child defaults from Microsoft's DynamicProperties contract.

    Only the supported versions use these defaults. Explicit source wins.
    The minimum of a leaf is its template default, not its Width/Height formula.
    """
    if control.version not in SUPPORTED.get(control.family, set()):
        return None
    if name == 'AcceptsFocus' and control.family.startswith('Modern'):
        from .focus import INTERACTIVE
        value = control.family in INTERACTIVE and (control.family != 'ModernText' or 'OnSelect' in control.properties)
        return '=true' if value else '=false'
    if name == 'TabIndex' and control.family in ('Classic/Button', 'Label', 'Image', 'Toggle'):
        return '=0' if control.family in ('Classic/Button', 'Toggle') or 'OnSelect' in control.properties else '=-1'
    nested = control.family in {"GroupContainer", "Gallery", "Form", "TypedDataCard"}
    if name == "FillPortions":
        return "=1" if nested else "=0"
    if name == "AlignInContainer":
        return "=AlignInContainer.Stretch" if nested else "=AlignInContainer.SetByContainer"
    if name in ("LayoutMinWidth", "LayoutMinHeight"):
        return "=32" if nested else DEFAULTS.get(control.family, {}).get(name[9:], COMMON[name[9:]])
    return None

# Browser layout and native number inputs use Float pixels/values in either host.
NUMERIC_CONTROL_PROPERTIES = set("X Y Width Height Rotation TemplateWidth TemplateHeight TemplateSize TemplatePadding WrapCount Size FontSize LayoutGap LayoutMinWidth LayoutMinHeight LayoutMaxWidth LayoutMaxHeight FillPortions PaddingTop PaddingBottom PaddingLeft PaddingRight PaddingStart PaddingEnd BorderThickness RadiusTopLeft RadiusTopRight RadiusBottomLeft RadiusBottomRight NumberOfColumns MaxLength Min Max Step".split())


INSPECT_OUTPUTS = {
    "TabList": ("Selected", "SelectedItems"),
    "Radio":("Selected","SelectedItems"),
    "ComboBox":("Selected","SelectedItems","SearchText"),"DropDown":("Selected","SelectedItems"),
    'Slider':('Value',),'TextInput':('Value',),'CheckBox':('Checked',),
    'Classic/Toggle':('Value',),'Classic/Slider':('Value',),'Classic/DatePicker':('SelectedDate',),
    'Classic/CheckBox':('Value',),'Classic/Radio':('Selected','SelectedText'),
    'Classic/TextInput':('Text',),'Classic/DropDown':('Selected','SelectedText'),
    'ModernTextInput': ('Text',), 'ModernNumberInput': ('Value',),
    'Toolbar': ('Selected','SelectedItems'), 'FluentV8/Rating': ('Value',), 'ModernRating': ('Value',), 'ModernDatePicker': ('SelectedDate',), 'ModernSlider': ('Value',),
    'Toggle': ('Checked',), 'ModernCheckbox': ('Checked',),
    'ModernCombobox': ('Selected', 'SelectedItems', 'SearchText'),
    'ModernTabList': ('Selected',),
    'ModernDropdown': ('Selected',), 'ModernRadio': ('Selected',),
    'ModernButton': ('Pressed',), 'Classic/Button': ('Pressed',),
    'DataTable': ('Selected',),
    'ModernDataGrid': ('Selected','SelectedItems','SearchText'),
    'Gallery': ('Selected', 'AllItems', 'AllItemsCount', 'TemplateWidth', 'TemplateHeight'),
    'Form': ('Mode', 'Item', 'Updates', 'Unsaved', 'Valid', 'LastSubmit', 'Error', 'ErrorKind'),
}


def inspect_properties(ref):
    """Authored properties and public outputs; runtime bookkeeping is separate."""
    keys = set(ref.control.properties) | set(INSPECT_OUTPUTS.get(ref.family, ()))
    keys.update(key for key in ref.state if key[:1].isupper())
    if ref.family == 'CanvasComponent':
        from .components import component_definition,validate_kind
        definition = component_definition(ref.runtime.project, ref.control)
        if definition:
            keys.update(name for name, spec in definition.raw.get('CustomProperties', {}).items()
                        if validate_kind(spec) in ('Input', 'Output'))
    return keys

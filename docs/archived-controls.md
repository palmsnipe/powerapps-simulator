# Archived canvas control contracts

[Documentation index](README.md) · [Project README](../README.md)

Contracts recovered from pinned Microsoft sample archives. Metadata establishes names, types and defaults; it does not establish native timing or pixel-perfect rendering.

## Native TextInput and CheckBox versions

The simulator now has separate native contracts for `TextInput@0.0.51`, `TextInput@0.0.53`, and `CheckBox@0.0.26`, `0.0.27`, `0.0.30`. They retain their source names and versions. These controls use different bound properties from the existing ModernTextInput and ModernCheckbox contracts.

| Native control | Bound input/output | Behavior events | Recovered defaults |
| --- | --- | --- | --- |
| TextInput 0.0.51 / 0.0.53 | Value (Text) | OnChange | Width 320, Height 32, MaxLength -1, TriggerOutput FocusOut, Mode SingleLine, Type Text |
| CheckBox 0.0.26 / 0.0.27 / 0.0.30 | Checked (Boolean) | OnCheck, OnUncheck, OnSelect | Width 160, Height 32, CheckboxSize 16, Label Checkbox, Checked false |

The metadata comes from Microsoft's pinned [modern input-controls solution](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mdainputcontrols/MDA_InputControls_Solution_1_0_0_4.zip), [classic input-controls solution](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mdaclassicinputcontrols/MDA_ClassicControls_Solution_1_0_0_3.zip), and [Language Tooling app](https://github.com/microsoft/PowerApps-Language-Tooling/blob/630e6973e5c81ddc196283cde26dd696d619d6c7/src/Persistence.Tests/_TestData/AlmApps/AlmTestApp-asManyEntitiesAsPossible.msapp). Bundled `static/canvas-inputs.json` preserves 137 native property descriptors, 11 event descriptors, subscribed functionality flags, archive checksums and explicit simulator defaults. CheckBox's OnCheck/OnUncheck descriptors live in Events, while OnSelect lives in CommonEvents; both sections are retained. All three public archives import their Windows source paths and retain these native control names. The archived 0.0.26 checkbox's authored OnCheck is supported.

TextInput's Value is a resettable bound property. Browser drafts survive ordinary preview updates. FocusOut commits on blur, Keypress commits on input, and Delayed commits after a local 500 ms debounce or blur. Python updates Value before OnChange, and a repeated unchanged blur does not invoke it again. Blank Value remains Blank until a meaningful edit. MaxLength -1 is unlimited; the simulator enforces nonnegative limits, including zero, using UTF-16 code units. Changing the input contract or bound default invalidates pending drafts. Password, search and multiline rendering are supported; multiline password rendering is explicitly unsupported. Native timing, coercion, blank/range behavior and the zero-length rule still require comparison in Studio.

CheckBox commits Checked before its state callback and OnSelect. The local event sequence is OnCheck or OnUncheck when the value changes, followed by OnSelect. Repeated selection invokes OnSelect; programmatic Select invokes OnSelect without toggling. Reset and bound-default changes do not emit state callbacks. Blank Checked displays as false. These are simulator interaction rules; native event ordering and Blank behavior have not been recorded. Each component or gallery row retains its own values, history and reset token. Disabled/view/hidden ancestors block browser edits; stale events cannot overwrite a reset or newly bound default.

Native font, color, appearance, alignment, border and padding fields are evaluated from the recovered contracts; rendering is approximate. TextInput 0.0.51 declares Align enum values, while 0.0.53 declares Align as Text without that enum restriction. Style fields such as FontColor are native Text properties. Unknown versions and properties remain visible diagnostics. Hidden PCFTeamsTheme is retained but unsupported. Reset(control) is supported separately from an authored Reset property. TextInput does not acquire Default, Text, OnSelect or DelayOutput aliases. CheckBox does not acquire Default, Value or OnChange aliases.

The native metadata advertises reset/focus capabilities. SetFocus for a standalone TextInput follows the simulator's existing screen and container restrictions and [Microsoft's SetFocus reference](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-setfocus). CheckBox SetFocus remains explicitly unsupported: its native flag and the published target list need a native runtime comparison. Keyboard Tab focus is available for both controls.

```sh
python -m powerapps_sim.fixtures projects/canvas-inputs --kind canvas-inputs
python -m powerapps_sim --import projects/canvas-inputs
```

The fictional fixture keeps screen YAML, component YAML, SQLite schemas/records and a 24-step workflow separate. It exercises both text versions and all three checkbox versions, two isolated component instances, typed text/Boolean callbacks, independent histories, English/French labels, reactive defaults, reset, focus, delayed output, gallery record writes and form editing/submission. Notes use mapped Title/Approved fields. Failed saves retain editable drafts; clearing the injected failure allows saving. Workflows run on copies and preserve the open owner's source, records and runtime. MCP staging can change both source documents and a list schema, run the candidate workflow, apply it and undo it.

Next compatibility work should recover the native ComboBox/DropDown contracts and their row/selection shapes, then compare component lifecycle and event ordering against recorded native runs. Studio clipboard acceptance, native themes/geometry/timing, broader control versions, live SharePoint/authentication and Windows execution remain open. The existing MCP server exposes local project/source/list/workflow tools; registering it with a chosen AI host remains a separate setup step.

## Archived canvas ComboBox and DropDown selectors

The simulator recognizes `ComboBox@0.0.48`, `ComboBox@0.0.49`,
`DropDown@0.0.44`, and the observed `ComboBoxDataField@1.5.0` metadata
children. These families have their own contracts in
`powerapps_sim/static/canvas-selectors.json` and `canvas_selectors.py`.
They preserve the archived `DefaultSelectedItems`, `TriggerOutput`, and
field-child source syntax. The two ComboBox versions default to **single**
selection. `Selected` is a record, `SelectedItems` is a table, and
`SearchText` is a ComboBox output. Only `OnChange` is an authored event.
Newer names such as `ItemDisplayText`, `Default`, `DelayOutput`, and
`OnSelect` are reported as unsupported instead of being substituted.

The archived descriptors come from checksum-verified, pinned first-party
[TestEngine input controls](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mdainputcontrols/MDA_InputControls_Solution_1_0_0_4.zip)
and [classic input controls](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mdaclassicinputcontrols/MDA_ClassicControls_Solution_1_0_0_3.zip).
All 108 property descriptors, three event descriptors, and subscribed flags
are retained. The field-child template identity and snapshot rules are
preserved; its complete property descriptors and native defaults were **not**
recovered. Its inferred scalar types and omitted-property defaults are local
models. The observed `textualColumn` variant and `s`, `l`, and `d` field type
codes are accepted; other variants/codes remain visible as unsupported.

The browser sends indexed selections and instance tokens to Python. Python
validates record/table shapes and configured display fields, commits selection,
and then runs `OnChange`. Duplicate rows retain separate addresses. Invalid
rows remain disabled with diagnostics while valid rows and other controls work.
Display fields resolve SharePoint internal/display names through Power Fx.
A native sample's mismatched field names remain errors after import; source is
never repaired silently. Component instances have independent selected records,
search text, reset tokens, and histories. Gallery and form selectors preserve
Choice records and tables of Choice records in SQLite. Failed saves keep the
draft; reset and default changes do not invoke change callbacks.

Interaction details are explicit **local approximations**, pending a native
runtime comparison: selection order determines `Selected`; search is casefolded
across configured text fields; `Keypress` commits search immediately, `Delayed`
uses 500 ms, and `FocusOut` commits on blur. Search does not invoke `OnChange`.
Selected records survive filtered `Items` and can be removed through their chips.
Reset restores matching defaults and clears search. Blank defaults give an empty
selection; unmatched defaults are ignored locally. Partial defaults match item
identity. The archive's empty DisplayMode descriptor is resolved to Edit locally.
Styling, padding, themes, and popup geometry are approximate. DropDown uses a
native desktop HTML select; retained selections outside current Items are shown
as a disabled retained option. `PCFTeamsTheme` and selector `SetFocus` remain
unsupported. Although archived subscription flags advertise SetFocus, the
[published SetFocus targets](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-setfocus)
do not include these families. Tab and native keyboard selection work.

Microsoft's current [Combo box](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-combobox)
and [Drop down](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-dropdown)
upgrade notes describe renamed properties and changed defaults. They are useful
version context, not evidence that the archived controls use the newer behavior.
Studio paste acceptance, exact event ordering/timing, field formatting/coercion,
and Windows execution still require manual/native comparisons.

Create a disposable linked component/form fixture:

```sh
python -m powerapps_sim.fixtures projects/canvas-selectors --kind canvas-selectors
python -m powerapps_sim --import projects/canvas-selectors --port 8853
```

The fixture includes both ComboBox versions, DropDown, ordered field children,
English/French labels, responsive independent component instances, a gallery
write, Choice/multiple-Choice form cards, and a 26-step isolated workflow. Its
source, list definitions, and workflow are shipped in `powerapps_sim/examples`.
The original private sample and its live servers are not modified by this demo.

## Archived canvas date pickers

`DatePicker@0.0.38` and `DatePicker@0.0.42` use their archived
`DatePickerCanvas` contracts. The two versions retain all **76 property
and two event descriptors**, enum names/backing values, and subscribed flags
from the pinned first-party [TestEngine input controls](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mdainputcontrols/MDA_InputControls_Solution_1_0_0_4.zip)
and [classic input controls](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mdaclassicinputcontrols/MDA_ClassicControls_Solution_1_0_0_3.zip).
Both archives import with their original Windows-style paths and render the
native date picker; other unsupported controls remain visible as diagnostics.

Author `SelectedDate` as the initial/resettable binding. User changes publish a
Date value and invoke `OnChange`; Reset or a changed binding restores the value
without invoking that callback. `DefaultDate` belongs to other versions and is
unsupported here. `DatePickerCanvas.Format.LongAbbreviated`, `.Short` and
`.YearMonth` resolve to the descriptor backing strings; StartOfWeek uses
`DatePickerCanvas.StartOfWeek.Monday` and the other named weekdays. The global
numeric `StartOfWeek` enum is a different contract. Environment language controls
formatting and typed-date parsing. Authored Language/ContentLanguage,
TriggerOutput/DelayOutput, OnSelect, Reset, variants, and unknown versions are
preserved with explicit diagnostics.

Python validates structured date/calendar events, ranges, visibility and edit
mode. Instance tokens reject events for another control or an outdated binding,
reset or restart. Components own independent dates and local callback histories;
DateAndTime callback parameters retain the existing typed component contract.
Form cards expose typed Updates, Required, Unsaved and reset behavior; failed
SQLite writes retain the draft for a retry. The browser shares the local calendar
renderer, including keyboard navigation and an editable typed-date field.
Choosing a valid calendar date now clears a prior invalid text draft, and opening
the calendar with ArrowDown focuses the selected day when it is enabled.

Blank bounds use the simulator's Gregorian date range, and the empty native
DisplayMode descriptor uses Edit locally. DateTime bindings project to Date
using the existing simulated clock-offset model. These defaults, callback/reset
timing, date coercion and calendar/theme styling are **local models** pending
recorded native comparison. `PCFTeamsTheme` and `SetFocus` remain unsupported.
Current [modern date picker documentation](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-date-picker)
describes newer contracts; its renamed properties do not redefine these archived
versions. Studio paste acceptance and physical Windows execution remain open.

Create a disposable fictional component/form fixture:

```sh
python -m powerapps_sim.fixtures projects/canvas-dates --kind canvas-dates
python -m powerapps_sim --import projects/canvas-dates --port 8855
```

The fixture contains both versions, two independent bilingual component
instances, a read-only month view, a required mapped date form, and a repeatable
24-step save/failure/retry workflow. The scenario supplies its own initial records
on an isolated copy, preserving the open app's edited data and runtime. Source,
list definitions and workflow remain separate files. The private sample and its
live servers are unaffected.

## Archived canvas radio controls

`Radio@0.0.23` and `Radio@0.0.24` retain their `RadioGroupCanvas` contracts,
including all **50 property and two event descriptors** from the pinned
first-party [TestEngine input controls](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mdainputcontrols/MDA_InputControls_Solution_1_0_0_4.zip)
and [classic input controls](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mdaclassicinputcontrols/MDA_ClassicControls_Solution_1_0_0_3.zip).
Both archives import their original Windows-style source paths and render their
radio options, including the older sample's three-column records.

Author a table in `DefaultSelectedItems`; `Selected` returns the full chosen
record and `SelectedItems` returns an empty or single-row table. User selection
commits in Python before `OnChange` runs. Repeated selections do not repeat the
callback; Reset and changed defaults restore selection without invoking it.
The local model chooses the first matching default and retains a selection when
Items is filtered. Native matching, retention and callback timing still need
recorded comparison. `Default`, ItemDisplayText, SelectedText, SelectMultiple,
SearchText, OnSelect, TriggerOutput, ValidationState, authored Reset, variants,
and unknown versions remain preserved with explicit diagnostics.

The archived Layout enum includes Vertical, Horizontal and HorizontalStacked;
the last has the backing text **"Horizontal Stacked"**. The local Power Fx
namespace is `RadioGroupCanvas.Layout`. Horizontal Stacked places each option's
label below its indicator, following [Fluent 2 radio layout guidance](https://fluent2.microsoft.design/components/web/react/core/radiogroup/usage/).
Exact native geometry, styling and enum paste syntax remain unverified. Font,
FontSize, FontColor, FontWeight, decoration and RadioSize use the archived names.
Required is exposed to accessibility and the existing form-validation model.
`PCFTeamsTheme` and SetFocus remain unsupported.

No archived ItemDisplayText or field-child contract was recovered. The explicit
**local display-column model** prefers `Value`, then the first text field, then
the first scalar field in the first record. Python resolves that field through
Power Fx for every row. Missing/complex/error labels disable the affected option
and retain source-located diagnostics; healthy options and other controls remain
usable. Selecting an option preserves its complete record, including extra
columns. This inference supports the original multi-column sample without
claiming its native display behavior was measured.

Archived radio, ComboBox and DropDown event tokens now include the control
instance path. Identical instances cannot accept each other's selection/search
events. Stale tokens after reset, default/Items changes or restart are rejected.
Component callbacks, local histories, typed record/table outputs, mapped Choice
form updates and failed-save retry share the existing server-authoritative paths.
The browser renders accessible native HTML radios with keyboard navigation,
read-only/disabled states, scrolling and stable focus during updates.

Create a disposable bilingual component/form fixture:

```sh
python -m powerapps_sim.fixtures projects/canvas-radio --kind canvas-radio
python -m powerapps_sim --import projects/canvas-radio --port 8856
```

The fixture contains both versions, independent component instances, stacked and
vertical layouts, translated choices from configured list options, a required
mapped Choice form, and a repeatable 26-step save/failure/retry workflow. The
scenario owns its initial records on an isolated copy, preserving the open app's
edited data and runtime. Screen/component YAML, list definitions and workflow
remain separate. The private sample and its live servers are unaffected.

## Archived native Slider and Toggle controls

`Slider@1.0.29/@1.0.31` uses authored/bound **Value**, finite Min/Max,
Slider.Layout.Vertical/Horizontal and Slider.Size.Small/Medium. It has OnChange;
Default, Step, LayoutDirection, authored OnInput/OnSelect/Reset and ReadOnly are
unsupported for these archived versions. These differ from the newer documented
Slider: Microsoft lists [Value → Default and Layout → LayoutDirection renames](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-updates).

`Toggle@1.1.2/@1.1.4/@1.1.5` uses authored/bound **Checked**, Label,
Toggle.LabelPosition.Before/After/Above, ToggleSize and font/palette properties.
It has OnCheck, OnUncheck and OnSelect; Default, Value, OnChange and authored
Reset are unsupported. The 1.1.5 contract reuses the identical public 1.1.4
property/event/subscription descriptors, verified against private target metadata.
The catalog contains public descriptors only, with checksums and pinned
[older](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mdaclassicinputcontrols/MDA_ClassicControls_Solution_1_0_0_3.zip)
and [newer](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mdainputcontrols/MDA_InputControls_Solution_1_0_0_4.zip)
archive provenance in `static/canvas-scalars.json`. PCFTeamsTheme and SetFocus
remain unsupported; original source/unknown properties remain available.

The **local execution model** coerces Blank Checked to false and Blank Value
to Min; Slider clamps to a nonblank ordered range. During dragging, its current
output changes on internal browser OnInput transport events without running a
Power Fx callback. OnChange runs once per changed committed release value.
Toggle commits Checked, runs the matching check callback when changed, then
OnSelect; repeated same-value selections run OnSelect only. These event timing,
coercion and clamp rules were not measured in Studio. Archive metadata verifies
the property/event contracts, not native timing. Omitted DisplayMode uses Edit.

Reset(control), component resets, reactive binding changes and form lifecycle
use the shared runtime. Gallery/form reset boundaries still apply. The corrected
simulator-owned gallery example selects a visible row reset button through
AllItems so Reset executes inside the row scope. The original imported source
is unchanged. Tokens include instance path, restart/reset epoch, bound formula
value and relevant contract properties; stale/cross-instance events are ignored.
The browser uses native keyboard range inputs and accessible switches, including
vertical sliders and label positioning, preserving input elements during updates.

```sh
python -m powerapps_sim.fixtures projects/canvas-scalars --kind canvas-scalars
python -m powerapps_sim --import projects/canvas-scalars --port 8857
```

This bilingual fixture includes all five versions, two isolated component
instances with typed Number/Boolean callbacks and histories, a mapped local
number/Boolean form and a repeatable 29-step save/failure/retry workflow. Separate
screen/component YAML, list schemas and workflow files support combined MCP
source/schema candidates with validation, apply and undo. Styling is approximate;
actual Studio clipboard acceptance and Windows execution remain manual checks.

## Archived TabList controls

`TabList@2.2.29` is a distinct contract from `ModernTabList@1.0.0/@1.0.2`.
Its public property/event descriptors come from Microsoft's pinned
[TestEngine input-controls archive](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mdainputcontrols/MDA_InputControls_Solution_1_0_0_4.zip).
The catalog preserves all 24 descriptors, including unsupported PCFTeamsTheme,
two common events, the source URL and archive checksum. This version has no
recovered subscription flags; none are invented.

Author a **table** in DefaultSelectedItems. Selected returns a full record and
SelectedItems returns its zero/one-row table. Size uses TabList.Size.Small,
Medium or Large; Alignment uses TabList.Alignment.Horizontal or Vertical.
FontSize is separate from Size. Font, FontColor, FontWeight, FontItalic,
FontUnderline, FontStrikethrough, BasePaletteColor, TabIndex, AccessibleLabel
and Tooltip use the archived property names. Omitted Items contains the native
three-item table, with Width 280, Height 55, Size Large and horizontal orientation.
DisplayMode Edit, zero X/Y/TabIndex and an empty default table are local defaults.
Authored Selected/SelectedItems, Default, TabSize, ItemDisplayText, Appearance,
SelectMultiple, Reset and PCFTeamsTheme report Unsupported and remain in source.
The [newer tab documentation](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-tabs-or-tabs-list)
describes a different contract; its names are not substituted into archives.

The local selection model uses the first matching default, the first healthy
tab for empty/Blank defaults, and Blank for unmatched nonempty defaults. The
first-tab fallback agrees with Microsoft's
[2023 update](https://www.microsoft.com/en-us/power-platform/blog/2023/06/05/may-2023-updates-for-modernization-in-power-apps/);
unmatched/multiple-default behavior and exact reset timing remain unmeasured.
Native field binding was not recovered. Display labels use Value, then the first
text column, then the first scalar column. Unsupported complex labels and row
errors stay visible. ID/Id plus occurrence keys refresh records and distinguish
duplicate tabs; removing a selected row falls back to the current default.

Python commits selection before OnSelect and changed-only OnChange. Repeated
clicks run OnSelect; Reset and bound-default changes do not run these callbacks.
These callback-order/reset rules are local models awaiting native traces.
Instance/version/default/Items stamps reject stale or cross-instance events.
Form and gallery reset boundaries remain enforced. Tab buttons support arrow,
Home/End, Enter/Space, retained focus, read-only states, horizontal/vertical
orientation and overflow scrolling. Theme colors, geometry and native timing
remain approximate. SetFocus is unsupported for this archived control.

```sh
python -m powerapps_sim.fixtures projects/canvas-tabs --kind canvas-tabs
python -m powerapps_sim --import projects/canvas-tabs --port 8859
```

The bilingual fixture has separate screen/component YAML, mapped Choice-list
configuration and a 27-step isolated workflow. It exercises paired instances,
typed Record callbacks, scoped collections, resets, view gating, form validation,
failed-save retention and successful retry. Its responsive heading wraps at
400 pixels. Expand the preview height to 1000 to inspect the full stacked form;
the fixed screen viewport clips content beyond its configured height. The tab
headers themselves scroll horizontally. MCP uses the shared source/schema
candidate, validation, apply and undo services. Transport stamps and simulator
configuration are excluded from exported Power Apps source.

## Archived Button controls

`Button@0.0.43/@0.0.44` use contracts recovered from Microsoft's pinned
[TestEngine classic-controls archive](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mdaclassicinputcontrols/MDA_ClassicControls_Solution_1_0_0_3.zip)
and [input-controls archive](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mdainputcontrols/MDA_InputControls_Solution_1_0_0_4.zip).
Each version retains 39 descriptors, OnSelect, native enum values, subscription
flags and archive provenance. PCFTeamsTheme remains visible as Unsupported.

Use FontSize, FontColor, FontItalic/FontUnderline/FontStrikethrough, BorderRadius
and BorderRadiusTopLeft/TopRight/BottomLeft/BottomRight. Appearance uses
ButtonCanvas.Appearance.Primary/Secondary/Outline/Subtle/Transparent;
Layout uses ButtonCanvas.Layout.IconBefore/IconAfter/TextOnly/IconOnly.
Its backing values contain spaces (for example, "Icon before"). IconStyle uses
ButtonCanvas.IconStyle.Outline/Filled. These names and backing values survive
copy/export. [Newer modern Button documentation](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-button)
describes different names; Size, Color, Italic, RadiusTopLeft, Pressed and OnChange
are not accepted as aliases for these archived versions. Unknown properties
remain in source and produce located diagnostics.

Omitted Width/Height are 96/32, Text is "Button", AcceptsFocus is true, and
native numeric decoration defaults retain Blank. Automatic layout treats Blank
padding/borders as zero inset without changing public property values.
X/Y/TabIndex zero and DisplayMode.Edit are documented local overrides.
Fonts, palette rendering, default decoration and geometry remain approximate.

The recovered autoDisabledViewState flag guards reentrant OnSelect actions on
the server and temporarily disables the browser button during its request.
It is a subscription flag, not an authored AutoDisableOnSelect property.
The preview restores prior keyboard focus only if the button remains eligible
and no other control took focus. SetFocus follows the recovered support flag;
component, gallery, form and container boundaries still apply. AcceptsFocus and
TabIndex affect local focus eligibility. These execution/focus rules are local
models awaiting recorded native timing comparisons. Buttons have no resettable
output. Component Reset and RaiseOnReset still operate on instance state.

```sh
python -m powerapps_sim.fixtures projects/canvas-buttons --kind canvas-buttons
python -m powerapps_sim --import projects/canvas-buttons --port 8860
```

The bilingual fixture separates screen YAML, component YAML, list configuration
and a 31-step workflow. It covers paired counters, typed Number callbacks,
scoped histories, resets, view gating, SetFocus, gallery actions, mapped numeric
form editing and failed-save retry. At 400 pixels the components stack and the
appearance gallery wraps. Expand the preview height to 1100 to inspect the full
stacked form; the fixed screen viewport still clips content beyond its height.
AI authoring uses the existing shared candidate/validation/apply/undo services
and optional MCP transport. Simulator metadata is excluded from source exports.

## Archived Text and Fluent Label controls

`Text@0.0.47` and `FluentV8/Label@1.6.0` use contracts recovered from Microsoft's pinned
[TestEngine display-controls archive](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mdadisplaycontrols/MDA_DisplayControls_1_0_0_1_managed.zip).
The archive SHA-256 is `c51c4ad655332e4818125cd82c8257671d8b6ae717f7ed04daf0c43429a8196b`.
Text retains 34 property descriptors and Fluent Label retains 24, including unsupported
PCFTeamsTheme metadata. Unknown properties remain in source with located diagnostics.
[Current modern Text documentation](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-text)
describes a different contract; those names and events are not aliases for these versions.

Text uses Size in local pixels, Weight, Align, VerticalAlign, FontColor,
FontItalic/FontUnderline/FontStrikethrough, Fill, native borders/corner radii and
PaddingTop/Right/Bottom/Left. Use TextCanvas.Weight.Regular/Medium/Semibold/Bold,
TextCanvas.Align.Start/End/Center/Justify and TextCanvas.VerticalAlign.Top/Middle/Bottom.
It has no recovered OnSelect or OnChange event and remains static in galleries.

Fluent Label uses FontSize in points (converted locally by 4/3), FontWeight,
Color, Alignment, VerticalAlignment and PaddingTop/End/Bottom/Start.
Its plain text alignment and weight properties accept the recovered lowercase defaults
and the archived Align/VerticalAlign/FontWeight enum results without rewriting source.
TextRole.Default/Heading1/Heading2/Heading3/Heading4 sets heading semantics;
Overflow.Hidden/Scroll controls local clipping and scrolling. Fluent labels support
OnSelect, including gallery selection and isolated typed component callbacks.
The hidden OnChange descriptor remains unverified and is rejected as an authored event.
Neither family has a recovered SetFocus subscription or resettable output; SetFocus
and Reset calls fail visibly instead of manufacturing support.

The recovered Fluent autoDisabledViewState subscription guards reentrant server
selection and temporarily gates browser actions. It is metadata, not an authored
property. Local TabIndex eligibility, Enter/Space selection, focus retention and
logical padding use browser behavior. AutoHeight estimates wrapped text using local
font metrics and retains the last visible height while a control or ancestor is
hidden. Overflow.Scroll uses a stable inner element so updates preserve scroll state.
These sizing, focus and event timing models await recorded native comparisons;
font measurement, theme and geometry remain approximate.

```sh
python -m powerapps_sim.fixtures projects/canvas-text --kind canvas-text
python -m powerapps_sim --import projects/canvas-text --port 8861
```

The bilingual fixture separates screen YAML, component YAML, list configuration
and a 41-step workflow. It covers two counters, typed Number callbacks, scoped
histories, resets, read-only gating, heading roles, hidden-height changes, scrolling,
mapped numeric form editing and failed-save retry. Caption AutoHeight feeds the
component's derived layout, including longer French labels. At 400 pixels the
components and form stack; use preview height 1300 to inspect the full content.
The fixed screen viewport clips content beyond its configured height.
AI edits use the shared source/schema candidate, validation, apply and undo services
and optional MCP transport. Copy/export preserves native source and excludes simulator
configuration. Next compatibility work is archived Link/Progress/Spinner/Badge
contracts and recorded native component/default/reset/event comparisons.

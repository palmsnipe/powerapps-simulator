# Compatibility and limitations

[Documentation index](README.md) · [Project README](../README.md)

Supported behaviour is a local subset of Power Apps. Use the selected conformance report and the fictional fixtures to assess a specific app.

## Compatibility

The compatibility target is Power Apps canvas-app behaviour: Power Fx formulas, controls, reusable components, and local SharePoint-shaped data. Public fictional examples and selected upstream conformance cases exercise the supported subset. Private imports, connector metadata, draft source, and databases live under the ignored `projects/` directory.

The Python interpreter uses a tokenizer, AST parser, scoped evaluator, and lexical type binder. It does not evaluate source as Python or JavaScript. It supports the sample's genuine built-in functions, comma arguments/semicolon behavior chains, quoted and disambiguated identifiers, record/table scopes, aliases, named formulas, typed record/table aliases, pure user-defined functions, component input/output data, pure input/output functions, actions, and event properties, and errors distinct from Blank. Unsupported functions, controls, versions, and identifiers are surfaced.

Implemented control versions are listed in `powerapps_sim/controls.py`: modern text/buttons/comboboxes/text inputs/number inputs/date pickers/tab lists/toggles/checkboxes/sliders/dropdowns/radio groups/progress bars/spinners, classic labels/buttons, rectangles/images, automatic/manual containers, galleries, forms/data cards, and canvas components. Form state includes modes, defaults, validation, updates, unsaved state, errors, and LastSubmit. Mutations persist in SQLite and invalidate evaluated properties.

`ModernButton@1.0.0` now resolves the selected outline/filled glyph, applies IconRotation, and renders IconBefore/IconAfter/TextOnly/IconOnly layouts. Icon, IconStyle, IconRotation and Layout defaults were checked against the Microsoft template embedded in the supplied archive; its desktop Width/Height defaults are 96/32. Authored Color, horizontal/vertical alignment, font decoration, padding, border style/thickness/color and independent corner radii reach the button face. Invalid properties report scoped errors and leave peer controls usable. These properties follow [Microsoft's modern Button contract](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-button). Theme-derived palettes, font metrics, hover/pressed styling and exact Studio rendering remain approximate; the existing legacy property compatibility is retained.

Create the fictional button comparison project with `python -m powerapps_sim.fixtures projects/buttons-check --kind buttons`. Its 32-step workflow covers reactive icon inputs, two isolated component counters, typed callbacks, reset, disabled gates, mapped SQLite writes and failed-save recovery in English/French and Float/Decimal modes. Source, list definitions and workflows are packaged separately; exported source contains only Power Apps YAML.

`ModernTabList@1.0.2` now honors Default and retains its imported Horizontal/Vertical alignment, TabSize and circular appearances. The [new documented 1.0.0 contract](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-tabs-or-tabs-list) uses Start/Center/End positioning and four appearances. Selection, scoped ItemDisplayText, callbacks, reset and stale-operation rejection stay in Python. Stable accessible buttons use arrow/Home/End focus navigation and Enter/Space activation, following [Fluent Tab List behavior](https://github.com/microsoft/fluentui/blob/master/packages/react-components/react-tabs/library/src/components/TabList/useTabList.ts). Native callback order, unmatched/default refresh behavior and theme metrics remain unverified. Omitted/Blank defaults retain the simulator’s first-tab fallback. Source is preserved; invented multi-selection properties report Unsupported. Create its fictional component/save fixture with `python -m powerapps_sim.fixtures projects/tabs-check --kind tabs`.


`ModernCheckbox@1.0.0` uses Boolean Checked, Label, OnSelect, OnCheck and OnUncheck; its callbacks see the committed value. The simulator runs OnSelect before the matching check callback; exact Studio ordering remains to be compared. `ModernSlider@1.0.0` uses Default, finite Min/Max, output Value, horizontal/vertical LayoutDirection and SliderSize.Small/Medium/Large. User input is bounded, and OnChange observes Self.Value. Both support reactive defaults, Reset, disabled/hidden gates, gallery scopes and isolated component instances. Slider styling is approximate. These contracts follow Microsoft's [Checkbox](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-checkbox) and [Slider](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-slider) documentation.

Modern Dropdown and Radio use scalar/record Default matching, record-valued Selected, per-item ItemDisplayText scopes, immediate OnChange, reactive default/reset handling and stable gallery/component instances. Selection reads refresh a matching record by ID when Items changes and return Blank when it disappears. Radio has vertical/horizontal layouts; omitted height is derived from option count and LineHeight. The dropdown uses a themed flyout with arrow/Home/End keys, typeahead, Enter selection and Escape dismissal. Required/ValidationState and accessible names are exposed. Explicit radio height and precise Studio sizing remain comparison points.

ProgressBar validates finite Value/Max, clamps only the displayed progress, and leaves its Power Fx Value intact. Indeterminate rendering does not observe Value/Max errors. Spinner supports reactive Label/Visible, four label positions and Primary/Inverted appearance. Both expose display semantics and respect reduced motion. Spinner's property-change OnChange timing and Radio TriggerOutput remain explicitly unsupported, including on hidden controls. Old Dropdown DefaultSelectedItems and authored Selected/SelectedItems remain visible errors rather than being translated silently. The registered contracts are ModernDropdown/ModernRadio/ModernProgressBar@1.0.0 and ModernSpinner@1.1.0. Sources: [Dropdown](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-dropdown), [Radio](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-controls-radio-group), [ProgressBar](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-progress-bar), [Spinner](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-spinner).

A reusable comparison project contains the four controls, two isolated ChoicePanel instances and an isolated workflow. Create it in an empty directory:

```sh
python -m powerapps_sim.fixtures /path/to/selectors --kind selectors
python -m powerapps_sim --import /path/to/selectors
```

`ModernCombobox@1.0.0` and `@1.1.2` now render a themed searchable menu with keyboard navigation, multiple selection, Clear, Required/ValidationState and a custom delimiter. Python owns `SearchText`, filtering, selection and callbacks. Typing updates search without firing OnChange or dirtying a form; selection/deselection callbacks see committed records. Selected records survive searches that hide them and refresh their fields when the same ID returns. Browser selections carry an option snapshot token so changed/reordered results reject stale clicks. Reset, component reset, changed form Item, NewForm, ResetForm and successful submission cancel pending search drafts. `DelayOutput` uses an approximate 500 ms pause; exact Studio timing remains a manual comparison. Searchable components keep their own query/selection, and the original authored source is retained. These contracts follow [Microsoft's modern Combo box documentation](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-combobox).

Power Fx `Search`, `GroupBy` and `Ungroup` now have AST evaluation and static column/type contracts, including typed empty tables, quoted identifiers and legacy string column names. Search performs case-insensitive text matching across the requested columns; blank queries return the source and encountered row/cell errors propagate. A combobox whose Items formula reads its own SearchText uses that custom query without a second label filter. GroupBy creates nested tables for the remaining columns and supports scoped aggregate formulas. Ungroup restores interleaved GroupBy order through internal value metadata, preserved by table shaping, collection storage and typed function coercion. Metadata is never a record field or exported source. Hand-authored nested tables flatten in outer/inner order; JSON/SQLite round trips discard original grouping order metadata. Complex grouping keys, blank-record ordering and exact Studio comparison remain manual fidelity checks. Sources: [Search](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-filter-lookup), [GroupBy/Ungroup](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-groupby).

Create the fictional search comparison fixture in an empty directory:

```sh
python -m powerapps_sim.fixtures /path/to/search --kind search
python -m powerapps_sim --import /path/to/search
```

It includes single/delayed and multiple selection, two isolated component instances, grouped totals, a SQLite choice card and a stored isolated workflow. Source and list definitions remain separate; exports omit list configuration and simulator state. The fixture generator also now retains stored workflows when a fixture contains lists.

This simulator implements a subset of Microsoft's runtime and compiler behaviour. The Python binder does not reproduce every Power Apps type-checker finding. Control styling, auto-height measurements, fonts, animation, loading/concurrency timing, and gallery virtualization are approximate. Gallery rows load from visible scroll windows; local queries still evaluate all records. The initial scope does not include live connectors, Microsoft authentication, SharePoint item permissions, delegation limits, arbitrary PCF controls, every enhanced component property schema/overload or every Power Fx function/overload. Existing broken references are preserved; unrelated screens remain inspectable.

Clipboard export produces Power Apps source syntax. Microsoft validates control versions and properties in Studio, so **actual paste acceptance must be checked there**. App formulas are copied separately because the App object is unavailable through code view. Export does not generate a replacement `.msapp` or imply that editing archive YAML makes an importable package. See [Microsoft's code view documentation](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/code-view) and [canvas source documentation](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/power-apps-yaml).

## Selected Power Fx conformance

Run the offline reference harness:

```sh
python -m powerapps_sim.conformance --json compatibility-report.json
```

On 11 October 2026, the current harness reports **6,703 passes out of 6,710 selected cases, seven known gaps, and zero unexpected regressions**. The reference revision is `df4ceba5e08220db670c25afead342ce699c50b5`. Expected JSON is independently encoded from the upstream expected expressions; the corpus retains Microsoft's MIT notice. This selection is not the complete Microsoft suite or proof of general Power Apps compatibility.

Six gaps involve the documented Canvas relative-year rule versus the pinned engine's absolute years. One involves Dec2Hex truncation of a negative fraction versus the pinned engine's flooring. Known gaps remain visible; `--strict` fails on them, while the default fails on unexpected regressions. The generated JSON records each case, its source and the known mismatch.

For supported host profiles and fixture examples, see [Power Fx](power-fx.md). Earlier corpus sizes and validation snapshots are retained in [History](history.md).

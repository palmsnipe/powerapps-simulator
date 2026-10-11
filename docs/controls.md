# Control reference

[Documentation index](README.md) · [Project README](../README.md)

Version-specific control behaviour, layout, events and fictional comparison fixtures. For native archived canvas versions, see [Archived controls](archived-controls.md).

## Modern text input output timing

`ModernTextInput@1.0.0` and `@1.1.2` now publish Text through `TriggerOutput.Keypress`, `FocusOut` or `Delayed`. Keypress is the default; inputs inside forms default to Delayed. OnChange fires on blur only when text changed since the previous notification. Publishing Text recalculates dependent formulas without running OnChange. Blank becomes empty text, View stays selectable and read-only, and password/search/multiline variants use native browser fields. These contracts follow [Microsoft's modern text input documentation](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-text-input).

The browser uses a 500 ms delay for Delayed output; exact Studio timing remains unverified. Reset, reactive defaults, restart and project switching cancel or reject stale pending output through instance tokens. Form title edits update Unsaved and Updates when published; form save/reset changes the token. The internal OnInput event transports published output to Python and is not an authored Power Apps property. Version 1.0.0 Text is an output; author Default instead. Unsupported source properties remain preserved with diagnostics.

```sh
python -m powerapps_sim.fixtures projects/text-check --kind text
python -m powerapps_sim --import projects/text-check
```

This fixture contains all three output timings, search filtering, password/multiline fields, a required editable form, a read-only field and two isolated component inputs. Its 39-step workflow verifies output versus blur callbacks, form save/view mode, component isolation and resets. The source, list definitions and workflow are packaged separately. Browser checks verified focus/caret preservation, search filtering, form saves, component outputs and pending reset cancellation. Studio paste acceptance remains manual.

## Selection events and read-only controls

Dropdown/radio browser events now carry an instance token for the rendered Items and reset generation. Python rejects a stale index after Items changes, reset, restart, a reactive default change, or project/instance switching. Combobox selection tokens include the same reset generation. Delayed SearchText publications carry an instance token and are discarded after reset; a changed DefaultSelectedItems clears the pending query. Legacy headless index events remain supported, and repeated identical combobox/tab-list selections do not fire duplicate OnChange callbacks.

Combobox defaults now include Required false, ValidationState.None and the documented "Find items" placeholder. Required, validation, layout and text delimiter properties have explicit type checks. This follows [Microsoft's combobox behavior and defaults](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-combobox), including immediate selection callbacks regardless of DelayOutput. The delayed search interval remains an approximate 500 ms.

View-mode dropdowns retain their normal appearance and cannot open choices. View-mode combobox fields remain selectable/read-only, hide the clear button and inherit a form's mode. Radio View mode retains the selected circle without disabled gray styling. Dropdown/radio selection changes remain immediate, following the documented [dropdown](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-dropdown) and [radio](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-controls-radio-group) contracts. Styling and complete version defaults still need Studio comparison. Radio TriggerOutput remains explicitly unsupported because its documented timing lacks a precise contract.

The selectors fixture now includes **Toggle read-only**; the search fixture includes **Toggle form view**. Both are source controls using ordinary Power Fx, and existing stored workflows remain applicable. New backend cases cover stale indices, reset/default/restart generations, instance isolation, malformed events, property types and callback deduplication. Browser evidence covers selection callbacks, delayed-search reset cancellation and inherited form View mode.

## Date and number input contracts

ModernNumberInput now supports versions 1.0.0 and 1.1.2, Step buttons, Auto or 0–3 decimal Precision, HintText and validation. Number text commits on blur; step clicks publish immediately. Python validates finite values, bounds and positive Step, and rejects invalid input while the browser retains the draft. Repeated values do not fire duplicate callbacks. Precision normalization uses half-away-from-zero rounding; steps stop at representable bounds. Exact Studio rounding and boundary behavior remain comparison tasks. This follows the documented properties and callback triggers in [Microsoft's number-input documentation](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-number-input).

ModernDatePicker supports versions 1.0.0 and 1.0.2 through a local calendar. Python generates the month cells, date bounds, weekday order and labels; browser selection returns an ISO date for validation and typed Date output. Previous/next and month/year navigation do not run OnChange. Format, StartOfWeek, StartDate, EndDate, IsEditable and ValidationState are evaluated. Editable fields accept ISO, supported custom numeric patterns and localized dates; View fields stay selectable and the calendar cannot open. The properties follow [Microsoft's date-picker documentation](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-date-picker). Calendar geometry, full locale coverage and Studio paste acceptance remain unverified.

DateTimeZone converts DateTime defaults using UTC or the simulated clock's fixed offset before taking the calendar date. Date-only values retain their day. Named timezone/DST support remains incomplete; this is not a full Microsoft client timezone model. Invalid calendar/number contracts stay visible as diagnostics. Tokens include control instance, resets and relevant settings so late drafts cannot apply after a default, language, format, bounds, restart or instance change. Forms retain typed Updates/LastSubmit and failed-save edits; browser blur commits are queued before form submission.

```sh
python -m powerapps_sim.fixtures projects/inputs-check --kind inputs
python -m powerapps_sim --import projects/inputs-check
```

This fixture contains bounded numeric inputs, two date input modes, two isolated component instances, English/French labels and a local cost/due-date form. Its 29-step workflow verifies precision, callbacks, typed saving, reset and component isolation. The source, list definitions and workflow are packaged separately. New 1.0.0 source treats Value/SelectedDate as outputs; older authored output bindings remain supported for imported patterns. Number TriggerOutput and the removed date Required property in 1.0.0 remain preserved with diagnostics.

## Modern icons and component images

`ModernIcon@1.1.0` renders local Fluent SVG glyphs with Outline/Filled styles, rotation, color, padding and borders. A meaningful OnSelect creates a native keyboard button; decorative icons remain outside the tab order. AccessibleLabel supplies the decorative image label. Disabled/View events stay blocked. Style, TabIndex and AcceptsFocus are reported as unsupported properties for this version. These contracts follow [Microsoft’s modern icon documentation](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-icon).

Modern button glyphs use the same assets. The vendored Microsoft SVG package contains 2,977 names and 5,899 glyphs, with its license and notices, and needs no runtime download. That catalog is broader than Studio’s documented picker; it does not prove that every name is accepted by Canvas. The verified classic catalog adds 181 Icon enum names; the previous Delete/Upload convenience aliases remain available to modern glyph formulas and report Unsupported on classic controls. Missing glyph/style combinations produce diagnostics. The 32×32 size, Outline style and zero rotation follow the documentation; other omitted visual defaults are simulator approximations. SetFocus remains unsupported for ModernIcon. Exact aliases, visual defaults and clipboard acceptance need Studio comparison.

Component Image inputs, outputs and function parameters retain media values through conversion, rendering and JSON binary handling. Type(...) declarations containing Image now report the documented unsupported-type diagnostic; component Image contracts remain supported. Blank remains Blank, Text explicitly removes the media type, and invalid aggregate cells retain their errors. Media origin is preserved for local assets. Live value inspection now retains Image typing alongside its URI, with previews for local assets/data images.

Create the fictional fixture with `python -m powerapps_sim.fixtures projects/icons-check --kind icons`, then launch `python -m powerapps_sim --import projects/icons-check`. Its 32-step isolated workflow covers two independent component instances, callbacks, gallery selection, reset, blocked controls and an image-bearing SQLite snapshot. Browser checks verified pointer/Enter/Space, tab order, glyph rotation/styles and persisted records. Backend checks cover all vendored symbols and source preservation. Actual Studio observations remain unverified.

## Classic icons and named colors

`Classic/Icon@2.5.0` is supported with 181 genuine `Icon.*` identifiers extracted from Microsoft's [pinned TestEngine sample](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mda-icons-controls/MDA_Icons_Solution_1_0_0_2.zip). The local mapping file records its source and archive hash. Glyphs use curated Fluent counterparts, so classic appearance is approximate. Filled enum variants retain their style and distinct enum identities even when two names map to the same glyph. Branches, records, tables, copying and Distinct preserve those identities; inspectors and the AI formula API label values as Icon. Explicit Text returns the mapped Fluent name. Exact Studio enum-to-text/equality coercions remain unverified; Type(Icon), Icon component property declarations and Power Fx JSON encoding of Icon values are unsupported. JSON reports the gap or honors IgnoreUnsupportedTypes rather than presenting the mapped name as a verified Canvas encoding.

Classic TabIndex defaults to -1, even with OnSelect. Negative values render an image (or unlabeled decoration) which can receive pointer selection; nonnegative values render a native keyboard button, even with a blank OnSelect. Disabled/View controls block events. Focus borders, hover/pressed/disabled colors and fills, padding, rotation and PreserveAspectRatio are implemented. Classic gallery icons use the existing implicit Select(Parent) action, with row scope preserved. TabIndex remains -1 unless authored. SetFocus does not support icons. Modern-only IconStyle/IconColor/AcceptsFocus/BasePaletteColor/Style properties report Unsupported. These interaction contracts follow [Microsoft's shape and icon reference](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-shapes-icons).

The sample template verifies ArrowDown, 64×64, rotation 0, TabIndex -1, PreserveAspectRatio true, black Color, transparent Fill, gray DisabledColor and Self/ColorFade interaction defaults. Common border/theme defaults, including focused thickness, are simulator approximations; exact border geometry, legacy glyphs and Studio clipboard acceptance still need comparison.

The color catalog now covers 148 documented names, including Transparent. ColorValue validates names case-insensitively and 6/8-digit hex input. ColorFade accepts named, hex and RGBA colors, retains alpha, and validates the -1…1 fade range in Float and Decimal host profiles. Fractional channel rounding remains an approximation. The catalog is local and records the [Microsoft color reference](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-colors) and source hash.

Create `python -m powerapps_sim.fixtures projects/classic-icons-check --kind classic-icons`. Its repeatable 29-step workflow tests two component instances, callbacks/reset, pointer/keyboard actions, blocked controls, enum identity and a SQLite snapshot. Browser checks cover Enter/Space, Tab order/focus retention, focused borders, disabled colors, rotation/aspect ratio, implicit gallery actions, long scrolling and filled glyphs. The CI browser case additionally asserts held-pointer pressed styling; it was compiled but not run during the native browser verification.

## Classic text inputs and dropdowns

`Classic/TextInput@2.3.2` and `Classic/DropDown@2.3.1` now have separate Canvas contracts. The checked-in catalog records defaults, versions and the hash of Microsoft's [pinned DifferentTypes sample](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/differentvariabletypes/DifferentTypes_1_0_0_11.zip). Its legacy template metadata is reference evidence; this does not add legacy JSON archive import. PCF text/dropdown controls use different contracts and are not covered by these classic families. Localized, inherited/theme and automatic-layout defaults remain approximate and are identified separately in the catalog.

Text input keeps Default and Text separate, publishes immediately or after the documented 500 ms DelayOutput interval, and runs OnChange on blur. Reset and default changes cancel old drafts. Single-line Clear preserves focus; multiline/password modes, MaxLength in UTF-16 units, spellcheck, keyboard hints, interaction colors and focus borders are rendered. Format.Number restricts the supported Latin numeric symbols while keeping Text as text. Device keyboards, complete locale restrictions and exact Canvas timing are unverified. See Microsoft's [text input reference](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-text-input).

Dropdowns resolve Value as the display column, including mapped logical list names, and match scalar Default against its displayed text. AllowEmptySelection controls Blank versus first-row fallback. Selected remains the source record; deprecated SelectedText exposes its display value. The flyout limits displayed choices to 500, preserves full Items, and supports pointer/keyboard selection, selection colors and instance/reset tokens. Removed selections fall back without inventing OnChange events. SetFocus supports classic text inputs; dropdown SetFocus remains unsupported. See Microsoft's [dropdown reference](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-drop-down).

Create `python -m powerapps_sim.fixtures projects/classic-inputs-check --kind classic-inputs`. Its 43-step isolated workflow covers two component instances, typed record callbacks, explicit component OnReset collection clearing, text/default resets, optional selections, mapped form writes, required-field failure and recovery. Native browser checks cover delayed-output caret retention and cancellation, clear-button focus, keyboard selection, SetFocus borders, independent components and form save/failure/reset. The CI browser case is compiled but was not executed in this native verification. Thirty-one backend regression cases cover these contracts, failed writes, stale selections and the 500-choice limit.

## Classic checkbox and radio controls

`Classic/CheckBox` supports the 2.0.1 reference and 2.1.0 compatibility target. The local catalog records Microsoft's [pinned component-test archive](https://github.com/microsoft/PowerApps-Tooling/blob/630e6973e5c81ddc196283cde26dd696d619d6c7/src/PAModelTests/Apps/ComponentTest.msapp), its hash and its 2.0.1 template version. Newer version differences and omitted inherited/theme/localized defaults remain unverified. `Classic/Radio@2.3.0` implements the documented property contract with approximate omitted defaults; its exact version template has not been recovered. These are compatibility targets, not verified Studio version equivalence.

Checkbox separates Boolean Default from Value and Text from the modern Label property. OnSelect and OnCheck/OnUncheck read the committed value; repeated values do not run change callbacks. Resets/default changes invalidate pending browser events without inventing callbacks. CheckboxSize, box/checkmark colors, state text/fill colors, focus borders, TabIndex and ancestor visibility/mode gates are rendered. The contract follows Microsoft's [checkbox reference](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-check-box). Exact callback ordering, Blank defaults and Studio appearance remain comparison points.

Radio uses Value as its display column, including logical list names, matches scalar Default against display text, and retains the full record in Selected. Deprecated SelectedText returns displayed Text according to the documentation. Missing/Blank defaults remain unselected; removed selections resolve the default without generating OnChange. Native radio groups support arrow/Space selection, horizontal/vertical layouts, colors and focused borders. Clicking an already-selected label runs OnSelect once. Selection tokens reject events from old instances, defaults or reset generations. Required and ItemDisplayText are modern contracts and report Unsupported; use a required form card and the classic Value column. See Microsoft's [radio reference](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-radio). Exact SelectedText legacy coercions, pixel geometry, version defaults and Studio paste acceptance remain unverified. SetFocus is unsupported for both families.

Create `python -m powerapps_sim.fixtures projects/classic-selection-check --kind classic-selection`. Its 58-step isolated scenario covers Boolean/radio events, two components, typed callbacks, resets, required Boolean false, mapped form writes, injected write failure/retry and missing-stage validation. Gallery checkboxes also write their own source rows and select their parent gallery. The same scenario runs with English and French labels while stored stage codes stay unchanged. Thirty-seven backend cases cover these contracts, tokens, logical columns, source preservation and owner isolation. Native browser checks verify keyboard/focus behavior, label callback deduplication, read-only/disabled controls, persisted Boolean false, gallery writes, translated labels and typed live component collections. The CI browser case is compiled but was not executed during this native verification.

### Classic toggle, slider and date picker

`Classic/Toggle@2.1.0`, `Classic/Slider@2.0.1/2.1.0`, and `Classic/DatePicker@2.6.0` now have separate classic contracts. Toggle and date-picker defaults were recovered from Microsoft's pinned TestEngine archive; the slider reference is version 2.0.1, so differences from 2.1.0 remain unverified. The catalog records provenance, null defaults and approximate theme/device defaults. No reference app data is included in the package.

Toggle exposes Boolean Value, Default, true/false labels and state colors, OnCheck/OnUncheck and OnChange. Slider exposes Number Value, signed bounds, clamped Default, ReadOnly, horizontal/vertical layout and handle/rail presentation. Slider movement updates the server value without running a callback; release/keyboard commit runs OnChange once per changed committed value. Reset and changed defaults invalidate queued events and clear pending committed-value comparisons. This timing and native continuous keyboard increments remain approximations pending Studio comparison. See Microsoft's [toggle](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-toggle) and [slider](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-slider) references.

The classic date picker exposes Date SelectedDate, DefaultDate, Language, Format, DateTimeZone, StartYear/EndYear and StartOfWeek. Python validates calendar/typed dates and builds localized cells. Calendar choices remain pending until OK; Cancel/Escape discard them. PageUp/PageDown navigate months, with Shift for years. Invalid typed drafts stay visible without changing the server value; reset restores the last valid date. Required date validation and mapped form writes remain server-owned. The calendar header/icon/selected/hover colors are approximated; authored hidden calendar geometry/unused internal colors report Unsupported; exact touch/accessibility behavior, callback timing and Studio paste acceptance need comparison. SetFocus is unsupported for these families. See Microsoft's [date-picker reference](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-date-picker).

Create `python -m powerapps_sim.fixtures projects/classic-scalars-check --kind classic-scalars`. Its 52-step isolated workflow passes in English and French and covers typed component records, separate instances, slider preview/commit deduplication, resets, signed bounds, mapped Boolean/Number/Date forms, failed saves/retries and required-date recovery. Thirty-three backend cases exercise contracts, stale events, malformed inputs, time zones and instance isolation. Native browser verification covers keyboard/focus preservation, OK/Cancel, month/year navigation, French labels, invalid drafts and saved values. The CI browser case is compiled but was not executed locally. All eight sample workflows pass on disposable snapshots while preserving the live owner's state.

## Gallery controls

Gallery backgrounds support pointer and Enter/Space activation, `Selectable`, row labels and per-row `TemplateFill`. Omitted child `OnSelect` uses `Select(Parent)` for recognized versions, while an explicit formula (including Blank) overrides that default. Programmatic `Select(Parent)` and `Select(Gallery, row [, child])` can select rows even when background selection is disabled; the sample role editor uses this path. `Select` retains queued callback ordering. Container default chains stop at component boundaries, and unsupported components inside galleries retain their diagnostics.

`ThisItem.IsSelected` is virtual row metadata: it is available to formulas without becoming a SQLite or exported source field. Stable row keys distinguish duplicate occurrences, refresh selected records after data changes, preserve row input instances across ID-based sorting, and select the correct child instance. Nested gallery Items formulas read the outer row; nested OnSelect formulas read their own selected row. Background event tokens reject stale clicks after item changes or reset. Reset restores Default/first-row selection and scroll position without recursively resetting template inputs.

Create the independent fixture with `python -m powerapps_sim.fixtures projects/gallery-check --kind galleries`, then launch `python -m powerapps_sim --import projects/gallery-check`. Its 27-step isolated workflow covers background selection, callbacks, programmatic actions, selection gates, defaults, reset and reordering. Browser checks additionally cover omitted child actions, typing/focus preservation, scrolling, keyboard activation, wrapping and nested galleries. `AllItemsCount` and `AllItems` reflect loaded rows, which may be fewer than Items. Scrolling loads additional rows without a 500-row cap. Styling, wrapping/padding geometry, exact Default-change timing, duplicate identity after arbitrary edits, screen-reader announcements and Studio observations of Selectable/programmatic selection still need comparison. Clipboard/source acceptance remains a manual Studio check.

`AllItems` includes typed references to the controls in each loaded row, including container descendants. Nested gallery controls expose their own AllItems; their inner controls stay in that inner scope. Reading AllItems can build row instances before any preview without evaluating unrelated properties or running events. Aliases, ThisRecord, projections, Filter/LookUp, aggregates and table shaping can read the controls. For example:

```powerfx
ForAll(ProjectGallery.AllItems As row,
    {ID: row.ID, Title: row.TitleInput.Text, Cost: row.CostInput.Value})
```

Captured AllItems records retain their data values and live control references. After ID-based reordering, those references still point at the same row instance. Removed instances raise an error when read after row reconciliation. Use explicit records to collect edit snapshots or write list fields; controls cannot be stored in SQLite. Item/control column-name collisions are reported instead of overwriting source fields. Control references in collection/variable inspectors open the corresponding control; its inspector includes public current outputs such as Text, Value, SelectedDate and SelectedItems, plus component input/output values. Internal bookkeeping is excluded.

Create the linked fixture with `python -m powerapps_sim.fixtures projects/gallery-edits-check --kind gallery-edits`. Its 49-step workflow verifies text, numeric, choice, date and toggle edits, live references versus snapshots, component callback saving, logical/display names, persistent list writes, partial validation failure, input reset, write-failure injection and retry. Saved-list error history can be cleared by a later row operation; the fixture captures each failed row's Errors table inside its ForAll error handler. Browser verification also checks clickable control inspection and horizontally scrolling 14-column collection tables. Exact Canvas reference lifetime, name-collision rules and loading/viewport timing remain Studio comparison points.

Gallery loading uses one initial viewport plus one buffer page. Scrolling adds the visible window and one page on either side; a jump loads its destination without loading every intervening row. Loaded rows retain their template control references and input values until removed from Items or the simulation restarts. The browser renders only the current window and caches detached input elements so malformed/unpublished drafts survive scrolling. Sorting retains ID-based row instances. Reset returns to the first scroll position and preserves edited inputs and loaded rows.

`DelayItemLoading` waits for the gallery's first visible browser frame. `LoadingSpinner.Controls`/`Data` shows a local loading indicator during that wait. Horizontal galleries and WrapCount share the same window logic. Browser viewport events only change presentation state; they do not execute app callbacks or write lists. These behaviors follow Microsoft's [Gallery control documentation](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-gallery). The buffer size, scheduling and spinner timing are simulator choices and require Studio comparison. Flexible-height gallery templates and navigation-arrow properties remain unsupported.

Create the 2,048-row fictional comparison fixture with `python -m powerapps_sim.fixtures projects/gallery-loading-check --kind gallery-loading`, then launch it with `python -m powerapps_sim --import projects/gallery-loading-check`. Its 28-step isolated workflow checks incremental loading, off-screen edits, captured references, sort/reset, wrapped scrolling and callback counts. Native browser verification additionally covered rows beyond 500, retained invalid numeric drafts, focus during updates, horizontal scrolling, and reset scroll position.

## Focus and keyboard navigation

`SetFocus(Control)` is a behavior function. Python validates the target and sends a distinct focus request; browser updates apply each request once. Supported targets are modern/classic buttons, modern text input, text/label and image controls. Disabled or hidden targets leave focus in place. Programmatic focus remains available when a control is excluded from the Tab sequence; read-only text inputs remain focusable. Gallery, form, component and container descendants, unsupported families and other-screen targets are rejected. Component event callbacks can request focus on a host control. These restrictions follow [Microsoft's SetFocus reference](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-setfocus); modern family mappings and exact canvas-host timing still need Studio comparison.

Modern `AcceptsFocus` and classic `TabIndex` govern keyboard stops. Positive custom indices are treated as zero, following Microsoft's [accessible control order guidance](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/accessible-apps-structure). Manual controls use the first rendered visual Y/X order, retained across reactive moves; containers, cards and gallery rows keep grouped sequences. Automatic containers retain flex order. Paint order remains based on authored order and open flyouts stay above it. Native Tab/Shift+Tab behavior is preserved. Exact saved-app ordering, screen-reader announcements, focus-border property styling and mobile soft-keyboard behavior remain comparison points.

Create the fixture with `python -m powerapps_sim.fixtures projects/focus-check --kind focus`, then launch `python -m powerapps_sim --import projects/focus-check`. Its 33-step isolated scenario covers typing, keyboard contracts, host callbacks, independent drafts and navigation. Browser checks additionally verify focus, off-screen scrolling and refreshes that preserve focus. Source, list configuration and workflows remain separate.

## HTML text and HTML/URL functions

`HtmlViewer@2.0.0` and `HtmlViewer@2.1.0` now render formatted text, inline styles, tables/lists, local bitmap assets and fragment links. HtmlText also coerces scalar numbers/dates through the host locale; record/table values remain errors. HTML properties evaluate through the Python AST runtime, including named formulas, typed component functions, gallery `ThisItem`, isolated component state and callback parameters. Non-link content invokes `OnSelect`; hyperlink clicks and keyboard activation do not. The HTML container has no TabIndex or SetFocus contract; its internal anchors use native tab navigation. The [Microsoft HTML control contract](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-html-text) documents these behaviors and the 7,680-pixel AutoHeight cap.

HTML is rendered in a separate shadow tree to isolate its IDs and styles from the editor. Script/embedded-app content, interactive inputs, global styles, external image/network sources, external navigation and unsupported CSS/attributes produce current Unsupported diagnostics. Supported local content remains inspectable. Raw HtmlText, formulas, names and YAML remain unchanged in source, inspectors, saved records and exports; sanitization only affects the preview fragment. Local `/api/asset/` bitmap URLs and embedded PNG/JPEG/GIF/WebP are supported. This release uses a deterministic server estimate for HTML wrapping/AutoHeight and reactive sibling layout, bounded at 7,680 pixels. Font metrics, table columns, CSS flex positioning, spans with mixed font sizes and absolute-positioned content remain approximate. Authored Height is a minimum for the current auto-grow estimate. Browser/Studio pixel comparison is still needed.

Width/Height (200/40), five-pixel padding, AutoHeight false and disabled/hover styling defaults were recovered from Microsoft's shipped 2.0.0 templates. The documented 2.1.0 version shares this contract; common font/theme fallbacks and the unresolved localized default HtmlText are simulator approximations. The original app's source is never repaired or renamed by this renderer.

`EncodeHTML`, `PlainText` and `EncodeUrl` are scalar Power Fx functions with text coercion, Blank/error handling, lazy branches and typed return values. They do not accept table overloads. EncodeHTML follows HttpUtility's quotes, Latin-1, supplementary-character and unpaired-surrogate handling. PlainText follows the pinned LibraryText tag replacement order, trims .NET whitespace, decodes HTML4 character references and uses the Canvas/Windows CRLF line-break contract on both platforms. PlainText is a text-conversion function, not an HTML sanitizer. EncodeUrl follows URI percent encoding with unreserved RFC3986 characters. See the [Microsoft function documentation](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-encode-decode) and [pinned implementation](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Interpreter/Functions/LibraryText.cs).

```sh
python -m powerapps_sim.fixtures projects/html-check --kind html-text
python -m powerapps_sim --import projects/html-check
```

The fictional fixture has two isolated components, live HTML, a typed formatter, action/event callbacks, HTML gallery rows, local saves, failure/retry, reset, editable records and a 20-column expandable collection. Its 43-step workflow runs in English/French and Float/Decimal modes on a disposable snapshot, preserving the owner's runtime and data. The corpus adds **98 independently encoded cases**: every expression in pinned EncodeHTML.txt and PlainText.txt in both number modes. Additional backend checks cover source round trips, malformed drafts, geometry, property contracts, scopes and visible unsupported HTML. The existing AI/MCP tools expose this control, its source and its workflows through the same runtime; no extra execution service is required.

## Rich text editor

`RichTextEditor@2.3.0`, `@2.5.0` and `@2.6.0` now provide WYSIWYG editing, bold/italic/underline, text and highlight colors, sizes, lists, links, clear formatting and native undo/redo. `Default` supplies HTML; `HtmlText` is an output. Python owns the published HTML value, reactive evaluation, `OnChange`, reset tokens and form persistence. Scalar defaults coerce through the host's Power Fx text conversion. Record/table defaults, authored output properties, unsupported contracts and unknown versions produce diagnostics without repairing source. `EnableSpellCheck`, signed `TabIndex`, inherited modes, component isolation, typed callbacks, gallery `ThisItem`, required cards and failed-save retry are covered.

The editor uses a script-free sandboxed iframe and a Python HTML sanitizer. Supported formatting and HTTP/mail/telephone/fragment hyperlink values survive into `HtmlText` and SQLite. Links are authorable but do not open destinations in the simulator. Script/style/embedded-app content, external images, unsupported CSS and attributes are removed from editor values and reported. Pasted HTML goes through Python before insertion; local/embedded PNG, JPEG, GIF and WebP are supported. A formatted empty paragraph publishes an empty string so required cards cannot be satisfied by empty markup. Reset, record switching, changed defaults and restart invalidate pending edits. Original source `Default` formulas and YAML stay unchanged; unlike the HTML display control, sanitized editor input becomes the output value.

Microsoft's shipped [Account Plan reviewer app](https://github.com/microsoft/PowerApps-Tooling/blob/630e6973e5c81ddc196283cde26dd696d619d6c7/src/PAModelTests/Apps/AccountPlanReviewerMaster.msapp) provides the 2.3.0 template: output HtmlText, OnChange, Reset, spellcheck true, TabIndex zero, and width/height 515/158. The [Microsoft Teams templates](https://github.com/microsoft/teams-powerapps-app-templates) contain 2.5.0 and 2.6.0. These verified versions share the implemented contract. Localized default content, theme fallbacks, toolbar layout, browser HTML serialization, change-event timing and paste appearance remain approximations awaiting Studio comparison. The implementation uses the browser's native editing commands for its undo buffer; a command unavailable in that browser emits an Unsupported diagnostic. The [Microsoft rich text contract](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-richtexteditor) remains the reference for actual Canvas behavior.

```sh
python -m powerapps_sim.fixtures projects/rich-check --kind rich-text
python -m powerapps_sim --import projects/rich-check
python -m powerapps_sim.workflows --project projects/rich-check --scenario projects/rich-check/tests/rich-text.workflow.json
```

The fictional fixture includes two isolated rich-text components, typed callbacks and HTML outputs, an editable form, gallery editors and a readable 20-column collection. Its 65-step workflow covers translations, resets, modes, required bodies, failed save/retry and persistent rich HTML. AI clients can inspect these outputs and run the scenario through the existing MCP adapter; the core editor still needs no SDK, Node, .NET or network at runtime.

## Timers and simulation time

`Timer@2.0.0`, `@2.0.1` and `@2.1.0` now have server-owned elapsed values and start/end callbacks. `Start`, `Repeat`, `Reset`, `AutoStart` and `AutoPause` participate in reactive evaluation. `Value` is an output. Duration is in milliseconds, from zero through 24 hours; the template default is 60 seconds. Hidden timers keep running, while AutoPause stops progression on an inactive screen. These properties follow the [Microsoft Timer contract](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-timer). The versions and Boolean defaults are present in [Microsoft PowerApps-Tooling](https://github.com/microsoft/PowerApps-Tooling/tree/630e6973e5c81ddc196283cde26dd696d619d6c7/src/PAModelTests/Apps) and [Teams templates](https://github.com/microsoft/teams-powerapps-app-templates).

The local preview has **Play/Pause time** and **Advance 1s** controls. A browser pulse sends no elapsed value: Python reads its monotonic clock and executes ordered deadlines. Multiple pulses at the same instant do not duplicate elapsed time. Paused time and direct screen/component inspection freeze progression without replaying the inspection interval. Restart creates a new generation token, rejecting pulses from older runtimes. A timer button can toggle native playback without modifying its authored Start formula. Programmatic `Select` continues to invoke OnSelect only. Reset and component OnReset affect the relevant instances, preserving independent component variables and collections.

`Now()` and `Today()` reflect the simulation offset from the configured clock; clock settings and source files remain unchanged. List metadata and callback timestamps use the same advanced clock. Timer callbacks execute through the existing Python behavior evaluator, including typed component events, record scopes, navigation, queued Select, Patch, errors and collections. Gallery timers follow ThisItem and stop after their source row disappears. AI runtime inspection observes timer state without advancing time or draining behavior. The existing MCP workflow tool can exercise the complete scheduling path.

Workflows support `{"op":"advance","milliseconds":1500}` for deterministic time steps. Deadlines run in stable control registration order when they coincide. End callbacks see Value at Duration; a repeating cycle then resets Value and emits its next start event. This release emits a start callback on resume as well. Source changes to Duration clamp the current value to the new duration; completion is processed on the next time step, including a zero-length advance. These ordering, resume and native-toggle details are simulator policies requiring actual Studio comparison; they are not claims of measured Canvas parity. Browser redraws are approximately every 250 milliseconds. No browser formula execution, worker process, Node or .NET is required.

Startup/reset loops are bounded at 100 events. A time step cannot replay more than 1,000 end callbacks; an oversized request reports a Cycle diagnostic and retains the reached clock/value state for further smaller steps. Zero-duration repeating loops are suspended after that diagnostic. Other healthy timer instances remain usable. Unsupported versions, authored Value/Running, input-value injection and invalid property types are visible. The unresolved inherited Text, dimensions, theme and styling defaults are approximations; timing jitter, serialization and exact Studio paste acceptance still need manual checks.

```sh
python -m powerapps_sim.fixtures projects/timer-check --kind timers
python -m powerapps_sim --import projects/timer-check
python -m powerapps_sim.workflows --project projects/timer-check --scenario projects/timer-check/tests/timers.workflow.json
```

The fictional fixture contains two scoped repeating timers, typed callbacks, SQLite writes, a hidden background timer, an AutoPause timer, a screen-entry one-shot, navigation and a 20-column collection. Its 83-step workflow tests these behaviors plus save failure/recovery and clock timestamps in English/French and Float/Decimal modes. All local app source remains exportable without clock/transport fields.


Classic ComboBox uses `Classic/ComboBox@2.3.0`, `2.3.1` or `2.4.0`. The first two versions are recovered from Microsoft Language Tooling archives at commit `630e6973e5c81ddc196283cde26dd696d619d6c7`. Nine pinned Microsoft Teams control manifests verify 2.4.0; its omitted-property contract inherits the recovered 2.3.1 template pending Studio comparison. Provenance, version overrides and approximate defaults are recorded in `powerapps_sim/static/classic-combobox.json`. The 2.3.0 delimiter retains the recovered template string verbatim; interpretation of its Unicode escape in Studio remains unverified.

Classic display and search use `DisplayFields`/`SearchFields` rather than modern `ItemDisplayText`. Python searches text fields and retains item indices. Search does not change selections, dirty forms or invoke OnChange. Record or table `DefaultSelectedItems` is supported, as is deprecated record `Default` when the newer property is omitted. `Selected` returns the last selected record; `SelectedItems` retains selection order. Individual tags, keyboard selection, clear/reset, mode gating, scoped callbacks, required card validation, form Updates/LastSubmit and SQLite persistence are supported. Authored outputs or modern-only properties report Unsupported and remain in exported source. [Microsoft ComboBox contract](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-combo-box).

Single, Double and Person templates render one or two text fields; person pictures use fictional initials. `NavigateFields` enables row navigation buttons and Alt+Enter; callbacks read `NavigateItem` without changing selection. This navigation UI and exact callback ordering are simulator policies needing Studio comparison. Explicit `SearchItems` is evaluated; when omitted, Python derives results from authored Items/SearchFields instead of the template's creation-time ComboBoxSample formula. Changed fields, results, selected tags or reset generations reject stale browser operations. Full-screen `UsePhoneLayout` reports Unsupported. The documented gallery limitation is represented by resetting classic ComboBox instances when a normal-play gallery scroll offset changes, without OnChange; exact virtualization timing is unverified. Other modern controls retain their existing selection behavior.

```sh
python -m powerapps_sim.fixtures projects/classic-combo-check --kind classic-combo
python -m powerapps_sim --import projects/classic-combo-check
python -m powerapps_sim.workflows --project projects/classic-combo-check --scenario projects/classic-combo-check/tests/classic-combo.workflow.json
```

The fictional fixture includes two isolated people-picker components, typed record callbacks, a single-select classic control, required form owners, SQLite writes and a 20-column collection. Its 69-step workflow runs in English/French and Float/Decimal modes. Workflow OnNavigate steps accept a row index; the service obtains the current option token before dispatching. Browser clients must supply tokens.

## Classic ListBox controls

`Classic/ListBox@2.2.0` and `ListBox@2.2.0` retain their authored names, version and properties. Version 2.2.0 is confirmed in three pinned Microsoft Teams control manifests. No ListBox template XML was recovered: omitted defaults in `static/listbox.json` are explicitly marked approximations, including sizing, colors, padding and selection defaults. Microsoft documents one scalar `Default`, record-valued `Selected`, table-valued `SelectedItems`, `SelectMultiple` and the deprecated text outputs. [Microsoft ListBox contract](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-list-box).

Python evaluates Items, display-name aliases, Value, Default and selection outputs. The browser sends toggle, replace, range, select-all or clear gestures. Tokens reject changes to records, display/default/mode or reset generations; queued gestures over unchanged Items use the current server selection and anchor. Selection tables follow Items order; Selected is the latest surviving selected record. The browser supports pointer selection, Shift ranges, Space/Enter, arrows, Home/End, page keys, typeahead and Ctrl/Cmd+A, with retained focus and scrolling. Exact ordering, range behavior, callback order and deprecated text-output shapes remain simulator policies awaiting Studio comparison.

OnSelect runs before OnChange; OnChange runs when the selected record set changes. Component instances own separate selections, anchors, variables and history. Reset restores one Default and clears the instance's authored state through OnReset. Single-selection ListBox fields work in required form cards with Updates, unsaved state, LastSubmit and save failure/recovery. Authored outputs and modern-only selection/search properties report Unsupported without changing exported code. ListBox does not add an undocumented SetFocus target.

Create a fictional comparison project:

```sh
python -m powerapps_sim.fixtures projects/listbox-check --kind listbox
python -m powerapps_sim --import projects/listbox-check
```

The next compatibility work should prioritize recorded Studio comparisons of existing controls and enhanced components: omitted defaults, callback order, Reset and nested scopes. The Python runtime, workflow runner and existing local MCP adapter share the same authoring/data services; AI can inspect, stage, test, apply and undo app/list changes through them. Broader control families can then be added against measured fixtures. The compatibility goal remains active.

## Form card geometry

Forms now use Python-calculated card bounds. Cards follow logical Y row groups and X order, wrap within each group when minimum widths overflow, share spare width between WidthFit cards, and stretch visually to their row's tallest card. Hidden cards leave the layout. AutoHeight text inside cards or manual groups can grow the row; blank AutoHeight labels collapse. The browser uses the returned bounds and scrolls within the form. [Microsoft form layout](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/working-with-form-layout).

Authored X/Y and Width/Height remain available to Power Fx and export. The control inspector separately shows Rendered X/Y/Width/Height. Source dimensions remain minima; children read those authored properties. Exact Studio evaluation of Parent.Width during WidthFit, sparse row indices, creation defaults, text measurement and scrollbar gutters need recorded comparisons. Omitted card width uses Parent.Width/NumberOfColumns, with WidthFit false and the existing one-column form fallback; these are simulator defaults. SnapToColumns authoring edits do not rewrite imported formulas. Form versions, fields, validation, updates and save callbacks retain their existing contracts.

```sh
python -m powerapps_sim.fixtures projects/form-layout-check --kind form-layout
python -m powerapps_sim --import projects/form-layout-check
```

## Classic DataTable controls

`DataTable@1.0.2` and `DataTableColumn@1.0.1` support record-valued Selected, Items, ordered columns, FieldName/FieldDisplayName, cell Text formulas with ThisItem, hyperlink formatting and column OnSelect callbacks. Those versions are confirmed in Microsoft's [IssueReporting control manifest](https://github.com/microsoft/teams-powerapps-app-templates/blob/75a82892c578397bdd19909af09651fffbb2e2be/IssueReporting/DataverseSolution/CanvasApps/msft_issuereporting_b51d5_DocumentUri_src/ControlTemplates.json). Omitted presentation defaults are simulator approximations; template XML was not recovered. [Microsoft DataTable contract](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-data-table), [column contract](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-column).

Python owns row selection and validates row indices against a data/source token. The token survives queued selections and expires after data, source or restart changes. A surviving selected ID receives refreshed fields after writes. Repeated IDs or identical records use occurrence keys so only one row is selected; this identity policy also awaits Studio comparison. With no explicit selection, the first healthy row is selected; when the selected record is filtered out, the first healthy row is the temporary fallback. Read-only inspection does not change the stored selection. Column callbacks execute after row selection, with ThisItem referring to that row. These selection and callback timing policies await recorded Studio comparisons.

Tables remain read-only. A connected Form.Item can use Table.Selected to edit records with existing validation, unsaved state, LastSubmit and save failure/recovery. Cells require scalar values; explicit Choice.Value or JSON projections can display complex values. Missing identifiers and cell errors remain visible and preserve healthy cells. Unknown versions, authored outputs, unsupported table events, individual column styling and unsupported placement inside galleries, forms, components or automatic-layout containers report diagnostics. Original names, unknown properties, formulas and column subtrees survive copy/export. Microsoft documents component restrictions in the [component overview](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/create-component).

The browser uses explicit column widths with horizontal/vertical scrolling, sticky headings, keyboard row selection and preserved DOM focus. Runtime column resizing affects presentation only and survives state refreshes; it never changes source Width. AutoWidth uses a bounded text-length estimate. Row heights, typography, omitted defaults, AutoWidth metrics, column visibility and callback ordering still need Studio comparison. Header sorting, inline editing, multiple selection and arbitrary newer table/grid versions are not implemented as classic DataTable capabilities.

```sh
python -m powerapps_sim.fixtures projects/data-table-check --kind data-table
python -m powerapps_sim --import projects/data-table-check
```

## Gallery aliases and component row scopes

A root `As` expression on Gallery.Items now names its template row. Nested galleries retain outer aliases, introduce their own alias and keep ThisItem/ThisRecord at the innermost row. Quoted alias names and nearest-scope shadowing work without changing source. Aliases are available to nested queries, input defaults, template fill, accessible labels and OnSelect callbacks, including galleries inside isolated components. Microsoft's [Power Fx operators example](https://learn.microsoft.com/en-us/power-platform/power-fx/operators) demonstrates this pattern with nested Rank and File galleries.

Record frames refresh for retained child controls after source/list changes. Aliases remain scoped to the gallery; they do not become app variables or leak into named formulas or pure component functions. Functions receive values through arguments; action/event callbacks receive the current aliased records through the declared component parameters. Component input/output, state isolation and Reset retain their existing contracts. Exact component Reset/default/event parity still requires Studio observations.

Workflow event steps can use a pure Power Fx control-reference expression instead of a generated control path. An optional scope selects the control/component context for that expression. Supply exactly one of path or target. For example:

```json
{"op":"event","target":"Index(Index(Ranks.AllItems,2).Files.AllItems,3).Pick","scope":"AliasLab/LeftGrid","event":"OnSelect"}
```

The expression resolves against the disposable simulation at that step. It must return a current control reference. Normal active-screen, visibility, display-mode and event checks still apply. Formula evaluation cannot execute behavior. Reports retain the expression, scope and resolved path, so AI clients can test nested rows in Float or Decimal modes without embedding generated row hashes. This is workflow configuration; it is excluded from Power Apps export.

```sh
python -m powerapps_sim.fixtures projects/gallery-alias-check --kind gallery-alias
python -m powerapps_sim --import projects/gallery-alias-check
```

## Modern Data Grid

`ModernDataGrid@1.1.0` and `ModernDataGridColumn@1.1.0` with `Variant: Textual` now render using local Fluent-style HTML. These creation keywords come from [Microsoft's Data Grid example](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-data-grid). Python evaluates cells with ThisItem, filters visible cell text, sorts underlying scalar values with the existing Power Fx comparator, and owns single/multiple selection. Selected is the latest surviving selection; SelectedItems follows source order. Choices represented as a single Value-column table display joined labels. Search and sort retain source Items and selection; selection changes run OnChange after committing the selected record. This ordering and retention policy requires Studio comparison. [Microsoft's control guide](https://github.com/microsoft/power-platform-skills/blob/main/plugins/canvas-apps/references/ControlGuide.md) identifies the selection callback as OnChange.

Searchable, Sortable, SelectMultiple, ShowHeaders, ShowSelector, Required and the selected-record outputs are available. Defaults initialize at first simulation load and are read again on Reset. Reactive default changes leave loaded selection alone. Turning off search clears its filter; disabling sorting clears the presentation order. Resets and stale source tokens prevent old browser gestures from changing new state. Component instances own independent histories, queries, sorting and selection. Form cards observe selection edits, validate required fields, retain failed writes and clear unsaved state after saving.

Columns retain readable widths, overflow horizontally, resize during simulation and keep source Width unchanged. Rows use a fixed height; above 2,000 rows, the browser displays a moving row window while Python still evaluates and searches the entire local table. This browser optimization does not add delegation. Keyboard selection, ranges, select-all, checkboxes, focus and scrolling are implemented as simulator policies. Grid cells remain read-only; connected forms and Local data edit stored records.

Only the documented Textual variant is verified. Other variant keywords, individual column styling, custom row heights, invented Fields/Columns definitions and authored output values report Unsupported. Dataverse AI row summaries require live services and are not simulated. Omitted theme/Required/default-selection choices, exact search collation and native event timing still need recorded Studio comparison.

```sh
python -m powerapps_sim.fixtures projects/modern-grid-check --kind modern-grid
python -m powerapps_sim --import projects/modern-grid-check
```

## Modern Rating

`ModernRating@1.0.0` supports documented `RatingStep.Full`/`Half`, numeric Value, Default, Max, Icon, Color and OnChange. The exact YAML version and property contract come from [Microsoft's Rating documentation](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-rating). Rendering uses bundled Fluent glyphs, including Star and Heart. Python validates input, commits Value before callbacks, tracks form edits and rejects invalid step/range values. Repeated selections do not fire another callback. Disabled/view/hidden ancestors block edits. Source and reset tokens prevent stale browser gestures; tokens are excluded from source exports.

Keyboard arrows change by Step; Home/End select zero/Max. Relative keyboard gestures execute against the current server value, so queued presses accumulate before a browser refresh. Pointer position within an icon selects a half step when enabled. The same DOM control retains focus during updates. Component instances have separate values/history and typed event arguments; aliased gallery rows can Patch their records. Form cards support retained failed edits, retry, LastSubmit and persisted SQLite scores.

Reactive Default changes reset input state without OnChange, following the simulator's existing scalar-input policy. Reset rereads Default. Blank defaults display zero; out-of-range defaults clamp; fractional defaults retain their numeric value even with Full input steps. Callback timing, reactive-default behavior, zero selection, rounding and exact appearance await Studio comparison. RatingStep uses symbolic identity; undocumented Studio backing numbers/conversions are not claimed. Theme color falls back to the simulator brand. Rendering above 1,000 icons reports Unsupported. Authored outputs and known unsupported properties/events are preserved and diagnosed.

```sh
python -m powerapps_sim.fixtures projects/rating-check --kind rating
python -m powerapps_sim --import projects/rating-check
```

## Modern badges and information buttons

`ModernBadge@1.0.0` supports text/numeric Content, optional local Fluent icons, IconPosition, semantic Intent, Appearance and Shape. Its `BadgeIntent`, `BadgeAppearance`, `BadgeShape` and `BadgeIconPosition` enums retain namespace identity in strong mode. An active OnSelect formula enables button semantics and Enter/Space activation; blank handlers are display-only. View/Disabled and ancestor visibility gates apply on the server. Numeric Content is formatted in Python, preserving Decimal host precision and the selected language. Defaults follow the current [Microsoft badge reference](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-controls-badge). Desktop dimensions are 64×32; explicit `"form_factor": "phone"` in emulator.json selects 88×44. Form factor is not inferred from viewport width or recovered from incomplete archive metadata.

`ModernInformationButton@1.0.0` supports Content, IconColor, font styling and OnSelect. Hover opens its presentation flyout without executing Power Fx; clicking also sends OnSelect to Python. Flyout content updates after app changes, long content scrolls within the browser viewport, and Escape/outside clicks dismiss it. View mode prevents opening, following the [Microsoft information-button reference](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-info-button). The local renderer accepts the existing sanitized HTML subset; exact native formatted-content syntax and hover/click timing need Studio comparison. Theme colors, font inheritance and flyout geometry remain approximate. Removed property names report Unsupported and remain in source.

Create the fictional comparison project with:

```sh
python -m powerapps_sim.fixtures /path/to/empty/status-project --kind status
python -m powerapps_sim --import /path/to/empty/status-project
```

Its 23-step workflow covers two isolated component counters, typed callbacks, gallery row scope, information actions, hidden/View gates, SQLite snapshots and component reset. UI-only flyout state is excluded from Power Apps exports. Link controls, exact native theme defaults and Studio clipboard acceptance remain open.

## Audio and Video playback

Canvas `Audio` and `Video` controls now play imported local media through native HTML players. Python owns playback intent, output values and Power Fx execution; the browser reports validated metadata, position and playback events. `Media`, `Start`, `AutoStart`, `AutoPause`, `Loop`, `StartTime`, `Reset` and `ShowControls` are supported, with read-only `Time`, `Duration` and `Paused` outputs. `OnPause` and `OnEnd` use the normal behavior/event pipeline, including typed component callbacks, `Self`, gallery `ThisItem` and navigation. Late observations after pause, completion, source/seek changes, reset or restart cannot alter a newer playback generation. Preview refreshes preserve the player and focused inputs. `AutoPause=false` can keep audio playing after navigation; direct inspection does not execute playback callbacks.

The common properties follow [Microsoft’s Audio/Video reference](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-audio-video). `OnStart` in that reference describes microphone recording and is not an Audio/Video playback event. Audio version `2.1.0`, its Boolean defaults and `Duration` output were inspected in the `audioPlayback` template shipped in [Microsoft’s Chess sample archive](https://github.com/microsoft/PowerApps-Tooling/blob/master/src/PAModelTests/Apps/Chess_for_Power_Apps_v1.03.msapp). Unversioned Audio/Video clipboard controls use the documented common contract. Other version numbers remain explicit unsupported findings pending template inspection. Default player dimensions are approximate, and the simulator does not invent the unavailable `SampleAudio` resource.

Only imported `/api/asset/` clips and audio/video data URIs play offline. Video captions use imported WebVTT files; external captions, remote video/YouTube and codec/autoplay failures remain visible diagnostics. Identical decoder errors in separate component instances remain isolated, and reset or a successful retry clears the affected finding. `Time`, `Duration` and `StartTime` currently use seconds from the browser decoder. Native Power Apps unit/default/callback ordering and loop-start behavior still need a Studio comparison; this release does not claim exact scheduling or player styling. Native browser autoplay/codec restrictions still apply. Microphone recording is not included.

```sh
python -m powerapps_sim.fixtures /path/to/empty/playback-project --kind media-playback
python -m powerapps_sim --import /path/to/empty/playback-project
```

The fictional example includes two independent typed media components, a WAV tone, an MP4 test pattern, local captions, a mapped SQLite snapshot list and a 27-step isolated workflow. Its AI regression stages a callback change in the component source and a snapshot/list-schema change, checks a 28-step candidate, applies it and verifies source/schema/data restoration on undo. The MP4 is a packaged development fixture; ffmpeg is not needed to create or run the project. Workflow `OnMedia` observations are simulator test transport, never added to exported Power Apps source.

## Classic button contracts and presentation

`Classic/Button@2.0.0`, `@2.0.1` and `@2.2.0` use audited Microsoft template defaults, including phone/web dimensions when the project's `form_factor` is configured. Version evidence and archive hashes are packaged in `static/classic-buttons.json`, from Microsoft's pinned [Chess example](https://github.com/microsoft/PowerApps-Tooling/blob/630e6973e5c81ddc196283cde26dd696d619d6c7/src/PAModelTests/Apps/Chess_for_Power_Apps_v1.03.msapp), [Test Studio example](https://github.com/microsoft/PowerApps-Tooling/blob/630e6973e5c81ddc196283cde26dd696d619d6c7/src/PAModelTests/Apps/TestStudio_Test.msapp) and [animation example](https://github.com/microsoft/PowerApps-Tooling/blob/630e6973e5c81ddc196283cde26dd696d619d6c7/src/PAModelTests/Apps/AnimationControlIdIsGuid.msapp). No intermediate version is assumed supported.

Normal, hover, pressed, disabled and focus colors/borders, per-corner radii, padding, typography, alignment and keyboard activation render from Python-evaluated properties. `Pressed` is a Boolean output; it participates in reactive formulas and scoped component callbacks. `AutoDisableOnSelect` prevents repeat activation while a browser callback is pending, guards server callback re-entry, and clears temporary state on success/error. It does not rewrite authored `DisplayMode`. Focus is retained after a temporary disable when the user has not moved it elsewhere; the caption element remains stable during updates. Unknown/version-inappropriate properties and authored outputs are preserved with located diagnostics. Older 2.0.x templates reject authored `ContentLanguage`.

Shared properties whose template contains no default value use explicit host fallbacks, including an English caption and `AutoDisableOnSelect=true`. The template's hover formula uses positive ColorFade; the current [Button reference](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-button) describes dimming. Template values are retained as version evidence; native theme replacement, localized captions, exact focus geometry, event timing and Studio observations remain open.

Create the public fictional example with `python -m powerapps_sim.fixtures projects/classic-buttons --kind classic-buttons`, then launch `python -m powerapps_sim --import projects/classic-buttons`. It has two isolated canvas components, typed color/Boolean/Number outputs, legacy versions, state/typography examples, a mapped SQLite counter total, and a 28-step workflow. Its source, component definition, list schema and workflow are separate editable files. MCP verification stages a two-file button-style/list-field change, runs a 29-step candidate workflow and checks apply/undo and owner preservation. This expands control accuracy; native equivalence remains a comparison task.

## Classic labels and shapes

The simulator now uses audited templates for these control versions:

| Control | Audited versions |
| --- | --- |
| Label | 2.3.0, 2.3.1, 2.3.2, 2.5.1 |
| Rectangle | 2.0.0, 2.1.0, 2.1.1, 2.1.2, 2.3.0 |
| Circle | 2.0.0, 2.1.2, 2.3.0 |
| Star | 2.0.0, including star6, star8 and star12 variants |

`static/classic-display.json` retains archive hashes and source links at Microsoft's pinned PowerApps-Tooling commit `630e6973e5c81ddc196283cde26dd696d619d6c7`. Both shared include-properties and inline OpenAjax declarations were inspected. Versioned defaults include Label line height, padding, wrapping, live announcements and phone/web dimensions. Shared properties with no recoverable default use explicit host fallbacks. Other versions and variant names retain located unsupported diagnostics.

Labels support typed presentation properties, `Live.Off/Polite/Assertive`, `Overflow.Hidden/Scroll` and `TextRole.Default/Heading1/Heading2/Heading3/Heading4`. Heading semantics do not change typography. Scrollbars require Wrap and fixed height; AutoHeight uses Python measurement and retains the previous height while the label or an ancestor is hidden. Visibility changes and restart recalculate it. Stable caption nodes retain keyboard focus and scroll state during updates. Normal, hover, pressed, disabled and focused visuals use evaluated colors, borders, typography and alignment. These behaviors follow [Microsoft's Label reference](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-text-box).

Shapes render local SVG rectangles, ellipses and stars from server geometry, with fill states, border styles and preserve-aspect-ratio settings. Authored TabIndex determines button versus image/decorative semantics; its native default is -1. Mouse selection remains possible without a tab stop, and nonnegative TabIndex allows Enter/Space activation. Shapes do not support SetFocus; screen-level Labels do, subject to the existing native focus restrictions. Shape Color/Rotation/Text and Label AccessibleLabel are not invented from unrelated COMMON properties. Unsupported reads and authored properties remain visible; unknown source is preserved. Internal layout treats shapes as having no padding. [Microsoft's shape reference](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-shapes-icons) and the shipped templates distinguish these contracts from Icon properties.

Font metrics, font units/theme replacement, exact SVG inner/outer/focus geometry, the star's inner radius, native announcement timing and Studio paste acceptance still need comparison. AutoHeight uses approximate character widths, not browser measurements or native font shaping. Deprecated `IsErrorMessage=true` is explicitly unsupported; configure Live in new source. The simulator never rewrites imported formulas to make these cases pass. The older fictional gallery fixture's unsupported Label AccessibleLabel was removed; imported projects were not changed.

Create the public comparison app:

```sh
python -m powerapps_sim.fixtures projects/classic-display --kind classic-display
python -m powerapps_sim --import projects/classic-display
```

It contains two isolated DisplayPanel components, typed callbacks and outputs, heading/live/scrolling labels, interactive shapes, a hidden-height scenario, a mapped SQLite snapshot list and a 30-step workflow. The MCP regression stages a two-file styling/snapshot change and mapped schema field, checks a 31-step candidate, applies it and verifies undo restores source/schema/data. The browser checks keyboard activation, focus, native pointer states, hidden height retention, scrolling, typed collections and editing a fractional mapped value. Isolated workflows preserve the open owner's runtime, cached dependencies, source and edited records.

## Modern Link controls

`ModernLink@1.0.0` supports evaluated Text/URL, LinkAppearance.Default/Subtle, Wrap/AutoHeight, font and border styling, padding, accessibility labels/language, and Edit/View/Disabled states. Dimensions, padding and alignment defaults follow [Microsoft's Modern Link reference](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-control-link). Strong enum mode retains LinkAppearance identity. Text accepts compatible scalar conversions; aggregate values and incorrect property types report errors. Both URL and Url source spellings are preserved; authoring both creates a located ambiguity diagnostic. Removed properties and unverified versions/variants remain in source and report Unsupported.

Python evaluates and validates the destination. The browser uses that returned destination for native keyboard/pointer navigation. Empty URLs are inactive. The local policy permits HTTP/HTTPS/mailto/tel; relative URLs and unverified protocols report Unsupported, and unsafe protocols or malformed web destinations report Validation. No URL fetch occurs during evaluation. View shows plain text; Disabled removes navigation and tab entry. Inspect mode selects the control without opening its destination. AutoHeight uses approximate local text measurement. Native palette/font geometry, underline defaults, exact safe-protocol allowlist and window targeting still require Studio comparison. Modern Link OnSelect/Select/Reset/SetFocus are not inferred from undocumented behavior.

Create the fictional comparison project:

```sh
python -m powerapps_sim.fixtures projects/links --kind links
python -m powerapps_sim --import projects/links
```

Its two isolated LinkCard components expose typed callbacks and output properties. The 28-step workflow checks appearance changes, mode gates, independent edits, reset, mapped bookmark writes, injected save failure and retry. Bookmarks has 13 fields, including a Choice-shaped Style. The AI/MCP candidate edits the screen and component source, narrows the URL length to 500, tests French/Decimal/strong-enum behavior, applies the change and restores source/schema/data with undo. All data is fictional. The destination parameter defaults to `http://127.0.0.1:8765/static/link-target.html`; update it in Simulation settings when launching on another port. Browser verification uses its matching local port.

Preview width/height inputs now retain unapplied drafts across live refresh until Resize succeeds. This keeps responsive testing usable while values continue to update.

## Fluent V8 rating controls

`FluentV8/Rating@1.5.1` has its own versioned contract. The source is Microsoft's [pinned input-controls solution](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mdainputcontrols/MDA_InputControls_Solution_1_0_0_4.zip). The bundled `static/fluent-rating.json` retains all 22 native property descriptors, two event descriptors and the archive checksum. Twenty-one properties are supported; hidden `PCFTeamsTheme` remains visibly unsupported. The native template marks **Value as authored/bound and resettable**, with literal Value 0, Max 5, Size 20, Width 320 and Height 36 defaults. The unknown X/Y and DisplayMode defaults use documented simulator approximations.

The server evaluates Value formulas, tracks user edits, resets to the current formula, invalidates stale input tokens, commits values before typed callbacks, and isolates component instances and gallery rows. Forms retain pending edits after failed saves and expose Updates/LastSubmit using list field mappings. The control supports AccessibleLabel, AcceptsFocus, TabIndex, four logical paddings, Size, and text-valued CheckedFill/UncheckedFill/HoverFill/DisabledFill properties. Authored ModernRating Default/Step/Icon/ReadOnly/Reset properties are reported as unsupported and preserved in exports.

Radio-style keyboard and fractional-star presentation use Microsoft's [pinned Fluent UI React implementation](https://github.com/microsoft/fluentui/blob/6e52576d457f0ca13225ea2712e0db7bd1c27e28/packages/react/src/components/Rating/Rating.base.tsx): Right/Down increase, Left/Up decrease, Home/PageUp select one, and End/PageDown select Max. Selecting the star already indicated by the rounded-up Value preserves a fractional bound value. Browser focus moves to the selected star after server updates. Keyboard edits run OnChange; pointer selections run a changed-value OnChange followed by OnSelect. That wrapper event order is a **local simulator choice**, not a verified native Power Apps observation.

```sh
python -m powerapps_sim.fixtures projects/fluent-rating --kind fluent-rating
python -m powerapps_sim --import projects/fluent-rating
```

This fictional fixture separates screen and component YAML, SQLite/list definitions and the 19-step workflow. It includes independent rating components, typed callback collections, reactive values, resets, translated labels, a mapped list gallery and an editable form. Its workflow seeds its own isolated dataset and leaves the owner's source, records and runtime untouched. At 400 pixels the components and form stack; the lower form remains usable through scrolling.

Native property metadata establishes supported names/types/defaults, but does not establish native wrapper runtime behavior. Zero/negative/out-of-range rendering, fractional Max, theme resolution, precise star geometry, native reset/event timing and Studio clipboard acceptance remain unverified. The simulator clamps displayed bound values into 0..Max, requires a positive whole Max, caps rendering at 1,000 stars and uses approximate colors. Classic Rating is still unsupported. Physical Windows and Python 3.11–3.13 verification remain open.

Next compatibility work should compare component reset and event ordering with recorded native observations, then recover additional versioned control contracts. The shared authoring service and optional MCP adapter already support revision-checked source/list changes, isolated candidate workflows, apply and undo. Broader AI edits should continue through that service while expanding workflow coverage; live SharePoint integration remains a separate optional adapter.

## Toolbar commands

`Toolbar@2.0.4` is recovered from Microsoft's [pinned input-controls solution](https://github.com/microsoft/PowerApps-TestEngine/blob/a497d6c19880d5a4496127ec9c20d682a8cb38c9/samples/mdainputcontrols/MDA_InputControls_Solution_1_0_0_4.zip). Bundled `static/toolbar.json` retains all 33 native property descriptors and the OnSelect event. It supports 22 inputs and the read-only Selected/SelectedItems outputs. The native PfxDefaultValue for Items supplies four commands; it is retained literally. Native Width 280, Height 55, Padding Medium, Alignment Horizontal and Layout `Icon before` defaults are retained. Unknown X/Y, DisplayMode and TabIndex defaults use explicit simulator approximations.

Items are a table of records with ItemKey, ItemDisplayName, ItemDisabled, ItemVisible, ItemIconName, ItemIconStyle, ItemAppearance and ItemTooltip fields. Regular/Filled icons use bundled Fluent glyphs. Python commits the chosen record before invoking OnSelect, including typed component events that create mapped Choice records or navigate. Repeated clicks invoke the command again. Disabled/hidden items and disabled/view/hidden ancestors block interaction. Tokens reject events after item/default/source/reset changes. Duplicate keys, malformed fields and unsupported icons disable affected items while preserving healthy commands and neighboring instances. These are local validation and interaction rules; native wrapper runtime timing has not been recorded.

Rendering follows [Fluent 2 toolbar guidance](https://fluent2.microsoft.design/components/web/react/core/toolbar/usage): labeled command groups, buttons with accessible labels, a single keyboard entry point, arrow/Home/End navigation, disabled-item skipping and an overflow menu instead of wrapping commands. Overflow buttons invoke the same Python path as visible commands. Icon-only commands retain accessible names and tooltips. Size, padding, colors, fonts, menu placement and precise native focus behavior remain approximate.

The native descriptors for authored dataset field bindings (the eight Item* properties on the control itself) and hidden PCFTeamsTheme are retained but visibly unsupported. Canonical fields in Items records are supported; field-binding syntax and theme behavior are not invented. Authored selection outputs, OnChange, Reset and unknown versions/properties report unsupported diagnostics. Reset(control) is supported independently of an authored Reset property. DefaultSelectedItems matches ItemKey against current Items; a command click replaces it with one selected record. Native multiple-default ordering, selection retention, blank/range behavior, enum paste syntax, reset/event ordering and Studio clipboard acceptance still need native comparison.

```sh
python -m powerapps_sim.fixtures projects/toolbar --kind toolbar
python -m powerapps_sim --import projects/toolbar
```

The fictional fixture separates two-screen YAML, component YAML, list schemas/SQLite and its 19-step workflow. Two labeled component instances retain separate history and selection, expose typed collections, translate labels, create fictional notes, reset independently and navigate. At 300 pixels the panels stack and overflowing commands remain accessible through the menu. Notes use mapped Title/State fields with editable Choice values. Stored workflows run on isolated copies and preserve the open owner's source, records and runtime.

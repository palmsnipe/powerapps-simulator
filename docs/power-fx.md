# Power Fx reference

[Documentation index](README.md) · [Project README](../README.md)

Implemented formula contracts, host profiles, and their known limits. Examples use repository-relative paths; detailed control and component contracts have separate guides.

## Temporal, numeric, table and lifecycle host profiles

Date, DateTime, and Time are now distinct immutable runtime values rather than text. Typed UDF aliases, component inputs/outputs/parameters, connector fields, Defaults, Patch, and form LastSubmit retain those types. Comparisons promote dates/times and parse text where needed; arithmetic uses day offsets, preserves fractional date offsets and hidden Time day overflow, and supports Date + Time. Constructors, TimeValue, Hour/Minute/Second, default Text formatting, temporal table coercions, and typed Blank arithmetic are covered. Browser events and SQLite/JSON exports still use ISO values.

**Simulation settings → Numeric date conversions** explicitly selects the host convention. The default **canvas-milliseconds** follows [Microsoft's canvas data-type documentation](https://learn.microsoft.com/en-us/power-platform/power-fx/data-types): Value(Date(1970,1,1)) is zero, date/time numeric values use milliseconds, and numeric date Text masks interpret Unix milliseconds. **powerfx-days** reproduces the selected open-source engine cases using serial days from 1899-12-30. Arithmetic day offsets do not change with that setting. This does not implement browser-local timezone or DST behavior; offsets supplied in ISO timestamps are retained and compared as instants.

Create the fictional component/form comparison project independently of any imported app:

```sh
python -m powerapps_sim.fixtures projects/temporal-check
python -m powerapps_sim --import projects/temporal-check
```

The creation command refuses to overwrite existing files. Source is in powerapps_sim/examples/temporal.pa.yaml, with a separate fictional list schema in temporal-lists.json. The fixture has two isolated date components, an action and a typed DateTime callback, a pure caption function, reset behavior, a mapped Date field, a DateTime appointment, and form submission events. Automated checks cover English/French captions, changes to defaults, empty required dates, failed saves retaining edits, successful saves, persistence after reopening, and browser focus. Source exports contain no simulator settings or database definitions.

For a manual Studio comparison, copy the component and screen source plus the separate App formulas into a disposable app and configure an Events list with Title, Due date (Date), and Appointment (DateTime). Check that advancing one component leaves the other unchanged, resetting restores its seed, callbacks carry DateTime, date input and form LastSubmit retain the expected calendar day, failed writes retain edits, and French captions follow Language(). Actual control/property paste acceptance and Studio observations remain unverified; record discrepancies separately from the local tests.

**Simulation settings → Number arithmetic** keeps **Float** as the canvas default. An optional **Decimal** host uses bounded base-ten numbers (96-bit coefficient, scale up to 28) and exact literal parsing. `Value` follows the selected host, `Float` selects binary floating point, and `Decimal` is available in Decimal mode. Number aliases and typed component/UDF contracts follow the host; mixed Float/Decimal arithmetic promotes to Float. Conversion, rounding, aggregates, numeric text/Boolean operands, conditional result coercions and overflow errors are covered. This follows [Microsoft's numeric type documentation](https://learn.microsoft.com/en-us/power-platform/power-fx/data-types), which distinguishes canvas Float from Decimal hosts. Decimal mode is an explicit comparison tool and does not claim that canvas Studio uses Decimal. Restart after changing modes so startup variables are recreated.

Exact Decimal values use `{"$decimal":"9007199254740993.25"}` at JSON/API boundaries to avoid JavaScript rounding. Local columns declared `{"type":"number","format":"decimal"}` persist that shape and hydrate typed Decimal values; ordinary SharePoint-style number columns remain Float. This is separate simulator schema configuration, never added to exported Power Apps source. Use text inputs plus `Value(Self.Text)` for exact Decimal entry: native browser number inputs and layout pixels use Float.

Create the independent numeric comparison fixture:

```sh
python -m powerapps_sim.fixtures projects/numeric-check --kind numbers
python -m powerapps_sim --import projects/numeric-check
```

Its Power Apps source is in powerapps_sim/examples/numeric.pa.yaml; fictional exact-column metadata lives separately in numeric-lists.json. Two isolated components exercise typed Number actions, callbacks, pure caption functions and reset. The form saves values beyond JavaScript's exact integer range without losing digits, retains edits after injected failures, and restores exact typed values after reopening. Switching the fixture to Float demonstrates the `.1 + .2 = .3` host difference without changing the source. Do not configure this exact column as a SharePoint number column and expect identical precision.

AddColumns, ShowColumns, DropColumns and RenameColumns accept records as well as tables, preserve untouched error cells, validate column names/collisions, and return copies. AddColumns evaluates each new field in the original row scope; reference another added field by nesting calls. Modern column identifiers and legacy literal names are accepted. Closed schemas survive empty tables, and concrete runtime fields are validated when static schemas are incomplete. These rules follow [Microsoft's table-shaping documentation](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-table-shaping).

Sort and SortByColumns keep Blank keys last in either direction. SortByColumns supports dynamic text column names, multiple sort keys, and a single-column custom order table; unmatched values retain their relative order after matched values. Sorting propagates observed key errors while preserving unrelated cell errors. FirstN/LastN accept Blank and numeric-coercible counts; Index is one-based and reports invalid bounds. Sorting provides deterministic basic English string ordering, not full culture-specific ICU collation.

Create the independent table/component comparison fixture:

```sh
python -m powerapps_sim.fixtures projects/tables-check --kind tables
python -m powerapps_sim --import projects/tables-check
```

Its source is in powerapps_sim/examples/tables.pa.yaml; fictional list schemas and seed records are separate in tables-lists.json. Two isolated components receive an explicit data-source Table input and expose shaped/sorted gallery outputs. Filtering and ordering one instance leave the other's inputs unchanged; typed Record functions and selection callbacks preserve projected fields. Increasing a selected amount writes SQLite, recalculates both outputs, and retains selection by row identity. Browser tests also verify focus during filtering. Source exports exclude schemas, seed records and simulator settings. Manual Studio comparison still needs an equivalent Drafts list and verification of control/property paste acceptance.

Len, Lower, Upper, Trim, TrimEnds, Abs, Round, RoundDown and RoundUp accept single-column tables and produce a `Value` column. Other input column names are accepted; use ShowColumns to extract one field from a wider table. Typed empty tables retain their result schemas; untyped `[]` or `Table()` cannot supply the required input column. Blank tables stay Blank, Blank cells use scalar defaults, and untouched Blank/error rows remain rows. Scalar arguments broadcast across rounding tables; scalar errors become cell errors and healthy rows remain usable. Text coercion uses the simulated English/French language. Len counts UTF-16 units (so a supplementary emoji counts as two); full culture-specific Unicode casing is outside this compatibility selection. Typed Table parameters retain their schema even when Blank inside UDFs and component functions.

**Simulation settings → Rounding tables of unequal length** keeps **canvas-zero** as the default. This follows [Microsoft's rounding documentation](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-round): a shorter DecimalPlaces table supplies zero for the remaining numbers. A shorter Number table reports NotApplicable cells for unmatched positions; this undocumented Canvas edge still needs Studio comparison. The optional **powerfx-errors** profile reproduces the pinned open-source engine, which reports NotApplicable for either length mismatch. A Blank table argument returns Blank; an empty typed digits table supplies zero under the Canvas profile. This setting remains separate from exported Power Apps code.

The queue fixture also exposes Lower/Len and Round outputs: normalized names, a pure Table-parameter Measure function, and amounts divided by three with independent digits inputs. Changing the left filter recalculates its names/lengths; list writes update both rounding outputs. Switching the length-mismatch profile displays handled errors in the left component while the fully matched right component remains usable. Browser checks cover the settings switch and restoring the Canvas default. These checks establish local behavior; actual Studio paste acceptance remains manual.

Component data inputs marked `RaiseOnReset: true` now trigger the instance's OnReset when their evaluated values change. Reading a property remains pure. The simulator settles these changes after a behavior chain, coalesces simultaneous input changes per instance, and establishes initial baselines without inventing startup reset events. Explicit Reset runs synchronously. Parameterized callbacks retain host scope; failures in one input are reported while healthy instances remain usable. Recursive reset and Select loops are bounded and diagnosed. This follows the [documented input-change trigger](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/component-behavior#update-onreset-using-custom-property); exact Studio startup/timing and implicit descendant-reset behavior still require manual comparison.

Select queues OnSelect until the caller finishes. Select(Gallery, row, ChildControl) materializes the requested template and runs that child's event with its ThisItem; Select(Parent) then propagates to the gallery. One-based whole-number bounds, gallery child membership, cross-screen selection and direct/indirect self-selection are checked before changing selection. See [Microsoft's Select rules](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-select).

For automatic containers, Python now calculates Width, Height, X and Y using FillPortions, fixed controls, min/max constraints, padding, gaps, visibility, alignment and justification. The browser renders the allocated sizes instead of independently redistributing them. Nested content-sized containers measure children before applying stretch, so ordinary height formulas do not create false dependency cycles. Supported-version responsive defaults follow [Microsoft's DynamicProperties contract](https://github.com/microsoft/PowerApps-Tooling/blob/master/src/PAModel/ControlTemplates/DynamicProperties.cs): nested container/gallery/form/card controls use FillPortions 1, Stretch and minimum 32; leaves use FillPortions 0 and template-sized minimums. Explicit YAML properties take precedence. Complete Studio template/variant defaults, scrollbar geometry, text measurement and themes remain approximate. Wrapped containers now pack rows/columns on the server using fixed sizes and flexible minimums, distribute FillPortions independently per line, and calculate cross-axis stretch/alignment and line-local justification. The CSS flex renderer consumes those allocated sizes. This follows the documented [container Wrap and Fill portions properties](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-horizontal-container); Child Align-in-container overrides are ignored when wrapping, following Microsoft's [documented container restriction](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/build-responsive-apps#known-issues). Exact Studio parent alignment/line stretching and scrollbar gutters still need comparison. Ten new cases cover horizontal/vertical wrapping, min/max/visibility/resize, AutoHeight, overflow, alignment and component lifecycle isolation.

Create the independent lifecycle/layout fixture:

```sh
python -m powerapps_sim.fixtures projects/lifecycle-check --kind lifecycle
python -m powerapps_sim --import projects/lifecycle-check
```

Its source is in powerapps_sim/examples/lifecycle.pa.yaml; it uses no list data. Two isolated components expose reset counts and parameterized callbacks. Change the left seed, explicitly reset it, queue the second gallery row, and toggle the fixed spacer. The on-screen trace shows behavior order, while captions expose Python's allocated widths. Browser checks compare computed CSS sizes and positions with server values at widths 1000, 460 and 400, including minimum-size overflow. Source exports retain RaiseOnReset and exclude simulator configuration.

Reset Boolean properties are observed after each behavior primitive, so `Set(resetInputs, true); Set(resetInputs, false)` resets inputs even within one behavior chain. Only a false-to-true transition fires; reads remain pure and holding the flag true does not repeatedly discard edits. Gallery template controls evaluate Reset in their row scope. Button.Pressed follows mouse and keyboard presses, including release outside the button. Reset does not invent OnChange events. See [Microsoft's Reset examples](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-reset). Exact held-flag timing still needs a Studio comparison.

ResetForm runs OnReset synchronously after discarding edits and changing New mode to Edit. LastSubmit survives resets and mode changes. SubmitForm and ResetForm have no effect in View mode. Failed submissions retain edits and run OnFailure; successful submissions expose LastSubmit to OnSuccess. Error clears on EditForm/ResetForm or successful submission. Changing the authored Item releases a saved-record override, so choosing another record after saving cannot leave the form pinned to the previous item. Unsaved returns false when inputs or selections return to their defaults, and settles changed defaults before reading dirty state. Mode-only Edit/View calls retain pending edits in this simulator; exact Studio treatment of pending edits and null Item/card evaluation still needs comparison. These rules are based on [Microsoft's form functions](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-form) and [form properties](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/control-form-detail).

Create the independent form lifecycle fixture:

```sh
python -m powerapps_sim.fixtures projects/forms-check --kind forms
python -m powerapps_sim --import projects/forms-check
```

It contains two clearly fictional records, Title/Amount cards, New/Edit/View/Reset/Save actions, a Reset pulse, a hold-to-reset button, record switching and an event trace. Source and fictional schema/records are separate in `powerapps_sim/examples/forms.pa.yaml` and `forms-lists.json`. Copy/export excludes the latter. The fixture is suitable for a manual comparison against a disposable Drafts list in Studio.

## Power Fx math and component calculations

The engine now supports `Sqrt`, `Exp`, `Ln`, `Log`, `Power`, `Int`, `Trunc`, `Sin`, `Cos`, `Tan`, `Cot`, `Asin`, `Acos`, `Atan`, `Acot`, `Atan2`, `Degrees`, `Radians` and `Pi`. Unary functions accept scalar or single-column tables; `Log` and `Power` also broadcast scalars against tables or pair table rows. Missing paired rows produce NotApplicable cells, while Blank rows, Blank cells and embedded errors remain distinct. `Pi` and `Atan2` are scalar-only; `Atan2(X,Y)` uses the Canvas coordinate order. Numeric text follows the simulated language. These contracts are based on Microsoft's [numerical](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-numericals), [trigonometric](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-trig) and [rounding](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-round) references and pinned engine cases.

`Int` floors and `Trunc` rounds toward zero, retaining Decimal precision when the argument is Decimal. Other math functions produce Float values, including in the Decimal host profile. `^` and `Power` share results and domain errors. Canvas `Trunc` accepts one argument, as the rounding documentation specifies; the open-source engine's optional digits argument is intentionally excluded. Use `RoundDown` for decimal places.

Domain failures remain catchable Numeric/Div0 errors, with source spans and table-cell isolation. Some numerical/trigonometric documentation still describes legacy Blank results; this simulator follows [formula-level error handling](https://learn.microsoft.com/en-us/power-platform/power-fx/error-handling) and the pinned engine's errors. A legacy Blank-return profile is not implemented. Float calculations use Python's math library; last-bit and extreme underflow differences from .NET/Studio remain possible.

The corpus adds **321 selected math cases** from revision `df4ceba5e08220db670c25afead342ce699c50b5`, with upstream expressions, independently decoded literal oracles and documented exclusions. These cases explicitly opt into the pinned [BaseRunner numeric comparison](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestHelpers/BaseRunner.cs#L421): absolute difference below 1e-5 or relative difference below 1e-14. Existing cases retain exact comparisons; Boolean, Blank and error kinds never use numeric tolerance. This does not claim exact bit-for-bit equivalence.

Create `python -m powerapps_sim.fixtures projects/math-check --kind math`, then launch `python -m powerapps_sim --import projects/math-check`. Two independent components expose typed calculation records, a custom pure function, capture actions/events and explicit reset behavior. Its 51-step isolated workflow passes in English and French, covering reactive geometry, callback deduplication, a 13-row/20-column collection, retained numeric error cells and failed/retried SQLite saves. Seventy-seven new backend cases and 321 reference cases pass. Native browser checks verified component input, angle-keyboard focus, recalculation, saved records and horizontal collection scrolling. The corresponding CI browser case is compiled but was not run locally. Actual Studio paste acceptance and calculation observations remain manual.

## Text table overloads and UTF-16 positions

`Left`, `Right`, `Mid`, `Replace`, `Substitute` and `Concatenate` now share scalar and single-column table contracts. Each argument can be a scalar or a typed single-column table, with scalar broadcasting, row pairing and `Value` output columns. Unequal table lengths retain NotApplicable cells; empty typed tables do not observe unused scalar errors. Blank table arguments, Blank cells and error rows remain distinct. Numeric argument roles are checked separately from text arguments. `Replace` adds positional insertion/replacement; `Substitute` handles empty matches without inserting text, uses nonoverlapping occurrences and never rescans replacement text. See Microsoft's [substring](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-left-mid-right), [replacement](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-replace-substitute) and [concatenation](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-concatenate) documentation.

Character positions and lengths use UTF-16 units, matching the pinned .NET reference. Emoji can be split into surrogate halves; recombining those halves with Concatenate restores the original text. Numeric counts/positions use the reference truncation behavior; text/number conversion follows the simulated locale. Invalid positions remain catchable errors with source spans and aggregated conversion failures. The substring documentation still describes legacy Blank behavior for invalid Mid positions; the simulator follows the pinned formula-error cases. Fractional positions below one remain rejected rather than exposing a host substring exception. Exact Studio observations, enum-to-text coercions and legacy Result-column profiles remain unverified.

All **363 cases** in the selected modern-column Left, Right, LeftRightT, Mid, MidT, Replace, Substitute, SubstituteT, Concatenate and ConcatenateT reference files pass against independently decoded literal oracles at revision `df4ceba5e08220db670c25afead342ce699c50b5`. These cases use exact comparisons and an explicit English-US/Float host profile. Fifty-six new backend cases cover UTF-16 slicing/recombination, binding, errors, locale/Decimal/Dynamic conversion, source preservation, component tables, persistence and workflow owner isolation.

Create `python -m powerapps_sim.fixtures projects/text-tables-check --kind text-tables`, then launch `python -m powerapps_sim --import projects/text-tables-check`. Its 49-step isolated workflow passes in English and French with two independent components, typed record callbacks, a pure table-returning function, reset, a 20-column collection, failed/retried mapped SQLite saves and required-field rejection. Native browser checks verify live values, retained focus, callback isolation, transformed gallery rows, saved/edited text and collection scrolling. The CI browser case is compiled and collected but was not run locally. Actual Studio paste acceptance remains manual.

## Unicode search, splitting and character codes

`Find` now measures one-based, case-sensitive positions in UTF-16 units and returns Blank when no match exists. Starting positions, empty needles and scalar/table broadcasts have binding and runtime checks. `Split` accepts scalar text, preserves empty fields and trailing separators, and returns a typed `Value` column. An empty delimiter separates UTF-16 units; an emoji can therefore occupy two rows. `Concat`, `Concatenate` and `&` recombine adjacent surrogate pairs into the original character. Empty tokens are empty Text values, matching the pinned modern-column interpreter cases; older documentation examples use Blank. Sources: [Find](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-find), [Split](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-split).

`Char` accepts codes from 1 to below 256 and truncates fractional values. `UniChar` accepts valid Unicode scalar codes, floors fractional values, and reports NotApplicable for isolated surrogate codes. Both support typed single-column tables, with errors retained in individual cells. `Hex2Dec` accepts up to ten hex characters and uses signed 40-bit two's-complement values; invalid hex reports Numeric. Find returns Float positions, while Hex2Dec follows the selected Float/Decimal host. Sources: [Char/UniChar](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-char), [hex conversion](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-hexdec).

All **279 selected cases** in the pinned Find, FindT, Split, Char, CharT, UniChar, UniCharT and Hex2Dec files pass, including three binding-error expectations. Expected results are independently decoded literal oracles; compiler message wording is not compared. Valid trailing commas in table literals are now accepted. Sixty-nine new backend cases cover the domains, UTF-16 positions, lazy and table errors, type validation, locale/Decimal conversion, components, persistent saves and report/transport encoding. The signed `8000000000` boundary follows Microsoft's documented negative range; the pinned interpreter has a boundary discrepancy outside the selected cases. Dec2Hex now follows documented Canvas truncation; the pinned interpreter discrepancy remains a known gap in its separate reference slice.

Create `python -m powerapps_sim.fixtures projects/unicode-check --kind unicode`, then launch `python -m powerapps_sim --import projects/unicode-check`. Its 58-step isolated workflow passes in English and French with two components, typed callbacks, search functions, empty gallery tokens, a 20-column collection, handled invalid codes, disabled-save enforcement, mapped SQLite writes and failure/retry. Native browser checks verify reactive outputs, independent errors, reset, save recovery, collection scrolling and editable Unicode/numeric list values. All eight sample scenarios also pass in disposable snapshots while preserving the live owner. Actual Studio paste acceptance and visual comparison remain manual.

Report files and Power Fx JSON escape isolated UTF-16 units losslessly. Browser JSON retains those strings. The MCP SDK requires Unicode scalar strings, so structured tool results represent an isolated unit as `{"$utf16":[55356]}`; the integers are the complete string's UTF-16 code units. Ordinary Unicode text stays Text, and this transport representation never enters source or runtime values. MCP resources contain escaped JSON text. The full Unicode scenario is tested over the official SDK's real stdio transport.

## Calendar weeks

`Weekday`, `WeekNum` and `ISOWeekNum` now evaluate scalar Date/DateTime values, localized date text, Blank and numeric dates under the selected date-numeric profile. `Weekday` accepts MondayZero and floors legacy numeric start codes; `WeekNum` rejects MondayZero and fractional codes. Blank start codes become zero for Weekday (InvalidArgument), and Sunday for WeekNum. Strong enum mode requires StartOfWeek identities; legacy mode accepts Excel numeric codes and numeric/text/Boolean coercion. Results retain the selected Float/Decimal host type. Numeric `If` conditions now convert zero to false and other numbers to true, preserving lazy branches and errors.

All **153 cases** in six active pinned Weekday/WeekNum files pass, with independently decoded literal/error oracles. ISO week boundaries additionally match [Microsoft's published examples](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-weeknum). The pinned interpreter keeps ISOWeekNum tests under NotYetReady, so those examples are separate backend checks, not claimed as interpreter executions. Calendar week 54, ISO week 53, leap dates, year boundaries and invalid codes are covered. `WeekNum` and `ISOWeekNum` also accept single-column date tables, including custom column names, typed empty/Blank tables and per-cell errors. StartOfWeek stays scalar; multi-column tables and table start codes report type errors. Table overloads follow the Canvas documentation and await Studio comparison. Weekday remains scalar; use `ForAll` for weekday calculations across records.

Create `python -m powerapps_sim.fixtures projects/calendar-check --kind calendar`, then launch `python -m powerapps_sim --import projects/calendar-check`. Its 35-step isolated workflow passes in English and French, with independent component date pickers, typed function/output/callback records, reset, a 14-row collection and failed/retried SQLite saves. Native browser checks verify Monday-first calendar ordering, typed date entry, date selection, year-boundary recalculation, component isolation, collection inspection and save recovery. The workflow also passes through the official MCP SDK over stdio. Studio comparison and Windows validation remain pending.

The table fixture uses `python -m powerapps_sim.fixtures projects/calendar-tables-check --kind calendar-tables`. Its 49-step workflow covers table-valued component functions/outputs/callback records, separate instance state, error cells, a 14-row/20-column collection and nested week arrays saved to SQLite. It passes in English/French with Float/Decimal result profiles; SQLite numeric fields retain their own connector types. Thirty-six new backend cases cover schema validation, empty/Blank/error tables, scalar start codes, coercion, typed functions and owner preservation. Native checks cover nested list editing, save failure/retry, readable error cells and horizontal scrolling. The selected table and collection sidebar now scroll independently: choosing a lower collection in a small inspector keeps the table visible. Their scroll positions survive live callback updates and pane resizing. A corresponding CI browser regression test is added but was not run locally; native browser checks provide the local evidence. The new scenario is also verified through MCP stdio and both offline bundles.

## Dec2Hex and built-in enum identity

`Dec2Hex(Number [, Places])` supports scalar and single-column table arguments, scalar broadcasting, paired tables, typed empty/Blank tables, numeric/text/Boolean coercion and individual error cells. Values truncate toward zero, fit signed 40-bit bounds and produce uppercase hex. Positive values pad to 1–10 Places; negative values produce ten digits while still validating Places. Too little space, invalid Places and out-of-range numbers report Numeric. The Canvas default deliberately follows [Microsoft's hex conversion contract](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-hexdec), including `Dec2Hex(-3.74) = "FFFFFFFFFD"`. The pinned interpreter floors to -4 instead; this is the sixth known reference gap, not a passing case.

**Simulation settings → Built-in enum handling** selects **Legacy scalar enums** (existing project behavior) or **Strong enum identity**. Strong mode covers ErrorKind, StartOfWeek, TimeUnit, SortOrder, DateTimeFormat and JSONFormat using the [pinned built-in definitions](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Core/Types/Enums/BuiltInEnums.cs). It retains namespace/member/backing values through records, collections, compatible branches and component callbacks. Text conversions use the member name for numeric enums and the backing string for text enums; for example `Text(ErrorKind.Network)` gives `"Network"`, and `Text(SortOrder.Descending)` gives `"descending"`. Explicit Value/Decimal/Float accept number-backed enums. Implicit numeric conversion is permitted for ErrorKind, while Boolean conversion, cross-namespace comparison and unsupported ordered comparisons are rejected. DateTimeFormat can accept a Text branch; TimeUnit/SortOrder cannot accept arbitrary Text in strong enum arguments. DateAdd/DateDiff, Sort/SortByColumns and Text consume their own namespaces. Date pickers consume strong StartOfWeek values. Restart after changing profiles to reinitialize authored variables; profile configuration never enters Power Apps exports.

Variables, component state and collection cells display qualified enum names and their types. HTTP/MCP inspection serializes them as `{"$enum":{"namespace":"ErrorKind","member":"Network","value":23}}`; this representation stays outside source/runtime values. Power Fx JSON now serializes these built-in enums through their backing values; IgnoreUnsupportedTypes retains supported enum fields. Calculated JSONFormat combinations show their backing flags in the inspector. Canvas control enums outside these eight namespaces retain their existing contracts. Full option sets and complete V1/legacy compatibility are still outstanding; Match and MatchOptions now have explicit regex contracts.

The new pinned selection contains **295 cases**: all 74 Dec2Hex cases, all ten strongly typed Find cases, and 211 built-in enum cases with independent literal or binding-error oracles. It adds 294 passes and one documented mismatch. Thirteen relevant enum cases remain outside the selection because they use functions outside this slice or computed/calculated enum oracles lacking independent backing values. The report does not imply coverage of the entire upstream enum suite. Seventy-six new backend tests cover domains, tables, explicit/implicit conversions, type rejection, profile changes, enum table identity, date-picker consumption, component error observation, callbacks and saves.

Create `python -m powerapps_sim.fixtures projects/hex-enums-check --kind hex-enums`, then launch `python -m powerapps_sim --import projects/hex-enums-check`. Its 55-step isolated scenario passes in English and French, with two component instances, numeric/text inputs, a typed pure Encode function, callbacks, reset, a 20-column collection, disabled-save rules and mapped SQLite failures/retry. Component function/action/event errors now propagate to their caller without immediately adding diagnostics: IfError can handle them, while an uncaught consuming control/event reports the error. Native browser checks cover handled failure/recovery, independent components, qualified live enum values, collection scrolling and list editing. The offline bundles include the source/list/workflow fixture, corpus and enum runtime. Actual Studio and cross-platform validation remain pending.

## Datasource error tables

`Errors(DataSource [, Record])` is now a pure property/formula function. It returns Record, Column, Message and numeric Error fields, with the datasource’s typed record schema and logical/display aliases. Failed creates have a Blank Record. A specific existing record filters by ID, so stale field values do not prevent finding its error; passing Blank selects creation failures. Column uses the internal field name, or Blank when no single field caused the failure.

```powerfx
First(Errors(Projects)).Message
CountRows(Errors(Projects, Blank()))
Filter(Errors(Projects, Gallery1.Selected), Error = ErrorKind.MissingRequired)
IfError(Patch(Projects, {ID: 1}, {Title: Blank()}),
    ClearCollect(saveErrors, Errors(Projects)))
```

Patch, Collect, Update/UpdateIf, Remove/RemoveIf, Refresh and SubmitForm share operation boundaries. Starting a later data operation clears that source’s earlier history; row calls inside a batch do not clear each other. Queries, Defaults, Choices and Errors reads preserve it, as do operations on another source or a plain collection. Failed row entries retain snapshots; successful rows can commit while other row errors remain visible. Form validation records affected cards and OnFailure can capture them. Callback data operations start their own history. Error reads remain available even while connector reads are configured to fail.

History is session-local and clears on app restart/dataset reset. It is absent from item storage and Power Apps exports. Local data shows expandable failed records with their column, message and code, using horizontal scrolling. AI `read_list`, `read_runtime` and isolated workflow reports expose the same information without changing it. The Canvas-documented singular EditPermission/DeletePermission/ConstraintViolation enum names are accepted alongside the pinned interpreter spellings.

Create the clean 66-step comparison fixture with `python -m powerapps_sim.fixtures projects/error-check --kind data-errors`, then launch `python -m powerapps_sim --import projects/error-check`. It exercises creation/edit/batch/removal failures, component scopes and callbacks, form validation, recovery and persistent IDs. This follows [Microsoft’s Errors reference](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-errors). Exact connector column spelling, clearing during argument evaluation, conflict/permission responses and form validation timing still need recorded Studio/SharePoint comparisons. The selected reference corpus does not provide an independent Errors datasource oracle; these are local contract/integration tests.

## Record removal and conditional deletion

`Remove` and `RemoveIf` now support collections, global/context table variables, tables nested in mutable records, isolated component state and local SQLite lists. Read-only computed tables and function parameters cannot be mutation targets. Collection records match their complete values; omitted fields are not filters. Remove deletes the first duplicate by default, or every duplicate with `RemoveFlags.All`. Record arguments and a sole table of records are supported. Logical/display column names are retained, and incompatible record shapes fail before writes.

```powerfx
Remove(local, First(local));
Remove(copy, Filter(copy, Enabled), RemoveFlags.All);
RemoveIf(book.Rows, Amount >= 20, !Enabled);
Remove(Projects, Table({ID: 1}, {ID: 2}));
```

Remove captures arguments before planning writes. Repeated requests for the same record select the same original first match once. A missing record reports NotFound while valid planned deletions still commit; multiple errors remain available to IfError/AllErrors. RemoveIf evaluates pure Boolean conditions in each row scope, short-circuiting false/Blank conditions. Predicate errors leave the table unchanged. Local source operations scan all records rather than the preview’s 500-row display limit. Source identity, invalid IDs, read-only lists and injected read/write failures remain checked.

SQLite tracks each list’s highest allocated ID, so deleting its last or highest row does not reuse an ID. Allocation history is included in authoring conflict checks. Migration initializes the counter from surviving IDs; IDs deleted before tracking cannot be recovered. Explicit dataset replacement/reset restarts the counter for repeatable fictional scenarios. Tracking metadata never appears in exported Power Apps source or item JSON.

These behavior functions return the modified table, following [Microsoft’s Canvas Remove/RemoveIf reference](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-remove-removeif). The pinned interpreter’s direct Remove host return can be Void; its 33 selected oracle cases observe the table or errors after the operation. Precise Canvas predicate-error timing, source-backed collection identity, duplicate request planning and nested-table matching still need recorded Studio comparisons. Recursive nested-table matching is a local extension. Live SharePoint/delegation behavior remains outside this release.

Create the clean fixture with `python -m powerapps_sim.fixtures projects/remove-check --kind remove`, then launch `python -m powerapps_sim --import projects/remove-check`. Its 62-step isolated workflow covers duplicate/table matching, copied/nested values, independent components, callbacks, mapped list fields, missing records, failed writes/retry and persistent IDs. A directly bound datasource gallery is now accepted by workflow selection. The fixture explicitly authors `Select(Parent)` on its gallery child; omitted gallery-child defaults and background selection remain control-fidelity follow-ups.

## Partial updates, pure merges and batch Patch

`Patch(record, change, ...)` merges records without modifying the arguments. Later fields override earlier fields, including replacing a lazy error with a healthy value. Pure merges are available in properties, named formulas and pure component/app functions. Overlapping fields follow strict aggregate contracts; nested records are replaced as fields rather than recursively merged. Blank records are ignored, and an all-Blank merge remains Blank.

Behavior Patch supports mutable collections, global or screen-context table variables, and tables nested in mutable record variables. Component variables/collections remain isolated. Set, UpdateContext, Navigate context and Collect assignments copy nested value trees, so editing one table does not change its earlier copies. Read-only computed tables, named formulas and function parameters cannot be mutation targets. Plain collections match the complete base record and update only the first duplicate; a missing match appends the change fields with other columns Blank. Defaults adds a new row using the target's declared columns.

Local list writes retain internal/display-name mappings and validate partial changes without blanking omitted fields. Source-backed records carry identity/default lineage internally; these attributes never appear as Power Fx record fields, stored JSON columns or exported source. A deleted ID fails instead of silently creating another record. IDs must be positive integral values, and generated ID/audit fields are protected. Key-and-update two-argument Patch requires records derived from the target source; a plain key literal requires the separate base/change overload. Unsafe Text-to-number/Boolean/date changes require explicit conversion.

```powerfx
Patch(local, First(local), {Amount: 5});
Patch(book.Rows, First(book.Rows), {Amount: 7});
Patch(Projects, Filter(Projects, Status.Value="Draft"),
    ForAll(Filter(Projects, Status.Value="Draft"), {Cost: Cost+5}));
Patch(Projects, Table(Defaults(Projects), Defaults(Projects)),
    Table({Title:"Fictional A",Cost:5}, {Title:"Fictional B",Cost:6}))
```

Batch base/change tables must have equal lengths. Length and record-shape errors occur before writes; Blank rows are skipped. The first observed row error stops later writes while preserving earlier successful writes. The result contains the patched rows in order. This follows Microsoft's [Patch reference](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-patch) and the upstream interpreter's [mutation implementation](https://github.com/microsoft/Power-Fx/blob/main/src/libraries/Microsoft.PowerFx.Interpreter/Functions/LibraryMutation.cs). Connector identity, coercion, generated fields and precise partial-failure timing still require recorded Canvas/SharePoint comparison. Operations run over all local records; live delegation remains excluded.

Create the fixture with `python -m powerapps_sim.fixtures projects/patch-check --kind patch`, then launch `python -m powerapps_sim --import projects/patch-check`. Its 63-step isolated scenario verifies pure merges, copied/nested tables, component actions/functions/callbacks/reset, mapped SQLite records, partial failure, retry, batch creation and keyed writes. Explicit fictional seed records keep it repeatable after live data edits. Source, list configuration and workflows remain separate. Browser checks also verify live variable inspection and editing newly created records.

## Record replacement and conditional updates

`Update` replaces a matching record; omitted editable fields become Blank. Collections match the entire old record, update the first duplicate by default, and support `RemoveFlags.All`. `UpdateIf` evaluates Boolean conditions in each row scope, applies the first matching change record, and retains fields that were not supplied. Both functions return the modified table and run only in behavior formulas. Aliases, nested scopes, logical/display column names, component-local collections and scalar argument conversions are supported. The implementation follows [Microsoft's Update/UpdateIf reference](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-update-updateif); matching and connector details still need Studio comparison.

SQLite replacements require the existing ID to be reaffirmed. Omitted managed audit values are retained; explicit read-only values must agree with the saved record. Required fields, options, relationships, lengths and complex shapes are validated before each row is saved. `UpdateIf` protects identity/audit fields. A failed row retains its prior record while other valid rows can commit; `IfError` receives the collected errors. There is no implicit insertion when `Update` fails to find its old record. Local operations examine all saved records, independently of the 500-row preview limit; live SharePoint delegation behavior is outside this implementation.

Create the fixture with `python -m powerapps_sim.fixtures projects/update-check --kind update`, then launch `python -m powerapps_sim --import projects/update-check`. Its 40-step isolated workflow covers collections, complete replacement, two independent component instances, callbacks, mapped SQLite fields, required-field errors, injected write failures and retries. Source, list configuration and workflows remain separate. Nested-table matching, precise partial-failure timing and connector-generated field rules remain manual comparison points; the selected upstream interpreter corpus does not cover these new functions. `Errors()` now exposes local list-operation history; collection removal and Patch overloads are described above.

## JSON formats and enum serialization

Strong enum mode gives JSONFormat its pinned Text-backed identity. Compact has an empty backing string; same-namespace `&` and scalar/table `Concatenate` combinations retain JSONFormat identity. Mixed Text combinations produce Text and fail the strong JSON option contract. Text conversion, branch/table typing and equality preserve enum semantics. Legacy scalar projects retain their existing flag representation.

Behavior-only JSON encodes ErrorKind/StartOfWeek numbers and TimeUnit/SortOrder/DateTimeFormat/JSONFormat backing strings, including nested records, tables and component callbacks. Calculated flags encode their combined string. Record keys use UTF-16 ordinal ordering, matching the [pinned JSON visitor](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Json/Functions/JsonFunctionImpl.cs). Readable inspection still retains enum identity; JSON output contains no simulator tags. Icon/other Canvas option sets remain subject to their documented unsupported contracts.

```powerfx
Set(flags, JSONFormat.IndentFour & JSONFormat.FlattenValueTables);
Set(payload, JSON({Kind: ErrorKind.Network, Weeks: [1, 2, 3]}, flags));
// Payload contains Kind: 23 and Weeks: [1,2,3].
```

```sh
python -m powerapps_sim.fixtures projects/json-enums-check --kind json-enums
python -m powerapps_sim --import projects/json-enums-check
```

The two-instance fixture exposes format selection, editable values, independent captures/reset, typed enum event records and persisted JSON payloads. Its 45-step workflow passes in English/French and Float/Decimal modes on disposable runtimes. Conflicting flags are caught, failed writes retain the payload, and retry persists it. Its live collection has 20 columns with horizontal scrolling and expandable nested flags. Current evidence includes 101 independent cases from the pinned built-in-enum/JSON reference files, 125 new backend tests, native browser interaction and a compiled browser CI regression. The automated browser suite was not run locally. Fresh core/MCP installations exercise the fixture and real stdio workflows; Studio comparisons remain pending.

## Validation

```sh
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

Browser verification uses Python Playwright during development only:

```sh
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest tests/test_browser.py -q
```

Browser tests start their own server on a free local port. The sample integration test uses `POWERAPPS_SAMPLE` when set, otherwise the original local download path, and skips if neither exists. Tests cover language semantics, typed functions, nested scopes, reactivity, source preservation, malformed drafts, component state/functions/actions/defaults/callbacks, lexical type checks, selected reference conformance, stable gallery identity, SQLite shapes/mappings/validation, persistent writes, form failures, import/export, browser editing, scrolling, and focus preservation.

## Regex validation and extraction

`IsMatch`, `Match`, and `MatchAll` execute in Python, with `Match` and `MatchOptions` namespaces. Patterns are authoring-time constants, assembled from literal strings, `&`, `Concatenate`, enum members, and literal `Char`/`UniChar` calls (including literal `Hex2Dec`). Legacy IsMatch also accepts pure constant string expressions. Dynamic pattern variables are diagnosed. Input changes recalculate validation; lazy branches and IfError retain normal Power Fx semantics.

Simulation settings select the regex profile independently of number and enum settings:

| Profile | IsMatch default | Captures and characters |
| --- | --- | --- |
| Canvas (default) | Complete | UTF-16 units; SubMatches includes numbered and named captures; legacy Email/Hyphen constants |
| Power Fx engine legacy | Contains | Legacy captures and UTF-16 units, for pinned engine comparisons |
| Power Fx V1 | Contains | Unicode scalar matching; unnamed groups capture only with NumberedSubMatches; named fields without a SubMatches column |

Match and MatchAll default to Contains in all profiles. StartMatch is a one-based UTF-16 position. Missing Match returns Blank; MatchAll returns an empty typed table. Unmatched optional captures are Blank. Legacy capture ordering follows .NET (unnamed first, then named); repeated named groups return their last capture. Named fields can replace FullMatch/StartMatch/SubMatches, with their resulting field types. Matching has a one-second timeout surfaced as ErrorKind.Timeout. Strong Match concatenation accepts Text backing values; strong MatchOptions requires its own namespace. These values retain their type in component state, collection inspection and JSON output.

V1 supports Unicode categories, supplementary character escapes, multiline Unicode line breaks, DotAll and FreeSpacing options, named/numbered captures, portable nested capture validation, backreferences and bounded lookbehind. This is a supported subset of the portable dialect. V1 inline flags and character classes follow the portable grammar: forbidden constructs produce Type diagnostics. Legacy lookbehind, complex groups, complemented character classes, octal and Unicode-block escapes retain Unsupported diagnostics. V1 rejects ambiguous optional/empty/alternating captures when quantified, and references to captures that may be absent. Legacy authoring-time DotAll/FreeSpacing options produce a profile error; the upstream legacy engine's dynamic-option loophole is intentionally not reproduced. Python's regex extensions are not silently accepted. Case folding across all scripts and additional legacy engine edge cases still require work. Studio acceptance and direct Canvas observations remain manual checks.

```sh
python -m powerapps_sim.fixtures projects/regex-check --kind regex
python -m powerapps_sim --import projects/regex-check
```

The fictional fixture covers two isolated components, immediate email validation, named extraction and nested capture tables, English/French labels, invalid-save blocking, SQLite failure/retry, reset and a 20-column collection. Its 44-step workflow runs on disposable snapshots and preserves the owner's records/runtime. The new corpus adds 226 independent literal/error oracles in both number modes from six [pinned Microsoft regex reference files](https://github.com/microsoft/Power-Fx/tree/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases). Semantics are based on the [Power Fx contracts](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-ismatch), [binder](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Core/Texl/Builtins/Match.cs), and [runtime](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Interpreter/Functions/LibraryRegEx.cs).

Next compatibility priorities are the remaining portable regex syntax and scoping rules, broader host contracts, and direct Studio comparison fixtures. The existing MCP adapter exposes these same server-side functions and isolated workflows; no separate AI execution engine is needed.

## Power Fx string interpolation

The lexer/parser now support `$"...{expression}..."` with nested interpolated strings, expressions, records, tables, quoted identifiers (including reserved words), and comments inside expression islands. Doubled braces/quotes preserve literal text. Embedded nodes retain source positions, and the ordinary AST visitors discover their variable/control dependencies, behavior calls, UDF recursion and cycles. Malformed/empty islands report parser errors; definition recovery tracks interpolation boundaries. The [Microsoft syntax contract](https://learn.microsoft.com/en-us/power-platform/power-fx/data-types) and [pinned lexer](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Core/Lexer/TexlLexer.cs) guide this implementation.

Evaluation stays in Python and uses the host's existing text conversions for numbers, Boolean values, dates/times, Dynamic scalars and enum values. Embedded record/table/control/function/icon values are diagnosed. Multiple segments evaluate in order and aggregate their errors; IfError/lazy branches continue to work. The [pinned IR translator](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Core/IR/IRTranslator.cs) returns a single embedded value after coercion: the simulator consequently preserves typed Blank and strong enum member identity for a single segment. Multiple combinable enum segments preserve their namespace as Concatenate does. A literal prefix forces Text unless the enum allows coercion from Text backing values (Match).

```powerfx
$"Project {ThisItem.Title} · {Text(ThisItem.Amount, "0.00", Language())}"
$"{{draft}} · {$"{CountRows(localRows)} records"}"
$"^{Match.MultipleDigits}$"
```

Reactive labels, typed component functions, actions/event parameters, named formulas, gallery scopes, captures and persisted list records can all use interpolation. Regex authoring constants accept interpolated constant string segments; V1 rejects numeric/function segments outside its restricted constant syntax, while the legacy IsMatch contract permits pure constant expressions. Formula source is preserved; there is no translation to Python f-strings or JavaScript templates.

```sh
python -m powerapps_sim.fixtures projects/interpolation-check --kind interpolation
python -m powerapps_sim --import projects/interpolation-check
```

The fixture has two isolated components, live title/quantity inputs, localized typed formatter functions, event callbacks, saved snapshots, failure/retry, reset and a 20-column collection with nested strings/records. Its 41-step scenario runs in English/French and Float/Decimal modes on a disposable snapshot. Export/round-trip tests preserve interpolation source and exclude simulator configuration. The corpus adds **88 reference cases**: every expression in [StringInterpolate.txt](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/StringInterpolate.txt) plus the interpolation regex cases in IsMatch and its V1-enabled/disabled variants, each in both number modes. Oracle strings are decoded independently of this interpreter. Power Fx text-first templates and additional host-specific coercion edge cases remain outside this milestone; direct Studio acceptance is still a manual check.

## Portable regex capture scopes

The V1 profile now analyzes nested groups and alternation before execution, using the [pinned Microsoft GroupTracker rules](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Core/Texl/Builtins/Match.cs). Valid repeated nested groups and named/numbered backreferences execute through the same Python formula runtime as other properties. Invalid patterns retain their source and produce Type diagnostics on the pattern argument. Forward/self references, possibly absent captures, external references to lookaround captures, duplicate/invalid names and ambiguous quantified capture groups are rejected. NumberedSubMatches retains its separate contract; it cannot be mixed with named captures/references in V1.

V1 positive/negative lookbehind supports bounded expressions up to 250 UTF-16 units, including bounded references to earlier captures. Unbounded quantifiers/references, nested lookbehind, captures inside lookbehind and quantifiers on lookarounds or containing groups are rejected. Capture names are limited to 62 UTF-16 units and group nesting to 31 levels. Option anchors do not consume that source nesting budget. Canvas/engine-legacy profiles keep their existing capture rules and still diagnose unsupported legacy lookbehind. MatchAll now computes UTF-16 offsets once and reuses the input representation for captured slices.

The new corpus adds **786 independent reference cases** in both number modes: every expression in [MatchFunctions_CaptureQuant.txt](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/MatchFunctions_CaptureQuant.txt), plus the capture definitions/depth/backreferences and bounded-lookbehind sections of [MatchFunctions_Limited.txt](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/MatchFunctions_Limited.txt). Oracles come from Microsoft's literal/error results, not this simulator. Additional tests cover source locations, static capture-table types, option anchors, supplementary-character limits, lazy/error behavior and 1,500-match UTF-16 positions.

```sh
python -m powerapps_sim.fixtures projects/regex-groups-check --kind regex-groups
python -m powerapps_sim --import projects/regex-groups-check
```

This fictional fixture extracts repeated words and numbers with named backreferences and negative lookbehind. Its two components retain separate capture collections and send typed callbacks to the host. The 58-step workflow verifies filtering, Unicode positions, resets, persisted captures, failure/retry and 20-column inspection in English/French and Float/Decimal modes while preserving the owner's state. Native browser checks verify focus, independent captures, saved records, failed-write preservation/retry and nested collection tables; an automated browser regression is added but was not run locally. The MCP adapter exposes the new semantics through existing formula/workflow tools. Direct Studio comparison remains unverified.

Inline options and character-class validation are now covered by the next fixture below. Next: broader control fidelity and recorded Studio comparison cases. The selected reference corpus is still a subset; passing it does not establish arbitrary Power Apps compatibility.

## Portable inline flags and character classes

V1 supports one initial `(?imnsx)` option block, using the [pinned portable grammar](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Core/Texl/Builtins/Match.cs). Flags affect IgnoreCase, Unicode multiline anchors, DotAll and FreeSpacing; `n` is redundant with V1's default explicit capture and conflicts with NumberedSubMatches. Repeated flags, later blocks, scoped flags and disabling flags are rejected. Inline and line comments are removed before execution, preserving escaped spaces/hash characters and spaces/hash characters inside classes. FreeSpacing follows .NET's Unicode separator/newline set, excluding Python's additional information separators.

Classes validate range endpoints/order, literal hyphens, reserved punctuation, escapes, empty classes and Unicode categories before compilation. Positive classes can combine literal/category atoms with `\D`, `\W`, and `\S`; their execution uses .NET-shaped Unicode sets. These complements and `\P` are forbidden inside negative classes. Portable classes reject supplementary characters/surrogates, backreferences and anchors; literal syntax punctuation must be escaped. V1 also rejects octal/engine-specific escapes and lazy exact quantifiers. An IgnoreCase guard bug that incorrectly rejected ASCII `s`/`S` is fixed, including positive/negative classes and hexadecimal escapes. Legacy profiles retain their own rules.

The corpus adds **1,104 independent reference cases** in both numeric modes: every remaining case from [MatchFunctions_Limited.txt](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/MatchFunctions_Limited.txt) and all cases in [MatchFunctions_Comments.txt](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/MatchFunctions_Comments.txt). Earlier capture references are not duplicated. Oracle integers/strings/records come from the source files. Decimal encoding preserves the [Len NumberOrDecimal contract](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Interpreter/Functions/LibraryText.cs) separately from Match's Number-valued StartMatch. Additional tests exercise syntax guards, source locations, Unicode sets, ASCII case folding, lazy/error handling and scoped component functions.

```sh
python -m powerapps_sim.fixtures projects/regex-syntax-check --kind regex-syntax
python -m powerapps_sim --import projects/regex-syntax-check
```

The fictional fixture has two components with a free-spacing/commented extraction formula, case-insensitive backreferences, complemented separator classes, typed Separators/IsNumber functions and typed callbacks. Its 77-step workflow checks English/French and Float/Decimal behavior, filtered captures, independent state/reset, mapped SQLite saves, failure/retry, persisted JSON and 20-column inspection. Native browser checks cover focus, mixed-case extraction, independent callbacks, save failure/retry, editable saved records, wide/nested collections and the isolated workflow; an automated browser regression is added and compiled, but was not run locally. The same formula/workflow operations are checked through the installed MCP SDK over real stdio. Actual Studio comparisons, physical Windows execution and Python 3.11–3.13 execution remain unverified.

The next compatibility priority is broader control/component behavior and recorded Studio comparisons; complete Unicode case folding and host-specific regex edge cases remain open. The active project goal continues beyond this regex milestone.

## App.OnError and formula error provenance

App.OnError has its own source editor and is available through source export and the AI/MCP facade. The handler receives FirstError and AllErrors, including numeric Kind, Message, Source, Observed and optional Details. Stored error values retain their origin until a consuming rule observes them. IfError and IsError contain caught failures; record/table cells remain independent. Unhandled behavior chains and ForAll aggregate failures while preserving completed side effects. A handler can log, notify or rethrow errors; reporting does not replace failed values. These semantics follow Microsoft's [error handling guide](https://learn.microsoft.com/en-us/power-platform/power-fx/error-handling), [App.OnError documentation](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/object-app) and [error record contract](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-iferror).

Python defers handlers until the current event or preview evaluation finishes. Property failures report once while continuously unchanged, then report again after a healthy evaluation or restart. Handlers execute sequentially; Canvas documents concurrent handlers, so concurrency and exact observation timing need Studio comparison. Qualified screen/component/row paths identify simulator rules; native Studio naming parity is unverified. Unhandled errors use a default notification, with consecutive identical messages suppressed. Handler failures cannot recursively invoke App.OnError. Structural cycles and unsupported capabilities remain visible as simulator diagnostics even if their values are caught.

Source offsets follow the originating formula, while diagnostics identify the consuming member and preserve Source/Observed metadata. Error records, including Decimal-valued Details, serialize through the shared runtime format. AI runtime reads expose a bounded error report history without executing queued handlers. Source exports contain only authored Power Apps code.

```sh
python -m powerapps_sim.fixtures projects/app-errors-check --kind app-errors
python -m powerapps_sim --import projects/app-errors-check
```

## Population statistics

StdevP and VarP accept numeric scalar arguments or a table with a numerical formula. Table formulas retain ThisRecord, As aliases, nested scopes and mapped list fields. Blank values do not contribute; an empty table or scalar arguments without nonblank values produce a catchable Div0 error. A typed Blank table stays Blank. Numeric text/Boolean coercion follows the pinned engine cases. Unrelated record-cell errors remain unobserved; a table aggregate stops at the first consumed row/formula error, while scalar argument errors aggregate. Both functions return Float even in the optional Decimal comparison mode. Welford accumulation follows the pinned Microsoft interpreter and avoids subtracting squared means. Nonfinite results/intermediates report Numeric errors.

The contracts come from Microsoft's [aggregate documentation](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-aggregates), [pinned StdevP tests](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/StdevP.txt) and [pinned VarP tests](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/VarP.txt). All 30 expressions have independently decoded expected values and run in Float/Decimal modes, adding 60 selected reference cases. Compiler/source semantics and errors are tested separately. The local runtime evaluates complete SQLite tables; this does not reproduce live delegation limits.

```sh
python -m powerapps_sim.fixtures projects/statistics-check --kind statistics
python -m powerapps_sim --import projects/statistics-check
```

A coordinated authoring check adds a Priority Choice column together with a filtering formula and an app button that marks a draft High. It validates and runs the combined candidate before applying it, then undoes both source and schema changes. Its 34-step scenario checks that excluding a high-priority draft recalculates the component statistics. This exercises the shared AI service and installed MCP transport on fictional local data; it does not connect an AI model or synchronize live SharePoint.

## Aggregate Blank, error and type contracts

Sum, Average, Min and Max omit Blank values after argument coercion. Sum/Min/Max return Blank when no nonblank value remains; Average reports a catchable Div0 error. A typed Blank table stays Blank, including for Average; an empty table is evaluated as an empty aggregate. Table formulas can handle error rows with IfError, leave unrelated error cells unobserved, and stop at the first consumed error. Scalar argument/conversion errors aggregate into AllErrors. The same scoped error-row handling and typed Blank-table rule now apply to VarP/StdevP. Accumulated Sum/Average and VarP/StdevP range errors are reported after iteration so a later row error retains precedence.

Min/Max preserve Date, DateTime and Time results. Their scalar V1 contract uses the first argument's type; the table overload uses the projection type. Sum/Average likewise select Float/Decimal from the first argument or projection. DateAdd now retains its input temporal type in binding and evaluation, so date-valued projections remain dates. Date values retain any time parts introduced by DateAdd for Hour and aggregate comparisons, although their wire representation remains a calendar date. Calendar/numeric coercions follow the selected explicit date-number profile. Time comparisons retain duration days, including negative durations; the existing Time wire display shows the clock portion. No separate legacy V1-disabled host is implemented.

The additional corpus contains every expression from pinned [Average](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/Average.txt), [Sum](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/Sum.txt), [MinMax](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/MinMax.txt) and [MinMax V1](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/MinMax_V1Compat.txt) in Float/Decimal modes, plus the Float-specific file. Expected values are independently decoded from literal upstream oracles; Power/Sqrt and their table unions retain Float output in Decimal mode. Four selected cases retain explicit known-gap status because [Canvas Date/DateTime](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-date-time) adds 1900 to years below 1900 whereas the pinned interpreter uses absolute years. Tests also cover typed functions, reactive collections, localized coercion, isolated statistics components, mapped saves and failed-write recovery. Actual Studio type/default/event/paste acceptance and physical Windows execution remain unverified.

## Single-column counts

`Count` counts numeric values in a single-column table. `CountA` counts present values, including empty text, false and zero; `CountRows` counts rows. Use `ShowColumns` to project a wider record table. Both single-column functions skip Blank rows/cells, return zero for typed Blank/empty tables and propagate the first observed row/cell error. They return the host's Number or Decimal type. Untyped empty literals, multi-column inputs and nonnumeric Count columns produce binding diagnostics. Nested record/table cells remain present without consuming their internal errors.

Mixed table literals now retain the first compatible scalar column type, matching the pinned reference cases. For example, `CountA([0,""])` is 1 after numeric coercion, whereas `CountA(["",Blank()])` is 1 because empty text is present. SQLite text writes follow the existing SharePoint-style blank normalization; component tables can retain empty text independently. Queries run over local records without live delegation.

The [Microsoft count documentation](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-table-counts) and complete pinned [Count](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/Count.txt) / [CountA](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/CountA.txt) cases provide independent expectations. The 122 added cases cover both Float and Decimal hosts.

Create the fictional comparison app with `python -m powerapps_sim.fixtures projects/counts-check --kind counts`. Its 20-step isolated workflow exercises two component scopes, typed functions, callback records, resets, mapped blank writes and failed-save recovery. The source remains editable Power Apps YAML and contains no simulator configuration.

## Row counts and predicate coercion

`CountRows` includes Blank rows and ignores errors inside record fields, but propagates the first error row. `CountIf` evaluates predicates in record scope, short-circuits after false/Blank, and propagates the first consumed error. A predicate such as `IsError(ThisRecord)` can inspect error rows without consuming them. Numeric predicates use zero/nonzero Boolean coercion. Text predicates accept case-insensitive true/false; empty text becomes Blank, while whitespace-padded or invalid text reports InvalidArgument. Typed Blank/empty tables return zero. Both functions retain the host's Number/Decimal return type; CountRows also keeps its Dynamic-array overload.

These contracts follow the pinned [CountRows cases](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/CountRows.txt), [CountIf cases](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/CountIf.txt), [interpreter](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Interpreter/Functions/LibraryTable.cs) and [Boolean coercion implementation](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Interpreter/Functions/LibraryUnary.cs). All 53 CountRows/CountIf expressions run in Float and Decimal modes, adding 106 independent reference cases. Error-row counting and CountIf error aggregation previously differed from the reference; those behaviors are now corrected.

Create the comparison app with `python -m powerapps_sim.fixtures projects/row-counts-check --kind row-counts`. Its 36-step workflow covers typed component functions/callbacks, adjustable scoped predicates, zero-valued samples, mapped Blank writes, error-row injection/recovery, failed saves and independent resets in English/French and both numeric modes. Local queries evaluate complete SQLite records; live Dataverse caches and delegation are outside this simulator.

## Scoped Filter / LookUp queries

`Filter` preserves a Blank source as Blank, while a real empty table returns an empty table. Its predicates run in row scope and can inspect error rows with `IsError(ThisRecord)`; false predicates discard those rows, while consumed predicate errors remain error-valued result rows. Canvas's multiple-predicate signature retains ordered short-circuiting. `LookUp` returns the first matching record or reduced value, stops at the first consumed predicate error, and evaluates its reduction only for the selected row. It retains its Boolean predicate contract.

An `As` alias replaces implicit fields and the current scope's `ThisRecord` in scoped functions. Use `row.Amount` inside `samples As row`; outer named/implicit scopes, global disambiguation and gallery `ThisItem` remain available. Three earlier test formulas relied on implicit fields or `ThisRecord` under an alias; their clean formulas now use the declared alias. Imported source is never rewritten by this correction.

The pinned [Filter cases](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/FilterFunctions.txt), [LookUp cases](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/Lookup.txt), [interpreter](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Interpreter/Functions/LibraryTable.cs) and [scope binder](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Core/Functions/FunctionScopeInfo.cs) provide 142 additional selected cases in Float and Decimal modes. The selection includes all expressions in FilterFunctions.txt/Lookup.txt and shared two-argument cases. V1-only rejection of multiple Filter predicates is explicitly excluded because Canvas supports them; V1 untyped-Blank scope rejection is not selected because this host retains Canvas's legacy Blank-source signature. This is a selected reference comparison, not a complete engine suite.

Create the fictional comparison app with `python -m powerapps_sim.fixtures projects/queries-check --kind queries`. Its 31-step scenario covers isolated component functions/events, scoped thresholds, gallery selection, mapped list writes, inspectable error rows, save failure/retry and independent resets. Scenarios seed disposable snapshots and preserve edited owner data/source/runtime. Non-Boolean Filter coercion, Dataverse views, delegation/caches, exact native query scheduling and Studio component reset/default/event/paste comparisons remain incomplete or unverified.

## Search contracts and mapped columns

Search resolves column identifiers and legacy string column names through the local list's internal/display-name metadata. Encoded SharePoint names work when present in that mapping; the simulator does not guess missing relationships. Retained columns keep their aliases through AddColumns/ShowColumns/DropColumns. Dropped or renamed fields cannot bind through an obsolete alias. Text-column and query validation includes empty sources and empty queries.

Search evaluates source and query arguments eagerly, combines their errors, preserves typed Blank sources, and returns the source records for an empty query. A nonempty query skips Blank rows and consumes row/column errors in order. A matching earlier column stops the scan before a later erroneous cell. Unsearched cells remain intact. Existing English/French case-insensitive substring behavior and Turkish/Azeri I handling remain; complete .NET culture-specific Unicode casing is unverified. Both column-syntax profiles are accepted intentionally rather than reproducing a Studio version switch.

The new independent reference file adds 72 cases from both pinned Microsoft Search expression files, in Float and Decimal modes. This compares independently encoded expected values with the Python engine, rather than running Microsoft's .NET engine. The clean fixture exercises isolated component inputs/functions/callbacks, Unicode text search, logical/display/legacy column names, inspectable error rows, reactive SQLite writes, failed saves/retry and a repeatable 29-step scenario under English/French and Float/Decimal settings. The original erroneous sample import remains separate.

```sh
python -m powerapps_sim.fixtures /path/to/search-demo --kind search-queries
python -m powerapps_sim --import /path/to/search-demo
```

Contracts are checked against [Microsoft's Search reference](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-filter-lookup) and the [pinned Search tests](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/Search.txt). Actual Studio clipboard acceptance, native component lifecycle timing and full Power Fx compatibility remain unverified.

## Grouped table mappings and UDF schemas

GroupBy and Ungroup now resolve both current identifiers and retained legacy literal-column names through explicit list metadata. Grouping keys retain their aliases in the outer record; remaining fields retain theirs inside the nested table. Flattening merges the two schemas and their unambiguous aliases. Removed columns cannot bind through stale metadata, and conflicting logical aliases require an explicit physical column name. Real field overlaps and duplicate grouping keys remain errors, including on empty typed tables.

Typed app functions now compare physical record fields instead of counting logical/display aliases twice. Genuine extra fields still fail restrictive UDF validation. Nested grouping, collection copies, typed function conversions and table shaping retain the order metadata used for ordinary GroupBy/Ungroup round trips; metadata is not a record field or exported Power Apps code. Non-key error cells remain inspectable until consumed. Key/row errors, scalar nested columns and invalid source contracts retain diagnostics.

Seven independently encoded expectations cover the CityPopulations grouping, filtering, totals and order examples from [Microsoft's grouping documentation](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-groupby), under English/French and Float/Decimal profiles. They live in examples/grouping-reference.json. The pinned open-source corpus has no GroupBy/Ungroup expression files, so these are documentation comparisons, not native engine test cases or Studio observations; the native selected corpus count remains unchanged. Complex grouping-key equality, Blank-record ordering and exact error scheduling remain unverified against Studio.

The grouping fixture provides two isolated aggregate components, mapped source records, typed summarizing/flattening functions, scoped gallery callbacks, error-row inspection, grouped collection snapshots and persistent save failure/retry. Its repeatable 29-step scenario runs on disposable project snapshots and preserves edited owner data and runtime state.

```sh
python -m powerapps_sim.fixtures /path/to/grouping-demo --kind grouping
python -m powerapps_sim --import /path/to/grouping-demo
```

## Mapped table-shaping contracts

`AddColumns`, `ShowColumns`, `DropColumns`, and `RenameColumns` resolve existing SharePoint internal/display names through explicit schema metadata. Identifier parameters and retained legacy literal names use the same contract in the binder and evaluator. New names stay authored names. Alias collisions and repeated drop/rename targets are rejected even for empty or typed-Blank sources. A logical self-rename retains the existing display key. Actual renames/drops remove their aliases, including after collection capture or reintroducing a plain column with the old display name. Source records, list schemas and SQLite values remain unchanged by shaping.

The fictional `grouping` fixture now projects mapped columns, calculates a trimmed note, drops the original note and renames the result before passing data into two typed components. List edits recalculate component input/output tables and aggregates. The stored note retains its original whitespace. This pipeline is ordinary exported Power Fx; mapping and order metadata stay outside record fields and YAML.

The reference corpus adds 160 comparisons with independently decoded Microsoft expected values and compiler rejections, covering previously unselected cases from nine pinned shaping files in Float/Decimal modes. Four cases are explicitly Decimal-only, including an explicit Float result inside a Decimal table. The two native display-name mutation-fixture cases remain excluded because their host uses logical record keys; local mapped-column regressions exercise the simulator's display-key storage separately. Compiler wording/severity, native connector display-name serialization and Studio component lifecycle/paste behavior remain unverified. See [Microsoft's Canvas table-shaping reference](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-table-shaping) and the [pinned RenameColumns binder](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Core/Texl/Builtins/RenameColumns.cs).

## Power Fx casing and typed component titles

`Proper` accepts text-coercible scalars and single-column tables, returns Text/Value results, preserves lazy error cells and typed Blank/empty tables, and rejects invalid column shapes before execution. `Lower`, `Upper`, and `Proper` now use simple Unicode case mappings in the supported English/French profiles. This avoids Python's expanding uppercase for sharp S/ligatures and contextual final sigma. Apostrophes, marks, punctuation, compatibility digraphs and supplementary letters follow the pinned interpreter's lowercase-then-TextInfo scan. Unsupported culture tags produce a visible error; the machine locale is not used.

The selected corpus adds all 13 pinned Proper expressions in Float and Decimal profiles, with independently decoded literal expected results. Existing Lower/Upper cases remain selected. See [Microsoft's casing reference](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-lower-upper-proper), [pinned interpreter casing](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Interpreter/Functions/LibraryText.cs), and [.NET's TextInfo word scan](https://github.com/dotnet/runtime/blob/v8.0.0/src/libraries/System.Private.CoreLib/src/System/Globalization/TextInfo.cs). Unicode/ICU table versions and exact Studio casing remain unverified. The documentation's numeric-address example says `789 Sw 39th #3b`; the pinned TextInfo scan implemented here produces `789 Sw 39Th #3B`. That discrepancy is not silently treated as a passing documentation comparison.

The fictional `casing` project includes two isolated typed components, immediate text outputs, callback history, normalized gallery rows, explicit independent resets, mapped SQLite titles and raw/normalized snapshots. Its 29-step workflow verifies failed saves/retry on a disposable snapshot while preserving edited owner source/data/runtime. Original casing remains stored until an authored source-write button changes it. Exports contain ordinary `Proper`, `Lower`, `Upper` and typed Power Fx definitions; Python casing logic and simulator metadata are excluded.

```sh
python -m powerapps_sim.fixtures /path/to/casing-demo --kind casing
python -m powerapps_sim --import /path/to/casing-demo
```

## Volatile formulas and observed dependencies

`Rand()`, `RandBetween(bottom,top)` and `Shuffle(table)` now work in Power Fx. A property or named formula that executes a volatile operation retains its result across unrelated changes. When an input it actually read changes, it evaluates again. Behavior calls draw afresh. The same mechanism retains `GUID()`, `Now()` and `Today()` within property/named rules; explicit simulated clock/timer changes remain inputs to clock rules.

Python tracks reads of control/App properties, variables, collections, list rows, list definitions, simulated users and parameters. Dependent rules compare returned values before consuming another draw. Lazy branches contribute their executed reads. Errors remain errors, including after a volatile call, and failed list reads can recover after the injected failure is cleared. Ordinary rules retain the existing broad invalidation caches; this is a first dependency layer around volatile rules rather than a complete incremental engine.

Simulation settings accept an optional `random_seed` integer (or `null`). It is simulator configuration, excluded from exported Power Apps source. With an explicit seed, restarting repeats random streams within this Python runtime. Property/named rules have separate streams from direct behavior/expression evaluations so drawing in one instance does not consume another instance's stream. This is an simulator replay policy; Microsoft PRNG sequences and shuffled row order are not reproduced. Direct expression evaluation, including AI formula evaluation containing a direct `Rand()`, is a fresh evaluation. Reading runtime inspectors does not draw values.

Create an independent fictional project:

```sh
.venv/bin/python -m powerapps_sim.fixtures /path/to/empty/volatile-project --kind volatile
.venv/bin/python -m powerapps_sim --import /path/to/volatile-project
```

The fixture contains two isolated typed components, independent sliders, stable property draws, fresh component Function/Action/Event draws, a shuffled gallery, mapped SQLite cards and a 14-step isolated workflow. The running development example is at `http://127.0.0.1:8830/`. It uses `random_seed: 20261010`; source formulas contain only Power Apps code.

`Rand` remains Float in the Decimal host. `RandBetween` accepts inclusive integer bounds, Blank-to-zero numeric coercion and the reference engine's ceiling fallback when a fractional interval contains no integer. `Shuffle` preserves duplicate rows, field names, aliases and lazy error cells, returning a separate table. Native comparison inputs and expected literals/invariants come from [pinned Rand tests](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/Rand.txt) and [pinned Shuffle tests](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/Shuffle.txt). Property lifetime follows [Microsoft's volatile-function contract](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-rand).

Dependency granularity is conservative for whole records, tables and gallery instance records: changing an unread field in an observed record/table can recalculate the enclosing rule. Direct internal rendering helpers, especially grid/form cells evaluated outside a property rule, still need the same dependency boundary and dedicated lifecycle checks. Exact Studio scheduling, implicit reset/default timing, native gallery virtualization, custom component output timing and Microsoft random-number distributions remain unverified. Next work should extend this boundary to specialized rendering paths and expose read-only recalculation/dependency information to the editor and MCP client.

## Formula lifetimes in rows, forms and dependency inspection

Classic table and modern grid cells now retain volatile results by control, property and record identity/duplicate occurrence. Rendering a table, selecting a row or reading a selected column shares that result. Gallery template decoration and selector/tab display formulas have the same boundary. A rule that reads `ThisItem` or its gallery alias observes the live record; a constant `Rand()` does not redraw because an unused record field changed. Nested record scopes remain separate from the enclosing form item.

Authored property evaluation, form-item settling and explicit input-default checks now share a formula result. This prevents the same volatile default or random form Item from drawing twice during a preview update. Input state reads observe individual state keys. Unrelated actions preserve drafts; deliberate resets restore the current default. Source edits, host profile changes and actually observed input changes still cause recalculation.

Open **Dependencies** in the inspector to filter cached rules, expand their source, and inspect values, observed inputs, evaluation/reuse counts and the most recent recalculation reason. The pane supports horizontal scrolling and resizing. Refresh and live observation read existing information; they do not render the app, execute behavior or draw random values. The revision-aware AI facade, HTTP `/api/dependencies`, MCP `read_dependencies` tool and `powerapps://dependencies` resource expose the same paged snapshot (1–500 rules per page). Source exports exclude this information.

The report covers **evaluated volatile rules and their consumers**. It is not a complete static dependency graph or trace of every pure formula. Each changed observed record is conservative as a whole; field-level dependency granularity and exact Studio scheduling remain open. Cached rules can include previously evaluated rows that are no longer visible. Read the running-source revision note after editing; apply/restart semantics are unchanged.

A fictional comparison fixture provides side-by-side tables, row-specific random values, aliased gallery decoration, a random form Item, persistent mapped budgets and a 17-step workflow:

```sh
python -m powerapps_sim.fixtures /path/to/empty/reactive-project --kind reactive-cells
python -m powerapps_sim --import /path/to/reactive-project
```

## Field member dependency precision

Direct member chains rooted in names and control properties now observe their returned value rather than every intermediate record. `ThisItem.Amount`, gallery aliases, nested variable fields and component input fields can retain volatile results when an unread field changes. A dependency probe repeats pure member access; it preserves volatility inherited from another cached property rule. Behavior expressions continue to execute normally. Records remain ordinary Power Fx records, preserving aliases, source metadata and lazy error cells.

The Dependencies inspector and MCP snapshot label the observed member path. Whole-record/table consumers retain whole-value dependencies. Query pipelines and constructed lexical records can still carry broader upstream dependencies; form Item settling and gallery/property wrapper signatures also remain conservative. This is finer observation for member access, not a complete incremental engine or a claim about exact Studio scheduling.

A fictional comparison app combines classic/modern tables, forms and two isolated components with nested record inputs, field-specific outputs, a deliberate whole-record output and typed callbacks:

```sh
python -m powerapps_sim.fixtures /path/to/empty/field-project --kind field-reads
python -m powerapps_sim --import /path/to/field-project
```

## Query result and row dependency precision

Pure table queries now expose their returned value as a dependency boundary. A title edit can recheck `Sum(Cards, Amount)` without redrawing an enclosing `Rand()` when the total stays the same. `LookUp(Cards, ID=1).Amount` observes the projected field; consumers of the complete returned record/table still observe all fields. Scoped query formulas retain volatile row values while their read fields remain unchanged.

This covers the existing Filter/LookUp, table shaping/grouping, search, sorting, aggregation/statistics, counting, First/Last/Index, ForAll/Concat/Distinct and table-construction paths. Row formula boundaries apply to predicates, projections, calculated columns and sort keys. Nested aliases, `ThisRecord`, surrounding `ThisItem` and source disambiguation keep their record scopes. Rows remain ordinary Power Fx records, preserving source-name mappings, Blank and error cells. Behavior expressions execute each time, including list writes and component callbacks.

Rows with IDs use the ID and duplicate occurrence; rows without IDs use their position. Duplicate objects and Blank rows have distinct occurrences. A removed row leaves the active query result; retained cached entries may remain visible in the read-only report until restart. Plain lexical records and typed function arguments remain conservative signatures: changing an unread field in those values can still recalculate an inner query. Query producers may recheck their full input table; this is precision around volatile results rather than full incremental execution or SharePoint delegation. Exact Studio recalculation scheduling remains unverified.

**Dependencies** and the existing `read_dependencies` MCP tool/resource include evaluated volatile query and row rules with expression spans, source, row identity, inputs and evaluation/reuse counts. Reading the report never probes a formula or consumes a random draw. Nested scope keys use bounded hashes; the UI displays expressions and row identities instead of recursive keys. Formula spans are character offsets within the associated property or App.Formulas text.

Create a fictional comparison app:

```sh
python -m powerapps_sim.fixtures /path/to/empty/query-project --kind query-reads
python -m powerapps_sim --import /path/to/empty/query-project
```

Its two components compare sums, positive-row counts, per-row draws and whole-table consumers. Title/amount edits, typed callbacks, a modern grid and mapped SQLite snapshots have a repeatable 19-step workflow. These source files contain Power Apps formulas only; seeded random settings and dependency instrumentation stay in simulator configuration/runtime.

## Validate and declared list ranges

`Validate(DataSource, Column, Value)` checks one column without requiring values for unrelated columns. `Validate(DataSource, OriginalRecord, Updates)` validates the merged record. Column identifiers, legacy quoted column strings, internal/display names, record variables and scoped callbacks are supported. Valid values return Blank; constraint failures return Text; formula errors remain catchable errors. This follows [Microsoft's Validate contract](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-validate).

Validation uses the local list metadata: required values, lengths, numeric bounds, declared complex shapes, configured choices and lookup relationships. Collections have no connector validation metadata and return Blank for well-formed inputs. Validation does not write, clear the connector error table or consume simulated operation failures. A valid result can still be followed by a failed save. Metadata and lookup targets participate in dependency observation, including when validation is used with volatile expressions.

List writes, record imports, data cards, form submission and Validate now share declared range checks. Numeric minimum/maximum values must be finite and ordered. Local date/date-time fields can use ISO bounds; date-time comparisons normalize offsets. Invalid bound definitions fail visibly. These definitions remain simulator configuration and are excluded from clipboard/source exports. Available constraints and error wording can differ from a live connector. DataSourceInfo's collection/default and field-type contracts are covered below; live connector parity remains unverified.

Disabled modern buttons use neutral disabled colors instead of retaining an enabled palette through inline styles. Correcting the validation input restores the enabled appearance. This is approximate Fluent presentation; it does not change app formulas or enable disabled workflows.

Create a comparison project:

```sh
python -m powerapps_sim.fixtures projects/validation --kind validation
python -m powerapps_sim --import projects/validation
```

The fixture has two isolated score editors, typed callbacks, live validation feedback, a 13-column mapped SQLite list and a 24-step workflow covering invalid values, endpoints, resets, save failure/retry and error-table preservation. The MCP test changes both source files and narrows the maximum from 100 to 75, validates the candidate in French/Decimal mode, then verifies apply/undo restores original source/schema/data. Exact native component lifecycle scheduling remains an open comparison; this milestone does not claim a timing fix.

## DataSourceInfo and collection metadata

`DataSourceInfo` supports column DisplayName/Required/MaxLength/MinValue/MaxValue and source Read/Create/Edit/DeletePermission/AllowedValues queries. Column calls require a column; source calls reject one. Unknown fields and malformed selectors have located diagnostics. Modern column identifiers and legacy literal strings resolve internal/display mappings. Strong enum mode retains DataSourceInfo member identity; legacy mode also accepts literal selector strings. Calculated selectors/column expressions report an explicit unsupported/type diagnostic.

DisplayName uses authored display mappings and falls back to the column name. Required uses local required-field metadata. Numeric limits apply to numeric columns; text lengths apply to Text columns. Absent or inapplicable limits are Blank, so local ISO date bounds never masquerade as numeric limits. Float/Decimal inference agrees with returned numeric values. Collections and computed tables expose metadata-free defaults: column-name display labels, false Required, Blank limits/AllowedValues and true permission defaults. Typed empty collections retain their schema for column validation.

Metadata reads do not fetch rows, write, clear Errors or consume injected failures. Schema and writable changes are observed by dependent properties, including formulas with volatile terms. The existing local writable gate supplies edit/create/delete flags; read remains true because local lists have no per-user read gate. AllowedValues remains Blank because that permission metadata is unavailable. This is local simulation, not Microsoft permission discovery. [Microsoft's DataSourceInfo reference](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-datasourceinfo) states that Microsoft Lists does not support the function and native permission checking is limited to Dataverse. Native metadata propagation through computed tables, exact Studio selector acceptance and timing remain unverified.

Create the fictional comparison project:

```sh
python -m powerapps_sim.fixtures projects/metadata --kind metadata
python -m powerapps_sim --import projects/metadata
```

The fixture reuses the ranged-score list and isolated component editors, adding metadata-driven required labels and a 30-step workflow. Tests cover English/French and Float/Decimal modes. The MCP candidate changes the display mapping to Progress score and the maximum to 75, updates affected source, verifies the scenario, applies it and restores source/schema/data with undo. No original sample source or access formula is repaired.

## Offline Power Fx locales

Value/Decimal/Float and Text now use pinned Babel 2.18.0 CLDR data for additional language, region and script profiles. Supported operations include local decimal/group/currency/percent symbols, Unicode decimal digits, regional grouping, localized month/weekday names and AM/PM, Gregorian numeric/named/field-unit date parsing, and date/time enum rendering. Existing English/French profiles retain their earlier outputs. Lower/Upper/Proper now apply Turkish and Azerbaijani dotted/dotless-I mappings to scalars and table overloads; other profiles retain simple one-character mappings. The .NET [TextInfo ICU implementation](https://github.com/dotnet/runtime/blob/v9.0.0/src/libraries/System.Private.CoreLib/src/System/Globalization/TextInfo.Icu.cs) distinguishes Turkic casing. Unicode/ICU version parity and culture collation remain unverified. Custom masks remain Power Fx masks, including separate format-language and result-language tags; no formula is translated into Python or JavaScript. This follows the general contracts in [Value](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-value), [Text](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-text) and [DateValue/TimeValue](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-datevalue-timevalue).

For example, Value("123,456","es-ES") produces 123.456, while an en-US override produces 123456. Text(Date(2016,1,31),"dddd mmmm d","es-ES") produces domingo enero 31. DateTimeValue("2022年07月28日 19:34:03","ja-JP") parses the localized Gregorian date. Unknown tags and calendar extensions report Unsupported; malformed tags report BadLanguageCode. CLDR profiles do not establish full Power Apps culture parity. Exact native calendar/currency symbols, patterns, collation/casing, arbitrary date grammar and timezone/DST still need comparison. Date and time operations use the simulator's Gregorian host rules.

Text parsing now maps two-digit years 00–49 to 2000–2049 and 50–99 to 1950–1999, following GetAdjustedCultureInfo in the [pinned Microsoft interpreter source](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Interpreter/Functions/LibraryDate.cs). This is separate from Canvas Date/DateTime constructors, which retain their documented relative-year behavior.

```sh
python -m powerapps_sim.fixtures projects/locales --kind locales
python -m powerapps_sim --import projects/locales
```

The fictional comparison project has two isolated locale components with typed callbacks, live collection values and a mapped Amounts list. Its 18-step workflow covers reactive language changes, percent conversion, invalid-input gating, independent values and numeric persistence. The AI/MCP candidate changes screen and component source plus the list schema, tests French/Decimal/strong-enum behavior, applies and undoes the change. Source, list definitions and tests remain separate. Babel's pure Python wheel and data are included in both offline packages; runtime needs no internet or OS locale installation. Re-running setup reinstalls the bundled packages, so updates work even while the development version stays at 0.1.0. Existing project source and database files are preserved by the verified macOS setup path; Windows execution remains unverified locally.

## Calendar and Clock namespace functions

`Calendar.MonthsLong()`, `Calendar.MonthsShort()`, `Calendar.WeekdaysLong()` and `Calendar.WeekdaysShort()` return single-column Text tables named `Value`. Months start with January; weekdays start with Sunday. Month selectors use stand-alone names, so Russian January is `январь` rather than the genitive date-form `января`. `Clock.IsClock24()` returns a Boolean. `Clock.AmPm()` and `Clock.AmPmShort()` return Text tables, including typed empty tables for 24-hour locales. These zero-argument pure calls work in component outputs, named formulas, typed functions, collection initialization, and ordinary table queries. They follow the documented [Calendar/Clock contracts](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-clock-calendar) and the pinned compiler's [Calendar](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Core/Texl/Builtins/Calendar.cs) and [Clock](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Core/Texl/Builtins/Clock.cs) return-type/arity declarations. The pinned interpreter does not implement these functions, so their documented English examples are separate from the native reference corpus.

The simulated language drives reactive selector tables and clock information. Changing language does not rerun App.OnStart or translate previously collected records. Names and 12/24-hour preference come from pinned Gregorian CLDR data. AM/PM labels use uppercase localized designations; short labels use the first UTF-16 unit. Exact Studio culture preferences, abbreviations and short-designation rules need native comparison. Alternate calendars and OS/user format overrides remain outside this profile. Babel 2.18.0 resolves aliases in inherited dictionaries; the simulator now isolates each locale's backing data to prevent month names leaking between languages. The isolation adapter depends on the pinned Babel version and has interleaving regression coverage.

```sh
python -m powerapps_sim.fixtures projects/calendar-selectors --kind locale-tables
python -m powerapps_sim --import projects/calendar-selectors
```

This fictional project has two independent components with classic month and modern weekday dropdowns, typed callbacks, reset buttons, a live history collection, an App.OnStart snapshot, and mapped local calendar records. Its 21-step workflow checks selector defaults/order, independent selection, callback values, reset without synthetic change events, typed empty Clock tables, and saves. English, French, Japanese and Arabic workflows run in Float/Decimal and legacy/strong-enum modes. The same workflow can test staged app/component/list changes through the existing MCP adapter.

## EDate and EOMonth

`EDate(start, months)` shifts by calendar months, clamping the day to the target month's last day. `EOMonth(start, months)` returns the target month's last day. Both return typed **Date** values at midnight, including when the input is DateTime and the offset is zero. Fractional month offsets truncate toward zero. Blank start dates use the Power Fx epoch (1899-12-30); Blank month offsets become zero. Dates outside years 1–9999 produce a catchable InvalidArgument error.

```powerfx
EDate(Date(2024, 1, 31), 1.9)       // Date(2024, 2, 29)
EOMonth(Date(2023, 5, 15), -1.9)    // Date(2023, 4, 30)
EDate(DateTime(2024, 1, 15, 9, 30, 0), 0) // Date(2024, 1, 15)
```

These are scalar functions. Use `ForAll` to apply them to rows. The binder rejects record/table arguments and Boolean start dates. Typed UDFs, component Date outputs/events, reactive properties, collections and mapped SQLite date columns retain their Date contracts. Failed writes retain the component input and computed dates; persisted records hydrate as Date values on reopening.

All **182 active cases** in Microsoft's pinned `EDateEOMonth.txt` file are included with independently decoded literal Date, number, text and error expectations. They pass; the same expressions also pass in the optional Decimal profile with its explicit Decimal serialization. Numeric dates and `Value(Date)` respect the chosen host profile: Canvas milliseconds remain the default, while the pinned interpreter references opt into serial days. This does not run Microsoft's .NET test suite. UTC/Gregorian cases are verified; native timezone normalization, DST behavior, Studio paste acceptance and physical Windows execution remain unverified.

Create the independent fictional fixture with:

```sh
python -m powerapps_sim.fixtures projects/month-planning --kind month-shifts
python -m powerapps_sim --import projects/month-planning
```

It contains two isolated components, start-date and fractional-month inputs, typed callbacks, resets, a mapped `Plans` list and a 16-step isolated workflow. Screen/component source, list schemas and workflow JSON remain separate. Browser checks cover leap-year changes, positive/negative offsets, keyboard increments, typed live collections, record editing, preserved open state after isolated testing and 400-pixel stacking. The optional MCP adapter validates a two-source/list-schema candidate and restores source/data through apply/undo.

Reference contracts: [Microsoft Learn](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-edate-eomonth), [pinned compiler types](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Core/Texl/Builtins/DateTime.cs#L344), [interpreter implementation](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Interpreter/Functions/LibraryDate.cs#L868), [complete expression file](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/tests/Microsoft.PowerFx.Core.Tests.Shared/ExpressionTestCases/EDateEOMonth.txt).

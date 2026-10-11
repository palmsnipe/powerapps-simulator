# Components, scopes and lifecycle

[Documentation index](README.md) · [Project README](../README.md)

Component ownership, callbacks, typed properties, resets, and inspection. Native lifecycle and timing parity remain subject to comparison in Power Apps Studio.

## Accuracy and component improvements

The binder registers definitions before resolution and tracks lexical record scopes, aliases, function parameters, table columns, per-screen context, component variables, and collection schemas. It validates typed UDF arguments/returns, component parameters/returns, assignments, query predicates, arity, and dependency cycles. Unknown types and open schemas represent incomplete inference or connector metadata, and are shown explicitly in the **Power Fx types** inspector alongside dependencies. This is a subset of the Power Apps type system, not an equivalent compiler.

Component input formulas and event callbacks run in the consuming app's scope; output formulas and actions run inside the component instance. Pure function properties use arguments rather than component/app variables. Local Set/Collect state is separate for every instance when AccessAppScope is off; enabling it shares app state and data sources. Parameter defaults and default record/table schemas are checked. Reset invokes the definition's OnReset behavior. **Components** displays live data properties alongside local variables and collections, including nested instance paths. Callable signatures retain parameter types, optional defaults and return types; expand Formula to inspect the effective definition or host callback. Selecting a property opens its component in the control inspector. The supported contracts follow [Microsoft's component documentation](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/component-properties) and [scope rules](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/create-component#scope).

The Components pane explicitly evaluates data properties through the same pure property access as the Control pane. It never invokes Function, Action, Event or OnReset handlers; errors stay attached to the affected property. The existing MCP `read_runtime` tool and runtime resource include `component_contracts` with effective formulas, source paths, input overrides, declared types, reset flags and callable signatures. This metadata path does not evaluate data properties or parameter defaults, render controls, drain events, or alter reset baselines. Current values remain available through scoped `evaluate_formula`. Inspection metadata is excluded from Power Apps exports.

Component lifecycle safety uses an **simulator limit of 100 automatic resets per instance per settling run**. A feedback callback that keeps changing a `RaiseOnReset` input is suspended for that instance and produces a source-located Cycle error observed by App.OnError. Repeated preview reads preserve the suspended state; peers and queued callbacks continue. A changed healthy reset-triggering input, an explicit Reset, or Restart re-arms the instance. Reentrant screen/control event callbacks also report a Cycle error before Python recursion. These are local safety rules. Native initialization, reset coalescing, nested reset ordering and callback timing still require recorded Power Apps comparisons; the published [component reset documentation](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/component-behavior) describes triggers without establishing this limit or ordering.

Try the independent component feedback fixture:

```sh
python -m powerapps_sim.fixtures projects/component-feedback --kind component-feedback
python -m powerapps_sim --import projects/component-feedback
```

The two component instances have typed callbacks and separate local state. Start feedback intentionally exercises the guard; Repair input or Reset left restores the affected instance. Its saved 23-step workflow expects one runtime diagnostic, checks callback snapshots and peer interaction, and preserves the caller source/data/runtime. Workflow traces have the existing 1,000-entry cap, so this deliberately repetitive case reports `trace_truncated`; its assertions and source diagnostic remain available.


Reactive input defaults now discard user edits when the default value changes without firing OnChange. Browser updates preserve focus and unsent text while applying server-driven default changes. Galleries retain selection by ID through refreshes and rebuild template references using stable row keys; removed rows reject stale browser events. Reset respects gallery/form boundaries and gallery reset preserves child state. Browser date inputs validate ISO calendar dates. Pixel measurements, themes, broad date parsing/localization, and runtime timing still need more fidelity work.

Record/table cells retain Power Fx errors until consumed. IsError(record) stays false when an unrelated cell has an error; reading that cell propagates its error. Table union coercions, projections and AddColumns preserve cell errors; Filter retains predicate failures as error rows and galleries show them beside healthy rows. Aggregates observe only the requested values. Set stores an unobserved error; behavior chains continue in order, and ForAll completes every iteration before returning aggregated errors. IfError exposes FirstError/AllErrors, and Error(AllErrors) rethrows them. SQLite writes reject errors anywhere in an updated record without committing the change.

Dates support overflowing Date parts, month/year/quarter adjustments with month-end clamping, and DateDiff unit boundaries through milliseconds. Parsing and formatting use the simulated language by default and accept explicit language overrides. Existing English/French profiles remain stable; additional language/region/script profiles use pinned offline CLDR data (see the locale section below). Numeric conversion handles grouping, currency, percentages and scientific notation; Text handles basic numeric masks and date/time placeholders, including minutes versus months, weekdays, AM/PM and milliseconds. Unknown locale tags and unsupported format grammars report explicit errors. Exact native culture/calendar parity, arbitrary date grammar, all implicit coercion overloads and timezone/DST simulation remain outside this implementation.

Date years 0–1899 follow the [documented canvas rule](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-date-time) of adding 1900. The pinned Microsoft engine tests use absolute years instead; the conformance report retains that difference as a known gap.

## Multi-value SharePoint cards and component callbacks

Array schemas with Choice, Lookup or Person record items now share options, validation and typed form handling with single-value columns. Required arrays reject empty selections; every entry is checked for its shape, configured Choice options, positive Lookup Id and local target existence, or nonempty Person Claims/Email. Nested required fields, types and text lengths are validated before any write. Missing choice/lookup configuration stays visible. People use the fictional directory; group principals and Microsoft identity resolution remain unsupported. The shapes follow the local SharePoint simulation rather than full live connector behavior. [Microsoft lookup metadata](https://learn.microsoft.com/en-us/graph/api/resources/lookupcolumn?view=graph-rest-1.0) and [person metadata](https://learn.microsoft.com/en-us/graph/api/resources/personorgroupcolumn?view=graph-rest-1.0) describe the multiple-value flags.

`Choices(List.Column [, text-filter])` requires a direct data-source column and returns full records. Its optional filter matches label prefixes, ignoring case, following [Microsoft's Choices reference](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/function-choices). Use `Search` when substring/multi-column searching is intended. Combobox defaults, Updates, LastSubmit and typed component callbacks retain arrays of these records. Person selections use Claims identity when labels change. Failed submissions and record-editor conflicts retain pending inputs.

Create the fictional comparison project:

```sh
python -m powerapps_sim.fixtures projects/complex-check --kind complex
python -m powerapps_sim --import projects/complex-check
```

It contains required tags/owners, optional related projects, two isolated component instances and a stored 22-step workflow covering failed saving, retry, callbacks and reset. `examples/complex.pa.yaml`, `complex-lists.json` and `complex.workflows.json` are packaged separately; source exports contain only Power Apps code. Studio paste acceptance and live SharePoint observations remain manual.

## Nested enhanced component scopes

A nested CanvasComponent now owns its action/output/reset state. Its authored inputs and Event callbacks execute in the containing component's scope; the outermost callback executes in the app. Parent and child collections with the same name stay separate, and each outer instance has its own descendants. The binder retains control identity across duplicate internal control names, including Self/Parent and callable contracts. Modern `Data` Input/Output properties use the same override rules as older encodings. Pure Function properties still require values as arguments, following [Microsoft's enhanced component properties](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/component-properties).

Recursive or missing definitions produce diagnostics while unaffected controls remain inspectable. Unsupported placement inside a gallery or form is reported according to [Microsoft's component limitations](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/create-component#known-limitations). Such imported source is preserved. Nested component paste acceptance and exact Studio lifecycle timing are not yet observed. The fixture explicitly resets its inner instances in its outer OnReset; it does not claim that Studio automatically invokes every descendant OnReset.

```sh
python -m powerapps_sim.fixtures projects/nested-check --kind nested
python -m powerapps_sim --import projects/nested-check
```

The fixture contains two panels, each with two counter components, actions with optional arguments, forwarded numeric callbacks, notes, separate history collections and explicit resets. Its stored workflow verifies 25 steps, including untouched peer instances and reactive seed changes. New nested tests cover mixed AccessAppScope settings, duplicate names, callback screen context, recursive definitions, and invalid placements. The clean source, empty data definitions and workflow are packaged as separate files.

## Behavioral app functions

App.Formulas now accepts typed behavior functions with curly bodies. Void discards a successful result while errors remain observable; other declared return types use the final expression. Functions register before startup, run ordered actions and retain lazy branches and IfError handling. A behavior function is rejected in a value property. Record-literal bodies remain pure. Direct and mutual recursion are diagnosed before the function starts. These contracts follow [Microsoft's app-function documentation](https://learn.microsoft.com/en-us/power-platform/power-fx/reference/object-app#behavior-user-defined-functions).

Functions use app scope and explicit parameters; they do not inherit caller record fields or component storage. Component events can call app functions in host scope. Direct calls from a component require AccessAppScope; component Function properties remain pure. ForAll restrictions survive nested function calls. Variable/collection inspectors and Power Fx types expose the resulting state and distinguish behavior functions.

```powerfx
Spend(amount: Number): Void = {
    Set(balance, balance - amount);
    Collect(events, {Action: "spend", Amount: amount})
};
```

```sh
python -m powerapps_sim.fixtures projects/actions-check --kind actions
python -m powerapps_sim --import projects/actions-check
```

The fixture combines startup initialization, nested actions, a Number-returning action, a Record-returning SQLite write, error handling and two isolated component callbacks. Its 30-step workflow covers failed writes and retry. Source, fictional schemas and workflow remain separate. No transaction rollback is invented: actions before an error remain applied, and behavior chains continue unless a lazy/error-handling branch prevents execution. Exact Studio binding, screen-context rules, implicit coercions and paste acceptance still need comparison.

## Enhanced component contracts

Data properties, function parameters and typed Function/Action/Event results now use compatible scalar and nested record/table conversions. Omitted arguments evaluate their declared defaults once; an explicit Blank remains Blank. Defaults run in a pure scope and cannot capture app variables, component state or other parameters. Signature, arity and statically incompatible argument checks run before argument actions. Malformed or unknown metadata yields diagnostics even for unused definitions, while unaffected components remain inspectable.

Record/table contracts come from the component definition, not instance overrides. Missing declared fields become Blank. Compatible extra fields are retained during component coercion, while closed-schema member access rejects undeclared fields. This differs from typed app UDFs, which retain restrictive aggregate contracts. Field conversion failures stay lazy until consumed. These component coercion choices are inferred from Microsoft's [enhanced property definitions](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/component-properties), [function type checking](https://github.com/microsoft/Power-Fx/blob/main/src/libraries/Microsoft.PowerFx.Core/Functions/TexlFunction.cs) and [aggregate coercion rules](https://github.com/microsoft/Power-Fx/blob/main/src/libraries/Microsoft.PowerFx.Core/Types/DType.cs). Exact canvas-host coercion, default timing and extra-field behavior still require a recorded Studio comparison.

Create the fictional fixture with `python -m powerapps_sim.fixtures projects/contracts-check --kind contracts`, then open it with `python -m powerapps_sim --import projects/contracts-check`. Its 37-step isolated workflow checks data/function conversions, defaults, record-to-table arguments, independent component state, typed callbacks, reset, bad-input retention and two SQLite writes. Browser checks confirm the same paths, typed variables, callback collections and saved records. Source, list configuration and workflow files remain separate.

## Component reset errors and recovery

Failures consumed by RaiseOnReset input comparison or Boolean Reset rules now reach deferred App.OnError, including when a child catches its visual value or is hidden. Pure property reads remain catchable without invoking the handler. Continuously unchanged failures report once; a healthy evaluation rearms reporting. A failed input keeps its last healthy baseline and does not reset the component. Recovering the same seed preserves local edits; changing the seed resets once. OnError can repair the input, after which settling runs OnReset. Origins remain distinct from the consuming child Reset rule. Handler failures cannot recurse.

```sh
python -m powerapps_sim.fixtures projects/component-reset-check --kind component-reset
python -m powerapps_sim --import projects/component-reset-check
```

The clean fixture contains two isolated components with typed action/event/function properties, translated input captions, an editable note, three fictional SQLite drafts, a gallery outside the components and explicit reset/failure/recovery controls. Its 38-step workflow checks callback parameter shadowing, committed outputs, peer isolation, blank defaults, repeated errors, failed writes and retry in English/French and Float/Decimal modes. Workflows use disposable snapshots and preserve owner source, records and runtime. Export retains Power Apps contracts and excludes fixtures/settings/database files.

## Authored record names and nested resets

Authored variable, collection, record-field and callback-parameter names beginning with `__` remain visible and usable. Lexical source/alias/open-schema markers now live on internal scope frames rather than occupying ordinary Power Fx fields. This fixes collisions in scoped aggregates, `With`, `ForAll`, `AddColumns` and nested `Table[@Field]` disambiguation; authored fields cannot accidentally open a closed schema. Parameter types participate in AST cache keys even when their names begin with `__`. Scope metadata stays outside serialized values, collection tables and source exports.

Component `RaiseOnReset` snapshots now retain all authored record fields. Changed nested record inputs reset affected instances and run their authored callbacks; equal inputs do not cause another reset. The inspector shows those fields and their types in app/component variables and collections. The new `scope-reset` fixture includes two parent instances, four nested children, typed callback parameters, live histories, reactive SQLite inputs and failed-save/retry checks. Its 24-step workflow runs on an isolated snapshot while preserving owner source, data and runtime.

```sh
python -m powerapps_sim.fixtures /path/to/scope-reset-demo --kind scope-reset
python -m powerapps_sim --import /path/to/scope-reset-demo
```

The [Power Fx identifier grammar](https://learn.microsoft.com/en-us/power-platform/power-fx/expression-grammar) permits underscore-led identifiers, and [Microsoft's component OnReset reference](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/component-behavior#onreset) describes resets on changed custom inputs. Local tests verify callback ordering and instance isolation; they do not establish native Studio scheduling, implicit descendant reset behavior, or complete component lifecycle parity.

## Component expression locations

Runtime expressions retain their declaration file, logical instance member, owner and YAML line. Definition-owned outputs/functions/actions and parameter defaults point to the component file; input-function and event overrides point to the host file. Omitted-argument conversion and return-type errors retain those origins. App properties, named formulas and user-defined function bodies use their App source. Unhandled errors keep Power Fx Source/Observed records and deferred App.OnError behavior. These internal locations never enter exported source or Power Fx error records.

Evaluated component query/row dependencies retain the instance owner even when a pure function has only parameter scope. Their source file, formula span and declaration line remain available through the existing Dependencies report and MCP tools. Component contract inspection exposes source lines and parameter-default locations without evaluating formulas, consuming random draws or invoking actions/events.

Create a fictional split-file comparison app:

```sh
python -m powerapps_sim.fixtures /path/to/empty/component-project --kind component-origins
python -m powerapps_sim --import /path/to/component-project
```

The 17-step workflow covers host/definition functions, omitted arguments, caught default errors, typed callbacks, independent instances, input-triggered resets, draft defaults and mapped SQLite snapshots. The separate Report default error button demonstrates an uncaught default and deferred App.OnError reporting. Runtime source-location checks include duplicate declarations and literal/folded multiline YAML. This does not change the existing reset scheduling policy or claim exact Studio event ordering. At that milestone, binding/historical findings still used separate location paths. Binding declaration locations are now covered below; exact quoted-scalar character columns and positions after source edits before restart remain open.

## Binding declaration locations

Static name/type/parse findings now retain the authored expression's source file, YAML line, logical declaration and character span. Duplicate occurrences and definitions stay separate. Nested named-formula inference reports the referenced declaration instead of attributing its syntax tree to a caller. Parameter defaults bind as their own pure expressions; schema inference does not report them again at a consuming control. Historical checker findings keep their imported positions.

Component signature findings locate PropertyKind, Parameters, parameter DataType and ReturnType/DataType fields. Missing fields anchor the existing declaration. Runtime signature validation preserves that master-file origin before evaluating arguments/body effects; alias-type failures retain their App type declaration and do not mutate cached errors. The selected App source follows the accepted property mapping when multiple App documents are present. This follows the existing model's selection; it does not merge or repair multiple App declarations.

Create an error-isolation comparison app:

```sh
python -m powerapps_sim.fixtures /path/to/empty/binding-project --kind binding-locations
python -m powerapps_sim --import /path/to/binding-project
```

Its 17-step workflow exercises unaffected component callbacks/resets and mapped SQLite snapshots while retaining eleven deliberate binding findings. They include repeated missing names, a type alias, parameter defaults, a forbidden host override, a function's component-value access and a missing value return contract. The source uses current InputFunction/OutputFunction declarations. The findings are simulator results, not a Studio checker claim. No source is renamed or repaired automatically. Exact quoted-scalar character columns, native reset/event ordering and Studio paste acceptance remain unverified.

## Required and optional component arguments

Component omission follows `IsOptional`, independently of `Default`. A parameter with no flag, or `IsOptional: false`, remains required even when its default defines a record schema. Optional arguments use their default when omitted, or Blank when no default exists. Explicit Blank stays explicit. Positional calls must supply arguments through the last required position. This matches the distinction in [Microsoft's parameter example](https://github.com/microsoft/PowerApps-Tooling/blob/master/src/schemas-tests/pa-yaml/v3.0/Examples/Src/Components/Parameters-Default.pa.yaml).

The binder and runtime share argument counts and validate Boolean flags before argument/body effects. Malformed flags retain their declaration location. The component inspector marks optional parameters with `?`; read-only MCP contracts expose minimum/maximum counts and each parameter's optionality. Simulator fixtures now declare intended optional arguments explicitly. Imported source stays unchanged: calls that omit unflagged arguments now receive an arity finding.

Create a clean comparison app:

```sh
python -m powerapps_sim.fixtures /path/to/empty/optional-project --kind optional-parameters
python -m powerapps_sim --import /path/to/optional-project
```

Its 19-step workflow covers required schema defaults, optional defaults/Blank, typed records, host functions, independent actions/events, resets and mapped snapshots. Native optional-parameter timing and Studio paste acceptance remain manual checks. Native component types such as DateAndTime, Currency, Screen and VideoOrAudio still need a fuller contract audit.

## Native component property data types

Component `DataType` and `ReturnType` contracts now recognize `DateAndTime`, `Currency`, `Screen` and `VideoOrAudio`, alongside existing types and aggregate schemas. These are clipboard property enums; they do not automatically become valid App.Formulas type names. The [Microsoft YAML model](https://github.com/microsoft/PowerApps-Tooling/blob/master/src/Persistence/PaYaml/Models/SchemaV3/PaYamlPropertyDataType.cs) and [Power Fx coercion rules](https://github.com/microsoft/Power-Fx/blob/df4ceba5e08220db670c25afead342ce699c50b5/src/libraries/Microsoft.PowerFx.Core/Types/DType.cs) provide the reference contracts.

`DateAndTime` uses the existing typed DateTime conversion. Currency accepts numeric, Boolean and locale-aware text arguments; its backing follows the configured Float/Decimal mode. Inspectors retain Currency identity and explicitly mark it as inferred from source. This does not impose an unverified native currency precision or rounding policy. Screen values remain references: strings and non-screen controls fail validation, while typed component functions/actions can return a screen, read its width and navigate to it.

Audio/video assets retain Media identity separately from Image. Local resource paths and data-URI MIME types classify these values without fetching URLs. Component conversions reject Image/Media interchange, and JSON keeps its existing explicit binary inclusion/omission policy. Reactive signatures include media kind and asset root, including nested values. Inspectors preview local media with browser controls and reserve wider table columns, preserving horizontal scrolling. Remote references remain text in the inspector. Native Audio/Video canvas controls, their playback events, and Studio comparison remain open; an inspector preview is not a full control implementation.

Create a fictional comparison app:

```sh
python -m powerapps_sim.fixtures /path/to/empty/native-project --kind native-types
python -m powerapps_sim --import /path/to/native-project
```

Its split source files, generated local tone, two isolated components and 19-step workflow cover typed data properties, callable parameters/returns, callbacks, resets, navigation, error handling and mapped SQLite snapshots. The MCP exercise changes a component default and snapshot formula across both source files, adds a mapped field, tests a 20-step candidate, and restores source/schema/data through apply/undo.

## Text editor event isolation

Native TextInput, ModernTextInput, Classic/TextInput and RichTextEditor share a
server-owned event stamp. It includes the full instance/row path, restart/reset
epoch, control kind/version and the evaluated default binding. Default bindings
settle before a stamp is checked, so events received before the next preview
cannot overwrite a changed default. Same-valued form records use the form
lifecycle's reset epochs. Observed contract changes advance the stamp even if
the setting later returns to its earlier value.

Native and modern text contracts include MaxLength, TriggerOutput, Mode and
Type; classic text includes MaxLength, DelayOutput, Mode and Format. Rich text
shares instance/default/version identity, including paste sanitization. Width
and ordinary typed values do not invalidate a current editing session. Existing
ancestor visibility and DisplayMode gates continue to reject unavailable edits.
This change does not add DisplayMode or Visible to the contract signature.

These are internal browser transport stamps, excluded from exported Power Apps
YAML. The original output/callback rules remain in effect: native FocusOut drafts
publish on blur, modern delayed output retains browser focus/caret, classic uses
its existing DelayOutput handling, and rich text uses the existing HTML sanitizer
and callback model. Legacy direct runtime event helpers still support their
existing tokenless calls; browser text events use structured stamped payloads.
Native timing and reset ordering still need recorded Power Apps comparisons.

The public native, modern, classic and rich fixtures exercise paired components,
form edits and repeatable save/failure/retry workflows. The demonstration server
at `http://127.0.0.1:8858/` uses disposable fixture projects and local SQLite.
The archived verification report links focused tests, fresh offline installs,
MCP stdio workflows and private sample snapshot checks. Source and records in the
private project are preserved; its live runtime was not compared or restarted.

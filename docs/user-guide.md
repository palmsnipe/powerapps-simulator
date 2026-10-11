# Using the simulator

[Documentation index](README.md) · [Project README](../README.md)

Edit source, inspect runtime state, and manage fictional local data. All source paths shown here are relative to the repository root.

## Editing and playing

1. **Import app** opens an `.msapp`, `.yaml`, or `.yml` file. **Paste YAML** accepts a screen, component definition, or clipboard control tree.
2. Expand the tree or select a source document. Dedicated App editors expose `Formulas`, `OnStart`, and `StartScreen`.
3. **Apply source** saves a draft and validates YAML. Malformed drafts remain recoverable; the active source and preview remain intact. **Restart app** loads valid edits and runs startup again.
4. Click controls in the preview to run their Power Fx events. Use **Inspect controls** to inspect formulas and values without clicking through the app.
5. Selecting a screen in the tree inspects it directly without changing the active app screen. **Run this screen's OnVisible** explicitly initializes that screen for inspection. **Play from active screen** returns to the app's own navigation.
6. **Copy** copies the current editor. The Control inspector can copy a selected control subtree. **Export source** downloads source YAML and assets, excluding SQLite and simulator configuration.

The editor applies explicit source changes rather than a visual drag/drop designer. YAML comments, unknown properties, names, versions, and formulas are preserved. App property edits use round-trip YAML serialization. Source locations are available in current diagnostics; imported Power Apps checker findings are displayed separately as a historical snapshot.

**Structure**, **Source**, **Preview**, and **Inspector** toggle each pane. Drag the separators or use their arrow keys to resize them; pane sizes and visibility persist in this browser. At least Source or Preview remains visible. The workspace uses local Fluent 2 color, spacing, typography and focus tokens based on Microsoft's [design tokens](https://fluent2.microsoft.design/design-tokens) and [layout guidance](https://fluent2.microsoft.design/layout).

The inspector's **Variables** tab shows current global and screen-context values with their types, including Blank and Error. **Collections** shows app and component collections as searchable, horizontally scrollable tables. Collection selectors display their instance paths so repeated names are distinguishable. **Components** shows each instance's inputs, outputs, callable signatures and private state. **Live** refreshes the visible inspector every two seconds; control events refresh immediately. **Refresh values** also reads server state after external AI/API operations. Unchanged tables retain focus and scroll position.

## Data and scenarios

An `.msapp` contains schema metadata, not its live SharePoint records. Imported connected lists initially have no records. **Reset mock data** replaces local records with clearly fictional linked data and configures inferred choice/lookup fixtures. Restart afterward so startup collections and roles reload. It never changes app source, grants roles by modifying formulas, or enables disabled workflows.

**Simulation settings** lets you choose a fictional user and configure language, URL parameters, an ISO clock value, and the people directory. `User()` reads `environment.user`; `Language()` reads `environment.language`; `Param()` reads `environment.parameters`. Clock examples: `2026-10-09T12:00:00-04:00` or `null` for the current clock. Resize the preview to reevaluate `App.Width` and `App.Height`; explicit dimensions in source stay explicit.

**Local data** displays searchable records in pages of 50. Columns stay 190 pixels wide and scroll horizontally, with ID and Title first. **Edit** opens one record; **New record** creates one. Numbers, booleans, text, Choice, Lookup and Person fields have typed editors. Multi-value Choice, Lookup and Person columns use searchable checkbox groups; selections retain their complete record values. List cells show readable names, with the stored JSON available in tooltips. Other complex fields use JSON. Read-only fields stay outside the edit form. Saving validates the changed fields and checks the source/schema revision and original record. Validation or conflict errors keep the pending inputs. Unknown option values remain visible; missing relationship/choice metadata still requires configuration.

Collapsed **Records JSON** and **Schema & choices** panels provide the existing bulk and schema tools. **Replace list records** replaces that list after validating the whole document; omitted rows are removed. File import upserts records, retaining supplied IDs. CSV complex cells must contain JSON. Example field values:

```json
{
  "Title": "Fictional project",
  "Status": {"Value": "Draft"},
  "Division": {"Id": 1, "Value": "Demo division"},
  "Owner": {
    "Claims": "i:0#.f|membership|submitter@example.test",
    "Email": "submitter@example.test",
    "DisplayName": "Demo Submitter"
  }
}
```

Schema `fields` use internal column names, and `mapping` maps them to Power Apps display names. `choices` maps an internal column to its allowed text values; `lookups` maps an internal column to a local list name. Connector metadata often omits choice options and target identifiers; `metadata_gaps` records those gaps. Generated options/targets are fixture configuration, not recovered SharePoint settings.

Read/write/all failure injection lets you exercise `IfError` and form failure events. Clearing a read failure remains possible even when loading the records fails.

## Repairing stale control references

Imported apps can contain stale control names in App.Formulas when the corresponding screen controls have numeric suffixes. The repair tool proposes replacements only when an existing suffixed control provides an unambiguous match; review the plan before applying it.

To inspect another imported project's App.Formulas for the same issue:

```sh
.venv/bin/python -m powerapps_sim.repair projects/your-project
```

Add `--apply` to apply the previewed changes, then restart the simulator. The command changes only AST identifier references with one existing numeric-suffix counterpart. Strings, comments, property names, local variables, and unrelated YAML remain intact. Ambiguous candidates are left unresolved. A source backup and a change report are retained in the project's `metadata/reference-repairs/` directory and excluded from Power Apps export. Literal YAML formula blocks are required; other styles remain editable through the normal source editor. Imports and runtime name lookup never repair or alias references automatically.

The simulator also supports data-card Error values populated on submission, per-field schema validation, Color.LightGray, nested query scopes that retain gallery/form ThisItem, and Table's union of columns and untyped blank-record inputs. Gallery OnSelect sees the selected item when a child calls Select(Parent); explicit input value formulas take precedence over version defaults until user input overrides them. AST type metadata now preserves record/table schemas for Blank expressions, including blank tables contributing no rows to Table. Scalar column coercions and numeric ErrorKind values are supported; full typed-Blank propagation across every overload remains incomplete.

## Themes, audit metadata and save errors

`App.Theme` now evaluates its authored formula instead of ignoring it. `PowerAppsTheme` and apps without an authored Theme use the 16-slot Fluent Web Light fallback (`Darker70` through `Darker10`, `Primary`, `Lighter10` through `Lighter80`), plus Name and Font. Custom records react to variable changes, and invalid/cyclic theme formulas stay errors. Slot structure follows [canvas modern theme documentation](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/controls/modern-controls/modern-theming); fallback values use [Microsoft's Fluent brand tokens](https://microsoft.github.io/fluentui-design-tokens/). This does not recover an archive's custom palette or implement seed/torsion/vibrancy generation.

Local list writes now stamp read-only Created By/Modified By Person records and Claims fields from the currently simulated user. Creating sets both; updating retains the creator and changes the editor. Failed writes preserve metadata. JSON imports and explicitly supplied system fixture metadata retain historical identities. This is simulation metadata, not authentication or SharePoint permission enforcement. Fictional planning datasets include submitter-owned drafts and configurable review choices.

SharePoint integer columns, including lookup Id fields, accept whole-valued Power Fx Float/Decimal numbers at storage time. Fractional/nonfinite values and Boolean lookup IDs remain invalid. This allows records selected from AddColumns-shaped tables to save without weakening lookup validation.

A save formula that wraps `IfError` around `Set(savedId, Patch(...).ID)` can store the Patch error without observing it. This follows [Power Fx's documented delayed observation of errors stored by Set](https://learn.microsoft.com/en-us/power-platform/power-fx/error-handling). To handle the failure immediately, place `IfError` inside the saved-ID assignment and return Blank after recording the error message. The public audit-identity tests exercise both forms, including failed writes that leave records unchanged.

## Live values and structured inspection

Variables includes app globals, screen context and component-private variables, including inferred uninitialized values. Variables, Collections and Components each offer a **Runtime scope** selector. Component scopes use full instance paths, including nested instances. Scope selection combines with the text filter, survives live refreshes and explicit simulation restarts, and is remembered independently for each tab. Changing projects clears the scope selections. App, screen and component identities remain separate even when an authored screen is named Global or values share names.

Variables and Components now retain Date, DateTime, Time, Image, Dynamic and Decimal identity through separate type metadata. Color and GUID labels use binding information because their current runtime representation is a string; the badge tooltip identifies that inference. Literal strings resembling images, colors or identifiers stay Text. Blank values retain a declared-type tooltip, and inferred but uninitialized variables are visible without executing their handlers. This follows the [implicit variable model](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/working-with-variables). Empty app/component collections retain their inferred columns. Unknown remains distinct from Blank.

Records, tables, Dynamic objects and captured errors expand into structured cells. Nested tables and top-level collections page through all rows in groups of 50. Column headings retain types, wider fields get readable column widths, and wide tables scroll horizontally. Local image previews and color swatches accompany the values. Expansion, nested paging, scroll positions and focused inspector controls survive value refreshes. Image previews do not automatically fetch external URLs. Expansion stops at 12 nested levels; deeper values remain available as JSON.

The state endpoint, AI read_runtime and workflow reports include a separate `types` object matching globals, collections, contexts and component instances. Existing value serialization is preserved. Metadata observation performs no formula/property evaluation, startup, reset, events or writes. AI formula results use runtime types with binding information for string-backed Color/GUID values. Binding now distinguishes the same context-variable name across screens. Source exports exclude metadata.

Create the fictional fixture with `python -m powerapps_sim.fixtures projects/inspection-check --kind inspection`. Its 24-step isolated workflow verifies captures in independent components, resets, nested collection values, Blank/error handling and owner preservation. The fixture also has a 20-column collection, a 55-row nested table and uninitialized typed values. Native browser checks cover paging, expansion/focus retention, horizontal scroll retention and typed empty headers. These are local evidence; exact Studio comparisons remain manual. [Microsoft’s data type reference](https://learn.microsoft.com/en-us/power-platform/power-fx/data-types) explicitly excludes Image from Type specifications; the simulator now diagnoses that case.

## Structured nested list editing

Local data now edits schema-defined records and arrays through typed fields and rows. Arrays offer Add row, Remove, Empty (`[]`) and Clear (`null`); blank records can be created explicitly. Nested arrays and records remain editable, and wide tables scroll horizontally. Existing unknown fields remain available as JSON. Choice, Lookup and Person fields keep their configured selectors.

Decimal fields use text inputs and retain `$decimal` digits without converting through a browser number. Untouched missing/null values, extra nested properties and unknown historical values are preserved. JSON views are available; malformed JSON and incorrect aggregate shapes retain the draft. JSON views containing read-only descendants are inspection-only. Read-only annotations in this editor are UI behavior, not a new permission boundary; Python validates list writes. Failed validation, writes and optimistic-revision conflicts leave the dialog open for correction or cancellation.

Complex list cells expand into typed records or tables with independent scrolling and row pagination. Source export remains Power Apps source only; these editors modify SQLite list records through the existing list API.

```sh
python -m powerapps_sim.fixtures projects/record-editor-check --kind record-editor
python -m powerapps_sim --import projects/record-editor-check
```

The fictional fixture has 20 declared row columns plus an unknown legacy field, nested locations/tags, nullable numeric arrays, read-only metadata and exact Decimal values. Its six-step workflow checks isolated formula reads and collection capture. Nine new backend tests cover mapped nested saves, precision/unknown-field preservation, atomic validation/write failures and workflow isolation. Native browser checks verified editing, draft retention, invalid JSON/shape recovery, row add/remove, nested record creation, empty arrays and horizontal scrolling. A browser CI regression is added and compiled; it was not run locally. Windows, Python 3.11–3.13 and actual Studio paste comparison remain unverified.

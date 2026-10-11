# MCP, workflows and reviewed changes

[Documentation index](README.md) · [Project README](../README.md)

Connect an AI client, run isolated scenarios, and review/apply coordinated source and schema changes through the shared workspace services.

## Connecting an AI client through MCP

Open **AI tools** in the editor. It shows the bound project, installed SDK version, an install command if needed, and copyable `command`/`args` settings for a stdio-capable client. It uses the current Python executable, server port and absolute project path. Keep the simulator running while using this HTTP attachment. The dialog does not install dependencies or register a client automatically.

From a source checkout, install the optional extra with the simulator's Python:

```sh
python -m pip install -e ".[mcp]"
```

For an already installed simulator, install `mcp==2.3.0` into the same environment. The core simulator never imports the SDK unless the MCP adapter is launched. A client must launch the adapter on the computer hosting the simulator; an AI host/model may have its own connectivity requirements.

HTTP attachment uses the existing browser session and database:

```sh
python -m powerapps_sim.mcp_server --url http://127.0.0.1:8766 --expect-project "/absolute/path/to/project"
```

The adapter pins the project identity at connection. If the browser switches projects, calls fail until explicitly reconnected. Only loopback HTTP is supported; environment proxies and HTTP redirects are disabled. Failed writes are never retried automatically. The editor's generated settings include the project check from the first request.

For headless authoring while the project's browser server is stopped:

```sh
python -m powerapps_sim.mcp_server --project "/absolute/path/to/project"
```

Headless mode owns the same OS project lock and does not execute OnStart or visibility events. Isolated workflows execute startup inside their disposable snapshots. The server writes protocol messages to stdout and diagnostics to stderr; it has no HTTP MCP listener.

The 16 tools are:

| Purpose | Tools |
| --- | --- |
| Inspect | `describe_project`, `read_source`, `read_list`, `read_diagnostics`, `read_analysis`, `read_runtime`, `read_dependencies` |
| Evaluate/export | `evaluate_formula`, `export_source` |
| Author | `list_changes`, `stage_change`, `apply_change`, `undo_change` |
| Verify | `list_workflows`, `run_workflow`, `read_workflow_report` |

Seven JSON resources expose `powerapps://project`, `diagnostics`, `analysis`, `runtime`, `dependencies`, `changes` and `workflows`. Source reads return saved YAML/App properties/control exports; runtime/type reads and pure evaluation observe the running source. Responses identify when saved and running source differ. Formula language errors are typed values; invalid arguments, ownership and revision conflicts are tool errors. Reading runtime state does not render controls or drain queued events. List reads are paged (1–500 records).

Recommended client sequence: read project/revision, source and schemas; stage combined replacements/migrations; inspect the diff and diagnostics; run named or inline workflows against the returned change ID; explicitly apply using its base revision. Review and undo use the same browser services. Source changes still need **Restart app** before the preview uses them. Workflow results are evidence for their assertions, not Studio certification. These tools expose local simulation only; they do not authenticate to Microsoft or write to SharePoint.

Optional offline MCP packaging includes native SDK dependencies, so build it on a connected computer matching the destination OS, architecture and Python minor:

```sh
.venv/bin/python tools/build_offline.py --with-mcp
```

This creates `dist/powerapps-sim-offline-mcp-<platform>-py<minor>.zip` beside the Windows/macOS core ZIP. Extract it and use the included setup/start scripts. `requirements-mcp.txt` pins the resolved wheels; `bundle.json` identifies the target. The supplied MCP build is for the development Mac/Python 3.14; it is not a Windows bundle. The universal core bundle remains suitable for the documented Python 3.11–3.14 targets without MCP. Actual registration and approval settings depend on the chosen AI client and remain a manual connection step.

## Isolated workflow scenarios

Open **Workflows**, choose a scenario, edit its JSON if needed, choose **Saved project source** or a staged change, then click **Run isolated workflow**. The result includes assertion values, ordered formula/behavior/navigation traces, current app diagnostics, changed record IDs and final variables/collections/component state. **Download report** saves the complete JSON result. Runs also remain in `.emu/runs/` for API retrieval. A pass means the declared assertions passed; it does not certify Studio compatibility or imply that app diagnostics are empty. Use a diagnostic-count assertion when that is required.

The runner snapshots saved source, schemas, assets, metadata and SQLite using a database backup. It starts an independent disposable runtime; it does not use unsaved editor drafts or the preview's current control state, globals or failure injections. Staged combined source/schema changes use the same validation/migration/apply service inside the snapshot. Nothing applies to the open project. Source/schema conflicts and stale staged schema data are rejected. The workspace lock serializes runs with local edits. Only a private report is added to the real project.

Store reusable definitions as `tests/NAME.workflow.json`. Forms and lifecycle comparison-project factories include clean scenarios; unmodified bundled fixtures also expose those presets without writing project files. The demo checks English/French translation, filtering, navigation and a component callback. The private sample project contains eight saved scenarios: four access/gate baselines, minimal and scored draft creation/reopening, saved-draft scope/discard checks with French labels and header callbacks, and failed-save/retry verification after the reviewed source correction. Review and submission flows remain gated by the source. The archived original-error source and scenario remain available separately from active workflows.

```json
{
  "format_version": 1,
  "name": "Fictional draft edit",
  "environment": {"clock": "2026-01-01T12:00:00+00:00"},
  "steps": [
    {"op": "event", "path": "Forms/DraftForm/TitleCard/TitleInput", "event": "OnChange", "value": "Fictional edit"},
    {"op": "assert", "formula": "DraftForm.Unsaved"},
    {"op": "event", "path": "Forms/SaveDraft", "event": "OnSelect"},
    {"op": "assert", "formula": "DraftForm.LastSubmit.Title", "expect": "Fictional edit"},
    {"op": "diagnostics", "expect": 0}
  ]
}
```

The version-one fields and steps are:

- `environment`: overrides for simulated `user` (`Email`, `FullName`), `language`, `parameters`, `clock`, `number_mode`, `date_numeric_mode` and `round_table_mode`. A supplied clock requires an ISO time zone. If the project has no clock, the runner freezes one and returns it for replay. For repeatable runs across days, declare a clock and explicit fixture records.
- `viewport`: optional width/height overrides, each 200–4000. `records`: optional map of list names to validated replacement rows in the disposable database; other lists retain their snapshot data. Relationship metadata and required field rules still apply. Fixture setup is excluded from reported app writes.
- `event`: an existing control `path`, `event` (`OnSelect`, `OnChange`, `Pressed`), optional `value` or zero-based `selection` indexes, and optional Boolean `expect_blocked`. When true, the runner requires a hidden/disabled control and records the blocking ancestor without executing its handler; an allowed event, missing control, inactive screen or formula error fails the assertion. Gallery children use rendered instance paths. Hidden/disabled/inactive-screen controls and invalid selections fail explicitly. Navigation occurs through app controls; there is no direct navigation/access bypass step.
- `scroll`: a visible, active-screen gallery `path`, nonnegative numeric `offset` and optional `extent` in logical pixels. It loads the presentation window without app events, including in View/Disabled mode. Hidden/inactive galleries remain blocked.
- `assert`: a pure Power Fx `formula`, optional control `scope` for `Self`/`Parent`/component values, and `expect` (defaults to Boolean true) or `error_kind`. Blank is JSON null, Decimal is `{"$decimal":"0.3"}`, and errors are distinct values. Assertions cannot run behavior functions. Boolean and Number expectations remain distinct.
- `failure`: a declared `list` and `mode` (`read`, `write`, `all`, or null to clear), applied only to the disposable runtime.
- `diagnostics`: the expected current diagnostic count. Imported historical checker results are not current findings. All steps accept an optional `label`.

Scenarios require at least one assertion and allow up to 200 steps. A failed action stops dependent steps and reports their skipped count; failed assertions continue so independent discrepancies remain visible. Traces are capped at 1,000 entries and explicitly mark truncation; execution continues. Write summaries report net row changes and per-step changes, not a complete SQLite transaction audit. Reports contain simulated data/formulas and stay local; they are excluded from Power Apps exports together with scenario definitions and simulator configuration. Timing, browser focus/scrolling and exact visual fidelity still need browser/Studio comparison tests.

HTTP clients sharing a running workspace use:

```text
GET  /api/workflows
POST /api/workflows/run
GET  /api/workflows/runs/RUN_ID
```

The POST body is `{"expected_revision":"CURRENT_REVISION","scenario":{...},"change_id":null}` with `X-Emulator-Request: 1`. Supply a staged ID to test it before applying. GET catalog returns validated stored/bundled definitions and a starter; invalid definitions remain visible with errors. Reports record base/data/candidate revisions, scenario digest and resolved environment. A failed workflow returns a report with `status: "failed"`; malformed input/conflicts return HTTP 400/409.

With the browser server stopped:

```sh
python -m powerapps_sim.workflows projects/forms-check scenario.json
python -m powerapps_sim.workflows projects/forms-check scenario.json --change CHANGE_ID
```

The CLI acquires the same project-owner lock, prints the JSON report, and exits 0 for passed assertions or 1 for a failed workflow. It never starts the live project runtime; startup and all actions occur inside the disposable snapshot. While a server owns the project, use HTTP instead.

## Reviewed source and list changes

In **Local data**, edit the schema and click **Review schema change**. The review shows the definition diff, records checked/changed, and candidate binding/source diagnostics. Nothing applies until **Apply reviewed change**. The **Changes** tab retains staged/applied/undone changes and allows reviewing or undoing the latest applied change. Source's existing **Apply source** also uses this service and records a reversible change; an invalid YAML draft remains separate from active source. Apply/undo source explicitly requires a simulation restart. Schema changes materialize immediately; restart after a combined source/schema change before testing its new formulas.

Each file in `lists/` is a plain JSON envelope:

```json
{
  "format_version": 1,
  "name": "Drafts",
  "definition": {
    "fields": {"ID": {"type": "integer", "x-ms-permission": "read-only"}, "Title": {"type": "string"}},
    "mapping": {"ID": "ID", "Title": "Title"},
    "required": ["Title"],
    "choices": {}, "lookups": {}, "writable": true
  }
}
```

Existing project schemas are copied from SQLite on first open, retaining internal/display names, unknown metadata, configured options/lookups and metadata gaps; records and YAML are unchanged. A marker records that migration. Removing a catalog file does not silently recreate it from old archive metadata. Hand-edit files while the server is stopped, or restart to validate/load them. Invalid external schemas do not replace the running workspace. Additive changes can materialize declared defaults, with a database backup under `metadata/catalog-sync/`; removing/renaming populated columns must use the reviewed migration service. List deletion, arbitrary cell-value transformations and schema format versions other than 1 are not supported yet.

In **Column migration**, declare removed columns explicitly, using internal names:

```json
{"rename_columns": {"Amount": "Budget"}, "drop_columns": ["ObsoleteColumn"]}
```

The new definition must declare Budget and update its required/mapping/choice/lookup entries. Rename destinations must be new columns, and ID cannot change. All existing records and nonblank defaults are validated against the candidate schemas, including constraints, choices and lookup IDs. A newly required field without a usable default fails when existing records need it. Dropping a field discards its local values only after review; undo restores the backup. These are local simulation migrations, not promises that a live SharePoint API accepts the same operation.

Authoring state lives under `.emu/changes/<id>/`: request, combined diff, validation report, record impact, file snapshots and (for schemas) a SQLite backup. Applies roll back on failure; interrupted apply/undo journals recover on the next workspace open. Undo requires the latest applied change and a matching source/schema revision. Schema undo also refuses to overwrite data written since the migration. Source-only undo leaves newer records and simulation settings alone. Cooperative clients must use the service; simultaneous arbitrary filesystem/SQLite writes are not a transactional authoring API.

Every source/schema write requires `expected_revision`, a content hash covering source and schema files. HTTP conflicts return **409** and preserve newer edits. Browser input stays in the editor after a conflict. Older saved drafts remain on disk but no longer replace newly edited source automatically. Record changes after staging reject a schema apply, requiring a fresh review. Pure binding/source diagnostics are included in validation; startup/events are not executed. Existing invalid Power Fx can remain reviewable/applicable with diagnostics; `strict: true` requires no current candidate binding/source findings. Passing these checks is not a completed workflow simulation or a Studio checker result.

A coding agent can use the current HTTP API against the running workspace:

| Operation | Endpoint |
| --- | --- |
| Read revision/project | `GET /api/project` |
| Read source/schema | `GET /api/source?name=Src/...` / `GET /api/lists/<name>` |
| Stage a combined change | `POST /api/changes` |
| Review history | `GET /api/changes` |
| Apply / undo | `POST /api/changes/<id>/apply` / `POST /api/changes/<id>/undo` |

POST uses JSON and the existing `X-Emulator-Request: 1` header. A staged request has `expected_revision`, optional `title`, `sources` (path to full text, or null for deletion), `lists` (list name to full definition), `migrations` (list name to rename/drop instructions), and optional `strict`. Apply/undo send the expected revision: base_revision for apply, after_revision for undo. Re-read/restage after a conflict rather than blindly retrying. Power Apps **Export source** still excludes schemas, configuration, database and history.

When the browser server is stopped, use the headless CLI:

```sh
python -m powerapps_sim.authoring projects/forms-check describe
python -m powerapps_sim.authoring projects/forms-check stage change.json
python -m powerapps_sim.authoring projects/forms-check apply CHANGE_ID --revision BASE_REVISION
python -m powerapps_sim.authoring projects/forms-check history
python -m powerapps_sim.authoring projects/forms-check undo CHANGE_ID --revision AFTER_REVISION
```

`change.json` uses the staged-request shape above. The CLI never runs OnStart or visibility events. It refuses a project already owned by a running server, so AI clients working with that server should use its HTTP API. The optional MCP adapter exposes these same services without another evaluator or competing workspace owner.

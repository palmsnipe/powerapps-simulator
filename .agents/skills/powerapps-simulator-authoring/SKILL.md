---
name: powerapps-simulator-authoring
description: Create or edit local canvas apps through the Power Apps Simulator MCP server. Use for app YAML, simulated list data, Power Fx control edits, and saved workflow tests.
---

# Power Apps simulator authoring

Use the simulator's versioned control contracts. Call `describe_project` for the bound project and revision. Use `read_controls` to locate existing controls, `read_control` for a specific version and its authored properties, and `read_list_schema` for field names and types. Read full source or sample rows when the change needs them.

## Create a project

Send `create_project` the complete source and, when needed, list definitions, seed records, and saved workflows together. Omit `expected_revision` for an empty workspace. Use the returned revision for subsequent calls. In an already bound workspace, pass the current revision if the task calls for creating and switching to a new project.

`sources` maps paths such as `Src/Main.pa.yaml` to full YAML strings. Control property values are Power Fx formulas beginning with `=`.

**In YAML source, use `>-` for every formula containing a Power Fx record literal, even a one-line formula in a gallery child.** Put `>-` on the property line and indent the entire formula below it. YAML can read the colon followed by a space in a record field as a mapping separator when the formula is inline.

```yaml
Screens:
  Main:
    Children:
      - EnableButton:
          Control: ModernButton@1.0.0
          Properties:
            Text: ="Enable"
            OnSelect: >-
              =Set(settings, {Enabled: true})
```

Use the same layout for a one-line gallery button action.

```yaml
OnSelect: >-
  =Patch(Projects, ThisItem, {Archived: true})
```

Before sending source to `create_project` or `stage_change`, scan all property formulas with records or colon-space, including nested gallery controls. Check that each uses a block scalar. The tool's JSON string escaping carries the YAML document and leaves its YAML syntax rules in effect.

`lists` maps list names to definitions with a `fields` object keyed by field name and an optional `required` array. `records` maps those list names to arrays of rows. Use these keys on the creation request for the clock, viewport, and saved workflow envelope. Supply a fixed clock through **`environment.clock`** as an ISO timestamp with a time zone. The simulator rejects an environment key named `now`. Keep `viewport` and `records` outside `environment`. Saved workflows inherit the project environment unless the scenario needs an override.

```json
{
  "environment": {"clock": "2026-02-01T12:00:00+00:00"},
  "viewport": {"width": 900, "height": 700},
  "workflows": {
    "enable.workflow.json": {
      "format_version": 1,
      "name": "Enable sets the flag",
      "steps": [
        {"op": "event", "path": "Main/EnableButton", "event": "OnSelect"},
        {"op": "assert", "formula": "settings.Enabled", "expect": true},
        {"op": "diagnostics", "expect": 0}
      ]
    }
  }
}
```

Run the saved workflows after creation to establish a baseline. For a scenario that simulates a failed write, use a step with `"op": "failure", "list": "<declared list name>", "mode": "write"`, then clear it with another step using `"mode": null`. Use `"expect_blocked": true` when testing a deliberately disabled control. For dropdown events, use `OnChange` and `"selection": [1]` for the second option, including on single-select controls. For gallery rows, resolve the rendered control with a `target` formula such as `First(ProjectGallery.AllItems).EditButton`.

## Stage, test, and verify

Use `stage_control_edits` for focused control edits and `stage_change` for broader source changes. For `add_control`, pass `control` as a JSON object with a versioned `Control` field and a `Properties` object. Replace the example revision with the current project revision and use the source-tree path of the parent.

```json
{
  "expected_revision": "CURRENT_REVISION",
  "edits": [
    {
      "op": "add_control",
      "parent": "Main",
      "name": "Caption",
      "control": {
        "Control": "ModernText@1.0.0",
        "Properties": {"Text": "=\"Project overview\"", "Y": "=64"}
      }
    }
  ]
}
```

Inspect the candidate diff and diagnostics before testing it. Batch relevant saved and inline tests with `run_workflows`, passing the base revision, candidate `change_id`, and entries containing either `scenario_file` or `scenario`. Scenario writes run in isolated snapshots. Test the visible behavior and resulting records, including defaults before any interaction.

Apply the passing candidate when authorized. `apply_change` reruns every saved workflow and blocks on any failure.

**When repairing a failing baseline**, stage and test the repair by itself. After applying it, explicitly call `run_workflows` on all saved scenarios with `expected_revision` set to the apply result's `after_revision`. Omit `change_id` so the run targets the newly saved baseline. Wait for this run to pass before staging the next feature.

After the final apply, use the returned `after_revision` to restart the preview when the task calls for live verification. Restart resets unsaved runtime state and runs startup and screen visibility formulas. Check diagnostics and verify the changed value or interaction.

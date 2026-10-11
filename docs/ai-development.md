# Local AI development benchmark

[Documentation index](README.md) · [AI tools and workflows](ai-workflows.md)

The benchmark exercises one complete simulator development loop: discover the relevant app source and list schema, stage a feature, test it in isolated workflows, apply it, restart the preview, export the source, and undo the change. It runs locally with fictional SQLite records and requires no Microsoft connection.

## Develop the starter app

```sh
.venv/bin/python -m powerapps_sim.fixtures projects/ai-development-starter --kind ai-development
.venv/bin/python -m powerapps_sim --import projects/ai-development-starter
```

The fixture generator requires an empty destination. The starter has a project gallery and title/budget editor. Its status filter is deliberately absent and its OnFailure handler deliberately resets the form. These are the development task, not simulator defects. `benchmark.task.json` records the request and a reference edit plan; `tests/*.workflow.json` contain independently isolated acceptance scenarios. A real agent trial should receive the request and acceptance scenarios, keeping `reference_edits` hidden until evaluation.

The request is:

> Add a status filter with All, Draft and Active options, defaulting to All. Filter the gallery and keep the visible project count correct. Preserve entered title and budget values and show an error when a save fails, so the user can retry without retyping. Keep record selection and required-title validation working. The app must fit desktop and 400-pixel-wide previews.

Connect an AI client through the simulator's **AI tools** dialog. Use this sequence:

1. `describe_project` supplies the project identity and source/schema revision.
2. `read_controls(query="Projects")`, `read_control` and `read_list_schema(name="Projects")` supply focused context.
3. `stage_control_edits` stages a filter control, the gallery Items formula and the failure handler together. Inspect its diff and diagnostics.
4. `list_workflows(include_scenarios=false)` and `run_workflows` verify all scenarios against the staged ID without changing the preview or records. Investigate failures with `read_workflow_report`.
5. `apply_change` applies the candidate using its base revision. Explicitly call `restart_preview` with the returned `after_revision` to load it and reset the preview.
6. Inspect the app in the browser. The simulator supports a 400×900 viewport for the narrow layout check.
7. `export_source` returns Power Apps YAML and separate App properties. `undo_change` can restore the source; restart again to preview the restored version.

The acceptance scenarios check default/Draft/Active filtering and counts, editing the selected filtered row without altering another record, preserving both entered values and the stored record after failure, a successful retry without duplicate records, and a required-title save gate. The last scenario also runs at 400×900. Browser verification checks actual interaction, retained input, disabled saves, desktop/narrow geometry and JavaScript errors. Formula workflows alone do not verify appearance.

## Compare tool overhead

```sh
.venv/bin/python -m powerapps_sim.benchmark --json test-results/ai-development-benchmark.json
```

This command creates two temporary starter projects and replays the same reference feature in each. The full-document mode reads source/records, sends replacement source and retrieves individual complete workflow reports. The focused mode discovers controls/schemas, sends targeted edits and retrieves a concise batch result. Both verify candidate workflows, preview startup, export and source/data restoration after undo. Both also record the deliberately failing starter workflows. Every run uses its own project; existing projects remain untouched.

The JSON contains per-tool request/response UTF-8 JSON byte counts, call counts and elapsed tool time. The same serializer is used for both modes; SDK protocol envelopes and tool schemas are excluded. Reports identify assertions, diagnostics, revisions and undo verification. This is a **reference replay, not an AI model benchmark**. Model token use and manual intervention counts are null because they are not measured. No claim about reasoning quality or generation speed follows from payload size alone. Timing varies by machine and includes local validation/workflow execution.

For an actual agent comparison, run the request against fresh starter projects, record client token usage and human interventions, and retain the staged diffs and workflow evidence. Use multiple feature requests before treating any result as representative of app development overall.

## Run actual AI authoring

With an authenticated Codex CLI and the optional MCP dependency installed:

```sh
.venv/bin/python -m powerapps_sim.agent_benchmark --output test-results/ai-agent-benchmark
```

This invokes a fresh `codex exec --json --ephemeral` session for each mode, retaining the user's model/provider settings. The starter's reference edits are removed before invocation. The AI receives the request and discovers the saved acceptance scenarios through simulator tools; it generates, tests and applies its own changes. Full-document mode exposes source/record reads, full replacements and individual workflow runs. Focused mode exposes control/schema reads, targeted edits and batch runs. Neither mode receives the reference solution or access to another trial's context. Shell tools, plugins, other MCP servers, web search and delegation are disabled for the invocation; non-simulator activity makes a trial fail.

The simulator MCP server owns only the disposable trial app. Its invocation-local `default_tools_approval_mode="approve"` permits the explicitly authorized apply/restart actions. The user's stored configuration and ordinary simulator annotations are unchanged. Without this policy, the CLI's non-interactive approval policy can reject these actions even when the candidate passes. See the [official MCP configuration documentation](https://learn.chatgpt.com/docs/extend/mcp).

The output directory must not contain an earlier trial with the same mode. Use a new directory to retain failed attempts. `--mode focused` runs just one mode; `--timeout 900` bounds each model invocation. This command consumes real model usage; the reference replay above does not.

`report.json` contains client-reported input, cached-input and output tokens, completed MCP calls (including rejected calls), service invocation counts, failures, payload bytes and wall time. Cached input is part of input tokens; reasoning tokens are part of output tokens. Neither is added again to the total. Tokens come from `turn.completed.usage`, as described in [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode); missing usage remains null and fails the measurement. Raw `client.jsonl`, `simulator.jsonl`, the task prompt, staged diffs and exported source are retained locally for audit.

Manual interventions mean human corrective prompts or edits after a trial starts. The harness sends one initial task, has no interactive follow-up, and records zero corrective prompts. Automated fixture setup, independent scoring and undo are excluded from agent call/token metrics. A setup correction between attempts must be reported separately, alongside the failed attempt's usage. The scorer reruns acceptance scenarios, checks source export and desktop/narrow geometry, confirms records were preserved and verifies undo. Browser interaction remains a separate check. One sample per mode demonstrates feasibility and measured cost for this task; it does not establish a general speedup.

The [11 October 2026 actual AI trial](benchmarks/2026-10-11/README.md) retains measured results, setup failures and both AI-authored source exports.

The simulator exports source rather than an importable `.msapp`. These checks establish local behavior for the tested flows; they do not certify native Power Apps compatibility.

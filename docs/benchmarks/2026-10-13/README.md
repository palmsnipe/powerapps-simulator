# Actual AI creation trial · 13 October 2026

[Benchmark guide](../../ai-development.md#benchmark-creation-from-an-empty-workspace) · [Measured results](report.json)

Codex CLI 0.162.1 used the configured `gpt-6.1-sol` model with high reasoning effort to create a task app from an empty workspace. The model supplied the YAML, local schema, three fictional seed rows and three saved acceptance workflows through `create_project`. It then generated staged edits for an All/Open/Done filter, tested the candidate, applied it, restarted the preview and exported the source. Only simulator MCP tools were enabled. There was no reference app or edit replay, direct file editing, shell, web, delegation or Microsoft connection.

| Measured activity | Initial attempt | Completed attempt | Experiment total |
| --- | ---: | ---: | ---: |
| Outcome | Incomplete; filter left staged | Passed | One completed app |
| Client MCP calls / simulator calls | 28 / 28 | 22 / 22 | 50 / 50 |
| Rejected tool calls | 9 | 3 | 12 |
| Input tokens | 671,158 | 455,938 | 1,127,096 |
| Cached input tokens, included above | 612,864 | 397,696 | 1,010,560 |
| Output tokens | 9,543 | 6,343 | 15,886 |
| Reasoning tokens, included in output | 3,326 | 1,539 | 4,865 |
| Total input + output tokens | 680,701 | 462,281 | 1,142,982 |
| Model invocation time | 319.76 s | 200.40 s | 520.16 s |
| Simulator service execution time | 5.23 s | 3.59 s | 8.82 s |
| Service request bytes | 141,340 | 68,909 | 210,249 |
| Service response bytes | 54,864 | 36,049 | 90,913 |
| Human corrective interventions | 0 | 0 | 0 |
| Corrective prompts during a session | 0 | 0 | 0 |

The completed attempt passed the AI's three saved workflows on the initial app and seven candidate workflows after editing. Four independent scenarios passed adding a trimmed title, blocking whitespace input, retaining input after write failure and retrying once, status filtering/counts, and toggling the correct filtered record. Independent scoring verified the schema, intrinsically read-only IDs, unchanged schema/seed data/saved workflows, exported source, clean diagnostics, desktop/narrow bounds without overlapping top-level controls, and undo to the AI's created source. Chromium verified actual filter/toggle interaction, title validation, failed-write retry, trimmed creation, the narrow preview and zero JavaScript errors. Scoring, undo and browser writes ran on copies; the retained trial app remains applied with its original three seed rows.

The initial attempt guessed several workflow step formats, schema conventions and YAML quoting rules, resulting in eight rejected creation calls. It eventually created the base app, then found errors in its own saved tests: clicking disabled buttons without `expect_blocked` and using an uninstantiated gallery scope. The task forbids changing saved tests after creation. The model verified corrected inline tests and staged the filter, but correctly declined to apply while the saved tests failed. Independent scoring also found that the authored schema did not declare the required Title field at the list level. This unsuccessful attempt and all its usage remain in the report.

Between attempts, the coordinating AI added serialization guidance to the initial prompt: the `op` step key, blocked-event and gallery-instance rules, a generic local schema example, and YAML quoting. The next attempt received a fresh context/workspace and no source or reference edit solution. It recovered from two rejected creation calls and one invalid selection request, and corrected a dropdown candidate that failed inspection before its final passing batch. This is **one automated prompt adjustment**, not a human correction or an in-session follow-up. Both [initial](attempt-1.prompt.txt) and [revised](attempt-2.prompt.txt) prompts are retained; these runs are not a controlled comparison of identical prompts.

Two independent scorer corrections required no additional model calls: canonicalizing the cloned project's path for identity checks, and probing read-only ID behavior instead of requiring an optional metadata spelling. The simulator protects IDs intrinsically. Both attempts were rescored with these corrections; the first remained failed and the second passed. The report retains the original scoring error and the corrections. The CLI also emitted its ordinary development-feature warning; this was not a model or simulator failure.

Tokens are native `turn.completed.usage` counts. Cached input is already included in input; reasoning is already included in output. Model time stops when the Codex subprocess exits and excludes automatic scoring/browser work. Byte counts measure shared-service arguments/results, excluding MCP protocol envelopes and tool schemas. The coordinating chat, harness preparation and automatic verification are excluded from model metrics. Zero manual interventions therefore means no human corrective prompts or app edits after either session started; it does not mean the experiment had no automated setup adjustments.

The [completed source](attempt-2.final.pa.yaml), [AI-created initial source](attempt-2.initial.pa.yaml) and [creation inputs including schema/data/workflows](attempt-2.project-inputs.json) are committed alongside the failed attempt's equivalent artifacts. Raw client/service logs and screenshots remain under `test-results/ai-creation-2026-10-13`; their sizes and SHA-256 hashes are in the report. To open the retained completed app after the benchmark subprocess has closed:

```sh
.venv/bin/python -m powerapps_sim --import test-results/ai-creation-2026-10-13/attempt-2/projects/task-desk
```

Creation and continued editing are feasible without human correction for this task. Tool-contract discovery is the clearest improvement opportunity: expose the nested workflow/schema contracts and precise validation errors so the model can avoid repeated complete creation requests. One small app and one completed sample do not establish a general speedup, large-data correctness or native Power Apps compatibility.

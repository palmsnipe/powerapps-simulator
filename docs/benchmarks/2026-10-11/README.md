# Actual AI authoring trial · 11 October 2026

[Benchmark guide](../../ai-development.md) · [Measured results](report.json)

Codex CLI 0.161.0 used the configured `gpt-6.1-sol` model with high reasoning effort to implement status filtering and failed-save recovery through the local simulator. Each mode received a fresh unfinished app, the same request and saved acceptance workflows. Reference edits were removed before invocation. The model generated its own edits and used only simulator MCP tools; there were no shell calls, direct file edits, web searches, Microsoft connections or corrective prompts.

| Completed trial | Full-document tools | Focused tools |
| --- | ---: | ---: |
| Simulator / client MCP calls | 20 | 13 |
| Failed calls, recovered by the model | 1 | 0 |
| Input tokens | 340,599 | 257,830 |
| Cached input tokens, included above | 299,520 | 231,680 |
| Output tokens | 1,872 | 1,765 |
| Total input + output tokens | 342,471 | 259,595 |
| Model invocation wall time | 60.28 s | 62.65 s |
| Service request bytes | 14,643 | 7,721 |
| Service response bytes | 110,214 | 51,634 |
| Human corrective interventions | 0 | 0 |

Both candidates passed all four acceptance workflows, preserved stored records, exported the applied source and passed independent undo verification. Browser checks against the actual AI-generated source confirmed filtering, selected-row edits, retained title/budget after a failed save, successful retry, required-title validation, narrow geometry and no JavaScript errors. The exported sources are retained as [full_document.pa.yaml](full_document.pa.yaml) and [focused.pa.yaml](focused.pa.yaml).

The focused trial used 35% fewer calls, 24.2% fewer total tokens and 53.2% fewer response bytes. Wall time was similar and slightly higher for the focused trial. This is one task with one completed sample per mode; it does not establish a general development speedup. Full-document ran first, and model prefix caching and sampling varied. Tokens are the CLI's native usage counts, not estimates from payload sizes. The coordinating chat and automated setup/scoring/browser checks are excluded from those counts.

The initial two attempts passed their candidate acceptance tests but could not apply: the CLI rejected `apply_change` under its default MCP approval policy. Those attempts used 17 and 12 client MCP calls and 253,389 and 200,341 tokens respectively. Two rejected calls never reached the simulator service. The coordinating AI corrected the invocation-local approval policy for the disposable server and reran both modes with fresh contexts/apps. No human input or app fix was required. The ordinary simulator annotations and stored user configuration were unchanged.

Including these setup attempts, the experiment consumed **62 client MCP calls**, **60 simulator service invocations** and **1,055,796 input + output tokens** (897,664 cached input tokens included), with **zero human interventions**. The report retains all four attempts, the configuration correction, per-call metrics, staged diffs, verification results and SHA-256 hashes of local raw evidence. Raw client/tool logs and screenshots remain under the ignored `test-results` directories.

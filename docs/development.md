# Development and verification

[Documentation index](README.md) · [Project README](../README.md)

## Install development dependencies

Inside a virtual environment:

```sh
python -m pip install -r requirements.txt
python -m pip install -e ".[test,mcp]"
python -m playwright install chromium
```

Use the virtual environment's Python for all commands below. The MCP dependency is optional when running the browser application.

## Code structure

| Location | Responsibility |
| --- | --- |
| `powerapps_sim/source.py` | Lossless project import/export and YAML source model |
| `syntax.py`, `binding.py`, `fx.py`, `runtime.py` | Power Fx parsing, type binding, evaluation, and runtime state |
| Other modules under `powerapps_sim/` | Formula families, control contracts, scopes, layout, and reactivity |
| `application.py`, `ownership.py` | Workspace ownership, locking, and runtime lifecycle |
| `store.py`, `sharepoint.py`, `catalog.py` | SQLite data, SharePoint-shaped values, and authored schemas |
| `authoring.py`, `workflows.py`, `ai_service.py` | Reviewed changes, isolated scenarios, and shared AI operations |
| `ai_authoring.py`, `benchmark.py`, `agent_benchmark.py` | Focused source discovery/control edits, reference tool-overhead replay and measured real AI authoring |
| `web.py`, `static/` | Flask endpoints and the browser editor/preview |
| `mcp_server.py` | Optional stdio MCP adapter using the same workspace services |
| `examples/`, `fixtures.py` | Public fictional source, datasets, and comparison projects |
| `conformance_cases/`, `conformance.py` | Selected pinned Microsoft expression cases and offline reference harness |
| `tests/` | Backend, protocol, workflow, and browser regression tests |
| `tools/` | Offline bundle and pinned icon-generation scripts |

The Python runtime is authoritative. The browser and MCP adapter share one workspace owner; a headless client must not open a second runtime against a project already owned by the browser server. Project data lives outside the package and is ignored by Git. See [AI and workflows](ai-workflows.md) for authoring and ownership details.

## Verification

```sh
python -m pytest -q --ignore=tests/test_browser.py --ignore=tests/test_ai_development_browser.py
python -m pytest -q tests/test_browser.py tests/test_ai_development_browser.py
python -m powerapps_sim.conformance --json compatibility-report.json
```

Browser tests require Playwright's Chromium. Private compatibility-archive tests are optional and skip when `POWERAPPS_SAMPLE` is unset; they target the original archived test fixture rather than an arbitrary imported app. The public examples and selected corpus are bundled.

The GitHub workflow runs the complete suite on Linux, macOS, and Windows with Python 3.11–3.14. A partial local run is not evidence that this matrix passes. Known conformance gaps remain reported separately from unexpected regressions; `--strict` also fails on known gaps.

## Build packages and offline bundles

```sh
python -m pip wheel --no-deps . -w dist
python tools/build_offline.py
python tools/build_offline.py --with-mcp
```

The core offline bundle targets the documented Windows/macOS Python versions. Optional MCP bundles are specific to the build computer's OS, architecture, and Python minor. Building bundles downloads dependencies; installing and running a generated core bundle can work offline.

Repository documentation is included in source distributions and offline ZIPs. Python wheels include runtime resources and licence notices; the README supplies links to the repository guides. Keep launcher commands, package metadata, docs, and bundle contents consistent when renaming or changing packaging.

## Before committing

Review the actual Git file list so private imports, databases, local test results, generated packages, and credentials stay outside the commit. Run checks appropriate to the changed source and report failures honestly. Preserve third-party notices and keep compatibility claims scoped to verified behaviour. Add focused regressions for behaviour fixes; documentation edits need link and packaging checks.

Earlier package-reorganization proposals and milestone plans are retained in [History](history.md).

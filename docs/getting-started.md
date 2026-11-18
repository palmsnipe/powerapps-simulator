# Getting started

[Documentation index](README.md) · [Project README](../README.md)

Install from source, import an app, or build an offline bundle.

## Run from source

Python **3.11–3.14** is the supported target. Open a terminal in this directory.

macOS / Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m powerapps_sim
```

Windows:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m powerapps_sim
```

The browser opens at **http://127.0.0.1:8765**. The initial project is a fictional working demo. `start.sh` and `start.cmd` provide shortcuts after setup. Stop the server with Ctrl+C in its terminal.

Import an app with the UI or the command line:

```sh
.venv/bin/python -m powerapps_sim --import "/path/to/example.msapp"
```

Use `--workspace /path/to/projects` to change storage, `--port 8766` to change ports, and `--no-browser` to suppress automatic opening. Open an existing project by its folder ID with `./start.sh --project-id task-tracker` (or `start.cmd --project-id task-tracker` on Windows), or select it in the project menu.

One launch serves the browser preview and its workspace API. Keep it running and copy the connection settings from **AI tools** when adding a local MCP client. The header shows the active project ID, saved source and schema revision, preview state and connected MCP adapters. [Connect an AI client](ai-workflows.md#connecting-an-ai-client-through-mcp)

The server listens on `127.0.0.1` and accepts requests addressed to `localhost` or `127.0.0.1`. Use one of those addresses for both the browser and MCP connection.

## Move a simulator project

Choose **Export project bundle** to download a `.pasim` with the saved source, assets, schema catalog, saved workflows and simulator settings. Select **Include local list records** if the recipient needs the current mock dataset. Leave it unchecked to start with empty lists. Workflows that rely on those records need them restored or seeded before validation. The bundle also carries the saved simulated people and environment settings. Check those settings before sharing the file.

Use **Import app** or `./start.sh --import /path/to/app.pasim` in the destination workspace. Import creates a new project with a fresh database and opens it with startup paused. Select **Start preview** when you are ready for the startup rules to run. To check the local copy independently, use **Workflows → Validate saved suite**.

## Hand off controls to Power Apps Studio

Select the control in the simulator inspector and copy its control source. In a signed-in Power Apps Studio app, paste it onto the target screen or parent control using the documented clipboard workflow. Allow clipboard access if the browser prompts. Reconnect data sources and check the control's formulas, layout and behavior in Studio. [Use code view in Power Apps Studio](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/code-view)

**Export source** downloads a ZIP of YAML and assets for review. Use `.pasim` to reopen the complete project in the simulator. For native app packaging, use Power Apps Studio and its supported source workflow. [Power Apps canvas source code files](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/power-apps-yaml)

## Offline setup on a work computer

The generated `dist/powerapps-sim-offline.zip` includes the application wheel, all pinned runtime dependencies, and setup/start scripts, the MIT licence and this documentation. Copy it to the other computer and extract it into a writable folder. Python must already be installed; the bundle does not install Python or change operating-system settings.

- Windows: run `setup_offline.cmd`, then `start.cmd`.
- macOS: in Terminal run `sh setup_offline.sh`, then `sh start.sh`.

The core bundle includes Python wheels plus pinned regex wheels for CPython 3.11–3.14 on Windows x64/ARM64 and macOS Intel/Apple Silicon. MarkupSafe uses its pure Python implementation. Installation needs neither a network connection nor a compiler. The application has no separate native runtime dependency. Windows/macOS setup scripts are supplied; automated execution has been verified on the development Mac, not on a physical Windows computer or every Python minor version.

To regenerate the bundle on a computer with internet access:

```sh
.venv/bin/python tools/build_offline.py
```

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

Use `--workspace /path/to/projects` to change storage, `--port 8766` to change ports, and `--no-browser` to suppress automatic opening. To reopen an imported project without importing a duplicate, pass its project directory to `--import`, or choose it in the project menu.

The server listens on `127.0.0.1` and accepts requests addressed to `localhost` or `127.0.0.1`. Other Host names return HTTP 400; use one of these loopback addresses for the browser and MCP connection.

## Offline setup on a work computer

The generated `dist/powerapps-sim-offline.zip` includes the application wheel, all pinned runtime dependencies, and setup/start scripts, the MIT licence and this documentation. Copy it to the other computer and extract it into a writable folder. Python must already be installed; the bundle does not install Python or change operating-system settings.

- Windows: run `setup_offline.cmd`, then `start.cmd`.
- macOS: in Terminal run `sh setup_offline.sh`, then `sh start.sh`.

The core bundle includes Python wheels plus pinned regex wheels for CPython 3.11–3.14 on Windows x64/ARM64 and macOS Intel/Apple Silicon. MarkupSafe uses its pure Python implementation. Installation needs neither a network connection nor a compiler. The application has no separate native runtime dependency. Windows/macOS setup scripts are supplied; automated execution has been verified on the development Mac, not on a physical Windows computer or every Python minor version.

To regenerate the bundle on a computer with internet access:

```sh
.venv/bin/python tools/build_offline.py
```

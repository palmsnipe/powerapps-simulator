import argparse
from pathlib import Path
import threading
import webbrowser

from .application import workspace_project_path
from .web import create_app


def main():
    parser = argparse.ArgumentParser(description="Offline Power Apps simulator")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--import", dest="initial", help="Import a .pasim/.msapp/YAML file or open a local project directory")
    selection.add_argument("--project-id", help="Open an existing project ID in this workspace")
    parser.add_argument("--workspace", default=str(Path.cwd() / "projects"), help="Local project storage directory")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    initial = args.initial
    if args.project_id:
        try:
            initial = workspace_project_path(Path(args.workspace).resolve(), args.project_id)
        except ValueError as error:
            parser.error(str(error))
    app = create_app(args.workspace, initial)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Power Apps Simulator · {url}\nProjects: {Path(args.workspace).resolve()}\n"
          f"MCP uses the same session. Open AI tools in the editor for stdio client settings.", flush=True)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()

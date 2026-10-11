import argparse
from pathlib import Path
import threading
import webbrowser

from .web import create_app


def main():
    parser = argparse.ArgumentParser(description="Offline Power Apps simulator")
    parser.add_argument("--import", dest="initial", help="Import an .msapp/YAML file or open a local project directory")
    parser.add_argument("--workspace", default=str(Path.cwd() / "projects"), help="Local project storage directory")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    app = create_app(args.workspace, args.initial)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Power Apps Simulator · {url}\nProjects: {args.workspace}")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()

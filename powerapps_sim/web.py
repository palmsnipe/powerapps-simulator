"""Local editor HTTP interface. All runtime mutations are serialized."""
from __future__ import annotations

import csv
from io import BytesIO, StringIO
import json
import sys
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
from zipfile import BadZipFile

from flask import Flask, jsonify, request, send_file, send_from_directory

from .runtime import Runtime, serial
from .scenarios import PEOPLE, demo_definitions, seed
from .source import Control, Project, safe_path
from .syntax import FxError
from .sharepoint import complex_kind


from .application import Workspace
from .authoring import RevisionConflict, revision


def create_app(workspace_root=None, initial=None):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    # The CLI listens on IPv4 loopback. Reject rebinding domains before exposing
    # source, records, or mutation endpoints, even when they supply our header.
    app.config["TRUSTED_HOSTS"] = ["localhost", "127.0.0.1"]
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
    workspace = Workspace(workspace_root or Path.cwd() / "projects", initial)
    app.extensions["workspace"] = workspace

    @app.before_request
    def local_write():
        if request.method in ("POST", "PUT", "DELETE") and request.headers.get("X-Emulator-Request") != "1":
            return jsonify(error="Use the local simulator interface"), 403

    @app.errorhandler(ValueError)
    @app.errorhandler(FxError)
    @app.errorhandler(BadZipFile)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(error="Import exceeds the 50 MB upload limit"), 413

    @app.errorhandler(RevisionConflict)
    def conflict(error):
        return jsonify(error=str(error), conflict=True, revision=revision(workspace.project.root)), 409

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/project")
    def project():
        with workspace.lock:
            return jsonify(workspace.summary())

    @app.get("/api/projects")
    def projects():
        found = []
        for path in workspace.root.iterdir():
            config = path / "emulator.json"
            if path.is_dir() and config.exists():
                found.append({"id": path.name, "title": json.loads(config.read_text(encoding="utf-8"))["title"]})
        return jsonify(found)

    @app.get('/api/ai-connection')
    def ai_connection():
        with workspace.lock:
            try:
                sdk = version('mcp')
            except PackageNotFoundError:
                sdk = None
            return jsonify(command=sys.executable,
                args=['-m', 'powerapps_sim.mcp_server', '--url', request.host_url.rstrip('/'),
                      '--expect-project', str(workspace.project.root)],
                transport='stdio', sdk_version=sdk, required_sdk='2.3.0',
                install_command=f'"{sys.executable}" -m pip install "mcp==2.3.0"',
                project_path=str(workspace.project.root))

    @app.post('/api/ai/<operation>')
    def ai_operation(operation):
        payload = request.get_json()
        if not isinstance(payload, dict) or set(payload) - {'arguments', 'expected_project'}:
            raise ValueError('Provide operation arguments and expected_project')
        return jsonify(workspace.ai.call(operation, payload.get('arguments'), expected_project=payload.get('expected_project')))

    @app.get('/api/workflows')
    def workflows():
        return jsonify(workspace.workflows.catalog())

    @app.post('/api/workflows/run')
    def run_workflow():
        j = request.get_json()
        if not isinstance(j, dict) or set(j) - {'scenario', 'expected_revision', 'change_id'}:
            raise ValueError('Provide scenario, expected_revision and optional change_id')
        return jsonify(workspace.workflows.run(j.get('scenario'), expected_revision=j.get('expected_revision'), change_id=j.get('change_id')))

    @app.get('/api/workflows/runs/<run_id>')
    def workflow_report(run_id):
        return jsonify(workspace.workflows.report(run_id))

    @app.post("/api/project/open")
    def open_project():
        with workspace.lock:
            directory = safe_path(workspace.root, request.json["id"])
            if not (directory / "emulator.json").exists():
                raise ValueError("Project not found")
            workspace.open(Project(directory))
            return jsonify(workspace.summary())

    @app.post("/api/import")
    def import_file():
        with workspace.lock:
            if "file" in request.files:
                file = request.files["file"]
                workspace.import_file(file.filename, file.read())
            else:
                workspace.import_file("Pasted.pa.yaml", request.json["text"].encode("utf-8"))
            return jsonify(workspace.summary())

    @app.get("/api/source")
    def source():
        with workspace.lock:
            name = request.args["name"]
            current = Project(workspace.project.root)
            if name not in current.documents:
                raise ValueError("Source not found")
            draft = safe_path(workspace.project.root, "drafts/" + name)
            current_revision = revision(current.root)
            draft_base = current.read_json('drafts/revisions.json', {}).get(name)
            stale = bool(draft_base and draft_base != current_revision)
            return jsonify(text=current.documents[name], draft=draft.read_text(encoding="utf-8") if draft.exists() and not stale else None,
                draft_stale=stale and draft.exists(), revision=current_revision)

    @app.post("/api/source")
    def save_source():
        with workspace.lock:
            try:
                j = request.json
                workspace.authoring.save_source(expected_revision=j.get('expected_revision'),
                    name=j.get('name'), property=j.get('property'), text=j['text'])
            except RevisionConflict:
                raise
            except Exception as error:
                return jsonify(error=str(error), draft_saved=bool(getattr(error, 'draft_saved', False))), 400
            return jsonify(workspace.summary())

    @app.get('/api/changes')
    def changes():
        with workspace.lock:
            return jsonify(revision=revision(workspace.project.root), changes=workspace.authoring.history())

    @app.post('/api/changes')
    def stage_change():
        payload = request.json
        if not isinstance(payload, dict):
            raise ValueError('Change request must be an object')
        if payload.keys() - {'expected_revision', 'sources', 'lists', 'migrations', 'title', 'strict'}:
            raise ValueError('Unknown change fields')
        payload.setdefault('expected_revision', None)
        return jsonify(workspace.authoring.stage(**payload))

    @app.post('/api/changes/<change_id>/apply')
    def apply_change(change_id):
        return jsonify(workspace.authoring.apply(change_id, expected_revision=request.json.get('expected_revision')))

    @app.post('/api/changes/<change_id>/undo')
    def undo_change(change_id):
        return jsonify(workspace.authoring.undo(change_id, expected_revision=request.json.get('expected_revision')))

    @app.post("/api/restart")
    def restart():
        with workspace.lock:
            workspace.open(Project(workspace.project.root))
            return jsonify(workspace.runtime.state())

    @app.get("/api/state")
    def state():
        with workspace.lock:
            return jsonify(workspace.runtime.state())

    @app.post('/api/time/pulse')
    def time_pulse():
        with workspace.lock:
            j=request.get_json()
            if not isinstance(j,dict) or set(j)!={'token','playing'}:raise ValueError('Provide timer token and Boolean play state')
            from .timers import pulse
            if not pulse(workspace.runtime,j['token'],j['playing']):return jsonify(stale=True)
            return jsonify(workspace.runtime.state())

    @app.post('/api/time/control')
    def time_control():
        with workspace.lock:
            j=request.get_json()
            if not isinstance(j,dict) or set(j)!={'token','playing'} or not isinstance(j['token'],str) or not isinstance(j['playing'],bool):raise ValueError('Provide timer token and Boolean play state')
            r=workspace.runtime
            if j['token']!=r.timer_token:return jsonify(stale=True)
            r.timer_playing=j['playing'];r.timer_live=False;r.timer_wall=None
            return jsonify(r.state())

    @app.post('/api/time/advance')
    def time_advance():
        with workspace.lock:
            j=request.get_json()
            if not isinstance(j,dict) or set(j)!={'token','milliseconds'} or not isinstance(j['token'],str):raise ValueError('Provide timer token and milliseconds')
            from .timers import advance
            r=workspace.runtime
            if j['token']!=r.timer_token:return jsonify(stale=True)
            r.timer_live=False;r.timer_wall=None
            advance(r,j['milliseconds'])
            return jsonify(r.state())

    @app.post("/api/richtext/sanitize")
    def sanitize_rich_text():
        with workspace.lock:
            j=request.get_json()
            if not isinstance(j,dict) or set(j)!={"path","html","reset_token"}:raise ValueError("Provide rich text path, HTML and reset token")
            if any(not isinstance(j[k],str) for k in ("path","html","reset_token")):raise ValueError("Rich text path, HTML and reset token must be strings")
            ref=workspace.runtime.refs.get(j["path"])
            if ref is None or ref.family!="RichTextEditor":raise ValueError("Rich text editor no longer exists")
            ref.sync_default("HtmlText")
            if j["reset_token"]!=workspace.runtime.text_token(ref):return jsonify(stale=True)
            from .rich_text import sanitize,issues
            result=sanitize(j["html"]);issues(workspace.runtime,ref,result["issues"])
            return jsonify(**result)

    @app.post("/api/event")
    def event():
        with workspace.lock:
            j = request.json
            workspace.runtime.event(j["path"], j["name"], j.get("value"), j.get("selection"))
            return jsonify(workspace.runtime.state())

    @app.get("/api/analysis")
    def analysis():
        with workspace.lock:
            return jsonify(workspace.runtime.analysis())

    @app.post("/api/screen")
    def screen():
        with workspace.lock:
            name = request.json.get("name")
            if name is not None and name not in workspace.runtime.screens:
                raise ValueError("Unknown screen")
            workspace.runtime.preview_screen = name
            workspace.runtime.preview_component = None
            workspace.runtime.invalidate()
            if request.json.get("initialize") and name:
                workspace.runtime.run_event(workspace.runtime.screens[name], "OnVisible")
            return jsonify(workspace.runtime.state())

    @app.post("/api/component")
    def component_preview():
        with workspace.lock:
            r = workspace.runtime
            name = request.json["name"]
            if name not in r.project.components:
                raise ValueError("Component not found in running source; restart after edits")
            definition = r.project.components[name]
            control = Control(name, "CanvasComponent", {"Control": "CanvasComponent", "ComponentName": name,
                "Properties": dict(definition.properties)}, definition.source)
            root = Control(name + " preview", "Screen", {"Properties": {}}, definition.source)
            ref = r.build(root, "__component__:" + name)
            ref.children = [r.build(control, ref.path + "/" + name, ref)]
            r.preview_component = ref
            r.preview_screen = None
            r.invalidate()
            return jsonify(r.state())

    @app.get("/api/control")
    def control():
        with workspace.lock:
            r = workspace.runtime
            ref = r.refs.get(request.args.get("path"))
            if not ref:
                raise ValueError("Control not found; render its screen first")
            values = {}
            from .controls import inspect_properties
            for key in inspect_properties(ref):
                if key.startswith("On"):
                    values[key] = "<behavior formula>"
                else:
                    try:
                        values[key] = serial(ref.property(key))
                    except FxError as error:
                        values[key] = serial(error)
            rendered_bounds=None
            if ref.family=='TypedDataCard' and ref.parent and ref.parent.family=='Form':
                from .form_layout import bounds
                try:rendered_bounds=bounds(ref.parent)['cards'].get(ref.path)
                except FxError:pass
            return jsonify(name=ref.name, kind=ref.control.kind, source=ref.control.source, rendered_bounds=rendered_bounds,
                formulas={k: str(v) for k, v in ref.control.properties.items()}, values=values,
                export=workspace.project.export_control(ref.name) if ref.name in workspace.project.controls else "")

    @app.get("/api/component-inspection")
    def component_inspection():
        with workspace.lock:
            from .component_inspection import describe
            return jsonify(describe(workspace.runtime, evaluate=True))

    @app.get('/api/dependencies')
    def dependencies():
        with workspace.lock:
            return jsonify(workspace.ai.call('read_dependencies',{
                'query':request.args.get('query',''),'offset':int(request.args.get('offset',0)),
                'limit':int(request.args.get('limit',100))}))

    @app.get("/api/export")
    def export():
        with workspace.lock:
            if request.args.get("control"):
                return jsonify(text=workspace.project.export_control(request.args["control"]))
            return send_file(BytesIO(workspace.project.export()), mimetype="application/zip", as_attachment=True, download_name="powerapps-source.zip")

    @app.get("/api/asset/<path:name>")
    def asset(name):
        if not name.startswith("Assets/"):
            raise ValueError("Not an app asset")
        return send_file(safe_path(workspace.project.root, name))

    @app.get("/api/lists/<name>")
    def list_data(name):
        with workspace.lock:
            store = workspace.runtime.store
            store.source(name)
            entry = store.catalog.read().get(name)
            field_options, option_errors = {}, {}
            for field, schema in store.definitions[name]['fields'].items():
                if complex_kind(schema, store.definitions[name], field):
                    try:
                        field_options[field] = serial(store.choices(name, field, workspace.runtime.people))
                    except FxError as error:
                        option_errors[field] = str(error)
            from .data_errors import rows as error_rows
            return jsonify(errors=serial(error_rows(store,name)), definition=entry[1] if entry else store.definitions[name], rows=store.rows(name), failure=store.failures.get(name),
                field_options=field_options, option_errors=option_errors,
                schema_path=store.catalog.path(name).relative_to(workspace.project.root).as_posix(), revision=revision(workspace.project.root))

    @app.post("/api/lists")
    def add_list():
        with workspace.lock:
            name = request.json.get("name", "").strip()
            if not name or name in workspace.runtime.store.definitions:
                raise ValueError("Choose a new, nonempty list name")
            definition = request.json.get("definition", {})
            if not isinstance(definition.get("fields"), dict):
                raise ValueError("List definition needs fields")
            entry = workspace.authoring.stage(expected_revision=request.json.get('expected_revision'), lists={name: definition}, title='Add list '+name)
            workspace.authoring.apply(entry['id'], expected_revision=request.json['expected_revision'])
            return jsonify(workspace.summary())

    @app.post("/api/lists/<name>")
    def list_write(name):
        with workspace.lock:
            r = workspace.runtime
            r.store.source(name)
            j = request.json
            if "definition" in j:
                d = {**r.store.definitions[name], **j["definition"]}
                if not isinstance(d.get("fields"), dict):
                    raise ValueError("List definition needs fields")
                if len(j.keys() - {'definition', 'expected_revision', 'migration'}) != 0:
                    raise ValueError('Apply a schema change separately from record/failure edits')
                entry = workspace.authoring.stage(expected_revision=j.get('expected_revision'), lists={name: d},
                    migrations={name: j.get('migration', {})}, title='Edit list '+name)
                workspace.authoring.apply(entry['id'], expected_revision=j['expected_revision'])
            if "failure" in j:
                if j["failure"] not in (None, "read", "write", "all"):
                    raise ValueError("Unknown failure mode")
                if j["failure"]:
                    r.store.failures[name] = j["failure"]
                else:
                    r.store.failures.pop(name, None)
            if "rows" in j:
                r.store.import_rows(name, j["rows"], replace=j.get("replace", False))
            r.invalidate()
            return jsonify(ok=True)

    @app.post("/api/lists/<name>/items")
    def list_item_write(name):
        with workspace.lock:
            r = workspace.runtime
            r.store.source(name)
            j = request.json
            if not isinstance(j, dict) or set(j) != {'id', 'changes', 'expected_record', 'expected_revision'}:
                raise ValueError('Record edit needs id, changes, expected_record and expected_revision')
            workspace.authoring.check_revision(j['expected_revision'])
            if not isinstance(j['changes'], dict):
                raise ValueError('Record changes must be an object')
            item_id = j['id']
            if item_id is not None and (type(item_id) is not int or item_id < 1):
                raise ValueError('Record ID must be a positive integer or null')
            base = {}
            if item_id is not None:
                id_field = r.store.definitions[name].get('mapping', {}).get('ID', 'ID')
                base = next((row for row in r.store.rows(name) if row.get(id_field) == item_id), None)
                from .workflows import _equal
                if base is None or not _equal(serial(base), j['expected_record']):
                    raise RevisionConflict('Record changed since it was opened. Reload it before saving.')
            elif j['expected_record'] is not None:
                raise ValueError('New records have no expected_record')
            row = r.store.patch(name, base, j['changes'])
            r.invalidate()
            return jsonify(record=serial(row))

    @app.post("/api/lists/<name>/import")
    def list_import(name):
        with workspace.lock:
            file = request.files["file"]
            content = file.read().decode("utf-8-sig")
            rows = list(csv.DictReader(StringIO(content))) if file.filename.lower().endswith(".csv") else json.loads(content)
            workspace.runtime.store.import_rows(name, rows)
            workspace.runtime.invalidate()
            return jsonify(ok=True, count=len(rows))

    @app.get("/api/lists/<name>/export")
    def list_export(name):
        with workspace.lock:
            store = workspace.runtime.store
            csv_format = request.args.get("format") == "csv"
            content = store.export_csv(name) if csv_format else json.dumps(store.rows(name), indent=2, ensure_ascii=False)
            return send_file(BytesIO(content.encode("utf-8")), mimetype="text/csv" if csv_format else "application/json",
                as_attachment=True, download_name=name + (".csv" if csv_format else ".json"))

    @app.post("/api/scenario")
    def scenario():
        with workspace.lock:
            r, p = workspace.runtime, workspace.project
            if request.json.get("reset"):
                r.store.failures.clear()
                seed(r.store, r.environment.get("clock"))
                p.config["people"] = PEOPLE
                p.save_config()
                r.people = PEOPLE
            if "environment" in request.json:
                env = request.json["environment"]
                from .reactivity import validate_seed
                validate_seed(env.get('random_seed'))
                if not isinstance(env.get("user"), dict) or not env["user"].get("Email"):
                    raise ValueError("A simulated user email is required")
                if env.get("clock"):
                    from .fx import date_value
                    date_value(env["clock"])
                from .numeric import NUMBER_MODES
                if env.get("number_mode", "float") not in NUMBER_MODES:
                    raise ValueError("Number mode must be float or decimal")
                previous_number_mode = r.environment.get("number_mode", "float")
                previous_enum_mode = r.environment.get("enum_mode","legacy")
                previous_regex_mode = r.environment.get("regex_mode","canvas")
                from .regex_fx import MODES
                if env.get("regex_mode","canvas") not in MODES:raise ValueError("Unknown regex compatibility profile")
                from .enum_fx import ENUM_MODES
                if env.get("enum_mode","legacy") not in ENUM_MODES:raise ValueError("Enum mode must be legacy or strong")
                from .temporal import NUMERIC_MODES
                if env.get("date_numeric_mode", "canvas-milliseconds") not in NUMERIC_MODES:
                    raise ValueError("Date numeric mode must be canvas-milliseconds or powerfx-days")
                from .overloads import ROUND_TABLE_MODES
                if env.get("round_table_mode", "canvas-zero") not in ROUND_TABLE_MODES:
                    raise ValueError("Round table mode must be canvas-zero or powerfx-errors")
                p.config["environment"] = env
                p.save_config()
                r.environment = env
                if previous_number_mode != env.get("number_mode", "float") or previous_enum_mode != env.get("enum_mode","legacy") or previous_regex_mode != env.get("regex_mode","canvas"):
                    r.binder.nodes.clear(); r.binder.node_refs.clear(); r.binder.named.clear(); r.binder.aliases.clear()
                    r.analyze()
            if "people" in request.json:
                p.config["people"] = request.json["people"]
                p.save_config()
                r.people = p.config["people"]
            if "viewport" in request.json:
                viewport = request.json["viewport"]
                if any(not isinstance(viewport.get(k), int) or not 200 <= viewport[k] <= 4000 for k in ("width", "height")):
                    raise ValueError("Viewport dimensions must be 200–4000 pixels")
                r.viewport = viewport
                p.config["viewport"] = viewport
                p.save_config()
            r.invalidate()
            return jsonify(r.state())

    @app.get("/api/checker")
    def checker():
        with workspace.lock:
            p = workspace.project
            results = []
            for run in p.read_json("metadata/checker.json", {}).get("runs", []):
                for result in run.get("results", []):
                    location = result.get("locations", [{}])[0]
                    message = result.get("message", {})
                    results.append({"rule": result.get("ruleId"), "severity": result.get("properties", {}).get("level"),
                        "message": message.get("text", ", ".join(map(str, message.get("arguments", [])))),
                        "member": location.get("physicalLocation", {}).get("address", {}).get("fullyQualifiedName"),
                        "snippet": location.get("physicalLocation", {}).get("region", {}).get("snippet", {}).get("text")})
            return jsonify(historical=True, source_edited=bool(p.config.get("source_edited")), results=results)

    return app

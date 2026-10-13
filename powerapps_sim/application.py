"""Python workspace owner shared by the HTTP interface and authoring CLI."""
from __future__ import annotations
import json
from pathlib import Path
import threading
import uuid
from .runtime import Runtime
from .source import Project
from .scenarios import PEOPLE, demo_definitions, seed
from .authoring import AuthoringService, revision, recover_changes
from .ownership import ProjectLease


class Workspace:
    def __init__(self, root, initial=None, *, start=True, empty=False):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.project, self.runtime = None, None
        self.start_simulation = start
        self.authoring = AuthoringService(self)
        from .workflows import WorkflowService
        self.workflows = WorkflowService(self)
        from .ai_service import AIService
        self.ai = AIService(self)
        if initial:
            path = Path(initial)
            if path.is_dir():
                self.open(Project(path))
            else:
                self.import_file(path.name, path.read_bytes())
        elif not empty:
            demo = self.root / "demo"
            if not (demo / "Src").exists():
                source = Path(__file__).parent / "examples" / "demo.pa.yaml"
                p = Project.import_yaml(source.read_text(encoding="utf-8"), demo, "demo.pa.yaml")
                p.config.update({"title": "Project workspace · demo", "demo": True, "people": PEOPLE})
                p.save_config()
            self.open(Project(demo))
            demo_definitions(self.runtime.store)
            if not self.runtime.store.rows("Projects"):
                seed(self.runtime.store)
            self.runtime.invalidate()

    def open(self, project, *, start=None):
        with self.lock:
            return self._open(project, start=start)

    def _open(self, project, *, start=None):
        same = self.runtime and self.project.root == project.root and getattr(self.runtime, 'workspace_lease', None)
        lease = self.runtime.workspace_lease if same else ProjectLease(project.root)
        try:
            if recover_changes(project.root):
                project = Project(project.root)
            runtime = Runtime(project)
        except Exception:
            if not same:
                lease.close()
            raise
        if project.config.get("demo"):
            demo_definitions(runtime.store)
        if self.runtime:
            if same:
                self.runtime.workspace_lease = None
            self.runtime.close()
        self.project, self.runtime = project, runtime
        runtime.workspace_lease = lease
        if (self.start_simulation if start is None else start):
            self.runtime.restart()

    def import_file(self, name, payload):
        with self.lock:
            return self._import_file(name, payload)

    def _import_file(self, name, payload):
        destination = self.root / uuid.uuid4().hex[:12]
        if name.lower().endswith(".msapp"):
            project = Project.import_archive(payload, destination, Path(name).stem)
        elif name.lower().endswith((".yaml", ".yml")):
            project = Project.import_yaml(payload.decode("utf-8-sig"), destination, name)
        else:
            raise ValueError("Import a .msapp or YAML file")
        project.config["people"] = PEOPLE
        project.save_config()
        self.open(project)

    def summary(self):
        with self.lock:
            return self._summary()

    def _summary(self):
        self.project = Project(self.project.root)
        p, r = self.project, self.runtime
        def tree(c):
            return {"name": c.name, "kind": c.kind, "source": c.source, "children": [tree(x) for x in c.children]}
        return {"title": p.config["title"], "project_path": str(p.root), "documents": list(p.documents),
            "screens": [tree(c) for c in p.screens.values()], "components": [tree(c) for c in p.components.values()],
            "app": {k: str(p.app.get(k, "")) for k in ("Formulas", "OnStart", "OnError", "StartScreen")},
            "revision": revision(p.root), "lists": list(r.store.definitions), "environment": r.environment, "people": r.people,
            "historical_count": sum(len(run.get("results", [])) for run in p.read_json("metadata/checker.json", {}).get("runs", [])),
            "compatibility": {"controls": sorted({c.kind for cs in p.controls.values() for c in cs}),
                "functions": sorted(n for n in r.functions_used if n), "formulas": len(r.fx.definitions)}}

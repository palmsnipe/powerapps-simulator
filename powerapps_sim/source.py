"""Source documents and lossless local project import/export."""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO, StringIO
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from ruamel.yaml import YAML


def yaml_engine():
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.allow_duplicate_keys = False
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def load_yaml(text):
    data = yaml_engine().load(text)
    if isinstance(data, list):
        if not all(isinstance(item, dict) and len(item) == 1 and isinstance(next(iter(item.values())), dict) for item in data):
            raise ValueError("Clipboard controls must be a sequence of named controls")
        # Normalize only the in-memory model; retain original clipboard text.
        return {"Screens": {"Scratch": {"Children": data}}}
    if not isinstance(data, dict):
        raise ValueError("YAML must contain an App, Screens, ComponentDefinitions, or control document")
    return data


def dump_yaml(data):
    stream = StringIO()
    yaml_engine().dump(data, stream)
    return stream.getvalue()


def safe_path(root, name):
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or ":" in normalized:
        raise ValueError("Unsafe project path")
    target = root.joinpath(*path.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Unsafe project path")
    return target


@dataclass
class Control:
    name: str
    kind: str
    raw: dict
    source: str
    parent: Control | None = None
    children: list[Control] = field(default_factory=list)

    @property
    def properties(self):
        return self.raw.get("Properties", {})

    @property
    def version(self):
        return self.kind.partition("@")[2]

    @property
    def family(self):
        return self.kind.partition("@")[0]


class Project:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = self.read_json("emulator.json", {})
        self.config.setdefault("title", self.root.name)
        self.config.setdefault("viewport", {"width": 1366, "height": 768})
        self.config.setdefault("environment", {"language": "en-US", "parameters": {}, "clock": None,
            "user": {"Email": "admin@example.test", "FullName": "Demo Administrator"}})
        self.config["environment"].setdefault("number_mode", "float")
        self.config["environment"].setdefault("date_numeric_mode", "canvas-milliseconds")
        self.config["environment"].setdefault("round_table_mode", "canvas-zero")
        self.config["environment"].setdefault("enum_mode", "legacy")
        self.config["environment"].setdefault("regex_mode", "canvas")
        self.documents, self.parsed, self.source_errors = {}, {}, []
        self.screens, self.components, self.controls, self.app = {}, {}, {}, {}
        self.reload()

    def read_json(self, name, default):
        path = safe_path(self.root, name)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    def write_json(self, name, data):
        path = safe_path(self.root, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def save_config(self):
        self.write_json("emulator.json", self.config)

    def reload(self):
        self.documents, self.parsed, self.source_errors = {}, {}, []
        self.screens, self.components, self.controls, self.app = {}, {}, {}, {}
        src = self.root / "Src"
        if not src.exists():
            return
        for path in sorted([*src.rglob("*.yaml"), *src.rglob("*.yml")]):
            name = path.relative_to(self.root).as_posix()
            text = path.read_text(encoding="utf-8-sig")
            self.documents[name] = text
            try:
                data = load_yaml(text)
                self.parsed[name] = data
                self._register(name, data)
            except Exception as error:
                mark = getattr(error, "problem_mark", None)
                self.source_errors.append({"category": "source", "message": str(error), "source": name,
                    "line": mark.line + 1 if mark else 1, "severity": "error"})
        order = self.config.get("screens_order", [])
        self.screens = dict(sorted(self.screens.items(), key=lambda pair: order.index(pair[0]) if pair[0] in order else len(order)))

    def _register(self, source, data):
        if "App" in data:
            self.app = data["App"].get("Properties", {})
        for section, target, kind in [("Screens", self.screens, "Screen"),
                                       ("ComponentDefinitions", self.components, "Component")]:
            for name, raw in data.get(section, {}).items():
                if name in target:
                    raise ValueError(f"Duplicate {section} name: {name}")
                target[name] = self._control(name, raw, source, kind=kind)
        # Clipboard control trees can be opened as a scratch screen without rewriting them.
        if "Control" in data:
            name = data.get("Name", "PastedControl")
            scratch = Control("Scratch", "Screen", {"Properties": {}}, source)
            scratch.children = [self._control(name, data, source, scratch)]
            self.screens[scratch.name] = scratch
        elif not any(k in data for k in ("Screens", "App", "ComponentDefinitions", "EditorState")):
            for name, raw in data.items():
                if isinstance(raw, dict) and "Control" in raw:
                    scratch = self.screens.setdefault("Scratch", Control("Scratch", "Screen", {"Properties": {}}, source))
                    scratch.children.append(self._control(name, raw, source, scratch))
                    scratch.raw.setdefault("Children", []).append({name: raw})
            if "Scratch" not in self.screens:
                raise ValueError("Document has no App, screen, component, or control definition")

    def _control(self, name, raw, source, parent=None, kind=None):
        c = Control(name, kind or raw.get("Control", "Unknown"), raw, source, parent)
        self.controls.setdefault(name, []).append(c)
        for item in raw.get("Children", []):
            if not isinstance(item, dict) or len(item) != 1:
                raise ValueError(f"Invalid child in {name}")
            child_name, child_raw = next(iter(item.items()))
            c.children.append(self._control(child_name, child_raw, source, c))
        return c

    def update_source(self, name, text):
        if not name.startswith("Src/") or not name.endswith((".yaml", ".yml")):
            raise ValueError("Source files must be YAML within Src/")
        draft = safe_path(self.root, "drafts/" + name)
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text(text, encoding="utf-8")
        load_yaml(text)
        # Stage and validate the whole model before replacing active source.
        previous = self.documents.get(name)
        target = safe_path(self.root, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        self.reload()
        new_errors = [e for e in self.source_errors if e["source"] == name]
        if new_errors:
            errors = new_errors
            if previous is None:
                target.unlink()
            else:
                target.write_text(previous, encoding="utf-8")
            self.reload()
            raise ValueError(errors[0]["message"])
        self.config["source_edited"] = True
        self.save_config()

    def update_app_property(self, prop, text):
        if prop not in ("Formulas", "OnStart", "OnError", "StartScreen"):
            raise ValueError("Unsupported App property")
        name = next((n for n, d in self.parsed.items() if "App" in d), "Src/App.pa.yaml")
        data = load_yaml(self.documents.get(name, "App:\n  Properties: {}\n"))
        from ruamel.yaml.scalarstring import LiteralScalarString
        data["App"].setdefault("Properties", {})[prop] = LiteralScalarString(text if text.startswith("=") else "=" + text)
        self.update_source(name, dump_yaml(data))

    def export_control(self, name):
        controls = self.controls.get(name, [])
        if not controls:
            raise ValueError("Control not found")
        c = controls[0]
        if c.kind == "Screen":
            return dump_yaml({"Screens": {name: c.raw}})
        if c.kind == "Component":
            return dump_yaml({"ComponentDefinitions": {name: c.raw}})
        return dump_yaml([{name: c.raw}])

    def export(self):
        result = BytesIO()
        with ZipFile(result, "w") as z:
            for name, text in self.documents.items():
                z.writestr(name, text)
            assets = self.root / "Assets"
            if assets.exists():
                for path in assets.rglob("*"):
                    if path.is_file():
                        z.write(path, path.relative_to(self.root).as_posix())
        return result.getvalue()

    @classmethod
    def import_archive(cls, payload, destination, title="Imported app"):
        root = Path(destination)
        root.mkdir(parents=True, exist_ok=True)
        references, props, checker, resources = {}, {}, {}, []
        with ZipFile(BytesIO(payload)) as z:
            if sum(i.file_size for i in z.infolist()) > 150_000_000:
                raise ValueError("App exceeds 150 MB uncompressed limit")
            for info in z.infolist():
                name = info.filename.replace("\\", "/")
                safe_path(root, name)
                if name.startswith("Src/") and name.endswith((".yaml", ".yml")) or name.startswith("Assets/"):
                    target = safe_path(root, name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not info.is_dir():
                        target.write_bytes(z.read(info))
                elif name == "References/DataSources.json":
                    references = json.loads(z.read(info))
                elif name == "Properties.json":
                    props = json.loads(z.read(info))
                elif name == "AppCheckerResult.sarif":
                    checker = json.loads(z.read(info))
                elif name == "References/Resources.json":
                    resources = [{k: v for k, v in r.items() if k != "RootPath"} for r in json.loads(z.read(info)).get("Resources", [])]
        project = cls(root)
        if not project.documents:
            raise ValueError("This archive has no Src YAML. Export a current canvas app containing .pa.yaml source files.")
        state = next((d.get("EditorState", {}) for d in project.parsed.values() if "EditorState" in d), {})
        project.config.update({"title": title, "screens_order": state.get("ScreensOrder", []),
            "viewport": {"width": props.get("DocumentLayoutWidth", 1366), "height": props.get("DocumentLayoutHeight", 768)},
            "scale_to_fit": props.get("DocumentLayoutScaleToFit", False),
            "resource_metadata": resources,
            "original_counts": {"parser_errors": props.get("ParserErrorCount", 0), "binding_errors": props.get("BindingErrorCount", 0)}})
        project.write_json("metadata/datasources.json", references)
        project.write_json("metadata/checker.json", checker)
        project.save_config()
        project.reload()
        return project

    @classmethod
    def import_yaml(cls, text, destination, name="Imported.pa.yaml"):
        root = Path(destination)
        root.mkdir(parents=True, exist_ok=True)
        load_yaml(text)
        target = safe_path(root, "Src/" + Path(name).name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return cls(root)

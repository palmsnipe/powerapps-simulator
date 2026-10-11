"""Shared, revision-checked project changes for browser, CLI and future MCP tools.

The workspace owns the runtime and lock. Validation uses a disposable database;
staging never changes live app source, schemas, records or preview state.
"""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import uuid

from .catalog import atomic_write, json_text
from .source import Project, dump_yaml, load_yaml, safe_path


class RevisionConflict(ValueError):
    pass


def revision(root):
    digest = hashlib.sha256()
    root = Path(root)
    files = sorted([*root.glob('Src/**/*.yaml'), *root.glob('Src/**/*.yml'), *root.glob('lists/*.json')])
    for target in files:
        digest.update(json.dumps(target.relative_to(root).as_posix()).encode())
        content = target.read_bytes()
        digest.update(str(len(content)).encode() + b':' + content)
    return digest.hexdigest()


def data_revision(store):
    digest = hashlib.sha256()
    for query in ('SELECT name,definition FROM lists ORDER BY name', 'SELECT list_name,id,record FROM items ORDER BY list_name,id', 'SELECT name,high_water FROM list_sequences ORDER BY name'):
        for row in store.db.execute(query):
            digest.update(json.dumps(tuple(row), ensure_ascii=False).encode())
    return digest.hexdigest()


def _schema_text(value):
    # JSON object ordering is immaterial; stable diffs expose actual schema edits.
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n'


def _source_name(root, name):
    if not isinstance(name, str):
        raise ValueError('Source name must be text')
    name = name.replace('\\', '/')
    safe_path(root, name)
    if not name.startswith('Src/') or not name.endswith(('.yaml', '.yml')):
        raise ValueError('Source files must be YAML within Src/')
    return name


def _restore_files(root, files):
    for name, content in files.items():
        target = safe_path(root, name)
        if content is None:
            target.unlink(missing_ok=True)
        else:
            atomic_write(target, base64.b64decode(content))


def _restore_database(root, backup):
    with sqlite3.connect(backup) as source, sqlite3.connect(Path(root) / 'data.sqlite') as destination:
        source.backup(destination)


def recover_changes(root):
    """Rollback interrupted applies/undos before opening a runtime."""
    recovered = False
    for manifest in sorted((Path(root) / '.emu/changes').glob('*/change.json')):
        change = json.loads(manifest.read_text(encoding='utf-8'))
        if change.get('status') not in ('applying', 'undoing'):
            continue
        undo = change['status'] == 'undoing'
        _restore_files(root, change['undo_files' if undo else 'before_files'])
        database = manifest.parent / ('undo.sqlite' if undo else 'before.sqlite')
        if database.exists():
            _restore_database(root, database)
        change['status'] = 'applied' if undo else 'rolled_back'
        change['recovered'] = True
        atomic_write(manifest, json_text(change))
        recovered = True
    return recovered


class AuthoringService:
    def __init__(self, workspace):
        self.workspace = workspace

    @property
    def root(self):
        return self.workspace.project.root

    @property
    def store(self):
        return self.workspace.runtime.store

    def check_revision(self, expected):
        if not isinstance(expected, str) or not expected:
            raise ValueError('expected_revision is required; read the project before editing')
        actual = revision(self.root)
        if expected != actual:
            raise RevisionConflict('Project changed since it was read. Refresh and review your edits before applying.')
        catalog = {n: d for n, (_, d) in self.store.catalog.read().items()}
        if catalog != self.store.definitions:
            raise RevisionConflict('Authored list files changed outside this session. Restart to validate and load them before staging changes.')
        return actual

    def _entry(self, change_id):
        if not isinstance(change_id, str) or not re.fullmatch('[a-f0-9]{32}', change_id):
            raise ValueError('Invalid change ID')
        target = self.root / '.emu/changes' / change_id / 'change.json'
        if not target.exists():
            raise ValueError('Change not found in this project')
        return target, json.loads(target.read_text(encoding='utf-8'))

    def _snapshot(self, names):
        return {name: base64.b64encode(safe_path(self.root, name).read_bytes()).decode() if safe_path(self.root, name).exists() else None for name in names}

    def _database_backup(self, target):
        with sqlite3.connect(target) as destination:
            self.store.db.backup(destination)

    def stage(self, *, expected_revision, sources=None, lists=None, migrations=None, title='Project change', strict=False):
        with self.workspace.lock:
            current = self.check_revision(expected_revision)
            sources = {} if sources is None else sources
            lists = {} if lists is None else lists
            migrations = {} if migrations is None else migrations
            if not isinstance(sources, dict) or not isinstance(lists, dict) or not isinstance(migrations, dict):
                raise ValueError('sources, lists and migrations must be objects')
            if not isinstance(strict, bool):
                raise ValueError('strict must be Boolean')
            if not sources and not lists:
                raise ValueError('A change needs source or list definitions')
            normalized = {_source_name(self.root, n): v for n, v in sources.items()}
            if len(normalized) != len(sources):
                raise ValueError('Two source paths refer to the same document')
            sources = normalized
            if any(v is not None and not isinstance(v, str) for v in sources.values()):
                raise ValueError('Source must be text, or null to remove a file')
            definitions, _, impacts = self.store.plan_schemas(lists, migrations)
            lists = {n: definitions[n] for n in lists}
            diagnostics = self._validate(sources, lists, migrations)
            self.check_revision(current)
            if strict and diagnostics:
                raise ValueError('Strict validation requires a project without current binding/source diagnostics')
            diffs = []
            for name, content in sources.items():
                target = safe_path(self.root, name)
                previous = target.read_text(encoding='utf-8') if target.exists() else ''
                diff = ''.join(difflib.unified_diff(previous.splitlines(True), (content or '').splitlines(True), fromfile=name, tofile=name))
                diffs.append({'path': name, 'diff': diff})
            for name, definition in lists.items():
                target = self.store.catalog.path(name)
                previous = self.store.definitions.get(name)
                diffs.append({'path': target.relative_to(self.root).as_posix(), 'diff': ''.join(difflib.unified_diff(
                    (_schema_text(previous) if previous else '').splitlines(True), _schema_text(definition).splitlines(True), fromfile=name, tofile=name))})
            change_id = uuid.uuid4().hex
            entry = {'id': change_id, 'title': str(title), 'created_at': datetime.now(timezone.utc).isoformat(),
                'status': 'staged', 'base_revision': current,
                'data_revision': data_revision(self.store) if lists else None,
                'sources': sources, 'lists': lists, 'migrations': migrations,
                'diffs': diffs, 'impacts': impacts, 'diagnostics': diagnostics, 'strict': bool(strict)}
            atomic_write(self.root / '.emu/changes' / change_id / 'change.json', json_text(entry))
            return self._public(entry)

    def _validate(self, sources, lists, migrations):
        from .runtime import Runtime
        with TemporaryDirectory(prefix='powerapps-validate-') as temporary:
            root = Path(temporary)
            for directory in ('Src', 'lists'):
                if (self.root / directory).exists():
                    shutil.copytree(self.root / directory, root / directory)
            for name in ('emulator.json', 'metadata/datasources.json', 'metadata/schema-catalog.json'):
                target = self.root / name
                if target.exists():
                    (root / name).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, root / name)
            self._database_backup(root / 'data.sqlite')
            for name, content in sources.items():
                if content is None:
                    safe_path(root, name).unlink(missing_ok=True)
                else:
                    load_yaml(content)
                    atomic_write(safe_path(root, name), content)
            candidate = Project(root)
            old_errors = {(e['source'], e['message']) for e in self.workspace.project.source_errors}
            if any(e['source'] in sources or (e['source'], e['message']) not in old_errors for e in candidate.source_errors):
                raise ValueError('The combined source change creates an invalid source model')
            r = Runtime(candidate)
            try:
                definitions, _, _ = r.store.plan_schemas(lists, migrations)
                r.store.definitions = definitions
                r.analyze()
                return deepcopy(r.bind_diagnostics)
            finally:
                r.close()

    @staticmethod
    def _public(entry):
        return {k: v for k, v in entry.items() if k not in ('before_files', 'undo_files')}

    def history(self):
        with self.workspace.lock:
            entries = [json.loads(p.read_text(encoding='utf-8')) for p in (self.root / '.emu/changes').glob('*/change.json')]
            return [self._public(e) for e in sorted(entries, key=lambda e: e['created_at'], reverse=True)]

    def apply(self, change_id, *, expected_revision):
        with self.workspace.lock:
            current = self.check_revision(expected_revision)
            manifest, entry = self._entry(change_id)
            if entry['status'] != 'staged':
                raise ValueError('Only staged changes can be applied')
            if entry['base_revision'] != current:
                raise RevisionConflict('Staged change is stale. Create a new review against the current project.')
            if entry['data_revision'] is not None and entry['data_revision'] != data_revision(self.store):
                raise RevisionConflict('List records changed after staging. Revalidate the migration against the current records.')
            definitions, rows, _ = self.store.plan_schemas(entry['lists'], entry['migrations'])
            entry['diagnostics'] = self._validate(entry['sources'], entry['lists'], entry['migrations'])
            if entry['strict'] and entry['diagnostics']:
                raise ValueError('Strict validation requires a project without current binding/source diagnostics')
            self.check_revision(current)
            names = [*entry['sources'], *(self.store.catalog.path(n).relative_to(self.root).as_posix() for n in entry['lists'])]
            if entry['lists']:
                names.append('metadata/schema-catalog.json')
                self._database_backup(manifest.parent / 'before.sqlite')
            names.append('emulator.json')
            entry.update(before_files=self._snapshot(names), status='applying')
            atomic_write(manifest, json_text(entry))
            previous = deepcopy(self.store.definitions)
            try:
                self.store.db.execute('BEGIN IMMEDIATE')
                for name, content in entry['sources'].items():
                    target = safe_path(self.root, _source_name(self.root, name))
                    if content is None:
                        target.unlink(missing_ok=True)
                    else:
                        atomic_write(target, content)
                for name in entry['lists']:
                    self.store.db.execute('INSERT OR REPLACE INTO lists VALUES(?,?)', (name, json.dumps(definitions[name])))
                    for item_id, record in rows[name]:
                        self.store.db.execute('UPDATE items SET record=? WHERE list_name=? AND id=?', (json.dumps(record), name, item_id))
                    self.store.catalog.write(name, definitions[name])
                self.store.definitions = definitions
                if entry['lists']:
                    self.store.catalog_marker()
                p = Project(self.root)
                if entry['sources']:
                    p.config['source_edited'] = True
                    p.save_config()
                self.store.db.commit()
                entry.update(status='applied', applied_at=datetime.now(timezone.utc).isoformat(), after_revision=revision(self.root), after_data_revision=data_revision(self.store))
                atomic_write(manifest, json_text(entry))
            except Exception:
                self.store.db.rollback()
                self.store.definitions = previous
                _restore_files(self.root, entry['before_files'])
                if (manifest.parent / 'before.sqlite').exists():
                    with sqlite3.connect(manifest.parent / 'before.sqlite') as backup:
                        backup.backup(self.store.db)
                entry['status'] = 'rolled_back'
                atomic_write(manifest, json_text(entry))
                raise
            self._refresh(bool(entry['sources']), bool(entry['lists']))
            return self._public(entry)

    def undo(self, change_id, *, expected_revision):
        with self.workspace.lock:
            current = self.check_revision(expected_revision)
            manifest, entry = self._entry(change_id)
            applied = sorted([e for e in self.history() if e['status'] == 'applied'], key=lambda e: e['applied_at'], reverse=True)
            if entry['status'] != 'applied' or not applied or applied[0]['id'] != change_id:
                raise ValueError('Undo the latest applied change first')
            if current != entry['after_revision']:
                raise RevisionConflict('Project changed after this change. Undo would overwrite newer edits.')
            if entry['lists'] and data_revision(self.store) != entry['after_data_revision']:
                raise RevisionConflict('Records changed after this migration. Undo would discard newer data; review a new migration instead.')
            before = {n: v for n, v in entry['before_files'].items() if n != 'emulator.json'}
            entry.update(status='undoing', undo_files=self._snapshot(before))
            if entry['lists']:
                self._database_backup(manifest.parent / 'undo.sqlite')
            atomic_write(manifest, json_text(entry))
            try:
                _restore_files(self.root, before)
                if entry['lists']:
                    with sqlite3.connect(manifest.parent / 'before.sqlite') as backup:
                        backup.backup(self.store.db)
                entry.update(status='undone', undone_at=datetime.now(timezone.utc).isoformat())
                atomic_write(manifest, json_text(entry))
            except Exception:
                _restore_files(self.root, entry['undo_files'])
                if entry['lists']:
                    with sqlite3.connect(manifest.parent / 'undo.sqlite') as backup:
                        backup.backup(self.store.db)
                entry['status'] = 'applied'
                atomic_write(manifest, json_text(entry))
                raise
            self._refresh(bool(entry['sources']), bool(entry['lists']))
            return self._public(entry)

    def _refresh(self, sources, lists):
        self.workspace.project = Project(self.root)
        r = self.workspace.runtime
        if sources:
            r.pending_source = True
        if lists:
            r.store.definitions = {row['name']: json.loads(row['definition']) for row in r.store.db.execute('SELECT * FROM lists')}
            r.analyze()
        r.invalidate()

    def save_source(self, *, expected_revision, text, name=None, property=None):
        with self.workspace.lock:
            self.check_revision(expected_revision)
            if not isinstance(text, str):
                raise ValueError('Source must be text')
            if property is not None:
                if property not in ('Formulas', 'OnStart', 'OnError', 'StartScreen'):
                    raise ValueError('Unsupported App property')
                p = Project(self.root)
                name = next((n for n, d in p.parsed.items() if 'App' in d), 'Src/App.pa.yaml')
                data = load_yaml(p.documents.get(name, 'App:\n  Properties: {}\n'))
                from ruamel.yaml.scalarstring import LiteralScalarString
                data['App'].setdefault('Properties', {})[property] = LiteralScalarString(text if text.startswith('=') else '='+text)
                text = dump_yaml(data)
            name = _source_name(self.root, name)
            atomic_write(safe_path(self.root, 'drafts/'+name), text)
            bases = self.workspace.project.read_json('drafts/revisions.json', {})
            bases[name] = expected_revision
            atomic_write(self.root / 'drafts/revisions.json', json_text(bases))
            try:
                entry = self.stage(expected_revision=expected_revision, sources={name: text}, title='Edit '+(f'App.{property}' if property else name))
                return self.apply(entry['id'], expected_revision=expected_revision)
            except Exception as error:
                error.draft_saved = True
                raise


def main():
    parser = argparse.ArgumentParser(description='Review/apply local source and list-schema changes')
    parser.add_argument('project', type=Path)
    actions = parser.add_subparsers(dest='action', required=True)
    actions.add_parser('describe')
    actions.add_parser('history')
    stage = actions.add_parser('stage'); stage.add_argument('file', type=Path)
    for command in ('apply', 'undo'):
        action = actions.add_parser(command); action.add_argument('change_id'); action.add_argument('--revision', required=True)
    args = parser.parse_args()
    if not args.project.is_dir() or not any((args.project / n).exists() for n in ('Src', 'emulator.json', 'data.sqlite')):
        parser.error('Choose an existing local project directory')
    from .application import Workspace
    workspace = None
    try:
        workspace = Workspace(args.project.parent, args.project, start=False)
        service = workspace.authoring
        if args.action == 'describe':
            result = workspace.summary()
        elif args.action == 'history':
            result = service.history()
        elif args.action == 'stage':
            result = service.stage(**json.loads(args.file.read_text(encoding='utf-8')))
        else:
            result = getattr(service, args.action)(args.change_id, expected_revision=args.revision)
        print(json_text(result))
    except Exception as error:
        parser.exit(1, str(error)+'\n')
    finally:
        if workspace:
            workspace.runtime.close()


if __name__ == '__main__':
    main()

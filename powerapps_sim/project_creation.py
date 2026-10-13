"""Validate and publish new local apps without evaluating startup behavior."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory

from .authoring import _source_name
from .catalog import atomic_write, json_text
from .ownership import ProjectLease
from .runtime import Runtime
from .source import Project, dump_yaml
from .store import ListStore
from .workflows import STARTER, validate


def project_name(name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', name):
        raise ValueError('name must be 1–64 letters, digits, underscores or hyphens, starting with a letter or digit')
    if name.upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        raise ValueError('name is reserved on Windows')
    return name


def starter_source(title):
    return dump_yaml({'App': {'Properties': {'StartScreen': '=Main'}}, 'Screens': {'Main': {
        'Properties': {'Fill': '=Color.White'}, 'Children': [{'Title': {
            'Control': 'ModernText@1.0.0', 'Properties': {
                'Text': '="' + title.replace('"', '""') + '"', 'X': '=24', 'Y': '=24',
                'Width': '=Max(0, Parent.Width - 48)', 'Height': '=40', 'Size': '=26'}}}]}}})


class _SeedStore(ListStore):
    """Defer record validation until every local lookup target has been seeded.

    This database is private, never a live project. import_rows still handles
    ID allocation, mappings and JSON conversion; validate_seed checks every
    persisted row before the directory can be published, including cyclic links.
    """
    def validate(self, name, record, *, fields=None):
        pass

    def validate_seed(self):
        for name, definition in self.definitions.items():
            for column, field in definition['fields'].items():
                if field.get('default') is not None:
                    super().validate(name, {column: field['default']}, fields={column})
        for name, record in self.db.execute('SELECT list_name,record FROM items'):
            super().validate(name, json.loads(record))


def create_project(workspace, *, name, title=None, sources=None, lists=None, records=None,
                   workflows=None, viewport=None, environment=None, strict=True):
    """Publish a complete app under the configured workspace and open it unstarted."""
    name = project_name(name)
    title = name if title is None else title
    if not isinstance(title, str) or not title.strip() or len(title) > 200 or '\n' in title or '\r' in title:
        raise ValueError('title must be nonempty single-line text of at most 200 characters')
    if type(strict) is not bool:
        raise ValueError('strict must be Boolean')
    sources = {'Src/App.pa.yaml': starter_source(title)} if sources is None else deepcopy(sources)
    lists, records, workflows = ({} if value is None else deepcopy(value) for value in (lists, records, workflows))
    if not isinstance(sources, dict) or not 1 <= len(sources) <= 100 or any(not isinstance(s, str) for s in sources.values()):
        raise ValueError('sources must contain 1–100 source filenames mapped to YAML text; omit it for a starter screen')
    if not isinstance(lists, dict) or len(lists) > 100 or any(not isinstance(n, str) or not n.strip() for n in lists):
        raise ValueError('lists must map up to 100 nonempty local list names to schema definitions')
    if not isinstance(records, dict) or set(records) - set(lists) or any(
            not isinstance(rows, list) or len(rows) > 10000 or any(not isinstance(row, dict) for row in rows)
            for rows in records.values()):
        raise ValueError('records must map declared list names to arrays of at most 10,000 sample records')
    if not isinstance(workflows, dict) or len(workflows) > 100:
        raise ValueError('workflows must map up to 100 workflow filenames to scenario objects')
    if any(not isinstance(filename, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\.workflow\.json', filename)
           for filename in workflows) or len({n.casefold() for n in workflows}) != len(workflows):
        raise ValueError('Workflow filenames must be unique portable basenames ending in .workflow.json')
    for filename in workflows:
        project_name(filename.removesuffix('.workflow.json'))
    workflows = {filename: validate(scenario) for filename, scenario in workflows.items()}
    viewport = {'width': 1366, 'height': 768} if viewport is None else deepcopy(viewport)
    if not isinstance(viewport, dict) or set(viewport) != {'width', 'height'} or any(
            type(v) is not int or not 200 <= v <= 4000 for v in viewport.values()):
        raise ValueError('viewport needs width and height integers from 200 to 4000')
    if environment is not None:
        environment = validate({**STARTER, 'environment': environment})['environment']
    json.dumps({'sources': sources, 'lists': lists, 'records': records, 'workflows': workflows}, allow_nan=False)
    root = workspace.root
    destination = root / name
    if destination.exists() or destination.is_symlink():
        raise ValueError('Project destination already exists; choose a new name. Existing directories are never replaced.')
    with TemporaryDirectory(prefix='.create-project-', dir=root) as temporary:
        project = Project(Path(temporary) / 'app')
        normalized = {}
        for filename, text in sources.items():
            filename = _source_name(project.root, filename)
            # Normalize aliases before checking portable case-insensitive uniqueness.
            filename = Path(filename).as_posix()
            if filename.casefold() in {n.casefold() for n in normalized}:
                raise ValueError('Source filenames must be unique after path normalization')
            normalized[filename] = text
        for filename, text in normalized.items():
            atomic_write(project.root / filename, text)
        project.reload()
        if project.source_errors or not project.screens:
            raise ValueError('New app needs valid YAML and at least one screen: ' +
                             (project.source_errors[0]['message'] if project.source_errors else 'no screens found'))
        project.config.update(title=title, viewport=viewport)
        if environment is not None:
            project.config['environment'].update(environment)
        project.save_config()
        store = _SeedStore(project.root / 'data.sqlite', schema_root=project.root / 'lists')
        try:
            # Validate all definitions together, so forward lookup declarations work.
            store.plan_schemas(lists)
            for list_name, definition in lists.items():
                store.add_list(list_name, definition)
            for list_name, rows in records.items():
                # Reserve supplied IDs before allocating implicit IDs, avoiding
                # accidental replacement when an implicit row precedes an explicit one.
                for row in rows:
                    item_id = store.internal(list_name, row).get('ID')
                    if item_id is not None:
                        if type(item_id) is not int or item_id <= 0:
                            raise ValueError('Sample record IDs must be positive integers')
                        store._remember_id(list_name, item_id)
                store.import_rows(list_name, rows)
            store.validate_seed()
        except (TypeError, sqlite3.Error) as error:
            raise ValueError(f'Invalid sample records: {error}') from None
        finally:
            store.close()
        for filename, scenario in workflows.items():
            atomic_write(project.root / 'tests' / filename, json_text(scenario))
        runtime = Runtime(project)
        try:
            diagnostics = deepcopy(runtime.diagnostics)
            if strict and diagnostics:
                raise ValueError('Strict creation requires no binding/source diagnostics: ' + diagnostics[0]['message'])
        finally:
            runtime.close()
        # Serialize publishers across processes and check again just before the
        # atomic rename. Open files/SQLite are closed before moving on Windows.
        lease = ProjectLease(root)
        try:
            if destination.exists() or destination.is_symlink():
                raise ValueError('Project destination already exists; existing directories are never replaced.')
            project.root.rename(destination)
        finally:
            lease.close()
    try:
        workspace.open(Project(destination), start=False)
    except Exception as error:
        # A fully validated project is already published. Preserve it rather than
        # deleting a directory another workspace may have opened in the meantime.
        raise ValueError(f'Project created at {destination}, but could not be opened: {error}. '
                         'The previous project is unchanged; the new directory was preserved.') from error
    result = workspace.ai.describe_project()
    result.update(status='created', created_sources=list(normalized),
                  sample_record_counts={n: len(records.get(n, [])) for n in lists},
                  workflow_files=list(workflows), diagnostics=diagnostics,
                  note='Project created and bound without startup. Acceptance workflows are saved, not executed. '
                       'Run workflows, then explicitly restart_preview; refresh the browser after switching projects.')
    return result

"""Project-bound operations shared by HTTP and the optional MCP adapter.

No SDK dependency belongs here. Behavior runs only through isolated workflows;
authoring uses the existing revision/migration/undo services.
"""
from __future__ import annotations

from copy import deepcopy
import inspect

from .authoring import RevisionConflict, data_revision, revision
from .binding import value_type
from .fx import Context
from .runtime import serial
from .source import Project
from .syntax import FxError


OPERATIONS = ('describe_project', 'read_source', 'read_list', 'read_diagnostics', 'read_analysis',
              'read_runtime', 'read_dependencies', 'evaluate_formula', 'export_source', 'list_changes', 'stage_change',
              'apply_change', 'undo_change', 'list_workflows', 'run_workflow', 'read_workflow_report')
WRITES = {'stage_change', 'apply_change', 'undo_change', 'run_workflow'}


class AIService:
    def __init__(self, workspace):
        self.workspace = workspace

    def call(self, operation, arguments=None, *, expected_project=None):
        if operation not in OPERATIONS:
            raise ValueError('Unknown AI operation')
        arguments = {} if arguments is None else arguments
        if not isinstance(arguments, dict):
            raise ValueError('Operation arguments must be an object')
        with self.workspace.lock:
            current = str(self.workspace.project.root)
            if expected_project is not None and expected_project != current:
                raise RevisionConflict('The workspace now owns a different project. Reconnect the adapter explicitly.')
            if operation in WRITES and expected_project is None:
                raise ValueError('Mutating AI operations require expected_project')
            method = getattr(self, operation)
            try:
                inspect.signature(method).bind(**arguments)
            except TypeError as error:
                raise ValueError(str(error)) from None
            # Detach mutable values from runtime/configuration before returning to any client.
            result = method(**arguments)
            return deepcopy(serial(result))

    def describe_project(self):
        result = self.workspace.summary()
        result.update(api_version=1, operations=list(OPERATIONS), data_revision=data_revision(self.workspace.runtime.store),
            runtime_started=self.workspace.runtime.started, pending_source=self.workspace.runtime.pending_source,
            running_revision=self._running_revision_note())
        return result

    def _running_revision_note(self):
        r = self.workspace.runtime
        saved = Project(self.workspace.project.root)
        return {'source_matches_saved': r.project.documents == saved.documents,
                'note': 'Saved source loads on explicit browser restart; workflows always use saved/candidate source.'}

    def read_source(self, name=None, app_property=None, control_name=None):
        if sum(x is not None for x in (name, app_property, control_name)) != 1:
            raise ValueError('Choose exactly one source name, app_property or control_name')
        p = Project(self.workspace.project.root)
        if name is not None:
            if not isinstance(name, str) or name not in p.documents:
                raise ValueError('Source document not found')
            text = p.documents[name]
        elif app_property is not None:
            if app_property not in ('Formulas', 'OnStart', 'OnError', 'StartScreen'):
                raise ValueError('App property must be Formulas, OnStart, OnError or StartScreen')
            text = str(p.app.get(app_property, ''))
        else:
            if not isinstance(control_name, str) or not p.controls.get(control_name):
                raise ValueError('Control not found')
            if len(p.controls[control_name]) != 1:
                raise ValueError('Control name is ambiguous; read its source document instead')
            text = p.export_control(control_name)
        return {'text': text, 'revision': revision(p.root), 'source': name, 'app_property': app_property, 'control_name': control_name}

    def read_list(self, name, offset=0, limit=50):
        if not isinstance(name, str):
            raise ValueError('List name must be text')
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('Use a nonnegative offset and a limit between 1 and 500')
        r = self.workspace.runtime
        r.store.source(name)
        rows = r.store.rows(name)
        definition = r.store.catalog.read().get(name)
        from .data_errors import rows as error_rows
        return {'errors': serial(error_rows(r.store,name)), 'name': name, 'definition': definition[1] if definition else r.store.definitions[name],
            'rows': rows[offset:offset + limit], 'total': len(rows), 'offset': offset,
            'next_offset': offset + limit if offset + limit < len(rows) else None,
            'revision': revision(self.workspace.project.root), 'data_revision': data_revision(r.store),
            'failure': r.store.failures.get(name)}

    def read_diagnostics(self, historical=False):
        if type(historical) is not bool:
            raise ValueError('historical must be Boolean')
        p = Project(self.workspace.project.root)
        if historical:
            return {'category': 'historical', 'checker': p.read_json('metadata/checker.json', {}),
                    'source_edited': bool(p.config.get('source_edited'))}
        return {'category': 'current', 'diagnostics': self.workspace.runtime.diagnostics,
                'saved_source_errors': p.source_errors, 'revision': revision(p.root),
                'running_source': self._running_revision_note()}

    def read_analysis(self):
        return self.workspace.runtime.analysis()

    def read_dependencies(self,query='',offset=0,limit=100,include_values=True):
        if not isinstance(query,str) or len(query)>1000:raise ValueError('Query must be text under 1000 characters')
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=500:
            raise ValueError('Use a nonnegative offset and a limit between 1 and 500')
        if type(include_values) is not bool:raise ValueError('include_values must be Boolean')
        return {**self.workspace.runtime.reactive.describe(query,offset,limit,include_values),
            'running_source':self._running_revision_note()}

    def read_runtime(self):
        r = self.workspace.runtime
        # Unlike state(), observing an AI resource must not drain queued events or
        # render controls: rendering can establish/reset component input baselines.
        from .timers import snapshot,refs
        from .component_inspection import describe
        timer_info={'timers':snapshot(r)} if refs(r) else {}
        from .media_controls import snapshots
        if r.media_states:timer_info['media']=snapshots(r)
        return {**timer_info,'active_screen': r.active_screen, 'preview_screen': r.preview_screen,
            'started': r.started, 'pending_source': r.pending_source, 'viewport': r.viewport,
            'globals': r.globals, 'collections': r.collections, 'contexts': r.screen_context, 'components': r.component_state,
            'types': r.inspector_types(),
            'component_contracts': describe(r),
            'data_errors': {name:[row for _,row in entries] for name,entries in r.store.operation_errors.items() if entries},
            'error_reports': r.app_errors.reports, 'notifications': r.notifications, 'running_source': self._running_revision_note()}

    def evaluate_formula(self, formula, scope=None):
        if not isinstance(formula, str) or not formula.strip() or len(formula) > 100_000:
            raise ValueError('Provide a nonempty Power Fx formula under 100,000 characters')
        r = self.workspace.runtime
        if scope is not None:
            if not isinstance(scope, str) or scope not in r.refs:
                raise ValueError('Scope must name an existing runtime control path')
            ctx = r.refs[scope].context()
        else:
            ctx = Context(r)
        try:
            value = r.fx.evaluate(formula, ctx)
        except FxError as error:
            value = error
        from .inspection import schema
        from .binding import UNKNOWN
        try:
            declared = r.fx.node_types.get(id(r.fx.bound_node(formula, ctx)), UNKNOWN)
        except FxError:
            declared = UNKNOWN
        return {'status': 'error' if isinstance(value, FxError) else 'ok', 'value': value,
            'type': schema(value_type(value), declared), 'error_kind': value.kind if isinstance(value, FxError) else None,
            'started': r.started, 'running_source': self._running_revision_note()}

    def export_source(self):
        p = Project(self.workspace.project.root)
        return {'documents': p.documents, 'app': {k: str(p.app.get(k, '')) for k in ('Formulas', 'OnStart', 'OnError', 'StartScreen')},
            'revision': revision(p.root), 'note': 'Power Apps YAML/formulas only; assets are available in the browser source ZIP.'}

    def list_changes(self):
        return {'revision': revision(self.workspace.project.root), 'changes': self.workspace.authoring.history()}

    def stage_change(self, expected_revision, sources=None, lists=None, migrations=None, title='AI project change', strict=False):
        return self.workspace.authoring.stage(expected_revision=expected_revision, sources=sources, lists=lists,
            migrations=migrations, title=title, strict=strict)

    def apply_change(self, change_id, expected_revision):
        return self.workspace.authoring.apply(change_id, expected_revision=expected_revision)

    def undo_change(self, change_id, expected_revision):
        return self.workspace.authoring.undo(change_id, expected_revision=expected_revision)

    def list_workflows(self):
        return self.workspace.workflows.catalog()

    def run_workflow(self, expected_revision, scenario=None, scenario_file=None, change_id=None):
        if (scenario is None) == (scenario_file is None):
            raise ValueError('Provide exactly one inline scenario or scenario_file from list_workflows')
        if scenario_file is not None:
            entry = next((e for e in self.workspace.workflows.catalog()['scenarios'] if e['file'] == scenario_file), None)
            if entry is None or entry.get('error'):
                raise ValueError('Valid workflow file not found in the project catalog')
            scenario = entry['scenario']
        return self.workspace.workflows.run(scenario, expected_revision=expected_revision, change_id=change_id)

    def read_workflow_report(self, run_id):
        return self.workspace.workflows.report(run_id)

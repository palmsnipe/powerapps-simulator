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
              'apply_change', 'undo_change', 'list_workflows', 'run_workflow', 'read_workflow_report',
              'read_controls', 'read_control', 'read_list_schema', 'stage_control_edits', 'run_workflows', 'restart_preview',
              'create_project', 'list_projects', 'open_project', 'validate_workflows', 'get_edit_context', 'check_change')
WORKSPACE_OPERATIONS = {'list_projects', 'open_project'}
WRITES = {'stage_change', 'apply_change', 'undo_change', 'run_workflow',
          'stage_control_edits', 'run_workflows', 'restart_preview', 'create_project', 'validate_workflows', 'check_change'}
APP_PROPERTIES = ('Formulas', 'OnStart', 'OnError', 'StartScreen')
SOURCE_TARGETS = {'document': 'name', 'app_property': 'app_property', 'control': 'control_name'}


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
            current = str(self.workspace.project.root) if self.workspace.project else None
            if operation not in WORKSPACE_OPERATIONS and expected_project is not None and expected_project != current:
                raise RevisionConflict('The workspace now owns a different project. Call list_projects and explicitly open_project to rebind.')
            if operation in WRITES and expected_project is None and not (operation == 'create_project' and current is None):
                raise ValueError('Mutating AI operations require expected_project')
            if current is None and operation not in WORKSPACE_OPERATIONS | {'create_project', 'describe_project'}:
                raise ValueError('No project is open; call open_project or create_project first')
            method = getattr(self, operation)
            try:
                inspect.signature(method).bind(**arguments)
            except TypeError as error:
                raise ValueError(str(error)) from None
            # Detach mutable values from runtime/configuration before returning to any client.
            result = method(**arguments)
            return deepcopy(serial(result))

    def describe_project(self):
        from .workflows import workflow_revision

        if self.workspace.project is None:
            return {'api_version': 1, 'workspace_root': str(self.workspace.root), 'project_path': None,
                    'revision': None, 'workflow_revision': None, 'runtime_started': False,
                    'operations': ['describe_project', 'list_projects', 'open_project', 'create_project'],
                    'note': 'Call list_projects and open_project, or create_project to create and bind an app.'}
        result = self.workspace.summary()
        result.update(api_version=1, workspace_root=str(self.workspace.root), operations=list(OPERATIONS), data_revision=data_revision(self.workspace.runtime.store),
            workflow_revision=workflow_revision(self.workspace.project.root),
            runtime_started=self.workspace.runtime.started, pending_source=self.workspace.runtime.pending_source,
            running_revision=self._running_revision_note())
        return result

    def list_projects(self):
        w = self.workspace
        current = w.project.root if w.project else None
        return {'workspace_root': str(w.root), 'active_project_id': current.name if current and current.parent == w.root else None,
                'projects': w.list_projects()}

    def open_project(self, project_id):
        self.workspace.open_project(project_id, start=False)
        return {'status': 'opened', **self.describe_project()}

    def create_project(self, name, title=None, sources=None, lists=None, records=None, workflows=None,
                       viewport=None, environment=None, strict=True, expected_revision=None):
        if self.workspace.project is not None:
            self.workspace.authoring.check_revision(expected_revision)
        elif expected_revision is not None:
            raise RevisionConflict('An empty workspace has no project revision; omit expected_revision')
        from .project_creation import create_project
        return create_project(self.workspace, name=name, title=title, sources=sources, lists=lists,
                              records=records, workflows=workflows, viewport=viewport,
                              environment=environment, strict=strict)

    def _running_revision_note(self):
        r = self.workspace.runtime
        saved = Project(self.workspace.project.root)
        return {'source_matches_saved': r.project.documents == saved.documents,
                'note': 'Saved source loads on explicit browser restart; workflows always use saved/candidate source.'}

    def read_source(self, name=None, app_property=None, control_name=None, target=None):
        if target is not None:
            if any(selector is not None for selector in (name, app_property, control_name)):
                raise ValueError('Use target by itself')
            if target == {'kind': 'index'}:
                return self._source_index(Project(self.workspace.project.root))
            if not isinstance(target, dict) or not isinstance(target.get('kind'), str):
                raise ValueError('Target needs a source kind and value')
            field = SOURCE_TARGETS.get(target['kind'])
            if field is None or set(target) != {'kind', 'value'} or not isinstance(target.get('value'), str):
                raise ValueError('Use a document, app_property or control target with a value')
            name, app_property, control_name = (target['value'] if field == item else None
                                                for item in ('name', 'app_property', 'control_name'))
        if sum(x is not None for x in (name, app_property, control_name)) != 1:
            raise ValueError('Choose exactly one source name, app_property or control_name')
        p = Project(self.workspace.project.root)
        if name is not None:
            if not isinstance(name, str) or name not in p.documents:
                raise ValueError('Source document not found')
            text = p.documents[name]
        elif app_property is not None:
            if app_property not in APP_PROPERTIES:
                raise ValueError('App property must be Formulas, OnStart, OnError or StartScreen')
            text = str(p.app.get(app_property, ''))
        else:
            if not isinstance(control_name, str) or not p.controls.get(control_name):
                raise ValueError('Control not found')
            if len(p.controls[control_name]) != 1:
                raise ValueError('Control name is ambiguous; read its source document instead')
            text = p.export_control(control_name)
        return {'text': text, 'revision': revision(p.root), 'source': name, 'app_property': app_property, 'control_name': control_name}

    @staticmethod
    def _source_index(project):
        return {'revision': revision(project.root), 'documents': list(project.documents),
                'app_properties': list(APP_PROPERTIES), 'screens': list(project.screens),
                'components': list(project.components)}

    def get_edit_context(self, query='', source=None, list_names=None, offset=0, limit=12):
        from .ai_authoring import read_controls
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('Edit context limit must be between 1 and 50')
        p = Project(self.workspace.project.root)
        names = sorted(self.workspace.runtime.store.definitions)
        if list_names is None:
            list_names = names if len(names) <= 3 else []
        if not isinstance(list_names, list) or len(list_names) > 10 or any(
            not isinstance(name, str) or name not in names for name in list_names
        ):
            raise ValueError('Use up to ten list names from the project list catalog')
        catalog = self.list_workflows(include_scenarios=False)
        controls = read_controls(p, query, source, offset, limit, include_properties=True)
        return {**self._source_index(p), 'project_path': str(p.root), 'title': p.config['title'],
                'workflow_revision': catalog['workflow_revision'],
                'workflows': [item for item in catalog['scenarios'] if not item.get('origin')],
                'list_names': names, 'list_schemas': {
                    name: self.read_list_schema(name)['definition'] for name in dict.fromkeys(list_names)},
                **controls, 'running_source': self._running_revision_note()}

    def read_controls(self, query='', source=None, offset=0, limit=50, include_properties=False):
        from .ai_authoring import read_controls
        p = Project(self.workspace.project.root)
        return {**read_controls(p, query, source, offset, limit, include_properties),
                'revision': revision(p.root), 'category': 'saved source'}

    def read_control(self, path, source=None):
        from .ai_authoring import read_control
        p = Project(self.workspace.project.root)
        return {**read_control(p, path, source), 'revision': revision(p.root), 'category': 'saved source'}

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

    def read_list_schema(self, name):
        if not isinstance(name, str):
            raise ValueError('List name must be text')
        store = self.workspace.runtime.store
        store.source(name)
        definition = store.catalog.read().get(name)
        return {'name': name, 'definition': definition[1] if definition else store.definitions[name],
                'revision': revision(self.workspace.project.root),
                'note': 'Local list schema and name mappings; no records were fetched.'}

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

    def stage_change(self, expected_revision, sources=None, lists=None, migrations=None, title='AI project change',
                     strict=False, workflows=None, expected_workflow_revision=None):
        return self.workspace.authoring.stage(expected_revision=expected_revision, sources=sources, lists=lists,
            migrations=migrations, title=title, strict=strict, workflows=workflows,
            expected_workflow_revision=expected_workflow_revision)

    def stage_control_edits(self, expected_revision, edits, lists=None, migrations=None,
                            title='AI control edits', strict=False, workflows=None, expected_workflow_revision=None):
        from .ai_authoring import edit_sources
        self.workspace.authoring.check_revision(expected_revision)
        sources = edit_sources(Project(self.workspace.project.root), edits)
        change = self.workspace.authoring.stage(expected_revision=expected_revision, sources=sources,
            lists=lists, migrations=migrations, title=title, strict=strict, workflows=workflows,
            expected_workflow_revision=expected_workflow_revision)
        # The agent already sent the edits; return their diff, not entire YAML documents.
        return {**{k: v for k, v in change.items() if k not in ('sources', 'lists', 'workflows')},
                'changed_sources': list(change['sources']), 'changed_lists': list(change['lists']),
                'changed_workflows': list(change.get('workflows', {}))}

    def apply_change(self, change_id, expected_revision):
        return self.workspace.authoring.apply(change_id, expected_revision=expected_revision)

    def undo_change(self, change_id, expected_revision):
        return self.workspace.authoring.undo(change_id, expected_revision=expected_revision)

    def list_workflows(self, include_scenarios=True):
        if type(include_scenarios) is not bool:
            raise ValueError('include_scenarios must be Boolean')
        catalog = self.workspace.workflows.catalog()
        if not include_scenarios:
            catalog['scenarios'] = [{**{k: v for k, v in e.items() if k != 'scenario'},
                **({'name': e['scenario']['name'], 'step_count': len(e['scenario']['steps'])}
                   if 'scenario' in e else {})} for e in catalog['scenarios']]
        return catalog

    def run_workflow(self, expected_revision, scenario=None, scenario_file=None, change_id=None):
        if (scenario is None) == (scenario_file is None):
            raise ValueError('Provide exactly one inline scenario or scenario_file from list_workflows')
        if scenario_file is not None:
            entry = next((e for e in self.workspace.workflows.catalog(change_id)['scenarios'] if e['file'] == scenario_file), None)
            if entry is None or entry.get('error'):
                raise ValueError('Valid workflow file not found in the project catalog')
            scenario = entry['scenario']
        return self.workspace.workflows.run(scenario, expected_revision=expected_revision, change_id=change_id)

    def read_workflow_report(self, run_id):
        return self.workspace.workflows.report(run_id)

    def run_workflows(self, expected_revision, workflows, change_id=None):
        from .workflows import validate, summarize
        if not isinstance(workflows, list) or not 1 <= len(workflows) <= 20:
            raise ValueError('Provide between 1 and 20 workflows')
        self.workspace.authoring.check_revision(expected_revision)
        catalog = {e['file']: e for e in self.workspace.workflows.catalog(change_id)['scenarios']}
        scenarios = []
        for entry in workflows:
            if not isinstance(entry, dict) or set(entry) not in ({'scenario'}, {'scenario_file'}):
                raise ValueError('Each workflow needs exactly one scenario or scenario_file')
            if 'scenario_file' in entry:
                name = entry['scenario_file']
                if not isinstance(name, str) or name not in catalog or catalog[name].get('error'):
                    raise ValueError('Valid workflow file not found in the project catalog')
                scenario = catalog[name]['scenario']
            else:
                scenario = entry['scenario']
            scenarios.append(validate(scenario))
        # Validate all definitions before creating any reports. Each run has its
        # own disposable runtime/database, even when a prior assertion fails.
        reports = [summarize(self.workspace.workflows.run(scenario,
            expected_revision=expected_revision, change_id=change_id)) for scenario in scenarios]
        return {'status': 'passed' if all(r['status'] == 'passed' for r in reports) else 'failed',
                'revision': expected_revision, 'change_id': change_id, 'runs': reports,
                'passed': sum(r['status'] == 'passed' for r in reports),
                'failed': sum(r['status'] == 'failed' for r in reports)}

    def validate_workflows(self, expected_revision, change_id=None):
        return self.workspace.workflows.validate_saved(expected_revision, change_id)

    def check_change(self, expected_revision, change_id, probe=None):
        from .candidate_inspection import inspect_property
        from .workflows import workflow_revision
        w = self.workspace
        base = w.authoring.check_revision(expected_revision)
        base_data = data_revision(w.runtime.store)
        _, candidate = w.authoring.check_candidate(change_id, base, base_data=base_data)
        revision_before = workflow_revision(w.project.root)
        sample = None
        if probe is not None:
            with w.workflows.isolated_candidate(base, change_id, base_data) as isolated:
                sample = inspect_property(isolated.runtime, probe)
        if data_revision(w.runtime.store) != base_data:
            raise RevisionConflict('Project records changed during the candidate check. Retry against the current project.')
        suite = w.workflows.validate_saved(base, change_id)
        if data_revision(w.runtime.store) != base_data:
            raise RevisionConflict('Project records changed during the candidate check. Retry against the current project.')
        if suite['workflow_revision'] != revision_before:
            raise RevisionConflict('Saved workflows changed during the candidate check. Retry against the current project.')
        broken = next((run for run in suite['runs'] if run['status'] != 'passed'), None)
        failure = None
        if broken:
            failure = {'file': broken['file'], 'report_id': broken.get('id'),
                       **next(iter(broken.get('failures', ())), {}),
                       **({'error': broken['error']} if 'error' in broken else {})}
        diagnostics = candidate['diagnostics']
        return {'change_id': change_id, 'revision': base, 'workflow_revision': suite['workflow_revision'],
                'status': 'passed' if suite['status'] == 'passed' and not diagnostics and
                (sample is None or sample['status'] != 'error') else 'failed',
                'saved_workflows': {'status': suite['status'], 'passed': suite['passed'], 'failed': suite['failed']},
                'first_failure': failure, 'formula': sample, 'diagnostics': diagnostics[:20],
                'diagnostic_count': len(diagnostics)}

    def restart_preview(self, expected_revision):
        w = self.workspace
        w.authoring.check_revision(expected_revision)
        project = Project(w.project.root)
        if project.source_errors:
            raise ValueError('Saved source has errors; repair it before restarting the preview')
        w.open(project)
        if not w.start_simulation:
            w.runtime.restart()
        return {'revision': revision(w.project.root), 'data_revision': data_revision(w.runtime.store),
                'active_screen': w.runtime.active_screen, 'started': w.runtime.started,
                'pending_source': w.runtime.pending_source, 'diagnostics': w.runtime.diagnostics,
                'running_source': self._running_revision_note(),
                'note': 'Preview restarted: unsaved control state was reset and startup/visibility behavior ran.'}

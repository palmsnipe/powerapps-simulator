"""Repeatable browser-equivalent workflows on disposable project snapshots."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import uuid

from .authoring import RevisionConflict, data_revision, revision
from .catalog import atomic_write, json_text
from .fx import Context, table
from .runtime import serial
from .source import Project, safe_path
from .syntax import FxError


STARTER = {'format_version': 1, 'name': 'Startup smoke', 'steps': [
    {'op': 'assert', 'formula': 'IsBlank(App.ActiveScreen)', 'expect': False}]}


def validate(scenario):
    if not isinstance(scenario, dict) or set(scenario) - {'format_version', 'name', 'environment', 'viewport', 'records', 'steps'}:
        raise ValueError('Scenario must be an object containing only documented fields')
    if type(scenario.get('format_version')) is not int or scenario['format_version'] != 1:
        raise ValueError('Scenario format_version must be 1')
    if not isinstance(scenario.get('name'), str) or not scenario['name'].strip():
        raise ValueError('Scenario needs a name')
    for key in ('environment', 'viewport', 'records'):
        if key in scenario and not isinstance(scenario[key], dict):
            raise ValueError(f'{key} must be an object')
    viewport = scenario.get('viewport', {})
    if set(viewport) - {'width', 'height'} or any(type(v) is not int or not 200 <= v <= 4000 for v in viewport.values()):
        raise ValueError('Viewport dimensions must be integers from 200 to 4000')
    environment = scenario.get('environment', {})
    from .numeric import NUMBER_MODES
    from .temporal import NUMERIC_MODES
    from .overloads import ROUND_TABLE_MODES
    from .enum_fx import ENUM_MODES
    from .regex_fx import MODES as REGEX_MODES
    allowed = {'random_seed','regex_mode','enum_mode','clock', 'user', 'parameters', 'language', 'number_mode', 'date_numeric_mode', 'round_table_mode'}
    if set(environment) - allowed:
        raise ValueError('Unknown scenario environment field')
    from .reactivity import validate_seed
    validate_seed(environment.get('random_seed'))
    for key, modes in (('regex_mode', REGEX_MODES),('enum_mode', ENUM_MODES),('number_mode', NUMBER_MODES), ('date_numeric_mode', NUMERIC_MODES), ('round_table_mode', ROUND_TABLE_MODES)):
        if key in environment and (not isinstance(environment[key], str) or environment[key] not in modes):
            raise ValueError(f'Unsupported {key}')
    if 'clock' in environment:
        clock = environment['clock']
        try:
            parsed = datetime.fromisoformat(clock)
            if not parsed.tzinfo:
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError('Scenario clock must be an ISO date/time with a time zone') from None
    if 'user' in environment and (not isinstance(environment['user'], dict) or
            any(not isinstance(environment['user'].get(k), str) for k in ('Email', 'FullName'))):
        raise ValueError('Scenario user needs Email and FullName strings')
    if 'parameters' in environment and not isinstance(environment['parameters'], dict):
        raise ValueError('Scenario parameters must be an object')
    if 'language' in environment and not isinstance(environment['language'], str):
        raise ValueError('Scenario language must be text')
    steps = scenario.get('steps')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 200:
        raise ValueError('Scenario needs between 1 and 200 steps')
    fields = {'advance':{'milliseconds'},'event': {'path', 'target', 'scope', 'event', 'value', 'selection', 'expect_blocked'}, 'assert': {'formula', 'expect', 'error_kind', 'scope'},
              'failure': {'list', 'mode'}, 'scroll': {'path', 'offset', 'extent'}, 'diagnostics': {'expect'}}
    for step in steps:
        if not isinstance(step, dict) or step.get('op') not in fields:
            raise ValueError('Supported steps: event, advance, scroll, assert, failure, diagnostics')
        op = step['op']
        if set(step) - (fields[op] | {'op', 'label'}):
            raise ValueError(f'Unknown {op} step field')
        if 'label' in step and not isinstance(step['label'], str):
            raise ValueError('Step label must be text')
        if op == 'event':
            if ('path' in step)==('target' in step) or not isinstance(step.get('path',step.get('target')),str) or not step.get('path',step.get('target')).strip():
                raise ValueError('Event needs exactly one path or target formula')
            if 'scope' in step and ('target' not in step or not isinstance(step['scope'],str)):
                raise ValueError('Event scope requires a target formula and control path')
            if step.get('event') not in ('OnSelect', 'OnChange', 'Pressed', 'OnSearch', 'OnInput', 'OnCalendar', 'OnNavigate','OnSort','OnMedia'):
                raise ValueError('Event needs a control path and OnSelect, OnChange, OnSearch, OnInput, OnCalendar or Pressed')
            if 'expect_blocked' in step and type(step['expect_blocked']) is not bool:
                raise ValueError('expect_blocked must be Boolean')
            if 'selection' in step and (not isinstance(step['selection'], list) or
                    any(type(i) is not int or i < 0 for i in step['selection'])):
                raise ValueError('Selection uses zero-based nonnegative integer indexes')
        elif op == 'advance':
            from .timers import number
            number(step.get('milliseconds'),'Time advance')
        elif op == 'scroll':
            from .gallery_loading import number
            if not isinstance(step.get('path'), str):
                raise ValueError('Scroll needs a gallery path')
            try:
                number(step.get('offset'), 'scroll offset')
                if 'extent' in step: number(step['extent'], 'visible extent')
            except FxError as error:
                raise ValueError(error.message) from None
        elif op == 'assert':
            if not isinstance(step.get('formula'), str) or not step['formula'].strip():
                raise ValueError('Assertion needs a Power Fx formula')
            if 'scope' in step and not isinstance(step['scope'], str):
                raise ValueError('Assertion scope must be a control path')
            if 'error_kind' in step and (not isinstance(step['error_kind'], str) or 'expect' in step):
                raise ValueError('Use error_kind or expect, never both')
        elif op == 'failure':
            if not isinstance(step.get('list'), str) or step.get('mode') not in (None, 'read', 'write', 'all'):
                raise ValueError('Failure needs a list and mode: read, write, all or null')
        elif type(step.get('expect')) is not int or step['expect'] < 0:
            raise ValueError('Diagnostic assertion expects a nonnegative count')
    if not any(s['op'] in ('assert', 'diagnostics') for s in steps):
        raise ValueError('Scenario needs at least one assertion')
    # Reject non-JSON values, NaN and infinities even for Python callers.
    json.dumps(scenario, allow_nan=False)
    return deepcopy(scenario)


def _copy_project(source, target, store):
    # Do not copy private history, drafts, or a possibly uncheckpointed DB file.
    for name in ('Src', 'lists', 'Assets', 'metadata'):
        directory = source / name
        if directory.exists():
            if directory.is_symlink() or any(p.is_symlink() for p in directory.rglob('*')):
                raise ValueError('Workflow snapshots do not follow project symlinks')
            shutil.copytree(directory, target / name)
    shutil.copy2(source / 'emulator.json', target / 'emulator.json')
    with sqlite3.connect(target / 'data.sqlite') as destination:
        store.db.backup(destination)


def _records(store):
    return {(name, item_id): record for name, item_id, record in
            store.db.execute('SELECT list_name,id,record FROM items ORDER BY list_name,id')}


def _delta(before, after):
    return [{'list': key[0], 'id': key[1], 'operation': 'insert' if key not in before else
             'delete' if key not in after else 'update'}
            for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]


def _equal(actual, expected):
    # JSON equality must distinguish Boolean from Number (Python considers True == 1).
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(_equal(actual[k], expected[k]) for k in actual)
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


class WorkflowService:
    def __init__(self, workspace):
        self.workspace = workspace

    def catalog(self):
        with self.workspace.lock:
            directory = self.workspace.project.root / 'tests'
            if directory.is_symlink():
                raise ValueError('Scenario directory cannot be a symlink')
            result = []
            for path in sorted(directory.glob('*.workflow.json')):
                entry = {'file': path.name}
                try:
                    if path.is_symlink() or path.stat().st_size > 1024 * 1024:
                        raise ValueError('Scenario must be a regular JSON file under 1 MB')
                    entry['scenario'] = validate(json.loads(path.read_text(encoding='utf-8')))
                except (ValueError, OSError) as error:
                    entry['error'] = str(error)
                result.append(entry)
            examples = Path(__file__).parent / 'examples'
            stored = {entry['file'] for entry in result}
            for name in ('forms', 'lifecycle', 'demo'):
                source = f'Src/{name}.pa.yaml'
                if self.workspace.project.documents.get(source) == (examples / f'{name}.pa.yaml').read_text(encoding='utf-8'):
                    for filename, scenario in json.loads((examples / f'{name}.workflows.json').read_text(encoding='utf-8')).items():
                        if filename not in stored:
                            result.append({'file': 'bundled:' + filename, 'scenario': validate(scenario), 'origin': 'bundled fixture'})
            return {'scenarios': result, 'starter': deepcopy(STARTER), 'revision': revision(self.workspace.project.root)}

    def report(self, run_id):
        with self.workspace.lock:
            if not isinstance(run_id, str) or not re.fullmatch('[0-9a-f]{32}', run_id):
                raise ValueError('Invalid workflow run ID')
            path = safe_path(self.workspace.project.root, '.emu/runs/' + run_id + '.json')
            if not path.is_file():
                raise ValueError('Workflow report not found')
            return json.loads(path.read_text(encoding='utf-8'))

    def run(self, scenario, *, expected_revision, change_id=None):
        scenario = validate(scenario)
        w = self.workspace
        with w.lock, TemporaryDirectory(prefix='powerapps-workflow-') as temporary:
            base = w.authoring.check_revision(expected_revision)
            data_base = data_revision(w.runtime.store)
            candidate = None
            if change_id is not None:
                _, candidate = w.authoring._entry(change_id)
                if candidate['status'] != 'staged':
                    raise ValueError('Workflow candidate must be a staged change')
                if candidate['base_revision'] != base or (candidate['data_revision'] is not None and candidate['data_revision'] != data_base):
                    raise RevisionConflict('Staged change is stale; stage it again before testing')
            root = Path(temporary) / 'project'
            root.mkdir()
            _copy_project(w.project.root, root, w.runtime.store)
            # Use the same migration/apply service, but only within the disposable project.
            from .application import Workspace
            isolated = Workspace(Path(temporary), root, start=False)
            try:
                if candidate:
                    change = isolated.authoring.stage(expected_revision=revision(root), sources=candidate['sources'],
                        lists=candidate['lists'], migrations=candidate['migrations'], strict=candidate['strict'], title=candidate['title'])
                    isolated.authoring.apply(change['id'], expected_revision=change['base_revision'])
                    isolated.open(Project(root))
                r = isolated.runtime
                previous_number_mode = r.fx.number_mode
                previous_enum_mode = r.environment.get("enum_mode","legacy")
                r.environment = deepcopy(r.environment)
                r.environment.update(scenario.get('environment', {}))
                if r.fx.number_mode != previous_number_mode or r.environment.get("enum_mode","legacy")!=previous_enum_mode:
                    r.analyze()  # Rebind host-dependent types and supported overload findings.
                frozen = not r.environment.get('clock')
                if frozen:
                    r.environment['clock'] = datetime.now(timezone.utc).isoformat()
                r.viewport.update(scenario.get('viewport', {}))
                for name, records in scenario.get('records', {}).items():
                    if name not in r.store.definitions:
                        raise ValueError(f'Unknown fixture list {name}')
                    r.store.import_rows(name, records, replace=True)
                # Failure injection belongs to the workflow; live preview failures are ignored.
                r.store.failures.clear()
                r.trace = []
                initial_records = _records(r.store)
                r.restart()
                r.state()  # Materialize galleries and settle component inputs like the browser.
                steps = []
                for index, step in enumerate(scenario['steps'], 1):
                    before = _records(r.store)
                    entry = {'index': index, 'op': step['op'], 'label': step.get('label', ''), 'status': 'passed'}
                    r.trace_event('step', index=index, op=step['op'])
                    try:
                        self._step(r, step, entry)
                    except (FxError, ValueError) as error:
                        entry.update(status='failed', error=str(error), error_kind=error.kind if isinstance(error, FxError) else 'Scenario')
                    r.state()
                    entry['active_screen'] = r.active_screen
                    entry['writes'] = _delta(before, _records(r.store))
                    steps.append(entry)
                    # A failed action leaves downstream assertions ambiguous. Failed assertions
                    # continue to expose independent failures in the same final state.
                    if entry['status'] == 'failed' and step['op'] not in ('assert', 'diagnostics'):
                        break
                report = {'id': uuid.uuid4().hex, 'name': scenario['name'], 'created_at': datetime.now(timezone.utc).isoformat(),
                    'status': 'passed' if all(s['status'] == 'passed' for s in steps) else 'failed',
                    'base_revision': base, 'data_revision': data_base, 'candidate_revision': revision(root),
                    'change_id': change_id, 'scenario_digest': hashlib.sha256(json_text(scenario).encode()).hexdigest(),
                    'scenario': scenario, 'environment': serial(r.environment), 'clock_frozen': frozen,
                    'viewport': r.viewport, 'steps': steps, 'steps_skipped': len(scenario['steps']) - len(steps),
                    'trace': r.trace, 'trace_truncated': r.trace_truncated, 'diagnostics': deepcopy(r.diagnostics),
                    'writes': _delta(initial_records, _records(r.store)), 'active_screen': r.active_screen,
                    'data_errors': serial({name:[row for _,row in entries] for name,entries in r.store.operation_errors.items() if entries}),
                    'globals': serial(r.globals), 'collections': serial(r.collections), 'components': serial(r.component_state),
                    'contexts': serial(r.screen_context), 'types': r.inspector_types()}
                w.authoring.check_revision(base)
                if data_revision(w.runtime.store) != data_base:
                    raise RevisionConflict('Project records changed externally during the workflow run')
                atomic_write(safe_path(w.project.root, '.emu/runs/' + report['id'] + '.json'), json_text(report))
                return report
            finally:
                isolated.runtime.close()

    @staticmethod
    def _step(r, step, entry):
        op = step['op']
        if op == 'event':
            if 'target' in step:
                entry.update(target=step['target'],scope=step.get('scope'))
                from .runtime import Ref
                scope=r.refs.get(step.get('scope')) if 'scope' in step else None
                if 'scope' in step and scope is None:raise ValueError('Target scope control does not exist')
                ref=r.fx.evaluate(step['target'],scope.context() if scope else Context(r))
                if not isinstance(ref,Ref) or r.refs.get(ref.path) is not ref:
                    raise ValueError('Target formula must return a current control reference')
                entry['control_path']=ref.path
            else:ref = r.refs.get(step['path'])
            if not ref:
                raise ValueError('Control path does not exist in the rendered app')
            media_observation=ref.family in ('Audio','Video') and step['event']=='OnMedia'
            background_media=False
            if media_observation:
                from .media_controls import snapshot
                background_media=not ref.property('AutoPause') and snapshot(ref)['playing']
            if r.screen_for(ref) != r.active_screen and not background_media:
                raise ValueError('Control is outside the active screen; navigate through the app first')
            ancestor = ref
            while ancestor:
                mode=ancestor.property('DisplayMode')
                if not ancestor.property('Visible') or (mode=='Disabled' if media_observation else mode!='Edit'):
                    if step.get('expect_blocked'):
                        entry.update(blocked=True, blocked_by=ancestor.path, actual={'blocked': True})
                        return
                    raise ValueError('Control is hidden or disabled by the app')
                ancestor = ancestor.parent
            if step.get('expect_blocked'):
                raise ValueError('Expected a hidden or disabled control, but the app allows this event')
            if 'selection' in step:
                rows = table(ref.property('Items'))
                if any(i >= len(rows) for i in step['selection']):
                    raise ValueError('Selection index is outside the control Items')
            value=step.get('value')
            if step['event']=='OnNavigate' and ref.family=='Classic/ComboBox' and isinstance(value,dict) and set(value)=={'index'}:
                value={**value,'option_token':r.combo_token(ref,table(ref.property('Items')))}
            selection=step.get('selection')
            if ref.family=='DataTable' and step['event']=='OnSelect' and selection is not None:
                from .data_table import token
                if len(selection)!=1 or value is not None and (not isinstance(value,dict) or set(value)!={'column'}):
                    raise ValueError('DataTable workflow selection requires one row and an optional column')
                value={**(value or {}),'index':selection[0],'items_token':token(ref)}
                selection=None
            if ref.family=='ModernDataGrid':
                from .modern_grid import token
                if selection is not None:
                    if step['event']!='OnChange':raise ValueError('Grid workflow selection requires OnChange')
                    value={**(value or {}),'indices':selection};selection=None
                if isinstance(value,dict):value={**value,'items_token':token(ref)}
            if ref.family in ('ComboBox','DropDown','Radio'):
                from .canvas_selectors import token,search_token
                if selection is not None:
                    if step['event']!='OnChange':raise ValueError('Native selector selection requires OnChange')
                    value={'indices':selection,'option_token':token(ref)};selection=None
                elif step['event']=='OnSearch' and isinstance(value,str):value={'text':value,'reset_token':search_token(ref)}
                elif isinstance(value,dict) and 'option_token' not in value:value={**value,'option_token':token(ref)}
            if ref.family in ('TextInput','CheckBox') and value is not None and not isinstance(value,dict):
                from .canvas_inputs import token
                value={('text' if ref.family=='TextInput' else 'checked'):value,'reset_token':token(ref)}
            if ref.family in ('Slider','Toggle') and value is not None:
                from .canvas_scalars import token
                value={**value,'reset_token':token(ref)} if isinstance(value,dict) else {('value' if ref.family=='Slider' else 'checked'):value,'reset_token':token(ref)}
            if ref.family == 'DatePicker':
                from .canvas_dates import token
                value = {**value, 'reset_token': token(ref)} if isinstance(value, dict) else {'value': value, 'source': 'calendar', 'reset_token': token(ref)}
            if ref.family=='Toolbar' and isinstance(value,dict) and set(value)=={'command_key'}:
                from .toolbar import token,commands
                value={'key':value['command_key'],'option_token':token(ref,commands(ref))}
            if ref.family in ('ModernRating','FluentV8/Rating') and step['event'] in ('OnChange','OnSelect') and isinstance(value,(int,float)) and not isinstance(value,bool):
                value={'value':value,'reset_token':r.scalar_token(ref)}
            if ref.family in ('Audio','Video') and step['event']=='OnMedia' and isinstance(value,dict) and 'token' not in value:
                from .media_controls import snapshot
                value={**value,'token':snapshot(ref)['token']}
            r.event(ref.path, step['event'], value, selection)
        elif op == 'advance':
            from .timers import advance
            entry['actual']=advance(r,step['milliseconds'])
        elif op == 'scroll':
            ref = r.refs.get(step['path'])
            if not ref or ref.family != 'Gallery':
                raise ValueError('Scroll requires a gallery in the rendered app')
            if r.screen_for(ref) != r.active_screen or any(not a.property('Visible') for a in [ref, *r.ancestors(ref)]):
                raise ValueError('Gallery is outside the visible active screen')
            from .gallery_loading import geometry,token
            value = {'offset': step['offset'], 'extent': step.get('extent', geometry(ref)['extent']), 'viewport_token': token(ref)}
            r.event(ref.path, 'OnViewport', value)
            entry['actual'] = {'loaded': ref.property('AllItemsCount')}
        elif op == 'failure':
            if step['list'] not in r.store.definitions:
                raise ValueError('Unknown failure-injection list')
            r.store.failures[step['list']] = step.get('mode')
            r.invalidate()
        elif op == 'diagnostics':
            entry.update(expected=step['expect'], actual=len(r.diagnostics))
            if entry['actual'] != entry['expected']:
                entry['status'] = 'failed'
        else:
            scope = step.get('scope')
            if scope and scope not in r.refs:
                raise ValueError('Assertion scope control does not exist')
            ctx = r.refs[scope].context() if scope else Context(r)
            try:
                actual = r.fx.evaluate(step['formula'], ctx)
            except FxError as error:
                actual = error
            entry.update(formula=step['formula'], actual=serial(actual))
            if 'error_kind' in step:
                entry['expected_error_kind'] = step['error_kind']
                entry['actual_error_kind'] = actual.kind if isinstance(actual, FxError) else None
                success = entry['actual_error_kind'] == step['error_kind']
            else:
                entry['expected'] = step.get('expect', True)
                success = not isinstance(actual, FxError) and _equal(entry['actual'], entry['expected'])
            if not success:
                entry['status'] = 'failed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('scenario', type=Path)
    parser.add_argument('--change', help='Test a staged change without applying it to the project')
    args = parser.parse_args()
    root = args.project.resolve()
    if not (root / 'Src').is_dir() or not (root / 'emulator.json').is_file():
        parser.error('Choose an existing simulator project')
    from .application import Workspace
    w = Workspace(root.parent, root, start=False)
    try:
        report = w.workflows.run(json.loads(args.scenario.read_text(encoding='utf-8')), expected_revision=revision(root), change_id=args.change)
        print(json_text(report), end='')
        return 0 if report['status'] == 'passed' else 1
    finally:
        w.runtime.close()


if __name__ == '__main__':
    raise SystemExit(main())

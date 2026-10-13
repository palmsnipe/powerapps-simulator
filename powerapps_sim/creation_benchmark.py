"""Measure a real AI creating, editing and testing a local app from an empty workspace."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
from tempfile import TemporaryDirectory
from time import perf_counter

from .agent_benchmark import MeasuredBackend, client_metrics, codex_command, read_events
from .application import Workspace
from .authoring import data_revision, revision
from .catalog import atomic_write, json_text, normalize_definition
from .mcp_server import HeadlessBackend, create_server
from .source import Project
from .fx import Context
from .syntax import FxError
from .workflows import summarize


TOOLS = {'describe_project', 'create_project', 'read_source', 'read_list', 'read_list_schema',
         'read_controls', 'read_control', 'read_diagnostics', 'read_runtime', 'evaluate_formula',
         'list_workflows', 'run_workflow', 'run_workflows', 'read_workflow_report',
         'stage_control_edits', 'stage_change', 'list_changes', 'apply_change',
         'restart_preview', 'export_source'}
SEEDS = [{'ID': 1, 'Title': 'Plan release', 'Done': False},
         {'ID': 2, 'Title': 'Review prototype', 'Done': True},
         {'ID': 3, 'Title': 'Write guide', 'Done': False}]
TOP_CONTROLS = ('Heading', 'TaskCount', 'NewTitle', 'AddTask', 'TaskGallery', 'StatusFilter')


def trial_prompt():
    return '''Build a new local task app AUTONOMOUSLY using ONLY the simulator MCP tools.
The workspace is initially empty: no app, source, data, schemas or tests have been prepared.
Do both phases in order in this single session. No reference source or edits are provided.

Phase 1: call describe_project, then create_project(name="task-desk", title="AI task desk")
with your own complete Power Apps YAML source, local schema, seed rows and at least THREE
saved acceptance workflows. Use a single screen named Main. The local list Tasks must have
ID (read-only integer), Title (required string) and Done (Boolean). Seed exactly these rows:
ID 1, Title "Plan release", Done false; ID 2, Title "Review prototype", Done true;
ID 3, Title "Write guide", Done false. Do not write records during startup.
Create these top-level controls: Heading, TaskCount, NewTitle, AddTask and TaskGallery.
NewTitle is an accessible text input named "New task title". AddTask is a button labelled
"Add task", disabled when the title is empty or whitespace. Adding creates exactly one
local record with a trimmed Title and Done false, and clears the input only on success.
A failed write must preserve the input so a retry creates one record without duplicates.
TaskGallery initially shows all tasks, with TaskTitle and ToggleTask children in each row.
ToggleTask is a button with AccessibleLabel "Toggle " followed by the row's title; it toggles
that row's Done value without changing other records. TaskCount displays the visible count
as e.g. "3 tasks". Make everything fit both 1000x740 and 400x900 previews, with readable
labels and no overlapping top-level controls. Use viewport 1000x740 and a fixed clock
2026-10-13T12:00:00+00:00. No filter in this initial source.
Write meaningful saved workflows covering add/required title, toggle and failure/retry.
Run ALL your saved workflows against the created app and fix failures autonomously.

Phase 2: implement a NEW feature through staged edits: add StatusFilter, a dropdown labelled
"Task status" with options in order All, Open, Done and default All. Open shows Done=false;
Done shows Done=true. TaskCount must track the currently visible rows, including after a
toggle changes a row's status. Keep add, validation, failure/retry and row identity correct.
Stage changes, inspect the diff/diagnostics, run ALL saved workflows plus INLINE workflows
covering All/Open/Done filtering, correct counts and toggling a filtered row. Apply only a
passing candidate. Explicitly restart_preview, check diagnostics and export_source.
Leave the final feature applied. Do not modify schemas, seeded records or saved workflows
after creation; test writes must remain isolated inside workflows. Do not create another app.

Simulator interface hints (contracts, not a solution): supported controls include
ModernText@1.0.0, ModernTextInput@1.1.2 (Default/Text), ModernButton@1.0.0,
ModernDropdown@1.0.0 (Items/DefaultSelectedItems/Selected.Value), Gallery@2.15.0
with Variant Vertical, Items, TemplateSize/TemplateWidth and ThisItem in its children.
Formula property strings start with '='. Workflow format_version is 1, with a name and
steps: event(path or target, event OnChange/OnSelect, value or zero-based selection),
assert(formula, expect), failure(list, mode write or null), diagnostics(expect 0).
Gallery actions can use target="First(TaskGallery.AllItems).ToggleTask"; ordinary paths
are Main/NewTitle, Main/AddTask and Main/StatusFilter. An assert with a scope can evaluate
row controls. Use the tools' JSON schemas and results to investigate any errors.

Exact serialization contracts: local schema definitions use a fields OBJECT (not an array
or JSON Schema properties), e.g. {"fields":{"Label":{"type":"string"}},"required":["Label"]}.
Each workflow step requires the key "op", e.g. {"op":"assert","formula":"1+1","expect":2}.
An intentionally disabled-button event MUST include "expect_blocked":true, otherwise
the runner considers the blocked event a failure. Gallery children have runtime instance
paths, so a static scope such as Main/TaskGallery/ToggleTask does not identify a row.
Use target formulas via TaskGallery.AllItems for row actions; assert row records or an
actual instantiated control. Quote YAML formula scalars containing ': ' or use a block
scalar. Validate these details before committing the saved workflows at creation.

You are authorized to create, stage, test, apply and restart this disposable local app.
Do not use shell, direct file edits, web, other MCP servers, delegation, repository reads
or external Microsoft services. Only simulator tools are allowed. A separate scorer will
run independent acceptance workflows, verify schema/data preservation and undo, and test
the actual generated app in a browser. Finish with a brief result and any obstacles.
'''


def acceptance_workflows():
    """Independent product assertions: never supply source or reference edits to the model."""
    def assertion(formula, expect):
        return {'op': 'assert', 'formula': formula, 'expect': expect}
    def event(path, **args):
        return {'op': 'event', 'path': 'Main/' + path, 'event': 'OnChange', **args}
    add = {'op': 'event', 'path': 'Main/AddTask', 'event': 'OnSelect'}
    toggle = {'op': 'event', 'target': 'First(TaskGallery.AllItems).ToggleTask', 'event': 'OnSelect'}
    scenarios = {
        'required-and-add': [event('NewTitle', value='   '), {**add, 'expect_blocked': True},
            assertion('CountRows(Tasks)', 3), event('NewTitle', value='  New task  '), add,
            assertion('CountRows(Tasks)', 4), assertion('Last(Tasks).Title', 'New task'),
            assertion('Last(Tasks).Done', False), assertion('NewTitle.Text', ''),
            assertion('TaskCount.Text', '4 tasks')],
        'failure-and-retry': [event('NewTitle', value='Retry task'),
            {'op': 'failure', 'list': 'Tasks', 'mode': 'write'}, add,
            assertion('CountRows(Tasks)', 3), assertion('NewTitle.Text', 'Retry task'),
            {'op': 'failure', 'list': 'Tasks', 'mode': None}, add,
            assertion('CountRows(Tasks)', 4), assertion('Last(Tasks).Title', 'Retry task'),
            assertion('NewTitle.Text', '')],
        'filter-and-count': [assertion('StatusFilter.Selected.Value', 'All'),
            assertion('TaskCount.Text', '3 tasks'), event('StatusFilter', selection=[1]),
            assertion('CountRows(TaskGallery.Items)', 2), assertion('TaskCount.Text', '2 tasks'),
            assertion('CountIf(TaskGallery.Items, Done)', 0), event('StatusFilter', selection=[2]),
            assertion('CountRows(TaskGallery.Items)', 1), assertion('TaskCount.Text', '1 tasks'),
            assertion('First(TaskGallery.Items).ID', 2), event('StatusFilter', selection=[0]),
            assertion('TaskCount.Text', '3 tasks')],
        'toggle-filtered-row': [event('StatusFilter', selection=[1]), toggle,
            assertion('LookUp(Tasks, ID = 1).Done', True), assertion('LookUp(Tasks, ID = 2).Done', True),
            assertion('LookUp(Tasks, ID = 3).Done', False), assertion('CountRows(Tasks)', 3),
            assertion('TaskCount.Text', '1 tasks'), assertion('First(TaskGallery.Items).ID', 3),
            event('StatusFilter', selection=[2]), toggle,
            assertion('LookUp(Tasks, ID = 1).Done', False), assertion('LookUp(Tasks, ID = 2).Done', True),
            assertion('TaskCount.Text', '1 tasks')],
    }
    return [{'format_version': 1, 'name': name, 'steps': deepcopy(steps) + [{'op': 'diagnostics', 'expect': 0}],
             **({'viewport': {'width': 400, 'height': 900}} if name == 'required-and-add' else {})}
            for name, steps in scenarios.items()]


def serve(workspace, log):
    backend = HeadlessBackend(workspace=workspace)
    try:
        server = create_server(MeasuredBackend(backend, log, TOOLS))
        from .ai_service import OPERATIONS
        for operation in OPERATIONS:
            if operation not in TOOLS:
                server.remove_tool(operation)
        server.run(transport='stdio')
    finally:
        backend.close()


def phase_evidence(calls):
    completed = [(i, c) for i, c in enumerate(calls) if c['status'] == 'completed']
    creations = [(i, c) for i, c in completed if c['operation'] == 'create_project']
    if len(creations) != 1:
        return {'passed': False, 'successful_creations': len(creations)}
    create_index, creation = creations[0]
    applies = [(i, c) for i, c in completed if c['operation'] == 'apply_change']
    stages = {c['result']['id']: (i, c) for i, c in completed
              if c['operation'] in ('stage_change', 'stage_control_edits')}
    feature_stage_index = stages.get(applies[-1][1]['arguments']['change_id'], (len(calls),))[0] if applies else len(calls)
    tested = {}
    base_files = set(creation['arguments'].get('workflows') or {})
    baseline_files = set()
    for i, c in completed:
        if c['operation'] not in ('run_workflow', 'run_workflows'):
            continue
        result, args = c['result'], c['arguments']
        if result.get('status') != 'passed':
            continue
        files = {e.get('scenario_file') for e in args.get('workflows', [args])} - {None}
        if args.get('change_id'):
            tested.setdefault(args['change_id'], []).append((i, files))
        elif create_index < i < feature_stage_index:
            baseline_files.update(files)
    applied_after_testing = bool(applies)
    for i, c in applies:
        change_id = c['arguments']['change_id']
        earlier_tests = [files for index, files in tested.get(change_id, []) if index < i]
        applied_after_testing &= change_id in stages and stages[change_id][0] > create_index and \
            bool(earlier_tests) and base_files <= set().union(*earlier_tests)
    restarted = any(i > applies[-1][0] and c['operation'] == 'restart_preview' for i, c in completed) if applies else False
    exported = any(i > applies[-1][0] and c['operation'] == 'export_source' for i, c in completed) if applies else False
    initially_no_filter = 'StatusFilter' not in '\n'.join((creation['arguments'].get('sources') or {}).values())
    return {'successful_creations': 1, 'saved_workflows': len(base_files),
            'baseline_workflows_tested': sorted(baseline_files), 'applied_after_candidate_tests': bool(applied_after_testing),
            'initially_no_filter': initially_no_filter, 'restarted_after_apply': restarted,
            'exported_after_apply': exported, 'passed': len(base_files) >= 3 and base_files <= baseline_files
                and applied_after_testing and initially_no_filter and restarted and exported}


def verify_trial(root, calls):
    """Score on copies so evaluation/undo/browser writes never change the retained model app."""
    creation = next((c for c in calls if c['operation'] == 'create_project' and c['status'] == 'completed'), None)
    if creation is None:
        return {'passed': False, 'error': 'The model did not successfully create an app'}
    app_root = root / 'projects' / 'task-desk'
    if not (app_root / 'emulator.json').is_file():
        return {'passed': False, 'error': 'The required task-desk app was not created'}
    with TemporaryDirectory(prefix='creation-score-') as temporary:
        clone = Path(temporary) / 'app'
        shutil.copytree(app_root, clone)
        workspace = Workspace(Path(temporary), clone, start=False)
        project = workspace.project
        try:
            base = revision(clone)
            before = data_revision(workspace.runtime.store)
            independent = [summarize(workspace.workflows.run(s, expected_revision=base)) for s in acceptance_workflows()]
            saved = workspace.workflows.catalog()['scenarios']
            saved_runs = [summarize(workspace.workflows.run(e['scenario'], expected_revision=base)) for e in saved if 'scenario' in e]
            definitions = workspace.runtime.store.definitions
            schemas_unchanged = definitions == {n: normalize_definition(d) for n, d in (creation['arguments'].get('lists') or {}).items()}
            schema = definitions.get('Tasks', {})
            fields = schema.get('fields', {})
            expected_types = {'ID': 'integer', 'Title': 'string', 'Done': 'boolean'}
            schema_valid = set(definitions) == {'Tasks'} and all(fields.get(n, {}).get('type') == t for n, t in expected_types.items()) \
                and 'Title' in schema.get('required', [])
            # IDs are intrinsically protected by the local mutation contract.
            # Check the required behavior instead of insisting on optional metadata.
            try:
                id_result = workspace.runtime.fx.evaluate('Patch(Tasks, First(Tasks), {ID:999})',
                                                         Context(workspace.runtime, behavior=True))
            except FxError as error:
                id_result = error
            id_readonly = isinstance(id_result, FxError) and id_result.kind == 'ReadOnlyValue' \
                and data_revision(workspace.runtime.store) == before
            records_preserved = workspace.runtime.store.rows('Tasks') == SEEDS and data_revision(workspace.runtime.store) == before
            saved_unchanged = {e['file']: e.get('scenario') for e in saved} == (creation['arguments'].get('workflows') or {})
            steps = [s for e in saved for s in e.get('scenario', {}).get('steps', [])]
            coverage = {'add': any(s.get('event') == 'OnSelect' and 'AddTask' in s.get('path', s.get('target', '')) for s in steps),
                        'toggle': any(s.get('event') == 'OnSelect' and 'ToggleTask' in s.get('path', s.get('target', '')) for s in steps),
                        'required_title': any(s.get('expect_blocked') is True for s in steps),
                        'failed_write': any(s.get('op') == 'failure' and s.get('mode') == 'write' for s in steps),
                        'assertions': all(any(s.get('op') == 'assert' for s in e.get('scenario', {}).get('steps', [])) for e in saved)}
            exported = workspace.ai.call('export_source', {}, expected_project=str(project.root))
            atomic_write(root / 'export.json', json_text(exported))
            agent_exports = [c['result'] for c in calls if c['operation'] == 'export_source' and c['status'] == 'completed']
            export_verified = bool(agent_exports) and exported['documents'] == agent_exports[-1]['documents'] == project.documents
            workspace.runtime.restart()
            geometry = []
            for width, height in ((1000, 740), (400, 900)):
                workspace.runtime.viewport = {'width': width, 'height': height}
                workspace.runtime.invalidate()
                state = workspace.runtime.state()
                nodes = {node['name']: node for node in state['tree']['children']}
                boxes = {name: nodes.get(name, {}).get('props', {}) for name in TOP_CONTROLS}
                fits = {n: bool(p) and p['Visible'] and p['Width'] > 0 and p['Height'] > 0 and p['X'] >= 0 and p['Y'] >= 0
                        and p['X'] + p['Width'] <= width and p['Y'] + p['Height'] <= height for n, p in boxes.items()}
                overlap = []
                for index, name in enumerate(TOP_CONTROLS):
                    for other in TOP_CONTROLS[index + 1:]:
                        a, b = boxes[name], boxes[other]
                        if a and b and min(a['X'] + a['Width'], b['X'] + b['Width']) > max(a['X'], b['X']) \
                                and min(a['Y'] + a['Height'], b['Y'] + b['Height']) > max(a['Y'], b['Y']):
                            overlap.append([name, other])
                geometry.append({'width': width, 'height': height, 'controls_fit': fits, 'overlap': overlap})
            clean = not workspace.runtime.diagnostics
            changes = workspace.ai.call('list_changes', {}, expected_project=str(project.root))['changes']
            applied = [c for c in changes if c['status'] == 'applied']
            diffs = [c['diffs'] for c in applied]
            # History is newest first: undo later changes before their bases.
            for change in applied:
                workspace.authoring.undo(change['id'], expected_revision=revision(clone))
            initial = creation['arguments'].get('sources') or {}
            undo_verified = bool(applied) and Project(clone).documents == initial and data_revision(workspace.runtime.store) == before
            return {'acceptance': independent, 'agent_saved_acceptance': saved_runs,
                    'schema_verified': schema_valid, 'id_readonly_verified': id_readonly,
                    'schemas_unchanged': schemas_unchanged,
                    'saved_workflow_coverage': coverage, 'records_preserved': records_preserved,
                    'saved_workflows_unchanged': saved_unchanged, 'export_verified': export_verified,
                    'preview_clean': clean, 'geometry': geometry, 'applied_changes': len(applied),
                    'diffs': diffs, 'undo_verified': undo_verified,
                    'passed': schema_valid and id_readonly and schemas_unchanged and records_preserved and saved_unchanged and all(coverage.values())
                        and export_verified and clean and undo_verified
                        and bool(saved_runs) and len(saved_runs) == len(saved)
                        and all(r['status'] == 'passed' and not r['diagnostics'] for r in independent + saved_runs)
                        and all(all(g['controls_fit'].values()) and not g['overlap'] for g in geometry)}
        finally:
            workspace.runtime.close()


def verify_browser(root):
    """Interact with the AI's saved app on a private server/copy, preserving the trial."""
    from playwright.sync_api import sync_playwright, expect
    from werkzeug.serving import make_server
    from .web import create_app
    artifacts = root / 'browser'
    artifacts.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='creation-browser-') as temporary:
        clone = Path(temporary) / 'app'
        shutil.copytree(root / 'projects/task-desk', clone)
        app = create_app(Path(temporary), clone)
        workspace = app.extensions['workspace']
        server = make_server('127.0.0.1', 0, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 1600, 'height': 1100})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(f'http://127.0.0.1:{server.server_port}')
                    count = page.locator('[data-control=TaskCount]')
                    count.get_by_text('3 tasks', exact=True).wait_for()
                    dropdown = page.get_by_role('combobox', name='Task status', exact=True)
                    def select(label):
                        dropdown.click()
                        page.get_by_role('option', name=label, exact=True).click()
                    select('Open')
                    count.get_by_text('2 tasks', exact=True).wait_for()
                    page.get_by_role('button', name='Toggle Plan release', exact=True).click()
                    count.get_by_text('1 tasks', exact=True).wait_for()
                    assert workspace.runtime.store.rows('Tasks')[0]['Done'] is True
                    select('Done')
                    count.get_by_text('2 tasks', exact=True).wait_for()
                    page.get_by_role('button', name='Toggle Plan release', exact=True).click()
                    count.get_by_text('1 tasks', exact=True).wait_for()
                    assert workspace.runtime.store.rows('Tasks')[0]['Done'] is False
                    select('All')
                    title = page.get_by_role('textbox', name='New task title', exact=True)
                    add = page.get_by_role('button', name='Add task', exact=True)
                    title.fill('   ')
                    title.press('Tab')
                    expect(add).to_be_disabled()
                    title.fill('  Browser task  ')
                    title.press('Tab')
                    with workspace.lock:
                        workspace.runtime.store.failures['Tasks'] = 'write'
                    with page.expect_response(lambda response: response.url.endswith('/api/event') and response.request.method == 'POST'):
                        add.click()
                    expect(title).to_have_value('  Browser task  ')
                    assert len(workspace.runtime.store.rows('Tasks')) == 3
                    with workspace.lock:
                        workspace.runtime.store.failures.clear()
                    add.click()
                    count.get_by_text('4 tasks', exact=True).wait_for()
                    expect(title).to_have_value('')
                    rows = workspace.runtime.store.rows('Tasks')
                    assert rows[-1]['Title'] == 'Browser task' and rows[-1]['Done'] is False
                    assert rows[:3] == SEEDS
                    page.screenshot(path=str(artifacts / 'desktop.png'), full_page=True)
                    page.get_by_label('Preview width', exact=True).fill('400')
                    page.get_by_label('Preview height', exact=True).fill('900')
                    page.get_by_role('button', name='Resize', exact=True).click()
                    page.wait_for_function('state.viewport.width === 400')
                    count.get_by_text('4 tasks', exact=True).wait_for()
                    page.screenshot(path=str(artifacts / 'narrow.png'), full_page=True)
                    assert not errors and not workspace.runtime.diagnostics
                    return {'passed': True, 'filter_toggle': True, 'required_title': True,
                            'failed_write_retry': True, 'trimmed_add': True, 'narrow_preview': True,
                            'other_records_preserved': True, 'javascript_errors': errors,
                            'screenshots': ['browser/desktop.png', 'browser/narrow.png']}
                finally:
                    browser.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
            workspace.runtime.close()


def run_trial(root, executable='codex', timeout=900, *, browser=False):
    root.mkdir(parents=True, exist_ok=False)
    (root / 'projects').mkdir()
    prompt = trial_prompt()
    atomic_write(root / 'prompt.txt', prompt)
    command, client = codex_command(root, 'from_scratch', executable, workspace=True,
                                   server_module='powerapps_sim.creation_benchmark')
    started = perf_counter()
    timed_out = False
    with (root / 'client.jsonl').open('w') as output, (root / 'client.stderr').open('w') as errors:
        with subprocess.Popen(command, stdin=subprocess.PIPE, text=True, stdout=output, stderr=errors,
                              start_new_session=os.name == 'posix') as process:
            try:
                process.communicate(prompt, timeout=timeout)
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                timed_out, exit_code = True, None
                if os.name == 'posix':
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
                process.communicate()
    elapsed = perf_counter() - started
    metrics = client_metrics(read_events(root / 'client.jsonl'))
    calls = read_events(root / 'simulator.jsonl') if (root / 'simulator.jsonl').exists() else []
    phases = phase_evidence(calls)
    try:
        verification = verify_trial(root, calls)
    except Exception as error:
        verification = {'passed': False, 'error': str(error)}
    unsupported = metrics['shell_calls'] or metrics['file_changes'] or metrics['web_searches'] or metrics['other_mcp_servers']
    result = {'format_version': 1, 'timestamp': datetime.now(timezone.utc).isoformat(), 'mode': 'from_scratch',
              'status': 'passed' if exit_code == 0 and not timed_out and not unsupported and not metrics['errors']
                  and metrics['usage'] is not None and phases['passed'] and verification['passed'] else 'failed',
              'measurement': 'One actual AI session, initially empty workspace. AI authors source, schema, records, '
                  'saved workflows and staged edits. No reference app/edits replayed. Native client token counts; '
                  'cached input included in input, not added again. Setup, scoring, browser and coordinating chat '
                  'excluded from model metrics. Human interventions are corrective prompts/edits after launch. '
                  'Raw client and service logs retained locally; this is one trial, not a general speed estimate.',
              'client': client, 'elapsed_seconds': elapsed, 'exit_code': exit_code, 'timed_out': timed_out,
              'client_metrics': metrics, 'manual_interventions': 0, 'corrective_prompts': 0,
              'simulator_calls': len(calls), 'simulator_failures': sum(c['status'] == 'failed' for c in calls),
              'operations': dict(Counter(c['operation'] for c in calls)),
              'request_bytes': sum(c['request_bytes'] for c in calls), 'response_bytes': sum(c['response_bytes'] for c in calls),
              'tool_elapsed_seconds': sum(c['elapsed_seconds'] for c in calls),
              'calls': [{k: c[k] for k in ('operation', 'status', 'elapsed_seconds', 'request_bytes', 'response_bytes')} for c in calls],
              'phases': phases, 'verification': verification}
    if browser:
        try:
            result['browser'] = verify_browser(root)
        except Exception as error:
            result['browser'] = {'passed': False, 'error': str(error)}
        if not result['browser']['passed']:
            result['status'] = 'failed'
    atomic_write(root / 'report.json', json_text(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--workspace', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--log', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--mode', choices=['from_scratch'], help=argparse.SUPPRESS)
    parser.add_argument('--output', type=Path, default=Path('test-results/ai-creation-benchmark'))
    parser.add_argument('--codex', default='codex')
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--browser', action='store_true', help='Also score the generated app in Chromium on a private copy')
    args = parser.parse_args()
    if args.serve:
        serve(args.workspace, args.log)
        return
    result = run_trial(args.output.resolve(), args.codex, args.timeout, browser=args.browser)
    print(json.dumps({k: result[k] for k in ('status', 'simulator_calls', 'elapsed_seconds', 'manual_interventions')}
                     | {'usage': result['client_metrics']['usage'], 'verification': result['verification']['passed']}), flush=True)
    raise SystemExit(0 if result['status'] == 'passed' else 1)


if __name__ == '__main__':
    main()

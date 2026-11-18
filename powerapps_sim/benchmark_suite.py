"""Run a repeatable, multi-task authoring benchmark through measured simulator MCP."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from . import agent_benchmark as agent, creation_benchmark as creation
from .ai_service import OPERATIONS
from .application import Workspace
from .authoring import data_revision, revision
from .benchmark_cases import OPERATIONAL_CASES, assertion, event, scenario
from .benchmark_metrics import CASES, summarize_trials
from .benchmark_power_fx import POWER_FX_CASES
from .catalog import atomic_write, json_text
from .mcp_server import HeadlessBackend, create_server
from .source import Project, load_yaml

SUITE_VERSION = 3
TOOLS = creation.TOOLS | {'list_projects', 'open_project'}
AUTHORING_CASES = OPERATIONAL_CASES | POWER_FX_CASES
BEFORE_TITLE = 'Project workbench'
AFTER_TITLE = 'Project delivery desk'
REPAIR_SOURCE = '''Screens:
  Main:
    Children:
      - NewTitle:
          Control: ModernTextInput@1.1.2
          Properties:
            Default: =""
      - SaveDraft:
          Control: ModernButton@1.0.0
          Properties:
            DisplayMode: =If(IsBlank(Trim(NewTitle.Text)), DisplayMode.Disabled, DisplayMode.Edit)
'''


@dataclass
class Fixture:
    project: Path
    request: str
    documents: dict
    workflows: dict
    data: str
    settings: dict
    other_project: Path | None = None
    other_files: dict | None = None


def type_title(value):
    return event('Main/NewTitle', 'OnChange', value=value)


def project_files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*')
            if p.is_file() and p.relative_to(root).parts[0] != '.emu'}


def saved_workflows(project):
    return {p.name: json.loads(p.read_text(encoding='utf-8')) for p in (project / 'tests').glob('*.workflow.json')}


def prepare_fixture(root, case):
    projects = root / 'projects'
    other_project = None
    if case == 'feature':
        initial, task, documents, data, _ = agent.prepare_trial(projects)
        project, request = initial.root, task['request']
    else:
        backend = HeadlessBackend(workspace=projects)
        try:
            if case == 'switch-edit':
                health = scenario('Startup is clean', {'op': 'diagnostics', 'expect': 0})
                decoy = backend.call('create_project', name='workbench-archive', title=BEFORE_TITLE,
                                     workflows={'startup.workflow.json': health})
                other_project = Path(decoy['project_path'])
                opened = backend.call('create_project', name='workbench-live', title=BEFORE_TITLE,
                                      expected_revision=decoy['revision'], workflows={'startup.workflow.json': health})
                request = (f'Open workbench-live, then change the text of Main/Title to "{AFTER_TITLE}". '
                           'Leave the other project and the rest of this app alone.')
            elif case in AUTHORING_CASES:
                definition = AUTHORING_CASES[case]
                opened = backend.call('create_project', **definition.fixture())
                request = definition.request
            else:
                opened = backend.call('create_project', name='saved-test-repair',
                    sources={'Src/Main.pa.yaml': REPAIR_SOURCE}, workflows={
                        'draft.workflow.json': scenario('Entered title is retained', type_title('Draft title'),
                                                       assertion('Main/NewTitle.Text', 'Draft title')),
                        'disabled.workflow.json': scenario('Blank title disables Save',
                                                          assertion('SaveDraft.DisplayMode', 0)),
                        'startup.workflow.json': scenario('Input initially blank', assertion('IsBlank(NewTitle.Text)', True)),
                    })
                request = ('Open saved-test-repair. Two saved workflows fail because their assertions use incorrect '
                           'reference or value formats. Repair the assertions. The draft test must still verify '
                           'that the input displays the entered title, and the disabled test must still verify '
                           'that Save is disabled with a blank title. Preserve the healthy workflow, app source, '
                           'schemas, and records.')
            project = Path(opened['project_path'])
            documents = backend.call('export_source')['documents']
            data = opened['data_revision']
        finally:
            backend.close()
    return Fixture(project, request, documents, saved_workflows(project), data, Project(project).config,
                   other_project, project_files(other_project) if other_project else None)


def prompt_for(case, fixture):
    if case == 'create':
        return creation.trial_prompt(allow_workflow_repairs=True)
    common = ('Use only simulator MCP tools in this disposable workspace. Start with list_projects and open_project. '
              'Inspect the app and saved tests as needed. Stage the requested change, inspect its diff, run '
              'validate_workflows with the staged change ID, and apply only if the full saved suite passes. '
              'Preserve schemas and records. Keep test writes isolated. Finish with a brief result.')
    finish = ('Run validate_workflows on the saved suite after Apply. Leave the repaired workflows applied.'
              if case == 'repair-tests' else
              'Preserve the saved workflow definitions. After Apply, restart the preview, check diagnostics, '
              'and call export_source. Leave the change applied.')
    return f'{fixture.request}\n\n{common}\n\n{finish}\n'


def serve(workspace, log):
    backend = HeadlessBackend(workspace=workspace)
    try:
        server = create_server(agent.MeasuredBackend(backend, log, TOOLS))
        for operation in set(OPERATIONS) - TOOLS:
            server.remove_tool(operation)
        server.run(transport='stdio')
    finally:
        backend.close()


def edit_phases(fixture, calls, repair):
    completed = [(i, c) for i, c in enumerate(calls) if c['status'] == 'completed']
    opens = [i for i, c in completed if c['operation'] == 'open_project'
             and c['result'].get('project_path') == str(fixture.project)]
    stages = {c['result']['id']: i for i, c in completed
              if c['operation'] in ('stage_control_edits', 'stage_change')}
    applies = [(i, c) for i, c in completed if c['operation'] == 'apply_change']
    validations = [(i, c) for i, c in completed if c['operation'] == 'validate_workflows'
                   and c['result']['status'] == 'passed'
                   and {run['file'] for run in c['result']['runs'] if run['status'] == 'passed'} == set(fixture.workflows)]
    ordered = bool(opens and applies)
    for index, call in applies:
        change = call['arguments']['change_id']
        staged = stages.get(change, -1)
        ordered &= bool(opens and opens[0] < staged and any(
            staged < i < index and c['arguments'].get('change_id') == change for i, c in validations))
    after_apply = [(i, c) for i, c in completed if applies and i > applies[-1][0]]
    checks = {'opened_intended_project': bool(opens), 'applied_after_saved_validation': ordered}
    if repair:
        final = applies[-1][1]['result'] if applies else {}
        checks['validated_saved_revision'] = any(
            not c['arguments'].get('change_id') and c['result'].get('workflow_revision') == final.get('after_workflow_revision')
            and i > applies[-1][0] for i, c in validations) if applies else False
    else:
        checks['restarted_and_exported'] = {'restart_preview', 'export_source'} <= {
            c['operation'] for _, c in after_apply}
    return checks


def title_only(before, after):
    def without_title(documents):
        parsed = {name: load_yaml(text) for name, text in documents.items()}
        try:
            properties = parsed['Src/App.pa.yaml']['Screens']['Main']['Children'][0]['Title']['Properties']
            del properties['Text']
        except (KeyError, IndexError, TypeError):
            return None
        return parsed
    return without_title(after) == without_title(before)


def verify_existing(root, case, fixture, calls):
    """Score a copy. Changes and evidence in the model's project survive undo scoring."""
    repair = case == 'repair-tests'
    checks = edit_phases(fixture, calls, repair)
    documents = Project(fixture.project).documents
    settings = Project(fixture.project).config
    checks['configuration_preserved'] = {k: v for k, v in settings.items() if k != 'source_edited'} == {
        k: v for k, v in fixture.settings.items() if k != 'source_edited'}
    saved = saved_workflows(fixture.project)
    if repair:
        replacements = {}
        for c in calls:
            if c['operation'] == 'apply_change' and c['status'] == 'completed':
                replacements.update(c['result'].get('workflows', {}))
        checks['only_reviewed_test_repairs'] = (set(replacements) == {'draft.workflow.json', 'disabled.workflow.json'}
            and saved == fixture.workflows | replacements and documents == fixture.documents)
    else:
        checks['saved_tests_preserved'] = saved == fixture.workflows
        exports = [c['result'] for c in calls if c['operation'] == 'export_source' and c['status'] == 'completed']
        checks['export_matches'] = bool(exports and exports[-1]['documents'] == documents)
    if fixture.other_project:
        checks['other_project_preserved'] = project_files(fixture.other_project) == fixture.other_files
    checks['no_extra_projects'] = {p.name for p in (root / 'projects').iterdir() if (p / 'emulator.json').is_file()} == {
        p.name for p in (fixture.project, fixture.other_project) if p is not None}

    with TemporaryDirectory(prefix='authoring-suite-score-') as temporary:
        folder = Path(temporary)
        clone = folder / 'app'
        shutil.copytree(fixture.project, clone)
        if case == 'feature':
            details = agent.verify_trial(folder, fixture.documents, fixture.data)
            checks['feature_acceptance_and_undo'] = details['passed']
            return checks, details
        workspace = Workspace(folder, clone, start=False)
        try:
            base = revision(clone)
            suite = workspace.workflows.validate_saved(base)
            details = {'saved_suite': suite}
            checks['saved_suite_passed'] = suite['status'] == 'passed'
            checks['data_preserved'] = data_revision(workspace.runtime.store) == fixture.data
            if case == 'switch-edit':
                visible = workspace.workflows.run(scenario('Read latest heading', assertion('Title.Text', AFTER_TITLE),
                    assertion('Title.Visible', True), {'op': 'diagnostics', 'expect': 0}), expected_revision=base)
                checks['only_title_changed'] = title_only(fixture.documents, documents)
                checks['title_is_visible'] = visible['status'] == 'passed'
            elif case in AUTHORING_CASES:
                acceptance, evidence = AUTHORING_CASES[case].score(workspace.workflows, base)
                checks.update(acceptance)
                details['acceptance'] = evidence
            elif checks['only_reviewed_test_repairs']:
                # A healthy suite must distinguish the expected state from a counterexample.
                draft = saved['draft.workflow.json']
                blank = saved['disabled.workflow.json']
                wrong_text = {**draft, 'steps': [type_title('Different title'),
                    *(s for s in draft['steps'] if s['op'] != 'event')]}
                can_save = {**blank, 'steps': [type_title('Nonblank title'), *blank['steps']]}
                for key, probe in (('draft_assertion_is_effective', wrong_text), ('disabled_assertion_is_effective', can_save)):
                    report = workspace.workflows.run(probe, expected_revision=base)
                    checks[key] = any(s['op'] == 'assert' and s['status'] == 'failed' for s in report['steps'])
            applied = [c for c in workspace.authoring.history() if c['status'] == 'applied']
            for change in sorted(applied, key=lambda c: c['applied_at'], reverse=True):
                workspace.authoring.undo(change['id'], expected_revision=revision(clone))
            checks['undo_restores_original'] = (bool(applied) and Project(clone).documents == fixture.documents
                and saved_workflows(clone) == fixture.workflows and data_revision(workspace.runtime.store) == fixture.data)
            return checks, details
        finally:
            workspace.runtime.close()


def score(root, case, fixture, calls):
    if case != 'create':
        return verify_existing(root, case, fixture, calls)
    phases = creation.phase_evidence(calls)
    verification = creation.verify_trial(root, calls, allow_workflow_repairs=True)
    browser = {'passed': False, 'error': 'No app to open'}
    if phases.get('successful_creations'):
        try:
            browser = creation.verify_browser(root)
        except Exception as error:
            browser = {'passed': False, 'error': f'{type(error).__name__}: {error}'}
    return {'authoring_sequence': phases['passed'], 'acceptance_and_undo': verification['passed'],
            'chromium': browser['passed']}, {'phases': phases, 'verification': verification, 'browser': browser}


def run_case(root, case, args, guidance):
    root.mkdir(parents=True, exist_ok=False)
    fixture = None
    if case == 'create':
        (root / 'projects').mkdir()
    else:
        fixture = prepare_fixture(root, case)
    prompt = prompt_for(case, fixture)
    if guidance:
        prompt += '\nUse the following simulator authoring skill for this task.\n\n' + guidance + '\n'
    command, client = agent.codex_command(root, case, args.codex, workspace=True,
        server_module='powerapps_sim.benchmark_suite', model=args.model,
        reasoning_effort=args.reasoning_effort, service_tier=args.service_tier)
    execution, calls = agent.run_measured_agent(root, command, prompt, args.timeout)
    metrics = execution['client_metrics']
    checks = {'session_completed': execution['exit_code'] == 0 and not execution['timed_out'] and not metrics['errors'],
              'simulator_only': not any(metrics[key] for key in ('shell_calls', 'file_changes', 'web_searches', 'other_mcp_servers')),
              'native_usage_recorded': metrics['usage'] is not None}
    try:
        task_checks, details = score(root, case, fixture, calls)
        checks.update(task_checks)
    except Exception as error:
        checks['independent_scoring_completed'] = False
        details = {'scoring_error': f'{type(error).__name__}: {error}'}
    operations = Counter(c['operation'] for c in calls)
    failure_count = sum(c['status'] == 'failed' for c in calls)
    validation_calls = [c for c in calls if c['operation'] in ('validate_workflows', 'run_workflow', 'run_workflows')]
    trial = {'case': case, 'status': 'passed' if all(checks.values()) else 'failed', 'client': client, **execution,
             'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(), 'checks': checks, 'details': details,
             'steps': metrics['mcp_tool_calls'], 'rejected_steps': metrics['mcp_failures'],
             'simulator_calls': len(calls), 'simulator_failures': failure_count,
             'tool_elapsed_seconds': sum(c['elapsed_seconds'] for c in calls),
             'request_bytes': sum(c['request_bytes'] for c in calls), 'response_bytes': sum(c['response_bytes'] for c in calls),
             'operations': dict(operations), 'validation_calls': len(validation_calls),
             'failed_validations': sum(c.get('result', {}).get('status') == 'failed' for c in validation_calls),
             'staged_changes': sum(c['status'] == 'completed' and c['operation'].startswith('stage_') for c in calls),
             'applied_changes': sum(c['status'] == 'completed' and c['operation'] == 'apply_change' for c in calls)}
    atomic_write(root / 'report.json', json_text(trial))
    return trial


def write_summary(root, cases, results, settings, run_id, started_at):
    by_case = {case: summarize_trials([row for row in results if row['case'] == case]) for case in cases}
    report = {'format_version': 1, 'suite_version': SUITE_VERSION, 'run_id': run_id,
              'started_at': started_at, 'settings': settings,
              'step_definition': 'One completed client MCP tool call, including calls rejected by the client or server.',
              'timing_definition': 'Agent wall time excludes fixture setup and independent scoring. Attempts run sequentially.',
              'overall': summarize_trials(results), 'cases': by_case, 'trials': results}
    atomic_write(root / 'report.json', json_text(report))
    lines = ['# Simulator authoring benchmark', '', f'Model **{settings["model"]}**', '',
             '| Case | Passes | Median time | Median MCP steps | Rejected steps |',
             '| --- | ---: | ---: | ---: | ---: |']
    for case, summary in [*by_case.items(), ('Overall', report['overall'])]:
        seconds, steps = summary['median_seconds'], summary['median_steps']
        time_label = f'{seconds:.1f} s' if seconds is not None else '—'
        step_label = f'{steps:g}' if steps is not None else '—'
        lines.append(f'| {CASES.get(case, case)} | {summary["passed"]}/{summary["attempts"]} | '
                     f'{time_label} | {step_label} | {summary["rejected_steps"]} |')
    lines.extend(['', 'Times cover the agent session. Each attempt used a fresh model session and workspace.', ''])
    atomic_write(root / 'summary.md', '\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--workspace', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--log', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--mode', help=argparse.SUPPRESS)
    parser.add_argument('--model', help='Codex model ID')
    parser.add_argument('--reasoning-effort', default='high')
    parser.add_argument('--service-tier', choices=('default', 'priority'), default='default')
    parser.add_argument('--case', action='append', choices=CASES, help='Select a case (repeatable). Default is all cases.')
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=420, help='Agent timeout in seconds per attempt')
    parser.add_argument('--codex', default='codex')
    parser.add_argument('--output', type=Path, help='New directory for logs and scores')
    parser.add_argument('--skill', type=Path, help='Include this SKILL.md verbatim in each task prompt')
    args = parser.parse_args()
    if args.serve:
        serve(args.workspace, args.log)
        return
    if not args.model or args.repeats < 1 or args.timeout < 1:
        parser.error('Provide --model, a positive --repeats, and a positive --timeout')
    guidance = args.skill.read_text(encoding='utf-8').strip() if args.skill else None
    if args.skill and not guidance:
        parser.error('The skill file is empty')
    cases = tuple(dict.fromkeys(args.case or CASES))
    started_at = datetime.now(timezone.utc)
    timestamp = started_at.strftime('%Y%m%dT%H%M%S%fZ')
    root = (args.output or Path('test-results') / 'authoring-suite' / timestamp).resolve()
    root.mkdir(parents=True, exist_ok=False)
    settings = {'model': args.model, 'reasoning_effort': args.reasoning_effort, 'service_tier': args.service_tier,
                'repeats': args.repeats, 'timeout': args.timeout, 'skill': str(args.skill.resolve()) if args.skill else None,
                'skill_sha256': hashlib.sha256(guidance.encode()).hexdigest() if guidance else None}
    results = []
    for repeat in range(1, args.repeats + 1):
        for case in cases:
            path = root / case / f'{repeat:02d}'
            try:
                result = run_case(path, case, args, guidance)
            except (OSError, ValueError, RuntimeError) as error:
                result = {'case': case, 'status': 'error', 'error': f'{type(error).__name__}: {error}'}
            row = {**result, 'repeat': repeat, 'artifact_dir': str(path)}
            results.append(row)
            write_summary(root, cases, results, settings, timestamp, started_at.isoformat())
            print(json.dumps({k: row.get(k) for k in ('case', 'repeat', 'status', 'elapsed_seconds', 'steps', 'error')}), flush=True)
    print(f'Report saved to {root / "report.json"}', flush=True)
    raise SystemExit(0 if all(row['status'] == 'passed' for row in results) else 1)


if __name__ == '__main__':
    main()

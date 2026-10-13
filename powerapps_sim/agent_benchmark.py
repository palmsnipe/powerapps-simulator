"""Measure real Codex authoring through local simulator MCP tools, without reference edits."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from time import perf_counter
import tomllib

from .application import Workspace
from .authoring import data_revision, revision
from .catalog import atomic_write, json_text
from .fixtures import ai_development_project
from .mcp_server import HeadlessBackend, create_server
from .source import Project
from .workflows import summarize


COMMON = {'describe_project', 'read_diagnostics', 'read_runtime', 'evaluate_formula',
          'export_source', 'list_changes', 'apply_change', 'restart_preview',
          'list_workflows', 'read_workflow_report'}
MODE_TOOLS = {
    'full_document': COMMON | {'read_source', 'read_list', 'stage_change', 'run_workflow'},
    'focused': COMMON | {'read_controls', 'read_control', 'read_list_schema',
                         'stage_control_edits', 'run_workflows'},
}


class MeasuredBackend:
    """Audit every service invocation, including failures and resource reads."""
    def __init__(self, backend, log, allowed):
        self.backend, self.log, self.allowed = backend, Path(log), allowed

    def call(self, operation, **arguments):
        started = perf_counter()
        entry = {'operation': operation, 'arguments': arguments,
                 'request_bytes': len(json_text({'arguments': arguments,
                     'expected_project': self.backend.project}).encode('utf-8'))}
        try:
            if operation not in self.allowed:
                raise ValueError('Operation is unavailable in this benchmark mode')
            result = self.backend.call(operation, **arguments)
            entry.update(status='completed', result=result,
                         response_bytes=len(json_text(result).encode('utf-8')))
            return result
        except Exception as error:
            entry.update(status='failed', error=str(error),
                         response_bytes=len(json_text({'error': str(error)}).encode('utf-8')))
            raise
        finally:
            entry['elapsed_seconds'] = perf_counter() - started
            with self.log.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(entry, ensure_ascii=True, allow_nan=False) + '\n')


def serve(project, log, mode):
    backend = HeadlessBackend(project)
    try:
        server = create_server(MeasuredBackend(backend, log, MODE_TOOLS[mode]))
        from .ai_service import OPERATIONS
        for operation in OPERATIONS:
            if operation not in MODE_TOOLS[mode]:
                server.remove_tool(operation)
        server.run(transport='stdio')
    finally:
        backend.close()


def read_events(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def client_metrics(events):
    """Count completed items once; never treat byte estimates as model tokens."""
    items = {e['item']['id']: e['item'] for e in events
             if e.get('type') == 'item.completed' and 'id' in e.get('item', {})}
    counts = Counter(item['type'] for item in items.values())
    usages = [e['usage'] for e in events if e.get('type') == 'turn.completed' and e.get('usage')]
    usage = {key: sum(u.get(key, 0) for u in usages) for key in set().union(*(u.keys() for u in usages))} if usages else None
    if usage is not None:
        usage['total_tokens'] = usage.get('input_tokens', 0) + usage.get('output_tokens', 0)
    return {'usage': usage, 'completed_turns': len(usages), 'items': dict(counts),
            'mcp_tool_calls': counts['mcp_tool_call'],
            'mcp_failures': sum(i.get('status') == 'failed' for i in items.values() if i['type'] == 'mcp_tool_call'),
            'shell_calls': counts['command_execution'], 'file_changes': counts['file_change'],
            'web_searches': counts['web_search'],
            'other_mcp_servers': sorted({i.get('server', '') for i in items.values()
                if i['type'] == 'mcp_tool_call' and i.get('server') != 'simulator'}),
            'errors': [e for e in events if e.get('type') in ('turn.failed', 'error')]}


def prepare_trial(root):
    project = ai_development_project(root / 'app')
    task = project.read_json('benchmark.task.json', {})
    task.pop('reference_edits', None)
    atomic_write(project.root / 'benchmark.task.json', json_text(task))
    original = dict(project.documents)
    workspace = Workspace(root, project.root)
    try:
        data = data_revision(workspace.runtime.store)
        base = revision(project.root)
        baseline = [summarize(workspace.workflows.run(entry['scenario'], expected_revision=base))
                    for entry in workspace.workflows.catalog()['scenarios']]
    finally:
        workspace.runtime.close()
    return project, task, original, data, baseline


def trial_prompt(task, mode):
    interface = ('Use read_source/read_list for context, stage_change for full source replacements, '
                 'and run_workflow for each existing acceptance scenario. Request the full workflow catalog.'
                 if mode == 'full_document' else
                 'Use focused control/schema discovery, stage_control_edits for source changes, '
                 'and run_workflows for batch verification. Request the compact workflow catalog when possible.')
    return (
        'Implement the following app request autonomously using ONLY the simulator MCP tools.\n\n'
        + task['request'] + '\n\n' + interface + '\n\n'
        'This is an authorized local authoring task. Inspect the project and its saved acceptance '
        'workflows. Generate your own edits; no reference solution is provided. Stage, inspect the '
        'diff and diagnostics, and run ALL existing acceptance workflows against the candidate. '
        'Fix failures yourself. Apply only a passing candidate, explicitly restart the preview, '
        'check diagnostics and export the source. Leave the feature applied for independent evaluation. '
        'Do not change tests, schemas, records or configuration. Do not use shell, file editing, web, '
        'other servers, delegation or external Microsoft services. Do not read any repository outside '
        'this trial. Keep requests focused and finish with a brief result, including any obstacles. '
        'The harness independently checks workflows, source/data preservation and undo after you finish.'
    )


def codex_command(root, mode, executable, *, workspace=False, server_module='powerapps_sim.agent_benchmark'):
    # Retain the user's model/provider settings, while disabling unrelated integrations.
    home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
    config_path = home / 'config.toml'
    config = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
    command = [executable, '--no-daemon', '-a', 'never', 'exec', '--json', '--ephemeral',
               '--skip-git-repo-check', '--sandbox', 'read-only', '-C', str(root),
               '--disable', 'multi_agent', '--disable', 'plugins', '--disable', 'apps',
               '--disable', 'shell_tool', '--enable', 'skip_host_skill_discovery',
               '-c', 'web_search="disabled"', '-c', 'notify=[]']
    for name in config.get('mcp_servers', {}):
        command += ['-c', f'mcp_servers.{name}.enabled=false']
    # -c is subprocess argv, not a shell command: source paths cannot execute code.
    package_root = str(Path(__file__).resolve().parent.parent)
    script = f'import sys; sys.path.insert(0, {package_root!r}); from {server_module} import main; main()'
    server_args = ['-c', script, '--serve', '--workspace' if workspace else '--project', str(root / ('projects' if workspace else 'app')),
                   '--log', str(root / 'simulator.jsonl'), '--mode', mode]
    # Authoring is explicitly authorized on this disposable project. This policy
    # is invocation-local and never changes the user's stored MCP configuration.
    command += ['-c', 'mcp_servers.simulator=' + '{command=' + json.dumps(sys.executable)
                + ',args=' + json.dumps(server_args)
                + ',required=true,tool_timeout_sec=120,default_tools_approval_mode="approve"}', '-']
    return command, {'model': config.get('model'), 'reasoning_effort': config.get('model_reasoning_effort'),
                     'codex_version': subprocess.check_output([executable, '--version'], text=True).strip(),
                     'simulator_approval_mode': 'approve'}


def verify_trial(root, original, original_data):
    """Independent scoring and undo, explicitly excluded from model tool metrics."""
    project = Project(root / 'app')
    workspace = Workspace(root, project.root)
    try:
        base = revision(project.root)
        runs = [summarize(workspace.workflows.run(e['scenario'], expected_revision=base))
                for e in workspace.workflows.catalog()['scenarios']]
        changes = workspace.ai.call('list_changes', {}, expected_project=str(project.root))['changes']
        applied = [change for change in changes if change['status'] == 'applied']
        exported = workspace.ai.call('export_source', {}, expected_project=str(project.root))
        export_matches = exported['documents'] == project.documents
        atomic_write(root / 'export.json', json_text(exported))
        unchanged_data = data_revision(workspace.runtime.store) == original_data
        workspace.runtime.state()
        preview_clean = not workspace.runtime.diagnostics
        geometry = []
        for width, height in ((1000, 740), (400, 900)):
            workspace.runtime.viewport = {'width': width, 'height': height}
            workspace.runtime.invalidate()
            state = workspace.runtime.state()
            nodes = {node['name']: node for node in state['tree']['children']}
            checks = {}
            for name in ('StatusFilter', 'ProjectGallery', 'ProjectForm', 'SaveProject', 'SaveFeedback'):
                props = nodes.get(name, {}).get('props', {})
                checks[name] = bool(props) and props['X'] >= 0 and props['Y'] >= 0 and \
                    props['X'] + props['Width'] <= width and props['Y'] + props['Height'] <= height
            geometry.append({'width': width, 'height': height, 'controls_fit': checks})
        for change in reversed(applied):
            workspace.authoring.undo(change['id'], expected_revision=revision(project.root))
        undo = Project(project.root).documents == original and data_revision(workspace.runtime.store) == original_data
        return {'acceptance': runs, 'applied_changes': len(applied),
                'diffs': [change['diffs'] for change in applied], 'export_verified': export_matches,
                'records_unchanged': unchanged_data, 'preview_clean': preview_clean,
                'geometry': geometry, 'undo_verified': undo,
                'passed': bool(applied) and all(r['status'] == 'passed' and not r['diagnostics'] for r in runs)
                    and export_matches and unchanged_data and preview_clean and undo
                    and all(all(g['controls_fit'].values()) for g in geometry)}
    finally:
        workspace.runtime.close()


def run_trial(root, mode, executable='codex', timeout=900):
    root.mkdir(parents=True, exist_ok=False)
    project, task, original, data, baseline = prepare_trial(root)
    prompt = trial_prompt(task, mode)
    atomic_write(root / 'prompt.txt', prompt)
    command, client = codex_command(root, mode, executable)
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
                # Stop the trial's MCP subprocess as well, releasing project ownership.
                if os.name == 'posix':
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
                process.communicate()
    elapsed = perf_counter() - started
    events = read_events(root / 'client.jsonl')
    metrics = client_metrics(events)
    calls = read_events(root / 'simulator.jsonl') if (root / 'simulator.jsonl').exists() else []
    verification = verify_trial(root, original, data)
    unsupported = metrics['shell_calls'] or metrics['file_changes'] or metrics['web_searches'] or metrics['other_mcp_servers']
    return {'mode': mode, 'status': 'passed' if exit_code == 0 and verification['passed'] and not unsupported
                and metrics['usage'] is not None else 'failed',
            'client': client, 'elapsed_seconds': elapsed, 'exit_code': exit_code, 'timed_out': timed_out,
            'simulator_calls': len(calls), 'simulator_failures': sum(c['status'] == 'failed' for c in calls),
            'operations': dict(Counter(c['operation'] for c in calls)),
            'request_bytes': sum(c['request_bytes'] for c in calls),
            'response_bytes': sum(c['response_bytes'] for c in calls),
            'tool_elapsed_seconds': sum(c['elapsed_seconds'] for c in calls),
            'client_metrics': metrics, 'manual_interventions': 0, 'corrective_prompts': 0,
            'calls': [{k: c[k] for k in ('operation', 'status', 'elapsed_seconds', 'request_bytes', 'response_bytes')}
                      for c in calls], 'baseline': baseline, 'verification': verification}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--project', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--log', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--mode', choices=MODE_TOOLS)
    parser.add_argument('--output', type=Path, default=Path('test-results/ai-agent-benchmark'))
    parser.add_argument('--codex', default='codex')
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    if args.serve:
        serve(args.project, args.log, args.mode)
        return
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for mode in ([args.mode] if args.mode else MODE_TOOLS):
        print(f'Starting real AI trial: {mode}', flush=True)
        result = run_trial(output / mode, mode, args.codex, args.timeout)
        results.append(result)
        atomic_write(output / f'{mode}.json', json_text(result))
        print(json.dumps({k: result[k] for k in ('mode', 'status', 'simulator_calls', 'elapsed_seconds',
                                               'manual_interventions')} | {'usage': result['client_metrics']['usage']}), flush=True)
    report = {'format_version': 1, 'timestamp': datetime.now(timezone.utc).isoformat(),
              'measurement': 'Actual Codex generation through local simulator MCP. Independent fresh contexts; reference edits removed. '
                  'One trial per mode, not a statistical estimate. Token usage is client-reported, cached input is a subset of input. '
                  'No model tokens are estimated from bytes. Manual interventions count human corrections during the task; '
                  'automatic fixture setup and post-run verification/undo are excluded from agent metrics. '
                  'Raw client and simulator logs remain local in the output directory.',
              'status': 'passed' if all(r['status'] == 'passed' for r in results) else 'failed', 'results': results}
    atomic_write(output / 'report.json', json_text(report))
    raise SystemExit(0 if report['status'] == 'passed' else 1)


if __name__ == '__main__':
    main()

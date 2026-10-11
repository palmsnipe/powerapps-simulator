"""Replay one fictional feature through full-document and focused local AI tools.

This measures tool traffic and execution overhead, not model reasoning or tokens.
Both modes use the same reference edits and independently generated projects.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from .ai_authoring import edit_sources
from .application import Workspace
from .authoring import data_revision
from .catalog import atomic_write, json_text
from .fixtures import ai_development_project
from .source import Project
from .workflows import summarize


def _replay(root, mode):
    project = ai_development_project(root / mode)
    workspace = Workspace(root, project.root)
    calls = []

    def call(operation, **arguments):
        started = perf_counter()
        result = workspace.ai.call(operation, arguments, expected_project=str(project.root))
        calls.append({'operation': operation, 'elapsed_seconds': perf_counter() - started,
                      'request_bytes': len(json_text({'arguments': arguments,
                          'expected_project': str(project.root)}).encode('utf-8')),
                      'response_bytes': len(json_text(result).encode('utf-8'))})
        return result

    try:
        original = dict(project.documents)
        original_data = data_revision(workspace.runtime.store)
        task = project.read_json('benchmark.task.json', {})
        description = call('describe_project')
        base = description['revision']
        catalog = workspace.workflows.catalog()['scenarios']
        baseline = [summarize(workspace.workflows.run(e['scenario'], expected_revision=base)) for e in catalog]
        if mode == 'full_document':
            call('read_source', name='Src/ai-development.pa.yaml')
            call('read_list', name='Projects')
            sources = edit_sources(Project(project.root), task['reference_edits'])
            change = call('stage_change', expected_revision=base, sources=sources,
                          title=task['name'], strict=True)
        else:
            call('read_controls', query='Projects')
            call('read_control', path='Workspace/ProjectGallery')
            call('read_control', path='Workspace/ProjectForm')
            call('read_list_schema', name='Projects')
            change = call('stage_control_edits', expected_revision=base, edits=task['reference_edits'],
                          title=task['name'], strict=True)
        catalog = call('list_workflows', include_scenarios=mode == 'full_document')['scenarios']
        if mode == 'full_document':
            runs = [summarize(call('run_workflow', expected_revision=base,
                change_id=change['id'], scenario_file=e['file'])) for e in catalog]
        else:
            runs = call('run_workflows', expected_revision=base, change_id=change['id'],
                        workflows=[{'scenario_file': e['file']} for e in catalog])['runs']
        if any(r['status'] != 'passed' or r['diagnostics'] for r in runs):
            raise ValueError('Reference candidate did not pass acceptance workflows')
        applied = call('apply_change', change_id=change['id'], expected_revision=base)
        preview = call('restart_preview', expected_revision=applied['after_revision'])
        exported = call('export_source')
        if preview['diagnostics'] or not preview['running_source']['source_matches_saved']:
            raise ValueError('Preview did not load the verified source cleanly')
        if exported['documents'] != Project(project.root).documents:
            raise ValueError('Export differs from the applied source')
        call('undo_change', change_id=change['id'], expected_revision=applied['after_revision'])
        if Project(project.root).documents != original or data_revision(workspace.runtime.store) != original_data:
            raise ValueError('Undo did not restore the original source and records')
        return {'mode': mode, 'status': 'passed', 'tool_calls': len(calls),
                'tool_elapsed_seconds': sum(c['elapsed_seconds'] for c in calls),
                'request_bytes': sum(c['request_bytes'] for c in calls),
                'response_bytes': sum(c['response_bytes'] for c in calls),
                'model_tokens': None, 'manual_interventions': None,
                'calls': calls, 'baseline': baseline, 'candidate': runs,
                'preview_verified': True, 'export_verified': bool(exported['documents']), 'undo_verified': True}
    finally:
        workspace.runtime.close()


def run_benchmark():
    with TemporaryDirectory(prefix='powerapps-ai-benchmark-') as temporary:
        root = Path(temporary)
        results = [_replay(root, mode) for mode in ('full_document', 'focused')]
    full, focused = results
    return {'format_version': 1, 'name': 'Local AI authoring: status filter and failed-save recovery',
            'status': 'passed', 'measurement': 'Reference tool replay; no AI model is invoked. Bytes are UTF-8 JSON payloads using the same serializer for both modes; SDK envelopes and tool schemas are excluded. Timings vary by machine. Model token use and human intervention are unmeasured.',
            'results': results, 'comparison': {
                'tool_calls_saved': full['tool_calls'] - focused['tool_calls'],
                'request_bytes_saved': full['request_bytes'] - focused['request_bytes'],
                'response_bytes_saved': full['response_bytes'] - focused['response_bytes']}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', type=Path, help='Save the complete comparison report')
    args = parser.parse_args()
    result = run_benchmark()
    if args.json:
        atomic_write(args.json, json_text(result))
    print(json.dumps({'status': result['status'], 'comparison': result['comparison'],
        'results': [{k: r[k] for k in ('mode', 'tool_calls', 'tool_elapsed_seconds', 'request_bytes', 'response_bytes')}
                    for r in result['results']]}, indent=2))


if __name__ == '__main__':
    main()

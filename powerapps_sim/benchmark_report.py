"""Regenerate an authoring benchmark comparison from saved suite report.json files."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from io import StringIO
import json
from pathlib import Path
import re

from .benchmark_metrics import CASES, summarize_trials
from .catalog import atomic_write

TITLE = 'Power Apps simulator authoring benchmark'
INTRO = ('Each trial uses a fresh agent session and a disposable Power Apps project workspace. '
         'Independent checks verify the resulting app and the authoring workflow.')
METHOD = ('Pass rates use all recorded attempts, including timeouts and setup errors. Pending attempts are shown '
          'separately. Agent time excludes fixture setup and independent scoring. MCP steps count completed client '
          'calls, including rejections. Read small samples as a baseline and compare models within the same '
          'suite and settings.')
TOKEN_FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens',
                'output_tokens', 'reasoning_output_tokens', 'total_tokens')
TRIAL_FIELDS = ('case', 'repeat', 'status', 'elapsed_seconds', 'steps', 'rejected_steps',
                'simulator_calls', 'simulator_failures', 'tool_elapsed_seconds', 'request_bytes', 'response_bytes',
                'validation_calls', 'failed_validations', 'staged_changes', 'applied_changes', 'timed_out',
                'exit_code', 'error', 'prompt_sha256', 'artifact_dir')
CSV_FIELDS = ('run_id', 'started_at', 'suite_version', 'model', 'reasoning_effort', 'service_tier',
              'skill_sha256', 'timeout_seconds', 'codex_version', 'provider', 'runner', 'report_path', *TRIAL_FIELDS,
              'checks_passed', 'checks_total', 'failed_checks', *TOKEN_FIELDS)
HEADERS = ('Model', 'Passed / run', 'Pass rate', 'Time (s)', 'Pass time (s)', 'MCP steps', 'Rejected')
COLUMN_NOTE = ('Time and MCP steps are medians over recorded measurements. Pass time includes only '
               'successful trials. Rejected counts are totals.')
RUNTIME_NOTE = ('These runs use the same cases, skill, and timeout and request the same reasoning level. '
                'Each elapsed time reflects the model, client, and inference service used for that run.')


@dataclass
class Run:
    path: Path
    report: dict
    id: str
    date: str

    @property
    def settings(self):
        return self.report['settings']

    @property
    def trials(self):
        return self.report['trials']

    @property
    def cases(self):
        selected = self.report['cases']
        return tuple(case for case in CASES if case in selected) + tuple(sorted(set(selected) - CASES.keys()))

    @property
    def condition(self):
        versions = {row['client']['codex_version'] for row in self.trials
                    if (row.get('client') or {}).get('codex_version')}
        return (self.report['suite_version'], self.cases, self.settings.get('reasoning_effort') or 'unspecified',
                self.settings.get('service_tier') or 'unspecified', self.settings.get('skill_sha256') or '',
                self.settings.get('timeout') or 0,
                ', '.join(sorted(versions)) or self.settings.get('runner') or 'unrecorded')


def read_runs(paths):
    runs = {}
    for path in paths:
        if path.is_dir():
            path = path / 'report.json'
        report = json.loads(path.read_text(encoding='utf-8'))
        if report.get('format_version') != 1 or not all(key in report for key in ('suite_version', 'settings', 'cases', 'trials')):
            raise ValueError(f'{path} is not a supported authoring suite report')
        trials = report['trials']
        trial_keys = {(row['case'], row['repeat']) for row in trials}
        if len(trial_keys) != len(trials) or any(
            case not in report['cases'] or not 1 <= repeat <= report['settings']['repeats'] for case, repeat in trial_keys
        ):
            raise ValueError(f'{path} has duplicate or unexpected attempts')
        run_id = report.get('run_id') or 'legacy-' + hashlib.sha256(
            json.dumps(report, sort_keys=True).encode()).hexdigest()[:16]
        previous = runs.get(run_id)
        if previous is not None and previous.report != report:
            raise ValueError(f'{path} and {previous.path} share a run ID but have different data')
        date = report.get('started_at', '')
        if not date:
            match = re.search(r'(\d{8}T\d{6})\d{0,6}Z$', path.parent.name)
            if match:
                date = datetime.strptime(match[1], '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc).isoformat()
        if previous is None:
            runs[run_id] = Run(path, report, run_id, date)
    return sorted(runs.values(), key=lambda run: (run.date, run.id))


def conditions(runs):
    grouped = defaultdict(list)
    for run in runs:
        grouped[run.condition].append(run)
    return sorted(grouped.items(), reverse=True)


def condition_text(condition, runs):
    _, _, effort, tier, skill, timeout, client = condition
    guidance = f'skill {skill[:12]}' if skill else 'no supplied skill'
    dates = ', '.join(datetime.fromisoformat(date).strftime('%d %B %Y')
                      for date in sorted({run.date[:10] for run in runs if run.date}))
    runtime = 'local inference' if tier == 'local' else f'{tier} tier'
    settings = f'{effort.capitalize()} reasoning, {runtime}, {timeout} s timeout, {client}, {guidance}.'
    return f'{settings} Runs recorded {dates} UTC.' if dates else settings


def comparison_rows(runs, case=None):
    by_model = defaultdict(list)
    for run in runs:
        by_model[run.settings['model']].append(run)
    rows = []
    for model, selected in sorted(by_model.items()):
        trials = [row for run in selected for row in run.trials if case is None or row['case'] == case]
        rows.append((model, summarize_trials(trials)))
    return rows


def display_rows(rows):
    def number(value, spec):
        return format(value, spec) if value is not None else '—'

    return [(model, f'{row["passed"]}/{row["attempts"]}', number(row['success_rate'], '.0%'),
             number(row['median_seconds'], '.1f'), number(row['median_success_seconds'], '.1f'),
             number(row['median_steps'], 'g'), str(row['rejected_steps'])) for model, row in rows]


def introduction(grouped):
    condition, runs = grouped[0]
    overall = comparison_rows(runs)
    if len(overall) != 1:
        return INTRO
    model, summary = overall[0]
    return (f'{model} passed {summary["passed"]} of {summary["attempts"]} recorded attempts in suite {condition[0]}. '
            f'{INTRO}')


def runtime_overview(grouped, case=None):
    """Compare the newest workload across clients without pooling its results."""
    primary = grouped[0][0]
    matches = [(condition, runs) for condition, runs in grouped
               if condition[:3] == primary[:3] and condition[4:6] == primary[4:6]]
    if len(matches) < 2:
        return []
    rows = []
    for condition, runs in matches:
        tier, client = condition[3], condition[-1]
        runtime = f'{client}, local' if tier == 'local' else f'{client}, {tier}'
        rows.extend((f'{model}\n{runtime}', *values)
                    for model, *values in display_rows(comparison_rows(runs, case)))
    return rows


def case_rows(condition, runs):
    include_model = len({run.settings['model'] for run in runs}) > 1
    for case in condition[1]:
        label = CASES.get(case, case)
        for model, *values in display_rows(comparison_rows(runs, case)):
            yield (f'{label}\n{model}' if include_model else label, *values)


def run_notes(runs):
    states = Counter(row['status'] for run in runs for row in run.trials)
    pending = sum(len(run.cases) * run.settings['repeats'] - len(run.trials) for run in runs)
    validations = sum(row.get('failed_validations', 0) for run in runs for row in run.trials)
    timeouts = sum(bool(row.get('timed_out')) for run in runs for row in run.trials)
    def count(value, label):
        return f'{value} {label}' + ('s' if value != 1 else '')

    return (f'{count(states["failed"], "failed trial")} ({count(timeouts, "timeout")}), '
            f'{count(states["error"], "setup error")}, and {count(pending, "pending attempt")}. '
            f'Authoring produced {count(validations, "failed workflow validation")}.')


def failed_check_counts(runs):
    return Counter((run.settings['model'], row['case'], check) for run in runs for row in run.trials
                   for check, passed in row.get('checks', {}).items() if not passed)


def failure_notes(runs):
    return [f'{model} · {case} · {check.replace("_", " ")} ({count})'
            for (model, case, check), count in sorted(failed_check_counts(runs).items())]


def csv_text(runs):
    text = StringIO(newline='')
    writer = csv.DictWriter(text, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for run in runs:
        for trial in run.trials:
            checks = trial.get('checks')
            client = trial.get('client') or {}
            usage = (trial.get('client_metrics') or {}).get('usage') or {}
            row = {key: trial.get(key) for key in TRIAL_FIELDS}
            row.update(run_id=run.id, started_at=run.date, suite_version=run.report['suite_version'],
                       model=run.settings['model'], reasoning_effort=run.settings.get('reasoning_effort'),
                       service_tier=run.settings.get('service_tier'), skill_sha256=run.settings.get('skill_sha256'),
                       timeout_seconds=run.settings.get('timeout'), codex_version=client.get('codex_version'),
                       provider=client.get('provider', run.settings.get('provider')),
                       runner=client.get('runner', run.settings.get('runner')),
                       report_path=str(run.path), checks_passed=sum(checks.values()) if checks is not None else None,
                       checks_total=len(checks) if checks is not None else None,
                       failed_checks='; '.join(key for key, ok in (checks or {}).items() if not ok),
                       **{key: usage.get(key) for key in TOKEN_FIELDS})
            # Keep text inert when opened in Excel. Numeric cells retain their original type.
            writer.writerow({key: "'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@'))
                             else value for key, value in row.items()})
    return text.getvalue()


def markdown_text(grouped):
    lines = [f'# {TITLE}', '', introduction(grouped), '', METHOD, '', COLUMN_NOTE, '']
    overview = runtime_overview(grouped)
    if overview:
        lines.extend(['## Current suite across runtimes', '', RUNTIME_NOTE, ''])
        lines.extend(markdown_table('Model and runtime', overview))
    for index, (condition, runs) in enumerate(grouped, 1):
        lines.extend([f'## Suite {condition[0]} Comparison {index}', '', condition_text(condition, runs), ''])
        for label, name, rows in (
            ('Overall', 'Model', display_rows(comparison_rows(runs))),
            ('Results by case', 'Case', case_rows(condition, runs)),
        ):
            lines.extend([f'### {label}', '', *markdown_table(name, rows)])
        lines.extend([run_notes(runs), ''])
        lines.extend(f'- {note}' for note in failure_notes(runs))
        lines.append('')
    return '\n'.join(lines)


def markdown_table(first_column, rows):
    return ['| ' + ' | '.join((first_column, *HEADERS[1:])) + ' |',
            '| --- |' + ' ---: |' * (len(HEADERS) - 1),
            *('| ' + ' | '.join(value.replace('|', r'\|').replace('\n', '<br>') for value in row) + ' |'
              for row in rows), '']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', type=Path, nargs='+', help='Suite report files or run directories')
    parser.add_argument('--output', type=Path, required=True, help='Directory for the comparison outputs')
    parser.add_argument('--docx', action='store_true', help='Include a Word report (requires python-docx)')
    args = parser.parse_args()
    try:
        runs = read_runs(args.reports)
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as error:
        parser.error(str(error))
    grouped = conditions(runs)
    if args.docx:
        try:
            from .benchmark_report_docx import write_docx
        except ModuleNotFoundError as error:
            if error.name != 'docx':
                raise
            parser.error('--docx requires python-docx in the active Python environment')
        write_docx(args.output / 'benchmark-results.docx', grouped)
    atomic_write(args.output / 'benchmark-attempts.csv', csv_text(runs).encode('utf-8-sig'))
    atomic_write(args.output / 'benchmark-results.md', markdown_text(grouped))
    print(f'Wrote {sum(len(run.trials) for run in runs)} attempts from {len(runs)} runs to {args.output}')


if __name__ == '__main__':
    main()

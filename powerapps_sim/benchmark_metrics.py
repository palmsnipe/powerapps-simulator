"""Shared case labels and timing definitions for the authoring benchmark."""
from statistics import median

CASES = {
    'create': 'Create and extend a task tracker',
    'feature': 'Add a status filter and preserve form retry',
    'switch-edit': 'Select the intended app and edit a title',
    'repair-tests': 'Repair two saved workflows through the apply gate',
    'large-list-search': 'Fix search across a large SharePoint list',
    'approval-flow': 'Fix a two-screen approval workflow',
}


def summarize_trials(trials):
    passed = sum(row['status'] == 'passed' for row in trials)
    timed = [row for row in trials if row.get('elapsed_seconds') is not None]
    wins = [row for row in timed if row['status'] == 'passed']
    steps = [row['steps'] for row in trials if row.get('steps') is not None]
    return {'attempts': len(trials), 'passed': passed, 'success_rate': passed / len(trials) if trials else None,
            'median_seconds': median(row['elapsed_seconds'] for row in timed) if timed else None,
            'median_success_seconds': median(row['elapsed_seconds'] for row in wins) if wins else None,
            'median_steps': median(steps) if steps else None,
            'rejected_steps': sum(row.get('rejected_steps', 0) for row in trials)}

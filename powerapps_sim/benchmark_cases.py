"""Fixtures and independent acceptance scenarios for operational authoring tasks."""
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from .workflows import summarize

EXAMPLES = Path(__file__).with_name('examples')
REQUESTS = {
    'large-list-search': (
        'Open asset-inventory. Staff miss records when searching the asset list. With a nonblank query, '
        'show every asset whose title starts with the trimmed query, case-insensitively, even when '
        'the record is beyond the default 500-row cutoff. Sort matches by Title ascending. With the search '
        'empty or whitespace-only, keep the original inventory view of the first 500 items in list order. '
        'Keep the existing search and gallery controls and their 400 px layout. Leave the 500-row setting, '
        'schema, and seed data intact.'
    ),
    'approval-flow': (
        'Open request-approvals. A reviewer must enter a nonblank approval note. Keep Approve disabled '
        'when the note is blank or whitespace-only. On success, save the trimmed note in ReviewNote and '
        'set only the selected request to Approved, then return to the inbox. If the write fails, remain '
        'on Review, keep the typed note, and show a visible message in ReviewError. The reviewer must '
        'be able to retry without retyping. Cancel must return without writing. When a review is opened '
        'again, the note and error should start clear. Keep the existing control names and pending inbox.'
    ),
}


@dataclass(frozen=True)
class AuthoringCase:
    request: str
    fixture: Callable[[], dict]
    scenarios: Callable[[], dict]

    def score(self, workflows, base):
        checks, details = {}, {}
        for name, (flow, expected_writes) in self.scenarios().items():
            report = workflows.run(flow, expected_revision=base)
            writes = [write for step in report['steps'] for write in step['writes']]
            checks[name] = report['status'] == 'passed' and writes == expected_writes
            details[name] = {**summarize(report), 'step_writes': writes, 'expected_writes': expected_writes}
        return checks, details


def scenario(name, *steps):
    return {'format_version': 1, 'name': name, 'steps': list(steps)}


def assertion(formula, expect):
    return {'op': 'assert', 'formula': formula, 'expect': expect}


def event(path, action, **fields):
    return {'op': 'event', 'path': path, 'event': action, **fields}


def inventory_rows():
    examples = {20: 'Spare Boreal Cable', 502: 'Boreal Tripod', 517: 'Boreal Adapter', 620: 'Tundra Monitor'}
    return [{'ID': i, 'Title': examples.get(i, f'Warehouse asset {i:03d}')} for i in range(1, 621)]


def fixture_inputs(case):
    health = {'op': 'diagnostics', 'expect': 0}
    identifier = {'type': 'integer', 'x-ms-permission': 'read-only'}
    title = {'type': 'string'}
    if case == 'large-list-search':
        name, heading, source = 'asset-inventory', 'Asset inventory', 'Inventory'
        list_name = 'Assets'
        fields = {'ID': identifier, 'Title': title}
        rows = inventory_rows()
        baseline = scenario('Default inventory opens with 500 rows', health,
                            assertion('CountRows(AssetGallery.Items)', 500),
                            assertion('First(AssetGallery.Items).ID', 1))
    else:
        name, heading, source = 'request-approvals', 'Request approvals', 'Approvals'
        list_name = 'Requests'
        fields = {'ID': identifier, 'Title': title, 'Status': {'type': 'string'}, 'ReviewNote': {'type': 'string'}}
        rows = [{'ID': i, 'Title': title, 'Status': status, 'ReviewNote': note} for i, title, status, note in (
            (1, 'Replace conference display', 'Pending', ''),
            (2, 'Order warehouse scanner', 'Pending', ''),
            (3, 'Renew design license', 'Approved', 'Budget confirmed'),
        )]
        baseline = scenario('Inbox lists pending requests and opens their details', health,
                            assertion('CountRows(PendingRequests.Items)', 2),
                            open_request(0), assertion('ReviewTitle.Text', 'Replace conference display'),
                            event('Review/CancelReview', 'OnSelect'), assertion('App.ActiveScreen.Name', 'Inbox'))
    text = (EXAMPLES / f'benchmark-{source.lower()}.pa.yaml').read_text(encoding='utf-8')
    return {'name': name, 'title': heading, 'sources': {f'Src/{source}.pa.yaml': text},
            'lists': {list_name: {'fields': fields, 'required': ['Title']}},
            'records': {list_name: rows}, 'workflows': {'startup.workflow.json': baseline}}


def inventory_scenarios():
    def search(value):
        return event('Inventory/AssetSearch', 'OnChange', value=value)

    def narrow(flow):
        return {**flow, 'viewport': {'width': 400, 'height': 900}}

    match = scenario('Trimmed prefix matches past row 500 in title order',
        search('  bOREAl  '), assertion('CountRows(AssetGallery.Items)', 2),
        assertion('First(AssetGallery.Items).ID', 517),
        assertion('Last(AssetGallery.Items).ID', 502),
        assertion('AssetSearch.X + AssetSearch.Width <= App.Width', True),
        assertion('AssetGallery.X + AssetGallery.Width <= App.Width', True),
        {'op': 'diagnostics', 'expect': 0})
    clear = scenario('A different query, empty state, and clear',
        search('TUNDRA'), assertion('CountRows(AssetGallery.Items)', 1),
        assertion('First(AssetGallery.Items).ID', 620),
        search('Not stocked'), assertion('CountRows(AssetGallery.Items)', 0),
        search('   '), assertion('CountRows(AssetGallery.Items)', 500),
        assertion('First(AssetGallery.Items).ID', 1),
        assertion('Last(AssetGallery.Items).ID', 500))
    return {'prefix_search_beyond_limit': (narrow(match), []), 'search_clear_and_empty_state': (clear, [])}


def open_request(index):
    return {'op': 'event', 'target': f'Index(PendingRequests.AllItems, {index + 1}).OpenRequest', 'event': 'OnSelect'}


def approval_scenarios():
    def note(value):
        return event('Review/ApprovalNote', 'OnChange', value=value)

    blocked = event('Review/ApproveRequest', 'OnSelect', expect_blocked=True)
    approve = event('Review/ApproveRequest', 'OnSelect')
    visible_error = 'ReviewError.Visible && !IsBlank(Trim(ReviewError.Text))'
    pending = assertion('LookUp(Requests, ID = 2, Status)', 'Pending')
    blank_cancel = scenario('Reject whitespace and cancel without a write',
        open_request(1), blocked, note('   '), blocked, note('Discard this'),
        event('Review/CancelReview', 'OnSelect'), assertion('App.ActiveScreen.Name', 'Inbox'), pending,
        open_request(1), assertion('IsBlank(ApprovalNote.Text)', True), assertion('ReviewError.Visible', False))
    retry = scenario('Failed write retains the selected request and note for retry',
        open_request(1), assertion('ReviewTitle.Text', 'Order warehouse scanner'), note('  Approved for Q4  '),
        {'op': 'failure', 'list': 'Requests', 'mode': 'write'}, approve,
        assertion('App.ActiveScreen.Name', 'Review'), assertion('ApprovalNote.Text', '  Approved for Q4  '),
        assertion(visible_error, True), pending,
        {'op': 'failure', 'list': 'Requests', 'mode': None}, approve,
        assertion('App.ActiveScreen.Name', 'Inbox'), assertion('CountRows(PendingRequests.Items)', 1),
        assertion('LookUp(Requests, ID = 2, Status)', 'Approved'),
        assertion('LookUp(Requests, ID = 2, ReviewNote)', 'Approved for Q4'),
        open_request(0), assertion('IsBlank(ApprovalNote.Text)', True), assertion('ReviewError.Visible', False),
        {'op': 'diagnostics', 'expect': 0})
    return {'blank_and_cancel_protect_data': (blank_cancel, []),
            'retry_saves_only_selected_request': ({**retry, 'viewport': {'width': 400, 'height': 900}},
                [{'list': 'Requests', 'id': 2, 'operation': 'update'}])}


OPERATIONAL_CASES = {
    'large-list-search': AuthoringCase(REQUESTS['large-list-search'], partial(fixture_inputs, 'large-list-search'),
                                      inventory_scenarios),
    'approval-flow': AuthoringCase(REQUESTS['approval-flow'], partial(fixture_inputs, 'approval-flow'),
                                   approval_scenarios),
}

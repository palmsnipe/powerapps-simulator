"""Create through real attached MCP, then interact with the new app in a browser."""
import asyncio
import json
from pathlib import Path
import re
import sys
import threading
from zipfile import ZipFile

import pytest
from werkzeug.serving import make_server

from powerapps_sim.fixtures import forms_project
from powerapps_sim.mcp_server import HTTPBackend
from powerapps_sim.store import ListStore
from powerapps_sim.web import create_app


SOURCE = '''App:
  Properties:
    StartScreen: =Main
Screens:
  Main:
    Properties:
      Fill: =Color.White
    Children:
      - Heading:
          Control: ModernText@1.0.0
          Properties:
            Text: ="Created through MCP"
            X: =24
            Y: =24
            Width: =Parent.Width - 48
            Height: =40
      - Count:
          Control: ModernText@1.0.0
          Properties:
            Text: =Text(CountRows(Projects)) & " projects"
            X: =24
            Y: =80
            Width: =Parent.Width - 48
            Height: =32
      - AddProject:
          Control: ModernButton@1.0.0
          Properties:
            Text: ="Add project"
            OnSelect: =Patch(Projects, Defaults(Projects), {Title:"Browser example"})
            X: =24
            Y: =128
            Width: =160
            Height: =40
'''


def test_attached_mcp_creation_is_visible_and_editable_in_browser(tmp_path):
    sdk = pytest.importorskip('mcp')
    playwright = pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import expect
    from mcp.client.stdio import StdioServerParameters
    original = forms_project(tmp_path / 'original')
    original_source = dict(original.documents)
    app = create_app(tmp_path, original.root)
    workspace = app.extensions['workspace']
    original_rows = workspace.runtime.store.rows('Drafts')
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        async def create():
            params = StdioServerParameters(command=sys.executable, args=['-m', 'powerapps_sim.mcp_server',
                '--url', url, '--expect-project', str(original.root)])
            async with sdk.Client(params, raise_exceptions=True) as client:
                async def call(operation, **arguments):
                    result = await client.call_tool(operation, arguments)
                    assert not result.is_error, result.content
                    return result.structured_content
                base = await call('describe_project')
                created = await call('create_project', name='from-scratch', title='MCP scratch app',
                    expected_revision=base['revision'], sources={'Src/Main.pa.yaml': SOURCE},
                    lists={'Projects': {'fields': {'ID': {'type': 'integer'}, 'Title': {'type': 'string'}}, 'required': ['Title']}},
                    records={'Projects': [{'ID': 1, 'Title': 'Seeded example'}]},
                    workflows={'add.workflow.json': {'format_version': 1, 'name': 'Add a local project', 'steps': [
                        {'op': 'event', 'path': 'Main/AddProject', 'event': 'OnSelect'},
                        {'op': 'assert', 'formula': 'CountRows(Projects)', 'expect': 2}, {'op': 'diagnostics', 'expect': 0}]},
                        'repair.workflow.json': {'format_version': 1, 'name': 'Check the initial count', 'steps': [
                            {'op': 'assert', 'formula': 'CountRows(Projects)', 'expect': 99}]}},
                    viewport={'width': 1000, 'height': 740})
                assert not created['runtime_started']
                tested = await call('run_workflows', expected_revision=created['revision'],
                                    workflows=[{'scenario_file': 'add.workflow.json'}])
                assert tested['status'] == 'passed'
                broken = await call('stage_control_edits', expected_revision=created['revision'], edits=[
                    {'op': 'set_property', 'path': 'Main/AddProject', 'property': 'OnSelect', 'value': '=Blank()'},
                ])
                blocked = await client.call_tool('apply_change', {
                    'change_id': broken['id'], 'expected_revision': created['revision'],
                })
                assert blocked.is_error and 'add.workflow.json' in blocked.content[0].text
                assert (await call('read_list', name='Projects'))['total'] == 1
                assert (await call('restart_preview', expected_revision=created['revision']))['started']
        asyncio.run(create())
        with playwright.sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except playwright.Error as error:
                pytest.skip(f'Install Chromium with playwright install chromium: {error}')
            try:
                page = browser.new_page(viewport={'width': 1600, 'height': 1100})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(url)
                expect(page.locator('#project-title')).to_have_text('MCP scratch app')
                page.get_by_role('button', name='Changes', exact=True).click()
                page.locator('.change-row').filter(has_text='AI control edits').get_by_role(
                    'button', name='Review change').click()
                page.get_by_role('button', name='Check candidate').click()
                expect(page.locator('#change-check-result')).to_contain_text('First failure: add.workflow.json · Step 2')
                expect(page.locator('#change-check-result')).to_contain_text('Expected 2')
                expect(page.locator('#change-check-result')).to_contain_text('Actual 1')
                page.get_by_role('button', name='Close', exact=True).click()
                page.get_by_role('button', name='Workflows', exact=True).click()
                page.get_by_label('Workflow scenario').select_option('repair.workflow.json')
                page.get_by_role('button', name='Validate saved suite').click()
                expect(page.locator('#workflow-report h2')).to_have_text('1 passed · 1 failed')
                editor = page.get_by_label('Scenario · JSON')
                definition = json.loads(editor.input_value())
                definition['steps'][0]['expect'] = 1
                editor.fill(json.dumps(definition))
                page.get_by_role('button', name='Stage saved workflow').click()
                expect(page.locator('#change-diff')).to_contain_text('tests/repair.workflow.json')
                page.get_by_text('Sample a Power Fx property', exact=True).click()
                page.get_by_label('Control path', exact=True).fill('Main/Count')
                page.get_by_label('Property', exact=True).fill('Text')
                page.get_by_role('button', name='Check candidate').click()
                expect(page.locator('#change-check-result')).to_contain_text('Saved tests: 2/2 passed')
                expect(page.locator('#change-check-result')).to_contain_text('Main/Count · Text · Text')
                expect(page.locator('#change-check-result')).to_contain_text('Sample "1 projects"')
                page.get_by_role('button', name='Close', exact=True).click()
                page.get_by_role('button', name='Validate saved suite').click()
                expect(page.locator('#workflow-report h2')).to_have_text('2 passed · 0 failed')
                page.get_by_role('button', name='Changes', exact=True).click()
                page.locator('.change-row').filter(has_text='Edit saved workflow repair.workflow.json').get_by_role(
                    'button', name='Review change').click()
                page.get_by_role('button', name='Apply reviewed change').click()
                expect(page.locator('#change-dialog')).to_be_hidden()
                page.get_by_role('button', name='Workflows', exact=True).click()
                page.get_by_label('Workflow source').select_option('')
                page.get_by_role('button', name='Validate saved suite').click()
                expect(page.locator('#workflow-report h2')).to_have_text('2 passed · 0 failed')
                page.get_by_role('button', name='Editor & preview', exact=True).click()
                count = page.locator('[data-control=Count]')
                count.get_by_text('1 projects', exact=True).wait_for()
                page.get_by_role('button', name='Add project', exact=True).click()
                count.get_by_text('2 projects', exact=True).wait_for()
                assert workspace.runtime.store.rows('Projects')[1]['Title'] == 'Browser example'
                artifacts = Path('test-results/create-project')
                artifacts.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(artifacts / 'desktop.png'), full_page=True)
                page.get_by_label('Preview width', exact=True).fill('400')
                page.get_by_label('Preview height', exact=True).fill('900')
                page.get_by_role('button', name='Resize', exact=True).click()
                page.wait_for_function('state.viewport.width === 400')
                tree = page.evaluate('state.tree')
                for control in tree['children']:
                    props = control['props']
                    assert 0 <= props['X'] and props['X'] + props['Width'] <= 400
                    assert 0 <= props['Y'] and props['Y'] + props['Height'] <= 900
                page.screenshot(path=str(artifacts / 'narrow.png'), full_page=True)
                assert not errors and not workspace.runtime.diagnostics
            finally:
                browser.close()
        assert original.documents == original_source
        store = ListStore(original.root / 'data.sqlite', schema_root=original.root / 'lists')
        try:
            assert store.rows('Drafts') == original_rows
        finally:
            store.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        workspace.runtime.close()


def test_browser_tracks_shared_mcp_session_and_transfers_bundle(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import expect

    original = forms_project(tmp_path / 'original')
    app = create_app(tmp_path, original.root)
    workspace = app.extensions['workspace']
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    attached = HTTPBackend(url)
    observer = HTTPBackend(url)
    try:
        with playwright.sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except playwright.Error as error:
                pytest.skip(f'Install Chromium with playwright install chromium: {error}')
            page = browser.new_page(viewport={'width': 1600, 'height': 1100})
            page.goto(url)
            session = page.locator('#session-status')
            attached.track_presence()
            observer.track_presence()
            expect(session).to_contain_text('2 MCP connected')
            base = attached.call('describe_project')
            created = attached.call('create_project', name='shared', title='Shared project',
                expected_revision=base['revision'], sources={'Src/Main.pa.yaml': SOURCE},
                lists={'Projects': {'fields': {'ID': {'type': 'integer'}, 'Title': {'type': 'string'}}}},
                records={'Projects': [{'ID': 5, 'Title': 'Portable record'}]})
            expect(page.locator('#project-title')).to_have_text('Shared project')
            expect(session).to_contain_text('shared · ' + created['revision'][:8])
            expect(session).to_contain_text('1 awaiting MCP rebind')
            expect(page.get_by_role('button', name='Start preview')).to_be_visible()
            change = attached.call('stage_control_edits', expected_revision=created['revision'], edits=[
                {'op': 'set_property', 'path': 'Main/Heading', 'property': 'Text', 'value': '="New saved heading"'}])
            applied = attached.call('apply_change', expected_revision=created['revision'], change_id=change['id'])
            expect(session).to_contain_text(applied['after_revision'][:8])
            expect(page.get_by_label('YAML or Power Fx source')).to_have_value(re.compile('New saved heading'))
            attached.call('restart_preview', expected_revision=applied['after_revision'])
            expect(session).to_contain_text('Preview running')
            expect(page.get_by_text('New saved heading', exact=True)).to_be_visible()

            editor = page.get_by_label('YAML or Power Fx source')
            editor.fill('# Browser draft remains')
            attached.call('open_project', project_id='original')
            expect(page.get_by_role('button', name='Sync session')).to_be_visible()
            expect(editor).to_have_value('# Browser draft remains')
            page.get_by_role('button', name='Export source', exact=True).click()
            expect(page.locator('#status')).to_contain_text('Sync the shared session again')
            page.get_by_role('button', name='Apply source').click()
            expect(page.locator('#source-state')).to_have_text('Conflict · edits kept')
            expect(editor).to_have_value('# Browser draft remains')
            page.once('dialog', lambda dialog: dialog.accept())
            page.get_by_role('button', name='Sync session').click()
            expect(page.locator('#project-title')).to_have_text(original.config['title'])
            expect(page.get_by_role('button', name='Sync session')).to_be_hidden()

            attached.call('open_project', project_id='shared')
            expect(page.locator('#project-title')).to_have_text('Shared project')
            with page.expect_download() as source_download:
                page.get_by_role('button', name='Export source', exact=True).click()
            with ZipFile(source_download.value.path()) as source_zip:
                assert source_zip.namelist() == ['Src/Main.pa.yaml']
                assert b'New saved heading' in source_zip.read('Src/Main.pa.yaml')
            page.get_by_role('button', name='Export project bundle').click()
            include_records = page.get_by_label('Include local list records')
            expect(include_records).not_to_be_checked()
            include_records.check()
            with page.expect_download() as download:
                page.get_by_role('button', name='Download bundle').click()
            path = tmp_path / 'transfer.pasim'
            download.value.save_as(path)
            page.locator('#file-import').set_input_files(path)
            expect(page.locator('#status')).to_contain_text('Use Start preview to run startup')
            expect(page.get_by_role('button', name='Start preview')).to_be_visible()
            assert workspace.project.root not in (original.root, tmp_path / 'shared')
            assert workspace.runtime.store.rows('Projects')[0]['Title'] == 'Portable record'
            expect(session).to_contain_text('2 awaiting MCP rebind')
            browser.close()
    finally:
        observer.close()
        attached.close()
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        workspace.runtime.close()

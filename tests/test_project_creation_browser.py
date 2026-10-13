"""Create through real attached MCP, then interact with the new app in a browser."""
import asyncio
from pathlib import Path
import sys
import threading

import pytest
from werkzeug.serving import make_server

from powerapps_sim.fixtures import forms_project
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
                        {'op': 'assert', 'formula': 'CountRows(Projects)', 'expect': 2}, {'op': 'diagnostics', 'expect': 0}]}},
                    viewport={'width': 1000, 'height': 740})
                assert not created['runtime_started']
                tested = await call('run_workflows', expected_revision=created['revision'],
                                    workflows=[{'scenario_file': 'add.workflow.json'}])
                assert tested['status'] == 'passed'
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

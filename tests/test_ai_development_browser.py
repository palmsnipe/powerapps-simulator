"""Browser proof for the local authoring benchmark, including narrow layout."""
from pathlib import Path
import threading

import pytest
from werkzeug.serving import make_server

from powerapps_sim.authoring import revision
from powerapps_sim.fixtures import ai_development_project
from powerapps_sim.web import create_app


def test_filtered_edit_failure_retry_and_responsive_layout(tmp_path):
    pytest.importorskip('playwright.sync_api')
    project = ai_development_project(tmp_path / 'app')
    app = create_app(tmp_path, project.root)
    w = app.extensions['workspace']
    task = project.read_json('benchmark.task.json', {})
    def call(operation, **args):
        return w.ai.call(operation, args, expected_project=str(project.root))
    change = call('stage_control_edits', expected_revision=revision(project.root), edits=task['reference_edits'], strict=True)
    applied = call('apply_change', change_id=change['id'], expected_revision=change['base_revision'])
    call('restart_preview', expected_revision=applied['after_revision'])
    exercise_saved_app(app, Path('test-results/ai-development'))


def exercise_saved_app(app, artifacts):
    """Exercise any saved authored app, without supplying or staging reference edits."""
    playwright = pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import expect
    w = app.extensions['workspace']
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except playwright.Error as error:
                pytest.skip(f'Install Chromium with playwright install chromium: {error}')
            try:
                page = browser.new_page(viewport={'width': 1600, 'height': 1100})
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.locator('[data-control=ProjectCount]').get_by_text('3 projects', exact=True).wait_for()
                dropdown = page.locator('[data-control=StatusFilter]').get_by_role('combobox')
                assert dropdown.get_attribute('aria-label')
                dropdown.click()
                page.get_by_role('option', name='Active', exact=True).click()
                page.locator('[data-control=ProjectCount]').get_by_text('1 projects', exact=True).wait_for()
                page.get_by_role('button', name='Edit Park survey', exact=True).click()
                title = page.get_by_role('textbox', name='Project title', exact=True)
                budget = page.get_by_role('spinbutton', name='Project budget', exact=True)
                expect(title).to_have_value('Park survey')
                title.fill('Park survey browser edit')
                title.press('Tab')
                budget.fill('350')
                budget.press('Tab')
                with w.lock:
                    w.runtime.store.failures['Projects'] = 'write'
                page.get_by_role('button', name='Save project', exact=True).click()
                page.wait_for_function('state.globals.selectedId===2 && state.tree.children.find(c=>c.name==="ProjectForm").props.Error.length>0')
                assert title.input_value() == 'Park survey browser edit' and budget.input_value() == '350'
                assert w.runtime.store.rows('Projects')[1]['Title'] == 'Park survey'
                assert w.runtime.fx.evaluate('!IsBlank(ProjectForm.Error)')
                with w.lock:
                    w.runtime.store.failures.clear()
                page.get_by_role('button', name='Save project', exact=True).click()
                page.get_by_role('button', name='Edit Park survey browser edit', exact=True).wait_for()
                assert w.runtime.store.rows('Projects')[1]['Amount'] == 350
                assert not w.runtime.fx.evaluate('ProjectForm.Unsaved')
                title.fill('')
                title.press('Tab')
                expect(page.get_by_role('button', name='Save project', exact=True)).to_be_disabled()
                title.fill('Park survey browser edit')
                title.press('Tab')
                expect(page.get_by_role('button', name='Save project', exact=True)).to_be_enabled()
                artifacts.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(artifacts / 'desktop.png'), full_page=True)
                page.get_by_label('Preview width', exact=True).fill('400')
                page.get_by_label('Preview height', exact=True).fill('900')
                page.get_by_role('button', name='Resize', exact=True).click()
                page.wait_for_function('state.viewport.width===400')
                # Check logical geometry; the editor scales the preview to fit.
                tree = page.evaluate('state.tree')
                nodes = {node['name']: node for node in tree['children']}
                for name in ('StatusFilter', 'ProjectGallery', 'ProjectForm', 'SaveProject', 'SaveFeedback'):
                    props = nodes[name]['props']
                    assert props['X'] >= 0 and props['X'] + props['Width'] <= 400
                    assert props['Y'] >= 0 and props['Y'] + props['Height'] <= 900
                gallery, form = nodes['ProjectGallery']['props'], nodes['ProjectForm']['props']
                assert form['Y'] >= gallery['Y'] + gallery['Height']
                assert title.input_value() == 'Park survey browser edit'
                page.screenshot(path=str(artifacts / 'narrow.png'), full_page=True)
                assert not errors and not w.runtime.diagnostics
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        w.runtime.close()

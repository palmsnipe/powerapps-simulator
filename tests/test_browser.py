"""Browser interactions are optional when development browsers are unavailable."""
import threading
from pathlib import Path
import os
import re

import pytest
from werkzeug.serving import make_server


@pytest.fixture
def page(app):
    playwright = pytest.importorskip('playwright.sync_api')
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except playwright.Error as error:
                pytest.skip(f'Install development Chromium with playwright install chromium: {error}')
            try:
                page = browser.new_page(viewport={'width':1600,'height':1000})
                page.errors = []
                page.on('pageerror', lambda error: page.errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.wait_for_selector('[data-control="ProjectGallery"]')
                yield page
                assert page.errors == []
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def assert_inspected_record(page, name, fields):
    record = page.locator(f'#inspector [data-live-value="{name}"]')
    record.locator('summary').first.click()
    for field, value in fields.items():
        row = record.locator('.record-values tr').filter(
            has=page.get_by_role('rowheader', name=field, exact=True))
        row.locator('td code').get_by_text(value, exact=True).wait_for()


def test_filter_translation_and_gallery_selection(page):
    page.get_by_role('textbox', name='Search projects', exact=True).fill('Water')
    page.get_by_role('textbox', name='Search projects', exact=True).press('Tab')
    page.wait_for_function("document.querySelector('[data-control=Total]').textContent.includes('1 projects')")
    assert page.locator('[data-control=ProjectGallery] .fx-row').count() == 1
    page.get_by_role('button', name='Français', exact=True).click()
    page.get_by_text('Espace projets', exact=True).wait_for()
    page.get_by_role('button', name='Edit Water assessment', exact=True).click()
    page.get_by_role('textbox', name='Project name', exact=True).wait_for()
    assert page.get_by_role('textbox', name='Project name', exact=True).input_value() == 'Water assessment'


def test_browser_form_creates_and_persists_record(page, runtime):
    page.get_by_role('button', name='New project', exact=True).click()
    page.get_by_role('textbox', name='Project name', exact=True).fill('Browser draft')
    page.get_by_role('spinbutton', name='Requested amount').fill('345')
    page.get_by_role('button', name='Save project', exact=True).click()
    page.get_by_text('Browser draft', exact=True).wait_for()
    assert len(runtime.store.rows('Projects')) == 4
    assert any(row['Title'] == 'Browser draft' and row['Amount'] == 345 for row in runtime.store.rows('Projects'))


def test_input_focus_and_caret_survive_state_refresh(page):
    textbox = page.get_by_role('textbox', name='Search projects', exact=True)
    textbox.fill('Water')
    textbox.evaluate('(e)=>e.setSelectionRange(2,2)')
    before = textbox.evaluate('(e)=>e')
    page.evaluate("async()=>{state=await api('/api/state');renderState();}")
    assert textbox.evaluate('(e)=>document.activeElement===e')
    assert textbox.input_value() == 'Water'
    assert textbox.evaluate('(e)=>e.selectionStart') == 2


def test_ai_connection_dialog_matches_current_workspace(page, app):
    w = app.extensions['workspace']
    page.get_by_role('button', name='AI tools', exact=True).click()
    page.get_by_role('heading', name='Connect an AI client').wait_for()
    import json
    config = json.loads(page.get_by_label('MCP command and arguments').input_value())
    assert config['args'][-1] == str(w.project.root)
    assert config['args'][3] == page.url.rstrip('/')
    assert config['args'][:2] == ['-m','powerapps_sim.mcp_server']
    page.get_by_role('button', name='Close', exact=True).click()
    assert not page.locator('#ai-dialog').is_visible()


def test_workflow_browser_runs_without_changing_open_preview(page, runtime):
    search = page.get_by_role('textbox', name='Search projects', exact=True)
    search.fill('Water')
    search.press('Tab')
    page.wait_for_function("document.querySelector('[data-control=Total]').textContent.includes('1 projects')")
    page.get_by_role('button', name='Workflows', exact=True).click()
    selector = page.get_by_label('Workflow scenario')
    page.wait_for_function("document.querySelector('#workflow-selector').options.length>1")
    selector.select_option(label='Translation, filtering and component navigation')
    page.get_by_role('button', name='Run isolated workflow', exact=True).click()
    page.locator('#workflow-report h2').filter(has_text='passed').wait_for()
    assert page.get_by_role('button', name='Download report').is_enabled()
    assert runtime.globals['varLanguage'] == 'en'
    assert runtime.global_refs['Search'].state['Text'] == 'Water'
    page.get_by_text('Ordered event trace', exact=True).click()
    assert 'navigation' in page.locator('#workflow-report').inner_text()
    page.get_by_role('button', name='Editor & preview', exact=True).click()
    assert search.input_value() == 'Water'


def test_scroll_and_responsive_layout(page):
    page.locator('#viewport-width').fill('900')
    page.get_by_role('button', name='Resize', exact=True).click()
    page.wait_for_function("state.viewport.width===900")
    assert page.locator('[data-control=Page]').evaluate('(e)=>getComputedStyle(e).display') == 'flex'
    gallery = page.locator('[data-control=ProjectGallery]')
    gallery.evaluate('(e)=>{e.style.height="80px";e.scrollTop=100;}')
    assert gallery.evaluate('(e)=>e.scrollTop') > 0


def test_inspection_does_not_trigger_button_and_copies_yaml(page):
    page.locator('#inspect-toggle').check()
    page.get_by_role('button', name='New project', exact=True).click()
    page.get_by_role('button', name='Copy control YAML').wait_for()
    assert page.locator('#screen-label').inner_text() == 'Home'
    assert 'NewProject' in page.locator('#selection-label').inner_text()
    assert 'NewForm(ProjectForm)' in page.locator('#inspector').inner_text()


def test_draft_error_keeps_preview(page):
    page.locator('#source-editor').fill('Screens: [broken')
    page.get_by_role('button', name='Apply source', exact=True).click()
    page.wait_for_function("document.getElementById('source-state').textContent==='Draft saved'")
    assert page.locator('[data-control=ProjectGallery]').is_visible()
    assert page.locator('#status').get_attribute('class') == 'error'


def test_repaired_sample_admin_component_and_gallery_navigation(page, app, tmp_path):
    sample_path = os.environ.get("POWERAPPS_SAMPLE")
    if not sample_path:
        pytest.skip("Set POWERAPPS_SAMPLE to an optional local compatibility archive")
    sample = Path(sample_path)
    if not sample.is_file():
        pytest.skip("Local compatibility archive is unavailable")
    from powerapps_sim.source import Project
    from powerapps_sim.repair import apply_repair, plan_repair
    from powerapps_sim.scenarios import seed
    p = Project.import_archive(sample.read_bytes(), tmp_path / "sample")
    apply_repair(p, plan_repair(p))
    workspace = app.extensions["workspace"]
    workspace.open(p)
    seed(workspace.runtime.store)
    workspace.runtime.restart()
    year = workspace.runtime.store.rows("Business Planning Fiscal Years")[0]["Title"]
    page.reload()
    page.get_by_role("button", name="Admin Setup", exact=True).click()
    assert page.get_by_role("button", name="Fiscal Year", exact=True).evaluate(
        "(el)=>getComputedStyle(el).color") == "rgb(36, 36, 36)"
    page.get_by_role("button", name="Fiscal Year", exact=True).click()
    page.get_by_role("button", name="Edit " + year, exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=DataCardValue1_1] input').value !== ''")
    assert page.get_by_role("textbox", name="Title", exact=True).input_value() == year
    page.get_by_role("button", name="User access", exact=True).click()
    page.get_by_role("button", name=re.compile(r"^Manage assignment: admin@example\.test")).click()
    page.wait_for_function("document.querySelector('[data-control=cmbAdminRoleUser] [role=combobox]').value === 'Demo Administrator'")
    assert workspace.runtime.globals["varAdminRoleRecord"]["ID"] == 1
    assert page.get_by_role("checkbox", name="Active assignment", exact=True).is_checked()
    assert not workspace.runtime.diagnostics


def test_type_inspector_and_component_state_are_available(page):
    page.get_by_role('button', name='Power Fx types', exact=True).click()
    page.get_by_role('textbox', name='Filter Power Fx types').wait_for()
    page.get_by_role('textbox', name='Filter Power Fx types').fill('ProjectRows')
    assert 'ProjectRows' in page.locator('#inspector').inner_text()
    assert 'Table' in page.locator('#inspector').inner_text() or '[{' in page.locator('#inspector').inner_text()
    page.get_by_role('button', name='Components', exact=True).click()
    page.locator('#inspector [data-live-value]').first.wait_for()


def test_default_normalization_updates_a_focused_input(page, runtime):
    search = runtime.global_refs['Search']
    runtime.globals['seed'] = ''
    search.control.properties['Default'] = '=seed'
    search.control.properties['OnChange'] = '=Set(seed, Lower(Trim(Self.Text)))'
    runtime.invalidate()
    page.reload()
    inp = page.get_by_role('textbox', name='Search projects', exact=True)
    inp.fill('  WATER  ')
    # Commit through the real FocusOut contract, then refocus before the server
    # responds so the assertion exercises normalization of a focused input.
    def refocus_before_commit(route):
        inp.focus()
        route.continue_()
    page.route('**/api/event', refocus_before_commit, times=1)
    inp.press('Tab')
    page.wait_for_function("document.querySelector('[data-control=Search] input').value==='water'")
    assert inp.evaluate('(e)=>document.activeElement===e')
    assert runtime.globals['seed'] == 'water'


def test_gallery_preserves_healthy_rows_and_input_when_predicate_fails(page, runtime):
    gallery = runtime.global_refs['ProjectGallery']
    gallery.control.properties['Items'] = '=Filter(Projects, 1/(ID - 2) <> 0)'
    runtime.invalidate()
    page.reload()
    page.locator('[data-control=ProjectGallery] .fx-row-error').wait_for()
    assert page.locator('[data-control=ProjectGallery] .fx-row').count() == 3
    assert page.locator('[data-control=ProjectGallery] .fx-row-error').count() == 1
    assert 'division by zero' in page.locator('.fx-row-error').inner_text().lower()
    page.get_by_role('textbox', name='Search projects', exact=True).fill('Still usable')
    page.get_by_role('textbox', name='Search projects', exact=True).press('Tab')
    assert page.get_by_role('textbox', name='Search projects', exact=True).input_value() == 'Still usable'
    assert page.locator('[data-control=ProjectGallery] .fx-row').count() == 3


def test_typed_dates_component_callbacks_and_form_roundtrip(page, app, tmp_path):
    from powerapps_sim.fixtures import temporal_project
    workspace = app.extensions['workspace']
    workspace.open(temporal_project(tmp_path / 'temporal-browser'))
    runtime = workspace.runtime
    runtime.restart()
    page.reload()
    page.get_by_text('Typed dates · component and form fixture', exact=True).first.wait_for()
    page.get_by_role('button', name='Advance 2026-01-01', exact=True).click()
    page.get_by_text('Friday, January 2, 2026', exact=True).wait_for()
    assert runtime.globals['leftChanged'].kind == 'DateTime'
    assert runtime.fx.evaluate('RightDate.Day').isoformat() == '2026-07-01'
    picker = page.get_by_label('Due date', exact=True)
    picker.fill('2026-04-07'); picker.press('Tab')
    page.wait_for_function("document.querySelector('[data-control=DueInput] input').value==='2026-04-07'")
    assert runtime.global_refs['DueInput'].property('SelectedDate').kind == 'Date'
    # A read-only state refresh must preserve the focused input and its date.
    picker.focus()
    page.evaluate("async()=>{state=await api('/api/state');renderState();}")
    assert picker.evaluate('(e)=>document.activeElement===e')
    assert picker.input_value() == '2026-04-07'
    page.get_by_role('button', name='Save date', exact=True).click()
    page.get_by_text('Tuesday, April 7, 2026', exact=True).wait_for()
    assert runtime.global_refs['DateForm'].property('LastSubmit')['Due date'].kind == 'Date'
    assert runtime.store.rows('Events')[0]['Due date'] == '2026-04-07'
    page.get_by_role('button', name='Simulation settings', exact=True).click()
    page.locator('#date-numeric-mode').select_option('powerfx-days')
    page.get_by_role('button', name='Save settings', exact=True).click()
    page.wait_for_function("!document.querySelector('#scenario-dialog').open")
    assert runtime.environment['date_numeric_mode'] == 'powerfx-days'
    assert not runtime.diagnostics


def test_decimal_component_form_precision_and_host_settings(page, app, tmp_path):
    from decimal import Decimal
    from powerapps_sim.fixtures import numeric_project
    workspace = app.extensions['workspace']
    workspace.open(numeric_project(tmp_path / 'numbers-browser'))
    runtime = workspace.runtime
    runtime.restart(); page.reload()
    page.get_by_text('0.1 + 0.2 = 0.3 (exact)', exact=True).wait_for()
    page.get_by_role('button', name='Add to 0.1', exact=True).click()
    page.get_by_role('button', name='Add to 0.1', exact=True).click()
    page.get_by_text('Total 0.3', exact=True).wait_for()
    assert runtime.globals['leftChanged'] == Decimal('.3')
    assert runtime.fx.evaluate('RightMoney.Total') == Decimal('.2')
    inp = page.get_by_role('textbox', name='Exact amount', exact=True)
    precise = '9007199254740993.25'
    inp.fill(precise); inp.dispatch_event('change')
    page.wait_for_function("state.screen==='Numbers' && state.diagnostics.length===0")
    inp.evaluate('(e)=>e.setSelectionRange(5,5)')
    page.evaluate("async()=>{state=await api('/api/state');renderState();}")
    assert inp.evaluate('(e)=>document.activeElement===e')
    assert inp.input_value() == precise and inp.evaluate('(e)=>e.selectionStart') == 5
    page.get_by_role('button', name='Save amount', exact=True).click()
    page.get_by_text('Saved exactly: ' + precise, exact=True).wait_for()
    assert runtime.store.rows('Ledger')[0]['Amount'] == {'$decimal':precise}
    assert runtime.global_refs['AmountForm'].property('LastSubmit')['Amount'] == Decimal(precise)
    source = dict(runtime.project.documents)
    for mode, caption in [('float','Float rounding differs from 0.3'), ('decimal','0.1 + 0.2 = 0.3 (exact)')]:
        page.get_by_role('button', name='Simulation settings', exact=True).click()
        page.locator('#number-mode').select_option(mode)
        page.get_by_role('button', name='Save settings', exact=True).click()
        page.wait_for_function("!document.querySelector('#scenario-dialog').open")
        with page.expect_response('**/api/restart'):
            page.locator('#restart-button').click()
        page.get_by_text(caption, exact=True).wait_for()
        runtime = workspace.runtime
        assert runtime.environment['number_mode'] == mode
    assert runtime.project.documents == source
    assert not runtime.diagnostics


def test_shaped_component_galleries_selection_filter_and_writes(page, app, tmp_path):
    from powerapps_sim.fixtures import tables_project
    workspace = app.extensions['workspace']
    workspace.open(tables_project(tmp_path / 'tables-browser'))
    runtime = workspace.runtime
    runtime.restart(); page.reload()
    left = page.locator('[data-control=LeftQueue]')
    right = page.locator('[data-control=RightQueue]')
    def titles(panel):
        return panel.locator('[data-control=ProjectButton] button').all_text_contents()
    page.get_by_text('Table shaping · queues and components', exact=True).first.wait_for()
    left.get_by_role('button', name='Select Fictional wetland study', exact=True).wait_for()
    assert titles(left)[0] == 'Fictional wetland study · Review · 400'
    assert titles(right)[0] == 'Fictional river survey · Draft · 200'
    left.get_by_role('button', name='Select Fictional wetland study', exact=True).click()
    page.get_by_text('Selected Fictional wetland study · preview amount 400', exact=True).wait_for()
    page.get_by_role('button', name='Order left draft first', exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=LeftQueue] [data-control=ProjectButton] button').textContent.startsWith('Fictional river')")
    assert titles(right)[0].startswith('Fictional river')
    page.get_by_role('button', name='Increase selected amount', exact=True).click()
    left.get_by_role('button', name='Select Fictional wetland study', exact=True).get_by_text('Fictional wetland study · Review · 420', exact=True).wait_for()
    assert runtime.store.rows('Drafts')[1]['Amount'] == 210
    assert runtime.globals['pickedProject']['Preview amount'] == 420
    search = page.get_by_role('textbox', name='Search left queue', exact=True)
    search.fill('river'); search.dispatch_event('change')
    page.wait_for_function("document.querySelectorAll('[data-control=LeftQueue] [data-control=ProjectButton]').length===1")
    assert len(titles(right)) == 4
    search.evaluate('(e)=>e.setSelectionRange(2,2)')
    page.evaluate("async()=>{state=await api('/api/state');renderState();}")
    assert search.evaluate('(e)=>document.activeElement===e')
    assert search.input_value() == 'river' and search.evaluate('(e)=>e.selectionStart') == 2
    assert not runtime.diagnostics


def test_component_scalar_table_outputs_and_rounding_host_profile(page, app, tmp_path):
    from powerapps_sim.fixtures import tables_project
    workspace = app.extensions['workspace']
    workspace.open(tables_project(tmp_path/'scalar-table-browser'))
    runtime = workspace.runtime
    runtime.restart();page.reload()
    left = page.locator('[data-control=LeftQueue] [data-control=MetricsCaption]')
    right = page.locator('[data-control=RightQueue] [data-control=MetricsCaption]')
    left.wait_for()
    page.wait_for_function("document.querySelector('[data-control=LeftQueue] [data-control=MetricsCaption]').textContent.includes('33.3 · 67 · 100 · 133')")
    assert 'Lower: fictional wetland study · length 23' in left.inner_text()
    assert 'Rounded: 33.33 · 66.67 · 100 · 133.33' in right.inner_text()
    source = dict(runtime.project.documents)
    page.get_by_role('button',name='Simulation settings',exact=True).click()
    assert page.locator('#round-table-mode').input_value() == 'canvas-zero'
    page.locator('#round-table-mode').select_option('powerfx-errors')
    page.get_by_role('button',name='Save settings',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=LeftQueue] [data-control=MetricsCaption]').textContent.includes('33.3 · error 27 · error 27 · error 27')")
    assert 'Rounded: 33.33 · 66.67 · 100 · 133.33' in right.inner_text()
    page.get_by_role('button',name='Simulation settings',exact=True).click()
    page.locator('#round-table-mode').select_option('canvas-zero')
    page.get_by_role('button',name='Save settings',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=LeftQueue] [data-control=MetricsCaption]').textContent.includes('33.3 · 67 · 100 · 133')")
    search = page.get_by_role('textbox',name='Search left queue',exact=True)
    search.fill('river');search.dispatch_event('change')
    page.wait_for_function("document.querySelector('[data-control=LeftQueue] [data-control=MetricsCaption]').textContent.includes('fictional river survey · length 22')")
    assert 'Lower: fictional river survey · length 22' in right.inner_text()
    assert len(runtime.fx.evaluate('LeftQueue.TitleLengths')) == 1
    assert len(runtime.fx.evaluate('RightQueue.TitleLengths')) == 4
    assert runtime.project.documents == source and not runtime.diagnostics


def test_component_lifecycle_and_server_layout_match_browser(page, app, tmp_path):
    from powerapps_sim.fixtures import lifecycle_project
    workspace = app.extensions['workspace']
    workspace.open(lifecycle_project(tmp_path/'lifecycle-browser'))
    runtime = workspace.runtime
    runtime.restart(); page.reload()
    page.get_by_role('button', name='Change left seed', exact=True).wait_for()
    left = page.locator('[data-control=LeftPanel]')
    right = page.locator('[data-control=RightPanel]')
    left.get_by_role('button', name='Increase locally', exact=True).click()
    left.get_by_text(re.compile(r'^Total 11 · resets 0')).wait_for()
    right.get_by_role('button', name='Increase locally', exact=True).click()
    right.get_by_text(re.compile(r'^Total 101 · resets 0')).wait_for()
    left.get_by_role('textbox', name='Component note', exact=True).fill('edited note')
    left.get_by_role('textbox', name='Component note', exact=True).press('Tab')
    page.get_by_role('button', name='Change left seed', exact=True).click()
    left.get_by_text(re.compile(r'^Total 20 · resets 1')).wait_for()
    assert left.get_by_role('textbox', name='Component note', exact=True).input_value() == 'component note'
    assert right.get_by_text(re.compile(r'^Total 101 · resets 0')).count() == 1
    page.get_by_role('button', name='Reset left', exact=True).click()
    left.get_by_text(re.compile(r'^Total 20 · resets 2')).wait_for()
    page.get_by_role('button', name='Queue gallery row 2', exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=Trace]').textContent.includes('gallery second')")
    assert [r['Step'] for r in runtime.collections['trace']][-4:] == ['before select','after select','child second','gallery second']
    for width in [1000,460,400]:
        page.locator('#viewport-width').fill(str(width))
        page.get_by_role('button', name='Resize', exact=True).click()
        page.wait_for_function('(w)=>state.viewport.width===w', arg=width)
        for name in ['LeftPanel','RightPanel']:
            node = page.locator(f'[data-control={name}]')
            # Computed CSS pixels are independent of the preview's zoom scale.
            actual = node.evaluate('(e)=>({width:parseFloat(getComputedStyle(e).width),height:parseFloat(getComputedStyle(e).height),x:e.offsetLeft,y:e.offsetTop})')
            ref = runtime.global_refs[name]
            assert actual['width'] == pytest.approx(ref.property('Width'), abs=.03)
            assert actual['height'] == pytest.approx(ref.property('Height'), abs=.03)
            assert actual['x'] == pytest.approx(ref.property('X'), abs=1)
            assert actual['y'] == pytest.approx(ref.property('Y'), abs=1)
    page.get_by_role('button', name='Toggle spacer', exact=True).click()
    page.wait_for_function('state.globals.showSpacer===false')
    assert page.locator('[data-control=Spacer]').is_hidden()
    assert not runtime.diagnostics


def test_form_reset_pulse_pressed_keyboard_modes_and_persistence(page, app, tmp_path):
    from powerapps_sim.fixtures import forms_project
    workspace = app.extensions['workspace']
    workspace.open(forms_project(tmp_path/'forms-browser'))
    r = workspace.runtime
    page.reload()
    title = page.get_by_role('textbox', name='Draft title', exact=True)
    title.wait_for()
    title.fill('edited'); title.press('Tab')
    page.wait_for_function('state.tree.children.find(n=>n.name==="DraftForm").props.Unsaved===true')
    page.get_by_role('button', name='Pulse inputs', exact=True).click()
    page.wait_for_function('document.querySelector("[data-control=TitleInput] input").value==="Fictional bridge study"')
    title.fill('pressed edit'); title.press('Tab')
    hold = page.get_by_role('button', name='Hold to reset', exact=True)
    hold.hover(); page.mouse.down()
    page.wait_for_function('state.tree.children.find(n=>n.name==="DraftForm").props.Unsaved===false')
    assert r.global_refs['HeldReset'].property('Pressed') is True
    page.mouse.move(10, 10); page.mouse.up()  # Release outside the button.
    page.wait_for_function('state.globals.resetInputs===false')
    page.evaluate('()=>requestQueue')
    assert r.global_refs['HeldReset'].property('Pressed') is False
    title.fill('keyboard edit'); title.press('Tab')
    hold.focus(); page.keyboard.down('Space')
    page.wait_for_function('document.querySelector("[data-control=TitleInput] input").value==="Fictional bridge study"')
    page.keyboard.up('Space'); page.evaluate('()=>requestQueue')
    assert r.global_refs['HeldReset'].property('Pressed') is False
    page.get_by_role('button', name='New draft', exact=True).click()
    page.wait_for_function('document.querySelector("[data-control=TitleInput] input").value===""')
    title.fill('Browser fictional draft'); title.press('Tab')
    page.get_by_role('button', name='Save draft', exact=True).click()
    page.wait_for_function('state.globals.selectedId===3')
    assert r.global_refs['DraftForm'].property('LastSubmit')['Title'] == 'Browser fictional draft'
    page.get_by_role('button', name='View mode', exact=True).click()
    page.wait_for_function('document.querySelector("[data-control=TitleInput] input").readOnly')
    assert not title.is_disabled()
    before = len(r.collections['trace'])
    page.get_by_role('button', name='Reset form', exact=True).click()
    page.get_by_role('button', name='Save draft', exact=True).click()
    page.evaluate('()=>requestQueue')
    assert len(r.collections['trace']) == before
    assert len(r.store.rows('Drafts')) == 3
    page.get_by_role('button', name='Edit mode', exact=True).click()
    page.get_by_role('button', name='Next record', exact=True).click()
    page.wait_for_function('document.querySelector("[data-control=TitleInput] input").value==="Fictional bridge study"')
    assert not r.diagnostics


def test_nested_actions_reset_and_live_component_inspector(page,app,tmp_path):
    from powerapps_sim.fixtures import nested_project
    workspace=app.extensions['workspace'];workspace.open(nested_project(tmp_path/'nested-browser'))
    r=workspace.runtime;r.restart();page.reload()
    page.get_by_role('button',name='Add left pair',exact=True).click()
    page.get_by_text('Left · first 11 · second 112 · last 112',exact=True).wait_for()
    page.get_by_text('Right · first 1000 · second 1100 · last 0',exact=True).wait_for()
    note=page.get_by_role('textbox',name='Note Left first',exact=True)
    note.fill('pending nested note')
    page.get_by_role('button',name='Reset left pair',exact=True).click()
    page.wait_for_function("document.querySelector('[data-path=\"Nested/LeftShell/InnerA/LeafNote\"] input').value==='note Left first'")
    page.get_by_role('button',name='Change left seed',exact=True).click()
    page.get_by_text('Left · first 20 · second 120 · last 0',exact=True).wait_for()
    page.get_by_role('button',name='Components',exact=True).click()
    inspector=page.locator('#inspector')
    inspector.get_by_text('Nested/LeftShell/InnerA · variables', exact=True).first.wait_for()
    assert 'Nested/LeftShell/InnerA · variables' in inspector.inner_text()
    assert 'Nested/LeftShell/InnerB · variables' in inspector.inner_text()
    page.get_by_role('button',name='Collections',exact=True).click()
    assert 'history' in inspector.inner_text()
    assert 'Nested/LeftShell/InnerA' in page.locator('.collection-list').inner_text()
    assert r.component_state['Nested/LeftShell/InnerA']['variables']['current']==20
    assert not r.diagnostics


def test_schema_review_applies_default_and_history_undo_restores_data(page, app):
    import json
    from copy import deepcopy
    r = app.extensions['workspace'].runtime
    page.get_by_role('button', name='Local data', exact=True).click()
    page.get_by_text('Schema & choices', exact=True).click()
    schema = page.get_by_role('textbox', name='List schema JSON', exact=True)
    schema.wait_for()
    definition = deepcopy(r.store.definitions['Projects'])
    definition['fields']['Priority'] = {'type':'string','default':'Normal'}
    definition['mapping']['Priority'] = 'Priority'
    schema.fill(json.dumps(definition))
    page.get_by_role('button', name='Review schema change', exact=True).click()
    page.get_by_role('button', name='Apply reviewed change', exact=True).wait_for()
    assert '3 records checked, 3 records changed' in page.locator('#change-impact').inner_text()
    assert 'Priority' in page.locator('#change-diff').inner_text()
    assert 'Priority' not in r.store.rows('Projects')[0]
    page.get_by_role('button', name='Apply reviewed change', exact=True).click()
    page.wait_for_function('document.querySelector("#records-editor").value.includes("Priority")')
    assert r.store.rows('Projects')[0]['Priority'] == 'Normal'
    page.get_by_role('button', name='Changes', exact=True).click()
    page.get_by_role('button', name='Review change', exact=True).click()
    page.get_by_role('button', name='Undo change', exact=True).click()
    page.wait_for_function('document.querySelector("#changes-list").textContent.includes("undone")')
    assert 'Priority' not in r.store.rows('Projects')[0]


def test_browser_stale_source_keeps_editor_text_and_newer_source(page, app):
    from powerapps_sim.authoring import revision
    w = app.extensions['workspace']
    original = w.project.documents['Src/demo.pa.yaml']
    editor = page.get_by_role('textbox', name='YAML or Power Fx source', exact=True)
    editor.fill(original.replace('Project workspace', 'My pending edit'))
    w.authoring.save_source(expected_revision=revision(w.project.root), name='Src/demo.pa.yaml', text=original.replace('Project workspace', 'Other client edit'))
    page.get_by_role('button', name='Apply source', exact=True).click()
    page.wait_for_function('document.querySelector("#source-state").textContent.includes("Conflict")')
    assert 'My pending edit' in editor.input_value()
    assert 'Other client edit' in w.project.documents['Src/demo.pa.yaml']


def test_workspace_panes_resize_and_remember_visibility(page):
    page.locator('[data-pane="structure"]').click()
    page.locator('[data-pane="source"]').click()
    assert not page.locator('#structure-pane').is_visible()
    assert not page.locator('#source-pane').is_visible()
    splitter=page.get_by_role('separator',name='Resize inspector')
    old=int(splitter.get_attribute('aria-valuenow'))
    splitter.press('ArrowUp')
    assert int(splitter.get_attribute('aria-valuenow'))==old+20
    page.reload()
    page.wait_for_selector('[data-control="ProjectGallery"]')
    assert not page.locator('#source-pane').is_visible()
    page.get_by_role('button',name='Show source',exact=True).click()
    assert page.locator('#source-pane').is_visible()


def test_record_dialog_validates_and_saves_only_changed_record(page,runtime):
    from copy import deepcopy
    before=deepcopy(runtime.store.rows('Projects'))
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('button',name='Edit record 1',exact=True).click()
    page.get_by_label('Title',exact=True).fill('')
    page.get_by_role('button',name='Save record',exact=True).click()
    page.get_by_text('Title is required',exact=True).wait_for()
    assert runtime.store.rows('Projects')==before
    page.get_by_label('Title',exact=True).fill('Fictional browser edit')
    page.get_by_label('Status',exact=True).select_option(label='Submitted')
    page.get_by_role('button',name='Save record',exact=True).click()
    page.wait_for_function("document.querySelector('#status').textContent==='Record saved.'")
    rows=runtime.store.rows('Projects')
    assert rows[0]['Title']=='Fictional browser edit' and rows[0]['Status']=={'Value':'Submitted'}
    assert rows[1:]==before[1:]


def test_wide_tables_scroll_with_readable_columns(page,runtime):
    fields={'ID':{'type':'integer','x-ms-permission':'read-only'},'Title':{'type':'string'}}
    fields.update({f'Column{i}':{'type':'string'} for i in range(18)})
    runtime.store.add_list('Wide',{'fields':fields})
    runtime.store.patch('Wide',{}, {'Title':'Fictional wide row'})
    page.reload()
    page.wait_for_selector('[data-control="ProjectGallery"]')
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_label('SharePoint list').select_option(label='Wide')
    page.wait_for_function("document.querySelector('#data-table th')?.parentElement.children.length===21")
    measurements=page.locator('#data-table').evaluate('(e)=>({width:e.clientWidth,scroll:e.scrollWidth,column:e.querySelectorAll("th")[1].getBoundingClientRect().width})')
    assert measurements['scroll']>measurements['width'] and measurements['column']>=160


def test_combobox_search_component_isolation_and_choice_card(page,app,tmp_path):
    from powerapps_sim.fixtures import search_project
    workspace=app.extensions['workspace'];workspace.open(search_project(tmp_path/'search-browser'))
    r=workspace.runtime;r.restart();page.reload()
    combo=page.get_by_role('combobox',name='Search records',exact=True)
    combo.fill('beta');page.get_by_role('option',name='Beta review',exact=True).wait_for()
    assert len(r.collections['events'])==1
    page.get_by_role('option',name='Beta review',exact=True).click()
    page.get_by_text('Query: beta · selected 2 · callbacks 1',exact=True).wait_for()
    assert combo.evaluate('(e)=>document.activeElement===e')
    combo.fill('gamma');page.get_by_role('option',name='Gamma planning',exact=True).wait_for();combo.press('Enter')
    page.get_by_text('Query: gamma · selected 3 · callbacks 2',exact=True).wait_for();combo.press('Escape')
    assert combo.input_value()=='Alpha planning, Beta review, Gamma planning'
    component=page.locator('[data-path="SearchScreen/LeftSearch/Picker"] [role=combobox]')
    component.fill('beta');page.get_by_role('option',name='Beta review',exact=True).wait_for();component.press('Enter')
    page.get_by_text('Query: beta · selected 1',exact=True).wait_for()
    assert r.fx.evaluate('RightSearch.Query')==''
    form=page.get_by_role('combobox',name='Form team',exact=True)
    form.fill('south');page.get_by_role('option',name='South',exact=True).wait_for()
    assert r.fx.evaluate('ChoiceForm.Unsaved') is False
    page.get_by_role('option',name='South',exact=True).click()
    page.get_by_text('Unsaved: true ·',exact=True).wait_for()
    page.get_by_role('button',name='Save choice',exact=True).click()
    page.get_by_text('Unsaved: false ·',exact=True).wait_for()
    assert r.store.rows('Projects')[0]['Team']=={'Value':'South'}
    delayed=page.get_by_role('combobox',name='Delayed search',exact=True)
    delayed.fill('delta');page.get_by_role('option',name='Delta review',exact=True).wait_for();delayed.press('Enter')
    page.wait_for_function("document.querySelector('[data-control=Single] [role=combobox]').value==='Delta review'")
    delayed.fill('uncommitted');page.get_by_role('button',name='Reset inputs',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=Single] [role=combobox]').value===''")
    delayed.click();page.get_by_role('option',name='Alpha planning',exact=True).wait_for()
    assert r.fx.evaluate('Single.SearchText')=='' and not r.diagnostics


def test_complex_cards_components_and_record_dialog(page,app,tmp_path):
    from powerapps_sim.fixtures import complex_project
    workspace=app.extensions['workspace'];workspace.open(complex_project(tmp_path/'complex-browser'))
    r=workspace.runtime;r.restart();page.reload()
    owners=page.get_by_role('combobox',name='Project owners',exact=True)
    owners.fill('sam');page.get_by_role('option',name='Sam Example',exact=True).wait_for()
    assert r.fx.evaluate('TaskForm.Unsaved') is False
    page.get_by_role('option',name='Sam Example',exact=True).click();owners.press('Escape')
    page.get_by_role('button',name='Save task',exact=True).click()
    page.get_by_text('Edit · unsaved false · valid true · saved 1',exact=True).wait_for()
    assert len(r.store.rows('Tasks')[0]['Project Owners'])==2
    component=page.locator('[data-path="ComplexScreen/LeftPeople/Picker"] [role=combobox]')
    component.fill('sam');page.get_by_role('option',name='Sam Example',exact=True).wait_for()
    page.get_by_role('option',name='Sam Example',exact=True).click();component.press('Escape')
    page.wait_for_function("document.querySelector('[data-path=\"ComplexScreen/LeftPeople/Picker\"] [role=combobox]').value==='Alex Example, Sam Example'")
    assert len(r.globals['leftOwners'])==2 and r.fx.evaluate('First(RightLinks.Current).Id')==1
    page.set_viewport_size({'width':1280,'height':720})
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_label('SharePoint list').select_option('Tasks')
    page.get_by_role('button',name='Edit record 1',exact=True).click()
    page.get_by_role('button',name='Clear Project Tags',exact=True).click()
    page.get_by_role('button',name='Save record',exact=True).click()
    page.get_by_text('Project Tags is required',exact=True).wait_for()
    assert page.locator('#save-record').evaluate('(e)=>e.getBoundingClientRect().bottom<=innerHeight')
    assert page.get_by_role('checkbox',name='Alex Example',exact=True).is_checked()
    assert page.get_by_role('checkbox',name='Sam Example',exact=True).is_checked()
    page.get_by_role('searchbox',name='Filter Project Tags',exact=True).fill('del')
    page.get_by_role('checkbox',name='Delivery',exact=True).check()
    assert not page.get_by_role('checkbox',name='Planning',exact=True).is_visible()
    page.get_by_role('searchbox',name='Filter Project Tags',exact=True).fill('')
    page.get_by_role('checkbox',name='Planning',exact=True).check()
    page.get_by_role('checkbox',name='Fictional park survey',exact=True).check()
    page.get_by_role('button',name='Save record',exact=True).click()
    page.get_by_text('Record saved.',exact=True).wait_for()
    saved=r.store.rows('Tasks')[0]
    assert saved['Project Tags']==[{'Value':'Planning'},{'Value':'Delivery'}]
    assert len(saved['Related Projects'])==len(saved['Project Owners'])==2
    assert 'Alex Example, Sam Example' in page.locator('#data-table').inner_text()
    page.get_by_role('button',name='Edit record 1',exact=True).click()
    assert page.get_by_role('checkbox',name='Delivery',exact=True).is_checked()
    page.get_by_role('button',name='Cancel',exact=True).click()
    assert not r.diagnostics


def test_modern_text_publication_blur_readonly_and_reset(page,app,tmp_path):
    from powerapps_sim.fixtures import text_project
    workspace=app.extensions['workspace'];workspace.open(text_project(tmp_path/'text-browser'))
    r=workspace.runtime;r.restart();page.reload()
    keys=page.get_by_role('textbox',name='Keypress text',exact=True)
    keys.fill('live');page.get_by_text('Output: live',exact=True).wait_for()
    assert r.collections.get('events',[])==[]
    focus=page.get_by_role('textbox',name='FocusOut text',exact=True)
    focus.fill('pending')
    assert r.fx.evaluate('Focus.Text')=='' and len(r.collections['events'])==1
    delayed=page.get_by_role('textbox',name='Delayed text',exact=True)
    delayed.fill('delayed');delayed.press('Home');delayed.press('ArrowRight')
    page.get_by_text('Output: delayed',exact=True).wait_for()
    assert delayed.evaluate('(e)=>document.activeElement===e && e.selectionStart===1')
    assert len(r.collections['events'])==2
    form=page.get_by_role('textbox',name='Form title',exact=True)
    form.fill('Fictional browser note')
    page.get_by_text('Form output: Fictional browser note · unsaved true',exact=True).wait_for()
    page.get_by_role('button',name='Save form',exact=True).click()
    page.get_by_text('Form output: Fictional browser note · unsaved false',exact=True).wait_for()
    assert r.store.rows('Notes')[0]['Title']=='Fictional browser note'
    page.get_by_role('button',name='Toggle form view',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=FormTitle] input').readOnly")
    assert form.evaluate('(e)=>e.readOnly && !e.disabled')
    assert page.get_by_role('textbox',name='Read-only text',exact=True).evaluate('(e)=>e.readOnly && !e.disabled')
    delayed.fill('cancel pending');page.get_by_role('button',name='Reset inputs',exact=True).click()
    page.get_by_role('button',name='Change defaults',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=Delayed] input').value==='+'");page.wait_for_timeout(600)
    assert delayed.input_value()=='+' and r.fx.evaluate('Delayed.Text')=='+'
    assert not r.diagnostics


def test_selector_view_mode_keeps_values_and_fluent_appearance(page,app,tmp_path):
    from powerapps_sim.fixtures import selectors_project, search_project
    workspace=app.extensions['workspace'];workspace.open(selectors_project(tmp_path/'selectors-view'))
    r=workspace.runtime;r.restart();page.reload()
    status=page.get_by_role('combobox',name='Project status',exact=True)
    status.click();page.get_by_role('option',name='Submitted',exact=True).click()
    page.get_by_role('radio',name='High',exact=True).check()
    page.get_by_role('button',name='Toggle read-only',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=Status] button').getAttribute('aria-readonly')==='true'")
    status.click();assert status.get_attribute('aria-expanded')=='false' and status.is_enabled()
    assert page.get_by_role('radio',name='High',exact=True).is_checked()
    assert r.fx.evaluate('Status.Selected.Value')=='Submitted' and r.fx.evaluate('Priority.Selected.Amount')==100
    workspace.open(search_project(tmp_path/'combo-view'));r=workspace.runtime;r.restart();page.reload()
    page.get_by_role('button',name='Toggle form view',exact=True).click()
    team=page.get_by_role('combobox',name='Form team',exact=True)
    page.wait_for_function("document.querySelector('[data-control=TeamChoice] input').readOnly")
    team.click();assert team.evaluate('(e)=>e.readOnly && !e.disabled')
    assert team.get_attribute('aria-expanded')=='false' and team.input_value()=='North'
    assert not page.locator('[data-control=TeamChoice] .fx-combobox-clear').is_visible()
    assert not r.diagnostics


def test_numeric_steps_calendar_dates_and_form_blur_save(page,app,tmp_path):
    from powerapps_sim.fixtures import inputs_project
    workspace=app.extensions['workspace'];workspace.open(inputs_project(tmp_path/'inputs-browser'))
    r=workspace.runtime;r.restart();page.reload()
    amount=page.get_by_role('spinbutton',name='Amount',exact=True)
    amount.fill('17.125');assert r.fx.evaluate('Amount.Value')==12.5 and r.collections.get('events',[])==[]
    page.get_by_role('spinbutton',name='Quantity',exact=True).click()
    page.get_by_text('Quantity 2 · amount 17.13 · callbacks 1',exact=True).wait_for()
    page.get_by_role('button',name='Increase Quantity',exact=True).click()
    page.get_by_text('Quantity 4 · amount 17.13 · callbacks 2',exact=True).wait_for()
    page.get_by_role('button',name='Open calendar Meeting date',exact=True).click()
    assert not page.get_by_role('gridcell',name='Friday, January 9, 2026',exact=True).is_enabled()
    page.get_by_role('button',name='Next month',exact=True).click()
    page.get_by_role('gridcell',name='Saturday, February 14, 2026',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=Meeting] input').value==='14/02/2026'")
    page.get_by_role('button',name='English / French',exact=True).click()
    page.wait_for_function('state.globals.french===true')
    amount.fill('18,125');page.get_by_role('spinbutton',name='Quantity',exact=True).click()
    page.get_by_text('Quantity 4 · amount 18.13 · callbacks 4',exact=True).wait_for()
    amount.fill('150');page.get_by_role('spinbutton',name='Quantity',exact=True).click()
    page.locator('[data-control=Amount] [role=alert]').wait_for()
    assert amount.input_value()=='150' and r.fx.evaluate('Amount.Value')==18.13
    amount.fill('18,13');page.get_by_role('spinbutton',name='Quantity',exact=True).click()
    page.get_by_text('Ready',exact=True).wait_for();assert not page.locator('[data-control=Amount] [role=alert]').is_visible()
    amount.fill('18,25');page.get_by_role('spinbutton',name='FormCost',exact=True).fill('32,25')
    page.get_by_role('textbox',name='FormDate',exact=True).fill('2026-02-03')
    page.get_by_role('button',name='Save record',exact=True).click()
    page.get_by_text('Unsaved false · cost 32.25 · due 2/3/2026',exact=True).wait_for()
    assert r.store.rows('Records')[0]['Cost']==32.25 and r.store.rows('Records')[0]['Due']=='2026-02-03'
    page.get_by_role('button',name='Toggle form view',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=FormCost] input').readOnly")
    assert page.get_by_role('spinbutton',name='FormCost',exact=True).evaluate('(e)=>e.readOnly && !e.disabled')
    assert page.get_by_role('textbox',name='FormDate',exact=True).evaluate('(e)=>e.readOnly && !e.disabled')
    assert not r.diagnostics


def test_behavior_functions_components_live_values_and_sqlite_save(page,app,tmp_path):
    from powerapps_sim.fixtures import actions_project
    p=actions_project(tmp_path/'actions');w=app.extensions['workspace'];w.open(p)
    page.reload();page.get_by_text('Reusable actions · typed functions and components',exact=True).wait_for()
    page.get_by_role('button',name='Source',exact=True).click()
    page.get_by_role('button',name='Structure',exact=True).click()
    page.get_by_role('button',name='Spend 3',exact=True).click()
    page.get_by_text('Balance 17 · spent 3 · last component 0',exact=True).wait_for()
    page.get_by_role('button',name='Spend 2 twice',exact=True).click()
    page.get_by_text('Balance 13 · spent 7 · last component 0',exact=True).wait_for()
    page.get_by_role('button',name='Try overspend',exact=True).click()
    page.get_by_text('Insufficient balance',exact=True).wait_for()
    page.locator('[data-path="Actions/Left/Increase"]').get_by_role('button').click()
    page.get_by_text('Component total 11',exact=True).wait_for()
    assert w.runtime.fx.evaluate('Right.Total')==100 and 'current' not in w.runtime.globals
    page.get_by_role('button',name='Variables',exact=True).click()
    assert page.get_by_role('searchbox',name='Filter runtime values').is_visible()
    page.get_by_role('button',name='Save fictional draft',exact=True).click()
    page.get_by_text('Saved drafts 1 · last Fictional action draft',exact=True).wait_for()
    assert w.runtime.store.rows('Drafts')[0]['Amount']==7 and not w.runtime.diagnostics


def test_typed_table_components_text_selection_and_write(page,app,tmp_path):
    from powerapps_sim.fixtures import types_project
    w=app.extensions['workspace'];w.open(types_project(tmp_path/'types'))
    page.reload()
    page.get_by_role('button',name='Source',exact=True).click()
    page.get_by_role('button',name='Structure',exact=True).click()
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Filter left panel',exact=True).click()
    left=page.locator('[data-path="Types/Left"]')
    left.get_by_text('Panel total 20',exact=True).wait_for()
    left.get_by_role('button',name='Fictional Beta · 20',exact=True).press('Enter')
    page.get_by_text('Selected Fictional Beta · partial none · amount 0',exact=True).wait_for()
    page.get_by_text('Pure component score 30 · picked rows 1',exact=True).wait_for()
    page.get_by_role('button',name='Increase selected',exact=True).click()
    page.get_by_text('App total 31 · numeric table 6',exact=True).wait_for()
    page.get_by_text('Pure component score 31 · picked rows 1',exact=True).wait_for()
    assert w.runtime.store.rows('Projects')[1]['Amount']==21
    assert w.runtime.fx.evaluate('Left.Total')==21 and w.runtime.fx.evaluate('Right.Total')==31
    assert len(w.runtime.collections['events'])==1 and not w.runtime.diagnostics


def test_json_payload_nested_save_component_callbacks_and_dynamic_inspector(page,app,tmp_path):
    from powerapps_sim.fixtures import json_project
    w=app.extensions['workspace'];w.open(json_project(tmp_path/'json'))
    page.reload()
    page.get_by_role('button',name='Source',exact=True).click()
    page.get_by_role('button',name='Structure',exact=True).click()
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Fictional Alpha · 10 · Draft',exact=True).click()
    page.get_by_text('Selected Fictional Alpha · callbacks 0',exact=True).wait_for()
    page.get_by_role('button',name='Save selected',exact=True).click()
    page.get_by_text('Saved · 2 rows · total 30 · saved 1',exact=True).wait_for()
    assert w.runtime.store.rows('Projects')[0]['Owners'][0]['Email']=='admin@example.test'
    payload=page.get_by_role('textbox',name='JSON payload',exact=True)
    payload.fill('not JSON');page.get_by_role('button',name='Parse payload',exact=True).click()
    page.get_by_text('Invalid JSON: Expecting value: line 1 column 1 (char 0) · 2 rows · total 30 · saved 1',exact=True).wait_for()
    payload.fill('{"Projects":[{"Amount":"wrong"}]}');page.get_by_role('button',name='Parse payload',exact=True).click()
    page.get_by_text('Schema mismatch · 2 rows · total 30 · saved 1',exact=True).wait_for()
    page.get_by_role('button',name='Reset payload',exact=True).click()
    page.get_by_role('button',name='Parse payload',exact=True).click()
    page.get_by_text('Parsed · 2 rows · total 30 · saved 1',exact=True).wait_for()
    page.locator('[data-path="JsonScreen/Right"]').get_by_role('button',name='Pick first',exact=True).click()
    page.get_by_text('Selected Fictional Alpha · callbacks 1',exact=True).wait_for()
    page.get_by_role('button',name='Change peer',exact=True).click()
    page.locator('[data-path="JsonScreen/Right"]').get_by_text('Dynamic panel · 2 rows',exact=True).wait_for()
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Variables',exact=True).click()
    page.get_by_role('row').filter(has_text='document').get_by_text('Dynamic',exact=True).wait_for()
    assert not w.runtime.diagnostics


def test_function_coercion_component_callbacks_and_readable_variables(page,app,tmp_path):
    from powerapps_sim.fixtures import coercion_project
    w=app.extensions['workspace'];w.open(coercion_project(tmp_path/'coercion'))
    page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    amount=page.get_by_role('textbox',name='Amount text',exact=True)
    amount.fill('25.5')
    page.get_by_role('textbox',name='Boolean text',exact=True).fill('false')
    page.get_by_role('button',name='Convert record',exact=True).click()
    page.get_by_text('Converted · title 100 · amount 25.5 · enabled false',exact=True).wait_for()
    page.get_by_role('button',name='Save result',exact=True).click()
    page.evaluate('()=>requestQueue')
    assert w.runtime.store.rows('Projects')[0]['Amount']==25.5
    assert w.runtime.store.rows('Projects')[0]['Enabled'] is False
    amount.fill('wrong');page.get_by_role('button',name='Convert record',exact=True).click()
    page.get_by_text("Cannot parse number 'wrong' · title 100 · amount 25.5 · enabled false",exact=True).wait_for()
    page.get_by_role('textbox',name='Left component amount',exact=True).fill('8')
    page.locator('[data-path="CoercionScreen/Left"]').get_by_role('button',name='Use amount',exact=True).click()
    page.get_by_text('Left callback · title Left callback · amount 8 · enabled true',exact=True).wait_for()
    assert w.runtime.fx.evaluate('Right.TextValue')=='7'
    page.locator('[data-path="CoercionScreen/Right"]').get_by_role('button',name='Use amount',exact=True).click()
    page.get_by_text('Right callback · title Right callback · amount 7 · enabled false',exact=True).wait_for()
    assert w.runtime.fx.evaluate('Left.TextValue')=='8'
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Variables',exact=True).click()
    assert_inspected_record(page, 'result', {'Amount':'7', 'Enabled':'false', 'Title':'Right callback'})
    page.get_by_role('button',name='Collections',exact=True).click()
    page.get_by_role('button',name=re.compile(r'^events · [23]')).wait_for()
    assert len(w.runtime.collections['events'])==2 and not w.runtime.diagnostics


def test_component_contract_defaults_conversions_reset_and_save(page,app,tmp_path):
    from powerapps_sim.fixtures import contracts_project
    w=app.extensions['workspace'];w.open(contracts_project(tmp_path/'contracts'))
    page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    left=page.locator('[data-path="ContractsScreen/Left"]')
    right=page.locator('[data-path="ContractsScreen/Right"]')
    amount=page.get_by_role('textbox',name='Fictional left amount',exact=True)
    amount.fill('8');left.get_by_role('button',name='Add amount',exact=True).click()
    page.get_by_text('Left total 18',exact=True).wait_for()
    right.get_by_role('button',name='Add default',exact=True).click()
    page.get_by_text('Right total 103',exact=True).wait_for()
    page.get_by_role('button',name='Convert record & table',exact=True).click()
    page.get_by_role('button',name='Save left snapshot',exact=True).click()
    page.get_by_text('Record amount 4 · enabled true · table total 6 · stored total 18',exact=True).wait_for()
    amount.fill('bad');left.get_by_role('button',name='Add amount',exact=True).click()
    page.get_by_text("Cannot parse number 'bad' · callbacks 2 · saved 1",exact=True).wait_for()
    assert w.runtime.fx.evaluate('Left.Total')==18 and w.runtime.fx.evaluate('Right.Total')==103
    page.get_by_role('button',name='Seed to 20',exact=True).click()
    page.get_by_role('button',name='Reset left',exact=True).click()
    page.get_by_text('Left total 20',exact=True).wait_for()
    amount.fill('2');left.get_by_role('button',name='Add amount',exact=True).click()
    page.get_by_role('button',name='Save left snapshot',exact=True).click()
    page.get_by_text('Saved left snapshot · callbacks 3 · saved 2',exact=True).wait_for()
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Variables',exact=True).click()
    assert_inspected_record(page, 'sample', {'Amount':'4', 'Enabled':'true'})
    page.get_by_role('button',name='Collections',exact=True).click()
    page.get_by_role('button',name=re.compile(r'^events · [23]')).wait_for()
    rows=w.runtime.store.rows('Projects')
    assert [row['Amount'] for row in rows]==[18,22] and all(row['Enabled'] is True for row in rows)
    assert len(w.runtime.collections['events'])==3 and not w.runtime.diagnostics


def test_setfocus_visual_tab_order_callbacks_and_offscreen_scroll(page,app,tmp_path):
    from powerapps_sim.fixtures import focus_project
    w=app.extensions['workspace'];w.open(focus_project(tmp_path/'focus'))
    page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    first=page.get_by_role('textbox',name='FirstName',exact=True)
    surname=page.get_by_role('textbox',name='Surname',exact=True)
    page.get_by_role('button',name='Focus first',exact=True).click()
    page.wait_for_function("document.activeElement.getAttribute('aria-label')==='FirstName'")
    first.press('Tab')
    page.wait_for_function("document.activeElement.getAttribute('aria-label')==='Surname'")
    page.get_by_role('button',name='Focus read-only',exact=True).click()
    page.wait_for_function("document.activeElement.getAttribute('aria-label')==='ReadOnly' && document.activeElement.readOnly")
    page.get_by_role('button',name='Toggle tab stop',exact=True).click()
    page.get_by_role('button',name='Focus first',exact=True).click()
    page.wait_for_function("document.activeElement.getAttribute('aria-label')==='FirstName' && document.activeElement.tabIndex===-1")
    page.get_by_role('button',name='Toggle disabled',exact=True).click()
    page.get_by_role('button',name='Focus first',exact=True).click()
    page.wait_for_function("document.activeElement.textContent==='Focus first' && document.querySelector('[data-control=FirstName] input').disabled")
    page.get_by_role('button',name='Toggle disabled',exact=True).click()
    page.get_by_role('button',name='Focus notes',exact=True).click()
    page.wait_for_function("document.activeElement.getAttribute('aria-label')==='Notes' && document.querySelector('#preview-scroll').scrollTop>0")
    page.get_by_role('button',name='Back to first',exact=True).click()
    page.get_by_role('button',name='Refresh values',exact=True).click()
    assert page.get_by_role('button',name='Refresh values',exact=True).evaluate('(e)=>e===document.activeElement')
    left=page.locator('[data-path="FocusScreen/Left"]')
    left.get_by_role('textbox').fill('Left draft')
    left.get_by_role('button',name='Focus host',exact=True).click()
    page.wait_for_function("document.activeElement.getAttribute('aria-label')==='FirstName'")
    page.get_by_role('button',name='Focus label',exact=True).click()
    page.wait_for_function("document.activeElement.closest('[data-path]').dataset.path==='FocusScreen/Caption'")
    page.get_by_role('button',name='Classic tab index 7',exact=True).press('Tab')
    page.wait_for_function("document.activeElement.textContent==='Next screen'")
    page.get_by_role('button',name='Next screen',exact=True).press('Enter')
    page.wait_for_function("document.activeElement.getAttribute('aria-label')==='Arrival'")
    page.get_by_role('button',name='Return',exact=True).click()
    first.wait_for();page.wait_for_function("document.activeElement.getAttribute('aria-label')==='FirstName'")
    assert w.runtime.fx.evaluate('Left.Draft')=='Left draft' and not w.runtime.diagnostics


def test_update_collections_components_and_mapped_list_failure_retry(page,app,tmp_path):
    from powerapps_sim.fixtures import update_project
    w=app.extensions['workspace'];w.open(update_project(tmp_path/'update'))
    page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    page.get_by_role('button',name='Increase enabled rows',exact=True).click()
    page.get_by_text('Collection total 60 · rows 3',exact=True).wait_for()
    page.get_by_role('button',name='Replace all duplicates',exact=True).click()
    page.get_by_text('Collection total 40 · rows 3',exact=True).wait_for()
    page.get_by_role('button',name='Increase local rows',exact=True).nth(0).click()
    page.get_by_text('Left 22 · right 200 · app collection 40',exact=True).wait_for()
    page.get_by_role('button',name='Increase local rows',exact=True).nth(1).click()
    page.get_by_text('Left 22 · right 202 · app collection 40',exact=True).wait_for()
    page.get_by_role('button',name='Increase draft projects',exact=True).click()
    page.get_by_text('Drafts updated · list total 70 · callbacks 2',exact=True).wait_for()
    page.get_by_role('button',name='Try invalid title',exact=True).click()
    page.get_by_text('Project name is required · list total 70 · callbacks 2',exact=True).wait_for()
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('combobox',name='Simulate failure',exact=True).select_option('write')
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Increase draft projects',exact=True).click()
    page.get_by_text('Simulated write failure for Projects · list total 70 · callbacks 2',exact=True).wait_for()
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('combobox',name='Simulate failure',exact=True).select_option('')
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Increase draft projects',exact=True).click()
    page.get_by_text('Drafts updated · list total 80 · callbacks 2',exact=True).wait_for()
    page.get_by_role('button',name='Replace first project',exact=True).click()
    page.get_by_text('Fictional replacement · 5 · blank',exact=True).wait_for()
    page.get_by_role('button',name='Reset left component',exact=True).click()
    page.get_by_text('Left 20 · right 202 · app collection 40',exact=True).wait_for()
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Collections',exact=True).click()
    page.get_by_role('button',name='local · 3 App',exact=True).click()
    page.wait_for_function("document.querySelectorAll('#inspector .value-table .value-type.blank').length===2")
    assert page.locator('#inspector .value-table td code').filter(has_text=re.compile('^Blank$')).count()==2
    assert w.runtime.fx.evaluate('Total')==65 and len(w.runtime.collections['events'])==2
    assert w.runtime.store.rows('Projects')[0]['Status'] is None and not w.runtime.diagnostics


def test_patch_owned_tables_components_batches_and_failed_save(page,app,tmp_path):
    from powerapps_sim.fixtures import patch_project
    w=app.extensions['workspace'];w.open(patch_project(tmp_path/'patch'))
    page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    for name in ('Patch first row','Append local row','Patch copied rows','Patch nested row'):
        page.get_by_role('button',name=name,exact=True).click()
    page.get_by_text('Local 30 · copy 40 · nested 15 · pure merge 2',exact=True).wait_for()
    page.get_by_role('button',name='Patch local row',exact=True).nth(0).click()
    page.get_by_text('Left 4 · right 21 · batch rows 0',exact=True).wait_for()
    page.get_by_role('button',name='Patch local row',exact=True).nth(1).click()
    page.get_by_role('button',name='Patch draft projects',exact=True).click()
    page.get_by_text('Drafts patched · list total 70 · callbacks 2',exact=True).wait_for()
    page.get_by_role('button',name='Try invalid batch',exact=True).click()
    page.get_by_text('Project name is required · list total 70 · callbacks 2',exact=True).wait_for()
    assert w.runtime.store.rows('Projects')[0]['Project name']=='Fictional validated 1'
    assert w.runtime.store.rows('Projects')[1]['Project name']=='Fictional project 2'
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('combobox',name='Simulate failure',exact=True).select_option('write')
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Patch draft projects',exact=True).click()
    page.get_by_text('Simulated write failure for Projects · list total 70 · callbacks 2',exact=True).wait_for()
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('combobox',name='Simulate failure',exact=True).select_option('')
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Patch draft projects',exact=True).click()
    page.get_by_role('button',name='Create two projects',exact=True).click()
    page.get_by_text('Two created · list total 91 · callbacks 2',exact=True).wait_for()
    page.get_by_role('button',name='Patch keyed record',exact=True).click()
    page.get_by_role('button',name='Reset left component',exact=True).click()
    page.get_by_text('Left 3 · right 22 · batch rows 2',exact=True).wait_for()
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('button',name='Edit record 4',exact=True).click()
    page.get_by_role('spinbutton',name='Amount',exact=True).fill('7')
    page.get_by_role('button',name='Save record',exact=True).click()
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_text('Left reset · list total 78 · callbacks 2',exact=True).wait_for()
    assert w.runtime.fx.evaluate('Sum(copy,Amount)')==40
    assert w.runtime.fx.evaluate('Sum(book.Rows,Amount)')==15
    assert w.runtime.fx.evaluate('Left.Merge(4)')==5
    assert len(w.runtime.store.rows('Projects'))==5 and not w.runtime.diagnostics
    assert not page.errors


def test_removal_matching_components_persistent_ids_and_failure_retry(page,app,tmp_path):
    from powerapps_sim.fixtures import remove_project
    w=app.extensions['workspace'];w.open(remove_project(tmp_path/'remove'))
    page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    for name in ('Remove one duplicate','Remove all duplicates','Remove copied matches','Remove nested matches'):
        page.get_by_role('button',name=name,exact=True).click()
    page.get_by_text('Local 1 · copy 1 · nested 2 · last ID ',exact=False).wait_for()
    page.get_by_role('button',name='Remove first local',exact=True).nth(0).click()
    page.get_by_role('button',name='Remove first local',exact=True).nth(1).click()
    page.get_by_text('Left 2 · right 2 · app rows 1',exact=True).wait_for()
    page.get_by_role('button',name='3 · Fictional project 3 · 30',exact=True).click()
    page.get_by_text('Selected ID 3',exact=True).wait_for()
    page.get_by_role('button',name='Remove selected project',exact=True).click()
    page.get_by_role('button',name='Create next project',exact=True).click()
    page.evaluate('()=>requestQueue')
    assert w.runtime.globals['lastId']==4
    page.get_by_role('button',name='Try missing batch',exact=True).click()
    page.get_by_text('Remove record was not found · list total 27 · callbacks 2',exact=True).wait_for()
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('combobox',name='Simulate failure',exact=True).select_option('write')
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Remove draft projects',exact=True).click()
    page.get_by_text('Simulated write failure for Projects · list total 27 · callbacks 2',exact=True).wait_for()
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('combobox',name='Simulate failure',exact=True).select_option('')
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Remove draft projects',exact=True).click()
    page.evaluate('()=>requestQueue')
    assert w.runtime.store.rows('Projects')==[]
    page.get_by_role('button',name='Create next project',exact=True).click()
    page.get_by_role('button',name='Try failing predicate',exact=True).click()
    page.get_by_text('Division by zero · list total 7 · callbacks 2',exact=True).wait_for()
    assert w.runtime.globals['lastId']==5 and len(w.runtime.store.rows('Projects'))==1
    page.get_by_role('button',name='Reset left component',exact=True).click()
    page.get_by_text('Left 3 · right 2 · app rows 1',exact=True).wait_for()
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('button',name='Edit record 5',exact=True).click()
    page.get_by_role('spinbutton',name='Amount',exact=True).fill('9')
    page.get_by_role('button',name='Save record',exact=True).click()
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_text('Left reset · list total 9 · callbacks 2',exact=True).wait_for()
    assert w.runtime.fx.evaluate('CountRows(copy)')==1 and w.runtime.fx.evaluate('CountRows(book.Rows)')==2
    assert len(w.runtime.collections['events'])==2 and w.runtime.store.next_id('Projects')==6
    assert not w.runtime.diagnostics and not page.errors


def test_datasource_errors_form_recovery_and_expanded_record_table(page,app,tmp_path):
    from powerapps_sim.fixtures import data_errors_project
    w=app.extensions['workspace'];w.open(data_errors_project(tmp_path/'data-errors'))
    page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    page.get_by_role('button',name='Try invalid create',exact=True).click()
    page.get_by_text('Blank creates 1 · left 0 · right 0',exact=True).wait_for()
    page.get_by_role('button',name='Try invalid edit',exact=True).click()
    page.get_by_role('button',name='Fail record save',exact=True).nth(1).click()
    page.get_by_text('Blank creates 0 · left 0 · right 1',exact=True).wait_for()
    page.get_by_role('button',name='Fail record save',exact=True).nth(0).click()
    page.get_by_role('button',name='Try failed row batch',exact=True).click()
    page.get_by_text('Batch failed · errors 2 · list total 139 · callbacks 2',exact=True).wait_for()
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('heading',name='Operation errors',exact=True).wait_for()
    page.get_by_text('Record 1 · Fictional project 1',exact=True).click()
    assert page.locator('#list-error-table details[open] pre').inner_text().find('"ID": 1')>=0
    page.get_by_role('combobox',name='Simulate failure',exact=True).select_option('write')
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Retry record save',exact=True).click()
    page.get_by_text('Retry failed · errors 1 · list total 139 · callbacks 2',exact=True).wait_for()
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('combobox',name='Simulate failure',exact=True).select_option('')
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Retry record save',exact=True).click()
    page.get_by_text('Retried · errors 0 · list total 139 · callbacks 2',exact=True).wait_for()
    title=page.get_by_role('textbox',name='Project name',exact=True)
    title.fill('');title.press('Tab')
    page.get_by_role('button',name='Save form',exact=True).click()
    page.get_by_text('Form failed · errors 1 · list total 139 · callbacks 2',exact=True).wait_for()
    assert w.runtime.fx.evaluate('ProjectForm.Unsaved') is True and w.runtime.collections['captured'][0]['Error']==2
    title.fill('Fictional recovered form');title.press('Tab')
    page.get_by_role('button',name='Save form',exact=True).click()
    page.get_by_text('Form saved · errors 0 · list total 139 · callbacks 2',exact=True).wait_for()
    assert w.runtime.fx.evaluate('Errors(Projects)')==[] and not w.runtime.diagnostics and not page.errors


def test_gallery_background_defaults_nested_scopes_focus_and_reset(page,app,tmp_path):
    from powerapps_sim.fixtures import galleries_project
    w=app.extensions['workspace'];w.open(galleries_project(tmp_path/'galleries'))
    page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    summary=page.locator('[data-control="Summary"]')
    page.get_by_role('listitem',name='Fictional Alpha',exact=True).click()
    page.get_by_text('gallery Fictional Alpha · selected Fictional Alpha · events 1 · loaded 3',exact=True).wait_for()
    page.get_by_role('list',name='Records',exact=True).get_by_role('button',name='Fictional Beta',exact=True).click()
    page.get_by_text('gallery Fictional Beta · selected Fictional Beta · events 2 · loaded 3',exact=True).wait_for()
    page.get_by_role('button',name='Custom Fictional Gamma',exact=True).click()
    page.get_by_text('custom Fictional Gamma · selected Fictional Gamma · events 2 · loaded 3',exact=True).wait_for()
    note=page.get_by_role('textbox',name='Note Fictional Beta',exact=True)
    note.click()
    page.get_by_text('gallery Fictional Beta · selected Fictional Beta · events 3 · loaded 3',exact=True).wait_for()
    note.fill('Kept after gallery reset')
    assert note.evaluate('(e)=>document.activeElement===e')
    note.press('Tab')
    page.get_by_role('listitem',name='Fictional Gamma',exact=True).press('Enter')
    page.get_by_text('gallery Fictional Gamma · selected Fictional Gamma · events 4 · loaded 3',exact=True).wait_for()
    assert page.locator('[data-control="Records"]').evaluate('(e)=>e.scrollTop')>0
    page.get_by_role('button',name='Reset gallery',exact=True).click()
    page.get_by_text('gallery Fictional Gamma · selected Fictional Beta · events 4 · loaded 3',exact=True).wait_for()
    assert note.input_value()=='Kept after gallery reset'
    assert page.locator('[data-control="Records"]').evaluate('(e)=>e.scrollTop')==0
    page.get_by_role('button',name='Inner Beta',exact=True).click()
    page.get_by_text('inner Inner Beta · selected Fictional Beta · events 4 · loaded 3',exact=True).wait_for()
    page.get_by_role('button',name='Toggle selection',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=Records]>.fx-gallery-surface>.fx-row').tabIndex===-1")
    page.get_by_role('listitem',name='Fictional Alpha',exact=True).click()
    assert w.runtime.fx.evaluate('Records.Selected.ID')==2
    page.get_by_role('button',name='Custom Fictional Alpha',exact=True).click()
    page.get_by_text('custom Fictional Alpha · selected Fictional Beta · events 4 · loaded 3',exact=True).wait_for()
    page.get_by_role('button',name='Toggle selection',exact=True).click()
    page.get_by_role('button',name='Toggle wrap',exact=True).click()
    page.wait_for_function("document.querySelectorAll('[data-control=Records]>.fx-gallery-surface>.fx-row')[0].offsetTop===document.querySelectorAll('[data-control=Records]>.fx-gallery-surface>.fx-row')[1].offsetTop")
    page.get_by_role('button',name='Reverse rows',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=Records]>.fx-gallery-surface>.fx-row').getAttribute('aria-label')==='Fictional Gamma'")
    assert note.input_value()=='Kept after gallery reset'
    assert not w.runtime.diagnostics and not page.errors


def test_allitems_gallery_edits_component_save_and_live_control_inspection(page,app,tmp_path):
    from powerapps_sim.fixtures import gallery_edits_project
    w=app.extensions['workspace'];w.open(gallery_edits_project(tmp_path/'gallery-edits'))
    page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    title=page.get_by_role('textbox',name='Title 2',exact=True)
    title.fill('Fictional edited Beta');title.press('Tab')
    cost=page.get_by_role('spinbutton',name='Cost 2',exact=True)
    cost.fill('25');cost.press('Tab')
    page.get_by_role('combobox',name='Status 2',exact=True).click()
    page.get_by_role('option',name='Done',exact=True).click()
    page.get_by_role('switch',name='Enabled 2',exact=True).uncheck()
    page.get_by_role('button',name='Open calendar Due 2',exact=True).click()
    page.get_by_role('gridcell',name='Thursday, February 5, 2026',exact=True).click()
    page.get_by_text('Ready · stored 60 · pending 65 · changed 1 · callbacks 0',exact=True).wait_for()
    page.get_by_role('button',name='Snapshot edits',exact=True).click()
    page.get_by_role('button',name='Capture controls',exact=True).click()
    page.get_by_role('button',name='Reverse rows',exact=True).click()
    assert title.input_value()=='Fictional edited Beta' and cost.input_value()=='25'
    page.get_by_role('button',name='Save edited rows',exact=True).click()
    page.get_by_text('Saved · stored 65 · pending 65 · changed 0 · callbacks 1',exact=True).wait_for()
    stored=w.runtime.store.rows('Projects')[1]
    assert stored['Amount']==25 and stored['Status']['Value']=='Done' and stored['Enabled'] is False
    assert stored['Due']=='2026-02-05'
    title.fill('');title.press('Tab')
    page.get_by_role('button',name='Save edited rows',exact=True).click()
    page.get_by_text('Save failed · stored 65 · pending 65 · changed 1 · callbacks 1',exact=True).wait_for()
    assert title.input_value()=='' and w.runtime.collections['saveErrors'][0]['Column']=='Title'
    page.get_by_role('button',name='Reset inputs',exact=True).click()
    page.get_by_text('Save failed · stored 65 · pending 65 · changed 0 · callbacks 1',exact=True).wait_for()
    assert title.input_value()=='Fictional edited Beta'
    cost.fill('40');cost.press('Tab')
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('combobox',name='Simulate failure',exact=True).select_option('write')
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Save edited rows',exact=True).click()
    page.get_by_text('Save failed · stored 65 · pending 80 · changed 1 · callbacks 1',exact=True).wait_for()
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('combobox',name='Simulate failure',exact=True).select_option('')
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Save edited rows',exact=True).click()
    page.get_by_text('Saved · stored 80 · pending 80 · changed 0 · callbacks 2',exact=True).wait_for()
    assert w.runtime.collections['editsSnapshot'][1]['Cost']==25
    cost.fill('45');cost.press('Tab')
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Collections',exact=True).click()
    table=page.get_by_label('controlRows collection')
    assert table.locator('thead th').count()==15
    assert table.evaluate('(e)=>e.scrollWidth>e.clientWidth')
    table.get_by_role('button',name='Inspect CostInput',exact=True).nth(1).click()
    value=page.locator('#inspector tr').filter(has=page.get_by_role('cell',name='Value',exact=True))
    default=page.locator('#inspector tr').filter(has=page.get_by_role('cell',name='Default',exact=True))
    value.wait_for();assert value.locator('td').last.inner_text()=='45'
    assert default.locator('td').last.inner_text()=='40'
    assert not w.runtime.diagnostics and not page.errors


def test_gallery_viewport_loading_retains_edits_drafts_and_focus(page,app,tmp_path):
    from powerapps_sim.fixtures import gallery_loading_project
    w=app.extensions['workspace'];w.open(gallery_loading_project(tmp_path/'gallery-loading'))
    page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    gallery=page.locator('[data-control="Records"]')
    page.wait_for_function("document.querySelector('[data-control=Horizontal]').getAttribute('aria-busy')==='false'")
    amount=page.get_by_role('spinbutton',name='Amount 1',exact=True)
    amount.fill('99');amount.press('Enter')
    note=page.get_by_role('textbox',name='Note 1',exact=True)
    note.fill('Fictional retained first');note.press('Tab')
    page.get_by_role('button',name='Capture loaded controls',exact=True).click()
    # Test harness drives browser scroll; Power Fx still runs exclusively in Python.
    gallery.evaluate('(e)=>{e.scrollTop=66000;}')
    far=page.get_by_role('spinbutton',name='Amount 661',exact=True);far.wait_for()
    assert gallery.locator(':scope > .fx-gallery-surface > .fx-row').count()<=10
    assert w.runtime.fx.evaluate('clicks')==0
    far.fill('-');far.press('Tab')
    page.get_by_text("Cannot parse number '-'",exact=True).last.wait_for()
    gallery.evaluate('(e)=>{e.scrollTop=0;}');amount.wait_for()
    assert amount.input_value()=='99' and note.input_value()=='Fictional retained first'
    gallery.evaluate('(e)=>{e.scrollTop=66000;}');far.wait_for()
    assert far.input_value()=='-'
    far.fill('700');far.press('Enter')
    draft=page.get_by_role('textbox',name='Note 661',exact=True);draft.fill('Fictional focus retained')
    page.wait_for_function("document.querySelector('[data-control=Summary]').textContent.includes('edits 3')")
    assert draft.evaluate('(e)=>document.activeElement===e')
    draft.press('Tab');page.get_by_role('button',name='Reset gallery',exact=True).click()
    amount.wait_for();assert amount.input_value()=='99'
    page.wait_for_function("document.querySelector('[data-control=Records]').scrollTop===0")
    assert w.runtime.fx.evaluate('First(captured).AmountInput.Value')==99
    assert not w.runtime.diagnostics and not page.errors


def test_modern_icons_keyboard_components_media_and_persistence(page,app,tmp_path):
    from powerapps_sim.fixtures import icons_project
    w=app.extensions['workspace'];w.open(icons_project(tmp_path/'icons'))
    page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    left=page.get_by_role('button',name='Increase Left',exact=True)
    left.click();left.press('Enter')
    page.get_by_role('button',name='Increase Right',exact=True).press('Space')
    page.get_by_text('Left 12 · right 101 · callbacks 3 · Ready',exact=True).wait_for()
    assert left.locator('svg use').get_attribute('href').startswith('/static/fluent-icons.svg#')
    assert page.get_by_role('img',name='Fictional badge Left',exact=True).get_attribute('src').startswith('data:image/svg+xml;base64,')
    assert page.get_by_role('img',name='Ready status',exact=True).count()==1
    assert not page.get_by_role('button',name='Disabled delete',exact=True).is_enabled()
    assert not page.get_by_role('button',name='Read-only edit',exact=True).is_enabled()
    rotate=page.get_by_role('button',name='Rotate icon',exact=True)
    rotate.click();page.wait_for_function("document.querySelector('[data-control=Rotate] svg').style.transform==='rotate(45deg)'")
    rotate.press('Tab')
    assert page.get_by_role('button',name='Reset left',exact=True).evaluate('(e)=>document.activeElement===e')
    page.get_by_role('button',name='Toggle style',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=Rotate] use').getAttribute('href').endsWith('-filled')")
    assert rotate.locator('use').get_attribute('href').endswith('-filled')
    page.get_by_role('button',name='Save snapshot',exact=True).click()
    page.get_by_text('Left 12 · right 101 · callbacks 3 · Saved',exact=True).wait_for()
    row=w.runtime.store.rows('Snapshots')[0]
    assert row['LeftCount']==12 and row['RightCount']==101 and row['Picture'].startswith('data:image/')
    page.get_by_role('button',name='Select Search',exact=True).click()
    page.get_by_text('Left 12 · right 101 · callbacks 3 · Selected Search',exact=True).wait_for()
    page.get_by_role('button',name='Reset left',exact=True).click()
    page.get_by_text('Left · 10',exact=True).wait_for()
    page.get_by_text('Right · 101',exact=True).wait_for()
    # Reset changes private state without inventing a callback to the host.
    page.get_by_text('Left 12 · right 101 · callbacks 3 · Selected Search',exact=True).wait_for()
    assert not w.runtime.diagnostics and not page.errors


def test_live_powerfx_types_nested_paging_and_refresh_focus(page,app,tmp_path):
    from powerapps_sim.fixtures import inspection_project
    w=app.extensions['workspace'];w.open(inspection_project(tmp_path/'inspection'))
    page.reload()
    for name in ('Source','Structure'):
        page.get_by_role('button',name=name,exact=True).click()
    page.get_by_role('button',name='Variables',exact=True).click()
    fields=page.get_by_role('searchbox',name='Filter runtime values',exact=True)
    fields.fill('photo')
    assert page.locator('[data-live-value=photo] .value-type').inner_text()=='Image'
    page.wait_for_function("document.querySelector('[data-live-value=photo] .value-image').naturalWidth>0")
    fields.fill('tint')
    assert page.locator('[data-live-value=tint] .value-type').inner_text()=='Color'
    assert page.locator('[data-live-value=tint] .color-swatch').is_visible()
    fields.fill('uninitialized')
    assert page.locator('[data-live-value=uninitialized] .value-type').get_attribute('title')=='Declared Date'
    fields.fill('person');page.get_by_text('Record · 4 fields',exact=True).click()
    groups=page.get_by_text('Table · 55 rows',exact=True);groups.click()
    page.get_by_role('button',name='Next rows of Groups',exact=True).click()
    page.get_by_text('51–55 of 55',exact=True).wait_for()
    page.get_by_text('Fictional group 55',exact=True).wait_for()
    groups.click();groups.click()
    with w.lock:w.runtime.event('InspectScreen/Snapshot','OnSelect')
    page.wait_for_function("document.querySelector('[data-control=Summary]').textContent.includes('Rows 3')")
    assert groups.evaluate('(e)=>document.activeElement===e&&e.parentElement.open')
    page.get_by_text('51–55 of 55',exact=True).wait_for()
    fields.fill('failure');page.get_by_role('button',name='Capture error',exact=True).click()
    page.wait_for_function("document.querySelector('[data-live-value=failure] .value-type').textContent==='Error'")
    page.locator('[data-live-value=failure] summary').click()
    assert page.locator('[data-live-value=failure] details').get_attribute('open') is not None
    assert not w.runtime.diagnostics and not page.errors


def test_typed_collection_headers_empty_shapes_and_horizontal_scroll(page,app,tmp_path):
    from powerapps_sim.fixtures import inspection_project
    w=app.extensions['workspace'];w.open(inspection_project(tmp_path/'inspection'))
    page.reload()
    for name in ('Source','Structure'):
        page.get_by_role('button',name=name,exact=True).click()
    page.get_by_role('button',name='Capture Left',exact=True).click()
    page.get_by_role('button',name='Capture Right',exact=True).click()
    page.get_by_role('button',name='Collections',exact=True).click()
    page.get_by_role('button',name=re.compile(r'^snapshots · 2')).click()
    grid=page.get_by_label('snapshots collection')
    assert grid.locator('th').count()==20
    assert grid.locator('th').filter(has_text='Picture').locator('.value-type').inner_text()=='Image'
    assert grid.locator('th').filter(has_text='Tint').locator('.value-type').inner_text()=='Color'
    grid.evaluate('(e)=>{e.scrollLeft=1500;}')
    before=grid.evaluate('(e)=>e.scrollLeft')
    with w.lock:w.runtime.event('InspectScreen/Snapshot','OnSelect')
    page.wait_for_function("document.querySelector('[data-control=Summary]').textContent.includes('Rows 3')")
    assert grid.evaluate('(e)=>e.scrollLeft')==before
    page.get_by_role('button',name=re.compile(r'^emptyTable · 0')).click()
    empty=page.get_by_label('emptyTable collection');assert empty.locator('th').count()==4
    assert empty.locator('th').filter(has_text='Due').locator('.value-type').inner_text()=='Date'
    page.get_by_role('button',name=re.compile(r'^values · 1')).filter(has_text='LeftPanel').click()
    local=page.get_by_label('values collection')
    assert local.locator('th').filter(has_text='Stamp').locator('.value-type').inner_text()=='DateTime'
    page.get_by_role('button',name='Reset left',exact=True).click()
    page.wait_for_function("document.querySelector('[aria-label=\"values collection\"] tbody').children.length===0")
    assert local.locator('th').count()==4 and local.locator('tbody tr').count()==0
    assert not w.runtime.diagnostics and not page.errors


def test_classic_icons_pointer_keyboard_colors_gallery_and_callbacks(page,app,tmp_path):
    from powerapps_sim.fixtures import classic_icons_project
    w=app.extensions['workspace'];w.open(classic_icons_project(tmp_path/'classic'))
    page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    left=page.get_by_role('button',name='Increase LeftPanel',exact=True)
    left.click();left.press('Enter')
    page.get_by_role('button',name='Increase RightPanel',exact=True).press('Space')
    page.get_by_text('Left 12 · Right 101 · callbacks 3 · RightPanel captured 101',exact=True).wait_for()
    pointer=page.get_by_role('img',name='Rotate by pointer',exact=True)
    pointer.click()
    page.wait_for_function("document.querySelector('[data-control=Pointer] svg').style.transform==='rotate(45deg)'")
    assert pointer.evaluate('(e)=>getComputedStyle(e).color')=='rgb(0, 128, 0)'
    assert pointer.locator('svg').get_attribute('preserveAspectRatio')=='none'
    assert pointer.evaluate('(e)=>e.tabIndex')==-1
    # Pressed colors are a visual state; no invented Self.Pressed event is sent.
    pointer.hover();page.mouse.down()
    assert pointer.evaluate('(e)=>getComputedStyle(e).color')=='rgb(255, 0, 0)'
    page.mouse.up()
    blank=page.get_by_role('button',name='Blank keyboard button',exact=True)
    blank.press('Enter')
    assert blank.evaluate('(e)=>getComputedStyle(e).outlineColor')=='rgb(128, 0, 128)'
    assert blank.evaluate('(e)=>getComputedStyle(e).outlineWidth')=='4px'
    blank.press('Tab')
    assert page.get_by_role('button',name='Reset left',exact=True).evaluate('(e)=>document.activeElement===e')
    assert not page.get_by_role('button',name='Disabled classic icon',exact=True).is_enabled()
    assert not page.get_by_role('button',name='Read-only classic icon',exact=True).is_enabled()
    assert page.get_by_role('button',name='Disabled classic icon',exact=True).evaluate('(e)=>getComputedStyle(e).color')=='rgb(128, 128, 128)'
    page.get_by_role('button',name='Select ArrowDown',exact=True).click()
    page.get_by_role('img',name='Pointer select ArrowLeft',exact=True).click()
    page.get_by_text('Left 12 · Right 101 · callbacks 3 · Selected ArrowLeft',exact=True).wait_for()
    page.get_by_role('button',name='Save snapshot',exact=True).click()
    page.get_by_text('Left 12 · Right 101 · callbacks 3 · Snapshot saved',exact=True).wait_for()
    assert w.runtime.store.rows('Snapshots')[0]['Selected']=='ArrowLeft'
    page.get_by_role('button',name='Reset left',exact=True).click()
    page.get_by_text('LeftPanel · 10',exact=True).wait_for()
    page.get_by_text('RightPanel · 101',exact=True).wait_for()
    assert len(w.runtime.collections['history'])==3
    assert not w.runtime.diagnostics and not page.errors


def test_classic_inputs_timing_focus_components_dropdown_and_form(page,app,tmp_path):
    from powerapps_sim.fixtures import classic_inputs_project
    w=app.extensions['workspace'];w.open(classic_inputs_project(tmp_path/'classic-inputs'))
    page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    left=page.get_by_role('textbox',name='LeftPanel title',exact=True)
    left.fill('Edited Alpha');left.press('Tab')
    page.wait_for_function("document.querySelector('[data-control=Summary]').textContent.includes('Callbacks 1')")
    right=page.get_by_role('combobox',name='RightPanel stage',exact=True)
    right.press('End');right.press('Enter')
    page.wait_for_function("document.querySelector('[data-control=Summary]').textContent.includes('Callbacks 2')")
    assert right.text_content()=='Completed▾'
    assert w.runtime.fx.evaluate('LeftPanel.Current.Title')=='Edited Alpha'
    assert w.runtime.fx.evaluate('RightPanel.Current.Stage')=='Done'
    assert left.evaluate('(e)=>getComputedStyle(e).borderWidth')=='1px'
    immediate=page.get_by_role('textbox',name='Immediate text',exact=True)
    page.get_by_role('button',name='Clear Immediate text',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=Immediate] input').value===''")
    assert immediate.evaluate('(e)=>document.activeElement===e')
    assert page.get_by_role('button',name='Clear Immediate text',exact=True).count()==0
    delayed=page.get_by_role('textbox',name='Delayed text',exact=True)
    delayed.fill('timed')
    assert w.runtime.fx.evaluate('Delayed.Text')==''
    page.wait_for_function("document.querySelector('[data-control=Summary]').textContent.includes('delayed [timed]')")
    assert delayed.evaluate('(e)=>document.activeElement===e')
    assert delayed.evaluate('(e)=>e.selectionStart')==5
    delayed.fill('pending');page.get_by_role('button',name='Reset delayed',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=Delayed] input').value===''")
    # Let the cancelled timer's deadline pass: it must not restore the draft.
    page.wait_for_timeout(600)
    assert w.runtime.fx.evaluate('Delayed.Text')=='' and delayed.input_value()==''
    optional=page.get_by_role('combobox',name='Optional stage',exact=True)
    optional.click();page.get_by_role('option',name='In review',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=Optional] button').textContent==='In review▾'")
    optional.click();page.get_by_role('option',name='Select…',exact=True).click()
    assert w.runtime.fx.evaluate('IsBlank(Optional.Selected)') is True
    page.get_by_role('button',name='Focus text',exact=True).click()
    page.wait_for_function("document.activeElement===document.querySelector('[data-control=Immediate] input')")
    assert immediate.evaluate('(e)=>document.activeElement===e')
    assert immediate.evaluate('(e)=>getComputedStyle(e).outlineWidth')=='3px'
    assert page.get_by_role('textbox',name='Fictional password',exact=True).get_attribute('type')=='password'
    assert page.get_by_role('textbox',name='Multiline notes',exact=True).evaluate('(e)=>e.spellcheck') is True
    title=page.get_by_role('textbox',name='Saved project title',exact=True)
    title.fill('Browser classic save')
    stage=page.get_by_role('combobox',name='Saved project stage',exact=True)
    stage.click();page.get_by_role('option',name='In review',exact=True).click()
    page.get_by_role('button',name='Save form',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=Summary]').textContent.includes('Saved Browser classic save')")
    assert w.runtime.store.rows('Drafts')[0]['Project Stage']=='Review'
    title.fill('');page.get_by_role('button',name='Save form',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=Summary]').textContent.includes('Save failed')")
    assert w.runtime.store.rows('Drafts')[0]['Project Title']=='Browser classic save'
    page.get_by_role('button',name='Reset form',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=TitleInput] input').value==='Browser classic save'")
    page.get_by_role('button',name='Reset left',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=LeftPanel] input').value==='Alpha'")
    assert w.runtime.fx.evaluate('RightPanel.Current.Stage')=='Done'
    assert not w.runtime.diagnostics and not page.errors


def test_classic_checkbox_radio_keyboard_components_form_and_gallery(page,app,tmp_path):
    from powerapps_sim.fixtures import classic_selection_project
    w=app.extensions['workspace'];w.open(classic_selection_project(tmp_path/'classic-selection'))
    page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    page.get_by_role('checkbox',name='LeftPanel enabled',exact=True).press('Space')
    right=page.get_by_role('radiogroup',name='RightPanel stage',exact=True)
    right.get_by_role('radio',name='In review',exact=True).press('ArrowDown')
    page.get_by_text('Callbacks 2 · RightPanel captured · unsaved false',exact=True).wait_for()
    assert w.runtime.fx.evaluate('LeftPanel.Current.Enabled') is True
    assert w.runtime.fx.evaluate('RightPanel.Current.Stage')=='Done'
    focused=right.get_by_role('radio',name='Completed',exact=True)
    assert focused.evaluate('(e)=>document.activeElement===e')
    assert right.evaluate('(e)=>getComputedStyle(e).outlineWidth')=='4px'
    # Native label activation forwards an input click; count it once.
    right.get_by_text('Completed',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=RightPanel] input[type=radio]:checked').getAttribute('aria-label')==='Completed'")
    page.get_by_role('button',name='Refresh values',exact=True).click()
    assert len(w.runtime.component_state['ClassicSelection/RightPanel']['collections']['selects'])==2
    assert len(w.runtime.collections['history'])==2
    assert page.get_by_role('checkbox',name='Pointer only',exact=True).get_attribute('tabindex')=='-1'
    assert page.get_by_role('checkbox',name='Read only',exact=True).is_disabled()
    assert page.get_by_role('checkbox',name='Disabled',exact=True).is_disabled()
    page.get_by_role('checkbox',name='Saved enabled',exact=True).click()
    page.get_by_role('radiogroup',name='Saved stage',exact=True).get_by_role('radio',name='In review',exact=True).click()
    page.get_by_role('button',name='Save form',exact=True).click()
    page.get_by_text('Callbacks 2 · Saved · enabled false · Review · unsaved false',exact=True).wait_for()
    assert w.runtime.store.rows('Drafts')[0]['Is Enabled'] is False
    page.get_by_role('button',name='Clear stage',exact=True).click()
    page.get_by_role('button',name='Save form',exact=True).click()
    page.get_by_text('Callbacks 2 · Save failed · unsaved false',exact=True).wait_for()
    assert w.runtime.store.rows('Drafts')[0]['Project Stage']=='Review'
    page.get_by_role('button',name='Reset form',exact=True).click()
    page.get_by_role('checkbox',name='Fictional second draft enabled',exact=True).click()
    page.get_by_text('Callbacks 2 · Selected Fictional second draft · unsaved false',exact=True).wait_for()
    assert w.runtime.store.rows('Drafts')[1]['Is Enabled'] is True
    page.get_by_role('button',name='Reset left',exact=True).click()
    page.wait_for_function("!document.querySelector('[data-control=LeftPanel] input[type=checkbox]').checked")
    assert w.runtime.fx.evaluate('RightPanel.Current.Stage')=='Done'
    assert not w.runtime.diagnostics and not page.errors


def test_classic_scalar_keyboard_calendar_confirmation_and_mapped_form(page,app,tmp_path):
    from powerapps_sim.fixtures import classic_scalars_project
    w=app.extensions['workspace'];w.open(classic_scalars_project(tmp_path/'classic-scalars'));page.reload()
    for name in ('Source','Structure','Inspector'):page.get_by_role('button',name=name,exact=True).click()
    page.get_by_role('switch',name='LeftPanel enabled',exact=True).check()
    page.get_by_text('Callbacks 1 · LeftPanel captured · unsaved false',exact=True).wait_for()
    amount=page.get_by_role('slider',name='LeftPanel amount',exact=True);amount.press('ArrowRight')
    page.get_by_text('Callbacks 2 · LeftPanel captured · unsaved false',exact=True).wait_for()
    assert amount.evaluate('(e)=>document.activeElement===e')
    assert amount.evaluate('(e)=>getComputedStyle(e.parentElement).outlineWidth')=='4px'
    page.get_by_role('button',name='Open calendar RightPanel date',exact=True).click()
    page.get_by_role('gridcell',name='Thursday, February 5, 2026',exact=True).click()
    assert page.get_by_role('textbox',name='RightPanel date',exact=True).input_value()=='10/02/2026'
    page.get_by_role('button',name='Cancel',exact=True).click()
    assert len(w.runtime.collections['history'])==2
    page.get_by_role('button',name='Open calendar RightPanel date',exact=True).click()
    page.get_by_role('gridcell',name='Thursday, February 5, 2026',exact=True).click()
    page.get_by_role('button',name='OK',exact=True).click()
    page.get_by_text('Callbacks 3 · RightPanel captured · unsaved false',exact=True).wait_for()
    day=page.get_by_role('textbox',name='LeftPanel date',exact=True);day.fill('31/02/2026');day.press('Tab')
    page.wait_for_function("document.querySelector('[aria-label=\"LeftPanel date\"]').getAttribute('aria-invalid')==='true'")
    assert day.input_value()=='31/02/2026'
    page.get_by_role('button',name='Reset left',exact=True).click()
    page.wait_for_function("document.querySelector('[aria-label=\"LeftPanel date\"]').value==='15/01/2026'")
    page.get_by_role('switch',name='Saved enabled',exact=True).uncheck()
    saved=page.get_by_role('textbox',name='Saved date',exact=True);saved.fill('05/04/2026');saved.press('Tab')
    page.get_by_role('button',name='Save form',exact=True).click()
    page.get_by_text('Callbacks 3 · Saved · unsaved false',exact=True).wait_for()
    assert w.runtime.store.rows('Drafts')[0]['Is Enabled'] is False
    assert w.runtime.store.rows('Drafts')[0]['Target Date']=='2026-04-05'
    assert page.get_by_role('slider',name='Read only amount',exact=True).is_disabled()
    assert not w.runtime.diagnostics and not page.errors


def test_math_component_reactivity_persistence_and_wide_collection(page,app,tmp_path):
    from powerapps_sim.fixtures import math_project
    w=app.extensions['workspace'];w.open(math_project(tmp_path/'math'));page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    area=page.get_by_role('spinbutton',name='LeftPanel area',exact=True)
    area.fill('36');area.press('Tab')
    page.get_by_text('Radius 3.3851 · estimate 12',exact=True).wait_for()
    assert w.runtime.fx.evaluate('RightPanel.Current.Estimate')==15
    angle=page.get_by_role('slider',name='LeftPanel angle',exact=True)
    angle.press('End')
    page.get_by_text('X -50 · Y 0',exact=True).wait_for()
    assert angle.evaluate('(e)=>document.activeElement===e')
    assert len(w.runtime.collections['history'])==2
    page.get_by_role('button',name='Save left',exact=True).click()
    page.get_by_text('Saved area 36 · angle 180 · estimate 12',exact=True).wait_for()
    assert w.runtime.store.rows('Measurements')[0]['Area']==36
    page.get_by_role('button',name='Build table',exact=True).click()
    page.get_by_role('button',name='Error cells',exact=True).click()
    page.get_by_text('Projection rows 13 · error rows 4',exact=True).wait_for()
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Collections',exact=True).click()
    page.get_by_role('button',name='results · 13 App',exact=True).click()
    table=page.locator('[aria-label="results collection"]')
    assert table.locator('th').count()==20
    assert table.evaluate('(e)=>e.scrollWidth>e.clientWidth')
    table.hover();page.mouse.wheel(2000,0)
    page.wait_for_function('document.querySelector("[aria-label=\\"results collection\\"]").scrollLeft>0')
    page.get_by_role('button',name='errorCells · 4 App',exact=True).click()
    error_table=page.locator('[aria-label="errorCells collection"]')
    assert 'Error' in error_table.inner_text() and 'Blank' in error_table.inner_text()
    assert w.runtime.collections['errorCells'][1]['Root'].kind=='Numeric'
    assert not w.runtime.diagnostics and not page.errors


def test_text_table_components_live_input_callbacks_and_persisted_output(page,app,tmp_path):
    from powerapps_sim.fixtures import text_tables_project
    w=app.extensions['workspace'];w.open(text_tables_project(tmp_path/'text-tables'));page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    left=page.get_by_role('textbox',name='LeftPanel title',exact=True)
    left.fill('River survey')
    page.get_by_text('Normalized: River_survey',exact=True).wait_for()
    assert left.evaluate('(e)=>document.activeElement===e')
    assert len(w.runtime.collections['history'])==0
    left.press('Tab')
    page.get_by_text('Callbacks 1 · LeftPanel captured',exact=True).wait_for()
    assert w.runtime.fx.evaluate('RightPanel.Current.Raw')=='Étude rivière'
    match=page.get_by_role('textbox',name='RightPanel match',exact=True)
    match.fill('è');match.press('Tab')
    replacement=page.get_by_role('textbox',name='RightPanel replacement',exact=True)
    replacement.fill('e');replacement.press('Tab')
    page.get_by_text('Normalized: Étude riviere',exact=True).wait_for()
    page.get_by_role('button',name='Save left',exact=True).click()
    page.get_by_text('Saved: River_survey',exact=True).wait_for()
    assert w.runtime.store.rows('Titles')[0]['Display Label']=='LeftPanel: Riv / vey'
    page.get_by_role('button',name='Build table',exact=True).click()
    page.get_by_role('button',name='Error cells',exact=True).click()
    page.get_by_text('Projection rows 3 · paired rows 3 · error rows 3',exact=True).wait_for()
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Collections',exact=True).click()
    page.get_by_role('button',name='results · 3 App',exact=True).click()
    table=page.locator('[aria-label="results collection"]')
    assert table.locator('th').count()==20
    assert table.evaluate('(e)=>e.scrollWidth>e.clientWidth')
    assert w.runtime.collections['errorCells'][1]['Value'].kind=='InvalidArgument'
    assert not w.runtime.diagnostics and not page.errors


def test_calendar_tables_keep_selected_collection_visible_and_preserve_scroll(page,app,tmp_path):
    from powerapps_sim.fixtures import calendar_tables_project
    page.set_viewport_size({'width':1280,'height':720})
    w=app.extensions['workspace'];w.open(calendar_tables_project(tmp_path/'calendar-tables'));page.reload()
    for name in ('Source','Structure','Inspector'):
        page.get_by_role('button',name=name,exact=True).click()
    page.get_by_role('button',name='Build weeks',exact=True).click()
    page.get_by_role('button',name='Error cells',exact=True).click()
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Collections',exact=True).click()
    page.get_by_role('button',name='results · 14 App',exact=True).click()
    table=page.locator('[aria-label="results collection"]')
    assert table.locator('th').count()==20
    assert table.evaluate('(e)=>e.scrollWidth>e.clientWidth')
    assert table.bounding_box()['y']>=page.locator('#inspector').bounding_box()['y']
    assert page.locator('#inspector').evaluate('(e)=>e.scrollTop')==0
    assert page.locator('.collection-list').evaluate('(e)=>e.scrollTop')>0
    table.hover();page.mouse.wheel(1500,0)
    page.wait_for_function('document.querySelector("[aria-label=\\"results collection\\"]").scrollLeft>0')
    before=table.evaluate('(e)=>e.scrollLeft')
    sidebar=page.locator('.collection-list').evaluate('(e)=>e.scrollTop')
    date=page.get_by_role('textbox',name='LeftPanel date',exact=True)
    date.fill('2021-01-03');date.press('Tab')
    page.get_by_text('Weeks 53, 1, 1, 1',exact=True).wait_for()
    page.get_by_role('button',name='Refresh values',exact=True).click()
    assert table.evaluate('(e)=>e.scrollLeft')==before
    assert page.locator('.collection-list').evaluate('(e)=>e.scrollTop')==sidebar
    page.get_by_role('button',name='errors · 3 App',exact=True).click()
    errors=page.locator('[aria-label="errors collection"]')
    assert 'Cannot parse date' in errors.inner_text() and 'Division by zero' in errors.inner_text()
    assert not w.runtime.diagnostics and not page.errors


def test_structured_nested_record_editor_precision_validation_and_json_drafts(page,app,tmp_path):
    from copy import deepcopy
    from powerapps_sim.fixtures import record_editor_project
    page.set_viewport_size({'width':1280,'height':720})
    w=app.extensions['workspace'];w.open(record_editor_project(tmp_path/'record-editor'));page.reload()
    original=deepcopy(w.runtime.store.rows('Drafts')[0])
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_text('Table · 2 rows',exact=True).click()
    table=page.get_by_label('Table Line Items',exact=True)
    page.wait_for_function("document.querySelector('[aria-label=\"Table Line Items\"] thead')?.children[0].children.length===21")
    assert table.locator('thead th').count()==21
    assert table.evaluate('(e)=>e.scrollWidth>e.clientWidth')
    page.get_by_role('button',name='Edit record 1',exact=True).click()
    lines=page.get_by_label('Line Items rows',exact=True)
    assert lines.evaluate('(e)=>e.scrollWidth>e.clientWidth')
    cost=page.get_by_label('Line Items row 1 Unit cost',exact=True)
    assert cost.input_value()=='9007199254740993.123456789'
    page.get_by_label('Line Items row 1 Quantity',exact=True).fill('5')
    page.get_by_label('Title',exact=True).fill('')
    page.get_by_role('button',name='Save record',exact=True).click()
    page.get_by_text('Title is required',exact=True).wait_for()
    assert page.get_by_label('Line Items row 1 Quantity',exact=True).input_value()=='5'
    assert w.runtime.store.rows('Drafts')[0]==original
    page.get_by_label('Title',exact=True).fill('Fictional structured edit')
    page.get_by_role('button',name='View Numeric Values JSON',exact=True).click()
    raw=page.get_by_label('Numeric Values JSON',exact=True);raw.fill('[1,')
    page.get_by_role('button',name='Edit Numeric Values rows',exact=True).click()
    assert raw.is_visible() and raw.input_value()=='[1,'
    raw.fill('{}')
    page.get_by_role('button',name='Edit Numeric Values rows',exact=True).click()
    page.get_by_text('Numeric Values expects an array',exact=True).wait_for()
    raw.fill('[1,2,null]')
    page.get_by_role('button',name='Edit Numeric Values rows',exact=True).click()
    page.get_by_role('button',name='Add Optional Tags row',exact=True).click()
    page.get_by_label('Optional Tags row 1 Value',exact=True).fill('Fictional tag')
    page.get_by_role('button',name='Empty Optional Tags',exact=True).click()
    page.get_by_role('button',name='Create Line Items row 2 Location record',exact=True).click()
    page.get_by_label('Line Items row 2 Location Site',exact=True).fill('Fictional woodland')
    page.get_by_role('button',name='View Settings JSON',exact=True).click()
    assert page.get_by_label('Settings JSON',exact=True).get_attribute('readonly') is not None
    page.get_by_role('button',name='Edit Settings fields',exact=True).click()
    page.get_by_role('button',name='Save record',exact=True).click()
    page.get_by_role('dialog').wait_for(state='hidden')
    saved=w.runtime.store.rows('Drafts')[0]
    assert saved['Line Items'][0]['Quantity']==5
    assert saved['Line Items'][0]['Cost']==original['Line Items'][0]['Cost']
    assert saved['Line Items'][0]['Legacy']==original['Line Items'][0]['Legacy']
    assert saved['Settings']==original['Settings'] and saved['Loose']==original['Loose']
    assert saved['Line Items'][1]['Location']=={'Site':'Fictional woodland'}
    assert saved['Optional Tags']==[] and saved['Numeric Values']==[1,2,None]
    page.get_by_role('button',name='Edit record 1',exact=True).click()
    page.get_by_label('Title',exact=True).fill('Fictional cancelled edit')
    page.get_by_role('button',name='Cancel',exact=True).click()
    assert w.runtime.store.rows('Drafts')[0]==saved and not page.errors


def test_json_enum_component_formats_failure_recovery_and_wide_values(page,app,tmp_path):
    import json
    from powerapps_sim.fixtures import json_enums_project
    w=app.extensions['workspace'];w.open(json_enums_project(tmp_path/'json-enums'));page.reload()
    for name in ('Source','Structure','Inspector'):page.get_by_role('button',name=name,exact=True).click()
    page.get_by_role('button',name='Encode LeftPanel',exact=True).click()
    page.get_by_role('combobox',name='LeftPanel format',exact=True).click()
    page.get_by_role('option',name='Flattened',exact=True).click()
    page.get_by_role('combobox',name='RightPanel format',exact=True).click()
    page.get_by_role('option',name='Indented flat',exact=True).click()
    amount=page.get_by_label('LeftPanel amount',exact=True);amount.fill('5');amount.press('Tab')
    page.get_by_role('button',name='Save left',exact=True).click()
    page.get_by_text('Callbacks 4 · Saved',exact=True).wait_for()
    saved=w.runtime.store.rows('Snapshots')
    assert len(saved)==1
    assert json.loads(saved[0]['Payload'])=={'Amount':5,'Flags':'_','Kind':23,'Order':'descending','Title':'Fictional LeftPanel','Unit':'months','Week':2,'Weeks':[1,2,3]}
    assert w.runtime.fx.evaluate('RightPanel.Current.Amount')==10
    page.get_by_role('combobox',name='LeftPanel format',exact=True).click()
    page.get_by_role('option',name='Conflicting media',exact=True).click()
    page.get_by_text('Invalid or conflicting JSONFormat flags',exact=True).wait_for()
    page.get_by_role('button',name='Save left',exact=True).click()
    page.get_by_text('Callbacks 5 · Encode a valid payload first',exact=True).wait_for()
    assert w.runtime.store.rows('Snapshots')==saved
    page.get_by_role('button',name='Reset left',exact=True).click()
    page.wait_for_function("document.querySelector('[aria-label=\"LeftPanel amount\"]').value==='1'")
    assert amount.input_value()=='1'
    assert w.runtime.fx.evaluate('CountRows(LeftPanel.History)')==0
    assert w.runtime.fx.evaluate('CountRows(RightPanel.History)')==1
    page.get_by_role('button',name='Encode LeftPanel',exact=True).click()
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('combobox',name='Simulate failure',exact=True).select_option('write')
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Save left',exact=True).click()
    page.get_by_text('Callbacks 6 · Save failed',exact=True).wait_for()
    assert w.runtime.store.rows('Snapshots')==saved
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('combobox',name='Simulate failure',exact=True).select_option('')
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Save left',exact=True).click()
    page.get_by_text('Callbacks 6 · Saved',exact=True).wait_for()
    assert len(w.runtime.store.rows('Snapshots'))==2
    page.get_by_role('button',name='Build table',exact=True).click()
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Collections',exact=True).click()
    page.get_by_role('button',name='results · 8 App',exact=True).click()
    table=page.get_by_label('results collection',exact=True)
    assert table.locator('thead th').count()==20
    assert table.evaluate('(e)=>e.scrollWidth>e.clientWidth')
    assert 'JSONFormat.IndentFour' in table.inner_text()
    table.get_by_text('Record · 1 fields',exact=True).first.click()
    page.get_by_text('JSONFormat · \"4_\"',exact=True).wait_for()
    assert not w.runtime.diagnostics and not page.errors


def test_regex_reactive_validation_captures_and_persistent_retry(page,app,tmp_path):
    from powerapps_sim.fixtures import regex_project
    w=app.extensions['workspace'];w.open(regex_project(tmp_path/'regex'));page.reload()
    for name in ('Source','Structure','Inspector'):page.get_by_role('button',name=name,exact=True).click()
    address=page.get_by_label('LeftPanel email',exact=True);address.fill('invalid')
    page.get_by_text('Invalid email',exact=True).wait_for()
    assert address.evaluate('(e)=>e===document.activeElement')
    page.get_by_role('button',name='Save left',exact=True).click()
    assert w.runtime.store.rows('Contacts')==[]
    page.get_by_role('button',name='Extract',exact=True).nth(0).click()
    page.get_by_text('Alpha · 12 · 1',exact=True).wait_for()
    page.get_by_label('RightPanel tokens',exact=True).fill('Gamma 56')
    page.get_by_role('button',name='Extract',exact=True).nth(1).click()
    page.get_by_text('Gamma · 56 · 1',exact=True).wait_for()
    assert w.runtime.fx.evaluate('CountRows(LeftPanel.Rows)')==2
    address.fill('sam@example.test');page.get_by_text('Valid email',exact=True).nth(0).wait_for()
    page.get_by_role('button',name='Save left',exact=True).click()
    page.get_by_label('App preview').get_by_text('Saved',exact=True).wait_for()
    assert len(w.runtime.store.rows('Contacts'))==1
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('combobox',name='Simulate failure',exact=True).select_option('write')
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Save left',exact=True).click()
    page.get_by_text('Save failed',exact=True).wait_for()
    assert len(w.runtime.store.rows('Contacts'))==1
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('combobox',name='Simulate failure',exact=True).select_option('')
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Save left',exact=True).click()
    page.get_by_label('App preview').get_by_text('Saved',exact=True).wait_for()
    assert len(w.runtime.store.rows('Contacts'))==2
    page.get_by_role('button',name='Build table',exact=True).click()
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Collections',exact=True).click()
    page.get_by_role('button',name='results · 2 App',exact=True).click()
    table=page.get_by_label('results collection',exact=True)
    assert table.locator('thead th').count()==20 and table.evaluate('(e)=>e.scrollWidth>e.clientWidth')
    table.get_by_text('Table · 2 rows',exact=True).first.click()
    assert not w.runtime.diagnostics and not page.errors


def test_interpolation_live_scopes_persistence_and_wide_inspection(page,app,tmp_path):
    from powerapps_sim.fixtures import interpolation_project
    w=app.extensions['workspace'];w.open(interpolation_project(tmp_path/'interpolation'));page.reload()
    for name in ('Source','Structure','Inspector'):page.get_by_role('button',name=name,exact=True).click()
    page.get_by_label('LeftPanel title',exact=True).fill('Fictional river')
    amount=page.get_by_label('LeftPanel quantity',exact=True);amount.fill('7.5')
    page.get_by_text('LeftPanel → Fictional river · 7.50 · {draft}',exact=True).wait_for()
    assert amount.evaluate('(e)=>e===document.activeElement')
    assert w.runtime.fx.evaluate('RightPanel.Quantity')==10
    page.get_by_role('button',name='Capture',exact=True).nth(0).click()
    page.get_by_role('button',name='Capture',exact=True).nth(1).click()
    page.get_by_text('Callbacks 2 · RightPanel · 1',exact=True).wait_for()
    page.get_by_role('button',name='Save left',exact=True).click()
    page.get_by_text('Callbacks 2 · Saved',exact=True).wait_for()
    saved=w.runtime.store.rows('Snapshots')
    assert saved[0]['Quantity']==7.5 and saved[0]['Preview']=='LeftPanel → Fictional river · 7.50 · {draft}'
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('combobox',name='Simulate failure',exact=True).select_option('write')
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Save left',exact=True).click()
    page.get_by_text('Callbacks 2 · Save failed',exact=True).wait_for()
    assert w.runtime.store.rows('Snapshots')==saved
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('combobox',name='Simulate failure',exact=True).select_option('')
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Save left',exact=True).click()
    page.get_by_text('Callbacks 2 · Saved',exact=True).wait_for()
    assert len(w.runtime.store.rows('Snapshots'))==2
    page.get_by_role('button',name='Build table',exact=True).click()
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Collections',exact=True).click()
    page.get_by_role('button',name='results · 8 App',exact=True).click()
    table=page.get_by_label('results collection',exact=True)
    assert table.locator('thead th').count()==20 and table.evaluate('(e)=>e.scrollWidth>e.clientWidth')
    assert '{1}' in table.inner_text()
    table.get_by_text('Record · 1 fields',exact=True).first.click()
    assert not w.runtime.diagnostics and not page.errors


def test_portable_regex_backreferences_and_component_capture_tables(page,app,tmp_path):
    from powerapps_sim.fixtures import regex_groups_project
    w=app.extensions['workspace'];w.open(regex_groups_project(tmp_path/'portable-regex'));page.reload()
    for name in ('Source','Structure','Inspector'):page.get_by_role('button',name=name,exact=True).click()
    tokens=page.get_by_label('LeftPanel tokens',exact=True)
    tokens.fill('😀 Alpha Beta 12 Delta Delta 78')
    assert tokens.evaluate('(e)=>e===document.activeElement')
    page.get_by_role('button',name='Extract',exact=True).nth(0).click()
    page.get_by_text('Delta · 78 · 18',exact=True).wait_for()
    page.get_by_label('RightPanel tokens',exact=True).fill('Gamma Gamma 56')
    page.get_by_role('button',name='Extract',exact=True).nth(1).click()
    page.get_by_text('Gamma · 56 · 1',exact=True).wait_for()
    assert w.runtime.fx.evaluate('CountRows(LeftPanel.Rows)')==1
    page.get_by_role('button',name='Save left',exact=True).click()
    page.get_by_label('App preview').get_by_text('Saved',exact=True).wait_for()
    assert w.runtime.store.rows('Contacts')[0]['TokenCount']==1
    page.get_by_role('button',name='Build table',exact=True).click()
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Collections',exact=True).click()
    page.get_by_role('button',name='results · 1 App',exact=True).click()
    table=page.get_by_label('results collection',exact=True)
    assert table.locator('thead th').count()==20 and table.evaluate('(e)=>e.scrollWidth>e.clientWidth')
    table.get_by_text('Table · 2 rows',exact=True).first.click()
    assert not w.runtime.diagnostics and not page.errors


def test_portable_inline_flags_class_unions_and_editable_saved_captures(page,app,tmp_path):
    from powerapps_sim.fixtures import regex_syntax_project
    w=app.extensions['workspace'];w.open(regex_syntax_project(tmp_path/'regex-syntax'));page.reload()
    for name in ('Source','Structure','Inspector'):page.get_by_role('button',name=name,exact=True).click()
    tokens=page.get_by_label('LeftPanel tokens',exact=True)
    tokens.fill('Sigma/sIGMA#42 Tau/tAU#81')
    assert tokens.evaluate('(e)=>e===document.activeElement')
    page.get_by_role('button',name='Extract',exact=True).nth(0).click()
    page.get_by_text('Sigma · 42 · 1',exact=True).wait_for()
    page.get_by_text('Tau · 81 · 16',exact=True).wait_for()
    page.get_by_label('RightPanel tokens',exact=True).fill('Gamma/gAMMA#56')
    page.get_by_role('button',name='Extract',exact=True).nth(1).click()
    page.get_by_text('Gamma · 56 · 1',exact=True).wait_for()
    assert w.runtime.fx.evaluate('LeftPanel.Separators("# / ")') is True
    assert w.runtime.fx.evaluate('RightPanel.IsNumber("١٢")') is True
    page.get_by_role('button',name='Save left',exact=True).click()
    page.get_by_label('App preview').get_by_text('Saved',exact=True).wait_for()
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('button',name='Edit record 1',exact=True).click()
    page.get_by_role('textbox',name='Title',exact=True).fill('Fictional edited capture')
    page.get_by_role('spinbutton',name='TokenCount',exact=True).fill('3')
    page.get_by_role('button',name='Save record',exact=True).click()
    page.get_by_text('Fictional edited capture',exact=True).wait_for()
    assert w.runtime.store.rows('Contacts')[0]['TokenCount']==3
    page.get_by_role('button',name='Editor & preview',exact=True).click()
    page.get_by_role('button',name='Build table',exact=True).click()
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Collections',exact=True).click()
    page.get_by_role('button',name='results · 2 App',exact=True).click()
    table=page.get_by_label('results collection',exact=True)
    assert table.locator('thead th').count()==20 and table.evaluate('(e)=>e.scrollWidth>e.clientWidth')
    table.get_by_text('Table · 2 rows',exact=True).first.click()
    assert not w.runtime.diagnostics and not page.errors


def test_html_formatting_shadow_links_and_editable_saved_source(page,app,tmp_path):
    from powerapps_sim.fixtures import html_text_project
    w=app.extensions['workspace'];w.open(html_text_project(tmp_path/'html-browser'));page.reload()
    page.wait_for_selector('[data-control="LeftPanel"]')
    for name in ('Structure','Source','Inspector'):page.get_by_role('button',name=name,exact=True).click()
    title=page.get_by_role('textbox',name='LeftPanel title',exact=True);title.fill('Fictional <river> & forest')
    left=page.locator('[data-path="HtmlLab/LeftPanel/LivePreview"]')
    left.get_by_text('Fictional <river> & forest',exact=True).wait_for()
    assert title.evaluate('(e)=>document.activeElement===e')
    status=page.locator('[data-control="Status"]');assert status.text_content()=='Callbacks 0 · Ready'
    before=page.url;left.get_by_role('link',name='↑ Details',exact=True).click()
    assert page.url==before and status.text_content()=='Callbacks 0 · Ready'
    left.get_by_role('link',name='↑ Details',exact=True).press('Enter')
    assert status.text_content()=='Callbacks 0 · Ready'
    left.get_by_text('Fictional <river> & forest',exact=True).click()
    page.wait_for_function("document.querySelector('[data-control=Status]').textContent.includes('Callbacks 1')")
    assert len(w.runtime.fx.evaluate('RightPanel.History'))==0
    page.get_by_role('button',name='Save left',exact=True).click()
    page.evaluate('()=>requestQueue')
    assert w.runtime.store.rows('Snapshots')[0]['Title']=='Fictional <river> & forest'
    page.get_by_role('button',name='Local data',exact=True).click()
    page.get_by_role('button',name='Edit record 1',exact=True).click()
    page.get_by_label('Title',exact=True).fill('Fictional saved HTML')
    page.get_by_role('button',name='Save record',exact=True).click()
    page.get_by_role('dialog').wait_for(state='hidden')
    assert w.runtime.store.rows('Snapshots')[0]['Title']=='Fictional saved HTML'
    assert '&lt;river&gt;' in w.runtime.store.rows('Snapshots')[0]['Preview']
    assert not w.runtime.diagnostics


def test_rich_text_native_formatting_reset_component_and_form_save(page,app,tmp_path):
    from powerapps_sim.fixtures import rich_text_project
    w=app.extensions['workspace'];w.open(rich_text_project(tmp_path/'rich-browser'));page.reload()
    page.wait_for_selector('iframe[title="LeftPanel notes"]')
    for name in ('Structure','Source','Inspector'):page.get_by_role('button',name=name,exact=True).click()
    body=page.frame_locator('iframe[title="LeftPanel notes"]').get_by_role('textbox',name='LeftPanel notes',exact=True)
    def action_event(action):
        with page.expect_response(lambda res:res.url.endswith('/api/event') and res.request.method=='POST'):
            action()
        page.evaluate('()=>requestQueue')
    action_event(lambda:body.fill('Fictional rich memo'));body.press('ControlOrMeta+A')
    action_event(lambda:page.get_by_role('button',name='Bold LeftPanel notes',exact=True).click())
    page.wait_for_function("document.querySelector('[data-control=Captures]').textContent.includes('2 changes')")
    assert 'font-weight:bold' in w.runtime.fx.evaluate('LeftPanel.Html')
    assert w.runtime.fx.evaluate('RightPanel.Changes')==0
    assert body.evaluate('(e)=>e.ownerDocument.activeElement===e')
    action_event(lambda:page.get_by_role('button',name='Underline LeftPanel notes',exact=True).click())
    assert 'text-decoration-line:underline' in w.runtime.fx.evaluate('LeftPanel.Html')
    action_event(lambda:page.get_by_role('button',name='Undo LeftPanel notes',exact=True).click())
    assert 'text-decoration-line:underline' not in body.inner_html()
    action_event(lambda:page.get_by_role('button',name='Redo LeftPanel notes',exact=True).click())
    assert 'text-decoration-line: underline' in body.inner_html()
    action_event(lambda:page.get_by_role('button',name='Capture',exact=True).first.click())
    assert len(w.runtime.fx.evaluate('LeftPanel.History'))==1
    action_event(lambda:page.get_by_role('button',name='Reset left',exact=True).click())
    assert w.runtime.fx.evaluate('LeftPanel.Plain')=='Fictional river memo'
    assert w.runtime.fx.evaluate('LeftPanel.Changes')==0
    action_event(lambda:page.get_by_role('button',name='Lock / unlock right',exact=True).click())
    assert not page.get_by_role('button',name='Bold RightPanel notes',exact=True).is_enabled()
    action_event(lambda:page.get_by_role('button',name='Lock / unlock right',exact=True).click())
    draft=page.frame_locator('iframe[title="Draft body"]').get_by_role('textbox',name='Draft body',exact=True)
    action_event(lambda:draft.fill('Fictional saved body'));draft.press('ControlOrMeta+A')
    action_event(lambda:page.get_by_role('button',name='Italic Draft body',exact=True).click())
    expected=w.runtime.fx.evaluate('MemoForm.Updates.Body');assert 'font-style:italic' in expected
    action_event(lambda:page.get_by_role('button',name='Save draft',exact=True).click())
    assert w.runtime.store.rows('Memos')[0]['Body']==expected and not w.runtime.fx.evaluate('MemoForm.Unsaved')
    action_event(lambda:page.get_by_role('button',name='View draft',exact=True).click())
    assert draft.get_attribute('contenteditable')=='false'
    assert not page.get_by_role('button',name='Bold Draft body',exact=True).is_enabled()
    action_event(lambda:page.get_by_role('button',name='Edit draft',exact=True).click())
    action_event(lambda:page.get_by_role('button',name='Build table',exact=True).click())
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Collections',exact=True).click()
    page.get_by_role('button',name='results · 8 App',exact=True).click()
    table=page.get_by_label('results collection',exact=True)
    assert table.locator('thead th').count()==20 and table.evaluate('(e)=>e.scrollWidth>e.clientWidth')
    table.get_by_text('Record · 2 fields',exact=True).first.click()
    assert not w.runtime.diagnostics and not page.errors


def test_timer_clock_stepping_playback_and_live_collections(page,app,tmp_path):
    from powerapps_sim.fixtures import timers_project
    w=app.extensions['workspace'];w.open(timers_project(tmp_path/'timer-browser'));page.reload()
    page.get_by_role('button',name='Pause time',exact=True).wait_for()
    page.get_by_role('button',name='Pause time',exact=True).click()
    for name in ('Structure','Source','Inspector'):page.get_by_role('button',name=name,exact=True).click()
    def event(action,route='/api/event'):
        with page.expect_response(lambda res:res.url.endswith(route) and res.request.method=='POST'):action()
        page.evaluate('()=>requestQueue')
    event(lambda:page.get_by_role('button',name='Start Left',exact=True).click())
    event(lambda:page.get_by_role('button',name='Advance 1s',exact=True).click(),'/api/time/advance')
    assert w.runtime.fx.evaluate('LeftPulse.Cycles')==1 and w.runtime.fx.evaluate('RightPulse.Cycles')==0
    assert len(w.runtime.store.rows('Ticks'))==1
    event(lambda:page.get_by_role('button',name='Start Right',exact=True).click())
    event(lambda:page.get_by_role('button',name='Advance 1s',exact=True).click(),'/api/time/advance')
    assert w.runtime.fx.evaluate('LeftPulse.Cycles')==2 and w.runtime.fx.evaluate('RightPulse.Elapsed')==1000
    event(lambda:page.get_by_role('button',name='Start background',exact=True).click())
    event(lambda:page.get_by_role('button',name='Review screen',exact=True).click())
    event(lambda:page.get_by_role('button',name='Advance 1s',exact=True).click(),'/api/time/advance')
    assert w.runtime.fx.evaluate('reviews')==1 and w.runtime.fx.evaluate('fgEnds')==0
    event(lambda:page.get_by_role('button',name='Return',exact=True).click())
    event(lambda:page.get_by_role('button',name='Build table',exact=True).click())
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Collections',exact=True).click()
    page.get_by_role('button',name='results · 8 App',exact=True).click()
    table=page.get_by_label('results collection',exact=True)
    assert table.locator('thead th').count()==20 and table.evaluate('(e)=>e.scrollWidth>e.clientWidth')
    table.get_by_text('Record · 2 fields',exact=True).first.click()
    assert table.locator('details[open]').count()==1
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Source',exact=True).click()
    source=page.get_by_role('textbox',name='YAML or Power Fx source',exact=True)
    page.get_by_role('button',name='Play time',exact=True).click()
    source.focus();source.press('ArrowRight');position=source.evaluate('(e)=>e.selectionStart')
    page.wait_for_function("document.querySelector('[data-control=BackgroundState]').textContent.includes('Background 1')")
    assert source.evaluate('(e)=>document.activeElement===e') and source.evaluate('(e)=>e.selectionStart')==position
    page.get_by_role('button',name='Pause time',exact=True).click()
    assert not w.runtime.diagnostics and not page.errors


def test_classic_combobox_fields_tags_components_and_form(page,app,tmp_path):
    from powerapps_sim.fixtures import classic_combo_project
    w=app.extensions['workspace'];w.open(classic_combo_project(tmp_path/'classic-combo-browser'));page.reload()
    page.get_by_role('combobox',name='Left picker',exact=True).wait_for()
    for name in ('Structure','Source','Inspector'):page.get_by_role('button',name=name,exact=True).click()
    def event(action):
        with page.expect_response(lambda res:res.url.endswith('/api/event') and res.request.method=='POST'):action()
        page.evaluate('()=>requestQueue')
    event(lambda:page.get_by_role('combobox',name='Left picker',exact=True).fill('casey@example'))
    page.get_by_role('option').filter(has_text='Fictional Casey Martin').wait_for()
    event(lambda:page.get_by_role('option').filter(has_text='Fictional Casey Martin').click())
    assert w.runtime.fx.evaluate('LeftPicker.Latest.ID')==2
    assert w.runtime.fx.evaluate('RightPicker.Latest.ID')==4
    event(lambda:page.get_by_role('combobox',name='Left picker',exact=True).fill('camille'))
    page.get_by_role('button',name='Navigate Fictional Camille Roy',exact=True).wait_for()
    event(lambda:page.get_by_role('button',name='Navigate Fictional Camille Roy',exact=True).click())
    assert w.runtime.globals['navigated']=='Fictional Camille Roy'
    assert len(w.runtime.collections['events'])==1
    page.get_by_role('combobox',name='Left picker',exact=True).press('Escape')
    event(lambda:page.get_by_role('button',name='Remove Fictional Casey Martin',exact=True).click())
    assert w.runtime.fx.evaluate('LeftPicker.Latest.ID')==1
    event(lambda:page.get_by_role('button',name='Reset left',exact=True).click())
    event(lambda:page.get_by_role('combobox',name='Draft owners',exact=True).fill('camille@example'))
    page.get_by_role('option').filter(has_text='Fictional Camille Roy').wait_for()
    event(lambda:page.get_by_role('combobox',name='Draft owners',exact=True).press('Enter'))
    page.get_by_role('combobox',name='Draft owners',exact=True).press('Escape')
    event(lambda:page.get_by_role('button',name='Save draft',exact=True).click())
    assert [v['ID'] for v in w.runtime.store.rows('Drafts')[0]['Owners']]==[1,3]
    event(lambda:page.get_by_role('button',name='Build table',exact=True).click())
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Collections',exact=True).click()
    page.get_by_role('button',name='results · 8 App',exact=True).click()
    table=page.get_by_label('results collection',exact=True)
    assert table.locator('th').count()==20
    assert table.evaluate('(e)=>e.scrollWidth>e.clientWidth')


def test_listbox_keyboard_components_form_and_wide_table(page,app,tmp_path):
    from powerapps_sim.fixtures import listbox_project
    w=app.extensions['workspace'];w.open(listbox_project(tmp_path/'listbox-browser'));page.reload()
    left=page.get_by_role('listbox',name='Left topics',exact=True)
    left.wait_for()
    for name in ('Structure','Source','Inspector'):page.get_by_role('button',name=name,exact=True).click()
    def event(action):
        with page.expect_response(lambda res:res.url.endswith('/api/event') and res.request.method=='POST') as response:action()
        assert response.value.status==200
        page.evaluate('()=>requestQueue')
    event(lambda:left.get_by_role('option',name='Fictional Transit',exact=True).click())
    event(lambda:left.press('Shift+ArrowDown'))
    assert [v['ID'] for v in w.runtime.fx.evaluate('LeftPicker.Chosen')]==[3,4]
    event(lambda:left.press('Control+a'))
    assert len(w.runtime.fx.evaluate('LeftPicker.Chosen'))==8
    left.press('End');event(lambda:left.press('Space'))
    assert len(w.runtime.fx.evaluate('LeftPicker.Chosen'))==7
    assert left.evaluate('(e)=>document.activeElement===e && e.scrollTop>0')
    right=page.get_by_role('listbox',name='Right topics',exact=True)
    event(lambda:right.get_by_role('option',name='Fictional Water',exact=True).click())
    event(lambda:page.get_by_role('button',name='Reset left',exact=True).click())
    assert w.runtime.fx.evaluate('LeftPicker.Latest.ID')==1 and w.runtime.fx.evaluate('RightPicker.Latest.ID')==5
    assert w.runtime.fx.evaluate('LeftPicker.Touches')==0
    event(lambda:page.get_by_role('listbox',name='Single topic',exact=True).press('ArrowDown'))
    assert w.runtime.fx.evaluate('Single.Selected.ID')==2
    event(lambda:page.get_by_role('textbox',name='Draft title',exact=True).fill('Fictional browser draft'))
    event(lambda:page.get_by_role('listbox',name='Draft topic',exact=True).get_by_role('option',name='Fictional Transit',exact=True).click())
    w.runtime.store.failures['Drafts']='write'
    event(lambda:page.get_by_role('button',name='Save draft',exact=True).click())
    assert w.runtime.fx.evaluate('DraftForm.Unsaved') and w.runtime.store.rows('Drafts')[0]['Topic']['ID']==1
    w.runtime.store.failures.clear()
    event(lambda:page.get_by_role('button',name='Save draft',exact=True).click())
    assert w.runtime.store.rows('Drafts')[0]['Topic']['ID']==3 and not w.runtime.fx.evaluate('DraftForm.Unsaved')
    event(lambda:page.get_by_role('button',name='Build table',exact=True).click())
    page.get_by_role('button',name='Inspector',exact=True).click()
    page.get_by_role('button',name='Collections',exact=True).click()
    page.get_by_role('button',name='results · 8 App',exact=True).click()
    table=page.get_by_label('results collection',exact=True)
    assert table.locator('thead th').count()==20 and table.evaluate('(e)=>e.scrollWidth>e.clientWidth')
    table.get_by_text('Record · 2 fields',exact=True).first.click()
    assert table.locator('details[open]').count()==1
    assert not w.runtime.diagnostics and not page.errors


def test_form_card_bounds_reflow_autoheight_and_retained_input(page,app,tmp_path):
    from powerapps_sim.fixtures import form_layout_project
    w=app.extensions['workspace'];w.open(form_layout_project(tmp_path/'form-layout-browser'));page.reload()
    page.get_by_role('textbox',name='Draft title',exact=True).wait_for()
    for name in ('Structure','Source','Inspector'):page.get_by_role('button',name=name,exact=True).click()
    def event(action):
        with page.expect_response(lambda res:res.url.endswith('/api/event') and res.request.method=='POST') as response:action()
        assert response.value.status==200
        page.evaluate('()=>requestQueue')
    def rectangle(name):return page.locator('[data-control='+name+']').evaluate('(e)=>({x:e.offsetLeft,y:e.offsetTop,width:e.offsetWidth,height:e.offsetHeight})')
    assert rectangle('TitleCard')['x']==0 and rectangle('AmountCard')['x']==280
    assert rectangle('AmountCard')['width']==380 and rectangle('TitleCard')['height']==120
    # Native Label defaults retain five pixels of padding above and below
    # empty text. Validation adds text height and grows the whole card row.
    assert rectangle('CardError')['height']==10
    event(lambda:page.get_by_role('switch',name='Fit title',exact=True).click())
    event(lambda:page.get_by_role('switch',name='Show extra',exact=True).click())
    assert rectangle('TitleCard')['width']==450 and rectangle('AmountCard')['width']==450
    event(lambda:page.get_by_role('textbox',name='Draft title',exact=True).fill('Fictional reflow edit'))
    assert page.get_by_role('textbox',name='Draft title',exact=True).evaluate('(e)=>document.activeElement===e')
    event(lambda:page.get_by_role('button',name='Resize form',exact=True).click())
    assert rectangle('TitleCard')['width']==540 and rectangle('AmountCard')['y']==95
    assert page.get_by_role('textbox',name='Draft title',exact=True).input_value()=='Fictional reflow edit'
    assert page.locator('[data-control=DraftForm]').evaluate('(e)=>e.scrollHeight>e.clientHeight')
    event(lambda:page.get_by_role('button',name='Save draft',exact=True).click())
    assert w.runtime.store.rows('Drafts')[0]['Title']=='Fictional reflow edit'
    event(lambda:page.get_by_role('textbox',name='Draft title',exact=True).fill(''))
    event(lambda:page.get_by_role('button',name='Save draft',exact=True).click())
    assert rectangle('CardError')['height']>0 and rectangle('TitleCard')['height']>95
    event(lambda:page.get_by_role('button',name='Reset draft',exact=True).click())
    assert rectangle('CardError')['height']==10 and rectangle('TitleCard')['height']==95
    assert not w.runtime.diagnostics and not page.errors


def test_data_table_selection_resize_scroll_focus_and_form_edits(page,app,tmp_path):
    from powerapps_sim.fixtures import data_table_project
    w=app.extensions['workspace'];w.open(data_table_project(tmp_path/'data-table-browser'));page.reload()
    page.get_by_role('grid',name='Fictional drafts',exact=True).wait_for()
    for name in ('Structure','Source','Inspector'):page.get_by_role('button',name=name,exact=True).click()
    def event(action):
        with page.expect_response(lambda res:res.url.endswith('/api/event') and res.request.method=='POST') as response:action()
        assert response.value.ok
        page.evaluate('()=>requestQueue')
    event(lambda:page.get_by_role('button',name='Fictional draft 5',exact=True).click())
    page.get_by_role('textbox',name='Draft title',exact=True).wait_for()
    assert w.runtime.fx.evaluate('DraftTable.Selected.ID')==5
    assert w.runtime.collections['clicks']==[{'ID':5,'Kind':'Title'}]
    assert w.runtime.fx.evaluate('OtherTable.Selected.ID')==101
    event(lambda:page.get_by_role('textbox',name='Draft title',exact=True).fill('Fictional table edit'))
    amount=page.get_by_role('textbox',name='Draft amount',exact=True)
    event(lambda:amount.fill('42'));event(lambda:amount.press('Tab'))
    w.runtime.store.failures['Drafts']='write'
    event(lambda:page.get_by_role('button',name='Save draft',exact=True).click())
    assert w.runtime.fx.evaluate('DraftForm.Unsaved && DraftTable.Selected.Amount=50')
    w.runtime.store.failures.clear()
    event(lambda:page.get_by_role('button',name='Save draft',exact=True).click())
    assert w.runtime.fx.evaluate('DraftTable.Selected.Title="Fictional table edit" && DraftTable.Selected.Amount=42')
    resize=page.get_by_role('separator',name='Resize Draft',exact=True);resize.press('ArrowRight')
    assert resize.get_attribute('aria-valuenow')=='300'
    assert w.runtime.fx.evaluate('TitleColumn.Width')==280
    grid=page.get_by_role('grid',name='Fictional drafts',exact=True)
    event(lambda:grid.press('ArrowDown'));assert w.runtime.fx.evaluate('DraftTable.Selected.ID')==6
    assert grid.evaluate('(e)=>document.activeElement===e')
    scroller=page.locator('[data-control=DraftTable] > .fx-data-table');assert scroller.evaluate('(e)=>e.scrollWidth>e.clientWidth')
    scroller.hover();page.mouse.wheel(2500,120)
    page.wait_for_function('document.querySelector("[data-control=DraftTable] > .fx-data-table").scrollLeft>0')
    left=scroller.evaluate('(e)=>e.scrollLeft')
    page.get_by_role('button',name='Refresh values',exact=True).click()
    assert scroller.evaluate('(e)=>e.scrollLeft')==left
    assert resize.get_attribute('aria-valuenow')=='300'
    event(lambda:page.get_by_role('switch',name='First four rows',exact=True).check())
    assert w.runtime.fx.evaluate('DraftTable.Selected.ID')==1
    event(lambda:page.get_by_role('switch',name='Amount column',exact=True).uncheck())
    assert page.locator('[data-control=DraftTable] thead th').count()==19
    assert not w.runtime.diagnostics and not page.errors


def test_nested_gallery_aliases_component_callbacks_and_target_workflows(page,app,tmp_path):
    from powerapps_sim.fixtures import gallery_alias_project
    w=app.extensions['workspace'];w.open(gallery_alias_project(tmp_path/'gallery-alias-browser'));page.reload()
    left=page.locator('[data-control=LeftGrid]');right=page.locator('[data-control=RightGrid]')
    left.get_by_role('button',name='2/23 Fictional cell 2.3',exact=True).wait_for()
    for name in ('Structure','Source','Inspector'):page.get_by_role('button',name=name,exact=True).click()
    def event(action):
        with page.expect_response(lambda res:res.url.endswith('/api/event') and res.request.method=='POST') as response:action()
        assert response.value.ok
        page.evaluate('()=>requestQueue')
    event(lambda:left.get_by_role('button',name='2/23 Fictional cell 2.3',exact=True).click())
    assert w.runtime.fx.evaluate('LeftGrid.Last.Outer=2 && LeftGrid.Last.Inner=23 && RightGrid.Last.Outer=0')
    note=page.get_by_role('textbox',name='Right grid note 1/12',exact=True)
    note.fill('Fictional live alias note')
    event(lambda:note.press('Tab'))
    assert w.runtime.fx.evaluate('RightGrid.Last.Inner=12 && RightGrid.Last.Caption="Fictional live alias note"')
    assert w.runtime.fx.evaluate('LeftGrid.Last.Inner')==23
    note.press('Home')
    page.wait_for_timeout(600)  # Test polling only; native verification uses fresh observations.
    assert note.evaluate('(e)=>document.activeElement===e && e.selectionStart===0')
    title=page.get_by_role('textbox',name='Draft title',exact=True)
    title.fill('Fictional saved alias draft');event(lambda:title.press('Tab'))
    event(lambda:page.get_by_role('button',name='Save draft',exact=True).click())
    assert left.locator('[data-control=RankTitle]').first.inner_text()=='Fictional saved alias draft'
    assert right.locator('[data-control=RankTitle]').first.inner_text()=='Fictional saved alias draft'
    assert note.input_value()=='Fictional live alias note'
    event(lambda:page.get_by_role('button',name='Reset left',exact=True).click())
    assert w.runtime.fx.evaluate('CountRows(LeftGrid.History)=0 && CountRows(RightGrid.History)=1')
    before=w.ai.read_runtime()
    page.get_by_role('button',name='Workflows',exact=True).click()
    page.get_by_role('combobox',name='Workflow scenario',exact=True).select_option(label='Nested gallery aliases and component callbacks')
    with page.expect_response(lambda res:res.url.endswith('/api/workflows/run') and res.request.method=='POST') as response:
        page.get_by_role('button',name='Run isolated workflow',exact=True).click()
    report=response.value.json();assert report['status']=='passed' and len(report['steps'])==35 and not report['diagnostics']
    assert w.ai.read_runtime()==before
    assert page.get_by_text('AliasLab/LeftGrid · Index(Index(Ranks.AllItems,2).Files.AllItems,3).Pick',exact=True).count()==1
    assert not w.runtime.diagnostics and not page.errors


def test_modern_grid_search_sort_selection_forms_and_large_row_window(page,app,tmp_path):
    from powerapps_sim.fixtures import modern_grid_project
    w=app.extensions['workspace'];w.open(modern_grid_project(tmp_path/'modern-grid-browser'));page.reload()
    left=page.get_by_role('grid',name='Left drafts',exact=True)
    right=page.get_by_role('grid',name='Right drafts',exact=True)
    left.wait_for()
    for name in ('Structure','Source','Inspector'):page.get_by_role('button',name=name,exact=True).click()
    def event(action):
        with page.expect_response(lambda res:res.url.endswith('/api/event') and res.request.method=='POST') as response:action()
        assert response.value.ok
        page.evaluate('()=>requestQueue')
    event(lambda:left.get_by_role('gridcell',name='Fictional draft 5',exact=True).click())
    event(lambda:left.get_by_role('checkbox',name='Select row 7',exact=True).check())
    assert w.runtime.fx.evaluate('CountRows(LeftPanel.Selection)=2 && LeftPanel.Current.ID=7 && RightPanel.Current.ID=1')
    search=page.get_by_role('searchbox',name='Left drafts search',exact=True)
    event(lambda:search.fill('draft 1'))
    page.wait_for_function('document.querySelectorAll("[data-control=LeftPanel] .fx-modern-grid tbody tr").length===4')
    search.press('Home');page.wait_for_timeout(600)
    assert search.evaluate('(e)=>document.activeElement===e && e.selectionStart===0')
    event(lambda:left.get_by_role('button',name='Amount',exact=True).click())
    event(lambda:left.get_by_role('button',name='Amount',exact=True).click())
    page.wait_for_function('document.querySelector("[data-control=LeftPanel] .fx-modern-grid tbody tr").dataset.index==="11"')
    assert w.runtime.fx.evaluate('First(LeftPanel.Rows).ID')==1
    handle=left.get_by_role('separator',name='Resize Draft',exact=True);handle.press('ArrowRight')
    assert handle.get_attribute('aria-valuenow')=='260'
    page.get_by_role('button',name='Refresh values',exact=True).click()
    assert handle.get_attribute('aria-valuenow')=='260'
    assert page.locator('[data-control=LeftPanel] .fx-grid-scroll').evaluate('(e)=>e.scrollWidth>e.clientWidth')
    event(lambda:right.get_by_role('gridcell',name='Fictional draft 2',exact=True).click())
    title=page.get_by_role('textbox',name='Draft title',exact=True)
    event(lambda:title.fill('Fictional browser grid edit'));event(lambda:title.press('Tab'))
    w.runtime.store.failures['Drafts']='write'
    event(lambda:page.get_by_role('button',name='Save draft',exact=True).click())
    assert w.runtime.fx.evaluate('DraftForm.Unsaved && RightPanel.Current.Title="Fictional draft 2"')
    w.runtime.store.failures.clear()
    event(lambda:page.get_by_role('button',name='Save draft',exact=True).click())
    right.get_by_role('gridcell',name='Fictional browser grid edit',exact=True).wait_for()
    assert w.runtime.fx.evaluate('RightPanel.Current.Title="Fictional browser grid edit" && !DraftForm.Unsaved')
    event(lambda:page.get_by_role('button',name='Reset left',exact=True).click())
    assert w.runtime.fx.evaluate('LeftPanel.Query="" && LeftPanel.Current.ID=1 && RightPanel.Current.ID=2')
    event(lambda:page.get_by_role('button',name='Large grid',exact=True).click())
    large=page.get_by_role('grid',name='Large fictional grid',exact=True);large.wait_for()
    assert large.get_attribute('aria-rowcount')=='2106' and large.locator('tbody tr').count()<50
    event(lambda:large.press('End'))
    page.get_by_text('Selected row: 2105 ·',exact=True).wait_for()
    assert large.locator('tbody tr').count()<50
    event(lambda:page.get_by_role('searchbox',name='Large fictional grid search',exact=True).fill('row 2105'))
    page.wait_for_function('document.querySelectorAll("[data-control=BigGrid] .fx-modern-grid tbody tr").length===1')
    assert large.get_by_role('gridcell',name='Fictional row 2105',exact=True).count()==1
    assert not w.runtime.diagnostics and not page.errors


def test_modern_rating_keyboard_half_pointer_isolation_and_form_save(page,app,tmp_path):
    from powerapps_sim.fixtures import rating_project
    p=rating_project(tmp_path/'rating');w=app.extensions['workspace'];w.open(p)
    page.reload();left=page.get_by_role('slider',name='Left rating',exact=True);left.wait_for()
    for name in ('Structure','Source','Inspector'):page.get_by_role('button',name=name,exact=True).click()
    def event(action):
        with page.expect_response(lambda res:res.url.endswith('/api/event') and res.request.method=='POST') as response:action()
        assert response.value.ok
        page.evaluate('()=>requestQueue')
    event(lambda:left.press('ArrowRight'));assert w.runtime.fx.evaluate('LeftRating.Current=3 && RightRating.Current=2.5')
    page.get_by_role('button',name='Refresh values',exact=True).evaluate('(e)=>e.click()')
    page.evaluate('()=>requestQueue')
    assert left.evaluate('(e)=>document.activeElement===e')
    heart=left.locator('.fx-rating-item').nth(3);box=heart.bounding_box()
    event(lambda:page.mouse.click(box['x']+box['width']*.25,box['y']+box['height']*.5))
    assert w.runtime.fx.evaluate('LeftRating.Current=3.5 && CountRows(LeftRating.History)=2')
    event(lambda:page.get_by_role('slider',name='Right rating',exact=True).press('End'))
    event(lambda:page.get_by_role('button',name='Reset left',exact=True).click())
    assert w.runtime.fx.evaluate('LeftRating.Current=2.5 && RightRating.Current=5 && CountRows(LeftRating.History)=0')
    event(lambda:page.get_by_role('slider',name='Fictional feedback 2',exact=True).press('End'))
    assert w.runtime.store.rows('Feedback')[1]['Score']==5
    draft=page.get_by_role('slider',name='Draft score',exact=True)
    event(lambda:draft.press('End'));event(lambda:draft.press('ArrowLeft'))
    assert w.runtime.fx.evaluate('FeedbackForm.Unsaved && FeedbackForm.Updates.Score=4.5')
    w.runtime.store.failures['Feedback']='write'
    event(lambda:page.get_by_role('button',name='Save score',exact=True).click())
    assert w.runtime.fx.evaluate('FeedbackForm.Unsaved && FormScore.Value=4.5')
    w.runtime.store.failures.clear()
    event(lambda:page.get_by_role('button',name='Save score',exact=True).click())
    assert w.runtime.fx.evaluate('!FeedbackForm.Unsaved && FeedbackForm.LastSubmit.Score=4.5')
    assert not w.runtime.diagnostics and not page.errors

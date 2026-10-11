from pathlib import Path
import os
import pytest

from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project
from powerapps_sim.syntax import FxError


def test_reactive_filter_and_translation(runtime):
    runtime.event('Home/Page/Toolbar/Search', 'OnChange', 'Water')
    assert runtime.fx.evaluate('CountRows(ProjectRows)') == 1
    runtime.event('Home/Page/Toolbar/SwitchLanguage', 'OnSelect')
    assert runtime.fx.evaluate('T("title", [])') == 'Espace projets'
    runtime.fx.evaluate('Reset(Search)', Context(runtime, behavior=True))
    assert runtime.fx.evaluate('CountRows(ProjectRows)') == 3


def test_new_form_validation_success_and_persistence(runtime):
    runtime.event('Home/Page/Toolbar/NewProject', 'OnSelect')
    assert runtime.active_screen == 'Edit'
    form = runtime.global_refs['ProjectForm']
    runtime.event('Edit/SaveProject', 'OnSelect')
    assert form.property('Error')
    assert len(runtime.store.rows('Projects')) == 3
    runtime.event('Edit/ProjectForm/TitleCard/TitleInput', 'OnChange', 'Test draft')
    runtime.event('Edit/ProjectForm/AmountCard/AmountInput', 'OnChange', 500)
    assert form.property('Unsaved') is True
    runtime.event('Edit/SaveProject', 'OnSelect')
    assert runtime.active_screen == 'Home'
    assert form.property('LastSubmit')['Title'] == 'Test draft'
    assert form.property('Unsaved') is False
    new_runtime = Runtime(Project(runtime.project.root))
    assert len(new_runtime.store.rows('Projects')) == 4
    new_runtime.close()


def test_card_errors_are_set_on_submission_and_reset_without_losing_inputs(runtime):
    runtime.event('Home/Page/Toolbar/NewProject', 'OnSelect')
    card = runtime.global_refs['TitleCard']
    form = runtime.global_refs['ProjectForm']
    assert card.property('Error') == ''
    assert card.property('Valid') is False
    runtime.submit_form(form)
    assert card.property('Error') == 'Title is required'
    runtime.event('Edit/ProjectForm/TitleCard/TitleInput', 'OnChange', 'Valid title')
    assert card.property('Valid') is True
    runtime.submit_form(form)
    assert card.property('Error') == ''
    assert not form.property('Error')


def test_card_validation_uses_its_own_schema_and_ignores_unbound_cards(runtime):
    form = runtime.global_refs['ProjectForm']
    title = runtime.global_refs['TitleCard']
    title.control.properties['MaxLength'] = '=500'
    runtime.fx.evaluate('NewForm(ProjectForm)', Context(runtime, behavior=True))
    title.control.properties['Update'] = '="' + 'x' * 256 + '"'
    runtime.invalidate()
    assert title.property('Valid') is False  # Schema length is 255.
    assert 'maximum length' in title.validation_error()
    title.control.properties['DataField'] = '=""'
    runtime.invalidate()
    assert title.property('Valid') is True
    assert 'Title' not in form.property('Updates')


def test_edit_and_failed_save_retains_inputs(runtime):
    state = runtime.state()
    edit = next(ref for path, ref in runtime.refs.items() if path.endswith('/EditProject'))
    runtime.event(edit.path, 'OnSelect')
    runtime.event('Edit/ProjectForm/TitleCard/TitleInput', 'OnChange', 'Changed name')
    runtime.store.failures['Projects'] = 'write'
    runtime.event('Edit/SaveProject', 'OnSelect')
    assert runtime.active_screen == 'Edit'
    assert runtime.global_refs['TitleInput'].property('Text') == 'Changed name'
    assert 'Simulated write failure' in runtime.global_refs['ProjectForm'].property('Error')
    runtime.store.failures.clear()
    runtime.event('Edit/SaveProject', 'OnSelect')
    assert len(runtime.store.rows('Projects')) == 3
    assert any(row['Title'] == 'Changed name' for row in runtime.store.rows('Projects'))


def test_component_instances_are_isolated(runtime):
    home = runtime.refs['Home/Page/HomeHeader']
    edit = runtime.refs['Edit/EditHeader']
    assert home.children[0].scope['Header'] is home
    assert edit.children[0].scope['Header'] is edit
    runtime.event('Home/Page/Toolbar/NewProject', 'OnSelect')
    runtime.event('Edit/EditHeader/HomeButton', 'OnSelect')
    assert runtime.active_screen == 'Home'


def test_component_event_parameters(runtime):
    source = runtime.project.documents['Src/demo.pa.yaml']
    source = source.replace('OnHome:\n        PropertyKind: Event', 'OnHome:\n        Parameters:\n          - pageId:\n              DataType: Text\n        PropertyKind: Event')
    source = source.replace('=Header.OnHome()', '=Header.OnHome("Home")')
    source = source.replace('OnHome: =ResetForm(ProjectForm); Navigate(Home, ScreenTransition.None)', 'OnHome: =Set(clickedPage, pageId); Navigate(Home, ScreenTransition.None)')
    runtime.project.update_source('Src/demo.pa.yaml', source)
    other = Runtime(runtime.project)
    other.restart()
    other.event('Home/Page/Toolbar/NewProject', 'OnSelect')
    other.event('Edit/EditHeader/HomeButton', 'OnSelect')
    assert other.globals['clickedPage'] == 'Home'
    other.close()


def test_inspection_does_not_change_active_screen_or_navigation(runtime):
    runtime.preview_screen = 'Edit'
    assert runtime.state()['screen'] == 'Edit'
    assert runtime.active_screen == 'Home'
    assert runtime.history == []


def test_patch_refresh_and_queued_select(runtime):
    ctx = Context(runtime, behavior=True)
    runtime.fx.evaluate('Patch(Projects, Defaults(Projects), {Title: "Patched", Amount: 2, Status: {Value: "Draft"}}); Refresh(Projects)', ctx)
    assert len(runtime.store.rows('Projects')) == 4
    runtime.project.screens['Home'].properties['OnVisible'] = '=Select(SwitchLanguage)'
    runtime.restart()
    assert runtime.globals['varLanguage'] == 'fr'


def test_unknown_control_never_becomes_blank(runtime):
    with pytest.raises(FxError, match='Unknown identifier'):
        runtime.fx.evaluate('NonexistentControl.Text')


def test_explicit_input_properties_take_precedence_over_defaults(runtime):
    title = runtime.global_refs["TitleInput"]
    amount = runtime.global_refs["AmountInput"]
    title.control.properties["Text"] = '="Explicit text"'
    amount.control.properties["Value"] = '=123'
    runtime.invalidate()
    assert title.property("Text") == "Explicit text"
    assert amount.property("Value") == 123
    runtime.event('Home/Page/Toolbar/NewProject', 'OnSelect')
    runtime.event(title.path, 'OnChange', 'User value')
    assert title.property('Text') == 'User value'


def test_display_gate_errors_and_view_forms_disable_mutations(runtime):
    button = runtime.global_refs['NewProject']
    button.control.properties['DisplayMode'] = '=MissingControl.Enabled'
    runtime.invalidate()
    node = runtime.render(button)
    assert node['props']['DisplayMode'] == 'Disabled'
    with pytest.raises(FxError):
        runtime.event(button.path, 'OnSelect')
    assert runtime.active_screen == 'Home'
    runtime.fx.evaluate('ViewForm(ProjectForm)', Context(runtime, behavior=True))
    assert runtime.global_refs['ProjectForm'].property('DisplayMode') == 'View'
    runtime.event('Edit/ProjectForm/TitleCard/TitleInput', 'OnChange', 'Should not change')
    assert not runtime.global_refs['TitleInput'].state


def test_every_sample_screen_imports_and_renders(tmp_path):
    sample_path = os.environ.get("POWERAPPS_SAMPLE")
    if not sample_path:
        pytest.skip("Set POWERAPPS_SAMPLE to an optional local compatibility archive")
    sample = Path(sample_path)
    if not sample.is_file():
        pytest.skip("Local compatibility archive is unavailable")
    p = Project.import_archive(sample.read_bytes(), tmp_path / 'sample')
    r = Runtime(p)
    assert len(p.screens) == 15
    assert len(p.components) == 3
    assert len(r.store.definitions) == 10
    assert len(r.fx.definitions) >= 190
    assert not [d for d in r.bind_diagnostics if d['category'] == 'unsupported']
    r.restart()
    for name in p.screens:
        r.preview_screen = name
        assert r.state()['tree']['name'] == name
    assert any('frmFiscalYear' in d['message'] for d in r.diagnostics)
    r.close()

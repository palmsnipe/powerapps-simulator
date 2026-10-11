"""Reset edges and form events over an independent fictional list."""
from io import BytesIO
from zipfile import ZipFile

import pytest

from powerapps_sim.fixtures import forms_project
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime


@pytest.fixture
def forms(tmp_path):
    r = Runtime(forms_project(tmp_path / 'forms'))
    r.restart()
    r.state()
    assert not r.diagnostics
    yield r
    r.close()


def evaluate(r, formula):
    return r.fx.evaluate(formula, Context(r, behavior=True))


def change(r, value):
    r.event('Forms/DraftForm/TitleCard/TitleInput', 'OnChange', value)


def steps(r):
    return [row['Step'] for row in r.collections['trace']]


def test_pulse_resets_inputs_inside_form_before_next_chain_step(forms):
    r = forms
    change(r, 'edited')
    evaluate(r, 'Set(resetInputs, true); Set(resetInputs, false); Set(observed, TitleInput.Text)')
    assert r.globals['observed'] == 'Fictional bridge study'
    assert not r.global_refs['DraftForm'].property('Unsaved')
    assert steps(r) == ['start']  # Neither OnReset nor OnChange is fabricated.


def test_reset_property_reads_are_pure_and_repeated_true_is_not_an_edge(forms):
    r = forms
    change(r, 'first')
    evaluate(r, 'Set(resetInputs, true)')
    assert r.global_refs['TitleInput'].property('Text') == 'Fictional bridge study'
    change(r, 'second')
    r.state(); r.state()
    assert r.global_refs['TitleInput'].property('Reset') is True
    assert r.global_refs['TitleInput'].property('Text') == 'second'
    evaluate(r, 'Set(resetInputs, false); Set(resetInputs, true)')
    assert r.global_refs['TitleInput'].property('Text') == 'Fictional bridge study'


def test_button_pressed_resets_and_release_does_not_run_onselect(forms):
    r = forms
    change(r, 'edited')
    r.event('Forms/HeldReset', 'Pressed', True)
    assert r.global_refs['HeldReset'].property('Pressed') is True
    assert r.global_refs['TitleInput'].property('Text') == 'Fictional bridge study'
    r.global_refs['HeldReset'].control.properties['Visible'] = '=false'
    r.invalidate()
    r.event('Forms/HeldReset', 'Pressed', False)
    assert r.global_refs['HeldReset'].property('Pressed') is False
    assert steps(r) == ['start']
    with pytest.raises(ValueError):
        r.event('Forms/DraftForm/TitleCard/TitleInput', 'Pressed', True)


def test_resetform_runs_synchronously_after_new_to_edit_and_retains_lastsubmit(forms):
    r = forms
    form = r.global_refs['DraftForm']
    change(r, 'saved title')
    evaluate(r, 'SubmitForm(DraftForm)')
    submitted = form.property('LastSubmit')
    assert submitted['Title'] == 'saved title'
    evaluate(r, 'NewForm(DraftForm)')
    assert form.property('Mode') == 'New'
    assert form.property('LastSubmit') == submitted
    change(r, 'discarded')
    evaluate(r, 'Collect(trace, {Step: "before"}); ResetForm(DraftForm); Collect(trace, {Step: "after"})')
    assert steps(r)[-3:] == ['before', 'reset Edit / saved title', 'after']
    assert form.property('LastSubmit') == submitted
    assert form.property('Mode') == 'Edit'
    assert not form.property('Unsaved')


def test_view_reset_and_submit_have_no_effect_even_with_injected_failure(forms):
    r = forms
    form = r.global_refs['DraftForm']
    change(r, 'pending')
    evaluate(r, 'ViewForm(DraftForm)')
    before = dict(form.state)
    r.store.failures['Drafts'] = 'write'
    evaluate(r, 'ResetForm(DraftForm); SubmitForm(DraftForm)')
    assert form.state == before
    assert steps(r) == ['start']
    assert r.global_refs['TitleInput'].property('Text') == 'pending'
    assert form.property('Error') == ''
    evaluate(r, 'EditForm(DraftForm)')
    assert r.global_refs['TitleInput'].property('Text') == 'pending'


def test_failed_save_retains_edits_and_error_until_edit_or_reset(forms):
    r = forms
    form = r.global_refs['DraftForm']
    change(r, 'pending')
    r.store.failures['Drafts'] = 'write'
    evaluate(r, 'SubmitForm(DraftForm)')
    message = form.property('Error')
    assert 'Simulated write failure' in message
    assert form.property('LastSubmit') is None
    assert form.property('Unsaved')
    evaluate(r, 'ViewForm(DraftForm); NewForm(DraftForm)')
    assert form.property('Error') == message
    evaluate(r, 'ResetForm(DraftForm)')
    assert form.property('Error') == ''
    assert form.property('ErrorKind') == 0
    assert steps(r)[-1] == 'reset Edit / Fictional bridge study'


def test_edit_null_record_and_switch_record_after_submit(forms):
    r = forms
    form = r.global_refs['DraftForm']
    change(r, 'saved title')
    evaluate(r, 'SubmitForm(DraftForm)')
    last = form.property('LastSubmit')
    evaluate(r, 'Set(selectedId, 2)')
    assert form.property('Item')['ID'] == 2
    assert r.global_refs['TitleInput'].property('Text') == 'Fictional park survey'
    assert form.property('LastSubmit') == last
    assert not form.property('Unsaved')
    evaluate(r, 'Set(selectedId, 99)')
    assert form.property('Item') is None
    assert r.global_refs['TitleInput'].property('Text') == ''


def test_unsaved_false_when_user_restores_default_or_default_changes(forms):
    r = forms
    form = r.global_refs['DraftForm']
    change(r, 'changed')
    assert form.property('Unsaved')
    change(r, 'Fictional bridge study')
    assert not form.property('Unsaved')
    change(r, 'changed again')
    evaluate(r, 'Set(selectedId, 2)')
    assert not form.property('Unsaved')
    assert r.global_refs['TitleInput'].property('Text') == 'Fictional park survey'


def test_recursive_onreset_reports_cycle_without_hanging(forms):
    r = forms
    r.global_refs['DraftForm'].control.properties['OnReset'] = '=ResetForm(Self)'
    evaluate(r, 'ResetForm(DraftForm)')
    assert any(d['kind'] == 'Cycle' and d['member'] == 'DraftForm.OnReset' for d in r.diagnostics)
    assert not r.resetting


def test_bad_reset_property_is_local_diagnostic_and_can_recover(forms):
    r = forms
    ref = r.global_refs['TitleInput']
    ref.control.properties['Reset'] = '=1'
    r.invalidate()
    change(r, 'edited')
    evaluate(r, 'Set(resetInputs, true)')
    assert any(d['kind'] == 'Type' and d['member'] == 'TitleInput.Reset' for d in r.diagnostics)
    ref.control.properties['Reset'] = '=resetInputs'
    r.invalidate(); r.sync_reset_properties()
    assert ref.property('Text') == 'Fictional bridge study'


def test_successful_new_submit_changes_mode_and_exposes_lastsubmit_to_callback(forms):
    r = forms
    evaluate(r, 'NewForm(DraftForm)')
    change(r, 'Fictional third record')
    evaluate(r, 'SubmitForm(DraftForm)')
    form = r.global_refs['DraftForm']
    assert form.property('Mode') == 'Edit'
    assert form.property('LastSubmit')['ID'] == 3
    assert r.globals['selectedId'] == 3
    assert steps(r)[-1] == 'saved Fictional third record'
    assert len(r.store.rows('Drafts')) == 3
    assert not form.property('Unsaved')


def test_fixture_source_export_excludes_list_and_runtime_metadata(forms):
    r = forms
    with ZipFile(BytesIO(r.project.export())) as archive:
        assert 'Src/forms.pa.yaml' in archive.namelist()
        assert not any(name.endswith(('sqlite', 'json')) for name in archive.namelist())
        assert archive.read('Src/forms.pa.yaml').decode() == r.project.documents['Src/forms.pa.yaml']


@pytest.mark.parametrize('family,default,value_prop,edited,expected', [
    ('ModernTextInput@1.1.2', '"seed"', 'Text', 'edit', 'seed'),
    ('ModernNumberInput@1.1.2', '42', 'Value', 7, 42),
    ('ModernDatePicker@1.0.2', 'Date(2026, 1, 1)', 'SelectedDate', '2026-02-02', '2026-01-01'),
])
def test_reset_property_in_each_gallery_row(tmp_path, family, default, value_prop, edited, expected):
    from powerapps_sim.source import Project, dump_yaml
    p = Project(tmp_path / 'gallery')
    default_prop = 'DefaultDate' if value_prop == 'SelectedDate' else 'Default'
    p.update_source('Src/Home.pa.yaml', dump_yaml({'Screens': {'Home': {'Children': [
        {'Rows': {'Control': 'Gallery@2.15.0', 'Properties': {'Items': '=Table({ID: 1}, {ID: 2})'}, 'Children': [
            {'Input': {'Control': family, 'Properties': {default_prop: '='+default, 'Reset': '=Rows.Selected.ID = ThisItem.ID && pulse'}}}
        ]}},
        {'Pulse': {'Control': 'ModernButton@1.0.0', 'Properties': {'OnSelect': '=Set(pulse, true); Set(pulse, false)'}}}
    ]}}}))
    r = Runtime(p)
    try:
        r.restart(); r.state()
        inputs = [ref for ref in r.refs.values() if ref.name == 'Input']
        assert len(inputs) == 2
        for ref in inputs:
            r.event(ref.path, 'OnChange', edited)
        r.event('Home/Pulse', 'OnSelect')
        actual = inputs[0].property(value_prop)
        assert actual.isoformat() == expected if value_prop == 'SelectedDate' else actual == expected
        other = inputs[1].property(value_prop)
        assert other.isoformat() == edited if value_prop == 'SelectedDate' else other == edited
        assert not r.diagnostics
    finally:
        r.close()


def test_unsaved_selection_returns_to_original_record_and_empty_default(tmp_path):
    from powerapps_sim.source import Project, dump_yaml
    p = Project(tmp_path / 'selection')
    p.update_source('Src/Home.pa.yaml', dump_yaml({'Screens': {'Home': {'Children': [
        {'EditForm': {'Control': 'Form@2.4.4', 'Children': [
            {'Combo': {'Control': 'ModernCombobox@1.1.2', 'Properties': {'Items': '=Table({ID: 1}, {ID: 2})', 'DefaultSelectedItems': '=Table({ID: 1})', 'Reset': '=flag'}}},
            {'Toggle': {'Control': 'Toggle@1.1.5'}}
        ]}},
        {'ResetInputs': {'Control': 'ModernButton@1.0.0', 'Properties': {'OnSelect': '=Set(flag, true); Set(flag, false)'}}}
    ]}}}))
    r = Runtime(p)
    try:
        r.restart()
        form = r.global_refs['EditForm']
        r.event('Home/EditForm/Combo', 'OnChange', selection=[1])
        assert form.property('Unsaved')
        r.event('Home/EditForm/Combo', 'OnChange', selection=[0])
        assert not form.property('Unsaved')
        r.event('Home/EditForm/Combo', 'OnChange', selection=[1])
        r.event('Home/ResetInputs', 'OnSelect')
        assert not form.property('Unsaved')
        assert r.global_refs['Combo'].property('Selected')['ID'] == 1
    finally:
        r.close()

"""Validate's documented overloads, pure observations and local write constraints."""
from copy import deepcopy
from decimal import Decimal
import pytest
from powerapps_sim.source import Project, dump_yaml
from powerapps_sim.runtime import Runtime
from powerapps_sim.fx import Context
from powerapps_sim.binding import BindScope
from powerapps_sim.authoring import data_revision, revision
from powerapps_sim.syntax import FxError


@pytest.fixture
def r(tmp_path):
    p = Project(tmp_path / 'p')
    p.update_source('Src/app.pa.yaml', dump_yaml({'Screens': {'Home': {}}}))
    r = Runtime(p)
    r.store.add_list('Scores', {'fields': {
        'ID': {'type': 'integer', 'x-ms-permission': 'read-only'},
        'Title': {'type': 'string', 'maxLength': 20},
        'Percentage': {'type': 'number', 'minimum': 0, 'maximum': 100},
        'Due': {'type': 'string', 'format': 'date', 'minimum': '2026-01-01', 'maximum': '2026-12-31'},
        'At': {'type': 'string', 'format': 'date-time', 'minimum': '2026-01-01T12:00:00Z'},
        'Status': {'type': 'object', 'properties': {'Value': {'type': 'string'}}}},
        'required': ['Title'], 'mapping': {'Title': 'Score title', 'Percentage': 'Completion percent'},
        'choices': {'Status': ['Draft', 'Ready']}})
    r.store.patch('Scores', {}, {'Title': 'Fictional first', 'Percentage': 10})
    r.close()
    r = Runtime(p)
    r.restart()
    yield r
    r.close()


def run(r, formula):
    return r.fx.evaluate(formula, Context(r, behavior=True))


def binding(r, formula):
    r.binder.errors.clear()
    typ = r.binder.bind(r.fx.parse(formula), BindScope(), ('validation-test', formula, 0))
    return typ, [error for _, error in r.binder.errors]


@pytest.mark.parametrize('column', ['Percentage', "'Completion percent'", '"Percentage"', '"Completion percent"'])
@pytest.mark.parametrize('value', [0, 10, 100])
def test_documented_column_bounds_and_mapped_identifiers(r, column, value):
    formula = f'Validate(Scores,{column},{value})'
    typ, errors = binding(r, formula)
    assert typ.kind == 'Text' and not errors
    assert r.fx.evaluate(formula) is None


@pytest.mark.parametrize('value', [-1, 120])
def test_out_of_range_is_validation_text_not_an_error(r, value):
    message = r.fx.evaluate(f'Validate(Scores,Percentage,{value})')
    assert isinstance(message, str) and 'Completion percent' in message
    assert r.fx.evaluate(f'IsError(Validate(Scores,Percentage,{value}))') is False


def test_column_validation_does_not_require_other_columns(r):
    assert r.fx.evaluate('Validate(Scores,Percentage,10)') is None
    assert 'required' in r.fx.evaluate('Validate(Scores,Title,Blank())')
    assert r.fx.evaluate('Validate(Scores,Percentage,Blank())') is None
    assert 'maximum length' in r.fx.evaluate('Validate(Scores,Title,"123456789012345678901")')


@pytest.mark.parametrize('original', ['First(Scores)', 'Defaults(Scores)', 'Blank()', '{}'])
def test_record_validation_merges_original_and_updates(r, original):
    assert r.fx.evaluate(f'Validate(Scores,{original},{{Title:"Fictional edit",Percentage:100}})') is None
    assert 'allowed range' in r.fx.evaluate(f'Validate(Scores,{original},{{Title:"Fictional edit",Percentage:120}})')
    assert 'required' in r.fx.evaluate(f'Validate(Scores,{original},{{Title:Blank()}})')


def test_record_variables_and_mapped_updates(r):
    run(r, 'Set(editRecord,First(Scores));Set(changes,{Percentage:55})')
    assert r.fx.evaluate('Validate(Scores,editRecord,changes)') is None
    assert r.fx.evaluate('Validate(Scores,First(Scores),{\'Completion percent\':100})') is None
    assert 'required' in r.fx.evaluate('Validate(Scores,First(Scores),{\'Score title\':Blank()})')


@pytest.mark.parametrize('formula', [
    'Validate(5,Percentage,10)', 'Validate(Scores,Percentage,"10")',
    'Validate(Scores,"Missing",10)', 'Validate(Scores,First(Scores),{Missing:10})',
    'Validate(Scores,First(Scores),{Percentage:"10"})', 'Validate(Scores,5,{Title:"X"})',
    'Validate(Scores,{Title:"X"},5)', 'Validate(Scores,Percentage)',
    'Validate(Scores,Percentage,10,20)'])
def test_invalid_types_names_and_arity_fail_binding(r, formula):
    assert binding(r, formula)[1]
    with pytest.raises(FxError): r.fx.evaluate(formula)


def test_original_and_updated_error_cells_propagate(r):
    assert r.fx.evaluate('IfError(Validate(Scores,Percentage,1/0),FirstError.Kind)') is not None
    with pytest.raises(FxError) as error:
        r.fx.evaluate('Validate(Scores,{Title:"Fictional",Percentage:1/0},{})')
    assert error.value.kind == 'Div0'
    assert r.fx.evaluate('Validate(Scores,{Title:"Fictional",Percentage:1/0},{Percentage:10})') is None
    assert r.fx.evaluate('If(false,Validate(Scores,Percentage,1/0),Blank())') is None


@pytest.mark.parametrize('formula', [
    'Validate(Scores,Due,Date(2026,1,1))', 'Validate(Scores,Due,Date(2026,12,31))',
    'Validate(Scores,At,DateTime(2026,1,1,12,0,0))'])
def test_date_bounds_accept_endpoints(r, formula):
    assert r.fx.evaluate(formula) is None


@pytest.mark.parametrize('formula', [
    'Validate(Scores,Due,Date(2025,12,31))', 'Validate(Scores,Due,Date(2027,1,1))',
    'Validate(Scores,At,DateTime(2026,1,1,11,59,59))'])
def test_date_bounds_are_validation_messages(r, formula):
    assert 'allowed range' in r.fx.evaluate(formula)


def test_complex_choice_shapes_share_local_metadata_validation(r):
    assert r.fx.evaluate('Validate(Scores,Status,{Value:"Ready"})') is None
    assert 'Invalid choice' in r.fx.evaluate('Validate(Scores,Status,{Value:"Unknown"})')


def test_collection_without_metadata_always_passes(r):
    run(r, 'ClearCollect(localScores,{Title:"X",Percentage:10})')
    assert r.fx.evaluate('Validate(localScores,Percentage,10000)') is None
    assert r.fx.evaluate('Validate(localScores,{Title:Blank(),Percentage:-10},{Percentage:10000})') is None
    assert r.fx.evaluate('Validate(Table({Percentage:10}),Percentage,120)') is None


def test_validation_does_not_write_clear_errors_or_consume_failure_injection(r):
    with pytest.raises(FxError): run(r, 'Patch(Scores,Defaults(Scores),{Title:Blank()})')
    before = deepcopy([r.store.operation_errors, r.globals, r.collections, r.component_state])
    exposed_errors = r.fx.evaluate('Errors(Scores)')
    source, data = revision(r.project.root), data_revision(r.store)
    r.store.failures['Scores'] = 'write'
    assert r.fx.evaluate('Validate(Scores,First(Scores),{Percentage:50})') is None
    assert 'allowed range' in r.fx.evaluate('Validate(Scores,Percentage,120)')
    assert revision(r.project.root) == source and data_revision(r.store) == data
    # Error exception objects have identity; compare the exposed error table.
    assert len(r.store.operation_errors['Scores']) == len(before[0]['Scores'])
    assert r.fx.evaluate('Errors(Scores)') == exposed_errors
    assert [r.globals,r.collections,r.component_state] == before[1:]
    with pytest.raises(FxError, match='Simulated write failure'):
        run(r, 'Patch(Scores,First(Scores),{Percentage:50})')


@pytest.mark.parametrize('number', ['float', 'decimal'])
def test_patch_import_and_validate_enforce_same_declared_range(r, number):
    r.environment['number_mode'] = number
    value = 100 if number == 'float' else Decimal('100')
    assert r.store.patch('Scores', {'ID':1}, {'Percentage':value})['Completion percent'] is not None
    with pytest.raises(FxError, match='allowed range'): run(r, 'Patch(Scores,First(Scores),{Percentage:120})')
    before = data_revision(r.store)
    with pytest.raises(FxError): r.store.import_rows('Scores', [{'Title':'Fictional import','Percentage':-1}])
    assert data_revision(r.store) == before


@pytest.mark.parametrize('field', [
    {'type':'number','minimum':True}, {'type':'number','maximum':float('inf')},
    {'type':'number','minimum':101,'maximum':100}, {'type':'string','minimum':0},
    {'type':'string','format':'date','minimum':'bad-date'},
    {'type':'string','format':'date-time','maximum':10}])
def test_invalid_range_metadata_is_rejected(r, field):
    with pytest.raises(FxError): r.store.add_list('Invalid', {'fields': {'Value':field}})


def test_scalar_contract_conversions_match_patch(r):
    assert r.fx.evaluate('Validate(Scores,Percentage,true)') is None
    assert r.fx.evaluate('Validate(Scores,Title,123)') is None
    assert run(r, 'Patch(Scores,First(Scores),{Percentage:true,Title:123})')['Score title'] == '123'


def test_volatile_property_rechecks_changed_validation_metadata(r):
    p = r.project
    p.update_source('Src/app.pa.yaml', dump_yaml({'Screens': {'Home': {'Children': [
        {'Check': {'Control':'ModernText@1.0.0','Properties': {
            'Text':'=Coalesce(Validate(Scores,Percentage,50),"Valid") & Text(Rand())'}}}]}}}))
    r.close()
    observed = Runtime(p)
    try:
        observed.restart()
        ref = observed.refs['Home/Check']
        first = ref.property('Text')
        assert first.startswith('Valid') and ref.property('Text') == first
        observed.store.definitions['Scores']['fields']['Percentage']['maximum'] = 40
        observed.invalidate()
        changed = ref.property('Text')
        assert 'allowed range' in changed and changed != first
    finally:
        observed.close()


def test_validation_uses_metadata_when_list_read_is_injected_to_fail(r):
    r.store.failures['Scores'] = 'read'
    assert r.fx.evaluate('Validate(Scores,Percentage,10)') is None
    assert 'allowed range' in r.fx.evaluate('Validate(Scores,Percentage,120)')


def test_form_validation_and_submission_share_declared_ranges(tmp_path):
    from powerapps_sim.fixtures import forms_project
    from powerapps_sim.store import ListStore
    p = forms_project(tmp_path/'forms')
    store = ListStore(p.root/'data.sqlite', schema_root=p.root/'lists')
    store.definitions['Drafts']['fields']['Amount'].update(minimum=0, maximum=200)
    store.save_definition('Drafts')
    store.close()
    r = Runtime(p)
    try:
        r.restart()
        r.state()
        form = r.global_refs['DraftForm']
        assert form.property('Valid')
        r.event('Forms/DraftForm/AmountCard/AmountInput','OnChange',201)
        assert not form.property('Valid')
        assert 'allowed range' in r.fx.evaluate('Validate(Drafts,First(Drafts),DraftForm.Updates)')
        before = data_revision(r.store)
        run(r,'SubmitForm(DraftForm)')
        assert 'allowed range' in form.property('Error')
        assert data_revision(r.store) == before
        r.event('Forms/DraftForm/AmountCard/AmountInput','OnChange',150)
        assert form.property('Valid')
        run(r,'SubmitForm(DraftForm)')
        assert form.property('LastSubmit')['Amount'] == 150 and not form.property('Error')
    finally:
        r.close()

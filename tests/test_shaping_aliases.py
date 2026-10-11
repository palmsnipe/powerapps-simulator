"""Mapped column contracts shared by static binding and server evaluation."""
from copy import deepcopy
from pathlib import Path
import json
import pytest

from powerapps_sim.binding import BindScope, value_type
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError
from powerapps_sim.tables import SourceRecord

CASES = json.loads((Path(__file__).parents[1] / 'powerapps_sim/conformance_cases/shaping_contracts.json').read_text())['cases']


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_pinned_shaping_compiler_and_value_contracts(runtime, case):
    from powerapps_sim.conformance import run_case
    result = run_case(runtime, case)
    assert result['status'] == 'passed', result


@pytest.fixture
def mapped(runtime):
    rows = [SourceRecord({'ID': 1, 'Display title': 'Fictional first', 'Display amount': 2, 'Display group': 'A'},
                         {'ID': 'ID', 'Display title': 'Title', 'Display amount': 'Cost_x0020_Value', 'Display group': 'Team'}),
            SourceRecord({'ID': 2, 'Display title': 'Fictional second', 'Display amount': 5, 'Display group': 'B'},
                         {'ID': 'ID', 'Display title': 'Title', 'Display amount': 'Cost_x0020_Value', 'Display group': 'Team'})]
    runtime.globals['Mapped'] = rows
    runtime.binder.globals['Mapped'] = value_type(rows)
    return runtime


@pytest.mark.parametrize('column', ['Title', "'Display title'", '"Title"', '"Display title"'])
@pytest.mark.parametrize('source', ['Mapped', 'Filter(Mapped,true)', 'First(Mapped)'])
@pytest.mark.parametrize('operation', ['ShowColumns', 'DropColumns', 'RenameColumns'])
def test_existing_column_names_resolve_to_physical_fields(mapped, column, source, operation):
    expression = f'{operation}({source},{column}' + (',Caption)' if operation == 'RenameColumns' else ')')
    before = deepcopy(mapped.globals['Mapped'])
    mapped.binder.errors.clear()
    typ = mapped.binder.bind(mapped.fx.parse(expression), BindScope())
    assert not mapped.binder.errors
    result = mapped.fx.evaluate(expression)
    rows = [result] if isinstance(result, dict) else result
    schema = typ if typ.kind == 'Record' else typ.row
    assert set(schema.physical_fields()) == set(rows[0])
    for original, row in zip(before, rows):
        expected = ({'Display title': original['Display title']} if operation == 'ShowColumns' else
                    {k: v for k, v in original.items() if k != 'Display title'})
        if operation == 'RenameColumns':
            expected['Caption'] = original['Display title']
        assert row == expected
        assert ('Title' in schema.aliases) == (operation == 'ShowColumns')
        assert ('Display title' in row.logical_names) == (operation == 'ShowColumns')
    assert before == mapped.globals['Mapped']
    assert before[0].logical_names == mapped.globals['Mapped'][0].logical_names


@pytest.mark.parametrize('source', ['Mapped', 'FirstN(Mapped,0)', 'If(false,Mapped)', 'First(Mapped)'])
@pytest.mark.parametrize('formula', [
    'AddColumns(SOURCE,Title,1)', 'AddColumns(SOURCE,\'Display title\',1)',
    'RenameColumns(SOURCE,Team,Title)', 'RenameColumns(SOURCE,Team,\'Display title\')',
    'DropColumns(SOURCE,Title,\'Display title\')',
    'RenameColumns(SOURCE,Title,Caption,\'Display title\',Other)',
    'RenameColumns(SOURCE,Title,\'Display title\')',
])
def test_alias_collisions_and_repeated_columns_validate_even_without_rows(mapped, source, formula):
    expression = formula.replace('SOURCE', source)
    mapped.binder.errors.clear()
    mapped.binder.bind(mapped.fx.parse(expression), BindScope())
    assert mapped.binder.errors
    assert all(error.end > error.start for _, error in mapped.binder.errors)
    with pytest.raises(FxError) as error:
        mapped.fx.evaluate(expression)
    assert error.value.end > error.value.start


@pytest.mark.parametrize('column', ['Title', "'Display title'", '"Title"', '"Display title"'])
def test_logical_self_rename_keeps_display_key_and_metadata(mapped, column):
    expression = f'RenameColumns(Mapped,{column},Title)'
    assert mapped.fx.evaluate(expression) == mapped.globals['Mapped']
    assert mapped.fx.evaluate(f'First({expression}).Title') == 'Fictional first'


def test_chained_shaping_original_scopes_and_encoded_internal_names(mapped):
    expression = "ShowColumns(RenameColumns(AddColumns(Mapped As R,Total,R.Cost_x0020_Value*3),Title,Caption),Caption,Total)"
    assert mapped.fx.evaluate(expression) == [{'Caption': 'Fictional first', 'Total': 6}, {'Caption': 'Fictional second', 'Total': 15}]
    assert mapped.fx.evaluate("First(ShowColumns(Mapped,Cost_x0020_Value)).Cost_x0020_Value") == 2
    # There is no inferred encoding or implicit alias after an actual rename.
    for expression in ["ShowColumns(Mapped,Cost_Value)", "First(RenameColumns(Mapped,Title,Caption)).Title",
                       "AddColumns(Mapped,New,1,Next,New+1)"]:
        mapped.binder.errors.clear()
        mapped.binder.bind(mapped.fx.parse(expression), BindScope())
        assert mapped.binder.errors


@pytest.mark.parametrize('transform', ["DropColumns(Mapped,Title)", "RenameColumns(Mapped,Title,Caption)"])
def test_removed_metadata_cannot_alias_a_reintroduced_plain_column(mapped, transform):
    expression = f"AddColumns({transform},'Display title',\"New plain title\")"
    rows = mapped.fx.evaluate(expression)
    assert all('Display title' not in row.logical_names for row in rows)
    mapped.fx.evaluate('ClearCollect(Captured,' + expression + ')', Context(mapped, behavior=True))
    assert mapped.fx.evaluate("First(Captured).'Display title'") == 'New plain title'
    mapped.binder.errors.clear()
    mapped.binder.bind(mapped.fx.parse('First(Captured).Title'), BindScope())
    assert any(e.kind == 'Name' for _, e in mapped.binder.errors)
    with pytest.raises(FxError):
        mapped.fx.evaluate('First(Captured).Title')


def test_shape_then_group_and_ungroup_keeps_aliases_lineage_and_errors(mapped):
    mapped.globals['Mapped'][0]['Untouched'] = FxError('fictional retained error', 'Div0')
    mapped.binder.globals['Mapped'] = value_type(mapped.globals['Mapped'])
    source = "AddColumns(ShowColumns(Mapped,ID,Title,Team,Cost_x0020_Value,Untouched),Extra,Cost_x0020_Value*2)"
    expression = f'Ungroup(GroupBy({source},Team,Members),Members)'
    assert mapped.fx.evaluate(f'First({expression}).Title') == 'Fictional first'
    assert mapped.fx.evaluate(f'First({expression}).Extra') == 4
    assert mapped.fx.evaluate(f'IfError(First({expression}).Untouched,FirstError.Kind)') == 13
    assert mapped.fx.evaluate(f'Concat({expression},Text(ID),",")') == '1,2'


def test_record_metadata_fallback_when_schema_is_open(mapped):
    from powerapps_sim.binding import OPEN_RECORD, tabular
    mapped.binder.globals['Mapped'] = tabular(OPEN_RECORD)
    assert mapped.fx.evaluate('ShowColumns(Mapped,Title)') == [{'Display title': 'Fictional first'}, {'Display title': 'Fictional second'}]
    assert mapped.fx.evaluate('First(RenameColumns(Mapped,Title,Caption)).Caption') == 'Fictional first'


@pytest.mark.parametrize('language', ['en-CA', 'fr-CA'])
@pytest.mark.parametrize('mode', ['float', 'decimal'])
def test_shaped_named_formula_feeds_typed_components_and_recalculates(tmp_path, language, mode):
    import io, zipfile
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import data_revision
    from powerapps_sim.fixtures import grouping_project
    project = grouping_project(tmp_path / 'project')
    project.config['environment'].update(language=language, number_mode=mode)
    project.save_config()
    workspace = Workspace(tmp_path, project.root)
    try:
        r = workspace.runtime
        assert not r.diagnostics
        assert r.fx.evaluate('CountRows(Summaries(ShapedSamples))') == 2
        assert r.fx.evaluate('LeftPanel.Info.Total') == 10
        assert r.fx.evaluate('RightPanel.Info.Total') == 18
        r.store.patch('Samples', r.store.rows('Samples')[0], {'Sample amount': 9, 'Sample note': '  Fictional edited note  '})
        r.invalidate(); r.state()
        assert r.fx.evaluate('LeftPanel.Info.Total') == 17
        assert r.fx.evaluate('RightPanel.Info.Total') == 18
        assert r.fx.evaluate("First(LeftPanel.Flat).'Sample note'") == 'Fictional edited note'
        assert r.store.rows('Samples')[0]['Sample note'] == '  Fictional edited note  '
        before = data_revision(r.store)
        r.fx.evaluate('ClearCollect(ShapedSnapshot,ShapedSamples)', Context(r, behavior=True))
        assert r.fx.evaluate('First(ShapedSnapshot).Title') == 'Fictional left 1'
        assert r.fx.evaluate("First(ShapedSnapshot).'Sample note'") == 'Fictional edited note'
        assert before == data_revision(r.store)
        assert not r.diagnostics
        with zipfile.ZipFile(io.BytesIO(project.export())) as archive:
            assert all(name.startswith('Src/') for name in archive.namelist())
            text = '\n'.join(archive.read(name).decode() for name in archive.namelist())
            assert 'ShapedSamples=RenameColumns(DropColumns(AddColumns(ShowColumns(' in text
            assert 'logical_names' not in text
    finally:
        workspace.runtime.close()

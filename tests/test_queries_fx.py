"""Pinned query oracles, alias scopes, and component-backed list queries."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import data_revision, revision
from powerapps_sim.binding import BindScope
from powerapps_sim.conformance import run_case
from powerapps_sim.fixtures import queries_project
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError

CASES = json.loads((Path(__file__).parents[1] / 'powerapps_sim/conformance_cases/queries.json').read_text())['cases']


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_pinned_query_contracts(runtime, case):
    result = run_case(runtime, case)
    assert result['status'] == 'passed', result


@pytest.mark.parametrize('formula,expected', [
    ('Filter(If(false,[1,2]),true)', None),
    ('Filter([],true)', []),
    ('Filter(Table({N:1},Error({Kind:ErrorKind.Div0}),Blank()),false)', []),
    ('CountIf(Filter(Table({N:1},Error({Kind:ErrorKind.Div0}),Blank()),IsError(ThisRecord)),true)', 1),
    ('CountRows(Filter(Table({N:1},Error({Kind:ErrorKind.Div0}),Blank()),!IsError(ThisRecord)))', 2),
    ('Filter([0,1,2],false,1/Value>0)', []),
    ('CountRows(Filter([0,1,2],Value>0,1/Value>0))', 2),
    ('IfError(LookUp(Table(Error({Kind:ErrorKind.Div0}),{N:3}),true,N),FirstError.Kind)', 13),
    ('LookUp(Table(Error({Kind:ErrorKind.Div0}),{N:3}),!IsError(ThisRecord),N)', 3),
    ('LookUp(Table({N:3},Error({Kind:ErrorKind.Div0})),true,N)', 3),
    ('LookUp([{N:1},{N:2}],false,1/0)', None),
    ('LookUp([1,2,0],Value>0,Value)', 1),
    ('LookUp(Table(Blank(),{N:2}),IsBlank(ThisRecord),"blank row")', 'blank row'),
    ('With({Value:9},LookUp([1,2] As row,row.Value>1,Value+row.Value))', 11),
    ('ForAll([10] As outer,LookUp([1,2] As inner,inner.Value>1,outer.Value+inner.Value))', [{'Value':12}]),
    ('ForAll([10],LookUp([1,2] As inner,inner.Value>1,ThisRecord.Value+inner.Value))', [{'Value':12}]),
])
def test_blank_error_rows_short_circuit_and_outer_scopes(runtime, formula, expected):
    assert runtime.fx.evaluate(formula) == expected


@pytest.mark.parametrize('formula', [
    'LookUp([1,2] As row,Value>0)', 'LookUp([1,2] As row,row.Value>0,Value)',
    'Filter([1,2] As row,ThisRecord.Value>0)', 'ForAll([1,2] As row,Value)',
    'With({N:1} As row,N)', 'LookUp([1,2],1)', 'LookUp([1,2],"true")',
    'Filter(ParseJSON("[]"),true)', 'LookUp({N:1},true)',
])
def test_binding_rejects_invalid_aliases_and_query_contracts(runtime, formula):
    runtime.binder.errors.clear()
    runtime.binder.bind(runtime.fx.parse(formula), BindScope())
    assert runtime.binder.errors
    assert all(error.end > error.start for _, error in runtime.binder.errors)


def test_aliases_do_not_hide_globals_or_gallery_item(runtime):
    runtime.globals['Value'] = 10
    ctx = Context(runtime, item={'Title':'Fictional gallery item'})
    assert runtime.fx.evaluate('LookUp([1,2] As row,row.Value>1,{N:Value+row.Value,Caption:ThisItem.Title})',ctx) == {'N':12,'Caption':'Fictional gallery item'}


def test_updateif_change_record_requires_its_explicit_alias(runtime):
    runtime.binder.errors.clear()
    runtime.binder.bind(runtime.fx.parse('UpdateIf(Projects As project,true,{Amount:Amount+1})'),BindScope(behavior=True))
    assert any(error.kind == 'Name' and 'Amount' in error.message for _, error in runtime.binder.errors)


@pytest.mark.parametrize('language', ['en-CA', 'fr-CA'])
@pytest.mark.parametrize('mode', ['float', 'decimal'])
def test_queries_workflow_preserves_edited_owner(tmp_path, language, mode):
    project = queries_project(tmp_path / 'project')
    workspace = Workspace(tmp_path, project.root)
    try:
        runtime = workspace.runtime
        runtime.store.patch('Samples',runtime.store.rows('Samples')[0],{'Sample amount':11})
        runtime.invalidate(); runtime.state()
        assert runtime.fx.evaluate('LeftPanel.Info.First') == 11
        before = (revision(project.root), data_revision(runtime.store), deepcopy(workspace.ai.read_runtime()))
        scenario = deepcopy(workspace.workflows.catalog()['scenarios'][0]['scenario'])
        scenario['environment'] = {'language':language,'number_mode':mode,'enum_mode':'strong'}
        result = workspace.workflows.run(scenario,expected_revision=before[0])
        assert result['status'] == 'passed', result['steps']
        assert len(result['steps']) == 31 and not result['diagnostics']
        assert before == (revision(project.root), data_revision(runtime.store), workspace.ai.read_runtime())
    finally:
        workspace.runtime.close()

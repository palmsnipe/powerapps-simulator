"""Documented grouping values, mapped schemas, nested lineage and components."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision,data_revision
from powerapps_sim.binding import BindScope,value_type
from powerapps_sim.fixtures import grouping_project
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError
from powerapps_sim.tables import SourceRecord

DOCUMENTATION=json.loads((Path(__file__).parents[1]/'powerapps_sim/examples/grouping-reference.json').read_text())

@pytest.mark.parametrize('language',['en-CA','fr-CA'])
@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('case',DOCUMENTATION['cases'],ids=lambda c:c['id'])
def test_documented_city_tables(runtime,case,language,mode):
    runtime.environment.update(language=language,number_mode=mode)
    assert runtime.fx.evaluate(case['expression'])==case['expected']

@pytest.mark.parametrize('column',['Team',"'Sample team'",'"Team"','"Sample team"'])
@pytest.mark.parametrize('source',['Samples','Filter(Samples,true)','AddColumns(Samples,Extra,"retained")'])
def test_mapped_group_columns_keep_nested_and_flattened_aliases(tmp_path,column,source):
    p=grouping_project(tmp_path/'project');w=Workspace(tmp_path,p.root)
    try:
        r=w.runtime;before=data_revision(r.store)
        groups=r.fx.evaluate(f'GroupBy({source},{column},Members)')
        assert [g['Sample team'] for g in groups]==['A','B']
        assert [[row['ID'] for row in g['Members']] for g in groups]==[[1,4,5],[2,3,6]]
        assert all('Team' not in row and 'Sample team' not in row for g in groups for row in g['Members'])
        assert r.fx.evaluate(f'Concat(Ungroup(GroupBy({source},{column},Members),Members),Text(ID),",")')=='1,2,3,4,5,6'
        assert r.fx.evaluate(f'First(Ungroup(GroupBy({source},{column},Members),Members)).Title')=='Fictional left 1'
        assert r.fx.evaluate(f'CountRows(Search(Ungroup(GroupBy({source},{column},Members),Members),"left",Title))')==3
        assert r.fx.evaluate(f'First(First(GroupBy({source},{column},Members)).Members).Note')=='Fictional 1'
        assert before==data_revision(r.store)
    finally:w.runtime.close()

@pytest.mark.parametrize('formula',[
 'GroupBy(Samples,Team,\'Sample team\',Members)','GroupBy(Samples,Team,Title)',
 'GroupBy(Samples,Team,\'Sample title\')','GroupBy(Samples,Missing,Members)',
 'Ungroup(GroupBy(Samples,Team,Members),Team)',
 'Ungroup(FirstN(Table({Rows:1}),0),Rows)','Ungroup(Table({Rows:Table({K:1}),K:2}),Rows)',
 'GroupBy(Blank(),Team,Members)','GroupBy(ParseJSON("[]"),Team,Members)',
 'GroupBy(Samples,Lower("Team"),Members)',
])
def test_invalid_grouping_contracts_include_source_spans(tmp_path,formula):
    p=grouping_project(tmp_path/'project');w=Workspace(tmp_path,p.root)
    try:
        r=w.runtime;r.binder.errors.clear();r.binder.bind(r.fx.parse(formula),BindScope())
        assert r.binder.errors
        assert all(e.end>e.start for _,e in r.binder.errors)
        with pytest.raises(FxError):r.fx.evaluate(formula)
    finally:w.runtime.close()

@pytest.mark.parametrize('formula,expected',[
 ('CountRows(GroupBy(Table({K:"a",N:Text(1/0)}),K,Rows))',1),
 ('IfError(Value(First(Ungroup(GroupBy(Table({K:"a",N:Text(1/0)}),K,Rows),Rows)).N),FirstError.Kind)',13),
 ('IfError(CountRows(GroupBy(Table({K:1/0,N:1}),K,Rows)),FirstError.Kind)',13),
 ('IfError(CountRows(GroupBy(Table({K:"a"},Error({Kind:ErrorKind.Div0})),K,Rows)),FirstError.Kind)',13),
 ('IfError(CountRows(Ungroup(Table({Rows:Table({N:1},Error({Kind:ErrorKind.Div0}))}),Rows)),FirstError.Kind)',13),
 ('Ungroup(Table({K:"a",Rows:Blank()},{K:"b",Rows:Table({N:2})}),Rows)',[{'K':'b','N':2}]),
 ('GroupBy(If(false,Table({K:"a",N:1})),K,Rows)',None),
 ('Ungroup(If(false,Table({Rows:Table({N:1})})),Rows)',None),
 ('GroupBy(FirstN(Table({K:"a",N:1}),0),K,Rows)',[]),
])
def test_error_cells_and_typed_blank_table_policies(runtime,formula,expected):
    assert runtime.fx.evaluate(formula)==expected


def test_ungroup_combines_outer_mapping_with_plain_children(runtime):
    row=SourceRecord({'Outer caption':'Fictional outer','Nested rows':[{'Value':'Fictional child'}]}, {'Outer caption':'Title','Nested rows':'Children'})
    runtime.globals['outerRows']=[row];runtime.binder.globals['outerRows']=value_type([row])
    assert runtime.fx.evaluate('First(Ungroup(outerRows,Children)).Title')=='Fictional outer'
    assert runtime.fx.evaluate('First(Ungroup(outerRows,"Children")).Value')=='Fictional child'
    assert set(runtime.fx.evaluate('First(Ungroup(outerRows,Children))'))=={'Outer caption','Value'}


def test_ungroup_does_not_choose_between_conflicting_aliases(runtime):
    child=SourceRecord({'Inner caption':'Fictional child'},{'Inner caption':'Title'})
    outer=SourceRecord({'Outer caption':'Fictional outer','Rows':[child]},{'Outer caption':'Title'})
    runtime.globals['conflict']=[outer];runtime.binder.globals['conflict']=value_type([outer])
    assert runtime.fx.evaluate('First(Ungroup(conflict,Rows)).\'Inner caption\'')=='Fictional child'
    assert runtime.fx.evaluate('First(Ungroup(conflict,Rows)).\'Outer caption\'')=='Fictional outer'
    formula='First(Ungroup(conflict,Rows)).Title'
    runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(formula),BindScope())
    assert any(e.kind=='Name' for _,e in runtime.binder.errors)
    with pytest.raises(FxError):runtime.fx.evaluate(formula)


def test_nested_group_round_trip_and_copied_collection_lineage(tmp_path):
    p=grouping_project(tmp_path/'project');w=Workspace(tmp_path,p.root)
    try:
        r=w.runtime
        formula='Ungroup(Ungroup(GroupBy(GroupBy(Samples,Side,Members),Side,Groups),Groups),Members)'
        assert r.fx.evaluate('Concat('+formula+',Text(ID),",")')=='1,2,3,4,5,6'
        r.fx.evaluate('ClearCollect(grouped,GroupBy(Samples,Team,Members))',Context(r,behavior=True))
        assert r.fx.evaluate('First(Ungroup(grouped,Members)).Team')=='A'
        assert r.fx.evaluate('Concat(Ungroup(SortByColumns(grouped,\'Sample team\',SortOrder.Descending),Members),Text(ID),",")')=='1,2,3,4,5,6'
        r.fx.evaluate('Patch(grouped,First(grouped),{Flag:true})',Context(r,behavior=True))
        assert r.fx.evaluate('Concat(Ungroup(grouped,Members),Text(ID),",")')=='1,2,3,4,5,6'
    finally:w.runtime.close()

@pytest.mark.parametrize('language',['en-CA','fr-CA'])
@pytest.mark.parametrize('mode',['float','decimal'])
def test_grouping_workflow_preserves_edited_owner(tmp_path,language,mode):
    p=grouping_project(tmp_path/'project');w=Workspace(tmp_path,p.root)
    try:
        r=w.runtime;r.store.patch('Samples',r.store.rows('Samples')[0],{'Sample amount':11});r.invalidate();r.state()
        assert r.fx.evaluate('LeftPanel.Info.Total')==19
        before=(revision(p.root),data_revision(r.store),deepcopy(w.ai.read_runtime()))
        scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);scenario['environment']={'language':language,'number_mode':mode,'enum_mode':'strong'}
        result=w.workflows.run(scenario,expected_revision=before[0])
        assert result['status']=='passed',result['steps']
        assert len(result['steps'])==29 and not result['diagnostics']
        assert before==(revision(p.root),data_revision(r.store),w.ai.read_runtime())
    finally:w.runtime.close()


def test_physical_udf_schema_ignores_alias_metadata_but_rejects_extra_fields(tmp_path):
    p=grouping_project(tmp_path/'project');w=Workspace(tmp_path,p.root)
    try:
        assert w.runtime.fx.evaluate('CountRows(Summaries(Samples))')==2
        formula='Summaries(AddColumns(Samples,Unexpected,"extra"))'
        w.runtime.binder.errors.clear();w.runtime.binder.bind(w.runtime.fx.parse(formula),BindScope())
        assert w.runtime.binder.errors
        with pytest.raises(FxError):w.runtime.fx.evaluate(formula)
    finally:w.runtime.close()


def test_multiple_group_keys_retained_aliases_and_plain_source_export(tmp_path):
    import io,zipfile
    p=grouping_project(tmp_path/'project');w=Workspace(tmp_path,p.root)
    try:
        assert w.runtime.fx.evaluate('CountRows(GroupBy(Samples,Side,Team,Members))')==4
        formula='Ungroup(GroupBy(Samples,Side,Team,Members),Members)'
        assert w.runtime.fx.evaluate('Concat('+formula+',Text(ID),",")')=='1,2,3,4,5,6'
        assert w.runtime.fx.evaluate('First('+formula+').Side')=='Left'
        assert w.runtime.fx.evaluate('First('+formula+').Team')=='A'
        rows=w.runtime.fx.evaluate(formula)
        assert all('Side' not in row and 'Team' not in row and not any(key.startswith('__') for key in row) for row in rows)
        with zipfile.ZipFile(io.BytesIO(p.export())) as archive:
            assert all(name.startswith('Src/') for name in archive.namelist())
            assert 'GroupBy(' in '\n'.join(archive.read(name).decode() for name in archive.namelist())
    finally:w.runtime.close()

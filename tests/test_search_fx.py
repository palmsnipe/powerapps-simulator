"""Independent Search oracles, metadata lineage and component isolation."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision, data_revision
from powerapps_sim.binding import BindScope
from powerapps_sim.conformance import run_case
from powerapps_sim.fixtures import search_queries_project
from powerapps_sim.syntax import FxError

CASES=json.loads((Path(__file__).parents[1]/'powerapps_sim/conformance_cases/search.json').read_text())['cases']

@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_pinned_search_contracts(runtime,case):
    result=run_case(runtime,case)
    assert result['status']=='passed',result

@pytest.mark.parametrize('source', ['Samples','Filter(Samples,true)','AddColumns(Samples,Extra,"extra")',"ShowColumns(Samples,'Sample title','Sample note')","DropColumns(Samples,'Sample amount')"])
@pytest.mark.parametrize('column',['Title','\'Sample title\'','"Title"','"Sample title"'])
def test_search_retains_mapped_names_and_records(tmp_path,source,column):
    project=search_queries_project(tmp_path/'project');w=Workspace(tmp_path,project.root)
    try:
        before=data_revision(w.runtime.store)
        rows=w.runtime.fx.evaluate(f'Search({source},"LEFT",{column})')
        assert [row['ID'] for row in rows]==[1,2] if 'ID' in rows[0] else len(rows)==2
        assert all('Title' not in row and 'Sample title' in row and not any(k.startswith('__') for k in row) for row in rows)
        assert data_revision(w.runtime.store)==before
    finally:w.runtime.close()

@pytest.mark.parametrize('formula,expected',[
 ('CountRows(Search(Table({A:"match",B:Text(1/0)}),"MATCH",A,B))',1),
 ('IfError(CountRows(Search(Table({A:Text(1/0),B:"match"}),"match",A,B)),FirstError.Kind)',13),
 ('CountRows(Search(Table({A:"match",B:Text(1/0)}),"match",A))',1),
 ('CountIf(Search(Table({A:"match"},Error({Kind:ErrorKind.Div0})),"",A),IsError(ThisRecord))',1),
 ('IfError(CountRows(Search(Table({A:"match"},Error({Kind:ErrorKind.Div0})),"match",A)),FirstError.Kind)',13),
 ('CountRows(Search(Table(Blank(),{A:"match"}),"match",A))',1),
 ('IfError(CountRows(Search(If(false,Table({A:""})),Text(1/0),A)),FirstError.Kind)',13),
 ('IfError(CountRows(Search(If(1/0>0,Table({A:""})),Text(1/0),A)),CountRows(AllErrors))',2),
])
def test_ordered_column_errors_and_eager_arguments(runtime,formula,expected):
    assert runtime.fx.evaluate(formula)==expected

@pytest.mark.parametrize('formula',[
 'Search(Table({A:"text"}),1,A)','Search(Table({A:"text"}),{N:1},A)',
 'Search(Table({A:1}),"",A)','Search(FirstN(Table({A:1}),0),"",A)',
 'Search(Table({A:Blank()}),"",A)','Search(Table({A:"text"}),"",Missing)',
 'Search(Blank(),"",A)','Search(Table({A:"text"}),"",Lower("A"))',
])
def test_invalid_contracts_have_source_locations(runtime,formula):
    runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(formula),BindScope())
    assert runtime.binder.errors
    assert all(error.end>error.start for _,error in runtime.binder.errors)
    with pytest.raises(FxError):runtime.fx.evaluate(formula)

@pytest.mark.parametrize('language',['en-CA','fr-CA'])
@pytest.mark.parametrize('mode',['float','decimal'])
def test_search_workflow_preserves_edited_owner(tmp_path,language,mode):
    project=search_queries_project(tmp_path/'project');w=Workspace(tmp_path,project.root)
    try:
        r=w.runtime;r.store.patch('Samples',r.store.rows('Samples')[0],{'Sample note':'Owned edited text'});r.invalidate();r.state()
        before=(revision(project.root),data_revision(r.store),deepcopy(w.ai.read_runtime()))
        scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);scenario['environment']={'language':language,'number_mode':mode,'enum_mode':'strong'}
        result=w.workflows.run(scenario,expected_revision=before[0])
        assert result['status']=='passed',result['steps']
        assert len(result['steps'])==29 and not result['diagnostics']
        assert before==(revision(project.root),data_revision(r.store),w.ai.read_runtime())
    finally:w.runtime.close()


def test_removed_mapping_is_not_a_column_and_export_is_plain_source(tmp_path):
    import io,zipfile
    project=search_queries_project(tmp_path/'project');w=Workspace(tmp_path,project.root)
    try:
        for source in ["DropColumns(Samples,'Sample title')","RenameColumns(Samples,'Sample title',Caption)"]:
            formula=f'Search({source},"left",Title)'
            w.runtime.binder.errors.clear();w.runtime.binder.bind(w.runtime.fx.parse(formula),BindScope())
            assert any(error.kind=='Name' and 'Title' in error.message for _,error in w.runtime.binder.errors)
            with pytest.raises(FxError):w.runtime.fx.evaluate(formula)
        with zipfile.ZipFile(io.BytesIO(project.export())) as archive:
            assert all(name.startswith('Src/') for name in archive.namelist())
            assert 'Search(' in '\n'.join(archive.read(name).decode() for name in archive.namelist())
    finally:w.runtime.close()


def test_metadata_encoded_internal_name_and_static_columns(runtime):
    runtime.store.add_list('Mapped',{'fields':{'ID':{'type':'integer'},'Search_x0020_note':{'type':'string'},'Title':{'type':'string'}},'mapping':{'Search_x0020_note':'Search note','Title':'Project title'}})
    runtime.store.patch('Mapped',{}, {'Search note':'Fictional match','Project title':'Alpha'})
    from powerapps_sim.binding import Binder
    runtime.binder=Binder(runtime)
    for column in ['Search_x0020_note','"Search_x0020_note"',"'Search note'"]:
        assert len(runtime.fx.evaluate(f'Search(Mapped,"MATCH",{column})'))==1
    runtime.globals['Missing']='Search note'
    with pytest.raises(FxError):runtime.fx.evaluate('Search(Mapped,"match",Missing)')
    assert runtime.fx.evaluate('CountRows(Search(Mapped,"alpha",Title,Title))')==1

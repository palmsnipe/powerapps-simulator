"""Native row counts, short-circuit predicates and isolated component recovery."""
from copy import deepcopy
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import json
import pytest
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision,data_revision
from powerapps_sim.binding import BindScope
from powerapps_sim.conformance import run_case
from powerapps_sim.fixtures import row_counts_project
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime
from powerapps_sim.syntax import FxError

CASES=json.loads((Path(__file__).parents[1]/'powerapps_sim/conformance_cases/row-counts.json').read_text())['cases']
@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_pinned_row_counts(runtime,case):
    result=run_case(runtime,case)
    assert result['status']=='passed',result

@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('formula,expected',[
 ('CountRows(Blank())',0),('CountRows([])',0),('CountIf([],true)',0),
 ('CountRows(Table({N:1/0},Blank(),{N:2}))',3),
 ('CountIf(Table({N:1},Error({Kind:ErrorKind.Div0}),Blank()),IsError(ThisRecord))',1),
 ('CountIf(Table({N:1},Error({Kind:ErrorKind.Div0}),Blank()),true)',3),
 ('CountIf(Table({N:1},Error({Kind:ErrorKind.Div0}),Blank()),IsBlank(ThisRecord))',None),
 ('CountIf(Table({N:1},Blank(),{N:2}),IsBlank(ThisRecord))',1),
 ('CountIf([0,1,2],false,1/Value>0)',0),
 ('CountIf([0,1,2],Value,1/Value>0)',2),
 ('CountIf(["",Blank(),"false","True"],Value)',1),
 ('CountIf([1,2,3],true,Blank(),1/0>0)',0),
 ('IfError(CountIf([0,0],1/Value>0),CountRows(AllErrors))',1),
 ('IfError(CountRows(Table(Error({Kind:ErrorKind.Div0}),Error({Kind:ErrorKind.Numeric}))),CountRows(AllErrors))',1),
 ('CountIf([{N:1},{N:2}] As outer,CountIf([1,2,3] As inner,inner.Value>outer.N)>1)',1),
 ('With({threshold:2},CountIf([1,2,3] As row,row.Value>[@threshold]))',None),
 ('CountRows(ParseJSON("[1,null,{},[2]]"))',4),
])
def test_scopes_coercion_short_circuit_and_host_numeric_types(runtime,mode,formula,expected):
    runtime.environment['number_mode']=mode;runtime.invalidate()
    if expected is None:
        with pytest.raises(FxError):runtime.fx.evaluate(formula)
    else:
        actual=runtime.fx.evaluate(formula)
        assert actual==expected
        assert isinstance(actual,Decimal)==(mode=='decimal')
        assert runtime.binder.bind(runtime.fx.parse(formula),BindScope()).kind==('Decimal' if mode=='decimal' else 'Number')

@pytest.mark.parametrize('formula',[
 'CountRows()','CountRows([1],[2])','CountRows({N:1})','CountRows(1)',
 'CountIf([1])','CountIf([1],Today())','CountIf([1],{A:true})',
 'CountIf([1],[true])','CountIf([1],Color.Red)','CountIf(ParseJSON("[1,2]"),true)',
])
def test_rejected_contracts_are_located(runtime,formula):
    runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(formula),BindScope())
    assert runtime.binder.errors and all(e.end>e.start for _,e in runtime.binder.errors)

@pytest.mark.parametrize('formula',[
 'CountIf(["bad"],Value)','CountIf([" true "],Value)','CountIf(["0"],Value)',
 'CountIf(["falſe"],Value)',
])
def test_invalid_text_is_not_truthy_or_trimmed(runtime,formula):
    with pytest.raises(FxError) as error:runtime.fx.evaluate(formula,Context(runtime,error_source='Count.Rule'))
    assert error.value.kind=='InvalidArgument' and error.value.end>error.value.start
    assert error.value.source=='Count.Rule'
    assert runtime.fx.evaluate(f'IfError({formula},FirstError.Kind)')==25

@pytest.mark.parametrize('mode',['float','decimal'])
def test_typed_functions_blank_tables_and_persistent_component_errors(runtime,mode):
    runtime.environment['number_mode']=mode;runtime.invalidate()
    runtime.fx.set_definitions('Rows:=Type([{N:Number}]); Total(rows:Rows):Number=CountRows(rows); Matched(rows:Rows):Number=CountIf(rows,N);')
    assert runtime.fx.evaluate('Total(Blank())')==0
    assert runtime.fx.evaluate('Matched(Blank())')==0
    assert runtime.fx.evaluate('Total([{N:1},{N:0},{N:Blank()}])')==3
    assert runtime.fx.evaluate('Matched([{N:1},{N:0},{N:Blank()}])')==1
    assert runtime.fx.evaluate('IfError(Total(Table({N:1},Error({Kind:ErrorKind.Div0}))),FirstError.Kind)')==13

@pytest.mark.parametrize('language',['en-CA','fr-CA'])
@pytest.mark.parametrize('mode',['float','decimal'])
def test_row_count_workflow_preserves_owner_and_language(tmp_path,language,mode):
    p=row_counts_project(tmp_path/'p');w=Workspace(tmp_path,p.root)
    try:
        w.runtime.store.patch('Samples',w.runtime.store.rows('Samples')[0],{'Sample amount':0})
        w.runtime.invalidate();w.runtime.state()
        assert w.runtime.fx.evaluate('LeftPanel.Matches.Numeric')==0
        before=(revision(p.root),data_revision(w.runtime.store),deepcopy(w.ai.read_runtime()))
        scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);scenario['environment']={'language':language,'number_mode':mode,'enum_mode':'strong'}
        result=w.workflows.run(scenario,expected_revision=before[0])
        assert result['status']=='passed',result['steps']
        assert len(result['steps'])==36 and not result['diagnostics']
        assert before==(revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime())
        w.runtime.environment.update(scenario['environment']);w.runtime.restart();w.runtime.state()
        assert w.runtime.refs['RowCountsLab/LeftPanel/Heading'].property('Text')==('Gauche' if language=='fr-CA' else 'Left')
    finally:w.runtime.close()

def test_list_projection_callbacks_errors_reset_and_source_export(tmp_path):
    p=row_counts_project(tmp_path/'p');r=Runtime(p)
    try:
        r.restart();r.state();assert not r.diagnostics
        assert r.fx.evaluate("CountIf(Samples,'Sample amount')")==2
        assert r.fx.evaluate("CountRows(ShowColumns(Samples,'Sample note'))")==3
        r.event('RowCountsLab/LeftPanel/Threshold','OnChange',1);r.state()
        assert r.collections['matchesTrace']==[{'Panel':'LeftPanel','Numeric':1,'Text':1,'Large':1,'Errors':0}]
        r.event('RowCountsLab/LeftPanel/Amount','OnChange',0)
        r.event('RowCountsLab/LeftPanel/AddSample','OnSelect');r.state()
        assert r.fx.evaluate('LeftPanel.Summary.Numeric')==2 and r.fx.evaluate('LeftPanel.Matches.Numeric')==1
        r.event('RowCountsLab/InjectFault','OnSelect');r.state()
        assert r.fx.evaluate('LeftPanel.RowState.Rows')==13
        assert r.fx.evaluate('LeftPanel.RowState.Errors')==1
        assert r.fx.evaluate('RightPanel.RowState.Rows')==1
        assert r.refs['RowCountsLab/LeftPanel/Result'].property('Text')=='Count error 13'
        assert not r.diagnostics
        r.event('RowCountsLab/InjectFault','OnSelect');r.state()
        assert r.fx.evaluate('LeftPanel.RowState.Rows')==3
        with ZipFile(BytesIO(p.export())) as z:
            assert z.namelist()==['Src/row-counts.pa.yaml']
            assert z.read(z.namelist()[0]).decode()==p.documents['Src/row-counts.pa.yaml']
    finally:r.close()

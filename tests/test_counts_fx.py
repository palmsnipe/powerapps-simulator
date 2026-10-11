"""Count contracts and independent native oracles in both numeric hosts."""
import json
from decimal import Decimal
from pathlib import Path
import pytest
from powerapps_sim.binding import BindScope
from powerapps_sim.conformance import run_case
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError

CASES=json.loads((Path(__file__).parents[1]/'powerapps_sim/conformance_cases/counts.json').read_text())['cases']
@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_pinned_counts(runtime,case):
    result=run_case(runtime,case)
    assert result['status']=='passed',result

@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('formula,expected',[
 ('Count(If(false,[1]))',0),('CountA(If(false,["x"]))',0),
 ('Count(FirstN([1],0))',0),('CountA(FirstN(["x"],0))',0),
 ('CountA(Table({N:{A:1/0}},{N:{A:2}}))',2),
 ('CountA(Table({N:[1/0]},{N:[2]}))',2),
 ('CountA([false,true,Blank()])',2),('Count([false,true])',None),
 ('CountA(["",Blank()," "])',2),('Count([0,"",Blank()])',1),
 ('Count([Blank(),"1",2])',None),
 ('Count([Blank(),2,"1"])',2),
 ('If(false,Count([1/0]),42)',42),
 ('IfError(CountA([1," ",1/0]),CountRows(AllErrors))',1),
 ('IfError(CountA([1," ",1/0]),FirstError.Kind)',25),
 ('IfError(CountA([1,1/0," "]),FirstError.Kind)',13),
])
def test_presence_laziness_nested_errors_and_numeric_identity(runtime,mode,formula,expected):
    runtime.environment['number_mode']=mode;runtime.invalidate()
    if expected is None:
        runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(formula),BindScope())
        assert runtime.binder.errors
    else:
        actual=runtime.fx.evaluate(formula)
        assert actual==expected
        if formula.startswith(('Count(', 'CountA(')):
            assert isinstance(actual,Decimal)==(mode=='decimal')
            assert runtime.binder.bind(runtime.fx.parse(formula),BindScope()).kind==('Decimal' if mode=='decimal' else 'Number')

@pytest.mark.parametrize('formula',['Count()','CountA([1],[2])','Count([])','CountA(Table())',
 'CountA(Blank())','Count({N:1})','CountA(ParseJSON("[1,2]"))',
 'Count(Table({N:1,M:2}))','CountA(Table({N:1,M:2}))','Count([Date(2026,1,1)])'])
def test_binding_errors_have_locations(runtime,formula):
    runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(formula),BindScope())
    assert runtime.binder.errors and all(e.end>e.start for _,e in runtime.binder.errors)

@pytest.mark.parametrize('mode',['float','decimal'])
def test_typed_functions_and_reactive_collection_summary(runtime,mode):
    runtime.environment['number_mode']=mode;runtime.invalidate()
    runtime.fx.set_definitions('Amounts:=Type([{N:Number}]); Numeric(rows:Amounts):Number=Count(rows);')
    assert runtime.fx.evaluate('Numeric(Blank())')==0
    assert runtime.fx.evaluate('Numeric([{N:2},{N:Blank()}])')==1
    ctx=Context(runtime,behavior=True)
    runtime.fx.evaluate('ClearCollect(samples,{N:2},{N:Blank()})',ctx)
    runtime.fx.set_definitions('Total=Count(ShowColumns(samples,N));Present=CountA(ShowColumns(samples,N));')
    assert runtime.fx.evaluate('Total')==runtime.fx.evaluate('Present')==1
    runtime.fx.evaluate('Collect(samples,{N:0})',ctx)
    assert runtime.fx.evaluate('Total')==2
    runtime.fx.evaluate('Remove(samples,{N:2})',ctx)
    assert runtime.fx.evaluate('Total')==1

def test_runtime_error_retains_source_and_first_cell_failure(runtime):
    with pytest.raises(FxError) as error:runtime.fx.evaluate('CountA([1," ",1/0])',Context(runtime,error_source='Summary.Count'))
    assert error.value.kind=='InvalidArgument' and error.value.source=='Summary.Count'
    assert error.value.end>error.value.start

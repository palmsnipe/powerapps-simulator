"""Pinned JSON flags/enum oracles and isolated component serialization flows."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import pytest
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError
from powerapps_sim.binding import BindScope
from powerapps_sim.enum_fx import EnumValue
from powerapps_sim.conformance import run_case

CORPUS=json.loads((Path(__file__).parents[1]/'powerapps_sim/conformance_cases/json_enums.json').read_text())

@pytest.mark.parametrize('case',CORPUS['cases'],ids=lambda case:case['id'])
def test_pinned_json_enum_oracle(runtime,case):
    result=run_case(runtime,case)
    assert result['status']=='passed',result

@pytest.fixture
def strong(runtime):
    runtime.environment['enum_mode']='strong';runtime.analyze()
    return runtime

@pytest.mark.parametrize('formula,expected',[
 ('JSON(ErrorKind.Network)','23'),('JSON(StartOfWeek.Friday)','15'),
 ('JSON(TimeUnit.Months)','"months"'),('JSON(SortOrder.Descending)','"descending"'),
 ('JSON(DateTimeFormat.LongDate)','"\'longdate\'"'),('JSON(JSONFormat.Compact)','""'),
 ('JSON(JSONFormat.IndentFour & JSONFormat.FlattenValueTables)','"4_"'),
 ('JSON({N:ErrorKind.Network,Unit:TimeUnit.Days},JSONFormat.IgnoreUnsupportedTypes)','{"N":23,"Unit":"days"}'),
 ('JSON([JSONFormat.Compact,JSONFormat.IndentFour],JSONFormat.FlattenValueTables)','["","4"]'),
 ('JSON({Z:1,A:{Z:2,A:StartOfWeek.Monday}})','{"A":{"A":2,"Z":2},"Z":1}'),
 ('JSON([1,2],Blank())','[{"Value":1},{"Value":2}]')])
def test_enum_backing_values_and_recursive_json_order(strong,formula,expected):
    assert strong.fx.evaluate(formula,Context(strong,behavior=True))==expected

@pytest.mark.parametrize('formula',[
 'JSON({},"_")','JSON({},JSONFormat.IgnoreBinaryData & "_")',
 'JSON({},Concatenate(JSONFormat.IgnoreBinaryData,"_"))','JSON({},TimeUnit.Days)',
 'JSON({},ErrorKind.Network)','JSON({},true)','JSON({},0)'])
def test_json_format_runtime_guard_does_not_depend_on_editor_diagnostics(strong,formula):
    with pytest.raises(FxError) as caught:strong.fx.evaluate(formula,Context(strong,behavior=True))
    assert caught.value.kind=='Type' and caught.value.end>caught.value.start


def test_concatenated_options_keep_enum_identity_in_tables_and_lazy_error_cells(strong):
    f='Concatenate([JSONFormat.Compact,JSONFormat.IgnoreBinaryData],JSONFormat.FlattenValueTables)'
    typ=strong.binder.bind(strong.fx.parse(f),BindScope())
    assert typ.row.fields['Value'].kind=='Enum' and typ.row.fields['Value'].name=='JSONFormat'
    values=strong.fx.evaluate(f)
    assert [row['Value'].backing for row in values]==['_','G_']
    assert all(isinstance(row['Value'],EnumValue) for row in values)
    assert strong.fx.evaluate('Concatenate(FirstN([JSONFormat.IndentFour],0),1/0)')==[]
    values=strong.fx.evaluate('Concatenate([JSONFormat.Compact,JSONFormat.IndentFour],[JSONFormat.FlattenValueTables])')
    assert values[0]['Value'].backing=='_' and isinstance(values[1]['Value'],FxError)
    assert strong.fx.evaluate('Text(Concatenate(If(false,JSONFormat.Compact),If(false,JSONFormat.IndentFour)))')==''
    assert strong.fx.evaluate('JSON({},Concatenate(If(false,JSONFormat.Compact),If(false,JSONFormat.IndentFour)))',Context(strong,behavior=True))=='{}'


def test_json_error_fields_propagate_and_behavior_boundaries_remain_visible(strong):
    result=strong.fx.evaluate('IfError(JSON({Healthy:23,Broken:1/0}),Text(FirstError.Kind))',Context(strong,behavior=True))
    assert result=='13'
    strong.binder.errors.clear();strong.binder.bind(strong.fx.parse('JSON(ErrorKind.Network)'),BindScope())
    assert any('behavior' in error.message for _,error in strong.binder.errors)
    with pytest.raises(FxError):strong.fx.evaluate('JSON(ErrorKind.Network)')
    assert strong.fx.evaluate('IfError(JSON({},JSONFormat.IncludeBinaryData & JSONFormat.IgnoreBinaryData),Text(FirstError.Kind))',Context(strong,behavior=True))=='25'


@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('mode',['float','decimal'])
def test_json_enum_component_workflow_preserves_owner_runtime_and_records(tmp_path,language,mode):
    from powerapps_sim.fixtures import json_enums_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    p=json_enums_project(tmp_path/'p');w=Workspace(tmp_path,p.root)
    try:
        w.runtime.store.patch('Snapshots',{}, {'Title':'Fictional owner record','Payload':'{}'})
        w.runtime.restart();before=deepcopy(w.ai.read_runtime());rows=deepcopy(w.runtime.store.rows('Snapshots'))
        entry=w.workflows.catalog()['scenarios'][0]
        result=w.workflows.run({**entry['scenario'],'environment':{'enum_mode':'strong','language':language,'number_mode':mode}},expected_revision=revision(p.root))
        assert result['status']=='passed',result['steps']
        assert len(result['steps'])==45 and not result['diagnostics']
        assert result['collections']['results'][0]['Flag']['$enum']['namespace']=='JSONFormat'
        assert len(result['collections']['results'][0])==20
        assert result['types']['collections']['results']['row']['fields']['Nested']['fields']['Option']=={'kind':'Enum','name':'JSONFormat'}
        assert w.ai.read_runtime()==before and w.runtime.store.rows('Snapshots')==rows
    finally:w.runtime.close()

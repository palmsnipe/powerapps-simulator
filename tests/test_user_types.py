"""User-defined type construction and restrictive aggregate contracts."""
import pytest
from powerapps_sim.binding import BindScope
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project,dump_yaml
from powerapps_sim.syntax import FxError


def make(tmp_path, formulas):
    p=Project(tmp_path/'types');p.update_source('Src/app.pa.yaml',dump_yaml({'App':{'Properties':{'Formulas':'='+formulas}},'Screens':{'Home':{}}}))
    r=Runtime(p);r.restart();return r


@pytest.fixture
def types(tmp_path):
    r=make(tmp_path,'''
      Row := Type(RecordOf(Rows));
      Rows := Type([{Name:Text,Amount:Number,Details:{Enabled:Boolean,When:Date}}]);
      Numbers := Type([Number]);
      NumberRow := Type(RecordOf(Numbers));
      MoreRows := Type([Row]);
      SameRow := Type(Row);
      Identity(r:Row):Row=r;
      Echo(rows:Rows):Rows=rows;
      Read(r:Row):Number=Coalesce(r.Amount,0);
      ReadName(r:Row):Text=r.Name;
      Total(rows:Rows):Number=Sum(rows,Amount);
      Nums(numbers:Numbers):Number=Sum(numbers,Value);
      Save(r:Row):Void={Set(saved,r)};
      EmptyRows():Rows=Blank();
      Part():Row={Name:"partial"};
      Good=42;
    ''')
    yield r;r.close()


def bind(r,source):
    r.binder.errors.clear();r.binder.bind(r.fx.parse(source),BindScope(),('test','',0))
    return [e.message for _,e in r.binder.errors]


def test_forward_recordof_aliases_and_scalar_table_shapes(types):
    r=types;assert not r.diagnostics
    row=r.binder.declared_type('Row')
    assert row==r.binder.declared_type('SameRow')==r.binder.declared_type('MoreRows').row
    assert row.fields['Details'].fields['When'].kind=='Date'
    assert r.binder.declared_type('NumberRow').fields['Value'].kind=='Number'
    assert r.fx.evaluate('Nums([1,2,3])')==6
    assert r.fx.evaluate('Read({Amount:7})')==7
    assert not bind(r,'Read({Amount:7})')
    assert r.analysis()['named']['Row']['schema']['kind']=='Record'


def test_partial_records_normalize_missing_fields_without_erasing_blank(types):
    value=types.fx.evaluate('Identity({Name:"one",Details:{Enabled:true}})')
    assert value=={'Name':'one','Amount':None,'Details':{'Enabled':True,'When':None}}
    assert types.fx.evaluate('Part()')=={'Name':'partial','Amount':None,'Details':None}
    assert types.fx.evaluate('Identity({})')=={'Name':None,'Amount':None,'Details':None}
    assert types.fx.evaluate('Identity(Blank())') is None
    assert types.fx.evaluate('Echo(Blank())') is None
    assert types.fx.evaluate('Echo([])')==[]
    assert types.fx.evaluate('Total(EmptyRows())') is None


@pytest.mark.parametrize('expression',[
 'Read({Name:"one",Extra:1})',
 'Identity({Details:{Enabled:true,Extra:1}})',
 'Echo(Table({Amount:1},{Amount:2,Extra:1}))',
 'Echo(FirstN(Table({Amount:1,Extra:1}),0))',
])
def test_extra_fields_including_typed_empty_tables_are_rejected(types,expression):
    assert bind(types,expression)
    with pytest.raises(FxError):types.fx.evaluate(expression)


@pytest.mark.parametrize('expression',[
 'Read({Amount:Color.Red})',
 'Identity({Details:{Enabled:Date(2026,1,1)}})',
 'Nums([{Value:{N:1}}])',
])
def test_incompatible_field_types_are_diagnosed_and_rejected(types,expression):
    assert bind(types,expression)
    with pytest.raises(FxError):types.fx.evaluate(expression)


def test_table_rows_normalize_unions_and_nested_inline_types(types):
    rows=types.fx.evaluate('Echo(Table({Name:"a"},{Amount:2,Details:{When:Date(2026,1,2)}}))')
    assert rows[0]=={'Name':'a','Amount':None,'Details':None}
    assert rows[1]['Name'] is None and rows[1]['Amount']==2
    assert rows[1]['Details']['Enabled'] is None and rows[1]['Details']['When'].kind=='Date'
    assert types.fx.evaluate('Total(Table({Name:"a"},{Amount:2}))')==2


def test_error_cells_stay_lazy_and_behavior_arguments_validate_before_writes(types):
    r=types
    assert r.fx.evaluate('ReadName({Name:"healthy",Amount:1/0})')=='healthy'
    row=r.fx.evaluate('Identity({Amount:1/0})');assert isinstance(row['Amount'],FxError)
    with pytest.raises(FxError):r.fx.evaluate('Save({Extra:1})',Context(r,behavior=True))
    assert 'saved' not in r.globals
    r.fx.evaluate('Save({Amount:4})',Context(r,behavior=True))
    assert r.globals['saved']=={'Name':None,'Amount':4,'Details':None}


@pytest.mark.parametrize('spec',[
 'Type()', 'Type(Text,Number)', 'Type([])', 'Type([Number,Text])',
 'Type({N:Number,N:Text})', 'Type({N:Void})', 'Type(123)',
 'Type(RecordOf(Text))', 'Type(RecordOf({N:Number}))',
 'Type(RecordOf())', 'Type(RecordOf(Rows,Rows))',
 'Type(Table({N:Number}))', 'Type([[Number]])',
])
def test_invalid_type_specs_are_local_diagnostics_with_source_spans(tmp_path,spec):
    r=make(tmp_path,f'Rows:=Type([{{N:Number}}]);Bad:={spec};Good=42;')
    try:
        assert r.diagnostics and r.fx.evaluate('Good')==42
        assert any(d['member']=='App.Formulas.Bad' and d['end']>d['start'] for d in r.diagnostics)
        with pytest.raises(FxError):r.fx.evaluate('Bad')
    finally:r.close()


def test_recursive_types_are_rejected_but_forward_types_are_registered(tmp_path):
    r=make(tmp_path,'A:=Type({Other:B});B:=Type({Other:A});Good=42;')
    try:
        assert r.diagnostics and r.fx.evaluate('Good')==42
        assert r.binder.declared_type('A').kind=='Unknown' or r.binder.declared_type('A').fields['Other'].kind=='Unknown'
    finally:r.close()


@pytest.mark.parametrize('expression',['RecordOf(Rows)','Type(Text)','Row'])
def test_type_values_cannot_be_used_as_runtime_data(types,expression):
    with pytest.raises(FxError,match='type declaration|runtime value'):types.fx.evaluate(expression)
    assert bind(types,expression)


def test_table_column_coercion_preserves_failed_cells(types):
    rows=types.fx.evaluate('Echo(Table({Amount:1},{Amount:"wrong"}))')
    assert rows[0]['Amount']==1 and isinstance(rows[1]['Amount'],FxError)


def test_bad_type_signature_cannot_run_effects_even_with_blank_argument(tmp_path):
    r=make(tmp_path,'Bad:=Type({N:Missing});Act(x:Bad):Void={Set(effect,true)};')
    try:
        with pytest.raises(FxError):r.fx.evaluate('Act(Blank())',Context(r,behavior=True))
        assert 'effect' not in r.globals
    finally:r.close()


def test_return_schema_rejects_additional_fields(tmp_path):
    r=make(tmp_path,'R:=Type({N:Number});Bad():R={N:1,Extra:2};')
    try:
        assert any('incompatible function schema' in d['message'] for d in r.diagnostics)
        with pytest.raises(FxError,match='incompatible function schema'):r.fx.evaluate('Bad()')
    finally:r.close()


def test_projected_lists_component_tables_and_roundtrip_workflow(tmp_path):
    from copy import deepcopy
    from powerapps_sim.fixtures import types_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision,data_revision
    from powerapps_sim.source import load_yaml
    p=types_project(tmp_path/'fixture');w=Workspace(tmp_path,p.root)
    try:
        assert not w.runtime.diagnostics
        source=p.documents['Src/types.pa.yaml']
        assert load_yaml(dump_yaml(load_yaml(source)))==load_yaml(source)
        assert 'RecordOf(ProjectTable)' in p.app['Formulas']
        live=deepcopy(w.runtime.globals);data=data_revision(w.runtime.store)
        entry=w.workflows.catalog()['scenarios'][0]
        result=w.workflows.run(entry['scenario'],expected_revision=revision(p.root))
        assert result['status']=='passed',result['steps']
        assert len(result['steps'])==21 and not result['diagnostics']
        assert w.runtime.globals==live and data_revision(w.runtime.store)==data
        assert result['writes']==[{'list':'Projects','id':2,'operation':'update'}]
    finally:w.runtime.close()


def test_nested_table_type_specs_and_scalar_aliases(tmp_path):
    r=make(tmp_path,'TextAlias:=Type(Text);R:=Type({Values:[Number],Text:TextAlias});Echo(x:R):R=x;')
    try:
        assert not r.diagnostics
        value=r.fx.evaluate('Echo({Values:[1,2]})')
        assert value=={'Values':[{'Value':1},{'Value':2}],'Text':None}
    finally:r.close()

"""Multi-value SharePoint records and direct Choices contracts."""
from copy import deepcopy
from pathlib import Path
import pytest
from powerapps_sim.store import ListStore
from powerapps_sim.binding import BindScope
from powerapps_sim.fx import Context
from powerapps_sim.scenarios import person
from powerapps_sim.syntax import FxError

CHOICE={'type':'object','properties':{'Value':{'type':'string'}},'x-ms-capabilities':{'x-ms-sp':{'IsChoice':True}}}
LOOKUP={'type':'object','properties':{'Id':{'type':'integer'},'Value':{'type':'string'}}}
PERSON={'type':'object','properties':{k:{'type':'string'} for k in ('Claims','Email','DisplayName','Department','JobTitle','Picture')}}
PEOPLE=[person('alex@example.test','Alex Example'),person('sam@example.test','Sam Example')]
DEFINITION={'fields':{'ID':{'type':'integer'},'Title':{'type':'string'},'Tags':{'type':'array','items':CHOICE},'Links':{'type':'array','items':LOOKUP},'Owners':{'type':'array','items':PERSON},'Reviewer':PERSON},'required':['Title','Tags'],'mapping':{'ID':'ID','Title':'Title','Tags':'Project Tags','Links':'Related Projects','Owners':'Project Owners','Reviewer':'Reviewer'},'choices':{'Tags':['Planning','Review','Completed']},'lookups':{'Links':'Projects'}}


def add_complex(r):
    r.store.add_list('Complex',DEFINITION);r.people=deepcopy(PEOPLE);r.analyze();r.invalidate()
    return r.store.patch('Complex',{}, {'Title':'Fictional complex record','Project Tags':[{'Value':'Planning'}],'Related Projects':[{'Id':1,'Value':'Wetland monitoring'}],'Project Owners':[PEOPLE[0]]})


@pytest.fixture
def complex_runtime(runtime):
    add_complex(runtime)
    return runtime


@pytest.mark.parametrize('column,expected',[('Project Tags',[{'Value':'Planning'},{'Value':'Review'},{'Value':'Completed'}]),('Related Projects',[{'Id':1,'Value':'Wetland monitoring'},{'Id':2,'Value':'Building efficiency'},{'Id':3,'Value':'Water assessment'}]),('Project Owners',PEOPLE),('Reviewer',PEOPLE)])
def test_choices_preserve_complex_shapes_and_array_row_type(complex_runtime,column,expected):
    r=complex_runtime;formula=f"Choices(Complex.'{column}')"
    assert r.fx.evaluate(formula)==expected
    typ=r.binder.bind(r.fx.parse(formula),BindScope())
    assert typ.kind=='Table' and typ.row.kind=='Record'
    assert r.fx.evaluate("DataSourceInfo(Complex,DataSourceInfo.Required,'Project Tags')") is True


@pytest.mark.parametrize('column,query,expected',[('Project Tags','re',[{'Value':'Review'}]),('Project Owners','aL',PEOPLE[:1]),('Project Owners','Sam',PEOPLE[1:]),('Project Owners','example',[]),('Reviewer','',PEOPLE),('Related Projects','water',[{'Id':3,'Value':'Water assessment'}])])
def test_choices_optional_filter_is_case_insensitive_prefix(complex_runtime,column,query,expected):
    assert complex_runtime.fx.evaluate(f"Choices(Complex.'{column}',\"{query}\")")==expected


@pytest.mark.parametrize('formula',["Choices(First(Complex).'Project Owners')","Choices(Complex)","Choices(Complex,\"Project Owners\")"])
def test_choices_rejects_indirect_undocumented_references(complex_runtime,formula):
    r=complex_runtime;r.binder.errors.clear();r.binder.bind(r.fx.parse(formula),BindScope())
    assert r.binder.errors
    with pytest.raises(FxError,match='direct data source'):r.fx.evaluate(formula)


@pytest.mark.parametrize('column,value,match',[
 ('Project Tags',[],'required'),('Project Tags',[{'Value':'No such tag'}],'Invalid choice'),('Project Tags',['Planning'],'Choice record'),
 ('Project Tags',[{'Value':3}],'Invalid choice'),('Project Tags',[None],'Choice record'),
 ('Related Projects',[{'Id':999,'Value':'Missing'}],'Missing lookup'),('Related Projects',[{'Id':True,'Value':'Wrong'}],'Lookup record'),
 ('Related Projects',[{'Id':1}],'Lookup record'),('Related Projects',[{'Id':0,'Value':'Wrong'}],'Lookup record'),
 ('Related Projects',[{'Id':1,'Value':99}],'Lookup record'),('Related Projects',[1],'Lookup record'),
 ('Project Owners',[{'Claims':3,'Email':'alex@example.test'}],'Person record'),
 ('Project Owners',[{'Claims':'a','Email':''}],'Person record'),('Project Owners',[{'Email':'alex@example.test'}],'Person record'),
 ('Project Owners',[None],'Person record'),('Project Owners',[{**PEOPLE[0],'DisplayName':99}],'expects string'),
 ('Reviewer',{'Claims':'a','Email':99},'Person record')])
def test_invalid_complex_cells_and_required_arrays_fail_atomically(complex_runtime,column,value,match):
    r=complex_runtime;before=deepcopy(r.store.rows('Complex'))
    with pytest.raises(FxError,match=match):r.store.patch('Complex',before[0],{column:value})
    assert r.store.rows('Complex')==before


def test_patch_from_powerfx_defaults_float_lookup_ids_and_nested_shapes_persist(complex_runtime,tmp_path):
    r=complex_runtime
    row=r.fx.evaluate('Patch(Complex,Defaults(Complex),{Title:"Created by Fx",\'Project Tags\':Table({Value:"Review"}),\'Related Projects\':Table({Id:2,Value:"Water assessment"}),\'Project Owners\':Choices(Complex.\'Project Owners\',"sam")})',Context(r,behavior=True))
    assert row['Related Projects']==[{'Id':2,'Value':'Water assessment'}] and row['Project Owners']==PEOPLE[1:]
    second=ListStore(r.project.root/'data.sqlite')
    try:assert second.rows('Complex')[-1]==row
    finally:second.close()


def test_options_api_includes_person_arrays_and_isolates_lookup_failure(client,complex_runtime):
    data=client.get('/api/lists/Complex').json
    assert data['field_options']['Owners']==PEOPLE
    assert data['field_options']['Tags']==[{'Value':'Planning'},{'Value':'Review'},{'Value':'Completed'}]
    complex_runtime.store.failures['Projects']='read'
    data=client.get('/api/lists/Complex').json
    assert len(data['rows'])==1 and data['field_options']['Owners']==PEOPLE
    assert 'Links' in data['option_errors']


def test_record_editor_complex_failure_retry_and_conflict_are_atomic(client,post,complex_runtime):
    r=complex_runtime;data=client.get('/api/lists/Complex').json
    original=deepcopy(data['rows'][0]);before=deepcopy(r.store.rows('Complex'))
    changes={'Project Tags':[{'Value':'Planning'},{'Value':'Review'}],
             'Related Projects':[{'Id':2,'Value':'Building efficiency'}],
             'Project Owners':deepcopy(PEOPLE)}
    body={'id':original['ID'],'expected_record':original,'expected_revision':data['revision'],'changes':changes}
    r.store.failures['Complex']='write'
    assert post('/api/lists/Complex/items',body).status_code==400
    assert r.store.rows('Complex')==before
    r.store.failures.clear()
    assert post('/api/lists/Complex/items',body).status_code==200
    saved=r.store.rows('Complex')[0]
    assert all(saved[key]==value for key,value in changes.items())
    assert post('/api/lists/Complex/items',body).status_code==409
    assert r.store.rows('Complex')==[saved]


def test_choice_metadata_with_optional_id_is_not_misclassified_as_lookup(runtime):
    shape={**deepcopy(CHOICE),'properties':{'Id':{'type':'integer'},'Value':{'type':'string'}}}
    runtime.store.add_list('ChoiceId',{'fields':{'ID':{'type':'integer'},'States':{'type':'array','items':shape}},'choices':{'States':['Draft']}})
    assert runtime.store.patch('ChoiceId',{}, {'States':[{'Value':'Draft'}]})['States']==[{'Value':'Draft'}]


@pytest.mark.parametrize('items',[[],5,{'type':'invalid'},{'type':'object','properties':{'Value':[]}}])
def test_malformed_nested_schema_is_diagnostic_and_never_saved(runtime,items):
    with pytest.raises(FxError):runtime.store.add_list('Bad',{'fields':{'Rows':{'type':'array','items':items}}})
    assert 'Bad' not in runtime.store.definitions


def test_field_required_flag_and_nested_required_and_length(runtime):
    runtime.store.add_list('Nested',{'fields':{'ID':{'type':'integer'},'Rows':{'type':'array','required':True,'items':{'type':'object','required':['Caption'],'properties':{'Caption':{'type':'string','maxLength':4}}}}}})
    with pytest.raises(FxError,match='Rows is required'):runtime.store.patch('Nested',{}, {'Rows':[]})
    with pytest.raises(FxError,match=r'Rows\[1\].Caption is required'):runtime.store.patch('Nested',{}, {'Rows':[{}]})
    with pytest.raises(FxError,match='maximum length'):runtime.store.patch('Nested',{}, {'Rows':[{'Caption':'long text'}]})
    assert runtime.store.patch('Nested',{}, {'Rows':[{'Caption':'ok'}]})['Rows']==[{'Caption':'ok'}]


def test_missing_column_and_lookup_configuration_are_visible(client,complex_runtime):
    r=complex_runtime
    with pytest.raises(FxError,match='Unknown column'):r.fx.evaluate('Choices(Complex.Missing)')
    r.store.add_list('Unconfigured',{'fields':{'ID':{'type':'integer'},'Links':{'type':'array','items':LOOKUP},'Tags':{'type':'array','items':CHOICE}}})
    gaps=r.store.definitions['Unconfigured']['metadata_gaps']
    assert any('Links:' in g for g in gaps) and any('Tags:' in g for g in gaps)
    data=client.get('/api/lists/Unconfigured').json
    assert set(data['option_errors'])=={'Links','Tags'}
    r.store.definitions['Unconfigured']['lookups']['Links']='Absent'
    with pytest.raises(FxError,match='Configure'):r.store.choices('Unconfigured','Links',r.people)


def test_choices_filter_type_blank_and_global_reference(complex_runtime):
    r=complex_runtime
    assert r.fx.evaluate("Choices([@Complex].'Project Owners',Blank())")==PEOPLE
    with pytest.raises(FxError,match='Text'):r.fx.evaluate("Choices(Complex.'Project Owners',true)")

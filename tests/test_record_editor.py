"""Record editing shares list validation and never replaces unrelated rows."""
from copy import deepcopy
import pytest
from powerapps_sim.fx import Context


def payload(client, **updates):
    data=client.get('/api/lists/Projects').json
    original=data['rows'][0]
    return {'id':original['ID'],'changes':{'Title':'Fictional edited title'},
        'expected_record':original,'expected_revision':data['revision'],**updates}


def test_single_record_edit_preserves_other_rows_and_refreshes_formulas(client,post,runtime):
    before=deepcopy(runtime.store.rows('Projects'))
    data=payload(client)
    result=post('/api/lists/Projects/items',data)
    assert result.status_code==200
    assert result.json['record']['Title']=='Fictional edited title'
    after=runtime.store.rows('Projects')
    assert after[1:]==before[1:]
    assert runtime.fx.evaluate('First(Projects).Title')=='Fictional edited title'
    assert result.json['record']['ID']==before[0]['ID']


def test_create_record_has_defaults_and_allocated_id(client,post,runtime):
    before=deepcopy(runtime.store.rows('Projects'))
    result=post('/api/lists/Projects/items',payload(client,id=None,expected_record=None,
        changes={'Title':'Fictional new row','Status':{'Value':'Draft'}}))
    assert result.status_code==200
    assert result.json['record']['ID']==4
    assert runtime.store.rows('Projects')[:3]==before


def test_stale_record_and_schema_revisions_reject_without_changes(client,post,runtime):
    data=payload(client)
    runtime.store.patch('Projects',data['expected_record'],{'Title':'Newer edit'})
    before=deepcopy(runtime.store.rows('Projects'))
    result=post('/api/lists/Projects/items',data)
    assert result.status_code==409 and result.json['conflict']
    assert runtime.store.rows('Projects')==before
    result=post('/api/lists/Projects/items',payload(client,expected_revision='stale'))
    assert result.status_code==409
    assert runtime.store.rows('Projects')==before


@pytest.mark.parametrize('changes',[{'Title':''},{'ID':99},{'Status':{'Value':'not configured'}},{'Title':'x'*256}])
def test_invalid_record_edit_is_atomic(client,post,runtime,changes):
    before=deepcopy(runtime.store.rows('Projects'))
    assert post('/api/lists/Projects/items',payload(client,changes=changes)).status_code==400
    assert runtime.store.rows('Projects')==before


def test_failure_retains_record_and_same_snapshot_can_retry(client,post,runtime):
    data=payload(client);before=deepcopy(runtime.store.rows('Projects'))
    runtime.store.failures['Projects']='write'
    assert post('/api/lists/Projects/items',data).status_code==400
    runtime.store.failures.clear()
    assert runtime.store.rows('Projects')==before
    assert post('/api/lists/Projects/items',data).status_code==200


@pytest.mark.parametrize('changes',[{'id':True},{'id':-1},{'id':1.5},{'expected_record':None},{'changes':[]},{'extra':'field'}])
def test_malformed_edit_envelope_rejected(client,post,runtime,changes):
    before=deepcopy(runtime.store.rows('Projects'))
    assert post('/api/lists/Projects/items',payload(client,**changes)).status_code in (400,409)
    assert runtime.store.rows('Projects')==before


def test_runtime_state_exposes_screen_context_scopes(runtime,client):
    runtime.fx.evaluate('UpdateContext({draftName:"Fictional draft",flag:false})',Context(runtime,behavior=True))
    state=runtime.state()
    assert state['contexts']['Home']=={'draftName':'Fictional draft','flag':False}
    assert 'draftName' not in state['globals']
    result=client.post('/api/ai/read_runtime',json={'arguments':{}},headers={'X-Emulator-Request':'1'})
    assert result.status_code==200 and result.json['contexts']['Home']==state['contexts']['Home']


def test_record_form_options_preserve_choice_person_and_lookup_shapes(client,runtime):
    definition={'fields':{'ID':{'type':'integer'},'Title':{'type':'string'},'Project':{'type':'object','properties':{'Id':{'type':'integer'},'Value':{'type':'string'}}}},'lookups':{'Project':'Projects'}}
    runtime.store.add_list('Details',definition)
    data=client.get('/api/lists/Projects').json
    assert data['field_options']['Status']==[{'Value':'Draft'},{'Value':'Submitted'},{'Value':'Approved'}]
    assert data['field_options']['Owner'][0]['Claims'].startswith('i:0#.f|membership|')
    detail=client.get('/api/lists/Details').json
    assert detail['field_options']['Project'][0]=={'Id':1,'Value':'Wetland monitoring'}
    assert not detail['option_errors']


def test_option_read_failure_leaves_independent_list_rows_inspectable(client,runtime):
    runtime.store.add_list('Details',{'fields':{'ID':{'type':'integer'},'Project':{'type':'object','properties':{'Id':{'type':'integer'},'Value':{'type':'string'}}}},'lookups':{'Project':'Projects'}})
    runtime.store.failures['Projects']='read'
    result=client.get('/api/lists/Details')
    assert result.status_code==200 and result.json['rows']==[]
    assert 'Project' in result.json['option_errors']
    assert 'Project' not in result.json['field_options']

@pytest.fixture
def nested_editor(app,tmp_path):
    from powerapps_sim.fixtures import record_editor_project
    workspace=app.extensions['workspace']
    workspace.open(record_editor_project(tmp_path/'record-editor'))
    return workspace


def nested_payload(client,changes):
    data=client.get('/api/lists/Drafts').json
    return {'id':1,'expected_record':data['rows'][0],
            'expected_revision':data['revision'],'changes':changes}


def test_nested_edit_preserves_decimal_unknown_keys_and_mapped_names(client,post,nested_editor):
    data=client.get('/api/lists/Drafts').json
    original=data['rows'][0]
    lines=deepcopy(original['Line Items']);lines[0]['Quantity']=5
    lines[1]['Location']={'Site':'Fictional woodland'}
    result=post('/api/lists/Drafts/items',nested_payload(client,{'Line Items':lines,'Optional Tags':[]}))
    assert result.status_code==200,result.json
    saved=result.json['record']
    assert saved['Line Items'][0]['Cost']=={'$decimal':'9007199254740993.123456789'}
    assert saved['Line Items'][0]['Legacy']==original['Line Items'][0]['Legacy']
    assert saved['Line Items'][0]['Location']==original['Line Items'][0]['Location']
    assert saved['Settings']==original['Settings'] and saved['Loose']==original['Loose']
    assert saved['Numeric Values']==[1,2,None] and saved['Optional Tags']==[]
    assert saved['Line Items'][0]['Quantity']==5 and 'Lines' not in saved
    assert nested_editor.runtime.fx.evaluate('Text(First(First(Drafts).Lines).Cost)')=='9007199254740993.123456789'
    assert nested_editor.runtime.fx.evaluate('Sum(First(Drafts).Lines,Quantity)')==8


@pytest.mark.parametrize('failure',['required','integer','length','shape','decimal','nested_required','write'])
def test_nested_edit_failures_are_atomic_and_snapshot_can_retry(client,post,nested_editor,failure):
    original=client.get('/api/lists/Drafts').json['rows'][0]
    lines=deepcopy(original['Line Items']);lines[0]['Quantity']=5
    changes={'Line Items':lines}
    if failure=='required':lines[0]['Description']=''
    elif failure=='integer':lines[0]['Quantity']=1.5
    elif failure=='length':lines[0]['Description']='x'*61
    elif failure=='shape':changes['Line Items']={}
    elif failure=='decimal':lines[0]['Cost']={'$decimal':'invalid'}
    elif failure=='nested_required':lines[0]['Location']={'Code':7}
    else:nested_editor.runtime.store.failures['Drafts']='write'
    assert post('/api/lists/Drafts/items',nested_payload(client,changes)).status_code==400
    nested_editor.runtime.store.failures.clear()
    assert client.get('/api/lists/Drafts').json['rows'][0]==original
    lines=deepcopy(original['Line Items']);lines[0]['Quantity']=5
    assert post('/api/lists/Drafts/items',nested_payload(client,{'Line Items':lines})).status_code==200


def test_nested_workflow_isolated_from_owner_records(nested_editor):
    from powerapps_sim.authoring import revision
    before=deepcopy(nested_editor.runtime.store.rows('Drafts'))
    entry=nested_editor.workflows.catalog()['scenarios'][0]
    result=nested_editor.workflows.run(entry['scenario'],expected_revision=revision(nested_editor.project.root))
    assert result['status']=='passed',result['steps']
    assert len(result['steps'])==6 and not result['diagnostics']
    assert nested_editor.runtime.store.rows('Drafts')==before

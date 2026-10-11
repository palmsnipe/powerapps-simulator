"""Session-local Errors tables: data operations, ownership, filtering and callbacks."""
from copy import deepcopy
import pytest
from powerapps_sim.binding import BindScope
from powerapps_sim.fx import Context
from powerapps_sim.fixtures import remove_project,complex_project
from powerapps_sim.runtime import Runtime,serial
from powerapps_sim.syntax import FxError
from powerapps_sim.store import ListStore
from powerapps_sim.authoring import data_revision,revision


@pytest.fixture
def r(tmp_path):
    runtime=Runtime(remove_project(tmp_path/'errors'));runtime.restart()
    yield runtime
    runtime.close()


def run(r,formula):return r.fx.evaluate(formula,Context(r,behavior=True))
def errs(r,formula='Errors(Projects)'):return r.fx.evaluate(formula)
def bind(r,formula):
    r.binder.errors.clear();typ=r.binder.bind(r.fx.parse(formula),BindScope(),('test','',0))
    return typ,[error for _,error in r.binder.errors]


def failed(r,formula):
    with pytest.raises(FxError) as error:run(r,formula)
    return error.value


def test_empty_history_is_typed_pure_and_has_expected_columns(r):
    assert errs(r)==[] and r.fx.evaluate('IsEmpty(Errors(Projects))') is True
    typ,errors=bind(r,'Errors(Projects)');assert not errors
    assert typ.kind=='Table' and set(typ.row.fields)=={'Record','Column','Message','Error'}
    record=typ.row.fields['Record'];assert record.aliases['Title']=='Project name'
    typ,errors=bind(r,'First(Errors(Projects)).Record.Title');assert not errors and typ.kind=='Text'


def test_failed_create_blank_record_internal_column_and_numeric_kind(r):
    error=failed(r,'Patch(Projects,Defaults(Projects),{Title:Blank()})')
    assert error.kind=='MissingRequired'
    assert errs(r)==[{'Record':None,'Column':'Title','Message':'Project name is required','Error':2}]
    assert errs(r,'Errors(Projects,Blank())')==errs(r)
    assert errs(r,'Errors(Projects,First(Projects))')==[]
    assert len(r.store.rows('Projects'))==3


def test_existing_failure_snapshots_saved_record_and_matches_identity(r):
    failed(r,'Patch(Projects,{ID:2},{Title:Blank()})')
    row=errs(r)[0];assert row['Record']['ID']==2 and row['Record']['Project name']=='Fictional project 2'
    assert errs(r,'Errors(Projects,{ID:2,Title:"Stale title"})')==[row]
    assert errs(r,'Errors(Projects,{ID:1})')==[] and errs(r,'Errors(Projects,Blank())')==[]
    assert r.fx.evaluate('First(Errors(Projects)).Record.Title')=='Fictional project 2'
    row['Record']['Amount']=999;assert errs(r)[0]['Record']['Amount']==20


def test_reading_querying_defaults_choices_and_errors_never_clears(r):
    failed(r,'Patch(Projects,{ID:1},{Title:Blank()})');before=errs(r)
    assert r.fx.evaluate('LookUp(Projects,ID=1).Cost')==10
    r.fx.evaluate('Filter(Projects,true)');r.fx.evaluate('Defaults(Projects)');r.fx.evaluate('Choices(Projects.Status)')
    assert r.fx.evaluate('First(Filter(Errors(Projects),Error=ErrorKind.MissingRequired)).Column')=='Title'
    assert errs(r)==before


def test_successful_retry_and_successful_empty_operation_clear(r):
    failed(r,'Patch(Projects,{ID:1},{Title:Blank()})')
    run(r,'Patch(Projects,{ID:1},{Title:"Fictional retry"})');assert errs(r)==[]
    failed(r,'Patch(Projects,{ID:1},{Title:Blank()})');run(r,'RemoveIf(Projects,false)');assert errs(r)==[]


def test_new_failure_replaces_previous_operation_errors(r):
    failed(r,'Patch(Projects,{ID:1},{Title:Blank()})')
    r.store.failures['Projects']='write';failed(r,'Patch(Projects,{ID:2},{Cost:7})')
    rows=errs(r);assert len(rows)==1 and rows[0]['Record']['ID']==2 and rows[0]['Column'] is None and rows[0]['Error']==23


def test_failed_writes_are_observable_even_while_reads_are_injected(r):
    r.store.failures['Projects']='all';failed(r,'Patch(Projects,{ID:2},{Cost:7})')
    assert len(errs(r))==1 and errs(r)[0]['Record']['ID']==2
    with pytest.raises(FxError):r.fx.evaluate('First(Projects)')
    assert len(errs(r))==1


@pytest.mark.parametrize('operation',['Remove(Projects,{ID:1})','RemoveIf(Projects,true)','Update(Projects,{ID:1},{ID:1,Title:"Fictional"})','UpdateIf(Projects,true,{Cost:1})','Refresh(Projects)'])
def test_connector_preflight_read_failures_enter_error_table(r,operation):
    r.store.failures['Projects']='read';failed(r,operation)
    assert len(errs(r))==1 and errs(r)[0]['Error']==23


def test_refresh_clears_previous_failure_and_records_refresh_failure(r):
    failed(r,'Patch(Projects,{ID:1},{Title:Blank()})');run(r,'Refresh(Projects)');assert errs(r)==[]
    r.store.failures['Projects']='read';failed(r,'Refresh(Projects)')
    assert errs(r)==[{'Record':None,'Column':None,'Message':'Simulated read failure for Projects','Error':23}]
    r.store.failures.clear();run(r,'Refresh(Projects)');assert errs(r)==[]


def test_batch_patch_keeps_prefix_and_attributes_failure_to_second_record(r):
    failed(r,'Patch(Projects,Table({ID:1},{ID:2},{ID:3}),Table({Title:"Fictional prefix"},{Title:Blank()},{Title:"Fictional not reached"}))')
    assert r.store.rows('Projects')[0]['Project name']=='Fictional prefix'
    assert r.store.rows('Projects')[2]['Project name']=='Fictional project 3'
    assert len(errs(r))==1 and errs(r)[0]['Record']['ID']==2


def test_updateif_preserves_multiple_row_failures_across_healthy_writes(r):
    failed(r,'UpdateIf(Projects,ID<>2,{Title:Blank()},true,{Cost:99})')
    assert [row['Record']['ID'] for row in errs(r)]==[1,3]
    assert all(row['Column']=='Title' and row['Error']==2 for row in errs(r))
    assert r.store.rows('Projects')[1]['Amount']==99


def test_remove_missing_records_and_valid_deletes_have_individual_history(r):
    error=failed(r,'Remove(Projects,Table({ID:999},{ID:1},{ID:888}))')
    assert len(error.records())==2
    assert [row['Record']['ID'] for row in errs(r)]==[999,888]
    assert all(row['Error']==7 for row in errs(r))
    assert [row['ID'] for row in r.store.rows('Projects')]==[2,3]


def test_update_missing_and_readonly_field_failures_are_exposed(r):
    failed(r,'Update(Projects,{ID:999},{ID:999,Title:"Fictional missing"})')
    assert len(errs(r))==1 and errs(r)[0]['Error']==7 and errs(r)[0]['Record']['ID']==999
    failed(r,'Patch(Projects,{ID:1},{ID:2})')
    assert errs(r)[0]['Column']=='ID' and errs(r)[0]['Error']==10


def test_collect_batch_has_blank_create_record_and_keeps_prefix(r):
    failed(r,'Collect(Projects,{Title:"Fictional collected"},{Title:Blank()},{Title:"Fictional not collected"})')
    assert len(r.store.rows('Projects'))==4
    assert errs(r)==[{'Record':None,'Column':'Title','Message':'Project name is required','Error':2}]
    run(r,'Collect(Projects,{Title:"Fictional retry"})');assert errs(r)==[]


def test_collection_writes_and_other_datasources_do_not_clear_history(r):
    failed(r,'Patch(Projects,{ID:1},{Title:Blank()})');before=errs(r)
    run(r,'Collect(local,{Title:"Fictional local",Amount:3,Enabled:false});Remove(local,Last(local))')
    r.store.add_list('Other',deepcopy(r.store.definitions['Projects']))
    run(r,'Collect(Other,{Title:"Fictional other"})')
    assert errs(r)==before and r.fx.evaluate('Errors(Other)')==[]


def test_foreign_source_filter_and_invalid_identity_are_rejected_without_clearing(r):
    failed(r,'Patch(Projects,{ID:1},{Title:Blank()})');before=errs(r)
    r.store.add_list('Other',deepcopy(r.store.definitions['Projects']));r.store.patch('Other',{}, {'Title':'Fictional foreign'})
    for formula in ['Errors(Projects,First(Other))','Errors(Projects,{ID:0})','Errors(Projects,{ID:true})','Errors(Projects,{ID:1.5})','Errors(Projects,{ID:"1"})']:
        with pytest.raises(FxError):errs(r,formula)
    assert errs(r)==before


@pytest.mark.parametrize('formula',['Errors()','Errors(Projects,Blank(),Blank())','Errors(local)','Errors(Filter(Projects,true))','Errors(Projects,1)','Errors(Projects,{ID:"1"})','Errors(Projects,{Unknown:1})','With({Projects:local},Errors(Projects))'])
def test_binder_rejects_non_sources_and_invalid_overloads(r,formula):
    assert bind(r,formula)[1]


def test_formula_errors_are_not_connector_history_and_do_not_clear(r):
    failed(r,'Patch(Projects,{ID:1},{Title:Blank()})');before=errs(r)
    failed(r,'Patch(Projects,First(Projects),If(1/0>0,{Cost:1}))')
    assert errs(r)==[]  # Invocation started, but no connector row failed.
    failed(r,'Patch(Projects,{ID:1},{Title:Blank()})')
    failed(r,'If(1/0>0,Patch(Projects,First(Projects),{Cost:1}))');assert errs(r)==before
    failed(r,'RemoveIf(Projects,1/0>0)');assert errs(r)==[]


def test_error_history_is_session_only_and_restart_reset_clear(r):
    failed(r,'Patch(Projects,{ID:1},{Title:Blank()})');before=data_revision(r.store)
    other=ListStore(r.project.root/'data.sqlite')
    try:
        from powerapps_sim.data_errors import rows
        assert rows(other,'Projects')==[] and data_revision(other)==before
    finally:other.close()
    r.restart();assert errs(r)==[]
    failed(r,'Patch(Projects,{ID:1},{Title:Blank()})');r.store.reset();assert errs(r)==[]


def test_keyword_store_calls_track_without_changing_public_signature(r):
    with pytest.raises(FxError):r.store.patch(name='Projects',base={'ID':1},updates={'Title':None})
    assert errs(r)[0]['Record']['ID']==1
    r.store.patch(name='Projects',base={'ID':1},updates={'Cost':3});assert errs(r)==[]


def test_form_failure_events_observe_errors_and_success_clears(tmp_path):
    r=Runtime(complex_project(tmp_path/'form-errors'));r.restart()
    try:
        form=r.global_refs['TaskForm']
        form.control.properties['OnFailure']='=ClearCollect(failures,Errors(Tasks));Set(failureCount,CountRows(Errors(Tasks)))'
        r.analyze();r.store.failures['Tasks']='write';r.event('ComplexScreen/Save','OnSelect')
        assert r.globals['failureCount']==1 and r.collections['failures'][0]['Record']['ID']==1
        assert r.fx.evaluate('TaskForm.ErrorKind')==23
        r.store.failures.clear();r.event('ComplexScreen/Save','OnSelect')
        assert r.fx.evaluate('Errors(Tasks)')==[] and r.collections['failures'][0]['Error']==23
        assert not r.diagnostics
    finally:r.close()


def test_form_multiple_required_cards_are_record_and_column_specific(tmp_path):
    r=Runtime(complex_project(tmp_path/'required-errors'));r.restart()
    try:
        r.event('ComplexScreen/TaskForm/TagsCard/TagsPicker','OnChange',selection=[])
        r.event('ComplexScreen/TaskForm/OwnersCard/OwnersPicker','OnChange',selection=[])
        r.event('ComplexScreen/Save','OnSelect')
        rows=r.fx.evaluate('Errors(Tasks)')
        assert len(rows)==2 and {row['Column'] for row in rows}=={'Tags','Owners'}
        assert all(row['Record']['ID']==1 and row['Error']==2 for row in rows)
        assert r.fx.evaluate('TaskForm.Unsaved') is True
        r.event('ComplexScreen/New','OnSelect');r.event('ComplexScreen/Save','OnSelect')
        assert all(row['Record'] is None for row in r.fx.evaluate('Errors(Tasks)'))
    finally:r.close()


def test_form_callback_data_operation_starts_new_history(tmp_path):
    r=Runtime(complex_project(tmp_path/'callback-errors'));r.restart()
    try:
        form=r.global_refs['TaskForm'];form.control.properties['OnFailure']='=Set(beforeClear,CountRows(Errors(Tasks)));Refresh(Tasks);Set(afterClear,CountRows(Errors(Tasks)))';r.analyze()
        r.store.failures['Tasks']='write';r.event('ComplexScreen/Save','OnSelect')
        assert r.globals['beforeClear']==1 and r.globals['afterClear']==0
    finally:r.close()


def test_http_list_and_ai_readers_expose_errors_without_side_effects(tmp_path):
    from powerapps_sim.web import create_app
    p=remove_project(tmp_path/'api-errors');app=create_app(tmp_path,p.root);w=app.extensions['workspace'];client=app.test_client()
    try:
        failed(w.runtime,'Patch(Projects,{ID:2},{Title:Blank()})');before=w.ai.read_runtime()
        data=client.get('/api/lists/Projects').json
        assert data['errors'][0]['Record']['ID']==2 and data['errors'][0]['Column']=='Title'
        assert w.ai.read_list('Projects')['errors']==serial(errs(w.runtime))
        assert w.ai.read_runtime()==before and before['data_errors']['Projects'][0]['Error']==2
        assert w.runtime.state()['data_errors']['Projects'][0]['Record']['ID']==2
        assert serial(errs(w.runtime))==data['errors']
    finally:w.runtime.close()


def test_isolated_workflow_preserves_live_failure_history(tmp_path):
    from powerapps_sim.application import Workspace
    p=remove_project(tmp_path/'workflow-errors');w=Workspace(tmp_path,p.root)
    try:
        failed(w.runtime,'Patch(Projects,{ID:2},{Title:Blank()})');before=errs(w.runtime)
        result=w.workflows.run(w.workflows.catalog()['scenarios'][0]['scenario'],expected_revision=revision(p.root))
        assert result['status']=='passed' and errs(w.runtime)==before
        assert 'operation_errors' not in p.export_control('Selected')
    finally:w.runtime.close()


@pytest.mark.parametrize('updates,column',[({'Title':'X'*61},'Title'),({'Cost':'wrong'},'Cost'),({'Status':{'Value':'Missing'}},'Status'),({'Due':'wrong'},'Due')])
def test_store_validation_metadata_uses_root_internal_column(r,updates,column):
    with pytest.raises(FxError):r.store.patch('Projects',{'ID':1},updates)
    row=errs(r)[0];assert row['Column']==column and row['Record']['ID']==1


def test_readonly_list_errors_and_kind_aliases(r):
    r.store.definitions['Projects']['writable']=False
    failed(r,'Patch(Projects,{ID:1},{Cost:9})')
    assert errs(r)[0]['Error']==10 and errs(r)[0]['Record']['ID']==1
    assert r.fx.evaluate('ErrorKind.EditPermission')==4
    assert r.fx.evaluate('ErrorKind.DeletePermission')==5
    assert r.fx.evaluate('ErrorKind.ConstraintViolation')==8


def test_error_fixture_workflow_preserves_live_errors_records_and_source(tmp_path):
    from powerapps_sim.application import Workspace
    from powerapps_sim.fixtures import data_errors_project
    p=data_errors_project(tmp_path/'error-fixture');w=Workspace(tmp_path,p.root)
    try:
        before_source=p.documents.copy();failed(w.runtime,'Patch(Projects,{ID:2},{Title:Blank()})')
        w.runtime.store.patch('Projects',{'ID':2},{'Cost':77})
        failed(w.runtime,'Patch(Projects,{ID:2},{Title:Blank()})')
        before_errors=errs(w.runtime);before_data=data_revision(w.runtime.store)
        scenario=w.workflows.catalog()['scenarios'][0]['scenario']
        result=w.workflows.run(scenario,expected_revision=revision(p.root))
        assert result['status']=='passed' and len(result['steps'])==66 and not result['diagnostics'],result['steps']
        assert errs(w.runtime)==before_errors and data_revision(w.runtime.store)==before_data
        assert w.project.documents==before_source and not w.runtime.diagnostics
        exported=p.export_control('ErrorGallery')
        assert 'Errors(Projects)' in exported and 'operation_errors' not in exported
    finally:w.runtime.close()


def test_workflow_report_exposes_candidate_errors_without_live_history_changes(tmp_path):
    from powerapps_sim.application import Workspace
    from powerapps_sim.fixtures import data_errors_project
    p=data_errors_project(tmp_path/'reported-errors');w=Workspace(tmp_path,p.root)
    try:
        failed(w.runtime,'Patch(Projects,{ID:2},{Title:Blank()})');before=errs(w.runtime)
        scenario={'format_version':1,'name':'Fictional failed edit','steps':[{'op':'event','path':'ErrorsScreen/BadEdit','event':'OnSelect'},{'op':'assert','formula':'First(Errors(Projects)).Error','expect':2}]}
        result=w.workflows.run(scenario,expected_revision=revision(p.root))
        assert result['status']=='passed' and result['data_errors']['Projects'][0]['Record']['ID']==1
        assert errs(w.runtime)==before and result['writes']==[]
    finally:w.runtime.close()

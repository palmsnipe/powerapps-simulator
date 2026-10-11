"""Removal contracts, scoped predicates, persistent identity and component isolation."""
import sqlite3
import pytest
from powerapps_sim.source import Project,dump_yaml
from powerapps_sim.runtime import Runtime
from powerapps_sim.store import ListStore
from powerapps_sim.fx import Context
from powerapps_sim.binding import BindScope
from powerapps_sim.syntax import FxError
from powerapps_sim.authoring import data_revision


def definition():
    return {'fields':{'ID':{'type':'integer','x-ms-permission':'read-only'},'Title':{'type':'string'},'Cost':{'type':'number'},'Enabled':{'type':'boolean'},'Status':{'type':'object','properties':{'Value':{'type':'string'}}}},'mapping':{'Title':'Project name','Cost':'Amount'},'required':['Title'],'choices':{'Status':['Draft','Done']}}


@pytest.fixture
def r(tmp_path):
    p=Project(tmp_path/'remove')
    p.update_source('Src/remove.pa.yaml',dump_yaml({'App':{'Properties':{'OnStart':'=ClearCollect(rows,{Title:"A",N:1,Flag:true,Detail:{Code:"x"}},{Title:"A",N:1,Flag:true,Detail:{Code:"x"}},{Title:"B",N:2,Flag:false,Detail:{Code:"y"}});Set(copy,rows);Set(book,{Items:rows});Set(limit,1)'}},'Screens':{'Home':{'Children':[{'Run':{'Control':'ModernButton@1.0.0','Properties':{'OnSelect':'=Blank()'}}}]}}}))
    s=ListStore(p.root/'data.sqlite',schema_root=p.root/'lists')
    for name in ('Projects','Other'):
        s.add_list(name,definition());s.import_rows(name,[{'ID':i,'Title':f'Fictional {i}','Cost':i*10,'Enabled':i!=2,'Status':{'Value':'Draft' if i!=3 else 'Done'}} for i in range(1,4)])
    s.close();runtime=Runtime(p);runtime.restart();assert not runtime.diagnostics
    yield runtime;runtime.close()


def run(r,formula):return r.fx.evaluate(formula,Context(r,behavior=True))
def bound(r,formula,behavior=True):
    r.binder.errors.clear();typ=r.binder.bind(r.fx.parse(formula),BindScope(behavior=behavior),('test','',0))
    return typ,[error for _,error in r.binder.errors]


def test_remove_first_duplicate_returns_table_and_preserves_copies(r):
    result=run(r,'Remove(rows,First(rows))')
    assert len(result)==2 and [row['N'] for row in result]==[1,2]
    assert len(r.globals['copy'])==3 and len(r.globals['book']['Items'])==3
    result.clear();assert len(r.collections['rows'])==2
    typ,errors=bound(r,'Remove(rows,First(rows))');assert typ.kind=='Table' and not errors


@pytest.mark.parametrize('flag',['RemoveFlags.All','"All"','"ALL"','"all"'])
def test_all_flag_removes_all_complete_matches(r,flag):
    assert run(r,'Remove(rows,First(rows),'+flag+')')==[{'Title':'B','N':2,'Flag':False,'Detail':{'Code':'y'}}]


def test_record_variadic_and_table_overloads(r):
    run(r,'Remove(rows,First(rows),Last(rows))')
    assert len(r.collections['rows'])==1 and r.collections['rows'][0]['Title']=='A'
    run(r,'Remove(copy,Table(First(copy),Last(copy)),RemoveFlags.All)')
    assert r.globals['copy']==[] and len(r.collections['rows'])==1


def test_more_than_three_record_arguments(r):
    run(r,'ClearCollect(numbers,{N:1},{N:2},{N:3},{N:4},{N:5})')
    result=run(r,'Remove(numbers,{N:1},{N:2},{N:3},{N:4})')
    assert result==[{'N':5}]


def test_matching_is_planned_before_deletion_for_repeated_requests(r):
    run(r,'Remove(rows,First(rows),First(rows))')
    assert len(r.collections['rows'])==2


def test_partial_record_is_not_a_filter_and_not_found_is_catchable(r):
    assert run(r,'IfError(Remove(rows,{N:1});true,FirstError.Kind=ErrorKind.NotFound)') is True
    assert len(r.collections['rows'])==3


def test_missing_records_collect_errors_while_valid_removals_commit(r):
    with pytest.raises(FxError) as caught:
        run(r,'Remove(rows,{N:99},First(rows),{N:100},Last(rows))')
    assert [e['Kind'] for e in caught.value.records()]==[7,7]
    assert len(r.collections['rows'])==1 and r.collections['rows'][0]['Title']=='A'


def test_nested_record_matches_and_malformed_nested_contract(r):
    run(r,'Remove(rows,{Title:"B",N:2,Flag:false,Detail:{Code:"y"}})')
    assert len(r.collections['rows'])==2
    assert bound(r,'Remove(rows,{Detail:{Wrong:"y"}})')[1]
    with pytest.raises(FxError,match='field type'):
        run(r,'Remove(rows,{Detail:{Wrong:"y"}})')


@pytest.mark.parametrize('value',['Blank()','false','""'])
def test_blank_zero_boolean_and_empty_text_are_distinct(r,value):
    run(r,'ClearCollect(numbers,{N:0})')
    with pytest.raises(FxError):run(r,'Remove(numbers,{N:'+value+'})')
    assert r.collections['numbers']==[{'N':0}]


def test_blank_record_rows_and_empty_argument_tables_are_noops(r):
    assert len(run(r,'Remove(rows,Blank())'))==3
    assert len(run(r,'Remove(rows,Table())'))==3
    run(r,'Remove(rows,Table(Blank(),Last(rows)))');assert len(r.collections['rows'])==2


def test_top_level_argument_errors_prevent_all_removals(r):
    with pytest.raises(FxError):run(r,'Remove(rows,First(rows),If(1/0<2,Last(rows)))')
    assert len(r.collections['rows'])==3


def test_embedded_error_values_are_not_equal_or_silently_replaced(r):
    run(r,'ClearCollect(broken,{N:1/0,Title:"Fictional bad"},{N:2,Title:"Fictional healthy"})')
    with pytest.raises(FxError) as caught:run(r,'Remove(broken,{N:1/0,Title:"Fictional bad"})')
    assert caught.value.kind=='NotFound'
    run(r,'Remove(broken,Last(broken))')
    assert r.fx.evaluate('IsError(First(broken).N)') is True


@pytest.mark.parametrize('formula',[
 'Remove(rows,First(rows),"wrong")','Remove(rows,"All")',
 'Remove(rows,Table(First(rows)),Last(rows))','Remove(rows,First(rows),Table(Last(rows)))',
 'Remove(rows,{N:"1"})','Remove(Projects,{Missing:1})',
 'Remove(rows,First(rows),3)',
])
def test_invalid_arguments_fail_before_any_removal(r,formula):
    assert bound(r,formula)[1]
    with pytest.raises(FxError):run(r,formula)
    assert len(r.collections['rows'])==3


def test_removeif_all_conditions_aliases_and_global_disambiguation(r):
    formula='RemoveIf(rows As R,R.N>=[@limit],R.Flag,CountRows(Filter(copy As C,C.N=R.N))=2)'
    typ,errors=bound(r,formula);assert not errors and typ.kind=='Table'
    assert run(r,formula)==[{'Title':'B','N':2,'Flag':False,'Detail':{'Code':'y'}}]


def test_removeif_false_branches_and_blank_predicates_are_lazy(r):
    assert len(run(r,'RemoveIf(rows,false,1/0=0)'))==3
    assert len(run(r,'RemoveIf(rows,Blank())'))==3
    run(r,'Clear(rows)');assert run(r,'RemoveIf(rows,1/0=0)')==[]


def test_removeif_predicates_fail_without_deleting_healthy_candidates(r):
    with pytest.raises(FxError):run(r,'RemoveIf(rows,If(N=2,1/0=0,true))')
    assert len(r.collections['rows'])==3
    assert bound(r,'RemoveIf(rows,1)')[1]
    with pytest.raises(FxError,match='Boolean'):run(r,'RemoveIf(rows,1)')


def test_removeif_predicates_are_pure_and_cannot_delete_during_evaluation(r):
    assert bound(r,'RemoveIf(rows,IsEmpty(Remove(copy,First(copy))))')[1]
    with pytest.raises(FxError):run(r,'RemoveIf(rows,IsEmpty(Remove(copy,First(copy))))')
    assert len(r.collections['rows'])==3 and len(r.globals['copy'])==3


def test_nested_and_screen_context_owned_table_targets(r):
    run(r,'Remove(book.Items,First(book.Items));RemoveIf(copy,N=2)')
    assert len(r.globals['book']['Items'])==2 and len(r.globals['copy'])==2 and len(r.collections['rows'])==3
    r.global_refs['Run'].control.properties['OnSelect']='=UpdateContext({cache:rows});RemoveIf(cache,N=1)';r.analyze()
    r.event('Home/Run','OnSelect')
    assert r.screen_context['Home']['cache'][0]['Title']=='B' and len(r.collections['rows'])==3 and not r.diagnostics


def test_mutable_typed_blank_table_retains_blank(r):
    run(r,'Set(blankTable,If(false,Table({N:1})))')
    assert run(r,'Remove(blankTable,{N:1})') is None
    assert run(r,'RemoveIf(blankTable,true)') is None


@pytest.mark.parametrize('formula',[
 'Remove(Filter(rows,true),First(rows))','RemoveIf(Table({N:1}),true)',
 'With({rows:Table({N:1})},Remove(rows,{N:1}))',
])
def test_computed_tables_and_row_parameters_are_readonly(r,formula):
    assert bound(r,formula)[1]
    with pytest.raises(FxError,match='read-only|mutable'):run(r,formula)
    assert len(r.collections['rows'])==3


def test_global_disambiguation_bypasses_row_name_shadowing(r):
    run(r,'With({rows:Table({N:99})},Remove([@rows],First([@rows])))')
    assert len(r.collections['rows'])==2


def test_pure_properties_reject_both_remove_functions(r):
    for formula in ('Remove(rows,First(rows))','RemoveIf(rows,true)'):
        assert bound(r,formula,False)[1]
        with pytest.raises(FxError):r.fx.evaluate(formula)
    assert len(r.collections['rows'])==3


def test_source_identity_stale_fields_and_logical_name_mappings(r):
    run(r,'Remove(Projects,{ID:2,Title:"stale"})')
    assert [row['ID'] for row in r.store.rows('Projects')]==[1,3]
    run(r,"RemoveIf(Projects As P,P.Cost>=30,P.'Project name'=\"Fictional 3\")")
    assert r.fx.evaluate('Sum(Projects,Cost)')==10


def test_table_source_records_and_source_backed_collection_identity(r):
    run(r,'ClearCollect(cached,Projects);Remove(cached,{ID:2})')
    assert [row['ID'] for row in r.collections['cached']]==[1,3]
    run(r,'Remove(Projects,Filter(Projects,ID>1))')
    assert [row['ID'] for row in r.store.rows('Projects')]==[1]
    assert len(r.collections['cached'])==2


def test_source_missing_records_are_errors_but_valid_ids_commit(r):
    with pytest.raises(FxError) as caught:run(r,'Remove(Projects,Table({ID:99},{ID:1},{ID:100},{ID:3}))')
    assert len(caught.value.records())==2 and [row['ID'] for row in r.store.rows('Projects')]==[2]


@pytest.mark.parametrize('identity',['true','1.5','0','-1','"1"'])
def test_invalid_source_identity_cannot_delete_a_different_record(r,identity):
    with pytest.raises(FxError):run(r,'Remove(Projects,{ID:'+identity+'})')
    assert len(r.store.rows('Projects'))==3


def test_wrong_source_defaults_or_record_are_not_valid_id_keys(r):
    for base in ('First(Other)','Defaults(Other)','Defaults(Projects)'):
        with pytest.raises(FxError):run(r,'Remove(Projects,'+base+')')
    assert len(r.store.rows('Projects'))==3


def test_source_readonly_write_and_read_failures_are_enforced(r):
    before=r.store.rows('Projects')
    for function in ('Remove(Projects,{ID:1})','RemoveIf(Projects,true)'):
        r.store.definitions['Projects']['writable']=False
        with pytest.raises(FxError,match='read-only'):run(r,function)
        r.store.definitions['Projects']['writable']=True
        for failure in ('write','read'):
            r.store.failures['Projects']=failure
            with pytest.raises(FxError):run(r,function)
            r.store.failures.clear()
        assert r.store.rows('Projects')==before
    run(r,'Remove(Projects,{ID:1})');assert len(r.store.rows('Projects'))==2


def test_deletes_persist_and_id_high_water_survives_reopening(r):
    run(r,'Remove(Projects,{ID:3})')
    store=ListStore(r.project.root/'data.sqlite',schema_root=r.project.root/'lists')
    assert [row['ID'] for row in store.rows('Projects')]==[1,2]
    created=store.patch('Projects',{}, {'Title':'Fictional new','Cost':4})
    assert created['ID']==4;store.close()
    run(r,'RemoveIf(Projects,true)')
    assert run(r,'Patch(Projects,Defaults(Projects),{Title:"Fictional next",Cost:5})')['ID']==5
    assert run(r,'Patch(Other,Defaults(Other),{Title:"Fictional independent",Cost:5})')['ID']==4


def test_explicit_dataset_replace_reset_ids_but_upsert_preserves_high_water(r):
    run(r,'Remove(Projects,{ID:3})')
    r.store.import_rows('Projects',[{'ID':1,'Title':'Fictional imported','Cost':1}])
    assert r.store.patch('Projects',{}, {'Title':'Fictional next','Cost':4})['ID']==4
    r.store.import_rows('Projects',[{'ID':1,'Title':'Fictional reset','Cost':1}],replace=True)
    assert r.store.patch('Projects',{}, {'Title':'Fictional next','Cost':2})['ID']==2
    r.store.reset();assert r.store.patch('Projects',{}, {'Title':'Fictional first','Cost':1})['ID']==1


def test_data_revision_detects_allocation_history_even_when_rows_are_restored(r):
    before=data_revision(r.store);rows=r.store.rows('Projects')
    r.store.patch('Projects',{}, {'Title':'Fictional transient','Cost':4});run(r,'Remove(Projects,{ID:4})')
    assert r.store.rows('Projects')==rows and data_revision(r.store)!=before


def test_failed_creation_does_not_consume_id(r):
    run(r,'Remove(Projects,{ID:3})')
    with pytest.raises(FxError):r.store.patch('Projects',{}, {'Cost':4})
    assert r.store.patch('Projects',{}, {'Title':'Fictional retry','Cost':4})['ID']==4


def test_all_local_rows_are_scanned_beyond_preview_limit(r):
    r.store.import_rows('Projects',[{'ID':i,'Title':f'Fictional {i}','Cost':i} for i in range(1,1002)],replace=True)
    run(r,'RemoveIf(Projects,Cost>500)')
    assert len(r.store.rows('Projects'))==500
    assert r.store.patch('Projects',{}, {'Title':'Fictional next','Cost':1})['ID']==1002


def test_id_migration_preserves_maximum_from_an_existing_database(tmp_path):
    path=tmp_path/'old.sqlite';db=sqlite3.connect(path)
    db.executescript('CREATE TABLE lists(name TEXT PRIMARY KEY,definition TEXT NOT NULL);CREATE TABLE items(list_name TEXT,id INTEGER,record TEXT);INSERT INTO items VALUES("Projects",7,\'{"ID":7,"Title":"Fictional old"}\');')
    db.commit();db.close();store=ListStore(path);store.add_list('Projects',definition())
    store.remove('Projects',{'ID':7});assert store.patch('Projects',{}, {'Title':'Fictional migrated'})['ID']==8;store.close()


def test_id_exhaustion_rejects_new_items_but_allows_explicit_restore_and_updates(r):
    maximum=2**63-1
    r.store.import_rows('Projects',[{'ID':maximum,'Title':'Fictional maximum'}])
    with pytest.raises(FxError,match='exhausted'):r.store.patch('Projects',{}, {'Title':'Fictional overflow'})
    r.store.import_rows('Projects',[{'ID':maximum,'Title':'Fictional restored maximum'}])
    assert r.store.patch('Projects',{'ID':maximum},{'Title':'Fictional edited maximum'})['ID']==maximum
    assert len(r.store.rows('Projects'))==4


def test_component_removals_and_nested_variable_tables_are_isolated(tmp_path):
    component={'AccessAppScope':False,'CustomProperties':{
        'Count':{'PropertyKind':'Output','DataType':'Number','Default':'=CountRows(local)'},
        'NestedCount':{'PropertyKind':'Output','DataType':'Number','Default':'=CountRows(book.Items)'},
        'Changed':{'PropertyKind':'Event','ReturnType':'None','Parameters':[{'count':{'DataType':'Number'}}],'Default':'=Blank()'},
        'Drop':{'PropertyKind':'Action','ReturnType':'None','Default':'=Remove(local,First(local));Panel.Changed(Panel.Count)'},
        'DropNested':{'PropertyKind':'Action','ReturnType':'None','Default':'=RemoveIf(book.Items,N=1)'}},
        'Properties':{'OnReset':'=ClearCollect(local,{N:1},{N:1},{N:2});Set(book,{Items:local})'}}
    source={'App':{'Properties':{'OnStart':'=ClearCollect(local,{N:99});Clear(events);Reset(Left);Reset(Right)'}},'ComponentDefinitions':{'Panel':component},'Screens':{'Home':{'Children':[
        {'Left':{'Control':'CanvasComponent','ComponentName':'Panel','Properties':{'Changed':'=Collect(events,{Title:"Left",Count:count})'}}},
        {'Right':{'Control':'CanvasComponent','ComponentName':'Panel','Properties':{'Changed':'=Collect(events,{Title:"Right",Count:count})'}}}]}}}
    p=Project(tmp_path/'component');p.update_source('Src/component.pa.yaml',dump_yaml(source));runtime=Runtime(p);runtime.restart()
    try:
        run(runtime,'Left.Drop();Left.DropNested()')
        assert runtime.fx.evaluate('Left.Count')==2 and runtime.fx.evaluate('Right.Count')==3
        assert runtime.fx.evaluate('Left.NestedCount')==1 and runtime.fx.evaluate('Right.NestedCount')==3
        assert runtime.collections['local']==[{'N':99}] and runtime.collections['events']==[{'Title':'Left','Count':2}]
        run(runtime,'Right.Drop();Reset(Left)')
        assert runtime.fx.evaluate('Left.Count')==3 and runtime.fx.evaluate('Right.Count')==2
        assert len(runtime.collections['events'])==2 and not runtime.diagnostics
    finally:runtime.close()


def test_clean_removal_fixture_workflow_source_export_and_live_state_isolation(tmp_path):
    from powerapps_sim.fixtures import remove_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    project=remove_project(tmp_path/'fixture');w=Workspace(tmp_path,project.root,start=False)
    try:
        source=(project.root/'Src/remove.pa.yaml').read_bytes()
        w.runtime.store.patch('Projects',{'ID':1},{'Title':'Fictional live edit','Cost':100})
        before=data_revision(w.runtime.store)
        scenario=w.workflows.catalog()['scenarios'][0]['scenario']
        result=w.workflows.run(scenario,expected_revision=revision(project.root))
        assert result['status']=='passed' and len(result['steps'])==62 and not result['diagnostics'],result['steps']
        assert data_revision(w.runtime.store)==before and w.runtime.globals=={}
        assert (project.root/'Src/remove.pa.yaml').read_bytes()==source
        assert 'list_sequences' not in project.export_control('Selected')
        assert 'simulator' not in project.export_control('Left')
    finally:w.runtime.close()

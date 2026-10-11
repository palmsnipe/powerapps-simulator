"""Patch overloads, mutation ownership, provenance and ordered persistent saves."""
import pytest
from powerapps_sim.source import Project,dump_yaml
from powerapps_sim.runtime import Runtime
from powerapps_sim.store import ListStore
from powerapps_sim.fx import Context
from powerapps_sim.binding import BindScope
from powerapps_sim.syntax import FxError


@pytest.fixture
def r(tmp_path):
    p=Project(tmp_path/'patch')
    p.update_source('Src/patch.pa.yaml',dump_yaml({'App':{'Properties':{'OnStart':'=ClearCollect(rows,{Title:"A",N:1,Flag:true,Detail:{Code:"x"}},{Title:"A",N:1,Flag:true,Detail:{Code:"x"}},{Title:"B",N:2,Flag:false,Detail:{Code:"y"}});ClearCollect(empty,First(rows));Clear(empty);Set(tableVariable,rows);Set(nested,{Items:rows,N:7});Set(saved,{N:0})'}},'Screens':{'Home':{'Children':[{'Run':{'Control':'ModernButton@1.0.0','Properties':{'OnSelect':'=Blank()'}}}]}}}))
    d={'fields':{'ID':{'type':'integer','x-ms-permission':'read-only'},'Title':{'type':'string','maxLength':60},'Cost':{'type':'number','default':99},'Enabled':{'type':'boolean'},'Due':{'type':'string','format':'date'},'Status':{'type':'object','properties':{'Value':{'type':'string'}}},'Created':{'type':'string','format':'date-time','x-ms-permission':'read-only'},'Modified':{'type':'string','format':'date-time','x-ms-permission':'read-only'}},'mapping':{'ID':'ID','Title':'Project name','Cost':'Amount'},'required':['Title'],'choices':{'Status':['Draft','Done']}}
    s=ListStore(p.root/'data.sqlite',schema_root=p.root/'lists')
    for name in ('Projects','Other'):
        s.add_list(name,d)
        s.import_rows(name,[{'ID':i,'Title':f'Fictional {i}','Cost':i*10,'Enabled':True,'Status':{'Value':'Draft'},'Created':'2026-01-01T12:00:00Z','Modified':'2026-01-01T12:00:00Z'} for i in range(1,4)])
    s.close();r=Runtime(p);r.environment['clock']='2026-01-01T12:00:00Z';r.restart()
    assert not r.diagnostics
    yield r;r.close()


def run(r,formula):return r.fx.evaluate(formula,Context(r,behavior=True))
def bound(r,formula,behavior=True):
    r.binder.errors.clear();typ=r.binder.bind(r.fx.parse(formula),BindScope(behavior=behavior),('test','',0))
    return typ,[error for _,error in r.binder.errors]


def test_pure_merge_union_later_override_and_no_variable_mutation(r):
    formula='Patch({N:1,Title:"First"},{N:2},{Title:"Last",Flag:true})'
    typ,errors=bound(r,formula,False);assert not errors and set(typ.fields)=={'N','Title','Flag'}
    assert r.fx.evaluate(formula)=={'N':2,'Title':'Last','Flag':True}
    assert run(r,'Patch(saved,{N:8})')=={'N':8} and r.globals['saved']=={'N':0}


def test_pure_merge_blank_and_typed_blank_field(r):
    assert r.fx.evaluate('Patch(Blank(),Blank(),Blank())') is None
    assert r.fx.evaluate('Patch(Blank(),{N:1},Blank())')=={'N':1}
    assert r.fx.evaluate('Patch({N:If(false,1)},{N:2})')=={'N':2}
    assert bound(r,'Patch({N:Blank()},{N:2})',False)[1]


def test_merge_error_cells_are_lazy_and_last_argument_can_replace_them(r):
    assert r.fx.evaluate('Patch({N:1},{N:1/0},{N:2}).N')==2
    assert r.fx.evaluate('Patch({N:1},{Bad:1/0}).N')==1
    assert r.fx.evaluate('IsError(Patch({N:1},{Bad:1/0}).Bad)') is True
    assert r.fx.evaluate('IfError(Patch({N:1},If(1/0<2,{N:3})).N,9)')==9


@pytest.mark.parametrize('formula',[
    'Patch({N:1},{N:"2"})','Patch({N:"1"},{N:2})','Patch({N:1},{N:[2]})',
    'Patch({Detail:{A:1,B:2}},{Detail:{A:3}})','Patch({N:1},2)',
])
def test_merge_type_errors_are_visible_in_pure_formulas(r,formula):
    assert bound(r,formula,False)[1]
    with pytest.raises(FxError):r.fx.evaluate(formula)


def test_patch_first_duplicate_retains_omitted_fields_and_returns_saved_record(r):
    old=r.collections['rows'][0]
    result=run(r,'Patch(rows,First(rows),{N:7},{Title:"Changed"},{N:8})')
    assert result=={'Title':'Changed','N':8,'Flag':True,'Detail':{'Code':'x'}}
    assert r.collections['rows'][1]['N']==1 and old['N']==1
    assert r.fx.evaluate('Sum(rows,N)')==11


def test_missing_full_match_appends_changes_without_old_fields(r):
    result=run(r,'Patch(rows,{Title:"B"},{N:99})')
    assert result=={'Title':None,'N':99,'Flag':None,'Detail':None}
    assert len(r.collections['rows'])==4 and r.collections['rows'][2]['N']==2


def test_collection_defaults_and_empty_declared_schema(r):
    assert r.fx.evaluate('Defaults(empty)')=={'Title':None,'N':None,'Flag':None,'Detail':None}
    result=run(r,'Patch(empty,Defaults(empty),{Title:"Created",N:3})')
    assert result['Title']=='Created' and result['N']==3 and result['Flag'] is None
    assert len(r.collections['empty'])==1
    with pytest.raises(FxError,match='Defaults'):run(r,'Patch(rows,Defaults(empty),{N:3})')


def test_global_and_nested_table_targets_and_assignment_copies(r):
    run(r,'Patch(tableVariable,First(tableVariable),{N:6})')
    run(r,'Patch(nested.Items,Last(nested.Items),{N:9})')
    assert r.globals['tableVariable'][0]['N']==6 and r.globals['nested']['Items'][-1]['N']==9
    assert [row['N'] for row in r.collections['rows']]==[1,1,2]
    assert r.globals['nested']['N']==7
    assert not bound(r,'Patch(nested.Items,First(nested.Items),{N:3})')[1]


def test_global_disambiguation_overcomes_a_record_scope_name(r):
    run(r,'With({tableVariable:Table({N:8})},Patch([@tableVariable],First([@tableVariable]),{N:3}))')
    assert r.globals['tableVariable'][0]['N']==3
    with pytest.raises(FxError,match='read-only'):run(r,'With({tableVariable:Table({N:8})},Patch(tableVariable,First(tableVariable),{N:3}))')


def test_set_data_source_owns_a_snapshot_and_patch_keeps_provenance(r):
    r.global_refs['Run'].control.properties['OnSelect']='=Set(copies,Projects)';r.analyze()
    run(r,'Set(copies,Projects)')
    run(r,'Patch(copies,First(copies),{Cost:7})')
    assert r.globals['copies'][0]['Amount']==7 and r.store.rows('Projects')[0]['Amount']==10
    saved=run(r,'Patch(copies,Patch(Last(copies),{Cost:42}))')
    assert saved['Amount']==42 and len(r.globals['copies'])==3
    assert r.fx.evaluate('First(copies).Title')=='Fictional 1'


def test_blank_single_change_is_ignored_and_blank_base_returns_blank(r):
    assert run(r,'Patch(rows,First(rows),Blank())')['N']==1
    before=list(r.collections['rows'])
    assert run(r,'Patch(rows,Blank(),{N:99})') is None
    assert r.collections['rows']==before


def test_collection_batch_returns_only_patched_rows_in_input_order(r):
    result=run(r,'Patch(rows,Table(Last(rows),First(rows)),Table({N:20},{N:10}),Table({Title:"Last"},{Title:"First"}))')
    assert [row['N'] for row in result]==[20,10] and [row['Title'] for row in result]==['Last','First']
    assert [row['N'] for row in r.collections['rows']]==[10,1,20]


def test_batch_length_and_shape_errors_prevent_all_writes(r):
    before=list(r.collections['rows'])
    with pytest.raises(FxError,match='same number'):run(r,'Patch(rows,rows,Table({N:8}))')
    assert r.collections['rows']==before
    with pytest.raises(FxError):run(r,'Patch(rows,rows,{N:8})')
    assert r.collections['rows']==before


def test_batch_skips_blank_rows_and_stops_on_top_level_error(r):
    result=run(r,'Patch(rows,Table(First(rows),Blank(),Last(rows)),Table({N:8},{N:9},Blank()))')
    assert len(result)==1 and result[0]['N']==8 and r.collections['rows'][-1]['N']==2
    with pytest.raises(FxError):run(r,'Patch(rows,Table(First(rows),1/0,Last(rows)),Table({N:5},{N:6},{N:7}))')
    assert r.collections['rows'][0]['N']==5 and r.collections['rows'][-1]['N']==2


def test_collection_cell_errors_can_be_overridden_before_mutation(r):
    run(r,'Patch(rows,First(rows),{N:1/0},{N:3})')
    assert r.fx.evaluate('First(rows).N')==3
    run(r,'Patch(rows,First(rows),{N:1/0})')
    assert r.fx.evaluate('IsError(First(rows).N)') is True


def test_persistent_single_write_mapping_defaults_and_safe_conversions(r):
    saved=run(r,'Patch(Projects,First(Projects),{Cost:false,Enabled:0,Title:GUID("1d9ec9bf-0000-0000-0000-c2a723a0f49d")})')
    assert saved['Amount']==0 and saved['Enabled'] is False
    assert saved['Project name']=='1d9ec9bf-0000-0000-0000-c2a723a0f49d'
    created=run(r,'Patch(Projects,Defaults(Projects),{Title:"Fictional new",Due:Date(2026,5,1)})')
    assert created['ID']==4 and created['Amount']==99 and created['Due'].kind=='Date'
    assert r.store.rows('Projects')[-1]['Due']=='2026-05-01'


@pytest.mark.parametrize('record', ['{Cost:"12"}','{Enabled:"false"}','{Due:"2026-05-01"}','{Cost:{N:1}}'])
def test_unsafe_field_conversions_are_rejected_before_saving(r,record):
    before=r.store.rows('Projects');formula='Patch(Projects,First(Projects),'+record+')'
    assert bound(r,formula)[1]
    with pytest.raises(FxError,match='Patch field type'):run(r,formula)
    assert r.store.rows('Projects')==before


@pytest.mark.parametrize('record',['{ID:2}','{Created:Now()}','{Modified:Now()}','{Missing:3}'])
def test_protected_and_unknown_fields_are_diagnosed_and_not_saved(r,record):
    before=r.store.rows('Projects');formula='Patch(Projects,First(Projects),'+record+')'
    assert bound(r,formula)[1]
    with pytest.raises(FxError):run(r,formula)
    assert r.store.rows('Projects')==before


def test_base_identity_shapes_and_missing_id_do_not_upsert_deleted_records(r):
    with pytest.raises(FxError,match='integer ID'):run(r,'Patch(Projects,{ID:true},{Title:"Wrong"})')
    with pytest.raises(FxError,match='no longer exists'):run(r,'Patch(Projects,{ID:99},{Title:"Wrong"})')
    assert len(r.store.rows('Projects'))==3
    with pytest.raises(FxError):run(r,'Patch(Projects,{ID:1.5},{Title:"Wrong"})')


def test_defaults_and_connected_record_provenance_must_match_target(r):
    before=r.store.rows('Projects')
    for base in ('Defaults(Other)','First(Other)','First(Table(Defaults(Other)))'):
        with pytest.raises(FxError,match='target data source'):run(r,'Patch(Projects,'+base+',{Title:"Wrong"})')
    assert r.store.rows('Projects')==before


def test_data_source_key_and_update_record_and_table_forms(r):
    result=run(r,'Patch(Projects,Patch(First(Projects),{Cost:8}))')
    assert result['ID']==1 and result['Amount']==8
    result=run(r,'Patch(Projects,ForAll(Filter(Projects,ID>1),Patch(ThisRecord,{Cost:Cost+1})))')
    assert [row['ID'] for row in result]==[2,3] and [row['Amount'] for row in result]==[21,31]
    with pytest.raises(FxError,match='derived'):run(r,'Patch(Projects,{ID:1,Cost:4})')
    with pytest.raises(FxError,match='source-backed'):run(r,'Patch(rows,{N:1})')


def test_multi_create_and_multiple_change_tables(r):
    result=run(r,'Patch(Projects,Table(Defaults(Projects),Defaults(Projects)),Table({Title:"Fictional 4"},{Title:"Fictional 5"}),Table({Cost:4},{Cost:5}))')
    assert [row['ID'] for row in result]==[4,5] and [row['Amount'] for row in result]==[4,5]
    result=run(r,'Patch(Projects,Table({ID:3},{ID:1}),Table({Cost:6},{Cost:7}),Table({Cost:8},{Cost:9}))')
    assert [row['ID'] for row in result]==[3,1] and [row['Amount'] for row in result]==[8,9]
    assert r.store.rows('Projects')[1]['Amount']==20


def test_batch_partial_failure_preserves_committed_prefix_and_skips_later_rows(r):
    assert run(r,'IfError(Patch(Projects,Projects,Table({Title:"First committed"},{Title:Blank()},{Title:"Must not run"}));true,false)') is False
    assert [row['Project name'] for row in r.store.rows('Projects')]==['First committed','Fictional 2','Fictional 3']


def test_overridden_error_cells_save_and_active_error_cells_fail_without_write(r):
    run(r,'Patch(Projects,First(Projects),{Cost:1/0},{Cost:8})')
    assert r.store.rows('Projects')[0]['Amount']==8
    before=r.store.rows('Projects')
    assert run(r,'IfError(Patch(Projects,First(Projects),{Cost:1/0});true,false)') is False
    assert r.store.rows('Projects')==before


def test_injected_write_failure_readonly_and_retry(r):
    before=r.store.rows('Projects');r.store.failures['Projects']='write'
    assert run(r,'IfError(Patch(Projects,Projects,Table({Cost:1},{Cost:2},{Cost:3}));true,false)') is False
    assert r.store.rows('Projects')==before
    r.store.failures.clear();run(r,'Patch(Projects,Projects,Table({Cost:1},{Cost:2},{Cost:3}))')
    assert [row['Amount'] for row in r.store.rows('Projects')]==[1,2,3]
    r.store.definitions['Projects']['writable']=False
    with pytest.raises(FxError,match='read-only'):run(r,'Patch(Projects,First(Projects),{Cost:0})')


def test_logical_aliases_default_records_and_batch_results_have_no_duplicate_columns(r):
    result=run(r,'Patch(Projects,Table(First(Projects)),Table({Title:"Changed",Cost:4}))')
    assert result[0]['Project name']=='Changed' and result[0]['Amount']==4
    assert 'Title' not in result[0] and 'Cost' not in result[0]
    r.global_refs['Run'].control.properties['OnSelect']='=Set(copies,Filter(Projects,false))';r.analyze()
    run(r,'Set(copies,Filter(Projects,false))')
    default=r.fx.evaluate('Defaults(copies)')
    assert 'Title' not in default and 'Project name' in default
    assert 'defaults_for' not in default and 'source_name' not in default


@pytest.mark.parametrize('formula',[
    'Patch(rows,First(rows),{N:3})','Patch(tableVariable,First(tableVariable),{N:3})',
    'Patch(nested.Items,First(nested.Items),{N:3})','Patch(Projects,First(Projects),{Cost:3})',
])
def test_table_mutation_is_forbidden_in_pure_properties(r,formula):
    assert bound(r,formula,False)[1]
    with pytest.raises(FxError,match='Behavior'):r.fx.evaluate(formula)


@pytest.mark.parametrize('target', ['Filter(rows,true)','Table({N:1})','With({N:1},Table(ThisRecord))'])
def test_computed_table_targets_are_rejected(r,target):
    formula='Patch('+target+',First('+target+'),{N:3})'
    assert bound(r,formula)[1]
    with pytest.raises(FxError,match='read-only'):run(r,formula)


def test_many_local_records_are_not_truncated(r):
    r.collections['rows']=[{'Title':str(i),'N':i,'Flag':True,'Detail':{'Code':'x'}} for i in range(1001)]
    result=run(r,'Patch(rows,rows,ForAll(rows,{N:N+1}))')
    assert len(result)==1001 and result[-1]['N']==1001 and len(r.collections['rows'])==1001


def test_component_local_tables_nested_variables_and_callbacks_are_isolated(tmp_path):
    definition={'AccessAppScope':False,'Properties':{'OnReset':'=ClearCollect(local,{N:1},{N:2});Set(book,{Items:local})'},'CustomProperties':{'Total':{'PropertyKind':'Output','DataType':'Number','Default':'=Sum(local,N)'},'BookTotal':{'PropertyKind':'Output','DataType':'Number','Default':'=Sum(book.Items,N)'},'Changed':{'PropertyKind':'Event','ReturnType':'None','Parameters':[{'amount':{'DataType':'Number'}}],'Default':'=Blank()'},'Run':{'PropertyKind':'Action','ReturnType':'None','Default':'=Patch(local,First(local),{N:First(local).N+10});Counter.Changed(Counter.Total)'},'Deep':{'PropertyKind':'Action','ReturnType':'None','Default':'=Patch(book.Items,First(book.Items),{N:20})'}},'Children':[]}
    src={'App':{'Properties':{'OnStart':'=ClearCollect(local,{N:99});Clear(events);Reset(Left);Reset(Right)'}},'ComponentDefinitions':{'Counter':definition},'Screens':{'Home':{'Children':[{'Left':{'Control':'CanvasComponent','ComponentName':'Counter','Properties':{'Changed':'=Collect(events,{N:amount})'}}},{'Right':{'Control':'CanvasComponent','ComponentName':'Counter'}}]}}}
    p=Project(tmp_path/'components');p.update_source('Src/components.pa.yaml',dump_yaml(src));r=Runtime(p);r.restart()
    run(r,'Left.Run();Left.Deep()')
    assert r.fx.evaluate('Left.Total')==13 and r.fx.evaluate('Right.Total')==3
    assert r.fx.evaluate('Left.BookTotal')==22 and r.fx.evaluate('Right.BookTotal')==3
    assert r.collections['local']==[{'N':99}] and r.collections['events']==[{'N':13}]
    assert not r.diagnostics;r.close()


def test_screen_context_table_is_mutable_in_its_screen(r):
    r.global_refs['Run'].control.properties['OnSelect']='=UpdateContext({cached:Table({N:1})});Patch(cached,First(cached),{N:2})'
    r.analyze();r.event('Home/Run','OnSelect')
    assert r.screen_context['Home']['cached']==[{'N':2}] and not r.diagnostics


def test_pure_udf_can_merge_records(r):
    r.project.update_app_property('Formulas','=Merge(a:Number):Number=Patch({N:a},{N:a+1}).N;')
    r.fx.set_definitions(r.project.app.get('Formulas',''));r.analyze();r.restart()
    assert r.fx.evaluate('Merge(2)')==3 and not r.diagnostics


def test_assignment_nested_data_source_and_defaults_copy_provenance(r):
    r.global_refs['Run'].control.properties['OnSelect']='=Set(cached,{Items:Projects});Set(base,Defaults(Other))';r.analyze()
    run(r,'Set(cached,{Items:Projects});Set(base,Defaults(Other))')
    run(r,'Patch(cached.Items,First(cached.Items),{Cost:2})')
    assert r.globals['cached']['Items'][0]['Amount']==2 and r.store.rows('Projects')[0]['Amount']==10
    with pytest.raises(FxError,match='target data source'):run(r,'Patch(Projects,base,{Title:"Wrong"})')


def test_single_record_readonly_metadata_cannot_be_changed(r):
    before=r.store.rows('Projects')
    with pytest.raises(FxError,match='read-only'):run(r,'Patch(Projects,Patch(First(Projects),{Created:DateTime(2020,1,1,0,0,0)}))')
    assert r.store.rows('Projects')==before


def test_snapshot_tables_are_independent_after_collection_update_and_clear(r):
    run(r,'Patch(rows,First(rows),{N:8});Clear(rows)')
    assert [row['N'] for row in r.globals['tableVariable']]==[1,1,2]
    assert [row['N'] for row in r.globals['nested']['Items']]==[1,1,2]


def test_alias_metadata_survives_default_tables_and_record_copies_without_extra_fields(r):
    r.global_refs['Run'].control.properties['OnSelect']='=Set(defaultCopy,Defaults(Projects))';r.analyze()
    run(r,'Set(defaultCopy,Defaults(Projects))')
    result=r.fx.evaluate('First(Table(defaultCopy)).Cost')
    assert result==99
    row=r.fx.evaluate('Patch(First(Projects),{Cost:8})')
    assert row['Amount']==8 and 'Cost' not in row and row.source_name=='Projects'


def test_single_table_batch_keeps_errors_catchable(r):
    before=r.store.rows('Projects')
    assert run(r,'IfError(Patch(Projects,ForAll(Projects,Patch(ThisRecord,{Cost:1/0})));true,false)') is False
    assert r.store.rows('Projects')==before


def test_sqlite_batch_writes_are_visible_to_a_new_connection(r):
    run(r,'Patch(Projects,Table({ID:2},{ID:1}),Table({Cost:7},{Cost:8}))')
    store=ListStore(r.project.root/'data.sqlite',schema_root=r.project.root/'lists')
    assert [row['Amount'] for row in store.rows('Projects')]==[8,7,30]
    store.close()


def test_runtime_only_table_variable_still_validates_its_known_row_shape(r):
    run(r,'Set(dynamicRows,Table({N:1}))')
    with pytest.raises(FxError,match='explicit conversion'):
        run(r,'Patch(dynamicRows,First(dynamicRows),{N:"2"})')
    assert r.globals['dynamicRows']==[{'N':1}]
    run(r,'Patch(dynamicRows,First(dynamicRows),{N:false})')
    assert r.globals['dynamicRows']==[{'N':0}]


def test_clean_patch_fixture_workflow_and_source_round_trip(tmp_path):
    from powerapps_sim.fixtures import patch_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    p=patch_project(tmp_path/'fixture');w=Workspace(tmp_path,p.root,start=False)
    text=(p.root/'Src/patch.pa.yaml').read_text()
    w.runtime.store.patch('Projects',{'ID':1},{'Title':'Fictional live edit','Cost':100})
    before=w.runtime.store.rows('Projects')
    entry=w.workflows.catalog()['scenarios'][0]
    result=w.workflows.run(entry['scenario'],expected_revision=revision(p.root))
    assert result['status']=='passed' and len(result['steps'])==63 and not result['diagnostics']
    assert w.runtime.store.rows('Projects')==before and w.runtime.globals=={}
    assert (p.root/'Src/patch.pa.yaml').read_text()==text
    assert 'simulator' not in p.export_control('Drafts') and 'defaults_for' not in p.export_control('Left')
    w.runtime.close()


@pytest.mark.parametrize('assignment',[
    'UpdateContext({contextCopy:{Items:rows}})',
    'Navigate(Home,ScreenTransition.None,{contextCopy:{Items:rows}})',
])
def test_context_table_assignments_own_nested_values(r,assignment):
    run(r,assignment)
    run(r,'Patch(contextCopy.Items,First(contextCopy.Items),{N:9})')
    assert r.fx.evaluate('First(contextCopy.Items).N')==9
    assert r.fx.evaluate('First(rows).N')==1
    run(r,'Patch(rows,First(rows),{N:7})')
    assert r.fx.evaluate('First(contextCopy.Items).N')==9


def test_collect_record_arguments_own_their_nested_tables(r):
    run(r,'Set(envelope,{Items:rows});ClearCollect(envelopes,envelope)')
    run(r,'Patch(envelope.Items,First(envelope.Items),{N:9})')
    assert r.fx.evaluate('First(envelope.Items).N')==9
    assert r.fx.evaluate('First(First(envelopes).Items).N')==1
    assert r.fx.evaluate('First(rows).N')==1

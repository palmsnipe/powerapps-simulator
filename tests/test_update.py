"""Replacement, row scopes, lazy errors and persistent local table mutations."""
from pathlib import Path
import pytest
from powerapps_sim.source import Project,dump_yaml
from powerapps_sim.runtime import Runtime
from powerapps_sim.store import ListStore
from powerapps_sim.fx import Context
from powerapps_sim.binding import BindScope
from powerapps_sim.syntax import FxError


def definition():
    return {'fields':{'ID':{'type':'integer','x-ms-permission':'read-only'},'Title':{'type':'string','maxLength':60},'Cost':{'type':'number','default':99},'Enabled':{'type':'boolean'},'Due':{'type':'string','format':'date'},'Status':{'type':'object','properties':{'Value':{'type':'string'}}},'Created':{'type':'string','format':'date-time','x-ms-permission':'read-only'},'Modified':{'type':'string','format':'date-time','x-ms-permission':'read-only'}},'mapping':{'ID':'ID','Title':'Project name','Cost':'Amount','Enabled':'Enabled','Due':'Due','Status':'Status','Created':'Created','Modified':'Modified'},'required':['Title'],'choices':{'Status':['Draft','Done']}}


@pytest.fixture
def r(tmp_path):
    p=Project(tmp_path/'update')
    p.update_source('Src/update.pa.yaml',dump_yaml({'App':{'Properties':{'OnStart':'=ClearCollect(rows,{Title:"A",N:1,Flag:true,Detail:{Code:"x"}},{Title:"A",N:1,Flag:true,Detail:{Code:"x"}},{Title:"B",N:2,Flag:false,Detail:{Code:"y"}});Set(limit,1)'}},'Screens':{'Home':{'Children':[{'Run':{'Control':'ModernButton@1.0.0','Properties':{'OnSelect':'=Blank()'}}}]}}}))
    s=ListStore(p.root/'data.sqlite',schema_root=p.root/'lists');s.add_list('Projects',definition());s.import_rows('Projects',[{'ID':1,'Title':'Fictional A','Cost':10,'Enabled':True,'Created':'2026-01-01T12:00:00Z','Modified':'2026-01-01T12:00:00Z','Status':{'Value':'Draft'}},{'ID':2,'Title':'Fictional B','Cost':20,'Enabled':False,'Created':'2026-01-01T12:00:00Z','Modified':'2026-01-01T12:00:00Z','Status':{'Value':'Draft'}},{'ID':3,'Title':'Fictional C','Cost':30,'Enabled':True,'Created':'2026-01-01T12:00:00Z','Modified':'2026-01-01T12:00:00Z','Status':{'Value':'Done'}}]);s.close()
    r=Runtime(p);r.restart();assert not r.diagnostics
    yield r;r.close()


def run(r,formula):return r.fx.evaluate(formula,Context(r,behavior=True))
def bound(r,formula,behavior=True):
    r.binder.errors.clear();typ=r.binder.bind(r.fx.parse(formula),BindScope(behavior=behavior),('test','',0))
    return typ,[error for _,error in r.binder.errors]


def test_replace_first_duplicate_and_blank_omitted_collection_fields(r):
    result=run(r,'Update(rows,First(rows),{Title:"Changed",N:10})')
    assert result[0]=={'Title':'Changed','N':10,'Flag':None,'Detail':None}
    assert result[1]['Title']=='A' and len(result)==3
    assert r.fx.evaluate('Sum(rows,N)')==13
    typ,errors=bound(r,'Update(rows,First(rows),{Title:"Changed",N:10})');assert not errors and typ.kind=='Table'


def test_replace_all_duplicates_entire_match_and_no_creation(r):
    run(r,'Update(rows,First(rows),{Title:"Changed",N:10},RemoveFlags.All)')
    assert [row['Title'] for row in r.collections['rows']]==['Changed','Changed','B']
    before=[dict(row) for row in r.collections['rows']]
    with pytest.raises(FxError,match='not found'):run(r,'Update(rows,{Title:"Changed"},{N:0})')
    assert r.collections['rows']==before


@pytest.mark.parametrize('old',[{'N':None},{'N':False},{'N':''}])
def test_matching_does_not_conflate_blank_zero_bool_or_text(r,old):
    from powerapps_sim.mutations import matches
    assert not matches({'N':0},old)
    assert matches({'N':None},{'N':None})


def test_matching_nested_records_and_tables(r):
    from powerapps_sim.mutations import matches
    assert matches({'A':{'B':[{'N':1}]}},{'A':{'B':[{'N':1}]}})
    assert not matches({'A':{'B':[{'N':1}]}},{'A':{'B':[{'N':2}]}})
    assert not matches({'A':1},{'A':1,'B':None})


def test_updateif_first_condition_lazy_change_and_original_row_values(r):
    result=run(r,'UpdateIf(rows,N=1,{N:N+10,Title:ThisRecord.Title&"!"},true,{N:1/0})')
    assert result[0]['N']==11 and result[1]['N']==11
    assert result[0]['Title']=='A!' and result[0]['Flag'] is True
    assert isinstance(result[2]['N'],FxError)
    assert r.fx.evaluate('First(rows).Title')=='A!'
    assert r.fx.evaluate('IsError(Last(rows).N)') is True


def test_updateif_aliases_disambiguation_nested_scopes_and_bound_return(r):
    formula='UpdateIf(rows As R,R.N>=limit,{N:Sum(Filter(rows As S,S.N=R.N),S.N),Title:R.Title&Text(rows[@N])})'
    # Nested scopes retain R, but the scoped source alias S is local to Filter.
    formula='UpdateIf(rows As R,R.N>=limit,{N:Sum(Filter(rows As S,S.N=R.N),N),Title:R.Title&Text(rows[@N])})'
    typ,errors=bound(r,formula);assert not errors and typ.row.fields['N'].kind=='Number'
    run(r,formula)
    assert [row['N'] for row in r.collections['rows']]==[2,1,4]  # Queries observe earlier committed updates.
    assert [row['Title'] for row in r.collections['rows']]==['A1','A1','B2']


def test_updateif_false_branches_and_zero_rows_do_not_evaluate_changes(r):
    assert run(r,'UpdateIf(rows,false,Error({Kind:ErrorKind.Validation,Message:"unused"}))')==r.collections['rows']
    run(r,'Clear(rows)');assert run(r,'UpdateIf(rows,true,Error({Kind:ErrorKind.Validation,Message:"unused"}))')==[]


def test_updateif_conditions_are_boolean_and_errors_do_not_block_healthy_rows(r):
    with pytest.raises(FxError,match='Boolean'):run(r,'UpdateIf(rows,1,{N:0})')
    with pytest.raises(FxError,match='broken'):
        run(r,'UpdateIf(rows,If(N=1,Error({Kind:ErrorKind.Validation,Message:"broken"}),true),{N:N+1})')
    assert [row['N'] for row in r.collections['rows']]==[1,1,3]


def test_data_source_replacement_blanks_fields_ignores_defaults_and_preserves_id(r):
    before=r.store.rows('Projects')[0]
    result=run(r,'Update(Projects,First(Projects),{ID:1,Title:"Replacement"})')
    assert result[0]['Project name']=='Replacement' and result[0]['Amount'] is None
    assert result[0]['Enabled'] is None and result[0]['Status'] is None and result[0]['ID']==1
    assert r.store.rows('Projects')[0]['Created']==before['Created'] and result[0]['Modified']
    assert not bound(r,'Update(Projects,First(Projects),{ID:1,Title:"Replacement"})')[1]


def test_data_source_old_record_matches_identity_not_stale_fields(r):
    result=run(r,'Update(Projects,{ID:2,Title:"stale"},{ID:2,Title:"Replaced B",Cost:50},RemoveFlags.All)')
    assert result[1]['Project name']=='Replaced B' and result[1]['Amount']==50
    assert len(result)==3


def test_data_source_display_and_internal_names_in_row_scopes_and_members(r):
    formula="UpdateIf(Projects As P,P.Cost>=20,{Cost:P.Cost+5,Title:P.'Project name'&\"!\",Enabled:!P.Enabled})"
    assert not bound(r,formula)[1]
    result=run(r,formula);assert [row['Amount'] for row in result]==[10,25,35]
    assert [row['Project name'] for row in result]==['Fictional A','Fictional B!','Fictional C!']
    assert r.fx.evaluate('Sum(Projects,Cost)')==70
    assert r.fx.evaluate('First(Projects).Cost')==10


def test_data_source_partial_updates_preserve_fields_choices_dates_and_reactivity(r):
    run(r,'UpdateIf(Projects,ID=1,{Cost:Amount+7,Status:{Value:"Done"},Due:Date(2026,4,5)})')
    row=r.store.rows('Projects')[0]
    assert row['Amount']==17 and row['Status']=={'Value':'Done'} and row['Due']=='2026-04-05'
    assert row['Project name']=='Fictional A' and row['Enabled'] is True
    assert r.fx.evaluate('First(Projects).Due').kind=='Date'
    assert r.fx.evaluate('Sum(Projects,Amount)')==67


@pytest.mark.parametrize('formula,match',[
 ('Update(Projects,First(Projects),{Title:"Missing ID"})','reaffirm'),
 ('Update(Projects,First(Projects),{ID:7,Title:"Changed ID"})','reaffirm'),
 ('UpdateIf(Projects,true,{ID:7})','read-only'),
 ('UpdateIf(Projects,true,{Created:"2026-01-01T00:00:00Z"})','read-only'),
 ('Update(Projects,First(Projects),{ID:1,Title:"Ok",Created:"2026-01-01T00:00:00Z"})','read-only'),
 ('Update(Projects,First(Projects),{ID:1})','required'),
 ('UpdateIf(Projects,true,{Status:{Value:"Invalid"}})','choice'),
 ('UpdateIf(Projects,true,{Missing:1})','Unknown update column'),
])
def test_invalid_writes_do_not_commit(r,formula,match):
    before=r.store.rows('Projects')
    with pytest.raises(FxError,match=match):run(r,formula)
    assert r.store.rows('Projects')==before


def test_update_can_reaffirm_all_readonly_fields(r):
    assert not bound(r,'Update(Projects,First(Projects),First(Projects))')[1]
    run(r,'Update(Projects,First(Projects),First(Projects))')
    assert r.store.rows('Projects')[0]['Project name']=='Fictional A'


def test_persisted_partial_success_and_combined_errors(r):
    with pytest.raises(FxError,match='required'):
        run(r,'UpdateIf(Projects,true,{Title:If(ID=2,Blank(),Title&" saved")})')
    assert [row['Project name'] for row in r.store.rows('Projects')]==['Fictional A saved','Fictional B','Fictional C saved']
    store=ListStore(r.project.root/'data.sqlite',schema_root=r.project.root/'lists')
    assert store.rows('Projects')==r.store.rows('Projects');store.close()
    assert r.fx.evaluate('First(Projects).Title')=='Fictional A saved'


def test_write_failures_readonly_and_catchable_errors(r):
    before=r.store.rows('Projects');r.store.failures['Projects']='write'
    assert run(r,'IfError(UpdateIf(Projects,true,{Cost:0});true,false)') is False
    assert r.store.rows('Projects')==before
    r.store.failures.clear();r.store.definitions['Projects']['writable']=False
    with pytest.raises(FxError,match='read-only'):run(r,'UpdateIf(Projects,true,{Cost:0})')
    assert r.store.rows('Projects')==before


@pytest.mark.parametrize('formula',[
 'Update(rows,First(rows))','Update(rows,First(rows),{N:0},RemoveFlags.All,1)',
 'UpdateIf(rows,true,{N:0},false)','UpdateIf(rows,42,{N:0})',
 'UpdateIf(rows,true,42)','UpdateIf(rows,true,{N:{X:1}})',
 'UpdateIf(Filter(rows,true),true,{N:0})','UpdateIf(Table({N:1}),true,{N:0})',
])
def test_static_contracts_reject_unsupported_types_and_targets(r,formula):
    assert bound(r,formula)[1]


def test_behavior_only_and_invalid_flags(r):
    assert bound(r,'UpdateIf(rows,true,{N:0})',False)[1]
    with pytest.raises(FxError,match='Behavior'):r.fx.evaluate('UpdateIf(rows,true,{N:0})')
    with pytest.raises(FxError,match='RemoveFlags.All'):run(r,'Update(rows,First(rows),{N:0},"bad")')
    assert [row['N'] for row in r.collections['rows']]==[1,1,2]


def test_no_truncation_at_gallery_preview_limit(r):
    r.collections['rows']=[{'Title':str(i),'N':i,'Flag':True,'Detail':{'Code':'x'}} for i in range(1001)]
    run(r,'UpdateIf(rows,N>=500,{N:N+1})')
    assert r.collections['rows'][-1]['N']==1001 and r.collections['rows'][499]['N']==499


def test_numeric_identity_text_coercion_and_boolean_rejection(r):
    run(r,'Update(Projects,{ID:"1"},{ID:1,Title:"Reaffirmed"})')
    assert r.store.rows('Projects')[0]['Project name']=='Reaffirmed'
    with pytest.raises(FxError,match='integer ID'):run(r,'Update(Projects,{ID:true},{ID:1,Title:"Wrong"})')


def test_identity_display_name_mapping(r):
    r.store.definitions['Projects']['mapping']['ID']='Item number';r.store.save_definition('Projects');r.analyze();r.invalidate()
    assert not bound(r,"Update(Projects,First(Projects),{'Item number':1,Title:\"Mapped\"})")[1]
    run(r,"Update(Projects,First(Projects),{'Item number':1,Title:\"Mapped\"})")
    assert r.store.rows('Projects')[0]['Item number']==1
    run(r,"UpdateIf(Projects,ID=1,{Cost:3})")
    assert r.store.rows('Projects')[0]['Amount']==3


def test_decimal_temporal_and_scalar_conversion_for_updates(r):
    r.environment['number_mode']='decimal';r.invalidate()
    run(r,'UpdateIf(Projects,ID=1,{Cost:"12.5",Enabled:"false",Due:"2026-06-02"})')
    row=r.store.rows('Projects')[0]
    assert row['Amount']==12.5 and row['Enabled'] is False and row['Due']=='2026-06-02'
    run(r,'UpdateIf(rows,N=1,{N:"2.5",Flag:"false"})')
    assert r.collections['rows'][0]['N']==2.5 and r.collections['rows'][0]['Flag'] is False


def test_bad_argument_types_do_not_match_or_write(r):
    before=list(r.collections['rows'])
    with pytest.raises(FxError,match='expected'):run(r,'Update(rows,{Title:"A",N:{X:1}},{N:0})')
    assert bound(r,'Update(rows,{Title:"A",N:{X:1}},{N:0})')[1]
    assert r.collections['rows']==before


def test_component_local_mutation_and_global_collection_isolation(tmp_path):
    p=Project(tmp_path/'components')
    definition={'AccessAppScope':False,'Properties':{'OnReset':'=ClearCollect(local,{N:1},{N:2})'},'CustomProperties':{'Total':{'PropertyKind':'Output','DataType':'Number','Default':'=Sum(local,N)'},'Run':{'PropertyKind':'Action','ReturnType':'None','Default':'=UpdateIf(local,N>0,{N:N+10})'}},'Children':[]}
    src={'App':{'Properties':{'OnStart':'=ClearCollect(local,{N:99})'}},'ComponentDefinitions':{'Counter':definition},'Screens':{'Home':{'Children':[{'Left':{'Control':'CanvasComponent','ComponentName':'Counter'}},{'Right':{'Control':'CanvasComponent','ComponentName':'Counter'}}]}}}
    p.update_source('Src/components.pa.yaml',dump_yaml(src));r=Runtime(p);r.restart()
    r.reset_ref(r.global_refs['Left']);r.reset_ref(r.global_refs['Right']);run(r,'Left.Run()')
    assert r.fx.evaluate('Left.Total')==23 and r.fx.evaluate('Right.Total')==3
    assert r.collections['local']==[{'N':99}] and not r.diagnostics
    r.close()


def test_collection_copied_from_list_resolves_logical_names_without_duplicate_columns(r):
    control=r.global_refs['Run'].control
    control.properties['OnSelect']='=ClearCollect(copies,Projects);UpdateIf(copies,Cost>0,{Cost:Cost+1})'
    r.analyze();r.run_event(r.global_refs['Run'],'OnSelect')
    assert [row['Amount'] for row in r.collections['copies']]==[11,21,31]
    assert all('Cost' not in row for row in r.collections['copies'])
    run(r,'Update(copies,First(copies),{ID:1,Title:"Changed"})')
    row=r.collections['copies'][0]
    assert row['Project name']=='Changed' and row['Amount'] is None and 'Title' not in row
    assert not r.diagnostics


def test_duplicate_aliases_are_diagnosed_and_do_not_write(r):
    before=r.store.rows('Projects')
    with pytest.raises(FxError,match='Duplicate aliases'):
        run(r,'UpdateIf(Projects,ID=1,{Cost:1,Amount:2})')
    assert r.store.rows('Projects')==before


def test_dynamic_copied_table_type_retains_aliases_without_exporting_extra_fields(r):
    from powerapps_sim.binding import value_type
    r.collections['copies']=r.store.rows('Projects');r.known_collections.add('copies');r.invalidate()
    typ=value_type(r.collections['copies']).row
    r.binder.collections['copies']=value_type(r.collections['copies'])
    assert typ.aliases['Title']=='Project name' and 'Title' not in typ.fields
    assert r.fx.evaluate('First(copies).Title')=='Fictional A'
    run(r,'UpdateIf(copies,Cost>0,{Cost:"7"})')
    assert [row['Amount'] for row in r.collections['copies']]==[7,7,7]
    assert all('Cost' not in row for row in r.collections['copies'])


def test_gallery_alias_members_remain_closed_to_unknown_fields(r):
    from powerapps_sim.fx import Context
    item=r.store.rows('Projects')[0]
    ctx=Context(r,item=item)
    assert r.fx.evaluate('ThisItem.Title',ctx)=='Fictional A'
    assert r.fx.evaluate('ThisItem.Cost',ctx)==10
    with pytest.raises(FxError,match='Unknown field'):r.fx.evaluate('ThisItem.Missing',ctx)


def test_mapped_record_types_do_not_share_wrong_member_binding_cache(r):
    from powerapps_sim.tables import SourceRecord
    a=SourceRecord({'Display':1},logical_names={'Display':'First'})
    b=SourceRecord({'Display':2},logical_names={'Display':'Second'})
    assert r.fx.evaluate('ThisItem.First',Context(r,item=a))==1
    with pytest.raises(FxError,match='Unknown field'):r.fx.evaluate('ThisItem.First',Context(r,item=b))


@pytest.mark.parametrize('container,formula',[
    (lambda row:{'row':row},'payload.row.First'),
    (lambda row:{'rows':[row]},'First(payload.rows).First'),
])
def test_nested_mapped_types_do_not_reuse_another_scope_alias(r,container,formula):
    from powerapps_sim.tables import SourceRecord
    a=SourceRecord({'Display':1},{'Display':'First'})
    b=SourceRecord({'Display':2},{'Display':'Second'})
    assert r.fx.evaluate(formula,Context(r,frames=[{'payload':container(a)}]))==1
    with pytest.raises(FxError,match='Unknown field'):
        r.fx.evaluate(formula,Context(r,frames=[{'payload':container(b)}]))


def test_clean_update_fixture_isolated_workflow_and_source_round_trip(tmp_path):
    from powerapps_sim.fixtures import update_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    p=update_project(tmp_path/'fixture');w=Workspace(tmp_path,p.root,start=False)
    scenario=w.workflows.catalog()['scenarios'][0]['scenario'];assert len(scenario['steps'])==40
    before=w.runtime.store.rows('Projects');text=(p.root/'Src/update.pa.yaml').read_text()
    result=w.workflows.run(scenario,expected_revision=revision(p.root));assert result['status']=='passed',result['steps']
    assert w.runtime.globals=={} and w.runtime.store.rows('Projects')==before
    assert (p.root/'Src/update.pa.yaml').read_text()==text
    assert 'simulator' not in p.export_control('BumpList')
    w.runtime.close()

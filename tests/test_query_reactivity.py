"""Query result precision, live record scopes and volatile row lifetimes."""
from copy import deepcopy
import pytest
from powerapps_sim.application import Workspace
from powerapps_sim.fixtures import reactive_cells_project
from powerapps_sim.source import Control
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError

@pytest.fixture(params=[('float','en-CA'),('decimal','en-CA'),('float','fr-CA'),('decimal','fr-CA')])
def workspace(tmp_path,request):
    p=reactive_cells_project(tmp_path/'project');w=Workspace(tmp_path,p.root)
    w.runtime.environment.update(number_mode=request.param[0],language=request.param[1]);w.runtime.restart()
    yield w
    w.runtime.close()

def states(r):return {k:v.getstate() for k,v in r.reactive.streams.items()}
def rule(r,formula,name='QueryProbe'):
    return r.build(Control(name,'ModernText@1.0.0',{'Properties':{'Text':'='+formula}},'Src/reactive-cells.pa.yaml'),'ReactiveLab/'+name)
def patch(r,values):
    r.store.patch('Cards',r.store.rows('Cards')[0],values);r.invalidate()

@pytest.mark.parametrize('formula',[
 'Sum(Cards,Amount)+Rand()', 'Average(Cards,Amount)+Rand()',
 'Min(Cards,Amount)+Rand()', 'Max(Cards,Amount)+Rand()',
 'VarP(Cards,Amount)+Rand()', 'StdevP(Cards,Amount)+Rand()',
 'CountRows(Filter(Cards,Amount>0))+Rand()', 'CountIf(Cards,Amount>0)+Rand()',
 'Count(ShowColumns(Cards,Amount))+Rand()', 'CountA(ShowColumns(Cards,Amount))+Rand()',
 'LookUp(Cards,ID=1,Amount)+Rand()', 'LookUp(Cards,ID=1).Amount+Rand()',
 'First(Cards).Amount+Rand()', 'Last(Cards).Amount+Rand()', 'Index(Cards,2).Amount+Rand()',
 'Sum(FirstN(Cards,2),Amount)+Rand()', 'Sum(LastN(Cards,2),Amount)+Rand()',
 'Sum(Sort(Cards,Amount),Amount)+Rand()', 'Sum(SortByColumns(Cards,"Amount"),Amount)+Rand()',
 'Sum(AddColumns(Cards,Computed,Amount*2),Computed)+Rand()',
 'Sum(DropColumns(Cards,Title),Amount)+Rand()',
 'Sum(RenameColumns(ShowColumns(Cards,Amount),Amount,Computed),Computed)+Rand()',
 'Sum(ForAll(Cards,Amount),Value)+Rand()', 'Sum(Distinct(Cards,Amount),Value)+Rand()',
 'Sum(Ungroup(GroupBy(Cards,Amount,Rows),Rows),Amount)+Rand()',
 'CountRows(Search(Cards,"Fictional",Title))+Rand()',
 'Len(Concat(Cards,Text(Amount),"|"))+Rand()',
 'With({constant:2},Sum(Cards,Amount+constant))+Rand()',
])
def test_unread_fields_do_not_recalculate_consumers(workspace,formula):
    r=workspace.runtime;ref=rule(r,formula);first=ref.property('Text');draws=states(r)
    patch(r,{'Title':'Fictional renamed'})
    assert ref.property('Text')==first and states(r)==draws
    r.invalidate();assert ref.property('Text')==first and states(r)==draws

@pytest.mark.parametrize('formula',[
 'Sum(Cards,Amount+Rand())+Rand()',
 'Sum(Cards As card,card.Amount+Rand())+Rand()',
 'Sum(Cards,Cards[@Amount]+Rand())+Rand()',
 'Sum(Cards,ThisRecord.Amount+Rand())+Rand()',
 'Sum(AddColumns(Cards,Noise,Amount+Rand()),Noise)+Rand()',
 'Sum(ForAll(Cards,{ID:ID,N:Amount+Rand()}),N)+Rand()',
 'Len(Concat(Cards,Text(Amount+Rand()),"|"))+Rand()',
 'Concat(Cards As outer,Text(outer.Amount+LookUp(Cards As inner,inner.ID=outer.ID,inner.Amount+Rand())),"|") & Text(Rand())',
])
def test_volatile_rows_keep_draws_and_recalculate_only_read_rows(workspace,formula):
    r=workspace.runtime;ref=rule(r,formula);first=ref.property('Text');draws=states(r)
    patch(r,{'Title':'Fictional renamed'});assert ref.property('Text')==first and states(r)==draws
    patch(r,{'Amount':55});assert ref.property('Text')!=first
    changed=[k for k,v in draws.items() if states(r).get(k)!=v]
    assert changed
    # Rows 2 and 3 retain their streams even inside nested aliased queries.
    def row_ids(key):
        found=[]
        if isinstance(key,tuple):
            if len(key)==3 and key[0]=='id':found.append(key[1])
            for child in key:found+=row_ids(child)
        return found
    assert all(not row_ids(k) or '1' in row_ids(k) for k in changed)


def test_same_returned_count_is_stable_then_membership_change_recalculates(workspace):
    r=workspace.runtime;ref=rule(r,'CountRows(Filter(Cards,Amount>0))+Rand()');first=ref.property('Text');draws=states(r)
    patch(r,{'Amount':55});assert ref.property('Text')==first and states(r)==draws
    patch(r,{'Amount':-1});assert ref.property('Text')!=first and states(r)!=draws


def test_whole_record_and_table_consumers_observe_unread_fields(workspace):
    r=workspace.runtime
    whole=rule(r,'If(IsBlank(LookUp(Cards,ID=1)),0,Rand())','WholeRecord')
    table_=rule(r,'If(IsEmpty(Filter(Cards,true)),0,Rand())','WholeTable')
    before=whole.property('Text'),table_.property('Text')
    patch(r,{'Title':'Fictional changed'})
    assert before[0]!=whole.property('Text') and before[1]!=table_.property('Text')


def test_duplicate_objects_blank_rows_and_reordering(workspace):
    r=workspace.runtime;record={'ID':1,'Amount':10,'Title':'Fictional'}
    r.globals['entries']=[record,record,{'ID':2,'Amount':20,'Title':'Fictional'}]
    ref=rule(r,'Concat(entries,Text(Amount+Rand()),"|")');first=ref.property('Text').split('|')
    assert first[0]!=first[1]
    draws=states(r);record['Title']='Fictional renamed';r.invalidate()
    assert ref.property('Text').split('|')==first and states(r)==draws
    # Distinct IDs retain their row values across a changed ordering.
    r.globals['entries']=[r.globals['entries'][2],record,record];r.invalidate()
    assert ref.property('Text').split('|')==[first[2],first[0],first[1]]
    blank=rule(r,'Concat(Table(Blank(),Blank()),Text(Rand()),"|")','BlankRows')
    assert len(set(blank.property('Text').split('|')))==2


def test_live_nested_outer_scopes_and_error_recovery(workspace):
    r=workspace.runtime;r.globals['entries']=[{'ID':1,'Amount':0,'Unused':'a'},{'ID':2,'Amount':2,'Unused':'b'}]
    ref=rule(r,'Concat(entries As outer,Text(LookUp(entries As inner,inner.ID=outer.ID,Rand()+1/inner.Amount)),"|")')
    with pytest.raises(FxError):ref.property('Text')
    draws=states(r);r.globals['entries'][0]['Unused']='c';r.invalidate()
    with pytest.raises(FxError):ref.property('Text')
    assert states(r)==draws
    r.globals['entries'][0]['Amount']=4;r.invalidate();assert '|' in ref.property('Text')


def test_lazy_predicates_list_failure_and_behavior_execution(workspace):
    r=workspace.runtime
    ref=rule(r,'IfError(CountRows(Filter(Cards,false,1/0>0)),0)+Rand()');first=ref.property('Text');draws=states(r)
    patch(r,{'Title':'Fictional changed'});assert ref.property('Text')==first and states(r)==draws
    r.store.failures['Cards']='read';r.invalidate()
    # Error transitions remain observed, even if IfError handles the result.
    failed=ref.property('Text');assert failed!=first
    draws=states(r);r.invalidate();assert ref.property('Text')==failed and states(r)==draws
    r.store.failures.clear();r.invalidate();assert ref.property('Text')!=failed
    behavior=Context(r,behavior=True)
    a=r.fx.evaluate('ForAll(Cards,{Value:Amount+Rand()})',behavior)
    b=r.fx.evaluate('ForAll(Cards,{Value:Amount+Rand()})',behavior)
    assert a!=b


def test_table_literals_and_udf_boundaries(workspace):
    r=workspace.runtime;r.globals['amount']=10;r.globals['unused']='a'
    r.fx.set_definitions('=Row := Type({N:Number}); Rows := Type([Row]); Total(items:Rows):Number=Sum(items,N);')
    ref=rule(r,'Total(Table({N:amount+Rand()}))+Rand()');first=ref.property('Text');draws=states(r)
    r.globals['unused']='b';r.invalidate();assert ref.property('Text')==first and states(r)==draws
    r.globals['amount']=20;r.invalidate();assert ref.property('Text')!=first
    literal=rule(r,'Sum([{N:amount+Rand()}],N+Rand())+Rand()','Literal')
    first=literal.property('Text');draws=states(r);r.invalidate()
    assert literal.property('Text')==first and states(r)==draws


def test_readonly_query_inspection_and_workflow_owner_preservation(tmp_path):
    from powerapps_sim.fixtures import query_reads_project
    from powerapps_sim.authoring import revision,data_revision
    from powerapps_sim.runtime import serial
    p=query_reads_project(tmp_path/'queries');w=Workspace(tmp_path,p.root);r=w.runtime
    try:
        r.state();assert not r.diagnostics
        before=states(r),serial(w.ai.read_runtime()),deepcopy(r.control_state),revision(p.root),data_revision(r.store)
        report=w.ai.read_dependencies(query='LeftPanel',limit=500)
        rows=[row for row in report['rows'] if row['kind'] in ('query','query-row')]
        assert rows and any(row['formula']=='Text(row.Budget+Rand(),"0.000000")' for row in rows)
        assert all(row['source']=='Src/query-reads.pa.yaml' and row['span'][1]>row['span'][0] for row in rows)
        assert any(row['row_key'] is not None for row in rows)
        assert before==(states(r),serial(w.ai.read_runtime()),deepcopy(r.control_state),revision(p.root),data_revision(r.store))
        scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario'])
        for mode,lang in [('float','en-CA'),('float','fr-CA'),('decimal','en-CA'),('decimal','fr-CA')]:
            scenario['environment'].update(number_mode=mode,language=lang)
            result=w.workflows.run(scenario,expected_revision=before[3])
            assert result['status']=='passed' and len(result['steps'])==19 and not result['diagnostics'],result['steps']
        assert before==(states(r),serial(w.ai.read_runtime()),deepcopy(r.control_state),revision(p.root),data_revision(r.store))
        exported=w.ai.export_source()
        assert 'query-result' not in str(exported) and 'random_seed' not in str(exported)
    finally:r.close()


@pytest.mark.parametrize('formula',[
 'Concat(Table({N:2},Error({Kind:ErrorKind.Div0}),Blank()),Text(IfError(ThisRecord.N,3)+Rand()),"|")',
 'LookUp(Table({N:2},Error({Kind:ErrorKind.Div0})),true,N)+Rand()',
 'CountRows(Filter(Table({N:2},Error({Kind:ErrorKind.Div0}),Blank()),!IsError(ThisRecord)))+Rand()',
])
def test_error_and_blank_scopes_retain_stable_draws(workspace,formula):
    r=workspace.runtime;ref=rule(r,formula);first=ref.property('Text');draws=states(r)
    r.invalidate();assert ref.property('Text')==first and states(r)==draws


def test_insert_remove_and_position_scopes(workspace):
    r=workspace.runtime;r.globals['entries']=[{'Amount':10,'Unused':1},{'Amount':20,'Unused':2}]
    ref=rule(r,'Concat(entries,Text(Amount+Rand()),"|")');first=ref.property('Text').split('|');draws=states(r)
    r.globals['entries'][0]['Unused']=3;r.invalidate();assert ref.property('Text').split('|')==first and states(r)==draws
    r.globals['entries'].append({'Amount':30,'Unused':4});r.invalidate()
    after=ref.property('Text').split('|');assert after[:2]==first and len(after)==3
    r.globals['entries'].pop();r.invalidate();assert ref.property('Text').split('|')==first


def test_component_query_callbacks_remain_behavioral(workspace):
    r=workspace.runtime;ref=rule(r,'Rand()+CountRows(ForAll(Cards,{N:Amount}))')
    before=ref.property('Text');r.invalidate();assert ref.property('Text')==before
    ctx=Context(r,behavior=True)
    r.fx.evaluate('ForAll(Cards,Collect(captures,{ID:ID,N:Amount+Rand()}))',ctx)
    r.fx.evaluate('ForAll(Cards,Collect(captures,{ID:ID,N:Amount+Rand()}))',ctx)
    rows=r.collections['captures'];assert len(rows)==6 and rows[:3]!=rows[3:]

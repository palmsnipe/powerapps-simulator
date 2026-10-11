"""Power Fx As scopes across nested galleries and isolated components."""
from copy import deepcopy
from pathlib import Path
import pytest
from powerapps_sim.fixtures import gallery_alias_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import dump_yaml,load_yaml,Project
from powerapps_sim.syntax import FxError
@pytest.fixture
def r(tmp_path):
    value=Runtime(gallery_alias_project(tmp_path/'alias'));value.restart();value.state();assert not value.diagnostics
    yield value;value.close()
def cell(r,outer=0,inner=0,panel='LeftGrid'):
    ranks=r.refs['AliasLab/'+panel+'/Ranks'].property('AllItems')
    return ranks[outer]['Files'].property('AllItems')[inner]
def test_nested_aliases_bind_render_and_keep_innermost_thisitem(r):
    for outer in (0,1):
        for inner in (0,1,2):
            c=cell(r,outer,inner)
            assert c['Note'].property('Text')==f'Fictional cell {outer+1}.{inner+1}'
            assert c['Pick'].property('Text')==f'{outer+1}/{(outer+1)*10+inner+1} Fictional cell {outer+1}.{inner+1}'
            ctx=c['Note'].context()
            assert r.fx.evaluate('Rank.ID',ctx)==outer+1
            assert r.fx.evaluate('File.ID=ThisItem.ID && ThisRecord.ID=File.ID',ctx)
            assert r.fx.evaluate('Concat(Sequence(2) As query,Text(Rank.ID)&":"&Text(File.ID)&":"&Text(query.Value),"|")',ctx)==f'{outer+1}:{(outer+1)*10+inner+1}:1|{outer+1}:{(outer+1)*10+inner+1}:2'
    assert not r.diagnostics

def test_component_callbacks_receive_current_rows_and_instances_stay_isolated(r):
    c=cell(r,1,2);r.event(c['Pick'].path,'OnSelect')
    assert r.fx.evaluate('LeftGrid.Last.Outer=2 && LeftGrid.Last.Inner=23')
    assert r.fx.evaluate('RightGrid.Last.Outer=0 && CountRows(RightGrid.History)=0')
    assert r.globals['selected']=={'Outer':2,'Inner':23,'Caption':'Fictional cell 2.3'}
    assert r.collections['events'][0]['Panel']=='LeftGrid'
    c=cell(r,0,1,'RightGrid');r.event(c['Note'].path,'OnChange','Fictional changed note')
    assert r.fx.evaluate('RightGrid.Last.Inner=12 && CountRows(RightGrid.History)=1')
    assert r.fx.evaluate('LeftGrid.Last.Inner=23')
    assert not r.diagnostics

def test_retained_child_frames_refresh_after_source_writes(r):
    note=cell(r,1,0)['Note'];r.store.patch('Drafts',r.store.rows('Drafts')[1],{'Title':'Fictional renamed south'});r.invalidate();r.state()
    refreshed=cell(r,1,0)['Note'];assert refreshed is note
    assert r.fx.evaluate('Rank.Title',refreshed.context())=='Fictional renamed south'
    assert r.fx.evaluate('Rank.ID=File.Owner',refreshed.context())
    assert not r.diagnostics

def test_component_reset_defaults_and_peer_edits(r):
    left=cell(r,0,0)['Note'];right=cell(r,0,0,'RightGrid')['Note']
    r.event(left.path,'OnChange','Fictional left edit');r.event(right.path,'OnChange','Fictional right edit')
    r.event('AliasLab/ResetLeft','OnSelect');r.state()
    assert r.fx.evaluate('CountRows(LeftGrid.History)=0 && CountRows(RightGrid.History)=1')
    assert right.property('Text')=='Fictional right edit'
    # The containing component reset clears its own descendant state.
    assert left.property('Text')=='Fictional cell 1.1'
    assert not r.diagnostics

def test_named_formulas_cannot_capture_gallery_aliases(r):
    r.fx.set_definitions('=Global=Rank.ID;');r.invalidate()
    with pytest.raises(FxError):r.fx.evaluate('Global',cell(r)['Note'].context())
    assert r.fx.evaluate('Rank.ID',cell(r)['Note'].context())==1

def test_aliases_do_not_escape_the_component_or_gallery(r):
    for name in ('Rank','File'):
        with pytest.raises(FxError):r.fx.evaluate(name)
    assert 'Rank' not in r.globals and 'File' not in r.globals
    assert all('Rank' not in state['variables'] for state in r.component_state.values())

def simple(tmp_path,outer='Rank',inner='File',inner_items='=Sequence(2) As File'):
    caption=f'=Text({outer}.Value)&":"&Text({inner}.Value)'
    source={'App':{'Properties':{'OnStart':'=Set(Rank,{Value:999});Clear(events)'}},'Screens':{'Home':{'Children':[{'Ranks':{'Control':'Gallery@2.15.0','Properties':{'Items':'=Sequence(2) As '+outer},'Children':[{'Files':{'Control':'Gallery@2.15.0','Properties':{'Items':inner_items,'OnSelect':f'=Collect(events,{{Outer:{outer}.Value,Inner:{inner}.Value}})','TemplateFill':f'=If({inner}.IsSelected,Color.Red,Color.White)','ItemAccessibleLabel':caption},'Children':[{'Caption':{'Control':'ModernText@1.0.0','Properties':{'Text':caption}}},{'Choose':{'Control':'ModernButton@1.0.0','Properties':{'OnSelect':'=Select(Parent)'}}}]}}]}}]}}}
    p=Project(tmp_path/'simple');p.update_source('Src/main.pa.yaml',dump_yaml(source));value=Runtime(p);value.restart();value.state();return value

def test_gallery_onselect_row_metadata_and_global_disambiguation(tmp_path):
    r=simple(tmp_path)
    try:
        ranks=r.fx.evaluate('Ranks.AllItems');files=ranks[1]['Files'];rows=files.property('AllItems')
        ctx=rows[1]['Choose'].context(True);assert r.fx.evaluate('[@Rank].Value',ctx)==999
        r.event(rows[1]['Choose'].path,'OnSelect')
        assert r.collections['events']==[{'Outer':2,'Inner':2}]
        assert files.property('ItemAccessibleLabel')=='2:2'
        assert files.property('TemplateFill')=='#ff0000'
        assert not r.diagnostics
    finally:r.close()

def test_quoted_alias_identifiers(tmp_path):
    r=simple(tmp_path,"'outer row'","'inner row'","=Sequence(2) As 'inner row'")
    try:
        row=r.fx.evaluate('Index(Ranks.AllItems,2)')['Files'].property('AllItems')[1]
        assert row['Caption'].property('Text')=='2:2' and not r.diagnostics
    finally:r.close()

def test_nearest_same_alias_shadows_outer(tmp_path):
    r=simple(tmp_path,'Rank','Rank','=Sequence(2,10) As Rank')
    try:
        rows=r.fx.evaluate('Ranks.AllItems')[1]['Files'].property('AllItems')
        assert rows[0]['Caption'].property('Text')=='10:10'
        assert rows[1]['Caption'].property('Text')=='11:11'
        assert not r.diagnostics
    finally:r.close()

def test_inner_items_can_query_outer_alias(tmp_path):
    r=simple(tmp_path,inner_items='=Sequence(Rank.Value) As File')
    try:
        rows=r.fx.evaluate('Ranks.AllItems');assert [len(row['Files'].property('AllItems')) for row in rows]==[1,2]
        assert not r.diagnostics
    finally:r.close()

def test_unknown_alias_preserves_healthy_rows_and_source(r):
    ref=cell(r)['Note'];ref.control=deepcopy(ref.control);ref.control.properties['Default']='=Rank_1.Title';r.invalidate()
    with pytest.raises(FxError):ref.property('Text')
    assert cell(r,0,0,'RightGrid')['Note'].property('Text')=='Fictional cell 1.1'
    assert 'As Rank' in (r.project.root/'Src/gallery-alias.pa.yaml').read_text()

@pytest.mark.parametrize('language,number',[('en-US','float'),('en-US','decimal'),('fr-CA','float'),('fr-CA','decimal')])
def test_disposable_alias_workflow_preserves_owner(r,language,number):
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    from powerapps_sim.workflows import data_revision
    w=Workspace(r.project.root.parent,r.project.root)
    try:
        before=deepcopy(w.ai.read_runtime());source=revision(r.project.root);data=data_revision(w.runtime.store)
        entry=w.workflows.catalog()['scenarios'][0]
        result=w.workflows.run({**entry['scenario'],'environment':{'language':language,'number_mode':number}},expected_revision=source)
        assert result['status']=='passed' and len(result['steps'])==35 and not result['diagnostics'],result['steps']
        assert w.ai.read_runtime()==before and revision(r.project.root)==source and data_revision(w.runtime.store)==data
    finally:w.runtime.close()


def test_alias_reads_do_not_mutate_source_or_owner_state(r):
    before=deepcopy(r.control_state);source=(r.project.root/'Src/gallery-alias.pa.yaml').read_bytes()
    for i in (0,1):cell(r,i,0)['Pick'].property('Text')
    assert r.control_state==before and (r.project.root/'Src/gallery-alias.pa.yaml').read_bytes()==source
    assert b'row_frames' not in source

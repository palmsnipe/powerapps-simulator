"""Member read precision without losing scopes, lazy errors or record semantics."""
import pytest
from powerapps_sim.application import Workspace
from powerapps_sim.fixtures import reactive_cells_project
from powerapps_sim.source import Control
from powerapps_sim.syntax import FxError

@pytest.fixture
def workspace(tmp_path):
    p=reactive_cells_project(tmp_path/'project');w=Workspace(tmp_path,p.root)
    yield w
    w.runtime.close()

def states(r):return {k:v.getstate() for k,v in r.reactive.streams.items()}
def rule(r,formula,name='FieldProbe'):
    return r.build(Control(name,'ModernText@1.0.0',{'Properties':{'Text':'='+formula}},'Src/reactive-cells.pa.yaml'),'ReactiveLab/'+name)

@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('language',['en-CA','fr-CA'])
@pytest.mark.parametrize('family',['Classic','Grid'])
def test_row_field_edit_preserves_unread_members_and_form_defaults(workspace,mode,language,family):
    r=workspace.runtime;r.environment.update(number_mode=mode,language=language);r.restart();r.state()
    ref=r.refs['ReactiveLab/'+family];input_=r.refs['ReactiveLab/Editor/AmountCard/AmountInput']
    before=r.render(ref)['rows'];default=input_.property('Text');draws=states(r)
    r.store.patch('Cards',r.store.rows('Cards')[0],{'Title':'Fictional renamed card'});r.invalidate();r.state()
    after=r.render(ref)['rows']
    assert after[0]['cells'][0]['text']=='Fictional renamed card'
    assert [row['cells'][1:] for row in before]==[row['cells'][1:] for row in after]
    assert default==input_.property('Text')
    relevant=lambda d:{k:v for k,v in d.items() if len(k)<2 or 'Decorations' not in k[1]}
    assert relevant(draws)==relevant(states(r))
    r.store.patch('Cards',r.store.rows('Cards')[0],{'Amount':45});r.invalidate();r.state()
    changed=r.render(ref)['rows']
    assert changed[0]['cells'][2]['text']!=after[0]['cells'][2]['text'] and changed[1:]==after[1:]
    deps=r.reactive.describe(query=family+'Roll')['rows']
    assert any(row['changed_input'] and row['changed_input'][0]=='field' for row in deps)
    assert not r.diagnostics

@pytest.mark.parametrize('formula',[
 'source.Owner.Email & Text(Rand())',
 'If(source.Enabled,source.Owner.Email & Text(Rand()),"off")',
 'With({constant:3},source.Owner.Email & Text(constant+Rand()))',
])
def test_nested_global_members_lazy_branches_and_whole_records(workspace,formula):
    r=workspace.runtime;r.globals['source']={'Enabled':True,'Owner':{'Email':'a@example.test','Name':'Fictional A'},'Title':'A'}
    ref=rule(r,formula);first=ref.property('Text');before=states(r)
    r.globals['source']['Owner']['Name']='Fictional renamed';r.globals['source']['Title']='B';r.invalidate()
    assert first==ref.property('Text') and before==states(r)
    r.globals['source']['Owner']['Email']='b@example.test';r.invalidate()
    assert ref.property('Text').startswith('b@example.test') and before!=states(r)
    whole=rule(r,'If(IsBlank(source),"blank",Text(Rand()))','WholeProbe');value=whole.property('Text')
    r.globals['source']['Owner']['Name']='Fictional changed again';r.invalidate()
    assert whole.property('Text')!=value
    assert isinstance(r.globals['source'],dict) and type(r.globals['source']['Owner']) is dict


def test_alias_nested_scopes_projection_and_row_errors(workspace):
    r=workspace.runtime;g=r.refs['ReactiveLab/Decorations']
    g.control.properties['ItemAccessibleLabel']='=card.Title & Text(With({Amount:7},ThisRecord.Amount)+Rand())';r.invalidate()
    first=[x['props']['ItemAccessibleLabel'] for x in r.render(g)['rows']];before=states(r)
    r.store.patch('Cards',r.store.rows('Cards')[0],{'Amount':55});r.invalidate()
    assert first==[x['props']['ItemAccessibleLabel'] for x in r.render(g)['rows']] and before==states(r)
    r.store.patch('Cards',r.store.rows('Cards')[0],{'Title':'Fictional alias renamed'});r.invalidate()
    after=[x['props']['ItemAccessibleLabel'] for x in r.render(g)['rows']]
    assert after[0]!=first[0] and after[1:]==first[1:]
    r.globals['source']={'Owner':{'Email':FxError('fictional failure','Validation')},'Unused':0}
    ref=rule(r,'Rand()+Len(source.Owner.Email)');
    with pytest.raises(FxError,match='fictional failure'):ref.property('Text')
    draws=states(r);r.globals['source']['Unused']=1;r.invalidate()
    with pytest.raises(FxError,match='fictional failure'):ref.property('Text')
    assert draws==states(r)
    r.globals['source']['Owner']['Email']='a@example.test';r.invalidate();assert ref.property('Text') is not None


def test_property_volatile_child_projection_and_behavior_draws(workspace):
    r=workspace.runtime;r.globals['number']=3
    r.fx.set_definitions('=Box={Value:number,Noise:Rand()};')
    ref=rule(r,'Box.Value+Rand()');first=ref.property('Text');before=states(r)
    r.invalidate();assert first==ref.property('Text') and before==states(r)
    r.globals['number']=4;r.invalidate();assert first!=ref.property('Text') and before!=states(r)
    from powerapps_sim.fx import Context
    a=r.fx.evaluate('Box.Value+Rand()',Context(r,behavior=True));b=r.fx.evaluate('Box.Value+Rand()',Context(r,behavior=True));assert a!=b
    # Pure-property cycle errors keep their local source and leave a healthy rule usable.
    ref.control.properties['Text']='=Self.Text+Rand()';r.invalidate()
    with pytest.raises(FxError,match='cycle'):ref.property('Text')
    assert rule(r,'"healthy"','Healthy').property('Text')=='healthy'

@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('language',['en-CA','fr-CA'])
def test_record_component_inputs_callbacks_and_isolated_workflow(tmp_path,mode,language):
    from powerapps_sim.fixtures import field_reads_project
    from powerapps_sim.authoring import revision,data_revision
    from powerapps_sim.runtime import serial
    p=field_reads_project(tmp_path/'fields');w=Workspace(tmp_path,p.root);r=w.runtime
    try:
        r.environment.update(number_mode=mode,language=language);r.restart();r.state()
        left=r.fx.evaluate('LeftFields.Roll');right=r.fx.evaluate('RightFields.Roll');mail=r.fx.evaluate('LeftFields.Mail');whole=r.fx.evaluate('LeftFields.Whole')
        r.event('ReactiveLab/RenameOwner','OnSelect');r.state()
        assert left==r.fx.evaluate('LeftFields.Roll') and right==r.fx.evaluate('RightFields.Roll') and mail==r.fx.evaluate('LeftFields.Mail')
        assert whole!=r.fx.evaluate('LeftFields.Whole')
        before=serial(w.ai.read_runtime()),r.reactive.describe(),states(r),revision(p.root),data_revision(r.store)
        entry=w.workflows.catalog()['scenarios'][0]['scenario'];scenario={**entry,'environment':{'number_mode':mode,'language':language,'random_seed':20261012}}
        result=w.workflows.run(scenario,expected_revision=before[3])
        assert result['status']=='passed' and len(result['steps'])==29 and not result['diagnostics'],result['steps']
        assert before==(serial(w.ai.read_runtime()),r.reactive.describe(),states(r),revision(p.root),data_revision(r.store))
    finally:r.close()

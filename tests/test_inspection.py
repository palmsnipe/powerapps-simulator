"""Actual/declared live types, read-only observation and protocol preservation."""
from copy import deepcopy
from decimal import Decimal
import pytest
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision, data_revision
from powerapps_sim.fixtures import inspection_project
from powerapps_sim.runtime import Ref, serial
from powerapps_sim.binding import value_type, record, tabular, DATE
from powerapps_sim.inspection import schema


@pytest.fixture
def w(tmp_path):
    project=inspection_project(tmp_path/'inspection')
    workspace=Workspace(tmp_path,project.root)
    workspace.runtime.state()
    assert not workspace.runtime.diagnostics
    yield workspace
    workspace.runtime.close()


@pytest.mark.parametrize('name,kind',[('due','Date'),('appointment','DateTime'),('timeOnly','Time'),('photo','Image'),('tint','Color'),('token','GUID'),('amount','Number'),('payload','Dynamic')])
def test_runtime_metadata_retains_types_which_json_alone_loses(w,name,kind):
    state=w.runtime.state()
    assert state['types']['globals'][name]['kind']==kind
    assert state['globals'][name]==serial(w.runtime.globals[name])
    assert state['types']==w.ai.read_runtime()['types']


def test_uninitialized_variables_and_collections_have_declared_shapes(w):
    r=w.runtime;types=r.inspector_types()
    assert 'uninitialized' not in r.globals and 'emptyTable' not in r.collections
    assert types['globals']['uninitialized']=={'kind':'Blank','declared':{'kind':'Date'}}
    fields=types['collections']['emptyTable']['row']['fields']
    assert {key:t['kind'] for key,t in fields.items()}=={'Title':'Text','Due':'Date','Picture':'Image','Tint':'Color'}
    assert types['collections']['emptyTable']['row']['origin']=='binding'


def test_nested_record_table_and_mapped_names_are_retained(w):
    fields=w.runtime.inspector_types()['globals']['person']['fields']
    assert fields['Picture']['kind']=='Image' and fields['Contact']['fields']['Email']['kind']=='Text'
    assert fields['Groups']['row']['fields']['ID']['kind']=='Number'
    mapped=record({'EventDate':DATE},aliases={'EventDate':'Event date'})
    typ=schema(value_type([]),tabular(mapped))
    assert typ['row']['fields']['Event date']['kind']=='Date'
    from dataclasses import replace
    from powerapps_sim.binding import BOOLEAN
    assert schema(replace(mapped,virtual={'IsSelected':BOOLEAN}))['virtual']['IsSelected']['kind']=='Boolean'


def test_context_values_and_component_local_scopes_are_independent(w):
    r=w.runtime;before=r.inspector_types()['components']['InspectScreen/RightPanel']
    assert r.inspector_types()['contexts']['InspectScreen']['screenDate']['kind']=='Date'
    r.event('InspectScreen/LeftPanel/CaptureButton','OnSelect')
    types=r.inspector_types()['components']
    assert types['InspectScreen/RightPanel']==before
    assert types['InspectScreen/LeftPanel']['variables']['picture']['kind']=='Image'
    assert types['InspectScreen/LeftPanel']['variables']['localTint']=={'kind':'Color','origin':'binding'}
    assert types['InspectScreen/LeftPanel']['collections']['values']['row']['fields']['Stamp']['kind']=='DateTime'
    r.event('InspectScreen/ResetLeft','OnSelect')
    reset=r.inspector_types()['components']['InspectScreen/LeftPanel']
    assert reset['variables']['picture']=={'kind':'Blank','declared':{'kind':'Image'}}
    assert reset['collections']['values']['row']['fields']['Picture']['kind']=='Image'


def test_empty_collection_keeps_columns_and_blank_does_not_become_image(w):
    r=w.runtime;r.event('InspectScreen/ClearValues','OnSelect')
    types=r.inspector_types()
    assert len(types['collections']['snapshots']['row']['fields'])==20
    assert types['collections']['snapshots']['row']['fields']['Picture']['kind']=='Image'
    assert types['globals']['photo']=={'kind':'Blank','declared':{'kind':'Image'}}
    assert types['contexts']['InspectScreen']['screenPicture']=={'kind':'Blank','declared':{'kind':'Image'}}


def test_read_only_type_observation_does_not_evaluate_or_mutate(w,monkeypatch):
    r=w.runtime
    before=deepcopy([r.globals,r.collections,r.component_state,r.screen_context,r.control_state,r.notifications,r.diagnostics])
    data=data_revision(r.store);source=revision(r.project.root)
    monkeypatch.setattr(Ref,'property',lambda *_:pytest.fail('Type observation evaluated a property'))
    first=w.ai.read_runtime()['types'];second=r.inspector_types()
    assert first==second
    assert [r.globals,r.collections,r.component_state,r.screen_context,r.control_state,r.notifications,r.diagnostics]==before
    assert data_revision(r.store)==data and revision(r.project.root)==source


@pytest.mark.parametrize('name,kind',[('tint','Color'),('token','GUID'),('screenDate','Date'),('screenPicture','Image'),('Text(token)','Text'),('"#0f6cbd"','Text')])
def test_pure_ai_formula_result_uses_scoped_powerfx_types(w,name,kind):
    report=w.ai.evaluate_formula(name,scope='InspectScreen')
    assert report['status']=='ok' and report['type']['kind']==kind
    assert not w.runtime.diagnostics


def test_error_and_decimal_remain_actual_values(w):
    r=w.runtime;r.event('InspectScreen/CaptureFailure','OnSelect')
    assert r.inspector_types()['globals']['failure']=={'kind':'Error','declared':{'kind':'Number'}}
    assert '$error' in r.state()['globals']['failure']
    r.globals['exactDecimal']=Decimal('0.3000000000000000001')
    assert r.inspector_types()['globals']['exactDecimal']['kind']=='Decimal'
    assert r.state()['globals']['exactDecimal']=={'$decimal':'0.3000000000000000001'}
    assert not r.diagnostics


def test_ui_types_never_guess_images_colors_or_identifiers_from_plain_text(w):
    r=w.runtime
    for name,value in [('imageText',str(r.globals['photo'])),('colorText','#0f6cbd'),('guidText',r.globals['token'])]:
        r.globals[name]=str(value)
        assert r.inspector_types()['globals'][name]=={'kind':'Text'}


def test_workflow_report_contains_types_and_contexts_without_changing_owner(w):
    before=serial(w.ai.read_runtime());data=data_revision(w.runtime.store)
    scenario=w.workflows.catalog()['scenarios'][0]['scenario']
    report=w.workflows.run(scenario,expected_revision=revision(w.project.root))
    assert report['status']=='passed' and len(report['steps'])==24 and not report['diagnostics'],report['steps']
    assert report['types']['globals']['failure']['kind']=='Error'
    assert report['types']['components']['InspectScreen/RightPanel']['variables']['picture']['kind']=='Image'
    assert report['types']['contexts']['InspectScreen']['screenPicture']['declared']['kind']=='Image'
    assert report['contexts']['InspectScreen']['screenPicture'] is None
    assert serial(w.ai.read_runtime())==before and data_revision(w.runtime.store)==data


def test_http_metadata_remains_detached_and_source_export_has_no_emulator_types(app,tmp_path):
    w=app.extensions['workspace'];w.open(inspection_project(tmp_path/'http-inspection'))
    client=app.test_client()
    result=client.get('/api/state').json
    assert result['types']['globals']['photo']['kind']=='Image'
    result['types']['globals']['photo']['kind']='Text'
    assert client.get('/api/state').json['types']['globals']['photo']['kind']=='Image'
    exported=w.ai.export_source()
    assert 'types' not in exported and 'types' not in exported['documents']


def test_formula_binding_tracks_same_context_name_across_screens(tmp_path):
    from powerapps_sim.source import Project
    source='''App:
  Properties:
    StartScreen: =One
Screens:
  One:
    Properties:
      OnVisible: =UpdateContext({shared:Date(2026,2,3)})
    Children:
      - Next:
          Control: ModernButton@1.0.0
          Properties:
            OnSelect: =Navigate(Two)
  Two:
    Properties:
      OnVisible: =UpdateContext({shared:Color.Red})
'''
    p=Project.import_yaml(source,tmp_path/'screens');w=Workspace(tmp_path,p.root)
    try:
        assert w.ai.evaluate_formula('shared')['type']['kind']=='Date'
        w.runtime.event('One/Next','OnSelect')
        assert w.ai.evaluate_formula('shared')['type']=={'kind':'Color','origin':'binding'}
        assert w.ai.evaluate_formula('shared',scope='One')['type']['kind']=='Date'
        assert w.runtime.inspector_types()['contexts']['Two']['shared']['kind']=='Color'
        assert not w.runtime.diagnostics
    finally:w.runtime.close()

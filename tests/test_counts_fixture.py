"""Counts across component scopes, mapped persistence and isolated workflows."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import pytest
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision,data_revision
from powerapps_sim.fixtures import counts_project
from powerapps_sim.runtime import Runtime

@pytest.mark.parametrize('language',['en-CA','fr-CA'])
@pytest.mark.parametrize('mode',['float','decimal'])
def test_count_workflow_preserves_owner_and_translates(tmp_path,language,mode):
    p=counts_project(tmp_path/'p');w=Workspace(tmp_path,p.root)
    try:
        before=(revision(p.root),data_revision(w.runtime.store),deepcopy(w.ai.read_runtime()))
        scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario'])
        scenario['environment']={'language':language,'number_mode':mode,'enum_mode':'strong'}
        result=w.workflows.run(scenario,expected_revision=before[0])
        assert result['status']=='passed',result['steps']
        assert len(result['steps'])==20
        assert not result['diagnostics']
        assert before==(revision(p.root),data_revision(w.runtime.store),w.ai.read_runtime())
        w.runtime.environment.update(scenario['environment']);w.runtime.restart();w.runtime.state()
        assert w.runtime.refs['CountsLab/LeftPanel/Heading'].property('Text')==('Gauche' if language=='fr-CA' else 'Left')
    finally:w.runtime.close()

def test_persistent_mapped_blank_changes_and_component_callbacks(tmp_path):
    p=counts_project(tmp_path/'p');r=Runtime(p)
    try:
        r.restart();r.state();assert not r.diagnostics
        r.event('CountsLab/LeftPanel/Amount','OnChange',0)
        r.event('CountsLab/LeftPanel/AddSample','OnSelect');r.state()
        assert r.fx.evaluate('LeftPanel.Summary.Numeric')==2
        assert r.fx.evaluate('RightPanel.Summary.Rows')==1
        assert r.collections['trace'][0]=={'Panel':'LeftPanel','Numeric':2,'Present':2,'Rows':3}
        assert 'extras' not in r.collections
        r.event('CountsLab/ClearAmount','OnSelect');r.state()
        assert r.store.rows('Samples')[0]['Sample amount'] is None
        r.event('CountsLab/SaveSnapshot','OnSelect');r.state()
        assert r.store.rows('Snapshots')[0]['Numeric']==1
        r.event('CountsLab/LeftPanel/ResetSamples','OnSelect');r.state()
        assert r.fx.evaluate('LeftPanel.Summary.Numeric')==0 and not r.diagnostics
    finally:r.close()
    r=Runtime(p)
    try:
        r.restart();r.state()
        assert r.fx.evaluate('LeftPanel.Summary.Numeric')==0
        assert r.store.rows('Snapshots')[0]['Rows']==3
    finally:r.close()

def test_source_exports_remain_powerapps_only(tmp_path):
    p=counts_project(tmp_path/'p')
    original=p.documents['Src/counts.pa.yaml']
    with ZipFile(BytesIO(p.export())) as z:
        assert z.namelist()==['Src/counts.pa.yaml']
        assert z.read('Src/counts.pa.yaml').decode()==original
    assert 'CountA(ShowColumns' in original and 'PropertyKind: Function' in original

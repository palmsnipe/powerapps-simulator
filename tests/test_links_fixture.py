from copy import deepcopy
import pytest
from powerapps_sim.fixtures import links_project
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision,data_revision


@pytest.mark.parametrize('language',['en-CA','fr-CA'])
@pytest.mark.parametrize('number',['float','decimal'])
def test_link_components_workflow_and_owner_preservation(tmp_path,language,number):
    p=links_project(tmp_path/'links');w=Workspace(tmp_path,p.root)
    try:
        w.runtime.state();owner=deepcopy(w.ai.read_runtime())
        source,data=revision(p.root),data_revision(w.runtime.store)
        scenario=w.workflows.catalog()['scenarios'][0]['scenario']
        scenario['environment']={'language':language,'number_mode':number,'enum_mode':'strong'}
        result=w.workflows.run(scenario,expected_revision=source)
        assert result['status']=='passed' and len(result['steps'])==28 and not result['diagnostics'],([s for s in result['steps'] if s['status']!='passed'],result['diagnostics'])
        assert w.ai.read_runtime()==owner and revision(p.root)==source and data_revision(w.runtime.store)==data
        assert len(w.runtime.store.definitions['Bookmarks']['fields'])==13
        exported=str(w.ai.export_source())
        assert 'ModernLink@1.0.0' in exported and 'link_url' not in exported
    finally:w.runtime.close()

from copy import deepcopy
import pytest
from powerapps_sim.fixtures import metadata_project
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision, data_revision


@pytest.mark.parametrize('language',['en-CA','fr-CA'])
@pytest.mark.parametrize('number',['float','decimal'])
def test_metadata_component_workflow_preserves_owner(tmp_path,language,number):
    p = metadata_project(tmp_path/'metadata')
    w = Workspace(tmp_path,p.root)
    try:
        owner = deepcopy(w.ai.read_runtime())
        source,data = revision(p.root), data_revision(w.runtime.store)
        scenario = w.workflows.catalog()['scenarios'][0]['scenario']
        scenario['environment'] = {'language':language,'number_mode':number,'enum_mode':'strong'}
        result = w.workflows.run(scenario,expected_revision=source)
        assert result['status'] == 'passed' and len(result['steps']) == 30 and not result['diagnostics'], result
        assert w.ai.read_runtime() == owner
        assert revision(p.root) == source and data_revision(w.runtime.store) == data
        exported = str(w.ai.export_source())
        assert 'DataSourceInfo' in exported and 'datasource-info-schema' not in exported
    finally:
        w.runtime.close()

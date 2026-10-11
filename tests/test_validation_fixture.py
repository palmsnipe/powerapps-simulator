from copy import deepcopy
import pytest
from powerapps_sim.fixtures import validation_project
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision, data_revision


@pytest.mark.parametrize('language', ['en-CA','fr-CA'])
@pytest.mark.parametrize('number', ['float','decimal'])
def test_component_validation_workflow_and_owner_preservation(tmp_path, language, number):
    p = validation_project(tmp_path/'validation')
    w = Workspace(tmp_path, p.root)
    try:
        w.runtime.state()
        owner = deepcopy(w.ai.read_runtime())
        source, data = revision(p.root), data_revision(w.runtime.store)
        scenario = w.workflows.catalog()['scenarios'][0]['scenario']
        scenario['environment'] = {'language':language,'number_mode':number,'enum_mode':'strong'}
        result = w.workflows.run(scenario, expected_revision=source)
        assert result['status'] == 'passed' and len(result['steps']) == 24, result['steps']
        assert not result['diagnostics']
        assert w.ai.read_runtime() == owner
        assert revision(p.root) == source and data_revision(w.runtime.store) == data
        exported = w.ai.export_source()
        assert 'Validate' in str(exported) and 'validation-schema' not in str(exported)
    finally:
        w.runtime.close()

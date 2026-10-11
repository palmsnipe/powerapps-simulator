import pytest
from powerapps_sim.fixtures import locales_project
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision,data_revision

@pytest.mark.parametrize('number',['float','decimal'])
@pytest.mark.parametrize('language',['en-US','es-ES','de-DE','ja-JP'])
def test_localized_workflow_preserves_owner(tmp_path,number,language):
 p=locales_project(tmp_path/'p');p.config['environment'].update(language=language,number_mode=number);p.save_config()
 w=Workspace(tmp_path,p.root,start=False)
 try:
  owner=w.ai.read_runtime();before=revision(p.root),data_revision(w.runtime.store)
  scenario=w.workflows.catalog()['scenarios'][0]['scenario']
  result=w.workflows.run(scenario,expected_revision=before[0])
  assert result['status']=='passed' and len(result['steps'])==18 and not result['diagnostics'],result
  assert w.ai.read_runtime()==owner and (revision(p.root),data_revision(w.runtime.store))==before
 finally:w.runtime.close()

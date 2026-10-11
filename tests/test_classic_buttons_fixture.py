"""Public button workflow isolates component state and preserves the AI owner."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import pytest
from powerapps_sim.fixtures import classic_buttons_project
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision,data_revision
from powerapps_sim.runtime import serial

@pytest.mark.parametrize('number,language',[('float','en-CA'),('float','fr-CA'),('decimal','en-CA'),('decimal','fr-CA')])
def test_classic_buttons_workflow_and_export(tmp_path,number,language):
 p=classic_buttons_project(tmp_path/'public');w=Workspace(tmp_path,p.root)
 try:
  w.runtime.state();owner=serial(w.ai.read_runtime());deps=w.ai.read_dependencies();source=revision(p.root);data=data_revision(w.runtime.store)
  scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);scenario['environment']={'number_mode':number,'language':language,'enum_mode':'strong'}
  result=w.workflows.run(scenario,expected_revision=source)
  assert result['status']=='passed' and len(result['steps'])==28 and not result['diagnostics'],result
  assert serial(w.ai.read_runtime())==owner and w.ai.read_dependencies()==deps
  assert revision(p.root)==source and data_revision(w.runtime.store)==data
  with ZipFile(BytesIO(p.export())) as z:
   assert set(z.namelist())=={'Src/classic-buttons.pa.yaml','Src/Components/CounterCard.pa.yaml'}
   for n in z.namelist():assert z.read(n).decode()==p.documents[n]
 finally:w.runtime.close()


def test_classic_button_event_contract(tmp_path):
 p=classic_buttons_project(tmp_path/'events');w=Workspace(tmp_path,p.root)
 try:
  for name in ('OnChange','OnInput','OnSort'):
   with pytest.raises(ValueError):w.runtime.event('Home/Left/Increase',name)
  assert w.runtime.fx.evaluate('Left.Count')==0 and not w.runtime.diagnostics
 finally:w.runtime.close()

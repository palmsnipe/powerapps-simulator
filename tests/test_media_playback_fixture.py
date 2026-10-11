"""Real assets, media-scoped component callbacks and isolated AI workflows."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import pytest
from powerapps_sim.fixtures import media_playback_project
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision, data_revision
from powerapps_sim.runtime import serial, Runtime
from powerapps_sim.media_controls import snapshot
from powerapps_sim.fx import Context
from powerapps_sim.source import dump_yaml, Project

@pytest.mark.parametrize('number,language',[('float','en-CA'),('float','fr-CA'),('decimal','en-CA'),('decimal','fr-CA')])
def test_public_playback_workflow_preserves_owner(tmp_path,number,language):
    p=media_playback_project(tmp_path/'public');w=Workspace(tmp_path,p.root)
    try:
        w.runtime.state();before=serial(w.ai.read_runtime());deps=w.ai.read_dependencies()
        source=revision(p.root);data=data_revision(w.runtime.store)
        scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario'])
        scenario['environment']={'number_mode':number,'language':language,'enum_mode':'strong'}
        result=w.workflows.run(scenario,expected_revision=source)
        assert result['status']=='passed' and len(result['steps'])==27 and not result['diagnostics'],result
        assert serial(w.ai.read_runtime())==before and w.ai.read_dependencies()==deps
        assert revision(p.root)==source and data_revision(w.runtime.store)==data
        assert (p.root/'Assets/tone.wav').read_bytes().startswith(b'RIFF')
        assert b'ftyp' in (p.root/'Assets/movie.mp4').read_bytes()[:32]
        with ZipFile(BytesIO(p.export())) as z:
            assert set(z.namelist())=={'Src/media-playback.pa.yaml','Src/Components/MediaPanel.pa.yaml','Assets/tone.wav','Assets/movie.mp4','Assets/captions.vtt'}
            assert all(z.read(n).decode()==p.documents[n] for n in z.namelist() if n.startswith('Src/'))
        assert 'OnMedia' not in '\n'.join(p.documents.values())
    finally:w.runtime.close()

def test_gallery_media_instances_use_thisitem_and_reset_boundary(tmp_path):
    p=Project(tmp_path/'gallery')
    p.update_source('Src/gallery.pa.yaml',dump_yaml({'App':{'Properties':{'OnStart':'=Clear(history)'}},'Screens':{'Home':{'Children':[{'Clips':{'Control':'Gallery@2.15.0','Properties':{'Items':'=Table({Title:"One"},{Title:"Two"})'},'Children':[{'Player':{'Control':'Audio@2.1.0','Properties':{'Media':'="data:audio/wav;base64,AA=="','OnEnd':'=Collect(history,{Title:ThisItem.Title,Seconds:Self.Time})'}}}]}}]}}}))
    r=Runtime(p);r.restart();r.state()
    try:
        refs=[r.refs[c['path']] for c in r.state()['media']['controls']]
        assert len(refs)==2
        for ref in refs:
            for operation,values in [('metadata',{'duration':2}),('play',{}),('end',{'time':2})]:
                r.event(ref.path,'OnMedia',{'token':snapshot(ref)['token'],'operation':operation,**values})
        assert [row['Title'] for row in r.collections['history']]==[ref.item['Title'] for ref in refs]
        assert all(row['Seconds']==2 for row in r.collections['history']) and not r.diagnostics
        r.fx.evaluate('Reset(Self)',Context(r,self_ref=refs[0],behavior=True));r.state()
        assert refs[0].property('Time')==0 and refs[1].property('Time')==2
    finally:r.close()

def test_background_source_change_mints_token_and_clears_metadata(tmp_path):
    r=Runtime(media_playback_project(tmp_path/'background'));r.restart();r.state()
    try:
        ref=r.refs['Home/Right/Player']
        for op,values in [('metadata',{'duration':6}),('play',{})]:r.event(ref.path,'OnMedia',{'token':snapshot(ref)['token'],'operation':op,**values})
        old=snapshot(ref)['token'];r.event('Home/OpenAway','OnSelect')
        ref.control.properties['Media']='="data:audio/wav;base64,AQ=="';r.invalidate();r.state()
        assert snapshot(ref)['token']!=old and ref.property('Duration')==0
        r.event(ref.path,'OnMedia',{'token':old,'operation':'end','time':6})
        assert not r.collections['history']
    finally:r.close()

def test_decode_diagnostics_are_isolated_and_clear_on_reset_or_retry(tmp_path):
    r=Runtime(media_playback_project(tmp_path/'issues'));r.restart();r.state()
    try:
        left=r.refs['Home/Left/Player'];right=r.refs['Home/Right/Player']
        for ref in (left,right):r.event(ref.path,'OnMedia',{'token':snapshot(ref)['token'],'operation':'issue','message':'Browser decode failure'})
        assert {d['control'] for d in r.diagnostics if d['category']=='media'}=={left.path,right.path}
        r.event('Home/Left/Reset','OnSelect');r.state()
        assert {d['control'] for d in r.diagnostics if d['category']=='media'}=={right.path}
        r.event(right.path,'OnMedia',{'token':snapshot(right)['token'],'operation':'play'})
        assert not r.diagnostics and not r.collections['history']
    finally:r.close()

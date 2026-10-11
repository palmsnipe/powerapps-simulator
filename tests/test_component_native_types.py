"""Native clipboard component type enums, coercion and instance boundaries."""
from decimal import Decimal
from copy import deepcopy
import pytest

from powerapps_sim.binding import BindScope, FxType, value_type
from powerapps_sim.component_inspection import describe
from powerapps_sim.fx import Context
from powerapps_sim.inspection import schema
from powerapps_sim.json_fx import Media, json_text
from powerapps_sim.reactivity import fingerprint
from powerapps_sim.runtime import Runtime, serial
from powerapps_sim.source import Project, dump_yaml
from powerapps_sim.syntax import FxError


TYPES = [('Currency', '12.25', 'Currency'), ('DateAndTime', 'Date(2026,1,2)', 'DateTime'),
    ('Screen', 'Target', 'Screen'), ('VideoOrAudio', 'Tone', 'Media')]


def make(tmp_path, native, kind='OutputFunction', default=None, body=None):
    parameter = {'DataType': native}
    if default is not None:
        parameter.update(IsOptional=True, Default=default)
    call = {'PropertyKind': kind, 'ReturnType': native, 'Parameters': [{'v': parameter}]}
    call_body = body or ('=Set(localValue,v);Worker.Changed(v);v' if kind == 'Action' else '=v')
    if kind == 'InputFunction': call['Default'] = '=v'
    if kind == 'Event': call['Default'] = '=Set(hostValue,v);v'
    p = Project(tmp_path/'native')
    p.config['resource_metadata'] = [{'Name': name, 'ResourceKind': 'LocalFile', 'Path': path}
        for name,path in [('Tone','Assets/tone.wav'),('Picture','Assets/picture.svg')]]
    p.update_source('Src/native.pa.yaml', dump_yaml({'App': {'Properties': {'OnStart': '=Clear(history)'}},
        'ComponentDefinitions': {'Worker': {'DefinitionType': 'CanvasComponent',
            'CustomProperties': {'Call': call, 'Changed': {'PropertyKind': 'Event', 'ReturnType': 'None',
                'Parameters': [{'value': {'DataType': native}}]}}, 'Properties': {'Call': call_body}}},
        'Screens': {'Home': {'Children': [{name: {'Control': 'CanvasComponent', 'ComponentName': 'Worker',
            'Properties': {'Changed': f'=Collect(history,{{Panel:"{name}",Value:value}})'}}} for name in ('Left','Right')]
            + [{'Label1': {'Control': 'Label@2.5.1', 'Properties': {'Text': '="Healthy"'}}}]}, 'Target': {}}}))
    p.save_config()
    r = Runtime(p); r.restart()
    return r


@pytest.mark.parametrize('native,argument,result_kind', TYPES)
@pytest.mark.parametrize('kind', ['InputFunction','OutputFunction','Action','Event'])
@pytest.mark.parametrize('number,language', [('float','en-CA'),('decimal','fr-CA')])
def test_native_contracts_callable_kinds_and_instance_isolation(tmp_path,native,argument,result_kind,kind,number,language):
    r = make(tmp_path,native,kind); r.environment.update(number_mode=number,language=language); r.analyze()
    try:
        assert not r.diagnostics
        before = deepcopy(r.component_state)
        ctx = Context(r,behavior=kind in ('Action','Event'))
        result = r.fx.evaluate(f'Left.Call({argument})',ctx)
        info = describe(r)['Home/Left']['properties']['Call']
        assert info['declared_type'] == native and info['type']['kind'] == result_kind
        assert info['parameters'][0]['type']['kind'] == result_kind
        if native == 'Currency':
            assert result == Decimal('12.25')
            assert isinstance(result, Decimal) == (number=='decimal')
        elif native == 'DateAndTime': assert result.kind == 'DateTime' and result.value.day == 2
        elif native == 'Screen': assert result is r.global_refs['Target']
        else:
            assert isinstance(result,Media) and value_type(result).kind=='Media'
            assert result.asset_root == r.project.root/'Assets'
        if kind == 'Action':
            assert r.component_state['Home/Left']['variables']['localValue']==result
            assert 'Home/Right' not in r.component_state
            assert r.collections['history'][0]['Panel']=='Left'
        elif kind == 'Event': assert r.globals['hostValue']==result
        else: assert r.component_state==before and not r.collections['history']
        assert r.fx.evaluate('Left.Call(Blank())',ctx) is None
    finally: r.close()


@pytest.mark.parametrize('native,invalid', [('Currency','Date(2026,1,1)'),('Currency','{Amount:1}'),
    ('Currency','Picture'),('DateAndTime','{Day:1}'),('Screen','Label1'),('Screen','"Target"'),
    ('VideoOrAudio','Picture'),('VideoOrAudio','12'),('Image','Tone')])
def test_invalid_arguments_bind_and_fail_before_argument_or_action_effects(tmp_path,native,invalid):
    r=make(tmp_path,native,'Action')
    try:
        node=r.fx.parse(f'Left.Call(If(true,Set(argumentEffect,true);{invalid}))')
        r.binder.errors.clear();r.binder.bind(node,BindScope(behavior=True),('test','',0))
        assert any('incompatible component contract' in error.message for _,error in r.binder.errors)
        with pytest.raises(FxError): r.fx.evaluate(f'Left.Call(If(true,Set(argumentEffect,true);{invalid}))',Context(r,behavior=True))
        assert 'argumentEffect' not in r.globals and not r.component_state and not r.collections['history']
        assert r.fx.evaluate('Label1.Text')=='Healthy'
    finally:r.close()


@pytest.mark.parametrize('number,language,text', [('float','en-CA','12.50'),('float','fr-CA','12,50'),
    ('decimal','en-CA','12.50'),('decimal','fr-CA','12,50')])
def test_currency_conversion_arithmetic_and_inspection(tmp_path,number,language,text):
    r=make(tmp_path,'Currency','Action');r.environment.update(number_mode=number,language=language);r.analyze()
    try:
        assert r.fx.evaluate(f'Left.Call("{text}")',Context(r,behavior=True))==Decimal('12.5')
        assert r.fx.evaluate('Left.Call(true)',Context(r,behavior=True))==1
        assert r.fx.evaluate('Left.Call(12.5)+2',Context(r,behavior=True))==Decimal('14.5')
        typ=r.binder.component_declared_type('Currency')
        assert schema(value_type(r.component_state['Home/Left']['variables']['localValue']),typ)=={
            'kind':'Currency','backing':'Decimal' if number=='decimal' else 'Number','origin':'binding'}
        count=len(r.collections['history'])
        assert r.fx.evaluate('IfError(Left.Call("broken"),-1)',Context(r,behavior=True))==-1
        assert len(r.collections['history'])==count
    finally:r.close()


@pytest.mark.parametrize('native,default,kind', [('Currency','=12.25','Currency'),
    ('DateAndTime','=Date(2026,1,2)','DateTime'),('VideoOrAudio','="offline.wav"','Media')])
def test_native_optional_defaults_preserve_declared_identity(tmp_path,native,default,kind):
    r=make(tmp_path,native,default=default)
    try:
        assert not r.diagnostics
        result=r.fx.evaluate('Left.Call()')
        assert schema(value_type(result),r.binder.component_declared_type(native))['kind']==kind
        assert r.fx.evaluate('Left.Call(Blank())') is None
    finally:r.close()


def test_screen_navigation_and_property_scope_are_references(tmp_path):
    r=make(tmp_path,'Screen','Action',body='=Navigate(v);v')
    try:
        assert r.fx.evaluate('Left.Call(Target).Width',Context(r,behavior=True))==r.viewport['width']
        assert r.active_screen=='Target'
        assert r.fx.evaluate('Left.Call(App.ActiveScreen)',Context(r,behavior=True)) is r.global_refs['Target']
        with pytest.raises(FxError):r.fx.evaluate('Left.Call(Label1)',Context(r,behavior=True))
        assert r.active_screen=='Target'
    finally:r.close()


def test_media_image_distinction_json_and_reactive_identity(tmp_path):
    r=make(tmp_path,'VideoOrAudio')
    try:
        root=r.project.root/'Assets';root.mkdir(exist_ok=True);(root/'tone.wav').write_bytes(b'fictional audio fixture')
        result=r.fx.evaluate('Left.Call(Tone)')
        assert value_type(result).kind=='Media' and r.binder.globals['Tone'].kind=='Media'
        assert value_type(r.resolve('Picture',Context(r))).kind=='Image'
        assert json_text(result,'B').startswith('"data:audio/')
        assert json_text({'Sound':result,'Title':'retained'},'G')=='{"Title":"retained"}'
        with pytest.raises(FxError):json_text(result)
        assert value_type(r.fx.evaluate('Left.Call("https://example.test/tone.wav")')).kind=='Media'
        assert fingerprint({'asset':Media('same',root,kind='Image')})!=fingerprint({'asset':Media('same',root,kind='Media')})
        assert fingerprint(Media('same',root,kind='Media'))!=fingerprint(Media('same',None,kind='Media'))
    finally:r.close()


@pytest.mark.parametrize('uri,kind',[('clip.mp4','Media'),('tone.wav','Media'),('clip.webm','Media'),
    ('data:audio/wav;base64,AA==','Media'),('picture.png','Image'),('data:image/svg+xml;base64,AA==','Image')])
def test_local_asset_mime_types(uri,kind):
    assert value_type(Media(uri)).kind==kind


@pytest.mark.parametrize('native,_,kind',TYPES)
def test_native_property_enums_do_not_expand_app_type_names(tmp_path,native,_,kind):
    r=make(tmp_path,native)
    try:
        assert r.binder.component_declared_type(native).kind==kind
        assert r.binder.declared_type(native).kind=='Unknown'
        with pytest.raises(FxError):r.fx.declared_contract(native)
    finally:r.close()


@pytest.mark.parametrize('number,language',[('float','en-CA'),('float','fr-CA'),('decimal','en-CA'),('decimal','fr-CA')])
def test_public_native_workflow_preserves_owner_and_source(tmp_path,number,language):
    from powerapps_sim.fixtures import native_types_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision, data_revision
    p=native_types_project(tmp_path/'public');w=Workspace(tmp_path,p.root)
    try:
        w.runtime.state();before=serial(w.ai.read_runtime());deps=w.ai.read_dependencies()
        source=revision(p.root);data=data_revision(w.runtime.store)
        scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario'])
        scenario['environment']={'number_mode':number,'language':language,'enum_mode':'strong'}
        result=w.workflows.run(scenario,expected_revision=source)
        assert result['status']=='passed' and len(result['steps'])==19 and not result['diagnostics'],result
        assert serial(w.ai.read_runtime())==before and w.ai.read_dependencies()==deps
        assert revision(p.root)==source and data_revision(w.runtime.store)==data
        types=before['types']['globals']
        assert types['money']['kind']=='Currency' and types['page']['kind']=='Screen' and types['sound']['kind']=='Media'
        text=p.documents['Src/Components/NativeCard.pa.yaml']
        assert all(f'DataType: {native}' in text for native,_,_ in TYPES)
        assert '$mediaIdentity' not in text and 'asset_root' not in text
    finally:w.runtime.close()


@pytest.mark.parametrize('native,invalid',[('Currency','={Amount:1}'),('DateAndTime','={Day:1}'),
    ('Screen','="Home"'),('VideoOrAudio','=4')])
def test_bad_data_property_is_isolated_and_located(tmp_path,native,invalid):
    r=make(tmp_path,native)
    try:
        master=r.project.components['Worker']
        master.raw['CustomProperties']['Bad']={'PropertyKind':'Output','DataType':native}
        master.properties['Bad']=invalid;r.invalidate();r.analyze()
        info=describe(r,evaluate=True)['Home/Left']['properties']['Bad']
        assert info['value']['$error']['Source']=='Home/Left.Bad'
        assert info['type']['kind']=='Error' and info['type']['declared']['kind']==r.binder.component_declared_type(native).kind
        assert r.fx.evaluate('Label1.Text')=='Healthy' and not r.collections['history']
    finally:r.close()

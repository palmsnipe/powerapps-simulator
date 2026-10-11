"""Selection publications are tied to the rendered instance and reset epoch."""
from copy import deepcopy
import pytest
from powerapps_sim.fixtures import selectors_project, search_project
from powerapps_sim.runtime import Runtime
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError

@pytest.fixture(params=['selectors','search'])
def controls(request,tmp_path):
    p=(selectors_project if request.param=='selectors' else search_project)(tmp_path/request.param)
    r=Runtime(p);r.restart();r.state()
    yield r;r.close()


def single_event(r,name,index=1,token=None):
    ref=r.global_refs[name];node=r.render(ref)
    r.event(ref.path,'OnChange',{'indices':[index],'option_token':token or node['option_token']})


def combo_event(r,name='Multi',index=1,token=None):
    ref=r.global_refs[name];node=r.render(ref)
    r.event(ref.path,'OnChange',{'operation':'toggle','index':index,'option_token':token or node['option_token']})


def test_selection_tokens_reject_reordered_items_without_callbacks(controls):
    r=controls;name='Status' if 'Status' in r.global_refs else 'Multi';ref=r.global_refs[name]
    token=r.render(ref)['option_token'];before=deepcopy(ref.property('Selected'));events=deepcopy(r.collections['events'])
    ref.control.properties['Items']=('=["Approved","Submitted","Draft"]' if name=='Status' else '=SortByColumns(Records,ID,SortOrder.Descending)');r.invalidate()
    with pytest.raises(ValueError,match='Choices changed'):
        (single_event if name=='Status' else combo_event)(r,name,1,token)
    assert ref.property('Selected')==before and r.collections['events']==events


def test_reset_restart_and_default_changes_invalidate_same_items(controls):
    r=controls;name='Status' if 'Status' in r.global_refs else 'Multi';ref=r.global_refs[name]
    for action in ('Reset','Restart','Default'):
        old=r.render(ref)['option_token'];events=deepcopy(r.collections['events'])
        if action=='Restart':r.restart();events=deepcopy(r.collections['events'])
        elif action=='Reset':r.fx.evaluate(f'Reset({name})',Context(r,behavior=True))
        else:ref.control.properties['Default' if name=='Status' else 'DefaultSelectedItems']='="Submitted"' if name=='Status' else '=LastN(Records,1)';r.invalidate()
        with pytest.raises(ValueError,match='Choices changed'):(single_event if name=='Status' else combo_event)(r,name,1,old)
        assert r.collections['events']==events and r.render(ref)['option_token']!=old


def test_tokens_are_bound_to_the_control_path_and_runtime(controls):
    r=controls;first,second=('Status','Priority') if 'Status' in r.global_refs else ('Multi','Single')
    token=r.render(r.global_refs[first])['option_token']
    with pytest.raises(ValueError,match='Choices changed'):(single_event if first=='Status' else combo_event)(r,second,1,token)
    fresh=Runtime(r.project);fresh.restart();fresh.state()
    try:
        with pytest.raises(ValueError,match='Choices changed'):(single_event if first=='Status' else combo_event)(fresh,first,1,token)
    finally:fresh.close()


def test_radio_reselect_and_clear_publish_once(tmp_path):
    r=Runtime(selectors_project(tmp_path/'radio'));r.restart();r.state()
    try:
        single_event(r,'Priority',2);before=deepcopy(r.collections['events']);single_event(r,'Priority',2)
        assert r.collections['events']==before
        node=r.render(r.global_refs['Priority']);r.event('ChoicesScreen/Priority','OnChange',{'indices':[],'option_token':node['option_token']})
        assert r.fx.evaluate('Priority.Selected') is None and len(r.collections['events'])==len(before)+1
    finally:r.close()


@pytest.mark.parametrize('payload',[{}, {'indices':[0]}, {'indices':None,'option_token':'current'}, {'indices':[True],'option_token':'current'}, {'indices':[1.5],'option_token':'current'}, {'indices':[0,1],'option_token':'current'}, {'indices':[99],'option_token':'current'}])
def test_malformed_single_events_never_write(tmp_path,payload):
    r=Runtime(selectors_project(tmp_path/'bad'));r.restart();r.state()
    try:
        if payload.get('option_token')=='current':payload['option_token']=r.render(r.global_refs['Status'])['option_token']
        before=deepcopy(r.control_state)
        with pytest.raises(ValueError):r.event('ChoicesScreen/Status','OnChange',payload)
        assert r.control_state==before and len(r.collections['events'])==1
    finally:r.close()


def test_search_default_reset_and_restart_reject_pending_output(tmp_path):
    r=Runtime(search_project(tmp_path/'search'));r.restart();r.state()
    try:
        ref=r.global_refs['Single']
        for action in ('Reset','Default','Restart'):
            token=r.render(ref)['search_reset']
            if action=='Reset':r.fx.evaluate('Reset(Single)',Context(r,behavior=True))
            elif action=='Default':ref.control.properties['DefaultSelectedItems']='=FirstN(Records,1)';r.invalidate()
            else:r.restart()
            before=deepcopy(r.collections['events'])
            r.event(ref.path,'OnSearch',{'text':'beta','reset_token':token})
            assert ref.property('SearchText')=='' and r.collections['events']==before
        token=r.render(ref)['search_reset'];r.event(ref.path,'OnSearch',{'text':'beta','reset_token':token})
        assert ref.property('SearchText')=='beta'
        ref.control.properties['DefaultSelectedItems']='=LastN(Records,1)';r.invalidate();r.state()
        assert ref.property('SearchText')=='' and ref.property('Selected')['ID']==4
    finally:r.close()


@pytest.mark.parametrize('payload',[{'text':1,'reset_token':'x'},{'text':'beta','reset_token':0},{'text':'beta'},{'text':'beta','reset_token':'x','extra':1}])
def test_malformed_search_output_is_rejected(tmp_path,payload):
    r=Runtime(search_project(tmp_path/'search'));r.restart()
    try:
        with pytest.raises(ValueError,match='Text'):r.event('SearchScreen/Single','OnSearch',payload)
        assert r.fx.evaluate('Single.SearchText')==''
    finally:r.close()


def test_legacy_selection_callbacks_require_changed_identity(tmp_path):
    r=Runtime(search_project(tmp_path/'search'));r.restart();r.state()
    try:
        before=deepcopy(r.collections['events']);r.event('SearchScreen/Multi','OnChange',selection=[0]);assert r.collections['events']==before
        r.event('SearchScreen/Multi','OnChange',selection=[0,1]);assert len(r.collections['events'])==len(before)+1
        r.event('SearchScreen/Multi','OnChange',selection=[0,1]);assert len(r.collections['events'])==len(before)+1
        r.event('SearchScreen/Multi','OnChange',selection=[]);assert len(r.collections['events'])==len(before)+2
    finally:r.close()


@pytest.mark.parametrize('name,prop,formula',[('Status','Required','="yes"'),('Status','ValidationState','="invalid"'),('Priority','Layout','="Diagonal"')])
def test_single_selector_property_types_remain_visible_errors(tmp_path,name,prop,formula):
    r=Runtime(selectors_project(tmp_path/'types'));r.restart()
    try:
        ref=r.global_refs[name];ref.control.properties[prop]=formula;r.invalidate()
        with pytest.raises(FxError):ref.property(prop)
        assert r.render(ref)['errors'] and r.diagnostics
    finally:r.close()


def test_combo_required_validation_and_placeholder_defaults(tmp_path):
    r=Runtime(search_project(tmp_path/'defaults'));r.restart()
    try:
        ref=r.global_refs['Multi'];ref.control.properties.pop('InputTextPlaceholder',None)
        assert ref.property('Required') is False and ref.property('ValidationState')=='None' and ref.property('InputTextPlaceholder')=='Find items'
        ref.control.properties['MultiValueDelimiter']='=false';r.invalidate()
        with pytest.raises(FxError,match='Text'):ref.property('MultiValueDelimiter')
    finally:r.close()


def test_equal_component_items_do_not_share_selection_tokens(controls):
    r=controls;single='Status' in r.global_refs
    left,right=('ChoicesScreen/LeftChoice/Picker','ChoicesScreen/RightChoice/Picker') if single else ('SearchScreen/LeftSearch/Picker','SearchScreen/RightSearch/Picker')
    left_node=r.render(r.refs[left]);right_node=r.render(r.refs[right])
    assert left_node['options']==right_node['options']
    assert left_node['option_token']!=right_node['option_token']
    value={'indices':[1],'option_token':left_node['option_token']} if single else {'operation':'toggle','index':1,'option_token':left_node['option_token']}
    before=deepcopy(r.refs[right].property('Selected'))
    with pytest.raises(ValueError,match='Choices changed'):r.event(right,'OnChange',value)
    assert r.refs[right].property('Selected')==before


def test_previous_runtime_search_token_is_discarded(tmp_path):
    p=search_project(tmp_path/'search');first=Runtime(p);first.restart();first.state()
    token=first.render(first.global_refs['Single'])['search_reset'];first.close()
    fresh=Runtime(p);fresh.restart();fresh.state()
    try:
        before=deepcopy(fresh.collections['events'])
        fresh.event('SearchScreen/Single','OnSearch',{'text':'previous project','reset_token':token})
        assert fresh.fx.evaluate('Single.SearchText')=='' and fresh.collections['events']==before
    finally:fresh.close()

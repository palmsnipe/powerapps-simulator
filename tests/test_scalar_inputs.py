"""Date/number contracts, server validation, callbacks, reset isolation and forms."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import math
import pytest
from powerapps_sim.fixtures import inputs_project
from powerapps_sim.runtime import Runtime, serial
from powerapps_sim.fx import Context
from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision
from powerapps_sim.syntax import FxError

@pytest.fixture
def inputs(tmp_path):
    r=Runtime(inputs_project(tmp_path/'inputs'));r.restart();r.state()
    yield r;r.close()

def event(r,name,**value):
    ref=r.global_refs.get(name) or r.refs[name]
    token=r.render(ref)['input_reset'];r.event(ref.path,'OnChange',{**value,'reset_token':token})

def number(r,name,text,direction=None):
    event(r,name,text=text,operation='step' if direction is not None else 'commit',**({'direction':direction} if direction is not None else {}))

def calendar(r,name,value,source='calendar'):
    event(r,name,value=value,source=source)

def test_defaults_enums_and_version_contracts(inputs):
    r=inputs
    assert r.fx.evaluate("DecimalPrecision.'2'")==2 and r.fx.evaluate('DecimalPrecision.Auto')=='Auto'
    assert r.fx.evaluate('StartOfWeek.Tuesday')==12
    assert r.fx.evaluate('Quantity.Value')==2 and r.render(r.global_refs['Amount'])['formatted_value']=='12.50'
    assert r.render(r.global_refs['Meeting'])['calendar']['weekdays']==['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
    assert not r.diagnostics


def test_number_precision_callbacks_blank_and_return_to_default(inputs):
    r=inputs;number(r,'Amount','17.125');assert r.fx.evaluate('Amount.Value')==17.13
    assert r.collections['events']==[{'Kind':'amount','Number':17.13}]
    number(r,'Amount','17.13');assert len(r.collections['events'])==1
    number(r,'Amount','');assert r.fx.evaluate('Amount.Value') is None
    number(r,'Amount','12.5');assert r.global_refs['Amount'].state['dirty'] is False
    assert r.render(r.global_refs['Amount'])['formatted_value']=='12.50'


def test_steps_use_configured_amount_and_stop_at_bounds(inputs):
    r=inputs;number(r,'Quantity','2',1);assert r.fx.evaluate('Quantity.Value')==4
    number(r,'Quantity','9',1);assert r.fx.evaluate('Quantity.Value')==10
    before=deepcopy(r.collections['events']);number(r,'Quantity','10',1);assert r.collections['events']==before
    number(r,'Quantity','0',-1);assert r.fx.evaluate('Quantity.Value')==0
    number(r,'Amount','12.5',-1);assert r.fx.evaluate('Amount.Value')==12.25


@pytest.mark.parametrize('value',[-1,101,float('inf'),float('nan'),True,'12.5',{},[]])
def test_invalid_number_publications_do_not_mutate(inputs,value):
    r=inputs;before=deepcopy(r.collections['events']);records=deepcopy(r.store.rows('Records'))
    with pytest.raises((FxError,ValueError)):r.event(r.global_refs['Amount'].path,'OnChange',value)
    assert r.fx.evaluate('Amount.Value')==12.5 and r.collections['events']==before and r.store.rows('Records')==records


@pytest.mark.parametrize('prop,formula',[('Min','="wrong"'),('Max','=true'),('Step','=0'),('Step','=-1'),('Precision','=4'),('Precision','=1.5'),('Precision','=true')])
def test_invalid_numeric_contracts_are_visible(inputs,prop,formula):
    ref=inputs.global_refs['Quantity'];ref.control.properties[prop]=formula;inputs.invalidate()
    assert inputs.render(ref)['errors']


def test_inverted_numeric_range_is_an_error_and_float_default_preserves_auto(inputs):
    r=inputs;ref=r.global_refs['Quantity'];ref.control.properties['Min']='=20';r.invalidate()
    assert r.render(ref)['errors']
    ref.control.properties.update(Min='=Blank()',Max='=Blank()',Precision='=DecimalPrecision.Auto',Default='=2.675');r.invalidate()
    assert ref.property('Value')==2.675
    ref.control.properties['Precision']="=DecimalPrecision.'2'";r.invalidate();assert ref.property('Value')==2.68


def test_french_number_entry_and_formatting_invalidate_pending_contract(inputs):
    r=inputs;old=r.render(r.global_refs['Amount'])['input_reset'];r.event('InputScreen/Language','OnSelect')
    assert r.render(r.global_refs['Amount'])['formatted_value']=='12,50'
    r.event('InputScreen/Amount','OnChange',{'text':'88.2','operation':'commit','reset_token':old})
    assert r.fx.evaluate('Amount.Value')==12.5
    number(r,'Amount','17,125');assert r.fx.evaluate('Amount.Value')==17.13
    assert r.render(r.global_refs['Meeting'])['calendar']['weekdays'][0]=='lun.'


def test_calendar_cells_navigation_bounds_and_no_change_callback(inputs):
    r=inputs;ref=r.global_refs['Meeting'];node=r.render(ref);c=node['calendar']
    assert c['formatted']=='15/01/2026' and c['previous'] is None and c['next']=='2026-02'
    assert next(d for d in c['days'] if d['date']=='2026-01-09')['disabled']
    r.event(ref.path,'OnCalendar',{'month':'2026-02','reset_token':node['input_reset']})
    c=r.render(ref)['calendar'];assert c['month']=='2026-02' and r.collections.get('events',[])==[]
    assert r.fx.evaluate('Meeting.SelectedDate').isoformat()=='2026-01-15'
    calendar(r,'Meeting','2026-02-14');assert r.fx.evaluate('Meeting.SelectedDate').isoformat()=='2026-02-14'
    assert r.render(ref)['calendar']['month']=='2026-02'
    before=deepcopy(r.collections['events']);calendar(r,'Meeting','2026-02-14');assert r.collections['events']==before
    calendar(r,'Meeting',None,'clear');assert r.fx.evaluate('Meeting.SelectedDate') is None


@pytest.mark.parametrize('value',['2026-01-09','2026-03-21','2026-02-30',True,3,'2026-01-15T00:00:00Z'])
def test_invalid_date_selection_never_changes_output(inputs,value):
    r=inputs
    with pytest.raises((ValueError,FxError)):calendar(r,'Meeting',value)
    assert serial(r.fx.evaluate('Meeting.SelectedDate'))=='2026-01-15' and r.collections.get('events',[])==[]


def test_typed_dates_follow_editability_and_formats(inputs):
    r=inputs
    with pytest.raises(ValueError,match='not directly editable'):calendar(r,'Meeting','2026-02-14','typed')
    calendar(r,'Editable','2026-02-14','typed');assert serial(r.fx.evaluate('Editable.SelectedDate'))=='2026-02-14'
    ref=r.global_refs['Editable'];ref.control.properties['Format']='="dd/mm/yyyy"';r.invalidate()
    calendar(r,'Editable','03/02/2026','typed');assert serial(ref.property('SelectedDate'))=='2026-02-03'
    assert r.render(ref)['calendar']['formatted']=='03/02/2026'


@pytest.mark.parametrize('prop,formula',[('StartDate','=Date(2026,4,1)'),('EndDate','=Blank()'),('IsEditable','="true"'),('DateTimeZone','="EST"'),('StartOfWeek','=8'),('Format','=false')])
def test_invalid_date_contracts_are_visible(inputs,prop,formula):
    r=inputs;ref=r.global_refs['Meeting'];ref.control.properties[prop]=formula;r.invalidate();assert r.render(ref)['errors']


def test_datetime_defaults_honor_utc_and_fixed_clock_offset_preserving_dates(inputs):
    r=inputs;ref=r.global_refs['Editable'];r.environment['clock']='2026-01-01T12:00:00-05:00'
    ref.control.properties['DefaultDate']='=DateTimeValue("2026-01-16T02:00:00Z")';r.invalidate()
    assert serial(ref.property('SelectedDate'))=='2026-01-15'
    ref.control.properties['DateTimeZone']='=DateTimeZone.UTC';r.invalidate();assert serial(ref.property('SelectedDate'))=='2026-01-16'
    ref.control.properties.update(DateTimeZone='=DateTimeZone.Local',DefaultDate='=Date(2026,1,16)');r.invalidate()
    assert serial(ref.property('SelectedDate'))=='2026-01-16'


@pytest.mark.parametrize('name,value',[('Amount',{'text':'88','operation':'commit'}),('Meeting',{'value':'2026-02-14','source':'calendar'})])
def test_reset_default_restart_and_new_runtime_reject_pending_values(inputs,name,value):
    r=inputs;ref=r.global_refs[name]
    for action in ('reset','default','restart'):
        old=r.render(ref)['input_reset']
        if action=='reset':r.fx.evaluate(f'Reset({name})',Context(r,behavior=True))
        elif action=='default':ref.control.properties['Default' if name=='Amount' else 'DefaultDate']='=20' if name=='Amount' else '=Date(2026,2,1)';r.invalidate()
        else:r.restart()
        r.event(ref.path,'OnChange',{**value,'reset_token':old})
        assert ref.property('Value' if name=='Amount' else 'SelectedDate')!= (88 if name=='Amount' else r.fx.evaluate('Date(2026,2,14)'))
    old=r.render(ref)['input_reset'];fresh=Runtime(r.project);fresh.restart();fresh.state()
    try:
        fresh.event(ref.path,'OnChange',{**value,'reset_token':old});assert fresh.collections.get('events',[])==[]
    finally:fresh.close()


def test_components_tokens_and_callbacks_are_isolated(inputs):
    r=inputs;left=r.refs['InputScreen/LeftPair/N'];right=r.refs['InputScreen/RightPair/N']
    assert r.render(left)['input_reset']!=r.render(right)['input_reset']
    number(r,left.path,'6');assert r.fx.evaluate('LeftPair.CurrentNumber')==6 and r.fx.evaluate('RightPair.CurrentNumber')==8
    assert r.collections['events']==[{'Kind':'LeftPair','Number':6}]
    r.fx.evaluate('Reset(LeftPair)',Context(r,behavior=True));assert r.fx.evaluate('LeftPair.CurrentNumber')==2


def test_form_save_failure_retry_reset_and_view_preserve_typed_values(inputs):
    r=inputs;number(r,'FormCost','32.25');calendar(r,'FormDate','2026-02-03','typed')
    assert r.fx.evaluate('InputForm.Unsaved') is True
    r.store.failures['Records']='write';r.event('InputScreen/Save','OnSelect');assert r.fx.evaluate('InputForm.Unsaved') is True
    assert r.store.rows('Records')[0]['Cost']==10
    r.store.failures.clear();r.event('InputScreen/Save','OnSelect')
    assert r.store.rows('Records')[0]['Cost']==32.25 and r.store.rows('Records')[0]['Due']=='2026-02-03'
    assert r.fx.evaluate('InputForm.LastSubmit.Due').kind=='Date' and r.fx.evaluate('InputForm.Unsaved') is False
    r.event('InputScreen/View','OnSelect');number(r,'FormCost','88');calendar(r,'FormDate','2026-03-03')
    assert r.fx.evaluate('InputForm.Updates.Cost')==32.25 and r.fx.evaluate('InputForm.Updates.Due').isoformat()=='2026-02-03'


def test_stored_workflow_isolated_and_source_export_has_only_app_files(inputs):
    r=inputs;w=Workspace(r.project.root.parent,r.project.root,start=False)
    try:
        before=w.runtime.state();records=deepcopy(w.runtime.store.rows('Records'));entry=w.workflows.catalog()['scenarios'][0]
        result=w.workflows.run(entry['scenario'],expected_revision=revision(r.project.root));assert result['status']=='passed',result['steps']
        assert len(result['steps'])==29 and not result['diagnostics']
        assert w.runtime.state()==before and w.runtime.store.rows('Records')==records
    finally:w.runtime.close()

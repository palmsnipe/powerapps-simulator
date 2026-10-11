"""The local SharePoint adapter owns author/editor metadata on writes."""
from copy import deepcopy
import pytest
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project
from powerapps_sim.scenarios import person, OPTIONS
from powerapps_sim.syntax import FxError
from powerapps_sim.fx import Context


@pytest.fixture
def audit(runtime):
    fields = {'ID': {'type':'integer','x-ms-permission':'read-only'}, 'Title':{'type':'string'},
        'Created':{'type':'string','format':'date-time','x-ms-permission':'read-only'},
        'Modified':{'type':'string','format':'date-time','x-ms-permission':'read-only'}}
    mapping = {k:k for k in fields}
    for key, label in [('Author','Created By'),('Editor','Modified By')]:
        fields[key] = {'type':'object','properties':{'Claims':{},'Email':{},'DisplayName':{}},'x-ms-permission':'read-only'}
        fields[key+'#Claims'] = {'type':'string','x-ms-permission':'read-only'}
        mapping.update({key:label,key+'#Claims':label+' Claims'})
    runtime.store.add_list('Audited',{'fields':fields,'mapping':mapping,'required':['Title']})
    return runtime


def test_create_and_update_use_simulated_user_and_preserve_creator(audit):
    r = audit
    r.environment['user'] = {'Email':'Submitter@Example.Test','FullName':'Fictional submitter'}
    r.store.clock = '2026-10-09T12:00:00+00:00'
    row = r.store.patch('Audited',{}, {'Title':'Fictional draft'})
    assert row['Created By']['Email'] == 'submitter@example.test'
    assert row['Created By']['DisplayName'] == 'Fictional submitter'
    assert row['Created By Claims'] == row['Created By']['Claims']
    assert row['Modified By'] == row['Created By']
    r.environment['user'] = {'Email':'reviewer@example.test','FullName':'Fictional reviewer'}
    r.store.clock = '2026-10-10T12:00:00+00:00'
    changed = r.store.patch('Audited',row,{'Title':'Fictional edit'})
    assert changed['Created By'] == row['Created By'] and changed['Created'] == row['Created']
    assert changed['Modified By']['Email'] == 'reviewer@example.test'
    assert changed['Modified By Claims'] == changed['Modified By']['Claims']
    assert changed['Modified'] == r.store.clock
    assert row['Title'] == 'Fictional draft'
    other = Runtime(Project(r.project.root))
    try:
        assert other.store.rows('Audited')[0] == changed
    finally:
        other.close()


def test_failed_write_spoof_and_fixture_restore_preserve_metadata(audit):
    r = audit
    original = person('historical@example.test','Fictional historical author')
    row = r.store.patch('Audited',{}, {'Title':'Restored','Created By':original,'Modified By':original},system=True)
    before = deepcopy(r.store.rows('Audited'))
    with pytest.raises(FxError, match='read-only'):
        r.store.patch('Audited',row,{'Created By':person('spoof@example.test','Spoof')})
    r.store.failures['Audited'] = 'write'
    with pytest.raises(FxError, match='write failure'):
        r.store.patch('Audited',row,{'Title':'Failed'})
    r.store.failures.clear()
    assert r.store.rows('Audited') == before
    r.store.import_rows('Audited',before,replace=True)
    assert r.store.rows('Audited') == before


def test_choice_fixtures_include_planning_draft_and_scoring_values():
    assert 'Draft' in OPTIONS['CurrentStage'] and 'Year-End' in OPTIONS['CurrentStage']
    assert 'Returned for Revision' in OPTIONS['CurrentStatus']
    assert OPTIONS['Factor3OperationalNeed'] == ['Direct support to CA operations','Indirect support to CA operations','Not linked to CA operation']


def test_iferror_must_observe_patch_before_set_stores_the_error(audit):
    r = audit
    r.store.failures['Audited'] = 'write'
    ctx = Context(r, behavior=True)
    r.fx.evaluate('IfError(Set(savedId, Patch(Audited, Defaults(Audited), {Title:"Failed"}).ID), Set(caught, true))',ctx)
    assert isinstance(r.globals['savedId'],FxError) and 'caught' not in r.globals
    r.fx.evaluate('Set(savedId, IfError(Patch(Audited, Defaults(Audited), {Title:"Failed"}).ID, Set(caught, true); Blank()))',ctx)
    assert r.globals['savedId'] is None and r.globals['caught'] is True
    assert not r.store.rows('Audited')


def test_lookup_ids_from_shaped_powerfx_tables_are_stored_as_integers(audit):
    r = audit
    r.store.add_list('Parents',{'fields':{'ID':{'type':'integer'},'Title':{'type':'string'}}})
    r.store.add_list('Children',{'fields':{'ID':{'type':'integer'},'Parent':{'type':'object','properties':{'Id':{'type':'integer'},'Value':{'type':'string'}}}},'lookups':{'Parent':'Parents'}})
    r.store.patch('Parents',{}, {'Title':'Fictional parent'})
    row = r.fx.evaluate('Patch(Children,Defaults(Children),{Parent:{Id:First(AddColumns(Parents,Tag,0)).ID,Value:"Fictional parent"}})',Context(r,behavior=True))
    assert row['Parent']['Id'] == 1 and type(row['Parent']['Id']) is int
    before = deepcopy(r.store.rows('Children'))
    for invalid in (True,1.5,float('inf'),float('nan')):
        with pytest.raises(FxError):
            r.store.patch('Children',row,{'Parent':{'Id':invalid,'Value':'Invalid'}})
    assert r.store.rows('Children') == before


def test_seeded_drafts_have_explicit_fictional_ownership(audit):
    from powerapps_sim.scenarios import seed
    definition = deepcopy(audit.store.definitions['Audited'])
    definition['fields']['CurrentStage'] = {'type':'object','properties':{'Value':{'type':'string'}},'x-ms-capabilities':{'x-ms-sp':{'IsChoice':True}}}
    definition['mapping']['CurrentStage'] = 'Current Stage'
    audit.store.add_list('Business Planning Project Submissions',definition)
    seed(audit.store,'2026-10-09T12:00:00+00:00')
    rows = audit.store.rows('Business Planning Project Submissions')
    assert len(rows) == 3
    assert all(r['Current Stage'] == {'Value':'Draft'} for r in rows)
    assert all(r['Created By']['Email'] == 'submitter@example.test' and r['Modified By']['Email'] == 'submitter@example.test' for r in rows)
    assert all(r['Created By Claims'] == r['Created By']['Claims'] for r in rows)

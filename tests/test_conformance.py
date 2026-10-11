from powerapps_sim.conformance import equivalent, report


def test_pinned_reference_corpus_has_no_unexpected_regressions():
    results = report()
    assert results['total'] == 6710
    assert len(results['revision']) == 40
    assert results['passed'] == 6703
    assert results['known_gaps'] == 7
    assert results['regressions'] == 0, [case for case in results['results'] if case['status'] == 'regression']
    for case in results['results']:
        assert results['revision'] in case['source']['url']
        assert case['source']['expected_powerfx']
        if case['status'] == 'known_gap':
            assert case['known_gap']


def test_oracle_distinguishes_boolean_from_number():
    assert not equivalent(True, 1)
    assert not equivalent([{'Value': False}], [{'Value': 0}])
    assert equivalent([{'Value': 1.0}], [{'Value': 1}])
    assert equivalent({'$error': {'Kind': 13, 'Message': 'host wording'}}, {'$error': {'Kind': 13}})
    assert not equivalent({'$error': {'Kind': 25}}, {'$error': {'Kind': 13}})


def test_mutation_references_never_use_the_callers_tables_or_database(tmp_path):
    from powerapps_sim.runtime import Runtime,serial
    from powerapps_sim.source import Project
    from powerapps_sim.binding import value_type
    from powerapps_sim.authoring import data_revision
    r=Runtime(Project(tmp_path/'caller'))
    try:
        r.globals.update({'r1':{'Title':'Fictional owned global'}})
        r.collections.update({'t1':[{'N':99}],'t2':[{'N':100}]})
        r.binder.globals.update({key:value_type(value) for key,value in r.globals.items()})
        r.binder.collections.update({key:value_type(value) for key,value in r.collections.items()})
        r.store.add_list('Owned',{'fields':{'ID':{'type':'integer'},'Title':{'type':'string'}}})
        r.store.patch('Owned',{}, {'Title':'Fictional owned record'})
        before=(serial(r.globals),serial(r.collections),data_revision(r.store),dict(r.environment))
        results=report(r)
        assert results['passed']==6703 and results['regressions']==0
        assert (serial(r.globals),serial(r.collections),data_revision(r.store),r.environment)==before
    finally:r.close()

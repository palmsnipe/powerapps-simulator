"""Pinned portable capture/scoping oracles; never derive expectations from engine."""
import json
from pathlib import Path
import pytest
from powerapps_sim.conformance import run_case

CORPUS=json.loads((Path(__file__).parents[1]/'powerapps_sim/conformance_cases/regex_groups.json').read_text())

@pytest.fixture(scope='module')
def portable_runtime(tmp_path_factory):
    from powerapps_sim.runtime import Runtime
    from powerapps_sim.source import Project
    r=Runtime(Project(tmp_path_factory.mktemp('portable-regex')))
    yield r
    r.close()

@pytest.mark.parametrize('case',CORPUS['cases'],ids=lambda c:c['id'])
def test_portable_regex_group_reference(portable_runtime,case):
    result=run_case(portable_runtime,case)
    assert result['status']=='passed', result

@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('number',['float','decimal'])
def test_portable_capture_component_workflow_preserves_owner(tmp_path,language,number):
    from copy import deepcopy
    from powerapps_sim.fixtures import regex_groups_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    p=regex_groups_project(tmp_path/'p');w=Workspace(tmp_path,p.root)
    try:
        w.runtime.store.patch('Contacts',{}, {'Title':'Fictional owner record','TokenCount':99})
        w.runtime.restart()
        before=deepcopy(w.ai.read_runtime());rows=deepcopy(w.runtime.store.rows('Contacts'))
        entry=w.workflows.catalog()['scenarios'][0]
        result=w.workflows.run({**entry['scenario'],'environment':{'enum_mode':'strong','regex_mode':'powerfx-v1','language':language,'number_mode':number}},expected_revision=revision(p.root))
        assert result['status']=='passed',result
        assert len(result['steps'])==58
        assert w.ai.read_runtime()==before
        assert w.runtime.store.rows('Contacts')==rows
    finally:w.runtime.close()

@pytest.mark.parametrize('pattern,options,message',[
    (r'(?<x>a)?b\k<x>','c','absent'),
    (r'(?<x>a\k<x>)','c','open'),
    (r'\k<x>(?<x>a)','c','earlier'),
    (r'(?<x>a)|\k<x>','c','alternation'),
    (r'(?=(?<x>a))\k<x>','c','lookaround'),
    (r'(?<=(?<x>a))b','c','inside lookbehind'),
    (r'(?<=a*)b','c','unbounded'),
    (r'(?<=(?<=a))b','c','nested'),
    (r'(?<=a{251})b','c','250'),
    (r'(?<=😀{126})b','c','250'),
    (r'((a)?)+','N','ambiguous'),
    (r'(?:(?=a)a)+','c','lookarounds'),
    ('(' * 32 + 'a' + ')' * 32,'c','depth'),
    ('(?<' + 'a' * 63 + '>a)','c','62'),
    (r'a{2147483648}','c','overflow'),
    (r'a{4,2}','c','minimum'),
    (r'a**','c','preceding'),
    (r'(?<x>a)\1','c','NumberedSubMatches'),
])
def test_portable_invalid_patterns_are_guarded_directly(pattern,options,message):
    from powerapps_sim.regex_fx import compile_pattern
    from powerapps_sim.syntax import FxError
    with pytest.raises(FxError) as error:
        compile_pattern(pattern,options,'powerfx-v1')
    assert error.value.kind=='Type'
    # Double quantifiers have an immediate syntax error before group analysis.
    if pattern != r'a**':assert message in error.value.message


def test_portable_static_shape_locations_lazy_and_error_handling(portable_runtime):
    from powerapps_sim.binding import BindScope
    from powerapps_sim.syntax import FxError
    r=portable_runtime;r.environment.update(regex_mode='powerfx-v1',enum_mode='strong');r.analyze()
    expression=r'MatchAll("ab ab 12", "(?<word>[a-z]+)\s+\k<word>\s+(?<number>\d+)")'
    node=r.fx.parse(expression);typ=r.binder.bind(node,BindScope())
    assert set(typ.row.fields)=={'FullMatch','StartMatch','word','number'}
    assert r.fx.evaluate(expression)==[{'FullMatch':'ab ab 12','StartMatch':1,'word':'ab','number':'12'}]
    bad=r'Match("b", "(?<x>a)?b\k<x>")'
    r.binder.errors.clear();r.binder.bind(r.fx.parse(bad),BindScope())
    location,error=r.binder.errors[0]
    assert error.kind=='Type' and error.start==11 and error.end==27
    assert r.fx.evaluate('If(false,'+bad+',"untouched")')=='untouched'
    assert r.fx.evaluate(r'IfError(Match(1/0,"(?<x>a)\k<x>").FullMatch,FirstError.Kind)')=='13'
    with pytest.raises(FxError):r.fx.evaluate(bad)


def test_option_anchors_do_not_consume_portable_nesting_budget():
    from powerapps_sim.regex_fx import compile_pattern
    pattern='('*31+'a'+')'*31
    assert compile_pattern(pattern,'^c$','powerfx-v1').compiled.fullmatch('a')
    assert compile_pattern(r'(?<=😀{125})b','c','powerfx-v1').compiled.search('😀'*125+'b')


@pytest.mark.parametrize('profile',['canvas','powerfx-v1'])
def test_many_capture_positions_keep_utf16_contract(portable_runtime,profile):
    r=portable_runtime;r.environment['regex_mode']=profile;r.analyze()
    r.globals['lines']='😀 ab ab 12 ' * 1500
    result=r.fx.evaluate(r'MatchAll(lines,"(?<word>ab)\s+\k<word>\s+(?<number>\d+)")')
    assert len(result)==1500
    assert result[0]['StartMatch']==4 and result[-1]['StartMatch']==17992
    assert result[-1]['word']=='ab' and result[-1]['number']=='12'

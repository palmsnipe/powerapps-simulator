"""Reference oracles and actual UI-event regex/component integration."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from powerapps_sim.binding import BindScope
from powerapps_sim.conformance import run_case
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError
from powerapps_sim.regex_fx import compile_pattern

CORPUS=json.loads((Path(__file__).parents[1]/'powerapps_sim/conformance_cases/regex.json').read_text())
@pytest.mark.parametrize('case',CORPUS['cases'],ids=lambda c:c['id'])
def test_pinned_regex_oracle(runtime,case):
    result=run_case(runtime,case)
    assert result['status']=='passed',result

@pytest.mark.parametrize('profile,validation,submatches',[
 ('canvas',False,True),('powerfx-legacy',True,True),('powerfx-v1',True,False)])
def test_profile_defaults_and_static_shape(runtime,profile,validation,submatches):
    runtime.environment.update(regex_mode=profile,enum_mode='strong');runtime.analyze()
    assert runtime.fx.evaluate('IsMatch("Hello","H")') is validation
    formula='Match("Hello","(?<letter>H)")'
    typ=runtime.binder.bind(runtime.fx.parse(formula),BindScope())
    value=runtime.fx.evaluate(formula)
    assert set(typ.fields)==set(value)==({'FullMatch','StartMatch','letter','SubMatches'} if submatches else {'FullMatch','StartMatch','letter'})
    assert value['letter']=='H'

@pytest.mark.parametrize('profile,expected',[
 ('canvas',[{'FullMatch':'\ud83d','StartMatch':1,'SubMatches':[]},{'FullMatch':'\ude00','StartMatch':2,'SubMatches':[]}]),
 ('powerfx-v1',[{'FullMatch':'😀','StartMatch':1}])])
def test_unicode_character_profile_and_utf16_positions(runtime,profile,expected):
    runtime.environment['regex_mode']=profile;runtime.analyze()
    assert runtime.fx.evaluate('MatchAll("😀", ".")')==expected
    assert runtime.fx.evaluate('Match("😀é", "é").StartMatch')==3

@pytest.mark.parametrize('newline',['\n','\r','\r\n','\v','\f','\x85','\u2028','\u2029'])
def test_v1_newline_multiline_and_dot(runtime,newline):
    runtime.environment['regex_mode']='powerfx-v1';runtime.analyze()
    runtime.globals['input']='ab'+newline+'cd'
    assert runtime.fx.evaluate('CountRows(MatchAll(input,"[a-z]+",MatchOptions.Complete & MatchOptions.Multiline))')==2
    assert runtime.fx.evaluate('IsMatch(input,".*",MatchOptions.Complete)') is False
    assert runtime.fx.evaluate('IsMatch(input,".*",MatchOptions.Complete & MatchOptions.DotAll)') is True

@pytest.mark.parametrize('formula',[
 'Match("a","(?<=x)a")','Match("a","(?>a)")','Match("a","[a-z-[aeiou]]")',
 'Match("a","(?R)")','Match("a","\\p{IsGreek}")'])
def test_engine_features_never_silently_adopt_python_extensions(runtime,formula):
    runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(formula),BindScope())
    assert any(e.kind=='Unsupported' for _,e in runtime.binder.errors)
    with pytest.raises(FxError) as caught:runtime.fx.evaluate(formula)
    assert caught.value.kind=='Unsupported'


def test_legacy_numbering_duplicate_names_and_backreferences(runtime):
    assert runtime.fx.evaluate('Match("abc","(?<n>a)(b)(?<n>c)")')=={'FullMatch':'abc','StartMatch':1,'n':'c','SubMatches':[{'Value':'b'},{'Value':'c'}]}
    assert runtime.fx.evaluate('IsMatch("abcbb","(?<n>a)(b)(c)\\1\\1")')
    assert runtime.fx.evaluate('Match("a","(?<FullMatch>a)(?<StartMatch>b)?(?<SubMatches>c)?")')=={'FullMatch':'a','StartMatch':None,'SubMatches':None}


def test_constant_contract_runtime_guards_lazy_errors_and_timeout(runtime,monkeypatch):
    runtime.globals['pattern']='a';runtime.environment['regex_mode']='powerfx-v1';runtime.analyze()
    for formula in ('Match("a",pattern)','Match("a","a",If(true,MatchOptions.Contains,MatchOptions.Complete))'):
        with pytest.raises(FxError) as caught:runtime.fx.evaluate(formula)
        assert caught.value.kind=='Type'
    assert runtime.fx.evaluate('If(false,Match("a",pattern),Blank())') is None
    assert runtime.fx.evaluate('IfError(Match(1/0,"a").FullMatch,FirstError.Kind)')=='13'
    assert runtime.fx.evaluate('IsMatch("""a",Char(34) & "a")')
    from powerapps_sim import regex_fx
    monkeypatch.setattr(regex_fx,'TIMEOUT',0)
    with pytest.raises(FxError) as caught:runtime.fx.evaluate('IsMatch("a","a")')
    assert caught.value.kind=='Timeout'


def test_empty_matches_use_dotnet_progression(runtime):
    assert [row['FullMatch'] for row in runtime.fx.evaluate('MatchAll("a", "|a")')]==['','']


def test_match_backing_coercion_and_options_strong_contract(runtime):
    runtime.environment['enum_mode']='strong';runtime.analyze()
    for f in ('Match.Digit & "+"','"^" & Match.Digit','Concatenate("^",Match.Digit,"+$")'):
        value=runtime.fx.evaluate(f)
        assert value.namespace=='Match'
    assert runtime.fx.evaluate('IsMatch("123", "^" & Match.MultipleDigits & "$")')
    runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse('Match("a","a",Match.Email)'),BindScope())
    assert runtime.binder.errors
    assert runtime.fx.evaluate('JSON({Pattern:Match.Email,Option:MatchOptions.IgnoreCase},JSONFormat.Compact)',Context(runtime,behavior=True))=='{"Option":"i","Pattern":".+@.+\\\\.[^.]{2,}"}'

@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('number',['float','decimal'])
def test_regex_component_and_persistence_workflow_preserves_owner(tmp_path,language,number):
    from powerapps_sim.fixtures import regex_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    p=regex_project(tmp_path/'p');w=Workspace(tmp_path,p.root)
    try:
        w.runtime.store.patch('Contacts',{}, {'Title':'Fictional owner record','TokenCount':99})
        w.runtime.restart();before=deepcopy(w.ai.read_runtime());rows=deepcopy(w.runtime.store.rows('Contacts'))
        entry=w.workflows.catalog()['scenarios'][0]
        result=w.workflows.run({**entry['scenario'],'environment':{'enum_mode':'strong','regex_mode':'canvas','language':language,'number_mode':number}},expected_revision=revision(p.root))
        assert result['status']=='passed',[(s.get('step'),s) for s in result['steps'] if s['status']!='passed']
        assert len(result['steps'])==44 and not result['diagnostics']
        assert len(result['collections']['results'][0])==20
        assert w.ai.read_runtime()==before and w.runtime.store.rows('Contacts')==rows
    finally:w.runtime.close()

@pytest.mark.parametrize('formula',['Match("a",JSONFormat.Compact)','Match("a","a","c")','Match("a","a",MatchOptions.Contains & "c")'])
def test_strong_regex_runtime_guards(runtime,formula):
    runtime.environment['enum_mode']='strong';runtime.analyze()
    with pytest.raises(FxError) as caught:runtime.fx.evaluate(formula)
    assert caught.value.kind=='Type'

@pytest.mark.parametrize('pattern,expected', [('s',False),('[a-z]',False),('[^a-z]',True),(r'\p{L}',True),('ſ',True)])
def test_dotnet_simple_case_folding_does_not_fold_long_s(runtime,pattern,expected):
    formula='IsMatch("ſ","'+pattern+'",MatchOptions.IgnoreCase)'
    assert runtime.fx.evaluate(formula) is expected

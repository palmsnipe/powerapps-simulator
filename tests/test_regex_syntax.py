"""Portable syntax oracles, authoring diagnostics and component execution."""
import json
from pathlib import Path
import pytest
from powerapps_sim.conformance import run_case
from powerapps_sim.regex_fx import compile_pattern
from powerapps_sim.syntax import FxError

CORPUS=json.loads((Path(__file__).parents[1]/'powerapps_sim/conformance_cases/regex_syntax.json').read_text())

@pytest.fixture(scope='module')
def portable_runtime(tmp_path_factory):
    from powerapps_sim.runtime import Runtime
    from powerapps_sim.source import Project
    r=Runtime(Project(tmp_path_factory.mktemp('portable-syntax')))
    yield r
    r.close()

@pytest.mark.parametrize('case',CORPUS['cases'],ids=lambda c:c['id'])
def test_pinned_portable_syntax_reference(portable_runtime,case):
    result=run_case(portable_runtime,case)
    assert result['status']=='passed',result

@pytest.mark.parametrize('pattern,options',[
    ('(?ii)a','c'),('(?n)a','N'),('a(?i)b','c'),('(?i)(?m)a','c'),
    ('(?i:a)','c'),('(?-i)a','c'),('(?q)a','c'),('(?i)+','c'),
    ('[a-b-c]','c'),('[a-]','c'),(r'[\d-a]','c'),(r'[a-\p{L}]','c'),
    (r'[^\W]','c'),(r'[^\P{L}]','c'),('[!!]','c'),('[()]','c'),
    ('[😀]','c'),(r'[\u{1f600}]','c'),(r'[\b]','c'),(r'[\1]','N'),
    ('a{2}?','c'),(r'\0','c'),(r'\v','c'),(r'\P{Cs}','c'),
    ('\ud800','c'),(r'\u{D800}\uDC00','c'),(r'[\uD800\uDC00]','c'),
])
def test_invalid_portable_syntax_is_rejected_before_execution(pattern,options):
    with pytest.raises(FxError) as error:compile_pattern(pattern,options,'powerfx-v1')
    assert error.value.kind=='Type'

@pytest.mark.parametrize('profile',['canvas','powerfx-v1'])
@pytest.mark.parametrize('pattern,text,expected',[
    ('s','s',True),('s','S',True),('s','ſ',False),
    ('[s]','s',True),('[s]','S',True),('[s]','ſ',False),
    ('[^s]','s',False),('[^s]','S',False),('[^s]','ſ',True),
    (r'\x73','S',True),(r'\x73','ſ',False),
])
def test_casefold_guards_do_not_exclude_ascii_s(profile,pattern,text,expected):
    compiled=compile_pattern(pattern,'ic',profile)
    assert bool(compiled.compiled.fullmatch(text)) is expected

@pytest.mark.parametrize('separator',['\x1c','\x1d','\x1e','\x1f'])
def test_free_spacing_keeps_non_dotnet_whitespace_literal(separator):
    pattern=compile_pattern('(?x)a'+separator+'b','c','powerfx-v1')
    assert pattern.compiled.fullmatch('a'+separator+'b')
    assert pattern.compiled.fullmatch('ab') is None

@pytest.mark.parametrize('pattern,text',[
    (r'(?i)[\W]+','# /'),(r'(?i)[a\W]+','a/#'),
    (r'(?i)[\D]+','abc#'),(r'[\S\d]+','12abc'),
    (r'(?s)a.b','a\nb'),(r'(?m)^b$','a\nb\nc'),
    (r'(?ix)a[ ]\#b','A #B'),(r'(?n)(a)','a'),
])
def test_valid_portable_options_and_class_unions(pattern,text):
    assert compile_pattern(pattern,'c','powerfx-v1').compiled.search(text)


def test_class_and_options_diagnostics_keep_pattern_source_locations(portable_runtime):
    from powerapps_sim.binding import BindScope
    r=portable_runtime;r.environment.update(regex_mode='powerfx-v1',enum_mode='strong');r.analyze()
    formula='IsMatch("abc", "(?i)[a-b-c]")'
    r.binder.errors.clear();r.binder.bind(r.fx.parse(formula),BindScope())
    location,error=r.binder.errors[0]
    assert error.kind=='Type' and formula[error.start:error.end]=='"(?i)[a-b-c]"'
    assert r.fx.evaluate('If(false,'+formula+',true)') is True
    assert r.fx.evaluate('IfError(Match(1/0,"(?i)[a-z]+").FullMatch,FirstError.Kind)')=='13'

@pytest.mark.parametrize('language',['en-US','fr-CA'])
@pytest.mark.parametrize('number',['float','decimal'])
def test_inline_classes_and_typed_component_workflow_preserves_owner(tmp_path,language,number):
    from copy import deepcopy
    from powerapps_sim.fixtures import regex_syntax_project
    from powerapps_sim.application import Workspace
    from powerapps_sim.authoring import revision
    p=regex_syntax_project(tmp_path/'p');w=Workspace(tmp_path,p.root)
    try:
        w.runtime.store.patch('Contacts',{}, {'Title':'Fictional owner record','TokenCount':99})
        w.runtime.restart()
        before=deepcopy(w.ai.read_runtime());rows=deepcopy(w.runtime.store.rows('Contacts'))
        entry=w.workflows.catalog()['scenarios'][0]
        result=w.workflows.run({**entry['scenario'],'environment':{'enum_mode':'strong','regex_mode':'powerfx-v1','language':language,'number_mode':number}},expected_revision=revision(p.root))
        assert result['status']=='passed',result
        assert len(result['steps'])==77
        assert w.ai.read_runtime()==before
        assert w.runtime.store.rows('Contacts')==rows
    finally:w.runtime.close()

"""Pinned Proper oracles and local casing/component/source contracts."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import json
import pytest
from powerapps_sim.binding import BindScope,TEXT,value_type
from powerapps_sim.conformance import _run_case
from powerapps_sim.fx import Context
from powerapps_sim.runtime import serial
from powerapps_sim.syntax import FxError

CASES=json.loads((Path(__file__).parents[1]/'powerapps_sim/conformance_cases/casing_contracts.json').read_text())['cases']

@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_pinned_proper_outputs_are_independent_oracles(runtime,case):
    runtime.environment.update(case['environment']);runtime.invalidate()
    result=_run_case(runtime,case)
    assert result['status']=='passed',result

@pytest.mark.parametrize('language',['en-CA','fr-CA'])
@pytest.mark.parametrize('raw,expected',[
 ('WE ARE THE BEST!','We Are The Best!'),("DON'T STOP","Don't Stop"),
 ("o'NEILL", "O'neill"),('l’ÉTUDE','L’Étude'),('ÉCOLE-DE-LA-RIVIÈRE','École-De-La-Rivière'),
 ('FISCAL_YEAR','Fiscal_Year'),('ǳUNGLE ǉUICE ǌAMES ǆEM','ǲungle ǈuice ǋames ǅem'),
 ('ßTRAßE ﬃELD','ßtraße ﬃeld'),('İSTANBUL','Istanbul'),('ΟΣ','Οσ'),
 ('e\u0301TUDE','E\u0301tude'),('𐐨𐐀','𐐀𐐨'),('🌲 RIVER\nSURVEY','🌲 River\nSurvey'),
 ('a\u200db','A\u200dB'),('a\u00a0b','A\u00a0B'),('a\ud800B','A\ud800b'),
 # Expected scan behavior follows pinned TextInfo source, not the address
 # example in Canvas documentation. Studio numeric-word behavior is unproven.
 ('789 SW 39th #3B','789 Sw 39Th #3B')])
def test_supported_word_boundaries_simple_maps_and_utf16(runtime,language,raw,expected):
    runtime.environment['language']=language
    runtime.globals['raw']=raw;runtime.binder.globals['raw']=TEXT
    assert runtime.fx.evaluate('Proper(raw)')==expected

@pytest.mark.parametrize('formula,expected',[
 ('Upper("straße")','STRAßE'),('Upper("ﬃeld")','ﬃELD'),
 ('Lower("ΟΣ")','οσ'),('Lower("İ")','i'),('Upper("ᾀ")','ᾈ'),
 ('Upper("𐐨")','𐐀'),('Lower("𐐀")','𐐨'),
 ('Proper(12.5)','12.5'),('Proper(true)','True'),('Proper(Blank())',''),
 ('Proper(["hELLO",Blank(),true])',[{'Value':'Hello'},{'Value':''},{'Value':'True'}]),
 ('Proper(FirstN(["text"],0))',[]),('Proper(If(false,["text"]))',None),
 ('Proper(Left("🌲",1))','\ud83c')])
def test_case_functions_coercion_tables_and_simple_character_identity(runtime,formula,expected):
    assert runtime.fx.evaluate(formula)==expected

@pytest.mark.parametrize('function',['Proper','Lower','Upper'])
def test_table_errors_are_lazy_and_source_records_remain_intact(runtime,function):
    from powerapps_sim.tables import SourceRecord
    rows=[SourceRecord({'Original title':'hELLO'},{'Original title':'Title'}),SourceRecord({'Original title':None},{'Original title':'Title'})]
    runtime.collections['Names']=rows;runtime.binder.collections['Names']=value_type(rows)
    before=deepcopy(serial(rows))
    result=runtime.fx.evaluate(f'{function}(Names)')
    assert result[1]=={'Value':''} and serial(rows)==before
    assert runtime.fx.evaluate('Names').__class__ is list
    typ=runtime.binder.bind(runtime.fx.parse(f'{function}(Names)'),BindScope())
    assert typ.row.fields=={'Value':TEXT}
    errors=runtime.fx.evaluate(f'{function}(Table({{Value:"healthy"}},{{Value:1/0}}))')
    assert errors[0]['Value'] and errors[1]['Value'].kind=='Div0'
    assert runtime.fx.evaluate(f'If(false,{function}(1/0),"kept")')=='kept'

@pytest.mark.parametrize('formula',['Proper()','Proper("a","b")','Proper({Raw:"text"})','Proper([{A:"a",B:"b"}])','Proper(FirstN([{A:"a",B:"b"}],0))','Proper([])'])
def test_invalid_arity_and_shape_are_static_errors(runtime,formula):
    runtime.binder.errors.clear();runtime.binder.bind(runtime.fx.parse(formula),BindScope())
    assert runtime.binder.errors
    with pytest.raises(FxError):runtime.fx.evaluate(formula)

@pytest.mark.parametrize('function',['Proper','Lower','Upper'])
def test_unsupported_culture_is_visible(runtime,function):
    runtime.environment['language']='zz-ZZ'
    with pytest.raises(FxError) as caught:runtime.fx.evaluate(f'{function}("text")')
    assert caught.value.kind=='Unsupported'

@pytest.fixture
def workspace(tmp_path):
    from powerapps_sim.application import Workspace
    from powerapps_sim.fixtures import casing_project
    p=casing_project(tmp_path/'project');w=Workspace(tmp_path,p.root)
    yield w
    w.runtime.close()

@pytest.mark.parametrize('mode',['float','decimal'])
@pytest.mark.parametrize('language',['en-CA','fr-CA'])
def test_components_typed_functions_callbacks_source_edits_and_isolated_workflow(workspace,mode,language):
    from powerapps_sim.authoring import revision,data_revision
    w=workspace;r=w.runtime;r.environment.update(language=language,number_mode=mode);r.restart();r.state()
    assert not r.diagnostics
    r.event('CasingLab/LeftPanel/Input','OnInput',"o'NEILL ÉTUDE")
    assert r.fx.evaluate('LeftPanel.Current.Propered')=="O'neill Étude"
    assert r.fx.evaluate('RightPanel.Current.Propered')=='Étude Rivière'
    r.event('CasingLab/LeftPanel/Input','OnChange',"o'NEILL ÉTUDE")
    assert r.collections['history'][-1]['Propered']=="O'neill Étude"
    assert r.component_state['CasingLab/LeftPanel']['collections']['captured'][-1]['Raw']=="o'NEILL ÉTUDE"
    r.event('CasingLab/Save','OnSelect');r.state()
    assert r.store.rows('Snapshots')[0]['Raw']=="o'NEILL ÉTUDE"
    assert r.store.rows('Snapshots')[0]['Propered']=="O'neill Étude"
    r.store.patch('Titles',r.store.rows('Titles')[0],{'Title':'FICTIONAL OWNED TITLE'});r.invalidate();r.state()
    assert r.fx.evaluate('LeftPanel.Current.Propered')=='Fictional Owned Title'
    before=(revision(w.project.root),data_revision(r.store),serial(w.ai.read_runtime()))
    scenario=deepcopy(w.workflows.catalog()['scenarios'][0]['scenario']);scenario['environment']={'language':language,'number_mode':mode,'enum_mode':'strong'}
    result=w.workflows.run(scenario,expected_revision=before[0])
    assert result['status']=='passed' and len(result['steps'])==29 and not result['diagnostics'],result['steps']
    assert before==(revision(w.project.root),data_revision(r.store),serial(w.ai.read_runtime()))
    assert w.ai.read_runtime()['types']['collections']['errorRows']['row']['fields']['Value']['kind']=='Text'


def test_source_exports_only_authored_functions_and_keeps_original_text(workspace):
    w=workspace
    before=w.ai.export_source();w.ai.read_runtime()
    assert before==w.ai.export_source()
    with ZipFile(BytesIO(w.project.export())) as z:
        assert z.namelist()==['Src/casing.pa.yaml']
        text=z.read(z.namelist()[0]).decode()
    assert 'Proper(' in text and 'Normalize(raw:Text):CaseRow' in text
    assert 'power_case' not in text and 'unicodedata' not in text

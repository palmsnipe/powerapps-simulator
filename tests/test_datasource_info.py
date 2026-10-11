"""Documented metadata defaults, mapped names and local simulation boundaries."""
from copy import deepcopy
from decimal import Decimal
import pytest
from powerapps_sim.source import Project, dump_yaml
from powerapps_sim.runtime import Runtime, serial
from powerapps_sim.fx import Context
from powerapps_sim.binding import BindScope
from powerapps_sim.authoring import revision, data_revision
from powerapps_sim.syntax import FxError


@pytest.fixture(params=['legacy', 'strong'])
def r(tmp_path, request):
    p = Project(tmp_path/'metadata')
    p.update_source('Src/app.pa.yaml', dump_yaml({'App': {'Properties': {'OnStart':'=ClearCollect(items,{Quantity:5});Clear(items)'}}, 'Screens': {'Home': {}}}))
    first = Runtime(p)
    first.store.add_list('IceCream', {'fields': {
        'Flavor': {'type':'string', 'maxLength':30},
        'Quantity': {'type':'number', 'minimum':0, 'maximum':100},
        'Optional': {'type':'string'}, 'Flag': {'type':'boolean', 'required':True},
        'Due': {'type':'string', 'format':'date', 'minimum':'2026-01-01', 'maximum':'2026-12-31'},
        'Choice': {'type':'object', 'properties':{'Value':{'type':'string'}}}},
        'required':['Flavor'], 'mapping':{'Quantity':'Quantity on Hand', 'Flavor':'Flavor label'},
        'choices':{'Choice':['Fictional vanilla']}})
    first.store.patch('IceCream', {}, {'Flavor':'Fictional vanilla','Quantity':10,'Flag':True})
    first.close()
    observed = Runtime(p)
    observed.environment['enum_mode'] = request.param
    observed.restart()
    yield observed
    observed.close()


def bind(r, formula):
    r.binder.errors.clear()
    typ = r.binder.bind(r.fx.parse(formula), BindScope(), ('metadata-test', formula, 0))
    return typ, [error for _, error in r.binder.errors]


@pytest.mark.parametrize('info,col,expected,kind', [
    ('DisplayName','Quantity','Quantity on Hand','Text'),
    ('DisplayName',"'Quantity on Hand'",'Quantity on Hand','Text'),
    ('DisplayName','Flavor','Flavor label','Text'),
    ('DisplayName','Optional','Optional','Text'),
    ('MaxLength','Flavor',30,'Number'), ('MaxLength','Optional',None,'Number'),
    ('MinValue','Quantity',0,'Number'), ('MaxValue','Quantity',100,'Number'),
    ('Required','Flavor',True,'Boolean'), ('Required','Quantity',False,'Boolean'),
    ('Required','Flag',True,'Boolean'), ('Required','Optional',False,'Boolean'),
    ('MaxLength','Quantity',None,'Number'), ('MinValue','Flavor',None,'Number'),
    ('MinValue','Due',None,'Number'), ('MaxValue','Due',None,'Number'),
    ('MaxLength','Due',None,'Number'), ('MaxLength','Choice',None,'Number')])
def test_column_metadata_results_and_types(r, info, col, expected, kind):
    formula = f'DataSourceInfo(IceCream,DataSourceInfo.{info},{col})'
    typ, errors = bind(r, formula)
    assert typ.kind == kind and not errors
    value = r.fx.evaluate(formula)
    assert value == expected and (expected is not None or value is None)
    if kind == 'Boolean': assert isinstance(value,bool)


@pytest.mark.parametrize('col', ['Quantity', "'Quantity on Hand'", '"Quantity"', '"Quantity on Hand"'])
def test_internal_display_and_legacy_column_syntax(r, col):
    assert r.fx.evaluate(f'DataSourceInfo(IceCream,DataSourceInfo.MaxValue,{col})') == 100


@pytest.mark.parametrize('info,expected', [('ReadPermission',True), ('EditPermission',True),
    ('CreatePermission',True), ('DeletePermission',True), ('AllowedValues',None)])
def test_source_defaults_and_readonly_local_gate(r, info, expected):
    formula = f'DataSourceInfo(IceCream,DataSourceInfo.{info})'
    typ, errors = bind(r,formula)
    assert typ.kind == 'Boolean' and not errors
    assert r.fx.evaluate(formula) is expected
    r.store.definitions['IceCream']['writable'] = False
    value = r.fx.evaluate(formula)
    assert value is (True if info == 'ReadPermission' else None if info == 'AllowedValues' else False)
    with pytest.raises(FxError, match='read-only'):
        r.store.patch('IceCream',{}, {'Flavor':'Fictional blocked','Flag':True})


@pytest.mark.parametrize('info,expected', [('DisplayName','Quantity'), ('Required',False),
    ('MinValue',None), ('MaxValue',None), ('MaxLength',None)])
@pytest.mark.parametrize('table', ['Table({Quantity:5})', 'FirstN(IceCream,0)', 'items'])
def test_tables_and_collections_have_no_connector_metadata(r, info, expected, table):
    r.fx.evaluate('ClearCollect(items,{Quantity:5});Clear(items)',Context(r,behavior=True))
    formula = f'DataSourceInfo({table},DataSourceInfo.{info},Quantity)'
    assert not bind(r,formula)[1]
    assert r.fx.evaluate(formula) == expected


@pytest.mark.parametrize('info,expected', [('ReadPermission',True),('CreatePermission',True),
    ('EditPermission',True),('DeletePermission',True),('AllowedValues',None)])
def test_collection_source_defaults(r,info,expected):
    assert r.fx.evaluate(f'DataSourceInfo(Table({{Title:"Fictional"}}),DataSourceInfo.{info})') is expected


@pytest.mark.parametrize('formula', [
    'DataSourceInfo(5,DataSourceInfo.ReadPermission)',
    'DataSourceInfo({Quantity:5},DataSourceInfo.Required,Quantity)',
    'DataSourceInfo(IceCream,DataSourceInfo.Required)',
    'DataSourceInfo(IceCream,DataSourceInfo.DisplayName)',
    'DataSourceInfo(IceCream,DataSourceInfo.MinValue)',
    'DataSourceInfo(IceCream,DataSourceInfo.ReadPermission,Quantity)',
    'DataSourceInfo(IceCream,DataSourceInfo.AllowedValues,Quantity)',
    'DataSourceInfo(IceCream,DataSourceInfo.DisplayName,Missing)',
    'DataSourceInfo(IceCream,DataSourceInfo.DisplayName,"Missing")',
    'DataSourceInfo(Table({Quantity:5}),DataSourceInfo.Required,Missing)',
    'DataSourceInfo(IceCream,DataSourceInfo.Missing,Quantity)',
    'DataSourceInfo(IceCream,DisplayMode.Edit,Quantity)',
    'DataSourceInfo(IceCream,Blank(),Quantity)',
    'DataSourceInfo(IceCream,DataSourceInfo.Required,5)',
    'DataSourceInfo(IceCream,DataSourceInfo.Required,Lower("Flavor"))',
    'DataSourceInfo(IceCream,If(true,DataSourceInfo.Required,DataSourceInfo.DisplayName),Quantity)'])
def test_invalid_calls_have_located_diagnostics(r,formula):
    errors = bind(r,formula)[1]
    assert errors and errors[0].end > errors[0].start
    with pytest.raises(FxError): r.fx.evaluate(formula)


def test_legacy_text_information_is_explicitly_profile_limited(r):
    formula = 'DataSourceInfo(IceCream,"DisplayName",Quantity)'
    if r.environment['enum_mode'] == 'strong':
        assert bind(r,formula)[1]
        with pytest.raises(FxError): r.fx.evaluate(formula)
    else:
        assert not bind(r,formula)[1]
        assert r.fx.evaluate(formula) == 'Quantity on Hand'


def test_metadata_is_pure_and_independent_of_row_reads(r):
    r.fx.evaluate('IfError(Patch(IceCream,Defaults(IceCream),{Flavor:Blank(),Flag:true}),Blank())',Context(r,behavior=True))
    r.store.failures['IceCream'] = 'all'
    owner = (serial(r.globals),serial(r.collections),deepcopy(r.fx.evaluate('Errors(IceCream)')),dict(r.store.failures))
    before = revision(r.project.root), data_revision(r.store)
    assert r.fx.evaluate('DataSourceInfo(IceCream,DataSourceInfo.MaxLength,Flavor)') == 30
    assert r.fx.evaluate('DataSourceInfo(IceCream,DataSourceInfo.DisplayName,Quantity)') == 'Quantity on Hand'
    assert r.fx.evaluate('DataSourceInfo(IceCream,DataSourceInfo.ReadPermission)') is True
    assert (serial(r.globals),serial(r.collections),r.fx.evaluate('Errors(IceCream)'),r.store.failures) == owner
    assert (revision(r.project.root),data_revision(r.store)) == before


def test_formula_errors_remain_errors_and_lazy_branches_remain_lazy(r):
    assert r.fx.evaluate('IfError(DataSourceInfo(Error({Kind:ErrorKind.Network}),DataSourceInfo.ReadPermission),false)') is False
    assert r.fx.evaluate('If(false,DataSourceInfo(Error({Kind:ErrorKind.Network}),DataSourceInfo.ReadPermission),true)') is True


def test_decimal_profile_infers_and_returns_decimal_limits(r):
    r.environment['number_mode'] = 'decimal'
    for info, col in [('MinValue','Quantity'),('MaxValue','Quantity'),('MaxLength','Flavor')]:
        formula = f'DataSourceInfo(IceCream,DataSourceInfo.{info},{col})'
        assert bind(r,formula)[0].kind == 'Decimal'
        assert isinstance(r.fx.evaluate(formula),Decimal)


def test_volatile_properties_observe_metadata_and_local_write_gates(r):
    project = r.project
    project.update_source('Src/app.pa.yaml',dump_yaml({'Screens':{'Home':{'Children':[
        {'Limits':{'Control':'ModernText@1.0.0','Properties':{'Text':'=Text(DataSourceInfo(IceCream,DataSourceInfo.MaxValue,Quantity)) & ":" & Text(Rand())'}}},
        {'Permission':{'Control':'ModernText@1.0.0','Properties':{'Text':'=Text(DataSourceInfo(IceCream,DataSourceInfo.EditPermission)) & ":" & Text(Rand())'}}}]}}}))
    observed = Runtime(project)
    try:
        observed.environment['enum_mode'] = r.environment['enum_mode']
        observed.restart()
        limits, permission = observed.refs['Home/Limits'], observed.refs['Home/Permission']
        first, allowed = limits.property('Text'), permission.property('Text')
        assert first.startswith('100:') and allowed.startswith('true:')
        assert limits.property('Text') == first
        observed.store.definitions['IceCream']['fields']['Quantity']['maximum'] = 75
        observed.store.definitions['IceCream']['writable'] = False
        observed.invalidate()
        assert limits.property('Text').startswith('75:') and limits.property('Text') != first
        assert permission.property('Text').startswith('false:')
    finally:
        observed.close()

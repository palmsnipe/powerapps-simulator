from pathlib import Path
import pytest

from powerapps_sim.binding import BindScope
from powerapps_sim.fx import Context
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project, dump_yaml
from powerapps_sim.syntax import FxError


def make_runtime(tmp_path, source):
    p = Project(tmp_path / 'fixture')
    p.update_source('Src/fixture.pa.yaml', dump_yaml(source))
    assert not p.source_errors
    r = Runtime(p)
    r.restart()
    return r


def bind(r, expression, behavior=False):
    binder = r.binder
    binder.errors.clear()
    t = binder.bind(r.fx.parse(expression), BindScope(behavior=behavior), ('test', '', 0))
    return t, [e.message for _, e in binder.errors]


@pytest.mark.parametrize('expression, expected', [
    ('With({local: 1}, local) + local', 'Unknown identifier local'),
    ('Filter(Table({Known: 1}), Missing = 1)', 'Unknown identifier Missing'),
    ('First(Table({Known: 1})).Missing', 'Unknown field Missing'),
    ('ShowColumns(Table({Known: 1}), Missing)', 'Unknown column Missing'),
    ('Filter(Table({Known: 1}), Known)', 'expected Boolean'),
    ('If({N:1}, 2, 3)', 'expected Boolean'),
    ('Set(private, 1)', 'Behavior functions'),
    ('With({N: 2}, N) + N', 'Unknown identifier N'),
])
def test_lexical_binding_errors(runtime, expression, expected):
    _, errors = bind(runtime, expression)
    assert any(expected in error for error in errors)


@pytest.mark.parametrize('expression', [
    'With({A: 2}, With({A: 3}, A))',
    'ForAll(Table({A: 1}) As outer, LookUp(Table({A: 2}) As inner, inner.A = 2, outer.A))',
    'ForAll(Projects As outer, LookUp(Projects, Projects[@ID] = outer.ID, outer.Title))',
    'IfError(1 / 0, FirstError.Message)',
    'ShowColumns(Table({Known: 1}), Known)',
])
def test_scoped_names_are_valid(runtime, expression):
    _, errors = bind(runtime, expression)
    assert not errors


def test_typed_alias_arguments_return_values_and_registration(tmp_path):
    r = make_runtime(tmp_path, {'App': {'Properties': {'Formulas': '=Result = Read({N: 4}); Read(arg: Row): Number = arg.N; Row := Type({N: Number}); Bad(x: Number): Number = "wrong";'}}, 'Screens': {'Home': {}}})
    try:
        assert r.fx.evaluate('Result') == 4
        assert not r.diagnostics
        with pytest.raises(FxError, match='Cannot parse number'):
            r.fx.evaluate('Bad(2)')
        _, errors = bind(r, 'Read({N: "wrong"})')
        assert not errors
        with pytest.raises(FxError, match='Cannot parse number'):
            r.fx.evaluate('Read({N: "wrong"})')
        _, errors = bind(r, 'arg.N')
        assert any('Unknown identifier arg' in e for e in errors)
        assert r.analysis()['named']['Result']['schema']['kind'] == 'Number'
    finally:
        r.close()


def test_cycles_assignments_and_no_binding_side_effects(tmp_path):
    r = make_runtime(tmp_path, {'App': {'Properties': {'Formulas': '=A = B + 1; B = A + 1;', 'OnStart': '=Set(count, 1); Set(count, "wrong")'}}, 'Screens': {'Home': {}}})
    try:
        assert any(d['kind'] == 'Cycle' for d in r.bind_diagnostics)
        assert any('Set(count)' in d['message'] for d in r.bind_diagnostics)
        before = dict(r.globals)
        r.analysis()
        assert r.globals == before
        with pytest.raises(FxError, match='cycle'):
            r.fx.evaluate('A')
    finally:
        r.close()


def counter_source(access=False):
    customs = {
        'Seed': {'PropertyKind': 'Input', 'DataType': 'Number', 'Default': '=1'},
        'Total': {'PropertyKind': 'Output', 'DataType': 'Number', 'Default': '=Coalesce(counter, Counter.Seed)'},
        'Rows': {'PropertyKind': 'Output', 'DataType': 'Table', 'Default': '=savedRows'},
        'Add': {'PropertyKind': 'Action', 'ReturnType': 'None', 'Parameters': [{'amount': {'DataType': 'Number'}}], 'Default': '=Set(counter, Counter.Total + amount); Collect(savedRows, {N: counter}); Counter.OnChanged(counter)'},
        'Twice': {'PropertyKind': 'Function', 'PropertyDefinition': 'Output', 'ReturnType': 'Number', 'Parameters': [{'number': {'DataType': 'Number'}}], 'Default': '=number * 2'},
        'Format': {'PropertyKind': 'Function', 'PropertyDefinition': 'Input', 'ReturnType': 'Text', 'Parameters': [{'number': {'DataType': 'Number'}}], 'Default': '=Text(number)'},
        'OnChanged': {'PropertyKind': 'Event', 'ReturnType': 'None', 'Parameters': [{'total': {'DataType': 'Number'}}], 'Default': '=Blank()'},
    }
    definition = {'AccessAppScope': access, 'CustomProperties': customs, 'Properties': {'Width': '=300', 'Height': '=100', 'OnReset': '=Set(counter, Counter.Seed); Clear(savedRows)'}, 'Children': [
        {'Increase': {'Control': 'ModernButton@1.0.0', 'Properties': {'OnSelect': '=Counter.Add(1)', 'Text': '=Counter.Format(Counter.Total)'}}},
    ]}
    children = [{name: {'Control': 'CanvasComponent', 'ComponentName': 'Counter', 'Properties': {'Seed': f'={seed}', 'OnChanged': f'=Set({name}Changed, total)', 'Format': f'=Text(number) & " {name}"'}}} for name, seed in [('Left', 10), ('Right', 100)]]
    return {'App': {'Properties': {'OnStart': '=Set(hostValue, 7)'}}, 'ComponentDefinitions': {'Counter': definition}, 'Screens': {'Home': {'Children': children}}}


def test_component_contracts_instance_state_callbacks_and_reset(tmp_path):
    r = make_runtime(tmp_path, counter_source())
    try:
        assert not r.diagnostics
        assert r.fx.evaluate('Left.Twice(3)') == 6
        assert r.refs['Home/Left/Increase'].property('Text') == '10 Left'
        r.event('Home/Left/Increase', 'OnSelect')
        assert r.fx.evaluate('Left.Total') == 11
        assert r.fx.evaluate('Right.Total') == 100
        assert r.fx.evaluate('Left.Rows') == [{'N': 11}]
        assert r.fx.evaluate('Right.Rows') == []
        assert r.globals['LeftChanged'] == 11
        assert 'counter' not in r.globals and 'savedRows' not in r.collections
        assert r.component_state['Home/Left']['variables']['counter'] == 11
        r.fx.evaluate('Reset(Left)', Context(r, behavior=True))
        assert r.fx.evaluate('Left.Total') == 10
        assert r.fx.evaluate('Left.Rows') == []
        assert r.fx.evaluate('Right.Total') == 100
        with pytest.raises(FxError, match='Behavior functions'):
            r.fx.evaluate('Left.Add(1)')
        with pytest.raises(FxError, match='Cannot parse number'):
            r.fx.evaluate('Left.Add("bad")', Context(r, behavior=True))
        _, errors = bind(r, 'Left.Add(1)')
        assert any('behavior formula' in e for e in errors)
        _, errors = bind(r, 'Left.Twice("bad")')
        assert not errors
        assert r.analysis()['component_variables']['Counter']['counter']['schema']['kind'] == 'Number'
    finally:
        r.close()


@pytest.mark.parametrize('access', [False, True])
def test_component_app_scope_and_host_input_context(tmp_path, access):
    source = counter_source(access)
    source['ComponentDefinitions']['Counter']['CustomProperties']['Host'] = {'PropertyKind': 'Output', 'DataType': 'Number', 'Default': '=hostValue'}
    source['Screens']['Home']['Children'][0]['Left']['Properties']['Seed'] = '=hostValue'
    r = make_runtime(tmp_path, source)
    try:
        assert r.fx.evaluate('Left.Seed') == 7  # Input belongs to the host even when app scope is off.
        if access:
            assert r.fx.evaluate('Left.Host') == 7
            r.event('Home/Left/Increase', 'OnSelect')
            assert r.globals['counter'] == 8
            assert r.fx.evaluate('Right.Total') == 8
        else:
            assert any('cannot access app identifier hostValue' in d['message'] for d in r.diagnostics)
            with pytest.raises(FxError, match='cannot access app identifier hostValue'):
                r.fx.evaluate('Left.Host')
    finally:
        r.close()


def test_component_functions_only_use_parameters_and_output_cannot_be_overridden(tmp_path):
    source = counter_source()
    source['ComponentDefinitions']['Counter']['CustomProperties']['Twice']['Default'] = '=number + hostValue'
    source['Screens']['Home']['Children'][0]['Left']['Properties']['Total'] = '=999'
    r = make_runtime(tmp_path, source)
    try:
        assert any('require hostValue to be passed' in d['message'] for d in r.diagnostics)
        with pytest.raises(FxError, match='require hostValue to be passed'):
            r.fx.evaluate('Left.Twice(2)')
        assert r.fx.evaluate('Left.Total') == 10
    finally:
        r.close()


def test_named_formulas_and_udfs_do_not_capture_caller_records(runtime):
    runtime.fx.set_definitions('=GlobalResult = shared; Get(): Number = shared; Empty = Blank();')
    runtime.globals['shared'] = 4
    runtime.invalidate()
    assert runtime.fx.evaluate('With({shared: 999}, GlobalResult)') == 4
    assert runtime.fx.evaluate('With({shared: 999}, Get())') == 4
    assert runtime.fx.evaluate('Empty') is None
    assert 'Empty' in runtime.formula_cache


def test_analysis_endpoint(client):
    report = client.get('/api/analysis').get_json()
    assert report['named']['ProjectRows']['schema']['kind'] == 'Table'
    assert report['note']


def test_defaults_recalculate_reset_user_edits_without_running_onchange(tmp_path):
    source = {'App': {'Properties': {'OnStart': '=Set(seed, "original"); Set(changes, 0)'}}, 'Screens': {'Home': {'Children': [
        {'Input': {'Control': 'ModernTextInput@1.1.2', 'Properties': {'Default': '=seed', 'OnChange': '=Set(changes, changes + 1)'}}},
    ]}}}
    r = make_runtime(tmp_path, source)
    try:
        inp = r.global_refs['Input']
        assert inp.property('Text') == 'original'
        r.event(inp.path, 'OnChange', 'user input')
        assert inp.property('Text') == 'user input'
        r.fx.evaluate('Set(seed, "updated")', Context(r, behavior=True))
        assert inp.property('Text') == 'updated'
        assert not inp.state.get('dirty')
        assert r.globals['changes'] == 1
        r.event(inp.path, 'OnChange', 'another edit')
        r.fx.evaluate('Reset(Input)', Context(r, behavior=True))
        assert inp.property('Text') == 'updated'
        assert r.globals['changes'] == 2
    finally:
        r.close()


def test_gallery_identity_selection_refresh_and_stale_events(runtime):
    gallery = runtime.global_refs['ProjectGallery']
    runtime.render(gallery)
    child = next(ref for ref in runtime.refs.values() if ref.control.name == 'EditProject' and ref.item['ID'] == 2)
    path = child.path
    gallery.state['Selected'] = child.item
    runtime.fx.evaluate('Patch(Projects, LookUp(Projects, ID = 2), {Title: "Changed title"})', Context(runtime, behavior=True))
    assert gallery.property('Selected')['Title'] == 'Changed title'
    gallery.control.properties['Items'] = '=SortByColumns(Projects, "ID", SortOrder.Descending)'
    runtime.invalidate()
    runtime.render(gallery)
    assert runtime.refs[path].item['ID'] == 2
    assert runtime.refs[path].item['Title'] == 'Changed title'
    gallery.control.properties['Items'] = '=Filter(Projects, ID = 1)'
    runtime.invalidate()
    runtime.render(gallery)
    assert gallery.property('Selected')['ID'] == 1
    assert path not in runtime.refs
    with pytest.raises(ValueError, match='no longer exists'):
        runtime.event(path, 'OnSelect')


def test_reset_gallery_preserves_template_inputs_and_enforces_form_boundary(runtime):
    form_input = runtime.global_refs['TitleInput']
    with pytest.raises(FxError, match='same gallery or form'):
        runtime.fx.evaluate('Reset(TitleInput)', Context(runtime, behavior=True))
    runtime.fx.evaluate('Reset(TitleInput)', form_input.context(True))
    runtime.render(runtime.global_refs['ProjectGallery'])
    child = next(ref for ref in runtime.refs.values() if ref.control.name == 'EditProject')
    child.state['test'] = 'retained'
    runtime.fx.evaluate('Reset(ProjectGallery)', Context(runtime, behavior=True))
    assert child.state['test'] == 'retained'


def test_component_parameter_defaults_and_record_shapes(tmp_path):
    source = counter_source()
    source['ComponentDefinitions']['Counter']['CustomProperties']['Twice']['Parameters'][0]['number']['Default'] = '=4'
    source['ComponentDefinitions']['Counter']['CustomProperties']['Twice']['Parameters'][0]['number']['IsOptional'] = True
    source['ComponentDefinitions']['Counter']['CustomProperties']['RecordValue'] = {'PropertyKind': 'Function', 'ReturnType': 'Number', 'Parameters': [{'row': {'IsOptional':True,'DataType': 'Record', 'Default': '={Amount: 0}'}}], 'Default': '=row.Amount'}
    r = make_runtime(tmp_path, source)
    try:
        assert r.fx.evaluate('Left.Twice()') == 8
        assert r.fx.evaluate('Left.RecordValue()') == 0
        assert r.fx.evaluate('Left.RecordValue({Amount: 12})') == 12
        _, errors = bind(r, 'Left.RecordValue({Other: 12})')
        assert not errors
        assert r.fx.evaluate('Left.RecordValue({Other: 12})') is None
        _, errors = bind(r, 'Left.Twice()')
        assert not errors
    finally:
        r.close()


def test_nested_behavior_assignments_infer_their_record_scopes(tmp_path):
    r = make_runtime(tmp_path, {'App': {'Properties': {'OnStart': '=With({Local: 7}, Set(result, Local)); ForAll(Table({Amount: 8}), Collect(saved, {Amount: Amount}))'}}, 'Screens': {'Home': {}}})
    try:
        assert not r.diagnostics
        assert r.globals['result'] == 7
        assert r.analysis()['variables']['result']['schema']['kind'] == 'Number'
        assert r.analysis()['collections']['saved']['schema']['row']['fields']['Amount']['kind'] == 'Number'
        _, errors = bind(r, 'Local + Amount')
        assert len(errors) == 2
    finally:
        r.close()


def test_component_function_bindable_return_conversion_fails_at_runtime(tmp_path):
    source = counter_source()
    source['ComponentDefinitions']['Counter']['CustomProperties']['Twice']['Default'] = '="wrong"'
    r = make_runtime(tmp_path, source)
    try:
        assert not r.diagnostics
        with pytest.raises(FxError, match='Cannot parse number'):
            r.fx.evaluate('Left.Twice(2)')
    finally:
        r.close()


def test_invalid_type_alias_does_not_prevent_other_formulas(tmp_path):
    r = make_runtime(tmp_path, {'App': {'Properties': {'Formulas': '=BadRow := Type({Amount: Nubmer}); Good = 4;'}}, 'Screens': {'Home': {}}})
    try:
        assert any('unknown or recursive type BadRow' in d['message'] for d in r.diagnostics)
        assert r.fx.evaluate('Good') == 4
        assert r.state()['tree']['name'] == 'Home'
    finally:
        r.close()


def test_equal_formula_text_keeps_each_control_scope_type(tmp_path):
    source = {'Screens': {'Home': {'Children': [
        {'Numbers': {'Control': 'GroupContainer@1.4.0', 'Properties': {'Items': '=Table({Value: 1}, {Value: true})'}, 'Children': [{'NumberLabel': {'Control': 'ModernText@1.0.0'}}]}},
        {'Strings': {'Control': 'GroupContainer@1.4.0', 'Properties': {'Items': '=Table({Value: "x"}, {Value: 2})'}, 'Children': [{'StringLabel': {'Control': 'ModernText@1.0.0'}}]}},
    ]}}}
    r = make_runtime(tmp_path, source)
    try:
        a, b = r.global_refs['NumberLabel'], r.global_refs['StringLabel']
        assert r.fx.evaluate('Table(Parent.Items)', a.context()) == [{'Value': 1}, {'Value': 1}]
        assert r.fx.evaluate('Table(Parent.Items)', b.context()) == [{'Value': 'x'}, {'Value': '2'}]
        assert r.fx.evaluate('Table(Parent.Items)', a.context()) == [{'Value': 1}, {'Value': 1}]
    finally:
        r.close()

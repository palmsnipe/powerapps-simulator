"""Theme formulas must behave like other pure App properties."""
import pytest
from powerapps_sim.fx import Context
from powerapps_sim.syntax import FxError


def test_default_theme_has_full_detached_brand_ramp(runtime):
    theme = runtime.fx.evaluate('App.Theme')
    assert theme['Name'] == 'PowerAppsTheme' and theme['Font'] == 'Segoe UI'
    assert len(theme['Colors']) == 16
    assert theme['Colors']['Darker10'] == '#115ea3'
    assert theme['Colors']['Darker70'] == '#061724'
    assert theme['Colors']['Lighter80'] == '#ebf3fc'
    theme['Colors']['Primary'] = 'invalid'
    assert runtime.fx.evaluate('PowerAppsTheme.Colors.Primary') == '#0f6cbd'
    assert runtime.fx.evaluate('App.Theme.Colors.Primary') == '#0f6cbd'
    with pytest.raises(FxError, match='Darker80'):
        runtime.fx.evaluate('App.Theme.Colors.Darker80')


def test_app_theme_formula_is_authoritative_and_reactive(runtime):
    runtime.project.app['Theme'] = '=If(useCustomTheme, {Name:"Custom", Font:"Arial", Colors:{Primary:Color.Red, Darker10:Color.Blue}}, PowerAppsTheme)'
    runtime.fx.evaluate('Set(useCustomTheme, false)', Context(runtime, behavior=True))
    assert runtime.fx.evaluate('App.Theme.Colors.Darker10') == '#115ea3'
    runtime.fx.evaluate('Set(useCustomTheme, true)', Context(runtime, behavior=True))
    assert runtime.fx.evaluate('App.Theme.Name') == 'Custom'
    assert runtime.fx.evaluate('App.Theme.Font') == 'Arial'
    assert runtime.fx.evaluate('App.Theme.Colors.Darker10') == runtime.fx.evaluate('Color.Blue')
    assert runtime.fx.evaluate('PowerAppsTheme.Colors.Darker10') == '#115ea3'


def test_app_theme_errors_and_cycles_are_not_replaced_by_fallback(runtime):
    runtime.project.app['Theme'] = '=UnknownTheme'
    with pytest.raises(FxError, match='UnknownTheme'):
        runtime.fx.evaluate('App.Theme')
    runtime.project.app['Theme'] = '=App.Theme'
    with pytest.raises(FxError) as error:
        runtime.fx.evaluate('App.Theme')
    assert error.value.kind == 'Cycle'
    runtime.project.app['Theme'] = '=PowerAppsTheme'
    assert runtime.fx.evaluate('App.Theme.Colors.Darker10') == '#115ea3'

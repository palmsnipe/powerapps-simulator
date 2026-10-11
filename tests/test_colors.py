"""Documented named colors and ColorFade alpha/range behavior."""
import pytest
from powerapps_sim.colors import catalog,components,fade
from powerapps_sim.fx import ENUMS,Context
from powerapps_sim.syntax import FxError


def test_all_documented_color_names_bind_and_decode(runtime):
    assert len(catalog())==148 and len(ENUMS['Color'])==148
    for name,value in catalog().items():
        assert runtime.fx.evaluate('Color.'+name)==value
        assert runtime.binder.globals['Color'].fields[name].kind=='Color'
        assert runtime.fx.evaluate('ColorValue("'+name.swapcase()+'")')==value
        rgba=components(value);assert all(0<=v<=255 for v in rgba[:3]) and 0<=rgba[3]<=1
    assert not runtime.diagnostics

@pytest.mark.parametrize('formula,expected',[
 ('ColorFade(Color.Red,20%)','rgba(255,51,51,1)'),
 ('ColorFade(Color.DarkBlue,-20%)','rgba(0,0,111.2,1)'),
 ('ColorFade(Color.Transparent,1)','rgba(255,255,255,0)'),
 ('ColorFade(ColorValue("#ff7f5080"),-1)','rgba(0,0,0,0.501961)'),
 ('ColorFade(RGBA(10,20,30,0.25),0)','rgba(10,20,30,0.25)'),
 ('ColorValue("ORANGE")','#ffa500'),
 ('ColorValue("#AABBCCDD")','#aabbccdd'),
])
def test_hex_named_and_rgba_fades_preserve_alpha(runtime,formula,expected):
    assert runtime.fx.evaluate(formula)==expected

@pytest.mark.parametrize('formula',[
 'ColorValue("madeupcolor")','ColorValue("#abcd")','ColorFade(Color.Red,1.01)',
 'ColorFade(Color.Red,-1.01)','ColorFade(Color.Red,1/0)','ColorFade("invalid",0)',
])
def test_invalid_colors_and_ranges_are_errors(runtime,formula):
    with pytest.raises(FxError):runtime.fx.evaluate(formula)


def test_dynamic_color_conversion_and_json_are_validated(runtime):
    assert runtime.fx.evaluate('ColorValue(ParseJSON("""orange"""))')=='#ffa500'
    assert runtime.fx.evaluate('JSON(ColorValue("orange"))',Context(runtime,behavior=True))=='"#ffa500ff"'
    assert runtime.fx.evaluate('IsError(ColorValue(ParseJSON("""invented""")))') is True


def test_fade_accepts_decimal_host_amounts():
    from decimal import Decimal
    assert fade('#ff0000',Decimal('0.2'))=='rgba(255,51,51,1)'

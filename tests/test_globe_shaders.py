"""Shader variants: GLSL 330 (desktop 3.3+), GLSL 150 (GTK's 3.2 core, used on macOS) and GLES 300."""

from frequenzradio.globe import POINTS_VS, SURFACE_FS, SURFACE_VS, _shader_source


def test_glsl150_variant_has_no_explicit_locations_and_keeps_the_body():
    out = _shader_source(POINTS_VS, es=False, glsl=150)
    assert out.startswith("#version 150 core\n")
    assert "layout(" not in out
    assert "in vec3 a_pos;" in out
    assert "in float a_state;" in out


def test_glsl330_and_gles_variants_are_unchanged():
    assert _shader_source(SURFACE_VS, es=False).startswith(
        "#version 330 core\nlayout(location = 0) in vec3 a_pos;")
    assert _shader_source(SURFACE_FS, es=True).startswith("#version 300 es\nprecision highp float;")

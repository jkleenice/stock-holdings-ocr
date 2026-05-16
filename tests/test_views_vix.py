import views.vix as vix_module


def test_vix_module_exports_render_callable():
    assert hasattr(vix_module, "render")
    assert callable(vix_module.render)

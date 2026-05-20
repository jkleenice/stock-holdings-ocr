import views.holdings as holdings_module


def test_holdings_view_exports_render_callable():
    assert hasattr(holdings_module, "render")
    assert callable(holdings_module.render)

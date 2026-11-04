def test_backend_main_import():
    """Verify that backend.main and all routers can be imported without missing dependencies or syntax errors."""
    import backend.main
    assert backend.main.app is not None

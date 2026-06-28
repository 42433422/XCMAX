from runtime import resolve_runtime_value


def test_resolve_runtime_value_requires_configured_value():
    assert resolve_runtime_value({'APP_VALUE': 'verified'}) == 'verified'

def resolve_runtime_value(env):
    value = env.get('APP_VALUE', '')
    if not value:
        raise ValueError('APP_VALUE is required')
    return value

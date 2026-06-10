from xcagi_common.csrf import csrf_tokens_match, generate_csrf_token


def test_generate_csrf_token_length() -> None:
    assert len(generate_csrf_token()) == 64


def test_csrf_tokens_match() -> None:
    t = generate_csrf_token()
    assert csrf_tokens_match(t, t)
    assert not csrf_tokens_match(t, "other")

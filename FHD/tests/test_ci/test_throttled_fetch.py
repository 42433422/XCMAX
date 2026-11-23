"""Upstream rate limits wait without weakening source-integrity assertions."""

from email.message import Message
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest

from tests.fixtures.backend_ci_isolation import retry_throttled_fetch


def limited(code=429, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError("https://example.invalid/source", code, "blocked", headers, None)


@pytest.mark.parametrize("code", [429, 503])
def test_retry_after_and_success(code):
    fetch = Mock(side_effect=[limited(code, retry_after="30"), b"real bytes"])
    sleep = Mock()
    assert retry_throttled_fetch(fetch, sleep=sleep)("same-path") == b"real bytes"
    assert fetch.call_count == 2
    assert all(call.args == ("same-path",) for call in fetch.call_args_list)
    sleep.assert_called_once_with(30)


@pytest.mark.parametrize(
    ("code", "retry_after"),
    [(code, None) for code in (401, 403, 404, 500)] + [(429, "600"), (503, "600")],
)
def test_terminal_errors_are_not_retried(code, retry_after):
    fetch, sleep = Mock(side_effect=limited(code, retry_after=retry_after)), Mock()
    with pytest.raises(HTTPError):
        retry_throttled_fetch(fetch, sleep=sleep)("path")
    assert fetch.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("code", [429, 503])
def test_exhaustion_stays_failure(code):
    fetch, sleep = Mock(side_effect=limited(code)), Mock()
    with pytest.raises(HTTPError):
        retry_throttled_fetch(fetch, sleep=sleep)("path")
    assert fetch.call_count == 3
    assert [call.args for call in sleep.call_args_list] == [(15,), (30,)]

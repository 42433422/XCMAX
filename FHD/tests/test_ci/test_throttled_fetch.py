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


def test_retry_after_and_success():
    fetch = Mock(side_effect=[limited(retry_after="30"), b"real bytes"])
    sleep = Mock()
    assert retry_throttled_fetch(fetch, sleep=sleep)("same-path") == b"real bytes"
    assert fetch.call_count == 2
    assert all(call.args == ("same-path",) for call in fetch.call_args_list)
    sleep.assert_called_once_with(30)


@pytest.mark.parametrize("code", [401, 403, 404, 500])
def test_other_errors_are_not_retried(code):
    fetch, sleep = Mock(side_effect=limited(code)), Mock()
    with pytest.raises(HTTPError):
        retry_throttled_fetch(fetch, sleep=sleep)("path")
    assert fetch.call_count == 1
    sleep.assert_not_called()


def test_exhaustion_stays_failure():
    fetch, sleep = Mock(side_effect=limited()), Mock()
    with pytest.raises(HTTPError):
        retry_throttled_fetch(fetch, sleep=sleep)("path")
    assert fetch.call_count == 3
    assert [call.args for call in sleep.call_args_list] == [(15,), (30,)]


def test_long_retry_after_fails_without_early_retry():
    fetch, sleep = Mock(side_effect=limited(retry_after="600")), Mock()
    with pytest.raises(HTTPError):
        retry_throttled_fetch(fetch, sleep=sleep)("path")
    assert fetch.call_count == 1
    sleep.assert_not_called()

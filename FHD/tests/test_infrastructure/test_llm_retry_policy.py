"""Retry hints are minimum delays, never extensions of an owner's deadline."""

from email.utils import formatdate

import pytest

from app.infrastructure.llm.retry_policy import retry_after_seconds, retry_delay


def test_retry_after_seconds_and_http_date_are_not_clamped_to_backoff_cap():
    assert retry_delay(1, "180") >= 180
    assert retry_delay(3, formatdate(1180, usegmt=True), now=1000) >= 180
    assert retry_after_seconds(formatdate(900, usegmt=True), now=1000) == 0


@pytest.mark.parametrize("hint", [None, "", "-1", "nan", "inf", "invalid-date"])
def test_invalid_retry_hint_uses_finite_exponential_backoff(hint):
    assert retry_after_seconds(hint) is None
    first, second, last = retry_delay(1, hint), retry_delay(2, hint), retry_delay(100000, hint)
    assert 0.25 <= first <= 0.5
    assert 0.5 <= second <= 0.75
    assert last == 5

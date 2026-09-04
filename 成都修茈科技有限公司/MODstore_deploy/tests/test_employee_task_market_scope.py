from __future__ import annotations

import pytest

from modstore_server.employee_task_market import _scope_from_incident


@pytest.mark.parametrize(
    "source",
    [
        "https://xiu-ci.com/news",
        "https://www.xiu-ci.com/",
        "official homepage failure",
        "官网访问失败",
    ],
)
def test_official_site_scope_accepts_only_the_canonical_host_or_explicit_label(source):
    assert _scope_from_incident(source, {}) == "official_site"


@pytest.mark.parametrize(
    "source",
    [
        "https://xiu-ci.com.evil.example/news",
        "https://evil-xiu-ci.com/news",
        "https://notxiu-ci.com/news",
    ],
)
def test_official_site_scope_rejects_hostname_confusion(source):
    assert _scope_from_incident(source, {}) == "global"

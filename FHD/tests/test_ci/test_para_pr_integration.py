import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from scripts.ci import ai_self_heal_sla as sla
from scripts.ci import para_pr_integration as integration

SHA = "a" * 40


@pytest.mark.parametrize(
    ("utc", "expected"),
    [
        ("2026-11-19T17:59:59+00:00", False),
        ("2026-11-19T18:00:00+00:00", True),
        ("2026-11-19T20:59:59+00:00", True),
        ("2026-11-19T21:00:00+00:00", False),
    ],
)
def test_shanghai_time_boundary(utc, expected):
    assert integration.integration_window_open(datetime.fromisoformat(utc)) is expected


def test_queue_binds_head_and_preserves_order():
    item = f'{{"pr":9,"head_sha":"{SHA}"}}'
    assert list(integration.integration_queue(f'[{item},{{"pr":2,"head_sha":"{SHA}"}}]')) == [9, 2]
    assert integration.integration_queue("") == {}
    with pytest.raises(ValueError, match="duplicate"):
        integration.integration_queue(f"[{item},{item}]")
    with pytest.raises(ValueError, match="full reviewed head"):
        integration.integration_queue('[{"pr":9,"head_sha":"abcd"}]')


def _pull(number, *, head=SHA, labels=(), merged=False):
    return {
        "number": number,
        "title": f"PR {number}",
        "html_url": f"https://github.com/{integration.REPOSITORY}/pull/{number}",
        "created_at": "2026-11-19T00:00:00Z",
        "state": "closed" if merged else "open",
        "draft": False,
        "merged": merged,
        "merge_commit_sha": "e" * 40 if merged else None,
        "user": {"login": "maintainer"},
        "base": {"ref": "main", "repo": {"full_name": integration.REPOSITORY}},
        "head": {"sha": head, "ref": f"feature/{number}"},
        "labels": [{"name": label} for label in labels],
    }


@pytest.mark.parametrize("head", [SHA, "f" * 40])
def test_queue_cannot_skip_an_unready_or_changed_head(monkeypatch, head):
    monkeypatch.setattr(integration, "integration_window_open", lambda: True)
    get_pr = MagicMock(side_effect=[_pull(3, merged=True), _pull(2, head=head)])
    handler = MagicMock(return_value="skipped")
    assert integration.process_integration_queue(
        {3: SHA, 2: SHA, 1: SHA}, get_pr, handler, dry_run=False
    )
    assert [call.args[0] for call in get_pr.call_args_list] == [3, 2]
    assert handler.call_count == int(head == SHA)


def test_merge_request_is_suppressed_at_cutoff(monkeypatch):
    client = sla.GitHubClient(integration.REPOSITORY, "fake")
    http = MagicMock()
    monkeypatch.setattr(client, "client", http)
    monkeypatch.setattr(sla, "integration_window_open", lambda: False)
    assert client.merge_pr(2, expected_head_sha=SHA) == (
        False,
        integration.WINDOW_CLOSED,
        "",
    )
    http.put.assert_not_called()


def test_integration_respects_unresolved_review_veto(monkeypatch):
    client = sla.GitHubClient(integration.REPOSITORY, "fake")
    pr = client._pr_info(_pull(2), "regular")
    reviews = [
        {
            "user": {"login": "reviewer"},
            "author_association": "COLLABORATOR",
            "state": "CHANGES_REQUESTED",
        },
        {
            "user": {"login": "maintainer"},
            "author_association": "OWNER",
            "state": "APPROVED",
        },
    ]
    monkeypatch.setattr(client, "_pages", lambda _: reviews)
    assert client.check_integration_reviews(pr) == (False, "review:changes_requested")
    reviews.append({**reviews[0], "state": "DISMISSED"})
    assert client.check_integration_reviews(pr) == (True, "ok")


@pytest.mark.parametrize(
    ("window_open", "hold_first", "behind_second", "merge_order"),
    [
        (False, False, False, []),
        (True, False, False, [9, 1, 2]),
        (True, True, False, []),
        (True, False, True, [9]),
    ],
)
def test_scheduled_workflow_uses_only_the_ordered_queue(
    monkeypatch, window_open, hold_first, behind_second, merge_order
):
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    monkeypatch.setenv("GITHUB_REPOSITORY", integration.REPOSITORY)
    monkeypatch.setenv(
        integration.QUEUE_VARIABLE,
        json.dumps([{"pr": number, "head_sha": SHA} for number in (9, 1, 2)]),
    )
    monkeypatch.setattr(integration, "integration_window_open", lambda: window_open)
    monkeypatch.setattr(sla, "integration_window_open", lambda: window_open)
    monkeypatch.setattr(sla, "load_trusted_authors", lambda _: ["maintainer"])
    monkeypatch.setattr(sla, "_append_stale", MagicMock())
    client = MagicMock(spec=sla.GitHubClient)
    client.repo = integration.REPOSITORY
    client.get_pr.side_effect = lambda number: _pull(
        number, labels=["hold-merge"] if hold_first and number == 9 else []
    )
    client._pr_info.side_effect = sla.GitHubClient._pr_info
    client.list_self_heal_prs.return_value = []
    client.list_pending_deliveries.return_value = [42]
    client.reconcile_delivery.return_value = "pending"
    client.get_workflow_run_conclusion.return_value = (True, "ok")
    client.get_pr_check_runs.return_value = (True, "ok")
    client.check_integration_reviews.return_value = (True, "ok")
    client.get_pr_mergeability.side_effect = lambda number: (
        True,
        "behind" if behind_second and number == 1 else "ok",
    )
    client.check_merge_snapshot.return_value = (True, "ok")
    client.merge_pr.return_value = (True, "ok", "b" * 40)
    client.update_pr_branch.return_value = (True, "ok")
    monkeypatch.setattr(sla, "GitHubClient", lambda *_: client)

    assert sla.main(["--scan-regular-prs"]) == 0
    client.list_regular_prs.assert_not_called()
    assert client.reconcile_delivery.call_args_list[0].args == (42,)
    assert [call.args[0] for call in client.merge_pr.call_args_list] == merge_order
    if behind_second:
        client.update_pr_branch.assert_called_once_with(1, SHA)
    else:
        client.update_pr_branch.assert_not_called()

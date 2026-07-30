"""ai_review.py 单元测试。

覆盖：
- parse_diff 解析 diff hunks
- match_high_risk_rules shell=True / eval / pickle.loads / 硬编码 secret
- call_llm_review fail-open（mock 超时返回 'false-positive'）
- post_line_comment mock github API
- confirmed-high 阻断（exit 1）
- LLM 故障 fail-open（不阻断）
- 无 finding 通过（exit 0）
- pragma: no cover 低危不阻断
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 把 FHD/scripts/ci 加入 sys.path 以便直接 import ai_review 模块
FHD_ROOT = Path(__file__).resolve().parents[2]
CI_SCRIPTS = FHD_ROOT / "scripts" / "ci"
if str(CI_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CI_SCRIPTS))

import ai_review as review  # noqa: E402

# =====================================================================
# parse_diff 测试
# =====================================================================


class TestParseDiff:
    def test_empty_diff_returns_empty(self) -> None:
        assert review.parse_diff("") == []
        assert review.parse_diff(None) == []  # type: ignore[arg-type]

    def test_single_file_single_hunk(self) -> None:
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "index 111..222 100644\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -10,3 +10,4 @@ def hello():\n"
            "     x = 1\n"
            "     y = 2\n"
            "+    z = x + y\n"
            "     return z\n"
        )
        hunks = review.parse_diff(diff)
        assert len(hunks) == 1
        hunk = hunks[0]
        assert hunk.file_path == "foo.py"
        assert hunk.start_line == 10
        # 5 行：context + context + add + context（注意 +++/--- 行被跳过）
        assert len(hunk.lines) == 4
        added = [ln for ln in hunk.lines if ln[1] == "+"]
        assert len(added) == 1
        assert added[0][0] == 12  # 第 12 行（10 + 2 context）
        assert "z = x + y" in added[0][2]

    def test_multiple_files(self) -> None:
        diff = (
            "diff --git a/a.py b/a.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-old\n"
            "+new\n"
            "diff --git a/b.py b/b.py\n"
            "@@ -5,1 +5,1 @@\n"
            "-x\n"
            "+y\n"
        )
        hunks = review.parse_diff(diff)
        assert len(hunks) == 2
        assert hunks[0].file_path == "a.py"
        assert hunks[1].file_path == "b.py"

    def test_quoted_paths_supported(self) -> None:
        diff = (
            'diff --git "a/中文/含空格 文件.py" "b/中文/含空格 文件.py"\n'
            "@@ -1,2 +1,2 @@\n"
            "-old line\n"
            "+new line\n"
            "diff --git a/c.py b/c.py\n"
            "@@ -3,1 +3,1 @@\n"
            "-x\n"
            "+y\n"
        )
        hunks = review.parse_diff(diff)
        assert len(hunks) == 2
        assert hunks[0].file_path == "中文/含空格 文件.py"
        assert hunks[1].file_path == "c.py"

    def test_hunk_with_no_additions(self) -> None:
        diff = "diff --git a/foo.py b/foo.py\n@@ -1,2 +1,2 @@\n context\n-removed\n context2\n"
        hunks = review.parse_diff(diff)
        assert len(hunks) == 1
        additions = [ln for ln in hunks[0].lines if ln[1] == "+"]
        assert len(additions) == 0


# =====================================================================
# match_high_risk_rules 测试
# =====================================================================


class TestMatchRules:
    def test_subprocess_shell_true_detected(self) -> None:
        hunks = [
            review.DiffHunk(
                file_path="evil.py",
                start_line=10,
                lines=[(10, "+", "subprocess.run('rm -rf /', shell=True)")],
                raw_header="@@ -10,1 +10,1 @@",
            )
        ]
        findings = review.match_high_risk_rules(hunks)
        assert len(findings) == 1
        assert findings[0].rule == "subprocess-shell-true"
        assert findings[0].severity == "high"
        assert findings[0].line == 10

    def test_eval_detected(self) -> None:
        hunks = [
            review.DiffHunk(
                file_path="evil.py",
                start_line=1,
                lines=[(1, "+", "result = eval(user_input)")],
                raw_header="@@ -1,1 +1,1 @@",
            )
        ]
        findings = review.match_high_risk_rules(hunks)
        assert any(f.rule == "eval" for f in findings)

    def test_exec_detected(self) -> None:
        hunks = [
            review.DiffHunk(
                file_path="evil.py",
                start_line=1,
                lines=[(1, "+", "exec(code)")],
                raw_header="@@ -1,1 +1,1 @@",
            )
        ]
        findings = review.match_high_risk_rules(hunks)
        assert any(f.rule == "exec" for f in findings)

    def test_ai_review_tooling_high_rules_are_skipped(self) -> None:
        hunks = [
            review.DiffHunk(
                file_path="FHD/scripts/ci/ai_review.py",
                start_line=330,
                lines=[
                    (
                        330,
                        "+",
                        r'"禁止 document.write()，已废弃且阻塞渲染；改用 DOM API 或 innerHTML+净化。"',
                    ),
                    (
                        331,
                        "+",
                        r'"禁止 new Function()，等价 eval() 可致代码注入；改用闭包或显式解析器。"',
                    ),
                ],
                raw_header="@@ -330,2 +330,2 @@",
            )
        ]
        findings = review.match_high_risk_rules(hunks)
        assert not any(f.severity in {"high", "medium"} for f in findings)

    def test_os_system_detected(self) -> None:
        hunks = [
            review.DiffHunk(
                file_path="evil.py",
                start_line=1,
                lines=[(1, "+", "os.system('rm -rf /')")],
                raw_header="@@ -1,1 +1,1 @@",
            )
        ]
        findings = review.match_high_risk_rules(hunks)
        assert any(f.rule == "os-system" for f in findings)

    def test_pickle_loads_detected(self) -> None:
        hunks = [
            review.DiffHunk(
                file_path="evil.py",
                start_line=1,
                lines=[(1, "+", "obj = pickle.loads(data)")],
                raw_header="@@ -1,1 +1,1 @@",
            )
        ]
        findings = review.match_high_risk_rules(hunks)
        assert any(f.rule == "pickle-loads" for f in findings)

    def test_hardcoded_aws_secret_detected(self) -> None:
        hunks = [
            review.DiffHunk(
                file_path="config.py",
                start_line=1,
                lines=[(1, "+", "AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'")],
                raw_header="@@ -1,1 +1,1 @@",
            )
        ]
        findings = review.match_high_risk_rules(hunks)
        assert any(f.rule == "hardcoded-aws-secret" for f in findings)

    def test_hardcoded_github_token_detected(self) -> None:
        hunks = [
            review.DiffHunk(
                file_path="config.py",
                start_line=1,
                lines=[(1, "+", "TOKEN = 'ghp_' + 'a' * 36")],  # noqa: S105 - 测试用
                raw_header="@@ -1,1 +1,1 @@",
            )
        ]
        # 简化：直接构造完整 token 字符串
        hunks[0].lines = [(1, "+", "TOKEN = 'ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789'")]  # noqa: S105
        findings = review.match_high_risk_rules(hunks)
        assert any(f.rule == "hardcoded-aws-secret" for f in findings)

    def test_yaml_load_no_loader_detected(self) -> None:
        hunks = [
            review.DiffHunk(
                file_path="config.py",
                start_line=1,
                lines=[(1, "+", "data = yaml.load(text)")],
                raw_header="@@ -1,1 +1,1 @@",
            )
        ]
        findings = review.match_high_risk_rules(hunks)
        assert any(f.rule == "yaml-load-no-loader" for f in findings)
        assert findings[0].severity == "medium"

    def test_yaml_load_with_safe_loader_not_detected(self) -> None:
        hunks = [
            review.DiffHunk(
                file_path="config.py",
                start_line=1,
                lines=[(1, "+", "data = yaml.load(text, Loader=yaml.SafeLoader)")],
                raw_header="@@ -1,1 +1,1 @@",
            )
        ]
        findings = review.match_high_risk_rules(hunks)
        assert all(f.rule != "yaml-load-no-loader" for f in findings)

    def test_requests_verify_false_detected(self) -> None:
        hunks = [
            review.DiffHunk(
                file_path="client.py",
                start_line=1,
                lines=[(1, "+", "requests.get(url, verify=False)")],
                raw_header="@@ -1,1 +1,1 @@",
            )
        ]
        findings = review.match_high_risk_rules(hunks)
        assert any(f.rule == "requests-verify-false" for f in findings)

    def test_pragma_no_cover_detected_as_low(self) -> None:
        hunks = [
            review.DiffHunk(
                file_path="foo.py",
                start_line=10,
                lines=[(10, "+", "    if x:  # pragma: no cover")],
                raw_header="@@ -10,1 +10,1 @@",
            )
        ]
        findings = review.match_high_risk_rules(hunks)
        assert len(findings) == 1
        assert findings[0].rule == "pragma-no-cover"
        assert findings[0].severity == "low"

    def test_business_and_performance_rules_detected(self) -> None:
        hunks = [
            review.DiffHunk(
                file_path="svc.py",
                start_line=1,
                lines=[
                    (1, "+", "while True:"),
                    (2, "+", "    time.sleep(1)"),
                    (3, "+", "    rows = cur.fetchall()"),
                    (4, "+", "for u in users: db.query(User).get(u.id)"),
                    (5, "+", "except Exception: pass"),
                ],
                raw_header="@@ -1,1 +1,5 @@",
            )
        ]
        rules = {f.rule for f in review.match_high_risk_rules(hunks)}
        assert "unbounded-while-true" in rules
        assert "time-sleep-hot-path" in rules
        assert "fetchall-unbounded" in rules
        assert "n-plus-one-inline" in rules
        assert "bare-except-pass" in rules

    def test_only_added_lines_checked(self) -> None:
        """删除行（'-'）中的高危代码不应触发 finding。"""
        hunks = [
            review.DiffHunk(
                file_path="foo.py",
                start_line=1,
                lines=[
                    (0, "-", "subprocess.run('rm', shell=True)"),
                    (1, "+", "safe_call()"),
                ],
                raw_header="@@ -1,1 +1,1 @@",
            )
        ]
        findings = review.match_high_risk_rules(hunks)
        assert len(findings) == 0

    def test_kb_evidence_diff_does_not_trigger_executable_code_rules(self) -> None:
        hunks = [
            review.DiffHunk(
                file_path="FHD/XCAGI/kb/fixes/example.json",
                start_line=7,
                lines=[
                    (
                        7,
                        "+",
                        '"fix_diff": "for u in users: db.query(User).get(u.id)\\nwhile True:",',
                    )
                ],
                raw_header="@@ -7,1 +7,1 @@",
            )
        ]
        findings = review.match_high_risk_rules(hunks)
        assert not any(
            finding.rule in {"n-plus-one-inline", "unbounded-while-true"} for finding in findings
        )

    def test_kb_evidence_still_scans_for_committed_secrets(self) -> None:
        hunks = [
            review.DiffHunk(
                file_path="FHD/XCAGI/kb/fixes/example.json",
                start_line=7,
                lines=[
                    (
                        7,
                        "+",
                        '"fix_diff": "TOKEN = \'ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789\'",',
                    )
                ],
                raw_header="@@ -7,1 +7,1 @@",
            )
        ]
        findings = review.match_high_risk_rules(hunks)
        assert any(finding.rule == "hardcoded-aws-secret" for finding in findings)

    def test_dedup_same_rule_same_line(self) -> None:
        hunks = [
            review.DiffHunk(
                file_path="foo.py",
                start_line=10,
                lines=[
                    (10, "+", "subprocess.run('rm', shell=True)"),
                    (10, "+", "subprocess.run('rm', shell=True)"),
                ],
                raw_header="@@ -10,1 +10,1 @@",
            )
        ]
        findings = review.match_high_risk_rules(hunks)
        assert len(findings) == 1


# =====================================================================
# call_llm_review fail-closed 测试
# =====================================================================


class TestCallLlmReview:
    def test_no_api_key_returns_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_LLM_API_KEY", raising=False)
        finding = review.Finding(
            file_path="f",
            line=1,
            rule="eval",
            severity="high",
            snippet="eval()",
            suggestion="don't",
        )
        assert review.call_llm_review(finding) == "unavailable"

    def test_timeout_returns_unavailable(self) -> None:
        finding = review.Finding(
            file_path="f",
            line=1,
            rule="eval",
            severity="high",
            snippet="eval()",
            suggestion="don't",
        )
        client = MagicMock()
        client.post.side_effect = TimeoutError("timeout")
        result = review.call_llm_review(finding, api_key="k", client=client)
        assert result == "unavailable"

    def test_http_500_returns_unavailable(self) -> None:
        finding = review.Finding(
            file_path="f",
            line=1,
            rule="eval",
            severity="high",
            snippet="eval()",
            suggestion="don't",
        )
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 500
        client.post.return_value = resp
        result = review.call_llm_review(finding, api_key="k", client=client)
        assert result == "unavailable"

    def test_valid_response_returns_verdict(self) -> None:
        finding = review.Finding(
            file_path="f",
            line=1,
            rule="eval",
            severity="high",
            snippet="eval()",
            suggestion="don't",
        )
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"verdict": "high"}
        client.post.return_value = resp
        result = review.call_llm_review(finding, api_key="k", client=client)
        assert result == "high"

    def test_invalid_verdict_returns_unavailable(self) -> None:
        finding = review.Finding(
            file_path="f",
            line=1,
            rule="eval",
            severity="high",
            snippet="eval()",
            suggestion="don't",
        )
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"verdict": "bogus"}
        client.post.return_value = resp
        result = review.call_llm_review(finding, api_key="k", client=client)
        assert result == "unavailable"

    def test_minimax_token_plan_uses_anthropic_protocol(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("XCAGI_LLM_ENDPOINT", "")
        monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://api.minimaxi.com/v1")
        monkeypatch.setenv("XCAGI_LLM_MODEL", "minimax/MiniMax-M2.7")
        finding = review.Finding(
            file_path="worker.py",
            line=9,
            rule="time-sleep-hot-path",
            severity="medium",
            snippet="time.sleep(delay)",
            suggestion="use bounded waiting",
        )
        client = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "content": [{"type": "text", "text": '{"verdict":"false-positive"}'}]
        }
        client.post.return_value = response

        result = review.call_llm_review(
            finding,
            api_key="minimaxsk-cp-test",
            client=client,
        )

        assert result == "false-positive"
        request_url = client.post.call_args.args[0]
        request = client.post.call_args.kwargs
        assert request_url == "https://api.minimaxi.com/anthropic/v1/messages"
        assert request["headers"]["x-api-key"] == "sk-cp-test"
        assert request["json"]["model"] == "MiniMax-M2.7"

    def test_openai_compatible_route_parses_chat_verdict(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("XCAGI_LLM_ENDPOINT", "")
        monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://api.example.test")
        monkeypatch.setenv("XCAGI_LLM_MODEL", "review-model")
        finding = review.Finding(
            file_path="worker.py",
            line=9,
            rule="fetchall-unbounded",
            severity="medium",
            snippet="rows = cursor.fetchall()",
            suggestion="use a bound",
        )
        client = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"choices": [{"message": {"content": '{"verdict":"low"}'}}]}
        client.post.return_value = response

        result = review.call_llm_review(finding, api_key="payg-test", client=client)

        assert result == "low"
        assert client.post.call_args.args[0] == ("https://api.example.test/v1/chat/completions")


# =====================================================================
# post_line_comment 测试
# =====================================================================


class TestPostLineComment:
    def test_no_token_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_REPOSITORY", "a/b")
        ok = review.post_line_comment(1, "f.py", 10, "body")
        assert ok is False

    def test_no_pr_number_returns_false(self) -> None:
        ok = review.post_line_comment(0, "f.py", 10, "body", token="t", repo="a/b")
        assert ok is False

    def test_success_returns_true(self) -> None:
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 201
        client.post.return_value = resp
        ok = review.post_line_comment(
            1,
            "f.py",
            10,
            "body",
            token="t",
            repo="a/b",
            client=client,
        )
        assert ok is True

    def test_http_error_returns_false(self) -> None:
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 422
        client.post.return_value = resp
        ok = review.post_line_comment(
            1,
            "f.py",
            10,
            "body",
            token="t",
            repo="a/b",
            client=client,
        )
        assert ok is False

    def test_exception_returns_false(self) -> None:
        client = MagicMock()
        client.post.side_effect = RuntimeError("boom")
        ok = review.post_line_comment(
            1,
            "f.py",
            10,
            "body",
            token="t",
            repo="a/b",
            client=client,
        )
        assert ok is False


# =====================================================================
# fetch_pr_diff 测试
# =====================================================================


class TestFetchPrDiff:
    def test_no_token_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_REPOSITORY", "a/b")
        assert review.fetch_pr_diff(1) == ""

    def test_no_repo_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        assert review.fetch_pr_diff(1) == ""

    def test_no_pr_number_returns_empty(self) -> None:
        assert review.fetch_pr_diff(0, token="t", repo="a/b") == ""

    def test_http_error_returns_empty(self) -> None:
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 404
        client.get.return_value = resp
        assert review.fetch_pr_diff(1, token="t", repo="a/b", client=client) == ""

    def test_success_returns_text(self) -> None:
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "diff --git a/foo b/foo"
        client.get.return_value = resp
        result = review.fetch_pr_diff(1, token="t", repo="a/b", client=client)
        assert "diff --git" in result


# =====================================================================
# main 集成测试
# =====================================================================


class TestMain:
    def test_no_pr_number_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PR_NUMBER", raising=False)
        monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
        rc = review.main([])
        assert rc == 2

    def test_empty_diff_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(review, "fetch_pr_diff", lambda *a, **k: "")
        assert review.main(["--pr-number", "1"]) == 2

    def test_no_finding_passes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 构造无 finding 的 diff
        diff = "diff --git a/foo.py b/foo.py\n@@ -1,1 +1,1 @@\n+x = 1\n"
        monkeypatch.setattr(review, "fetch_pr_diff", lambda *a, **k: diff)
        rc = review.main(["--pr-number", "1", "--dry-run"])
        assert rc == 0

    def test_confirmed_high_blocks(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        diff = "diff --git a/evil.py b/evil.py\n@@ -1,1 +1,1 @@\n+result = eval(user_input)\n"
        monkeypatch.setattr(review, "fetch_pr_diff", lambda *a, **k: diff)
        # 不实际发评论
        monkeypatch.setattr(review, "post_line_comment", lambda *a, **k: True)
        rc = review.main(["--pr-number", "1"])
        assert rc == 1

    def test_medium_llm_failure_fails_open(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """LLM 不可用时 fail-open 不阻断（符合 cicd-e2e-prompt.md 决策矩阵）。"""
        diff = (
            "diff --git a/client.py b/client.py\n"
            "@@ -1,1 +1,1 @@\n"
            "+requests.get(url, verify=" + "False)\n"
        )
        monkeypatch.setattr(review, "fetch_pr_diff", lambda *a, **k: diff)
        monkeypatch.setattr(
            review,
            "call_llm_review",
            lambda *a, **k: "unavailable",
        )
        monkeypatch.setattr(review, "post_line_comment", lambda *a, **k: True)
        rc = review.main(["--pr-number", "1"])
        assert rc == 0  # fail-open：LLM 不可用不阻断

    def test_pragma_no_cover_does_not_block(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """pragma: no cover 是低危，不应阻断（无需 LLM 复核）。"""
        diff = "diff --git a/foo.py b/foo.py\n@@ -10,1 +10,1 @@\n+    if x:  # pragma: no cover\n"
        monkeypatch.setattr(review, "fetch_pr_diff", lambda *a, **k: diff)
        called = {"llm": False}

        def fake_llm(*a: object, **k: object) -> str:
            called["llm"] = True
            return "high"

        monkeypatch.setattr(review, "call_llm_review", fake_llm)
        monkeypatch.setattr(review, "post_line_comment", lambda *a, **k: True)
        rc = review.main(["--pr-number", "1"])
        assert rc == 0  # 不阻断
        assert called["llm"] is False  # 低危不调用 LLM

    def test_dry_run_does_not_comment_or_block(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        diff = "diff --git a/evil.py b/evil.py\n@@ -1,1 +1,1 @@\n+result = eval(user_input)\n"
        monkeypatch.setattr(review, "fetch_pr_diff", lambda *a, **k: diff)
        monkeypatch.setattr(review, "call_llm_review", lambda *a, **k: "high")
        commented = {"called": False}

        def fake_comment(*a: object, **k: object) -> bool:
            commented["called"] = True
            return True

        monkeypatch.setattr(review, "post_line_comment", fake_comment)
        rc = review.main(["--pr-number", "1", "--dry-run"])
        assert rc == 0
        assert commented["called"] is False

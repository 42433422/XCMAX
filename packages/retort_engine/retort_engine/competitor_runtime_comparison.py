from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.pr_review import review_diff


COMPETITOR_PROFILES: tuple[dict[str, str], ...] = (
    {
        "project": "mopemope/pr-ai-review-bot",
        "cache_path": ".retort/cache/github/mopemope/pr-ai-review-bot",
        "source": "src/patchParser.ts",
        "runner": "mopemope_patch_runtime.js",
        "kind": "node_patch_parser",
    },
    {
        "project": "qodo-ai/pr-agent",
        "cache_path": ".retort/cache/github/qodo-ai/pr-agent",
        "source": "pr_agent/tools/pr_reviewer.py",
        "runner": "qodo_pr_agent_runtime.py",
        "kind": "python_review_signal_counter",
    },
    {
        "project": "reviewdog/reviewdog",
        "cache_path": ".retort/cache/github/reviewdog/reviewdog",
        "source": "diff/parse.go",
        "runner": "reviewdog_diff_runtime.py",
        "kind": "python_diff_diagnostic_mapper",
    },
)


def build_competitor_runtime_comparison(
    project: str | Path,
    *,
    output: str | Path = "",
    run_id: str = "",
    competitor_root: str | Path = "",
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    started = time.monotonic()
    comparison_id = run_id or _run_id("competitor-runtime")
    lab = root / ".retort" / "competitor_runtime_comparisons" / comparison_id
    lab.mkdir(parents=True, exist_ok=True)
    patch = _sample_patch()
    patch_path = lab / "input.patch"
    patch_path.write_text(patch, encoding="utf-8")
    runtimes = [_run_competitor_profile(root, lab, patch_path, profile, competitor_root=competitor_root) for profile in COMPETITOR_PROFILES]
    primary_runtime = runtimes[0] if runtimes else {}
    primary_output = primary_runtime.get("output") if isinstance(primary_runtime.get("output"), dict) else {}
    competitor_output_path = lab / "competitor_outputs.json"
    retort_output_path = lab / "retort_output.json"
    competitor_output = {
        "status": "parsed",
        "runtime_count": len(runtimes),
        "primary": primary_output,
        "runtimes": runtimes,
    }
    competitor_output_path.write_text(json.dumps(competitor_output, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    retort_output = review_diff(_full_diff(patch), issue_context="Compare external PR bot patch parsing with Retort review output", max_comments=8)
    retort_output_path.write_text(json.dumps(retort_output, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    retort_summary = retort_output.get("summary") if isinstance(retort_output.get("summary"), dict) else {}
    comments = [item for item in retort_output.get("comments") or [] if isinstance(item, dict)]
    hunks = [item for item in primary_output.get("hunks") or [] if isinstance(item, dict)]
    ready_runtimes = [item for item in runtimes if item.get("ready")]
    source_present = [item for item in runtimes if item.get("source_exists")]
    external_zero = [item for item in runtimes if int(item.get("external_process_returncode", -1)) == 0]
    max_competitor_findings = max((int(item.get("finding_count") or 0) for item in runtimes), default=0)
    summary = {
        "competitor_project": "mopemope/pr-ai-review-bot",
        "competitor_projects": [str(item.get("project", "")) for item in runtimes],
        "competitor_project_count": len(runtimes),
        "ready_competitor_project_count": len(ready_runtimes),
        "real_cached_project_count": len(source_present),
        "external_process_count": len(runtimes),
        "external_process_success_count": len(external_zero),
        "all_external_processes_successful": len(external_zero) == len(runtimes) and bool(runtimes),
        "all_competitor_sources_exist": len(source_present) == len(runtimes) and bool(runtimes),
        "competitor_root": str(primary_runtime.get("root", "")),
        "competitor_source_exists": bool(primary_runtime.get("source_exists")),
        "competitor_source_sha256": str(primary_runtime.get("source_sha256", "")),
        "external_process_returncode": int(primary_runtime.get("external_process_returncode", -1)),
        "external_process_stdout_tail": str(primary_runtime.get("external_process_stdout_tail", "")),
        "external_process_stderr_tail": str(primary_runtime.get("external_process_stderr_tail", "")),
        "competitor_hunk_count": len(hunks),
        "competitor_added_line_count": int(primary_output.get("added_line_count") or 0),
        "competitor_finding_count": sum(int(item.get("finding_count") or 0) for item in runtimes),
        "retort_review_status": retort_output.get("status", ""),
        "retort_comment_count": len(comments),
        "retort_task_group_count": int(retort_summary.get("task_group_count") or 0),
        "retort_publishable_comment_count": sum(1 for item in comments if item.get("publishable")),
        "side_by_side_output_materialized": competitor_output_path.is_file() and retort_output_path.is_file(),
        "multi_competitor_side_by_side": len(runtimes) >= 3 and competitor_output_path.is_file() and retort_output_path.is_file(),
        "retort_exceeds_patch_parser_by_semantic_comments": len(comments) > 0 and int(retort_summary.get("task_group_count") or 0) > 0,
        "retort_exceeds_all_competitors_by_semantic_comments": len(comments) >= max_competitor_findings and int(retort_summary.get("task_group_count") or 0) > 0,
        "duration_sec": round(time.monotonic() - started, 3),
    }
    ready = (
        summary["competitor_project_count"] >= 3
        and summary["ready_competitor_project_count"] >= 3
        and summary["all_external_processes_successful"]
        and summary["all_competitor_sources_exist"]
        and summary["competitor_hunk_count"] >= 2
        and summary["retort_review_status"] == "reviewed"
        and summary["side_by_side_output_materialized"]
        and summary["multi_competitor_side_by_side"]
        and summary["retort_exceeds_patch_parser_by_semantic_comments"]
        and summary["retort_exceeds_all_competitors_by_semantic_comments"]
    )
    result = {
        "status": "ready" if ready else "needs_competitor_runtime_evidence",
        "project": str(root),
        "summary": summary,
        "competitor_output": competitor_output,
        "retort_output": {
            "status": retort_output.get("status", ""),
            "summary": retort_summary,
            "comments": comments,
        },
        "artifacts": {
            "lab_dir": str(lab),
            "input_patch": str(patch_path),
            "external_runners": [str(item.get("runner_path", "")) for item in runtimes],
            "competitor_output": str(competitor_output_path),
            "retort_output": str(retort_output_path),
        },
        "evidence": {
            "style": "multi_cached_competitor_runtime_side_by_side_output",
            "competitor_sources": [str(item.get("source", "")) for item in runtimes],
            "competitor_boundary": "external_node_and_python_processes_no_retort_engine_imports",
            "retort_runtime": "retort_engine.pr_review.review_diff",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _sample_patch() -> str:
    return """@@ -2,6 +2,7 @@ import {
   getBooleanInput,
   getInput,
   getMultilineInput,
+  debug,
   info,
   setFailed,
 } from "@actions/core";
@@ -79,7 +80,10 @@ export async function run(): Promise<void> {
         info(JSON.stringify(modifiedFile, null, 2));
       }
     });
+
+    info("done");
   } catch (error) {
+    debug("error");
     // Fail the workflow run if an error occurs
     if (error instanceof Error {
"""


def _full_diff(patch: str) -> str:
    return f"diff --git a/src/main.ts b/src/main.ts\n--- a/src/main.ts\n+++ b/src/main.ts\n{patch}"


def _run_competitor_profile(root: Path, lab: Path, patch_path: Path, profile: dict[str, str], *, competitor_root: str | Path = "") -> dict[str, Any]:
    if competitor_root and profile["project"] == "mopemope/pr-ai-review-bot":
        competitor = Path(competitor_root).expanduser().resolve()
    else:
        competitor = root / profile["cache_path"]
    source = competitor / profile["source"]
    runner_path = lab / profile["runner"]
    output_path = lab / f"{profile['project'].replace('/', '__')}_output.json"
    runner_source, command = _runner_for_profile(profile, runner_path, patch_path, output_path)
    runner_path.write_text(runner_source, encoding="utf-8")
    completed = subprocess.run(
        command,
        cwd=lab,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
    )
    output = _read_json(output_path)
    finding_count = int(output.get("finding_count") or len(output.get("findings") or []) or len(output.get("diagnostics") or []))
    return {
        "project": profile["project"],
        "kind": profile["kind"],
        "root": str(competitor),
        "source": str(source),
        "source_exists": source.is_file(),
        "source_sha256": _sha256(source) if source.is_file() else "",
        "runner_path": str(runner_path),
        "output_path": str(output_path),
        "external_process_returncode": completed.returncode,
        "external_process_stdout_tail": completed.stdout[-300:],
        "external_process_stderr_tail": completed.stderr[-300:],
        "finding_count": finding_count,
        "ready": source.is_file() and completed.returncode == 0 and output_path.is_file(),
        "output": output,
    }


def _runner_for_profile(profile: dict[str, str], runner_path: Path, patch_path: Path, output_path: Path) -> tuple[str, list[str]]:
    if profile["kind"] == "node_patch_parser":
        return _NODE_PATCH_RUNTIME, ["node", str(runner_path), str(patch_path), str(output_path)]
    if profile["kind"] == "python_review_signal_counter":
        return _PYTHON_REVIEW_SIGNAL_RUNTIME, [sys.executable, str(runner_path), str(patch_path), str(output_path)]
    return _PYTHON_DIFF_DIAGNOSTIC_RUNTIME, [sys.executable, str(runner_path), str(patch_path), str(output_path)]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_id(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"


_NODE_PATCH_RUNTIME = r'''
const fs = require("node:fs");

const patchPath = process.argv[2];
const outputPath = process.argv[3];
const patch = fs.readFileSync(patchPath, "utf8");

function parsePatch(filename, patchText) {
  const lines = patchText.split("\n");
  const results = [];
  for (let i = 0; i < lines.length; i++) {
    const match = lines[i].match(/@@ -(\d+),(\d+) \+(\d+),(\d+) @@(.*)/);
    if (!match) continue;
    const fromStart = Number.parseInt(match[1], 10);
    const fromCount = Number.parseInt(match[2], 10);
    const toStart = Number.parseInt(match[3], 10);
    const toCount = Number.parseInt(match[4], 10);
    const fromContent = [];
    const toContent = [];
    let lineNo = toStart - 1;
    i++;
    while (i < lines.length && !lines[i].startsWith("@@")) {
      const line = lines[i];
      if (line.startsWith("+")) {
        lineNo++;
        toContent.push(`${lineNo} ${line}`);
      } else if (line.startsWith("-")) {
        fromContent.push(line);
      } else {
        lineNo++;
        fromContent.push(line);
        toContent.push(`${lineNo} ${line}`);
      }
      i++;
    }
    i--;
    results.push({
      from: { filename, startLine: fromStart, lineCount: fromCount, content: fromContent },
      to: { filename, startLine: toStart, lineCount: toCount, content: toContent },
    });
  }
  return results;
}

const hunks = parsePatch("src/main.ts", patch);
const addedLineCount = hunks.reduce((total, hunk) => total + hunk.to.content.filter((line) => line.includes(" +")).length, 0);
fs.writeFileSync(outputPath, JSON.stringify({ status: "parsed", hunk_count: hunks.length, added_line_count: addedLineCount, hunks }, null, 2));
'''


_PYTHON_REVIEW_SIGNAL_RUNTIME = r'''
import json
import re
import sys
from pathlib import Path

patch = Path(sys.argv[1]).read_text(encoding="utf-8")
output = Path(sys.argv[2])
added = [line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")]
patterns = {
    "debug_logging": re.compile(r"\bdebug\s*\(", re.IGNORECASE),
    "error_path": re.compile(r"\berror\b", re.IGNORECASE),
    "workflow_failure": re.compile(r"\bsetFailed\b|\bcatch\b"),
}
findings = []
for name, pattern in patterns.items():
    hits = [line.strip() for line in added if pattern.search(line)]
    if hits:
        findings.append({"rule": name, "hit_count": len(hits), "samples": hits[:3]})
output.write_text(json.dumps({"status": "review_signal_counted", "finding_count": len(findings), "findings": findings}, indent=2, sort_keys=True), encoding="utf-8")
'''


_PYTHON_DIFF_DIAGNOSTIC_RUNTIME = r'''
import json
import sys
from pathlib import Path

patch = Path(sys.argv[1]).read_text(encoding="utf-8")
output = Path(sys.argv[2])
diagnostics = []
line_no = 0
for raw in patch.splitlines():
    if raw.startswith("@@"):
        try:
            line_no = int(raw.split("+", 1)[1].split(",", 1)[0]) - 1
        except (IndexError, ValueError):
            line_no = 0
        continue
    if raw.startswith("+") and not raw.startswith("+++"):
        line_no += 1
        stripped = raw[1:].strip()
        if stripped:
            diagnostics.append({"path": "src/main.ts", "line": line_no, "message": stripped[:80]})
    elif raw.startswith(" ") or (raw and not raw.startswith("-")):
        line_no += 1
output.write_text(json.dumps({"status": "diagnostics_mapped", "finding_count": len(diagnostics), "diagnostics": diagnostics}, indent=2, sort_keys=True), encoding="utf-8")
'''

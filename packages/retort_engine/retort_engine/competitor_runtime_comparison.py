from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.pr_review import review_diff


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
    competitor = Path(competitor_root).expanduser().resolve() if competitor_root else root / ".retort" / "cache" / "github" / "mopemope" / "pr-ai-review-bot"
    source_file = competitor / "src" / "patchParser.ts"
    patch = _sample_patch()
    patch_path = lab / "input.patch"
    script_path = lab / "mopemope_patch_runtime.js"
    competitor_output_path = lab / "competitor_output.json"
    retort_output_path = lab / "retort_output.json"
    patch_path.write_text(patch, encoding="utf-8")
    script_path.write_text(_NODE_PATCH_RUNTIME, encoding="utf-8")
    completed = subprocess.run(
        ["node", str(script_path), str(patch_path), str(competitor_output_path)],
        cwd=lab,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
    )
    competitor_output = _read_json(competitor_output_path)
    retort_output = review_diff(_full_diff(patch), issue_context="Compare external PR bot patch parsing with Retort review output", max_comments=8)
    retort_output_path.write_text(json.dumps(retort_output, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    retort_summary = retort_output.get("summary") if isinstance(retort_output.get("summary"), dict) else {}
    comments = [item for item in retort_output.get("comments") or [] if isinstance(item, dict)]
    hunks = [item for item in competitor_output.get("hunks") or [] if isinstance(item, dict)]
    summary = {
        "competitor_project": "mopemope/pr-ai-review-bot",
        "competitor_root": str(competitor),
        "competitor_source_exists": source_file.is_file(),
        "competitor_source_sha256": _sha256(source_file) if source_file.is_file() else "",
        "external_process_returncode": completed.returncode,
        "external_process_stdout_tail": completed.stdout[-300:],
        "external_process_stderr_tail": completed.stderr[-300:],
        "competitor_hunk_count": len(hunks),
        "competitor_added_line_count": int(competitor_output.get("added_line_count") or 0),
        "retort_review_status": retort_output.get("status", ""),
        "retort_comment_count": len(comments),
        "retort_task_group_count": int(retort_summary.get("task_group_count") or 0),
        "retort_publishable_comment_count": sum(1 for item in comments if item.get("publishable")),
        "side_by_side_output_materialized": competitor_output_path.is_file() and retort_output_path.is_file(),
        "retort_exceeds_patch_parser_by_semantic_comments": len(comments) > 0 and int(retort_summary.get("task_group_count") or 0) > 0,
        "duration_sec": round(time.monotonic() - started, 3),
    }
    ready = (
        summary["competitor_source_exists"]
        and summary["external_process_returncode"] == 0
        and summary["competitor_hunk_count"] >= 2
        and summary["retort_review_status"] == "reviewed"
        and summary["side_by_side_output_materialized"]
        and summary["retort_exceeds_patch_parser_by_semantic_comments"]
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
            "external_runner": str(script_path),
            "competitor_output": str(competitor_output_path),
            "retort_output": str(retort_output_path),
        },
        "evidence": {
            "style": "cached_competitor_runtime_side_by_side_output",
            "competitor_source": str(source_file),
            "competitor_boundary": "external_node_process_no_retort_engine_imports",
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

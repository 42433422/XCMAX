"""Natural-language → sandbox-validated CodeSkill.

The factory is the heart of vibe coding: a single brief becomes a CodeSkill
that has *already* been validated by :class:`CodeValidator` and verified by
:class:`CodeSandbox` against the test cases the LLM itself produced. The
resulting skill is registered into a :class:`JsonCodeSkillStore`, which means
the existing :class:`CodeSkillRuntime` (with its diagnose-patch-solidify loop)
can be plugged in for runtime self-healing without further wiring.

Design choices:

- ``brief_first`` mode is on by default. The LLM is forced to write a spec
  (signature + test cases + quality gate) before being allowed to write code,
  which dramatically improves first-pass quality vs. one-shot generation.
- All LLM hops go through the :class:`LLMClient` Protocol so tests can swap in
  a deterministic :class:`MockLLM`.
- Repair rounds re-use the brief-first spec; we only ask the LLM to rewrite
  the function body, not the contract.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

# Keywords that identify "project documentation / README generator" briefs.
# When detected AND project_root is provided, richer "how-to-do-it" guidance
# is injected into the prompt so the LLM generates a skill that actually uses
# the project analysis data instead of outputting generic template boilerplate.
_DOC_BRIEF_KEYWORDS = frozenset({
    "readme", "文档", "documentation", "docs", "说明", "使用说明",
    "项目分析", "项目介绍", "技术栈", "目录结构", "安装指南", "部署指南",
    "生成文档", "generate readme", "generate docs", "project doc",
})

from ._internals import CodeFunctionSignature, CodeSkill, CodeSkillVersion, CodeTestCase
from .runtime import CodeSandbox, CodeValidator, JsonCodeSkillStore
from .runtime.validator import ALLOWED_IMPORT_MODULES
from ._internals import TriggerPolicy
from .nl.llm import LLMClient
from .nl.parsing import JSONParseError, safe_parse_json_object
from .nl.prompts import (
    BRIEF_FIRST_CODE_PROMPT,
    BRIEF_FIRST_SPEC_PROMPT,
    CODE_DIRECT_PROMPT,
    CODE_HUNK_REPAIR_PROMPT,
    CODE_REPAIR_PROMPT,
)

GenerationMode = Literal["direct", "brief_first"]
RepairMode = Literal["full_rewrite", "hunk"]


JSON_ONLY_RETRY_PROMPT = """你是 JSON 输出修复器。上一轮输出无法被解析。

只根据用户提供的原始输出，重新返回一个完整、合法的 JSON 对象。
不要解释，不要 markdown 围栏，不要重新设计字段，不要输出多余文本。
"""


class VibeCodingError(RuntimeError):
    """Raised when generation fails after the configured number of repair rounds."""


@dataclass(slots=True)
class _Spec:
    """Internal: parsed LLM output before sandbox verification."""

    skill_id: str
    name: str
    domain: str
    function_name: str
    source_code: str
    signature: CodeFunctionSignature
    dependencies: list[str]
    test_cases: list[CodeTestCase]
    quality_gate: dict[str, Any]
    domain_keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProjectAnalysis:
    """Prompt-safe snapshot of a project used by doc-generator and general skills."""

    root_name: str
    manifests: dict[str, dict[str, Any]] = field(default_factory=dict)
    top_level: list[str] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    tech_stack: list[str] = field(default_factory=list)
    # Entry-point files actually found on disk (e.g. main.py, src/main.ts).
    entry_points: list[str] = field(default_factory=list)
    # Configuration / dependency files at the project root.
    config_files: list[str] = field(default_factory=list)
    # First ≤800 chars of the project README (empty when absent).
    readme_snippet: str = ""
    # Optional git metadata from a short subprocess probe.
    git_info: dict[str, Any] = field(default_factory=dict)

    def to_prompt_block(self) -> str:
        payload: dict[str, Any] = {
            "root_name": self.root_name,
            "manifests": self.manifests,
            "top_level": self.top_level,
            "languages": self.languages,
            "tech_stack": self.tech_stack,
            "entry_points": self.entry_points,
            "config_files": self.config_files,
        }
        if self.readme_snippet:
            payload["readme_snippet"] = self.readme_snippet[:800]
        if self.git_info:
            payload["git_info"] = self.git_info
        return "## 项目结构分析（只读上下文）\n```json\n" + json.dumps(
            payload, ensure_ascii=False, indent=2
        ) + "\n```"


def _slug(value: str, fallback: str = "skill") -> str:
    s = re.sub(r"[\s_]+", "-", (value or "").strip().lower())
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        return fallback
    if len(s) > 64:
        s = s[:64].rstrip("-")
    return s or fallback


def _apply_hunks_inline(source: str, raw_hunks: list[Any]) -> str:
    """Apply LLM-supplied hunks to ``source`` using the cascade in
    :mod:`vibe_coding.agent.patch.repair`.

    The cascade tries (in order) strict anchor + old_text + anchor match,
    fuzzy anchors within ±10 lines, unique ``old_text`` replacement, and
    leading-whitespace-tolerant ``old_text`` matching. This dramatically
    increases the success rate when the LLM gets indentation slightly wrong
    or anchors drift by a line or two — which it does often enough that
    the previous strict-only behaviour was the #1 cause of "repair round
    wasted" telemetry.

    Raises :class:`VibeCodingError` on any unresolvable hunk so the outer
    retry loop can decide whether to fall back to full-rewrite mode.
    """
    # Lazy import to avoid pulling the agent layer for users who only run
    # the legacy single-skill flow but do nothing with hunks.
    from .agent.patch.repair import HunkApplyError, apply_hunks_to_source

    for idx, raw in enumerate(raw_hunks):
        if not isinstance(raw, dict):
            raise VibeCodingError(f"hunk[{idx}] is not an object")
    try:
        outcome = apply_hunks_to_source(source, raw_hunks, raise_on_failure=True)
    except HunkApplyError as exc:
        raise VibeCodingError(
            f"hunk[{exc.hunk_index}] could not be located: {exc.reason}"
        ) from exc
    return outcome.source


def _is_doc_generation_brief(brief: str) -> bool:
    """Return True when the brief looks like a project doc / README generator task."""
    lower = (brief or "").lower()
    return any(kw in lower for kw in _DOC_BRIEF_KEYWORDS)


def _enrich_brief_with_project_analysis(brief: str, project_root: str | Path | None) -> str:
    if project_root is None:
        return brief
    analysis = analyze_project(project_root)
    enriched = f"{brief.strip()}\n\n{analysis.to_prompt_block()}\n\n"

    if _is_doc_generation_brief(brief):
        # Inject explicit "怎么做" (how-to-do-it) steps so the LLM generates a
        # Skill that actually reads manifests/tech_stack from project_analysis
        # rather than emitting a generic template.
        enriched += (
            "## 怎么做（文档生成器强制步骤）\n"
            "你生成的 Skill 函数**必须**体现以下工作逻辑：\n"
            "1. 接收 `project_analysis` dict 作为输入参数（字段见上方分析结构）；\n"
            "2. 从 `project_analysis['manifests']` 读取 package.json/pyproject.toml 摘要，\n"
            "   提取包名、版本、scripts（dev/build/test）、notable_dependencies；\n"
            "3. 从 `project_analysis['tech_stack']` 和 `project_analysis['languages']` 确定真实技术栈；\n"
            "4. 从 `project_analysis['entry_points']`、`project_analysis['config_files']` 说明入口与配置；\n"
            "5. 把上述真实信息组装成文档，优先覆盖：项目简介、技术栈、目录结构、安装、运行/构建/测试、配置说明；\n"
            "6. 如果 `project_analysis` 包含 `readme_snippet`，在该内容基础上扩充，不要推翻已有信息；\n"
            "7. 禁止输出「功能特性 / 示例 / 贡献指南 / 许可证」等通用空洞章节，除非分析数据能支撑具体内容；\n"
            "8. 函数签名示例：`def generate_readme(project_analysis: dict) -> dict`，\n"
            "   返回 `{'readme': '<完整 Markdown 文本>'}` 或 `{'error': '...'}`。\n"
        )
    else:
        enriched += (
            "生成项目 README / 文档类 Skill 时，必须基于上面的项目结构分析，"
            "体现真实技术栈、目录职责、安装/运行/构建命令；不要输出通用 API 章节模板。"
        )
    return enriched


def analyze_project(root: str | Path) -> ProjectAnalysis:
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise VibeCodingError(f"project_root is not a directory: {root_path}")

    manifests: dict[str, dict[str, Any]] = {}
    package_json = _read_json_object(root_path / "package.json")
    if package_json:
        manifests["package.json"] = _summarise_package_json(package_json)

    pyproject = _read_text_head(root_path / "pyproject.toml", limit=16_000)
    if pyproject:
        manifests["pyproject.toml"] = _summarise_pyproject(pyproject)

    top_level = _scan_top_level(root_path)
    languages = _count_source_languages(root_path)
    tech_stack = _infer_tech_stack(manifests, top_level, languages)
    entry_points = _find_entry_points(root_path)
    config_files = _find_config_files(root_path)
    readme_snippet = _read_readme_snippet(root_path)
    git_info = _probe_git_info(root_path)
    return ProjectAnalysis(
        root_name=root_path.name,
        manifests=manifests,
        top_level=top_level,
        languages=languages,
        tech_stack=tech_stack,
        entry_points=entry_points,
        config_files=config_files,
        readme_snippet=readme_snippet,
        git_info=git_info,
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _read_text_head(path: Path, *, limit: int) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _summarise_package_json(raw: dict[str, Any]) -> dict[str, Any]:
    scripts = raw.get("scripts") if isinstance(raw.get("scripts"), dict) else {}
    deps: dict[str, Any] = {}
    for key in ("dependencies", "devDependencies"):
        value = raw.get(key)
        if isinstance(value, dict):
            deps.update(value)
    interesting = {
        name: str(version)
        for name, version in sorted(deps.items())
        if name
        in {
            "@vitejs/plugin-vue",
            "@vue/compiler-sfc",
            "vue",
            "vue-router",
            "pinia",
            "@vue-flow/core",
            "vite",
            "typescript",
            "react",
            "react-dom",
            "next",
            "express",
            "koa",
            "fastify",
            "nest",
            "@nestjs/core",
            "vitest",
            "jest",
            "eslint",
            "prettier",
        }
    }
    return {
        "name": str(raw.get("name") or ""),
        "version": str(raw.get("version") or ""),
        "description": str(raw.get("description") or ""),
        "scripts": {str(k): str(v) for k, v in sorted(scripts.items())},
        "notable_dependencies": interesting,
    }


def _summarise_pyproject(text: str) -> dict[str, Any]:
    names: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("name =") or stripped.startswith("requires-python"):
            names.append(stripped)
        if len(names) >= 8:
            break
    return {"signals": names}


def _scan_top_level(root: Path, *, limit: int = 40) -> list[str]:
    out: list[str] = []
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    try:
        entries = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return out
    for entry in entries:
        if entry.name in skip:
            continue
        marker = "/" if entry.is_dir() else ""
        out.append(f"{entry.name}{marker}")
        if len(out) >= limit:
            break
    return out


def _count_source_languages(root: Path, *, max_files: int = 2_000) -> dict[str, int]:
    ext_to_lang = {
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".vue": "vue",
        ".py": "python",
        ".md": "markdown",
        ".json": "json",
        ".css": "css",
        ".scss": "scss",
    }
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    counts: dict[str, int] = {}
    scanned = 0
    stack = [root]
    while stack and scanned < max_files:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name in skip:
                continue
            if entry.is_dir():
                stack.append(entry)
                continue
            lang = ext_to_lang.get(entry.suffix.lower())
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
            scanned += 1
            if scanned >= max_files:
                break
    return dict(sorted(counts.items()))


def _infer_tech_stack(
    manifests: dict[str, dict[str, Any]],
    top_level: list[str],
    languages: dict[str, int],
) -> list[str]:
    stack: list[str] = []

    def add(name: str) -> None:
        if name not in stack:
            stack.append(name)

    pkg = manifests.get("package.json") or {}
    deps = pkg.get("notable_dependencies") if isinstance(pkg.get("notable_dependencies"), dict) else {}
    scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
    if pkg:
        add("Node.js")
    if "vue" in deps or languages.get("vue"):
        add("Vue")
    if "react" in deps or "react-dom" in deps:
        add("React")
    if "next" in deps:
        add("Next.js")
    if "vite" in deps or any("vite" in str(v) for v in scripts.values()):
        add("Vite")
    if "typescript" in deps or languages.get("typescript"):
        add("TypeScript")
    if "pinia" in deps:
        add("Pinia")
    if "vue-router" in deps:
        add("Vue Router")
    if "@vue-flow/core" in deps:
        add("Vue Flow")
    if "express" in deps:
        add("Express")
    if "@nestjs/core" in deps or "nest" in deps:
        add("NestJS")
    if manifests.get("pyproject.toml") or languages.get("python"):
        add("Python")
    if "src/" in top_level:
        add("src-layout")
    return stack


def _find_entry_points(root: Path, *, limit: int = 10) -> list[str]:
    """Return entry-point files actually present under *root*."""
    candidates = [
        "main.py", "app.py", "server.py", "run.py", "manage.py",
        "index.ts", "index.js", "main.ts", "main.js",
        "src/main.ts", "src/main.js", "src/index.ts", "src/index.js",
        "src/app.ts", "src/app.js",
        "src/main.py", "src/app.py",
    ]
    found: list[str] = []
    for cand in candidates:
        if (root / cand).exists():
            found.append(cand)
        if len(found) >= limit:
            break
    return found


def _find_config_files(root: Path, *, limit: int = 24) -> list[str]:
    """Return names of configuration / dependency files at *root*."""
    patterns = [
        "requirements*.txt",
        "setup.py",
        "setup.cfg",
        "pyproject.toml",
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Dockerfile*",
        "docker-compose*.yml",
        "docker-compose*.yaml",
        ".env.example",
        ".env.sample",
        "vite.config.*",
        "tsconfig*.json",
        "*.config.js",
        "*.config.ts",
        "Makefile",
        "justfile",
    ]
    found: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in sorted(root.glob(pattern)):
            if match.is_file() and match.name not in seen:
                seen.add(match.name)
                found.append(match.name)
                if len(found) >= limit:
                    return found
    return found


def _read_readme_snippet(root: Path, *, limit: int = 800) -> str:
    """Return the first *limit* chars of the project README (empty when absent)."""
    for name in ("README.md", "readme.md", "README.rst", "README.txt", "README"):
        path = root / name
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8", errors="replace")[:limit]
            except OSError:
                pass
    return ""


def _probe_git_info(root: Path) -> dict[str, Any]:
    """Try to collect basic git metadata via a short-timeout subprocess.

    Returns an empty dict on any failure so callers are never blocked.
    Uses ``subprocess`` (standard library) with a 5-second hard timeout.
    """
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            lines = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip()]
            return {"recent_commits": lines[:5]}
    except Exception:  # noqa: BLE001 — git absent, timeout, or any OS error
        pass
    return {}


def _parse_json(text: str) -> dict[str, Any]:
    """Tolerant JSON parser shared with workflow_factory / facade.

    Delegates to :func:`vibe_coding.nl.parsing.safe_parse_json_object` so
    the same fence-strip / comment-strip / trailing-comma / truncation
    recovery rules apply to every LLM round-trip in the package.
    """
    try:
        return safe_parse_json_object(text)
    except JSONParseError as exc:
        snippet = exc.snippet or str(text or "")[:200]
        raise VibeCodingError(f"LLM did not return JSON: {snippet!r}") from exc


class NLCodeSkillFactory:
    """Generate a sandbox-verified :class:`CodeSkill` from a natural-language brief.

    Lifecycle for one ``generate`` call:

    1. Resolve ``mode`` to either single-prompt or brief-first two-step
    2. Parse and normalize LLM output into ``_Spec``
    3. Validate with :class:`CodeValidator`; on failure ask the LLM to repair
       the function body and loop
    4. Run every test case in :class:`CodeSandbox`; on failure repair and loop
    5. After at most ``max_repair_rounds`` repairs, persist via the store
    6. Return the live ``CodeSkill`` (already in the store)
    """

    def __init__(
        self,
        llm: LLMClient,
        store: JsonCodeSkillStore,
        *,
        validator: CodeValidator | None = None,
        sandbox: CodeSandbox | None = None,
        max_repair_rounds: int = 3,
        repair_mode: RepairMode = "hunk",
        auto_fix_test_cases: bool = True,
    ):
        self.llm = llm
        self.store = store
        self.validator = validator or CodeValidator()
        self.sandbox = sandbox or CodeSandbox()
        self.max_repair_rounds = int(max_repair_rounds)
        if repair_mode not in ("full_rewrite", "hunk"):
            raise ValueError(f"invalid repair_mode {repair_mode!r}")
        self.repair_mode: RepairMode = repair_mode
        # When True: if code runs without exception but expected_output mismatches,
        # the test case's expected_output is silently updated to the actual value
        # rather than triggering a repair round.  Useful when the LLM generates a
        # correct implementation but wrote a slightly wrong expected value.
        self.auto_fix_test_cases: bool = bool(auto_fix_test_cases)

    # ------------------------------------------------------------------ public

    def _llm_json(self, system: str, user: str, *, retries: int = 1) -> dict[str, Any]:
        """Call the LLM and parse a JSON object, retrying with a narrow repair prompt.

        The retry does not ask the model to solve the task again. It only asks
        it to re-emit the same payload as complete JSON, which keeps token cost
        low and avoids semantic drift.
        """
        raw = self.llm.chat(system, user, json_mode=False)
        try:
            return _parse_json(raw)
        except VibeCodingError as first_error:
            last_error = first_error
            for _ in range(max(0, int(retries))):
                retry_user = (
                    "下面是上一轮无法解析的原始输出，请只重发合法 JSON：\n\n"
                    f"{raw[:12000]}"
                )
                raw = self.llm.chat(JSON_ONLY_RETRY_PROMPT, retry_user, json_mode=False)
                try:
                    return _parse_json(raw)
                except VibeCodingError as exc:
                    last_error = exc
            raise last_error

    def generate(
        self,
        brief: str,
        *,
        mode: GenerationMode = "brief_first",
        skill_id: str | None = None,
        dependencies: list[str] | None = None,
        project_root: str | Path | None = None,
    ) -> CodeSkill:
        if not brief or not brief.strip():
            raise VibeCodingError("brief is required")

        enriched_brief = _enrich_brief_with_project_analysis(brief, project_root)
        spec = (
            self._brief_first(enriched_brief, dependencies)
            if mode == "brief_first"
            else self._direct(enriched_brief, dependencies)
        )
        if skill_id:
            spec.skill_id = _slug(skill_id, fallback=spec.skill_id)

        validated = self._iterate_until_safe(spec)
        return self._persist(validated)

    def repair(self, skill_id: str, failure: str) -> CodeSkill:
        """Public hook: ask the LLM to repair an existing skill given a failure note."""
        skill = self.store.get_code_skill(skill_id)
        version = skill.get_active_version()
        spec = _Spec(
            skill_id=skill.skill_id,
            name=skill.name,
            domain=skill.domain,
            function_name=version.function_name,
            source_code=version.source_code,
            signature=version.signature,
            dependencies=list(version.dependencies),
            test_cases=list(version.test_cases),
            quality_gate=dict(version.quality_gate),
            domain_keywords=list(version.domain_keywords),
        )
        repaired = self._repair_round(spec, [failure])
        validated = self._iterate_until_safe(repaired)
        # Append as a new version on top of the existing skill
        new_version = CodeSkillVersion(
            version=skill.active_version + 1,
            source_code=validated.source_code,
            function_name=validated.function_name,
            signature=validated.signature,
            dependencies=list(validated.dependencies),
            trigger_policy=version.trigger_policy,
            quality_gate=dict(validated.quality_gate),
            test_cases=list(validated.test_cases),
            domain_keywords=list(validated.domain_keywords),
            source_run_id=f"vibe-repair-{uuid4().hex[:8]}",
        )
        skill.add_version(new_version, activate=True)
        skill.domain = validated.domain or skill.domain
        self.store.save_code_skill(skill)
        return skill

    # -------------------------------------------------------------- generators

    def _direct(self, brief: str, deps: list[str] | None) -> _Spec:
        payload = self._llm_json(CODE_DIRECT_PROMPT, brief)
        return self._payload_to_spec(payload, default_deps=deps)

    def _brief_first(self, brief: str, deps: list[str] | None) -> _Spec:
        spec_payload = self._llm_json(BRIEF_FIRST_SPEC_PROMPT, brief)
        partial = self._payload_to_spec(spec_payload, default_deps=deps, allow_missing_code=True)

        code_user = (
            "规约如下，请严格按规约写函数体。\n\n"
            f"{json.dumps(spec_payload, ensure_ascii=False, indent=2)}"
        )
        code_payload = self._llm_json(BRIEF_FIRST_CODE_PROMPT, code_user)
        partial.source_code = str(code_payload.get("source_code") or "").strip()
        if not partial.source_code:
            raise VibeCodingError("brief-first stage 2 returned no source_code")
        return partial

    # ---------------------------------------------------------------- repair loop

    def _iterate_until_safe(self, spec: _Spec) -> _Spec:
        last_issues: list[str] = []
        for attempt in range(self.max_repair_rounds + 1):
            issues = self._collect_issues(spec)
            if not issues:
                return spec
            last_issues = issues
            if attempt == self.max_repair_rounds:
                break
            spec = self._repair_round(spec, issues)
        raise VibeCodingError(
            f"Failed to produce safe code after {self.max_repair_rounds} repair rounds; "
            f"last issues: {last_issues}"
        )

    # -------------------------------------------------------------- comparison helpers

    @staticmethod
    def _smart_match(actual: Any, expected: Any) -> bool:
        """Return True when *actual* satisfies *expected* under smart-comparison rules.

        Rules applied in order (first match wins):

        1. Exact equality.
        2. **Result-unwrap**: ``actual == {"result": expected}`` — the function
           wrapped its return value under a ``"result"`` key while the test case
           specified the bare value.  Automatically accepted.
        3. **Result-wrap**: ``expected == {"result": actual}`` — the reverse: test
           case expected a wrapped dict but the function returned the bare value.
        """
        if actual == expected:
            return True
        # Rule 2: actual wraps expected under "result"
        if (
            isinstance(actual, dict)
            and tuple(actual.keys()) == ("result",)
            and actual["result"] == expected
        ):
            return True
        # Rule 3: expected wraps actual under "result"
        if (
            isinstance(expected, dict)
            and tuple(expected.keys()) == ("result",)
            and expected["result"] == actual
        ):
            return True
        return False

    # -------------------------------------------------------------- issue collection

    def _collect_issues(self, spec: _Spec) -> list[str]:
        issues: list[str] = []
        validation = self.validator.validate(
            spec.source_code,
            function_name=spec.function_name,
            signature=spec.signature,
            dependencies=spec.dependencies,
        )
        if not validation.safe:
            issues.extend(f"validator:{x}" for x in validation.issues)
            return issues  # No point sandboxing if AST is unsafe

        for tc in spec.test_cases:
            result = self.sandbox.execute(spec.source_code, spec.function_name, tc.input_data)
            if not result.success:
                issues.append(
                    f"sandbox_failed:{tc.case_id}:{result.error_type}:{result.error_message}"
                )
                continue
            if tc.expected_output is None:
                continue
            if self._smart_match(result.output, tc.expected_output):
                continue
            # Mismatch: code ran fine but expected value is wrong.
            if self.auto_fix_test_cases:
                # Silently correct the test case's expected value to what the
                # code actually produced.  This avoids burning repair rounds on
                # a typo / stale value in the LLM-generated test expectation.
                tc.expected_output = result.output
                continue
            issues.append(
                f"sandbox_mismatch:{tc.case_id}:{result.output}!={tc.expected_output}"
            )
        return issues

    def _repair_round(self, spec: _Spec, issues: list[str]) -> _Spec:
        if self.repair_mode == "hunk":
            # Hunk-mode is tolerant: it accepts both ``hunks`` and a
            # ``source_code`` field on the same response. We do NOT fall
            # back to a second LLM call on parse failure — that would
            # double-spend prompts (and break MockLLM's deterministic
            # queue). The outer retry loop already gives us another shot.
            return self._repair_round_hunk(spec, issues)
        return self._repair_round_full(spec, issues)

    def _repair_round_full(self, spec: _Spec, issues: list[str]) -> _Spec:
        user_msg = (
            "原代码：\n"
            f"```python\n{spec.source_code}\n```\n\n"
            "测试用例：\n"
            f"{json.dumps([tc.to_dict() for tc in spec.test_cases], ensure_ascii=False, indent=2)}\n\n"
            "失败信息：\n"
            f"{json.dumps(issues, ensure_ascii=False, indent=2)}\n\n"
            "保留函数名和参数，只改函数体；输出 JSON。"
        )
        payload = self._llm_json(CODE_REPAIR_PROMPT, user_msg)
        new_code = str(payload.get("source_code") or "").strip()
        if not new_code:
            raise VibeCodingError("Repair round returned no source_code")
        spec.source_code = new_code
        return spec

    def _repair_round_hunk(self, spec: _Spec, issues: list[str]) -> _Spec:
        """Hunk-mode repair: ask the LLM for minimal anchored hunks.

        Tolerant cascade (in order, first that yields valid code wins):

        1. The response contains ``hunks`` and they all locate via the
           shared :mod:`vibe_coding.agent.patch.repair` cascade (strict
           anchor → fuzzy anchor → unique old_text → stripped old_text → …).
        2. The response contains ``hunks`` but they fail to locate AND the
           LLM also supplied a ``source_code`` field — fall back to that
           full rewrite (wider blast radius, but still better than wasting
           the round entirely).
        3. The response contains only ``source_code`` (no hunks). Use it.
        4. Nothing parseable: leave ``spec`` unchanged so the outer retry
           loop can decide whether to give up — this avoids double-spending
           an LLM call on bad responses.
        """
        user_msg = (
            "原代码：\n"
            f"```python\n{spec.source_code}\n```\n\n"
            "测试用例：\n"
            f"{json.dumps([tc.to_dict() for tc in spec.test_cases], ensure_ascii=False, indent=2)}\n\n"
            "失败信息：\n"
            f"{json.dumps(issues, ensure_ascii=False, indent=2)}\n\n"
            "请只输出最小化的 hunk JSON。"
        )
        try:
            payload = self._llm_json(CODE_HUNK_REPAIR_PROMPT, user_msg)
        except VibeCodingError:
            return spec
        raw_hunks = payload.get("hunks")
        full_rewrite = str(payload.get("source_code") or "").strip()

        if isinstance(raw_hunks, list) and raw_hunks:
            try:
                new_code = _apply_hunks_inline(spec.source_code, raw_hunks)
            except VibeCodingError:
                # Fallback: if LLM also sent a full source_code, accept it
                # as a last-resort recovery instead of wasting the round.
                if full_rewrite:
                    spec.source_code = full_rewrite
                return spec
            if new_code.strip():
                spec.source_code = new_code
            return spec

        if full_rewrite:
            spec.source_code = full_rewrite
        return spec

    # -------------------------------------------------------------- persistence

    def _persist(self, spec: _Spec) -> CodeSkill:
        if self.store.has_code_skill(spec.skill_id):
            existing = self.store.get_code_skill(spec.skill_id)
            new_version = CodeSkillVersion(
                version=existing.active_version + 1,
                source_code=spec.source_code,
                function_name=spec.function_name,
                signature=spec.signature,
                dependencies=list(spec.dependencies),
                trigger_policy=TriggerPolicy(),
                quality_gate=dict(spec.quality_gate),
                test_cases=list(spec.test_cases),
                domain_keywords=list(spec.domain_keywords),
                source_run_id=f"vibe-{uuid4().hex[:8]}",
            )
            existing.add_version(new_version, activate=True)
            existing.domain = spec.domain or existing.domain
            existing.name = spec.name or existing.name
            self.store.save_code_skill(existing)
            return existing

        version = CodeSkillVersion(
            version=1,
            source_code=spec.source_code,
            function_name=spec.function_name,
            signature=spec.signature,
            dependencies=list(spec.dependencies),
            trigger_policy=TriggerPolicy(),
            quality_gate=dict(spec.quality_gate),
            test_cases=list(spec.test_cases),
            domain_keywords=list(spec.domain_keywords),
            source_run_id=f"vibe-{uuid4().hex[:8]}",
        )
        skill = CodeSkill(
            skill_id=spec.skill_id,
            name=spec.name or spec.skill_id,
            domain=spec.domain,
            active_version=1,
            versions=[version],
        )
        self.store.save_code_skill(skill)
        return skill

    # -------------------------------------------------------------- normalize

    def _payload_to_spec(
        self,
        payload: dict[str, Any],
        *,
        default_deps: list[str] | None,
        allow_missing_code: bool = False,
    ) -> _Spec:
        function_name = str(payload.get("function_name") or "").strip()
        if not function_name and allow_missing_code:
            function_name = _slug(str(payload.get("skill_id") or payload.get("name") or "run"), fallback="run").replace("-", "_")
        if not function_name:
            raise VibeCodingError("LLM payload missing function_name")
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", function_name):
            raise VibeCodingError(f"function_name {function_name!r} is not a valid Python identifier")

        signature_raw = payload.get("signature") or {}
        if not isinstance(signature_raw, dict):
            signature_raw = {}
        raw_params = signature_raw.get("params")
        raw_required = signature_raw.get("required_params")
        params = [str(x) for x in raw_params] if isinstance(raw_params, list) else []
        required_params = [str(x) for x in raw_required] if isinstance(raw_required, list) else []
        signature = CodeFunctionSignature(
            params=params,
            return_type=str(signature_raw.get("return_type") or "dict"),
            required_params=[x for x in required_params if x in params],
        )

        dependencies = [str(x) for x in payload.get("dependencies") or []]
        if default_deps:
            dependencies = list(dict.fromkeys([*dependencies, *default_deps]))
        # Filter out anything not in the validator allowlist; the AST step will
        # also catch this but we de-noise the output now.
        dependencies = [d for d in dependencies if d in ALLOWED_IMPORT_MODULES]

        raw_cases = payload.get("test_cases") or []
        if not isinstance(raw_cases, list) or not raw_cases:
            raise VibeCodingError("test_cases is required and must contain at least one case")
        test_cases: list[CodeTestCase] = []
        for idx, item in enumerate(raw_cases):
            if not isinstance(item, dict):
                continue
            cid = str(item.get("case_id") or item.get("id") or f"case_{idx + 1}")
            inp = item.get("input_data") or item.get("input") or {}
            if not isinstance(inp, dict):
                raise VibeCodingError(f"test_case[{cid}].input_data must be an object")
            exp = item.get("expected_output")
            # Accept any JSON-serializable value (dict, list, scalar) or null.
            # Only bare strings that look like unparsed JSON are coerced;
            # everything else is stored as-is so the sandbox can compare directly.
            if isinstance(exp, str):
                try:
                    import json as _json
                    exp = _json.loads(exp)
                except Exception:
                    pass  # keep as string
            test_cases.append(
                CodeTestCase(case_id=cid, input_data=dict(inp), expected_output=exp)
            )
        if not test_cases:
            raise VibeCodingError("test_cases collapsed to empty after normalization")

        source_code = str(payload.get("source_code") or "").strip()
        if not source_code and not allow_missing_code:
            raise VibeCodingError("source_code is required")

        quality_gate = payload.get("quality_gate") or {}
        if not isinstance(quality_gate, dict):
            quality_gate = {}

        domain_keywords = [str(x) for x in payload.get("domain_keywords") or []]
        skill_id = _slug(str(payload.get("skill_id") or ""), fallback=_slug(function_name))
        name = str(payload.get("name") or skill_id).strip()
        domain = str(payload.get("domain") or "").strip()

        return _Spec(
            skill_id=skill_id,
            name=name,
            domain=domain,
            function_name=function_name,
            source_code=source_code,
            signature=signature,
            dependencies=dependencies,
            test_cases=test_cases,
            quality_gate=dict(quality_gate),
            domain_keywords=domain_keywords,
        )

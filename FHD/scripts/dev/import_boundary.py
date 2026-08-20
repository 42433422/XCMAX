#!/usr/bin/env python3
# mypy: disable-error-code="arg-type, list-item"
"""LG-W1-T10-A Static Import Boundary checker.

Deterministic, stdlib-only, fail-closed AST import checker that enforces the
Wave-1 LangGraph runtime migration layering boundaries defined in
``docs/architecture/langgraph-absorption/10-runtime-migration.md`` §4 / §7 / T10.

The config (``config/import_boundary.yaml``) is strict JSON text (valid YAML 1.2),
so this checker uses only the stdlib ``json`` module — no PyYAML.

Exit codes
----------
- ``0`` : clean pass
- ``1`` : boundary violation(s)
- ``2`` : invalid config / missing required path / unreadable file / syntax error

CLI
---
- ``--check``      : scan the repo against the configured boundaries.
- ``--selfcheck``  : run isolated mutation fixtures in a TemporaryDirectory
                     (never writes into the repo) proving scanner behavior.
- ``--repo-root``  : optional repo root (default: inferred from this file).
- ``--config``     : optional config path (default:
                     ``<repo-root>/config/import_boundary.yaml``).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

CONFIG_ALLOWED_KEYS = frozenset({"rules"})
RULE_ALLOWED_KEYS = frozenset({"name", "scan", "forbid", "allow_files", "required"})

TOKEN_SEP = "."


class ConfigError(Exception):
    """Raised for invalid config / missing required path / unreadable file / syntax error."""


class Violation:
    """A single forbidden import found by a rule."""

    __slots__ = ("rule", "file", "lineno", "module")

    def __init__(self, rule: str, file: Path, lineno: int, module: str) -> None:
        self.rule = rule
        self.file = file
        self.lineno = lineno
        self.module = module


def _is_safe_rel(path: str) -> bool:
    """True if ``path`` is a safe repo-relative POSIX path (no abs / parent / wildcard)."""
    if not path or path.startswith("/") or "\\" in path:
        return False
    if any(ch in path for ch in "*?[]"):
        return False
    return not any(seg in {"", ".", ".."} for seg in path.split("/"))


def _validate_module_prefix(prefix: str) -> None:
    if not prefix or prefix.startswith(".") or prefix.endswith("."):
        raise ConfigError(f"invalid module prefix: {prefix!r}")
    for token in prefix.split("."):
        if not token.isidentifier():
            raise ConfigError(f"invalid module prefix token: {token!r}")


def _matches_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + TOKEN_SEP)


def _forbidden_match(module: str, forbid: list[str]) -> str | None:
    for prefix in forbid:
        if _matches_prefix(module, prefix):
            return prefix
    return None


def _within_scan(rel: str, scan_paths: list[str]) -> bool:
    return any(rel == s or rel.startswith(s + "/") for s in scan_paths)


def _validate_rule(rule: Any, idx: int, repo_root: Path, seen: set[str]) -> dict[str, Any]:
    if not isinstance(rule, dict):
        raise ConfigError(f"rule[{idx}] must be a JSON object")
    unknown = set(rule) - RULE_ALLOWED_KEYS
    if unknown:
        raise ConfigError(f"rule[{idx}] unknown keys: {sorted(unknown)}")
    name = rule.get("name")
    if not isinstance(name, str) or not name:
        raise ConfigError(f"rule[{idx}] requires a non-empty string 'name'")
    if name in seen:
        raise ConfigError(f"duplicate rule name: {name!r}")
    seen.add(name)

    scan = rule.get("scan")
    if not isinstance(scan, list) or not scan:
        raise ConfigError(f"rule {name!r}: 'scan' must be a non-empty list")
    scan_paths: list[str] = []
    seen_scan: set[str] = set()
    for s in scan:
        if not isinstance(s, str) or not _is_safe_rel(s):
            raise ConfigError(f"rule {name!r}: unsafe scan path {s!r}")
        if s in seen_scan:
            raise ConfigError(f"rule {name!r}: duplicate scan path {s!r}")
        seen_scan.add(s)
        scan_paths.append(s)

    forbid = rule.get("forbid")
    if not isinstance(forbid, list) or not forbid:
        raise ConfigError(f"rule {name!r}: 'forbid' must be a non-empty list")
    forbid_list: list[str] = []
    seen_forbid: set[str] = set()
    for f in forbid:
        if not isinstance(f, str):
            raise ConfigError(f"rule {name!r}: forbid entry must be a string")
        _validate_module_prefix(f)
        if f in seen_forbid:
            raise ConfigError(f"rule {name!r}: duplicate forbid entry {f!r}")
        seen_forbid.add(f)
        forbid_list.append(f)

    allow_files = rule.get("allow_files", []) or []
    if not isinstance(allow_files, list):
        raise ConfigError(f"rule {name!r}: 'allow_files' must be a list")
    allow_set: list[str] = []
    seen_allow: set[str] = set()
    for af in allow_files:
        if not isinstance(af, str) or not _is_safe_rel(af):
            raise ConfigError(f"rule {name!r}: unsafe allow-file path {af!r}")
        if af in seen_allow:
            raise ConfigError(f"rule {name!r}: duplicate allow-file {af!r}")
        seen_allow.add(af)
        resolved_af = _assert_within(repo_root, repo_root / af, f"allow-file {af!r}")
        if not resolved_af.is_file():
            raise ConfigError(f"rule {name!r}: allow-file does not exist: {af!r}")
        if not _within_scan(af, scan_paths):
            raise ConfigError(f"rule {name!r}: allow-file outside scan scope: {af!r}")
        allow_set.append(af)

    required = rule.get("required", False)
    if not isinstance(required, bool):
        raise ConfigError(f"rule {name!r}: 'required' must be a boolean")

    return {
        "name": name,
        "scan": scan_paths,
        "forbid": forbid_list,
        "allow_files": allow_set,
        "required": required,
    }


def validate_config(data: Any, repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if not isinstance(data, dict):
        raise ConfigError("config root must be a JSON object")
    unknown = set(data) - CONFIG_ALLOWED_KEYS
    if unknown:
        raise ConfigError(f"unknown top-level keys: {sorted(unknown)}")
    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ConfigError("config must contain a non-empty 'rules' list")
    seen: set[str] = set()
    out = [_validate_rule(r, i, repo_root, seen) for i, r in enumerate(rules)]
    return {"rules": out}


def load_config(path: Path, repo_root: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"unreadable config {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON config {path}: {exc}") from exc
    return validate_config(data, repo_root)


def _assert_within(repo_root: Path, target: Path, what: str) -> Path:
    """Resolve ``target`` and prove its resolved location stays inside ``repo_root``.

    Fail-closed: a symlink (or any path component) that resolves outside the
    resolved repo root raises :class:`ConfigError` instead of being scanned.
    Returns the fully resolved path (kept inside the root), so downstream
    repo-relative output paths remain stable.
    """
    resolved = target.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        raise ConfigError(f"{what} escapes repo root: {target} resolves to {resolved}") from None
    return resolved


def expand_scan(repo_root: Path, scan_paths: list[str]) -> list[Path]:
    files: set[Path] = set()
    for s in scan_paths:
        try:
            root = _assert_within(repo_root, repo_root / s, f"scan path {s!r}")
            if root.is_file():
                if root.suffix == ".py":
                    files.add(root)
            elif root.is_dir():
                for f in root.rglob("*.py"):
                    resolved = _assert_within(repo_root, f, f"discovered file {f!r}")
                    if resolved.is_file():
                        files.add(resolved)
        except OSError as exc:
            raise ConfigError(f"scan traversal failed for {s!r}: {exc}") from exc
    return sorted(files, key=lambda f: f.as_posix())


def _rel_posix(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def scan_py(path: Path, rule: dict[str, Any], repo_root: Path) -> list[Violation]:
    rel = _rel_posix(path, repo_root)
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"unreadable file {path}: {exc}") from exc
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise ConfigError(f"syntax error in {path}: line {exc.lineno}: {exc.msg}") from exc
    # Parse first, allow only after: an allowed file with a syntax error or
    # unreadable content must still fail closed.
    if rel in rule["allow_files"]:
        return []
    forbid = rule["forbid"]
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _forbidden_match(alias.name, forbid) is not None:
                    violations.append(Violation(rule["name"], path, node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue
            module = node.module or ""
            if _forbidden_match(module, forbid) is not None:
                violations.append(Violation(rule["name"], path, node.lineno, module))
    return violations


def run_check(config: dict[str, Any], repo_root: Path) -> tuple[list[Violation], dict[str, int]]:
    repo_root = repo_root.resolve()
    violations: list[Violation] = []
    counts: dict[str, int] = {}
    for rule in config["rules"]:
        files = expand_scan(repo_root, rule["scan"])
        if rule["required"] and not files:
            raise ConfigError(f"rule {rule['name']!r} is required but matches zero files")
        counts[rule["name"]] = len(files)
        for f in files:
            violations.extend(scan_py(f, rule, repo_root))
    return violations, counts


def format_violations(violations: list[Violation], repo_root: Path) -> list[str]:
    ordered = sorted(
        violations,
        key=lambda v: (v.rule, _rel_posix(v.file, repo_root), v.lineno, v.module),
    )
    return [
        f"{v.rule}: {_rel_posix(v.file, repo_root)}:{v.lineno}: imports {v.module}" for v in ordered
    ]


def run_check_cli(repo_root: Path, config_path: Path | None) -> int:
    repo_root = repo_root.resolve()
    if config_path is None:
        config_path = repo_root / "config" / "import_boundary.yaml"
    config_path = config_path.resolve()
    try:
        config = load_config(config_path, repo_root)
        violations, counts = run_check(config, repo_root)
    except ConfigError as exc:
        print(f"[import-boundary] ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"[import-boundary] repo={repo_root}")
    for rule in config["rules"]:
        print(f"[import-boundary] rule {rule['name']}: scanned {counts[rule['name']]} file(s)")
    if not violations:
        print("[import-boundary] OK — no boundary violations")
        return 0
    print(f"[import-boundary] {len(violations)} violation(s):")
    for line in format_violations(violations, repo_root):
        print(f"[import-boundary] {line}")
    return 1


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_case_in(tmp: Path, config_dict: dict[str, Any], files: dict[str, str]):
    for rel, content in files.items():
        _write(tmp / rel, content)
    cfg = tmp / "config" / "import_boundary.yaml"
    _write(cfg, json.dumps(config_dict, ensure_ascii=False, indent=2))
    config = load_config(cfg, tmp)
    return run_check(config, tmp)


def _run_case(config_dict: dict[str, Any], files: dict[str, str]):
    with tempfile.TemporaryDirectory(prefix="import_boundary_selfcheck_") as td:
        return _run_case_in(Path(td).resolve(), config_dict, files)


def _violation_key(v: Violation) -> tuple[str, int, str]:
    return (v.file.name, v.lineno, v.module)


def run_selfcheck(repo_root: Path, config_path: Path | None) -> int:
    del repo_root, config_path  # selfcheck is fully isolated; ignores repo/config args
    results: list[tuple[str, str | None]] = []

    def record(label: str, error: str | None) -> None:
        results.append((label, error))

    # A. clean imports pass (import X and from X import Y)
    try:
        violations, _ = _run_case(
            {
                "rules": [
                    {
                        "name": "r",
                        "scan": ["src"],
                        "forbid": ["app.bad"],
                        "allow_files": [],
                        "required": True,
                    }
                ]
            },
            {"src/clean.py": "import app.good\nfrom app.good import thing\n"},
        )
        record("clean-imports-pass", None if not violations else f"unexpected: {violations}")
    except ConfigError as exc:
        record("clean-imports-pass", f"unexpected ConfigError: {exc}")

    # B. violations fail (import X and from X import Y)
    try:
        violations, _ = _run_case(
            {
                "rules": [
                    {
                        "name": "r",
                        "scan": ["src"],
                        "forbid": ["app.bad"],
                        "allow_files": [],
                        "required": True,
                    }
                ]
            },
            {
                "src/bad_import.py": "import app.bad\n",
                "src/bad_from.py": "from app.bad import thing\n",
            },
        )
        got = sorted(_violation_key(v) for v in violations)
        expected = [("bad_from.py", 1, "app.bad"), ("bad_import.py", 1, "app.bad")]
        record(
            "import-and-from-violations", None if got == expected else f"got {got}, want {expected}"
        )
    except ConfigError as exc:
        record("import-and-from-violations", f"unexpected ConfigError: {exc}")

    # C. child-prefix violation fails
    try:
        violations, _ = _run_case(
            {
                "rules": [
                    {
                        "name": "r",
                        "scan": ["src"],
                        "forbid": ["app.bad"],
                        "allow_files": [],
                        "required": True,
                    }
                ]
            },
            {"src/child.py": "from app.bad.sub import thing\n"},
        )
        ok = len(violations) == 1 and violations[0].module == "app.bad.sub"
        record("child-prefix-violation", None if ok else f"got {violations}")
    except ConfigError as exc:
        record("child-prefix-violation", f"unexpected ConfigError: {exc}")

    # D. substring false positive passes
    try:
        violations, _ = _run_case(
            {
                "rules": [
                    {
                        "name": "r",
                        "scan": ["src"],
                        "forbid": ["app.bad"],
                        "allow_files": [],
                        "required": True,
                    }
                ]
            },
            {"src/substr.py": "import app.badthings\nimport appbad\n"},
        )
        record("substring-false-positive", None if not violations else f"unexpected: {violations}")
    except ConfigError as exc:
        record("substring-false-positive", f"unexpected ConfigError: {exc}")

    # E. exact allow-file works while another file fails
    try:
        violations, _ = _run_case(
            {
                "rules": [
                    {
                        "name": "r",
                        "scan": ["sel"],
                        "forbid": ["app.bad"],
                        "allow_files": ["sel/allow.py"],
                        "required": True,
                    }
                ]
            },
            {"sel/allow.py": "import app.bad\n", "sel/other.py": "import app.bad\n"},
        )
        ok = len(violations) == 1 and violations[0].file.name == "other.py"
        record("allow-file-vs-other", None if ok else f"got {violations}")
    except ConfigError as exc:
        record("allow-file-vs-other", f"unexpected ConfigError: {exc}")

    # F. relative import passes
    try:
        violations, _ = _run_case(
            {
                "rules": [
                    {
                        "name": "r",
                        "scan": ["pkg"],
                        "forbid": ["app.bad"],
                        "allow_files": [],
                        "required": True,
                    }
                ]
            },
            {"pkg/__init__.py": "", "pkg/mod.py": "from . import sibling\nfrom .other import z\n"},
        )
        record("relative-import-passes", None if not violations else f"unexpected: {violations}")
    except ConfigError as exc:
        record("relative-import-passes", f"unexpected ConfigError: {exc}")

    # G. syntax error fails closed
    try:
        _run_case(
            {
                "rules": [
                    {
                        "name": "r",
                        "scan": ["src"],
                        "forbid": ["app.bad"],
                        "allow_files": [],
                        "required": True,
                    }
                ]
            },
            {"src/broken.py": "def broken(:\n"},
        )
        record("syntax-error-fails-closed", "expected ConfigError, got none")
    except ConfigError:
        record("syntax-error-fails-closed", None)

    # G2. allowed-file with syntax error still fails closed
    try:
        _run_case(
            {
                "rules": [
                    {
                        "name": "r",
                        "scan": ["sel"],
                        "forbid": ["app.bad"],
                        "allow_files": ["sel/allow.py"],
                        "required": True,
                    }
                ]
            },
            {"sel/allow.py": "def broken(:\n", "sel/other.py": "import app.bad\n"},
        )
        record("allowed-syntax-error-fails-closed", "expected ConfigError, got none")
    except ConfigError:
        record("allowed-syntax-error-fails-closed", None)

    # H. malformed/unknown config fails
    malformed_cases = [
        ("config-unknown-top-level", {"foo": 1, "rules": []}),
        ("config-empty-rules", {"rules": []}),
        (
            "config-unknown-rule-key",
            {"rules": [{"name": "r", "scan": ["src"], "forbid": ["app.bad"], "bogus": 1}]},
        ),
        (
            "config-duplicate-rule-name",
            {
                "rules": [
                    {"name": "r", "scan": ["a"], "forbid": ["x"]},
                    {"name": "r", "scan": ["b"], "forbid": ["y"]},
                ]
            },
        ),
        (
            "config-absolute-scan-glob",
            {"rules": [{"name": "r", "scan": ["/abs"], "forbid": ["x"]}]},
        ),
        (
            "config-parent-traversal-glob",
            {"rules": [{"name": "r", "scan": ["../up"], "forbid": ["x"]}]},
        ),
        (
            "config-invalid-allow-file",
            {
                "rules": [
                    {
                        "name": "r",
                        "scan": ["src"],
                        "forbid": ["x"],
                        "allow_files": ["src/missing.py"],
                    }
                ]
            },
        ),
        ("config-duplicate-scan", {"rules": [{"name": "r", "scan": ["a", "a"], "forbid": ["x"]}]}),
        (
            "config-duplicate-forbid",
            {"rules": [{"name": "r", "scan": ["a"], "forbid": ["x", "x"]}]},
        ),
    ]
    for label, cfg in malformed_cases:
        try:
            _run_case(cfg, {})
            record(label, "expected ConfigError, got none")
        except ConfigError:
            record(label, None)

    # H2. duplicate allow_files entry fails (file must exist to reach the check)
    try:
        _run_case(
            {
                "rules": [
                    {
                        "name": "r",
                        "scan": ["a"],
                        "forbid": ["x"],
                        "allow_files": ["a/f.py", "a/f.py"],
                    }
                ]
            },
            {"a/f.py": ""},
        )
        record("config-duplicate-allow-files", "expected ConfigError, got none")
    except ConfigError:
        record("config-duplicate-allow-files", None)

    # H3. invalid raw JSON config fails through load_config
    try:
        with tempfile.TemporaryDirectory(prefix="import_boundary_selfcheck_") as td:
            tmp = Path(td).resolve()
            cfg = tmp / "config" / "import_boundary.yaml"
            _write(cfg, "{ this is not valid json")
            load_config(cfg, tmp)
        record("invalid-raw-json", "expected ConfigError, got none")
    except ConfigError:
        record("invalid-raw-json", None)

    # I. required zero-match rule fails
    try:
        _run_case(
            {
                "rules": [
                    {
                        "name": "r",
                        "scan": ["nonexistent"],
                        "forbid": ["x"],
                        "allow_files": [],
                        "required": True,
                    }
                ]
            },
            {},
        )
        record("required-zero-match", "expected ConfigError, got none")
    except ConfigError:
        record("required-zero-match", None)

    # I2. symlink escape rejected when symlinks are supported
    try:
        with tempfile.TemporaryDirectory(prefix="import_boundary_selfcheck_") as td:
            base = Path(td).resolve()
            repo = base / "root"
            outside = base / "outside"
            _write(outside / "evil.py", "import app.bad\n")
            src = repo / "src"
            src.mkdir(parents=True)
            try:
                (src / "link.py").symlink_to(outside / "evil.py")
            except OSError:
                record("symlink-escape-rejected", None)  # symlinks unsupported: skip
            else:
                config = {
                    "rules": [
                        {
                            "name": "r",
                            "scan": ["src"],
                            "forbid": ["app.bad"],
                            "allow_files": [],
                            "required": True,
                        }
                    ]
                }
                _run_case_in(repo, config, {})
                record("symlink-escape-rejected", "expected ConfigError, got none")
    except ConfigError:
        record("symlink-escape-rejected", None)

    # J. production ordering is stable by rule, file, line, module (no pre-sorting)
    fixture = {"src/z.py": "import app.bad\n", "src/a.py": "from app.bad import x\n"}
    config = {
        "rules": [
            {
                "name": "r",
                "scan": ["src"],
                "forbid": ["app.bad"],
                "allow_files": [],
                "required": True,
            }
        ]
    }
    try:
        with tempfile.TemporaryDirectory(prefix="import_boundary_selfcheck_") as td:
            tmp = Path(td).resolve()
            first = format_violations(_run_case_in(tmp, config, fixture)[0], tmp)
            second = format_violations(_run_case_in(tmp, config, fixture)[0], tmp)
            expected = [
                "r: src/a.py:1: imports app.bad",
                "r: src/z.py:1: imports app.bad",
            ]
            ok = first == second and first == expected
            record(
                "deterministic-ordering",
                None if ok else f"got {first} / {second}, want {expected}",
            )
    except ConfigError as exc:
        record("deterministic-ordering", f"unexpected ConfigError: {exc}")

    for label, err in results:
        if err is None:
            print(f"[selfcheck] PASS {label}")
        else:
            print(f"[selfcheck] FAIL {label}: {err}")
    failed = sum(1 for _, err in results if err is not None)
    if failed:
        print(f"[selfcheck] {failed} case(s) failed", file=sys.stderr)
        return 2
    print(f"[selfcheck] OK — {len(results)} case(s) passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="check repo against configured boundaries"
    )
    parser.add_argument("--selfcheck", action="store_true", help="run isolated mutation self-tests")
    parser.add_argument(
        "--repo-root", type=Path, default=None, help="repo root (default: inferred)"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="config file (default: config/import_boundary.yaml)",
    )
    args = parser.parse_args(argv)

    if args.check and args.selfcheck:
        print(
            "[import-boundary] ERROR: choose exactly one of --check / --selfcheck", file=sys.stderr
        )
        return 2
    if not args.check and not args.selfcheck:
        print("[import-boundary] ERROR: must specify --check or --selfcheck", file=sys.stderr)
        return 2

    repo_root = (
        Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parents[2]
    )
    if not repo_root.is_dir():
        print(f"[import-boundary] ERROR: repo root not a directory: {repo_root}", file=sys.stderr)
        return 2

    if args.check:
        return run_check_cli(repo_root, args.config)
    return run_selfcheck(repo_root, args.config)


if __name__ == "__main__":
    sys.exit(main())

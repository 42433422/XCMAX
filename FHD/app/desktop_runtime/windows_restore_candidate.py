"""Windows 恢复候选：在应用替换目录之外准备可信恢复程序及依赖清单。

对应需求第 16、17 条：

- 恢复程序与依赖必须完整复制到应用替换目录之外，不能只复制一个 EXE；
- 必须核验清单与逐文件哈希；
- 不得使用旧版备份中的后端执行只有新版才支持的恢复协议。

本模块只负责“准备与核验”，不执行恢复；执行由
``windows_restore_job`` 在 Job Object 内完成。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

MANIFEST_NAME = "manifest.json"
DEFAULT_BACKEND_ARGV = ["-m", "app.desktop_runtime.restore_helper"]
_BUNDLE_SKIP_SUFFIXES = (".pyc",)


class RestoreBundleError(RuntimeError):
    """恢复候选包准备或核验失败。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


@dataclass(frozen=True)
class BundleManifest:
    executable: str
    argv: tuple[str, ...]
    files: tuple[dict[str, str], ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "executable": self.executable,
            "argv": list(self.argv),
            "files": list(self.files),
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normcase(path: Path) -> str:
    return os.path.normcase(os.path.realpath(str(path)))


def _is_inside(root: Path, candidate: Path) -> bool:
    root_key = _normcase(root)
    candidate_key = _normcase(candidate)
    return candidate_key == root_key or candidate_key.startswith(
        root_key + os.sep
    )


def _iter_bundle_files(source: Path) -> list[Path]:
    collected: list[Path] = []
    if source.is_file():
        return [source]
    for current_root, _dirs, names in os.walk(source):
        for name in names:
            path = Path(current_root) / name
            if path.is_symlink():
                raise RestoreBundleError(
                    "DB_GUARD_HELPER_UNVERIFIED",
                    f"恢复程序依赖不能是软链接：{path}",
                )
            if path.suffix in _BUNDLE_SKIP_SUFFIXES:
                continue
            collected.append(path)
    return sorted(collected, key=lambda item: str(item))


def build_helper_bundle(
    source: str | os.PathLike[str],
    install_dir: str | os.PathLike[str],
    bundle_root: str | os.PathLike[str],
    *,
    executable_name: str = "xcagi-backend.exe",
    argv: list[str] | None = None,
    bundle_name: str = "current",
) -> Path:
    """把恢复程序及依赖复制到 ``bundle_root/bundle_name`` 并生成清单。

    ``bundle_root`` 必须位于 ``install_dir`` 之外，否则拒绝执行——被替换的
    目录里的“恢复程序”无法在替换过程中存活。
    """

    source_path = Path(source).resolve()
    install_path = Path(install_dir).resolve()
    bundle_root_path = Path(bundle_root).resolve()

    if not source_path.exists():
        raise RestoreBundleError("DB_GUARD_HELPER_MISSING", f"恢复程序源不存在：{source_path}")
    if _is_inside(install_path, bundle_root_path):
        raise RestoreBundleError(
            "DB_GUARD_PATH_ESCAPE",
            f"恢复候选包不能在待替换的应用目录内：{bundle_root_path}",
        )

    if source_path.is_dir():
        executable = source_path / executable_name
        if not executable.is_file():
            raise RestoreBundleError(
                "DB_GUARD_HELPER_MISSING",
                f"恢复程序目录缺少主程序 {executable_name}：{source_path}",
            )
    else:
        executable = source_path

    staging = bundle_root_path / f".{bundle_name}.staging-{os.getpid()}"
    target = bundle_root_path / bundle_name
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, str]] = []
    base = source_path if source_path.is_dir() else source_path.parent
    try:
        for item in _iter_bundle_files(source_path):
            relative = item.relative_to(base)
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
            entries.append({"path": relative.as_posix(), "sha256": _sha256(destination)})
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise RestoreBundleError(
            "DB_GUARD_HELPER_UNVERIFIED", f"复制恢复程序依赖失败：{exc}"
        ) from exc

    manifest = BundleManifest(
        executable=(Path(executable_name) if source_path.is_dir() else executable.name).as_posix(),
        argv=tuple(argv or DEFAULT_BACKEND_ARGV),
        files=tuple(entries),
    )
    (staging / MANIFEST_NAME).write_text(
        json.dumps(manifest.to_payload(), indent=2), encoding="utf-8"
    )

    verify_helper_bundle(staging)
    if target.exists():
        shutil.rmtree(target)
    os.replace(staging, target)
    verify_helper_bundle(target)
    return target


def verify_helper_bundle(bundle_dir: str | os.PathLike[str]) -> BundleManifest:
    """逐文件核验清单与哈希；任何缺失或不一致都拒绝执行。"""

    root = Path(bundle_dir).resolve()
    manifest_path = root / MANIFEST_NAME
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RestoreBundleError(
            "DB_GUARD_HELPER_UNVERIFIED", f"恢复程序清单缺失或不可解析：{manifest_path}"
        ) from exc

    executable = str(payload.get("executable") or "")
    files = payload.get("files")
    if not executable or not isinstance(files, list) or not files:
        raise RestoreBundleError(
            "DB_GUARD_HELPER_UNVERIFIED", "恢复程序清单为空，无法核验依赖完整性"
        )

    manifest = BundleManifest(
        executable=executable,
        argv=tuple(str(item) for item in payload.get("argv") or []),
        files=tuple(
            {"path": str(item.get("path")), "sha256": str(item.get("sha256"))}
            for item in files
            if isinstance(item, dict) and item.get("path") and item.get("sha256")
        ),
    )
    if len(manifest.files) != len(files):
        raise RestoreBundleError(
            "DB_GUARD_HELPER_UNVERIFIED", "恢复程序清单存在缺少 path/sha256 的条目"
        )

    for entry in manifest.files:
        absolute = root / entry["path"]
        if not absolute.is_file():
            raise RestoreBundleError(
                "DB_GUARD_HELPER_UNVERIFIED", f"恢复程序依赖缺失：{absolute}"
            )
        if _sha256(absolute) != entry["sha256"]:
            raise RestoreBundleError(
                "DB_GUARD_HELPER_UNVERIFIED", f"恢复程序依赖哈希不匹配：{absolute}"
            )

    if not (root / manifest.executable).is_file():
        raise RestoreBundleError(
            "DB_GUARD_HELPER_MISSING", f"恢复程序不存在：{root / manifest.executable}"
        )
    return manifest


def helper_invocation(manifest: BundleManifest, bundle_dir: str | os.PathLike[str]) -> list[str]:
    """返回可执行的命令前缀（主程序 + 附加参数）。"""

    return [str(Path(bundle_dir).resolve() / manifest.executable), *manifest.argv]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="准备/核验 Windows 恢复候选包")
    parser.add_argument("--source", required=True, help="构建产物中的后端目录或可执行文件")
    parser.add_argument("--install-dir", required=True, help="被替换的应用安装目录")
    parser.add_argument("--bundle-root", required=True, help="应用目录之外的可写目录")
    parser.add_argument("--bundle-name", default="current")
    parser.add_argument("--executable-name", default="xcagi-backend.exe")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        bundle = build_helper_bundle(
            args.source,
            args.install_dir,
            args.bundle_root,
            executable_name=args.executable_name,
            bundle_name=args.bundle_name,
        )
        manifest = verify_helper_bundle(bundle)
    except RestoreBundleError as exc:
        output = {"status": "failed", **exc.to_dict()}
        print(json.dumps(output, ensure_ascii=False) if args.json else exc)
        return 1

    output = {
        "status": "verified",
        "bundle": str(bundle),
        "executable": manifest.executable,
        "files": len(manifest.files),
    }
    print(json.dumps(output, ensure_ascii=False) if args.json else output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

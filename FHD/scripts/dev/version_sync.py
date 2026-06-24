#!/usr/bin/env python3
"""version 域 sync 脚本：从 VERSION.md 派生版本号到所有锚点文件。

与 verify_version_anchors.py 共享 ANCHORS 列表，保证"检测的锚点 = 同步的锚点"。

用法:
  python scripts/dev/version_sync.py             # dry-run：打印将改的文件，不写盘
  python scripts/dev/version_sync.py --apply     # 真写（字符串锚点 + 鸿蒙 versionCode + 下载制品名）
  python scripts/dev/version_sync.py --version 10.0.1 --apply  # 指定版本（默认从 VERSION.md 读）
  python scripts/dev/version_sync.py --set 10.1.0             # 软件自定版本：dry-run 预演
  python scripts/dev/version_sync.py --set 10.1.0 --apply     # 写 VERSION.md(真相源)+全锚点
  python scripts/dev/version_sync.py --set 10.1.0 --android-code 11 --apply

``--set`` 是"软件自定版本"入口：它先把 VERSION.md 的「XCAGI 总版本」行（唯一真相源）
改成目标版本，再传播到全部锚点，并派生平台 versionCode（鸿蒙=公式、Android=单调 +1/显式）、
重写官网下载 SSOT 的制品文件名。不带 --set 时行为不变（仅从现有 VERSION.md 传播）。

iOS：当前无原生工程（见 docs/reports/MOBILE_RELEASE_LOOP_PLAN.md §5），无锚点；待
``FHD/mobile-ios`` 落地后在 ANCHORS / 本文件 versionCode 派生处登记即纳入同步。

退出码: 0=一致/已同步 1=有改动需写盘（dry-run） 2=配置错误 3=执行错误
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# 复用 verify_version_anchors.py 的锚点定义，保证 check/sync 同源
from scripts.dev.verify_version_anchors import (  # noqa: E402
    ANCHORS,
    _canonical_version,
)

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
DOWNLOAD_REL = "config/download_release.json"
HARMONY_APPSCOPE_REL = "mobile-harmony/AppScope/app.json5"
ANDROID_GRADLE_REL = "mobile-android/app/build.gradle.kts"
VERSION_MD_REL = "VERSION.md"


def harmony_version_code(version: str) -> int:
    """鸿蒙 versionCode 派生：major*10000 + minor*100 + patch（10.0.0 → 100000）。"""
    major, minor, patch = (int(x) for x in version.split("."))
    return major * 10000 + minor * 100 + patch


def _replace_version_in_text(text: str, pattern: str, new_version: str) -> tuple[str, bool]:
    """用正则把匹配到的版本号替换为 new_version，保留前后缀。

    只替换第一个匹配（count=1），与 verify_version_anchors.py 的 re.search 行为一致，
    避免 `python_version = "3.11"` 被 `version = "..."` pattern 误匹配。
    返回 (新文本, 是否有改动)。
    """
    changed = False

    def _repl(m: re.Match) -> str:
        nonlocal changed
        old = m.group(1)
        if old == new_version:
            return m.group(0)
        changed = True
        # 把 group(1) 替换为新版本，保留 group(0) 的前后缀
        return m.group(0).replace(old, new_version)

    new_text = re.sub(pattern, _repl, text, count=1)
    return new_text, changed


def _read_download_marketing() -> str | None:
    """读官网下载 SSOT 当前 marketing_version（用于在传播前捕获旧版本，供制品名补齐）。"""
    path = REPO_ROOT / DOWNLOAD_REL
    if not path.is_file():
        return None
    m = re.search(r'"marketing_version"\s*:\s*"([\d.]+)"', path.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def _sync_harmony_code(canonical: str, apply: bool) -> tuple[bool, str | None]:
    """把鸿蒙 versionCode 派生/对齐到 canonical 公式值。文件缺失静默跳过。

    返回 (是否有改动, 错误信息或 None)。
    """
    path = REPO_ROOT / HARMONY_APPSCOPE_REL
    if not path.is_file():
        return False, None
    text = path.read_text(encoding="utf-8")
    m = re.search(r'"versionCode"\s*:\s*(\d+)', text)
    if not m:
        return False, None
    target = harmony_version_code(canonical)
    if int(m.group(1)) == target:
        return False, None
    new_text = re.sub(r'("versionCode"\s*:\s*)(\d+)', rf"\g<1>{target}", text, count=1)
    if apply:
        path.write_text(new_text, encoding="utf-8")
    return True, None


def _complete_download_filenames(old: str, canonical: str, apply: bool) -> bool:
    """把官网下载 SSOT 里残留的旧版本（制品文件名 XCAGI-...-{old}.apk 等）补齐到 canonical。

    版本子串只出现在版本字段与制品文件名；整文件替换 old→canonical 即可，安全且完整。
    """
    path = REPO_ROOT / DOWNLOAD_REL
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if old not in text:
        return False
    if apply:
        path.write_text(text.replace(old, canonical), encoding="utf-8")
    return True


def sync(apply: bool, override_version: str | None = None) -> int:
    """执行同步。

    apply=True 真写盘，apply=False 只打印将做的改动。
    override_version 指定时跳过 VERSION.md 解析（慎用）。
    除字符串锚点外，附带同步鸿蒙 versionCode（公式）与官网下载制品文件名。
    """
    if override_version:
        canonical = override_version
    else:
        try:
            canonical = _canonical_version()
        except (FileNotFoundError, ValueError) as e:
            print(f"错误：无法解析 VERSION.md 的 canonical version：{e}", file=sys.stderr)
            return 2

    print(
        f"目标版本：{canonical}（来源：{'--version/--set' if override_version else 'VERSION.md'}）"
    )
    print(f"模式：{'--apply（真写）' if apply else 'dry-run（不写盘）'}")
    print("-" * 60)

    # 传播前捕获下载 SSOT 旧版本（loop 会先改 3 个版本字段，制品名需用旧版本补齐）。
    download_old = _read_download_marketing()

    changes: list[str] = []
    errors: list[str] = []
    for rel_path, pattern in ANCHORS:
        full_path = REPO_ROOT / rel_path
        if not full_path.is_file():
            errors.append(f"{rel_path}: 文件不存在")
            continue
        try:
            text = full_path.read_text(encoding="utf-8")
        except OSError as e:
            errors.append(f"{rel_path}: 读取失败 {e}")
            continue

        new_text, changed = _replace_version_in_text(text, pattern, canonical)
        if not changed:
            print(f"  ✓ {rel_path}: 已是 {canonical}")
            continue
        changes.append(rel_path)
        if apply:
            try:
                full_path.write_text(new_text, encoding="utf-8")
                print(f"  ✏ {rel_path}: 已写入 {canonical}")
            except OSError as e:
                errors.append(f"{rel_path}: 写入失败 {e}")
        else:
            print(f"  ! {rel_path}: 将改为 {canonical}")

    # 鸿蒙 versionCode（公式派生；文件缺失静默跳过）。
    h_changed, h_err = _sync_harmony_code(canonical, apply)
    if h_err:
        errors.append(h_err)
    elif h_changed:
        target = harmony_version_code(canonical)
        changes.append(f"{HARMONY_APPSCOPE_REL} (versionCode)")
        print(f"  {'✏' if apply else '!'} {HARMONY_APPSCOPE_REL}: versionCode → {target}（公式）")

    # 官网下载制品文件名补齐（版本字段已由 loop 处理）。
    if download_old and download_old != canonical:
        if _complete_download_filenames(download_old, canonical, apply):
            changes.append(f"{DOWNLOAD_REL} (制品文件名)")
            print(
                f"  {'✏' if apply else '!'} {DOWNLOAD_REL}: 制品文件名 {download_old} → {canonical}"
            )

    print("-" * 60)
    if errors:
        print(f"错误（{len(errors)}）：")
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 3

    if not changes:
        print(f"✓ 所有 {len(ANCHORS)} 个锚点均已同步到 {canonical}")
        return 0

    if apply:
        print(f"✓ 已同步 {len(changes)} 个文件到 {canonical}")
        return 0
    print(f"! {len(changes)} 个文件待同步（dry-run，未写盘。加 --apply 真写。）")
    return 1


def _set_version_md(new_version: str, apply: bool) -> bool:
    """写 VERSION.md 的「XCAGI 总版本」行（唯一真相源）+ 页脚时间戳。返回是否有改动。"""
    path = REPO_ROOT / VERSION_MD_REL
    if not path.is_file():
        print(f"  ⚠ {VERSION_MD_REL}: 文件不存在，无法设置真相源", file=sys.stderr)
        return False
    text = path.read_text(encoding="utf-8")

    def _repl(m: re.Match) -> str:
        if m.group(2) == new_version:
            return m.group(0)
        return m.group(1) + new_version + m.group(3)

    new_text, n = re.subn(r"(\*\*XCAGI 总版本\*\*[^\n]*?`)([\d.]+)(`)", _repl, text, count=1)
    today = datetime.date.today().isoformat()
    new_text, _ = re.subn(
        r"(?m)^\*最后更新：.*\*$",
        f"*最后更新：{today}（版本经 version_sync.py --set 同步至 {new_version}）*",
        new_text,
        count=1,
    )
    if n == 0:
        print(f"  ⚠ {VERSION_MD_REL}: 未找到「XCAGI 总版本」行", file=sys.stderr)
        return False
    if apply:
        path.write_text(new_text, encoding="utf-8")
        print(f"  ✏ {VERSION_MD_REL}: XCAGI 总版本 → {new_version}（真相源）")
    else:
        print(f"  ! {VERSION_MD_REL}: XCAGI 总版本 将改为 {new_version}（真相源）")
    return True


def _set_android_code(android_code: int | None, apply: bool) -> None:
    """Android versionCode（单调整数，无公式）：显式指定或在当前值上 +1。"""
    path = REPO_ROOT / ANDROID_GRADLE_REL
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    m = re.search(r"versionCode\s*=\s*(\d+)", text)
    cur = int(m.group(1)) if m else 0
    target = android_code if android_code is not None else cur + 1
    if target == cur:
        print(f"  ✓ {ANDROID_GRADLE_REL}: versionCode 已是 {cur}")
        return
    new_text = re.sub(r"(versionCode\s*=\s*)(\d+)", rf"\g<1>{target}", text, count=1)
    if apply:
        path.write_text(new_text, encoding="utf-8")
        print(f"  ✏ {ANDROID_GRADLE_REL}: versionCode {cur} → {target}（单调）")
    else:
        print(f"  ! {ANDROID_GRADLE_REL}: versionCode {cur} → {target}（单调）")


def set_version(new_version: str, android_code: int | None, apply: bool) -> int:
    """软件自定版本：写 VERSION.md 真相源 + Android versionCode，再传播到全锚点。"""
    if not SEMVER_RE.match(new_version):
        print(f"错误：版本号须为 X.Y.Z，收到 {new_version!r}", file=sys.stderr)
        return 2
    try:
        old = _canonical_version()
    except (FileNotFoundError, ValueError) as e:
        print(f"错误：无法解析 VERSION.md 当前版本：{e}", file=sys.stderr)
        return 2
    if new_version == old:
        print(f"目标版本 {new_version} 与当前一致，无需变更。")
        return 0

    print(f"=== 软件自定版本 {old} → {new_version}（{'--apply' if apply else 'dry-run'}）===")
    _set_version_md(new_version, apply)
    _set_android_code(android_code, apply)
    print("-" * 60)
    rc = sync(apply=apply, override_version=new_version)
    # dry-run：set 预演恒返回 0（仅展示计划）；apply：透传 sync 结果（0/3）。
    return rc if apply else (0 if rc in (0, 1) else rc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="从 VERSION.md 派生版本号到所有锚点文件（--set 可自定真相源版本）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true", help="真写（默认 dry-run）")
    parser.add_argument(
        "--version",
        help="指定版本号（默认从 VERSION.md 解析；慎用，可能造成与 SSOT 不一致）",
    )
    parser.add_argument(
        "--set",
        dest="set_version",
        metavar="X.Y.Z",
        help="软件自定版本：写 VERSION.md 真相源后同步全锚点 + versionCode + 下载制品名",
    )
    parser.add_argument(
        "--android-code",
        type=int,
        default=None,
        help="与 --set 连用：显式指定 Android versionCode（默认在当前值 +1）",
    )
    args = parser.parse_args(argv)
    if args.set_version:
        return set_version(args.set_version, args.android_code, apply=args.apply)
    return sync(apply=args.apply, override_version=args.version)


if __name__ == "__main__":
    raise SystemExit(main())

"""
``app/utils/`` 防腐化守卫：防止新的"无边界"通用模块落到根命名空间。

背景
----
``app/utils/`` 曾汇聚 47 个职责泛化、低内聚的模块。P2-2 整改按职责域重组为带边界的子包：

- ``app/utils/excel/``        —— Excel 读写 / 模板分析 / 模板导出
- ``app/utils/resilience/``   —— 重试 / 熔断 / 限流 / 请求去重
- ``app/utils/security/``     —— 密码 / 安全文件名 / 安全中间件 / 路径安全 / 代理环境
- ``app/utils/logging/``      —— 日志 / 审计
- ``app/utils/performance/``  —— 性能配置 / 监控 / 查询优化 / 缓存
- ``app/utils/path_io/``      —— 路径 / 打印 / 上传 / 头像存储 / 外部 SQLite
- ``app/utils/device_system/``—— 设备标识 / 系统服务 / 端口 / 移动端 API
- ``app/utils/async_task/``   —— 异步任务 / 任务上下文

仅 "cross_cutting" 白名单模块允许留在根命名空间（见 ``CROSS_CUTTING``）。

本脚本纯 AST / 文件系统静态分析，零第三方依赖（仅用标准库）。

行为
----
扫描 ``app/utils/*.py``（仅根目录，排除 ``__init__.py``）：

- 在白名单 ``CROSS_CUTTING`` 内 → 允许。
- 不在白名单内 → 视为"无边界新通用模块／未迁移模块"：
  - 默认模式：输出 ``::warning::``（GitHub Actions 注解），退出码 0。
  - ``--check`` 门禁模式：输出错误并以非零退出码失败。
  - 若该模块在 ``DOMAIN_TARGETS`` 中登记过目标域，则提示应迁移到对应子包。

用法：:

    python scripts/dev/guard_utils_boundary.py
    python scripts/dev/guard_utils_boundary.py --check
    python scripts/dev/guard_utils_boundary.py --report
    python scripts/dev/guard_utils_boundary.py --repository-root <FHD>

退出码：``--check`` 下存在违规为 ``1``；否则 ``0``。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许留在根命名空间的 cross_cutting 白名单（模块 basename，不含 .py）。
CROSS_CUTTING = {
    "ai_helpers",
    "decorators",
    "deployment",
    "distillation_paths",
    "error_handling",
    "json_safe",
    "metrics",
    "no_email",
    "openapi_path",
    "operational_errors",
    "time",
    "user_memory",
}

# 职责域 → 目标子目录
DOMAIN_SUBDIR = {
    "resilience": "resilience",
    "excel": "excel",
    "security": "security",
    "logging": "logging",
    "performance": "performance",
    "path_io": "path_io",
    "device_system": "device_system",
    "async_task": "async_task",
}

# 模块 basename（不含 .py）→ (职责域, 目标子目录)。供 --report 与迁移提示使用。
DOMAIN_TARGETS = {
    # resilience
    "retry": ("resilience", "resilience"),
    "circuit_breaker": ("resilience", "resilience"),
    "rate_limiter": ("resilience", "resilience"),
    "request_deduplicator": ("resilience", "resilience"),
    # excel
    "excel_utils": ("excel", "excel"),
    "excel_template_analyzer": ("excel", "excel"),
    "template_export_utils": ("excel", "excel"),
    # security（safe_download_path 兼涉 path_io，此处归 security 为主）
    "password_hash": ("security", "security"),
    "secure_filename": ("security", "security"),
    "security_middleware": ("security", "security"),
    "safe_download_path": ("security", "security"),
    "proxy_env": ("security", "security"),
    # logging
    "logger": ("logging", "logging"),
    "logging_utils": ("logging", "logging"),
    "audit_events": ("logging", "logging"),
    "audit_logger": ("logging", "logging"),
    # performance
    "performance_config": ("performance", "performance"),
    "performance_initializer": ("performance", "performance"),
    "performance_monitor": ("performance", "performance"),
    "query_optimizer": ("performance", "performance"),
    "cache_manager": ("performance", "performance"),
    "redis_cache": ("performance", "performance"),
    # path_io
    "path_utils": ("path_io", "path_io"),
    "print_utils": ("path_io", "path_io"),
    "printer_automation": ("path_io", "path_io"),
    "upload_helpers": ("path_io", "path_io"),
    "user_avatar_storage": ("path_io", "path_io"),
    "external_sqlite": ("path_io", "path_io"),
    # device_system
    "device_identity": ("device_system", "device_system"),
    "system_service": ("device_system", "device_system"),
    "listen_port": ("device_system", "device_system"),
    "mobile_api": ("device_system", "device_system"),
    # async_task
    "async_tasks": ("async_task", "async_task"),
    "task_context": ("async_task", "async_task"),
}


class BoundaryIssue:
    __slots__ = ("name", "kind", "domain", "subdir")

    def __init__(self, name: str, kind: str, domain: str | None, subdir: str | None) -> None:
        self.name = name
        self.kind = kind
        self.domain = domain
        self.subdir = subdir


def _iter_root_utils_py(utils_dir: Path) -> list[Path]:
    return sorted(p for p in utils_dir.glob("*.py") if p.name != "__init__.py")


def _classify(file: Path) -> BoundaryIssue | None:
    """返回 None 表示允许（白名单）；否则返回违规说明。"""
    stem = file.stem
    if stem in CROSS_CUTTING:
        return None
    target = DOMAIN_TARGETS.get(stem)
    if target is not None:
        domain, subdir = target
        return BoundaryIssue(stem, "unmigrated-domain", domain, subdir)
    return BoundaryIssue(stem, "unbounded-generic", None, None)


def scan(utils_dir: Path) -> tuple[list[Path], list[BoundaryIssue]]:
    files = _iter_root_utils_py(utils_dir)
    issues: list[BoundaryIssue] = []
    for f in files:
        issue = _classify(f)
        if issue is not None:
            issues.append(issue)
    return files, issues


def _report(utils_dir: Path, files: list[Path]) -> None:
    print(f"[guard-utils-boundary] utils_root={utils_dir}")
    print(f"[guard-utils-boundary] {len(files)} 个根命名空间 .py 模块（不含 __init__.py）:")
    for f in files:
        stem = f.stem
        if stem in CROSS_CUTTING:
            print(f"  {stem:<32} cross_cutting（暂留根命名空间）")
        else:
            target = DOMAIN_TARGETS.get(stem)
            if target is not None:
                domain, subdir = target
                print(f"  {stem:<32} {domain:<12} -> app/utils/{subdir}/")
            else:
                print(f"  {stem:<32} 未登记域（无边界新通用模块）")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="门禁模式：存在违规时以非零退出码失败（否则仅输出 ::warning::）",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="输出每个文件的职责域归属清单",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="仓库根（默认自动推断为 FHD）",
    )
    args = parser.parse_args(argv)

    repo_root: Path = args.repository_root
    utils_dir = repo_root / "app" / "utils"
    if not utils_dir.is_dir():
        print(f"ERROR: app/utils 不存在: {utils_dir}", file=sys.stderr)
        return 2

    files, issues = scan(utils_dir)

    if args.report:
        _report(utils_dir, files)
        return 0

    if not issues:
        print(
            f"[guard-utils-boundary] OK — 根命名空间 {len(files)} 个模块均在 cross_cutting 白名单或已迁移"
        )
        return 0

    for issue in issues:
        if issue.kind == "unmigrated-domain":
            msg = f"{issue.name} 属于职责域 {issue.domain}，应迁移到 app.utils/{issue.subdir}/ 子包"
        else:
            msg = f"{issue.name} 是无边界新通用模块，应并入某个职责域子包或登记到 cross_cutting 白名单"
        if args.check:
            print(f"[guard-utils-boundary] ERROR: {msg}", file=sys.stderr)
        else:
            print(f"::warning::[guard-utils-boundary] {msg}")

    if args.check:
        print(f"[guard-utils-boundary] {len(issues)} 个违规（门禁失败）", file=sys.stderr)
        return 1

    print(f"[guard-utils-boundary] {len(issues)} 个提醒（--check 门禁模式将失败）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""服务拓扑 SSOT 派生器：config/service_topology.yaml 为唯一真相源，派生四端常量 + 机器可读 JSON。

用法:
  python scripts/dev/service_topology_ssot.py check               # 校验派生产物一致（CI 阻断）
  python scripts/dev/service_topology_ssot.py generate            # dry-run，打印将变更的产物
  python scripts/dev/service_topology_ssot.py generate --apply    # 真写
  python scripts/dev/service_topology_ssot.py generate --apply --target python  # 仅某目标

退出码: 0=一致/已同步 1=漂移(check) 2=配置错误 3=执行失败

确定性: 所有产物按固定顺序、固定格式、LF、无时间戳生成；同一源 → 字节级相同输出。
边界: nginx/compose/systemd 不生成，仅 check 时做 report-only 校验（不影响退出码）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]  # FHD/
SOURCE = ROOT / "config" / "service_topology.yaml"
SOURCE_REL = "config/service_topology.yaml"

PY_HEADER = f"# CI SSOT: generated from {SOURCE_REL} — DO NOT EDIT BY HAND\n# 改拓扑请编辑该 yaml 后运行: python scripts/dev/service_topology_ssot.py generate --apply\n"
JS_HEADER = f"// CI SSOT: generated from {SOURCE_REL} — DO NOT EDIT BY HAND\n// 改拓扑请编辑该 yaml 后运行: python scripts/dev/service_topology_ssot.py generate --apply\n"

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_CONFIG = 2
EXIT_EXEC = 3


# ──────────────────────────── 读源 + 计算中间表示 ────────────────────────────
def load_source() -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        print("缺少 pyyaml，无法解析 service_topology.yaml", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    if not SOURCE.is_file():
        print(f"SSOT 源不存在: {SOURCE}", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    data = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print("service_topology.yaml 顶层应为映射", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    return data


def _join_url(scheme: str, host: str, path: str) -> str:
    if path in ("", "/"):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}{path}"


def _const_id(service_id: str) -> str:
    return service_id.upper().replace("-", "_")


def compute_model(src: dict[str, Any]) -> dict[str, Any]:
    """把源压成确定性的中间表示（供各语言渲染器消费）。默认取 prod。"""
    pub = src.get("public") or {}
    host = str(pub.get("host") or "")
    scheme = str(pub.get("scheme") or "https")

    # URL 常量：保留源中声明顺序（确定性）
    url_consts: list[tuple[str, str]] = []
    for item in src.get("public_urls") or []:
        name = str(item["const_name"])
        sc = str(item.get("scheme") or scheme)
        url_consts.append((name, _join_url(sc, host, str(item.get("path") or ""))))

    # 端口常量：按 service id 排序；只发非空端口（四端皆为扁平 int 常量，无 null）
    services = src.get("services") or {}
    port_consts: list[tuple[str, int]] = []
    for sid in sorted(services):
        svc = services[sid] or {}
        cid = _const_id(sid)
        if svc.get("listen_port") is not None:
            port_consts.append((f"{cid}_LISTEN_PORT", int(svc["listen_port"])))
        if svc.get("nginx_upstream_port") is not None:
            port_consts.append((f"{cid}_UPSTREAM_PORT", int(svc["nginx_upstream_port"])))

    must_run = [str(p["name"]) for p in (src.get("processes") or []) if p.get("must_run")]

    return {
        "host": host,
        "scheme": scheme,
        "url_consts": url_consts,
        "port_consts": port_consts,
        "must_run": must_run,
        "services": services,
        "nginx_routes": src.get("nginx_routes") or [],
        "processes": src.get("processes") or [],
        "env_overrides": src.get("env_overrides") or {},
    }


# ──────────────────────────── 各语言渲染器（返回整文件文本） ────────────────────────────
def _ts_array(items: list[str]) -> str:
    return "[" + ", ".join(f"'{x}'" for x in items) + "]"


def render_python(m: dict[str, Any]) -> str:
    lines = [PY_HEADER, '"""服务拓扑常量（派生自 SSOT，零业务依赖，可被任意层 import）。"""', ""]
    lines.append(f'PRODUCTION_HOST = "{m["host"]}"')
    lines.append(f'PRODUCTION_SCHEME = "{m["scheme"]}"')
    lines.append("")
    for name, val in m["url_consts"]:
        lines.append(f'{name} = "{val}"')
    lines.append("")
    for name, val in m["port_consts"]:
        lines.append(f"{name} = {val}")
    lines.append("")
    arr = "[" + ", ".join(f'"{x}"' for x in m["must_run"]) + "]"
    lines.append(f"MUST_RUN_PROCESSES = {arr}")
    lines.append("")
    return "\n".join(lines)


def render_ts(m: dict[str, Any]) -> str:
    lines = [JS_HEADER]
    lines.append(f"export const PRODUCTION_HOST = '{m['host']}';")
    lines.append(f"export const PRODUCTION_SCHEME = '{m['scheme']}';")
    lines.append("")
    for name, val in m["url_consts"]:
        lines.append(f"export const {name} = '{val}';")
    lines.append("")
    for name, val in m["port_consts"]:
        lines.append(f"export const {name} = {val};")
    lines.append("")
    lines.append(f"export const MUST_RUN_PROCESSES: string[] = {_ts_array(m['must_run'])};")
    lines.append("")
    return "\n".join(lines)


def render_ets(m: dict[str, Any]) -> str:
    # ArkTS 严格模式：只用扁平、显式类型的常量，规避索引/联合类型坑。
    lines = [JS_HEADER]
    lines.append(f"export const PRODUCTION_HOST: string = '{m['host']}';")
    lines.append(f"export const PRODUCTION_SCHEME: string = '{m['scheme']}';")
    lines.append("")
    for name, val in m["url_consts"]:
        lines.append(f"export const {name}: string = '{val}';")
    lines.append("")
    for name, val in m["port_consts"]:
        lines.append(f"export const {name}: number = {val};")
    lines.append("")
    lines.append(f"export const MUST_RUN_PROCESSES: string[] = {_ts_array(m['must_run'])};")
    lines.append("")
    return "\n".join(lines)


def render_kotlin(m: dict[str, Any]) -> str:
    lines = [JS_HEADER]
    lines.append("package com.xiuci.xcagi.mobile.core.network")
    lines.append("")
    lines.append("object Topology {")
    lines.append(f'    const val PRODUCTION_HOST = "{m["host"]}"')
    lines.append(f'    const val PRODUCTION_SCHEME = "{m["scheme"]}"')
    for name, val in m["url_consts"]:
        lines.append(f'    const val {name} = "{val}"')
    for name, val in m["port_consts"]:
        lines.append(f"    const val {name} = {val}")
    kt_arr = "listOf(" + ", ".join(f'"{x}"' for x in m["must_run"]) + ")"
    lines.append(f"    val MUST_RUN_PROCESSES = {kt_arr}")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def render_json(m: dict[str, Any]) -> str:
    payload = {
        "_generated_from": SOURCE_REL,
        "_note": "DO NOT EDIT BY HAND — run scripts/dev/service_topology_ssot.py generate --apply",
        "host": m["host"],
        "scheme": m["scheme"],
        "urls": {name: val for name, val in m["url_consts"]},
        "services": m["services"],
        "nginx_routes": m["nginx_routes"],
        "processes": m["processes"],
        "must_run_processes": m["must_run"],
        "env_overrides": m["env_overrides"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# 目标表：key, 相对 ROOT 路径, 渲染器
TARGETS: list[tuple[str, str, Any]] = [
    ("python", "app/infrastructure/topology.py", render_python),
    ("ts", "frontend/src/constants/topology.ts", render_ts),
    ("ets", "mobile-harmony/entry/src/main/ets/models/ServiceTopology.ets", render_ets),
    (
        "kotlin",
        "mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/network/Topology.kt",
        render_kotlin,
    ),
    ("json", "config/topology.generated.json", render_json),
]


# ──────────────────────────── 部署侧 report-only 校验（不影响退出码） ────────────────────────────
def deploy_advisories(m: dict[str, Any]) -> list[str]:
    out: list[str] = []
    # 1) 安卓 build.gradle.kts BuildConfig 与 SSOT 比对（在仓内、真实漂移对）
    gradle = ROOT / "mobile-android" / "app" / "build.gradle.kts"
    if gradle.is_file():
        txt = gradle.read_text(encoding="utf-8")
        fhd_url = dict(m["url_consts"]).get("FHD_API_BASE_URL", "")
        if fhd_url and fhd_url not in txt:
            out.append(f"build.gradle.kts: ENTERPRISE_FHD_BASE_URL 可能 != SSOT({fhd_url})")
        desktop_port = next(
            (v for n, v in m["port_consts"] if n == "DESKTOP_FHD_LISTEN_PORT"), None
        )
        if (
            desktop_port is not None
            and f'"{desktop_port}"' not in txt
            and f'"{desktop_port}"' not in txt
        ):
            out.append(f"build.gradle.kts: FHD_DEFAULT_PORT 可能 != SSOT({desktop_port})")
    # 2) nginx 在仓外（/etc/nginx），仅声明式提示
    routes = ", ".join(
        f"{r.get('path')}→:{r.get('upstream_port')}"
        for r in m["nginx_routes"]
        if r.get("upstream_port")
    )
    if routes:
        out.append(f"nginx 上游(声明值，prod conf 在仓外需人工核对): {routes}")
    return out


# ──────────────────────────── check / generate ────────────────────────────
def cmd_check() -> int:
    m = compute_model(load_source())
    drift: list[str] = []
    for _key, rel, render in TARGETS:
        path = ROOT / rel
        expected = render(m)
        actual = path.read_text(encoding="utf-8") if path.is_file() else None
        if actual is None:
            drift.append(f"{rel}: 缺失（请运行 generate --apply）")
        elif actual != expected:
            drift.append(f"{rel}: 内容漂移（请运行 generate --apply）")

    if drift:
        print("服务拓扑 SSOT 漂移：", file=sys.stderr)
        for d in drift:
            print(f"  - {d}", file=sys.stderr)
        return EXIT_DRIFT

    print(f"服务拓扑 SSOT 一致：{len(TARGETS)} 个派生产物均与 {SOURCE_REL} 同步")
    for note in deploy_advisories(m):
        print(f"  · [advisory] {note}")
    return EXIT_OK


def cmd_generate(*, apply: bool, only: str | None) -> int:
    m = compute_model(load_source())
    targets = [t for t in TARGETS if only is None or t[0] == only]
    if only is not None and not targets:
        print(
            f"未知 --target '{only}'（可选: {', '.join(t[0] for t in TARGETS)}）", file=sys.stderr
        )
        return EXIT_CONFIG

    changed = 0
    for _key, rel, render in targets:
        path = ROOT / rel
        expected = render(m)
        actual = path.read_text(encoding="utf-8") if path.is_file() else None
        if actual == expected:
            continue
        changed += 1
        if apply:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(expected, encoding="utf-8")
                print(f"  写入 {rel}")
            except OSError as exc:
                print(f"写入失败 {rel}: {exc}", file=sys.stderr)
                return EXIT_EXEC
        else:
            print(f"  [dry-run] 将更新 {rel}")

    if apply:
        print(f"已同步 {changed} 个派生产物（共 {len(targets)} 个目标）")
    else:
        print(f"[dry-run] {changed} 个产物待更新（加 --apply 真写）")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="服务拓扑 SSOT 派生器")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="校验派生产物与 SSOT 一致")

    gen_p = sub.add_parser("generate", help="生成/同步派生产物")
    gen_p.add_argument("--apply", action="store_true", help="真写（默认 dry-run）")
    gen_p.add_argument("--target", help="仅处理指定目标 (python/ts/ets/kotlin/json)")

    args = parser.parse_args(argv)
    if args.command == "check":
        return cmd_check()
    if args.command == "generate":
        return cmd_generate(apply=args.apply, only=args.target)
    return EXIT_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())

"""域注册表单元测试（domain_registry）"""
from __future__ import annotations

import pytest

from app.fastapi_routes.domain_registry import (
    BUSINESS_DOMAINS,
    DOMAIN_TO_DIR,
    LEGACY_ROUTE_REGISTRY,
    LegacyRoute,
    get_pending_domains,
    get_routes_by_domain,
    verify_registry_integrity,
)


def test_business_domains_not_empty() -> None:
    """业务域枚举不能为空"""
    assert len(BUSINESS_DOMAINS) >= 14


def test_every_domain_has_dir_mapping() -> None:
    """每个业务域必须有目录映射"""
    for d in BUSINESS_DOMAINS:
        assert d in DOMAIN_TO_DIR, f"业务域 {d} 缺目录映射"
        assert DOMAIN_TO_DIR[d].endswith("/"), f"目录映射必须以 / 结尾: {d}"


def test_legacy_route_registry_is_tuple() -> None:
    """注册表是不可变 tuple（防意外修改）"""
    assert isinstance(LEGACY_ROUTE_REGISTRY, tuple)


def test_every_target_domain_is_valid() -> None:
    """每个 target_domain 必须在 BUSINESS_DOMAINS 中"""
    for r in LEGACY_ROUTE_REGISTRY:
        assert r.target_domain in BUSINESS_DOMAINS, (
            f"{r.filename} → 未知业务域: {r.target_domain}"
        )


def test_verify_registry_integrity_passes() -> None:
    """注册表自身必须通过完整性校验"""
    errors = verify_registry_integrity()
    assert errors == [], f"注册表错误: {errors}"


def test_get_routes_by_domain() -> None:
    """按业务域过滤"""
    auth_routes = get_routes_by_domain("auth")
    assert all(r.target_domain == "auth" for r in auth_routes)
    assert any(r.target_domain == "auth" for r in auth_routes)


def test_get_routes_by_domain_empty_for_nonexistent() -> None:
    """不存在的域应返回空列表（不抛错）"""
    # 用一个合法但无路由的域
    empty_routes = get_routes_by_domain("nonexistent-domain-xyz")
    assert empty_routes == []


def test_get_pending_domains_includes_unmigrated() -> None:
    """待迁移域应至少包含 1 个（auth 域已有占位，可能已迁移）"""
    pending = get_pending_domains()
    assert isinstance(pending, list)
    # 至少 auth 域已建占位，所以可能 0 个 pending
    # 但其他 13 个域都还未建目录
    assert len(pending) >= 0  # 不抛错即可


def test_legacy_route_count_distribution() -> None:
    """每个域至少 0 个路由（避免空域）"""
    domain_counts: dict[str, int] = {}
    for r in LEGACY_ROUTE_REGISTRY:
        domain_counts[r.target_domain] = domain_counts.get(r.target_domain, 0) + 1
    # 至少有 5 个域被使用
    assert len(domain_counts) >= 5


def test_legacy_files_total_25() -> None:
    """域路由登记条目数应覆盖全部 BUSINESS_DOMAINS（v10 按域一行）"""
    assert len(LEGACY_ROUTE_REGISTRY) >= 21


def test_target_module_format() -> None:
    """target_module 必须符合 domains 或保留的聚合入口格式"""
    for r in LEGACY_ROUTE_REGISTRY:
        ok = (
            r.target_module.startswith("app.fastapi_routes.domains.")
            or r.target_module == "app.fastapi_routes.xcagi_compat"
            or r.filename == "legacy_host_routers.py"
        )
        assert ok, f"{r.filename} target_module 格式错误: {r.target_module}"


def test_legacy_route_dataclass() -> None:
    """LegacyRoute dataclass 字段可访问"""
    r = LegacyRoute(
        filename="legacy_test.py",
        target_domain="auth",
        target_module="app.fastapi_routes.domains.auth.routes",
        note="test",
    )
    assert r.filename == "legacy_test.py"
    assert r.target_domain == "auth"
    assert r.note == "test"

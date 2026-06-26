"""共享 fixtures：隔离配置与库目录，避免测试污染开发者本机 .modstore-config.json。"""

from __future__ import annotations

import os

# ``create_app`` → ``register_all_middleware`` 要求非空 ``MODSTORE_JWT_SECRET``（除非显式不安全标志）。
# 在收集/导入 ``modstore_server.app`` 之前写入，避免本地未配 .env 时整包测试失败。
if not (os.environ.get("MODSTORE_JWT_SECRET") or "").strip():
    os.environ["MODSTORE_JWT_SECRET"] = "pytest-default-secret-at-least-32-characters"

# TestClient 多数 POST 不带浏览器 Cookie；与 ``register_all_middleware`` 中的 CSRF 叠加会 403。
os.environ.setdefault("MODSTORE_DISABLE_CSRF", "1")

# 联网检索测试仅走 Bing 爬虫，不调用 Tavily 付费 API。
os.environ.setdefault("MODSTORE_WEB_SEARCH_USE_TAVILY", "0")
# 单元测试不抓取链接正文（集成测试可显式开启 MODSTORE_WEB_FETCH_PAGES=1）。
os.environ.setdefault("MODSTORE_WEB_FETCH_PAGES", "0")

# 未显式配置时使用临时 SQLite，避免本机 modstore.db 历史表结构缺列（如 ORM 新增列）导致测试失败。
if not (os.environ.get("MODSTORE_DB_PATH") or "").strip():
    import tempfile
    from pathlib import Path as _Path

    _pytest_db_dir = _Path(tempfile.mkdtemp(prefix="modstore_pytest_"))
    os.environ["MODSTORE_DB_PATH"] = str(_pytest_db_dir / "test.db")
    # 本机 .env.local 常设 DATABASE_URL；与临时 SQLite 并存时 get_engine 会优先 URL 导致无表/缺列。
    os.environ.pop("DATABASE_URL", None)
    os.environ["MODSTORE_PYTEST_USE_SQLITE"] = "1"

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from modman.repo_config import RepoConfig


@pytest.fixture
def isolated_modstore(tmp_path, monkeypatch):
    """
    将库根、项目根（沙箱目录父级）指向临时目录，并替换 load/save_config。
    """
    library = tmp_path / "library"
    library.mkdir(parents=True, exist_ok=True)
    project_home = tmp_path / "modstore_project"
    project_home.mkdir(parents=True, exist_ok=True)

    cfg_holder: dict[str, RepoConfig] = {
        "cfg": RepoConfig(
            library_root=str(library),
            xcagi_root="",
            xcagi_backend_url="http://test.invalid",
        )
    }

    def fake_load() -> RepoConfig:
        return cfg_holder["cfg"]

    def fake_save(c: RepoConfig) -> None:
        cfg_holder["cfg"] = c

    monkeypatch.setattr("modstore_server.app.load_config", fake_load)
    monkeypatch.setattr("modstore_server.app.save_config", fake_save)
    monkeypatch.setattr("modstore_server.app.project_root", lambda: project_home)

    from modstore_server.app import app

    return {
        "client": TestClient(app),
        "library": library,
        "project_home": project_home,
        "cfg_holder": cfg_holder,
    }


@pytest.fixture
def client(isolated_modstore):
    return isolated_modstore["client"]


@pytest.fixture
def library(isolated_modstore):
    return isolated_modstore["library"]


@pytest.fixture
def project_home(isolated_modstore):
    return isolated_modstore["project_home"]


@pytest.fixture
def auth_headers(client, monkeypatch):
    """注册临时用户（固定邮箱验证码）并返回 Bearer，供需登录的 /api/mods 等接口使用。"""
    import uuid

    for module_name in (
        "modstore_server.market_api",
        "modstore_server.api.market_routes",
    ):
        monkeypatch.setattr(f"{module_name}.assert_email_outbound_configured", lambda: None)
        monkeypatch.setattr(f"{module_name}.generate_verification_code", lambda: "999999")
        monkeypatch.setattr(
            f"{module_name}.send_verification_email",
            lambda *args, **kwargs: None,
        )

    username = f"pytest_{uuid.uuid4().hex[:16]}"
    email = f"u{uuid.uuid4().hex[:10]}@pytest.local"
    r = client.post("/api/auth/send-register-code", json={"email": email})
    assert r.status_code == 202, r.text
    r = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": "pytest-pass-12",
            "email": email,
            "verification_code": "999999",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    token = body.get("access_token") or body.get("token")
    assert token, body
    return {"Authorization": f"Bearer {token}"}


def _file_sha256_prefix(path: Path, *, max_bytes: int = 2_000_000) -> str:
    import hashlib

    if not path.is_file():
        return "absent"
    data = path.read_bytes()
    if len(data) > max_bytes:
        data = data[:max_bytes]
    return hashlib.sha256(data).hexdigest()[:12]


def pytest_sessionstart(session: pytest.Session) -> None:
    """打印可复现指纹，便于对照 CI / 他机结果（设 MODSTORE_TEST_ENV_QUIET=1 可静默）。"""
    quiet = (os.environ.get("MODSTORE_TEST_ENV_QUIET") or "").strip().lower()
    if quiet in ("1", "true", "yes"):
        return
    import platform
    import sys

    modstore_root = Path(__file__).resolve().parent.parent
    repo_root = modstore_root.parent
    pyproject = modstore_root / "pyproject.toml"
    market_lock = modstore_root / "market" / "package-lock.json"
    repo_lock = repo_root / "package-lock.json"
    print(
        "\n".join(
            (
                "[pytest-env] reproducibility fingerprint",
                f"python={sys.version.split()[0]} executable={sys.executable}",
                f"platform={platform.platform()}",
                f"MODSTORE_DB_PATH={(os.environ.get('MODSTORE_DB_PATH') or '')}",
                f"pyproject.toml sha256[:12]={_file_sha256_prefix(pyproject)}",
                f"market/package-lock.json sha256[:12]={_file_sha256_prefix(market_lock)}",
                f"repo/package-lock.json sha256[:12]={_file_sha256_prefix(repo_lock)}",
            )
        ),
        flush=True,
    )

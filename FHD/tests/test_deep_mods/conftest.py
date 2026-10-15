"""Real SQLite login sessions; no production or desktop user data."""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def mod_accounts(tmp_path, monkeypatch):
    import app.db as database
    import app.db.session as db_session
    from app.db.base import Base
    from app.db.models.tenant import Tenant
    from app.db.models.user import Session, User
    from app.utils.time import utc_now_naive

    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "0")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'accounts.db'}",
        connect_args={"check_same_thread": False},
    )
    sessions = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "HostSessionLocal", sessions)
    monkeypatch.setattr(db_session, "SessionLocal", sessions)
    with sessions.begin() as db:
        for uid, name, active, expires in (
            (1, "SUNBIRD", True, 1),
            (2, "OTHER", True, 1),
            (3, "DISABLED", False, 1),
            (4, "EXPIRED", True, -1),
        ):
            db.add(Tenant(id=uid, code=f"mod-owner-{uid}", name=f"Company {uid}"))
            db.add(
                User(
                    id=uid,
                    username=name,
                    password="unusable-fixture-password",
                    role="user",
                    tier="enterprise",
                    is_active=active,
                    tenant_id=uid,
                    market_user_id=100 + uid,
                )
            )
            db.add(
                Session(
                    session_id=f"mod-session-{uid}",
                    user_id=uid,
                    tenant_id=uid,
                    account_kind="enterprise",
                    market_user_id=100 + uid,
                    entitled_mod_ids_json='["taiyangniao-pro"]' if uid == 1 else "[]",
                    expires_at=utc_now_naive() + timedelta(hours=expires),
                )
            )
    yield SimpleNamespace(sessions=sessions, root=tmp_path / "workspace", engine=engine)
    engine.dispose()


@pytest.fixture
def signed_runtime_mod(tmp_path, monkeypatch, mod_accounts):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from app.infrastructure.mods import install_receipts
    from app.infrastructure.mods.package import ModPackage

    key = Ed25519PrivateKey.generate()
    secret = tmp_path / "fixture-key.pem"
    secret.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    secret.chmod(0o600)
    monkeypatch.setattr(
        "app.infrastructure.mods.trusted_keys.load_trusted_public_keys",
        lambda: [key.public_key()],
    )
    root = tmp_path / "installed-mods"
    root.mkdir()
    monkeypatch.setattr(install_receipts, "_root", lambda _mods_root: root)

    def install(
        *,
        mod_id="unknown-ui-fixture",
        version="1.0.0",
        content="export function mount() { return () => {} }",
        owner="tenant:1",
        signed=True,
        loaded=False,
        source=None,
    ):
        source = source or tmp_path / f"source-{mod_id}-{version}"
        source.mkdir(exist_ok=True)
        if not (source / "manifest.json").exists():
            manifest = {
                "id": mod_id,
                "name": "Independent UI",
                "version": version,
                "scope": "account",
                "entitlement_mod_id": "taiyangniao-pro",
                "frontend": {
                    "runtime": {
                        "sdk_version": 1,
                        "entry": "frontend/runtime/index.js",
                        "routes": [{"path": f"/mod/{mod_id}/home", "title": "Independent UI"}],
                    }
                },
            }
            (source / "manifest.json").write_text(json.dumps(manifest))
            entry = source / "frontend/runtime/index.js"
            entry.parent.mkdir(parents=True)
            entry.write_text(content)
        manifest = json.loads((source / "manifest.json").read_text())
        package = ModPackage(str(source)).create_package(
            str(tmp_path / "packages"),
            include_signature=signed,
            private_key=str(secret) if signed else None,
        )
        install_receipts.install_extracted(
            mods_root=str(root),
            extracted_root=str(source),
            manifest=manifest,
            package_path=package,
            verify_signature=signed,
            was_loaded=loaded,
            owner_scope=owner,
        )
        return root / mod_id

    return SimpleNamespace(install=install, root=root)

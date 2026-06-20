"""ButlerProfileService 集成测试 — 验证读写路径 + 模型持久化。

使用内存 SQLite + 全量 Base.metadata，不 mock 任何内部模块，验证真实 DB 行为。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.butler_identity_catalog import (
    DEFAULT_MBTI_EI,
    DEFAULT_MBTI_JP,
    DEFAULT_MBTI_SN,
    DEFAULT_MBTI_TF,
    derive_four_axes,
    derive_mbti_type,
)
from app.db.base import Base
from app.db.models.butler_profile import ButlerUserProfile
from app.db.models.user import User
from app.services.butler_profile_service import ButlerProfileService


@pytest.fixture
def service():
    """创建绑定到内存 SQLite 的 service 实例 + 测试用户。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    # 插入测试用户（满足 FK 约束）
    setup_session = SessionLocal()
    user = User(username="test_butler_user", password="dummy_hash", email="butler@test.com")
    setup_session.add(user)
    setup_session.commit()
    user_id = user.id
    setup_session.close()

    svc_session = SessionLocal()
    svc = ButlerProfileService(svc_session)
    try:
        yield svc, user_id
    finally:
        svc_session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


class TestButlerProfileServiceRead:
    """读路径测试。"""

    def test_get_active_profile_not_exists_returns_none(self, service):
        """未初始化的用户返回 None。"""
        svc, user_id = service
        assert svc.get_active_profile(user_id) is None

    def test_get_or_create_creates_default_profile(self, service):
        """新用户初始化为默认 ENFJ 管家型。"""
        svc, user_id = service
        profile = svc.get_or_create_profile(user_id)

        assert profile.user_id == user_id
        assert profile.mbti_ei == DEFAULT_MBTI_EI
        assert profile.mbti_sn == DEFAULT_MBTI_SN
        assert profile.mbti_tf == DEFAULT_MBTI_TF
        assert profile.mbti_jp == DEFAULT_MBTI_JP
        assert profile.mbti_type == "ENFJ"
        assert profile.identity_primary != ""
        assert profile.interaction_count == 0
        assert profile.mbti_confidence == 0.3

    def test_get_or_create_idempotent(self, service):
        """重复调用 get_or_create 不创建新行。"""
        svc, user_id = service
        p1 = svc.get_or_create_profile(user_id)
        p2 = svc.get_or_create_profile(user_id)
        assert p1.user_id == p2.user_id

    def test_get_profile_view_hides_mbti_raw_scores(self, service):
        """UI 视图不含 MBTI 原始分数，但含派生四轴。"""
        svc, user_id = service
        view = svc.get_profile_view(user_id)

        assert "four_axes" in view
        assert "mbti_ei" not in view
        assert "mbti_sn" not in view
        assert "mbti_tf" not in view
        assert "mbti_jp" not in view
        assert view["mbti_type"] == "ENFJ"
        axes = view["four_axes"]
        assert all(k in axes for k in ("warmth", "verbosity", "proactiveness", "structuredness"))

    def test_get_prompt_overlay_contains_identity_and_axes(self, service):
        """prompt 叠加层包含身份 + 四轴数值。"""
        svc, user_id = service
        overlay = svc.get_prompt_overlay(user_id)

        assert "个性化人设叠加" in overlay
        assert "身份：" in overlay
        assert "亲切度" in overlay
        assert "详细度" in overlay
        assert "主动度" in overlay
        assert "结构度" in overlay


class TestButlerProfileServiceWrite:
    """写路径测试。"""

    def test_record_interaction_increments_count(self, service):
        """记录互动后 interaction_count 递增。"""
        svc, user_id = service
        svc.get_or_create_profile(user_id)

        svc.record_interaction(user_id, "你好", "您好，我是管家")
        svc.record_interaction(user_id, "谢谢", "不客气")
        svc.record_interaction(user_id, "再来", "好的")

        profile = svc.get_active_profile(user_id)
        assert profile.interaction_count == 3

    def test_record_interaction_auto_creates_profile(self, service):
        """未初始化用户记录互动时自动创建 profile。"""
        svc, user_id = service
        svc.record_interaction(user_id, "首次", "您好")

        profile = svc.get_active_profile(user_id)
        assert profile is not None
        assert profile.interaction_count == 1

    def test_update_profile_changes_mbti_and_rederives_type(self, service):
        """update_profile 更新 MBTI 分数后自动重算 16 型。"""
        svc, user_id = service
        svc.get_or_create_profile(user_id)

        # 改成 ISTJ（I=20, S=30, T=25, J=20）
        updated = svc.update_profile(user_id, mbti_ei=20, mbti_sn=30, mbti_tf=25, mbti_jp=20)
        assert updated is not None
        assert updated.mbti_type == "ISTJ"

    def test_update_profile_clamps_values(self, service):
        """MBTI 分数越界时被 clamp 到 [0, 100]。"""
        svc, user_id = service
        svc.get_or_create_profile(user_id)

        updated = svc.update_profile(user_id, mbti_ei=200, mbti_sn=-50)
        assert updated.mbti_ei == 100
        assert updated.mbti_sn == 0

    def test_update_profile_refreshes_identity_vector(self, service):
        """更新 MBTI 后身份亲和度向量同步刷新。"""
        svc, user_id = service
        svc.get_or_create_profile(user_id)

        old_vector = json.loads(svc.get_active_profile(user_id).identity_vector_json)
        svc.update_profile(user_id, mbti_ei=20, mbti_sn=30, mbti_tf=25, mbti_jp=20)
        new_vector = json.loads(svc.get_active_profile(user_id).identity_vector_json)

        assert old_vector != new_vector

    def test_update_profile_nonexistent_returns_none(self, service):
        """更新不存在的用户返回 None。"""
        svc, _user_id = service
        assert svc.update_profile(99999, mbti_ei=50) is None

    def test_update_profile_confidence_clamped(self, service):
        """置信度 clamp 到 [0, 1]。"""
        svc, user_id = service
        svc.get_or_create_profile(user_id)

        updated = svc.update_profile(user_id, mbti_confidence=1.5)
        assert updated.mbti_confidence == 1.0

        updated = svc.update_profile(user_id, mbti_confidence=-0.5)
        assert updated.mbti_confidence == 0.0


class TestButlerProfileModel:
    """模型层测试。"""

    def test_to_public_dict_does_not_leak_mbti_scores(self, service):
        """to_public_dict 不泄露 MBTI 原始分数。"""
        svc, user_id = service
        profile = svc.get_or_create_profile(user_id)
        public = profile.to_public_dict()

        for key in ("mbti_ei", "mbti_sn", "mbti_tf", "mbti_jp", "identity_vector_json"):
            assert key not in public, f"public dict 不应包含 {key}"

    def test_to_internal_dict_contains_mbti_scores(self, service):
        """to_internal_dict 包含完整 MBTI 分数（供推断引擎）。"""
        svc, user_id = service
        profile = svc.get_or_create_profile(user_id)
        internal = profile.to_internal_dict()

        for key in ("mbti_ei", "mbti_sn", "mbti_tf", "mbti_jp", "mbti_type"):
            assert key in internal

    def test_four_axes_consistent_with_mbti(self, service):
        """四轴派生值与 MBTI 分数一致。"""
        svc, user_id = service
        profile = svc.get_or_create_profile(user_id)
        public = profile.to_public_dict()

        expected = derive_four_axes(
            profile.mbti_ei, profile.mbti_sn, profile.mbti_tf, profile.mbti_jp
        )
        assert public["four_axes"] == expected

    def test_default_mbti_produces_enfj(self):
        """默认 MBTI 分数派生为 ENFJ。"""
        mbti_type = derive_mbti_type(
            DEFAULT_MBTI_EI, DEFAULT_MBTI_SN, DEFAULT_MBTI_TF, DEFAULT_MBTI_JP
        )
        assert mbti_type == "ENFJ"

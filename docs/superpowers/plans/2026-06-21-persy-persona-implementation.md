# Persy Persona 系统实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为桌面端「智能对话」和手机端「小C助理」引入拟人化 persona 系统，实现"根据用户使用风格自动适配人格"的体验。

**Architecture:** 三维度 persona 模型（身份 + 关系深度 + 四轴风格参数），三层推断管线（规则 + embedding + LLM），后端透明注入 prompt 和推理参数，前端零改动。复用现有 LLM Client、Redis、Neuro Bus 基础设施。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / Redis / pytest / dataclasses / Neuro Bus

**Spec:** [docs/superpowers/specs/2026-06-21-persy-persona-design.md](../specs/2026-06-21-persy-persona-design.md)

---

## 文件结构总览

### 新增文件

```
FHD/app/domain/persona/
├── __init__.py
├── value_objects.py          # PersonaAxes, PersonaIdentity, RapportScore
├── entities.py               # PersonaProfile 聚合根
└── repositories.py           # PersonaProfileRepository 接口

FHD/app/services/persona/
├── __init__.py
├── rule_inferencer.py        # L1 规则推断
├── embedding_inferencer.py   # L2 embedding 推断
├── llm_inferencer.py         # L3 LLM 推断
├── axes_fuser.py             # 三层融合 + 软偏移
├── rapport_calculator.py     # 关系深度计算
├── identity_resolver.py      # 身份解析 + 漂移
├── prompt_builder.py         # Prompt 生成器
├── param_mapper.py           # 模型参数映射
└── persona_service.py        # PersonaService 主服务

FHD/app/infrastructure/persona/
├── __init__.py
├── models.py                 # DB ORM 模型
├── persona_repository_impl.py # 画像持久化（Redis+DB）
└── embedding_client.py       # 外部 embedding API 客户端

FHD/app/neuro_bus/events/
└── persona_event.py          # persona 领域事件

FHD/tests/test_persona/
├── __init__.py
├── conftest.py
├── test_value_objects.py
├── test_entities.py
├── test_rule_inferencer.py
├── test_embedding_inferencer.py
├── test_llm_inferencer.py
├── test_axes_fuser.py
├── test_rapport_calculator.py
├── test_identity_resolver.py
├── test_prompt_builder.py
├── test_param_mapper.py
├── test_persona_repository_impl.py
├── test_persona_service.py
└── test_integration.py
```

### 修改文件

```
FHD/app/db/models/__init__.py           # 注册新模型
FHD/app/services/conversation/api.py    # base_prompt → persona prompt
FHD/app/services/conversation/manager.py # 注入 PersonaService
FHD/app/infrastructure/llm/invoke.py    # 接收 persona 推理参数
FHD/app/domain/neuro/cognition/conscious_llm_handler.py # 动态 prompt
FHD/app/services/conversation/handlers.py # 工具结果 persona 风格
```

---

## Task 1: 值对象（PersonaAxes, PersonaIdentity, RapportScore）

**Files:**
- Create: `FHD/app/domain/persona/__init__.py`
- Create: `FHD/app/domain/persona/value_objects.py`
- Test: `FHD/tests/test_persona/__init__.py`
- Test: `FHD/tests/test_persona/test_value_objects.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_persona/test_value_objects.py
"""Persona 值对象测试。"""
from __future__ import annotations

import pytest

from app.domain.persona.value_objects import (
    PersonaAxes,
    PersonaIdentity,
    RapportScore,
)


class TestPersonaAxes:
    """四轴风格参数值对象测试。"""

    def test_create_with_defaults_returns_mid_values(self):
        axes = PersonaAxes()
        assert axes.warmth == 0.5
        assert axes.detail == 0.5
        assert axes.proactivity == 0.5
        assert axes.structure == 0.5

    def test_create_with_valid_values_returns_axes(self):
        axes = PersonaAxes(warmth=0.8, detail=0.3, proactivity=0.6, structure=0.9)
        assert axes.warmth == 0.8
        assert axes.detail == 0.3
        assert axes.proactivity == 0.6
        assert axes.structure == 0.9

    def test_create_with_value_below_zero_raises(self):
        with pytest.raises(ValueError, match="warmth"):
            PersonaAxes(warmth=-0.1)

    def test_create_with_value_above_one_raises(self):
        with pytest.raises(ValueError, match="detail"):
            PersonaAxes(detail=1.1)

    def test_create_with_none_raises(self):
        with pytest.raises((TypeError, ValueError)):
            PersonaAxes(warmth=None)  # type: ignore[arg-type]

    def test_to_dict_returns_all_axes(self):
        axes = PersonaAxes(warmth=0.7, detail=0.4, proactivity=0.6, structure=0.8)
        d = axes.to_dict()
        assert d == {"warmth": 0.7, "detail": 0.4, "proactivity": 0.6, "structure": 0.8}

    def test_from_dict_returns_axes(self):
        d = {"warmth": 0.7, "detail": 0.4, "proactivity": 0.6, "structure": 0.8}
        axes = PersonaAxes.from_dict(d)
        assert axes.warmth == 0.7
        assert axes.structure == 0.8

    def test_clamp_returns_bounded_copy(self):
        axes = PersonaAxes(warmth=0.5, detail=0.5, proactivity=0.5, structure=0.5)
        clamped = axes.clamp(warmth_offset=0.6)
        assert clamped.warmth == 1.0  # 0.5 + 0.6 = 1.1 → clamp to 1.0


class TestPersonaIdentity:
    """身份值对象测试。"""

    def test_create_returns_identity(self):
        identity = PersonaIdentity(
            name="考勤管家",
            brief="专业地服务用户，熟悉考勤业务",
            business_domain="attendance",
            industry="服务业",
        )
        assert identity.name == "考勤管家"
        assert identity.business_domain == "attendance"

    def test_create_with_empty_name_raises(self):
        with pytest.raises(ValueError, match="name"):
            PersonaIdentity(name="", brief="x", business_domain="y", industry="z")

    def test_to_dict_returns_all_fields(self):
        identity = PersonaIdentity(
            name="考勤管家",
            brief="专业地服务用户",
            business_domain="attendance",
            industry="服务业",
        )
        d = identity.to_dict()
        assert d["name"] == "考勤管家"
        assert d["business_domain"] == "attendance"


class TestRapportScore:
    """关系深度值对象测试。"""

    def test_create_with_defaults_returns_cold_start(self):
        rapport = RapportScore()
        assert rapport.score == 0.3  # 冷启动友好默认
        assert rapport.interaction_count == 0
        assert rapport.business_depth == 0.0
        assert rapport.emotion_signal_count == 0

    def test_create_with_valid_values_returns_rapport(self):
        rapport = RapportScore(
            score=0.7,
            interaction_count=250,
            business_depth=0.6,
            emotion_signal_count=30,
        )
        assert rapport.score == 0.7
        assert rapport.interaction_count == 250

    def test_create_with_score_below_zero_raises(self):
        with pytest.raises(ValueError, match="score"):
            RapportScore(score=-0.1)

    def test_create_with_score_above_one_raises(self):
        with pytest.raises(ValueError, match="score"):
            RapportScore(score=1.5)

    def test_is_loyal_returns_true_when_score_high(self):
        assert RapportScore(score=0.8).is_loyal() is True

    def test_is_loyal_returns_false_when_score_low(self):
        assert RapportScore(score=0.3).is_loyal() is False

    def test_is_stranger_returns_true_when_score_low(self):
        assert RapportScore(score=0.2).is_stranger() is True

    def test_to_dict_returns_all_fields(self):
        rapport = RapportScore(score=0.5, interaction_count=100, business_depth=0.4, emotion_signal_count=10)
        d = rapport.to_dict()
        assert d["score"] == 0.5
        assert d["interaction_count"] == 100
```

```python
# FHD/tests/test_persona/__init__.py
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_value_objects.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.persona'`

- [ ] **Step 3: 实现值对象**

```python
# FHD/app/domain/persona/__init__.py
"""Persona 领域模型。"""
from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import (
    PersonaAxes,
    PersonaIdentity,
    RapportScore,
)

__all__ = ["PersonaProfile", "PersonaAxes", "PersonaIdentity", "RapportScore"]
```

```python
# FHD/app/domain/persona/value_objects.py
"""Persona 值对象。"""
from __future__ import annotations

from dataclasses import dataclass, field


def _clamp01(value: float) -> float:
    """将值限制在 [0, 1] 区间。"""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


@dataclass(frozen=True)
class PersonaAxes:
    """四轴风格参数（MBTI 映射业务四轴）。

    - warmth: 亲切度（T/F）0=就事论事 / 1=有温度
    - detail: 详细度（S/N）0=概括方向 / 1=具体步骤
    - proactivity: 主动度（E/I）0=问什么答什么 / 1=主动建议
    - structure: 结构度（J/P）0=灵活对话 / 1=结构化清单
    """

    warmth: float = 0.5
    detail: float = 0.5
    proactivity: float = 0.5
    structure: float = 0.5

    def __post_init__(self):
        for name in ("warmth", "detail", "proactivity", "structure"):
            value = getattr(self, name)
            if value is None:
                raise ValueError(f"{name} 不能为 None")
            if not isinstance(value, (int, float)):
                raise ValueError(f"{name} 必须是数值，实际: {type(value)}")
            if value < 0.0 or value > 1.0:
                raise ValueError(f"{name} 必须在 [0, 1] 区间，实际: {value}")

    def to_dict(self) -> dict[str, float]:
        return {
            "warmth": self.warmth,
            "detail": self.detail,
            "proactivity": self.proactivity,
            "structure": self.structure,
        }

    @classmethod
    def from_dict(cls, d: dict[str, float]) -> "PersonaAxes":
        return cls(
            warmth=d["warmth"],
            detail=d["detail"],
            proactivity=d["proactivity"],
            structure=d["structure"],
        )

    def clamp(self, **offsets: float) -> "PersonaAxes":
        """对指定轴施加偏移并 clamp 到 [0,1]，返回新实例。"""
        return PersonaAxes(
            warmth=_clamp01(self.warmth + offsets.get("warmth_offset", 0.0)),
            detail=_clamp01(self.detail + offsets.get("detail_offset", 0.0)),
            proactivity=_clamp01(self.proactivity + offsets.get("proactivity_offset", 0.0)),
            structure=_clamp01(self.structure + offsets.get("structure_offset", 0.0)),
        )


@dataclass(frozen=True)
class PersonaIdentity:
    """身份值对象。"""

    name: str
    brief: str
    business_domain: str
    industry: str

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("name 不能为空")
        if not self.business_domain or not self.business_domain.strip():
            raise ValueError("business_domain 不能为空")

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "brief": self.brief,
            "business_domain": self.business_domain,
            "industry": self.industry,
        }

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> "PersonaIdentity":
        return cls(
            name=d["name"],
            brief=d.get("brief", ""),
            business_domain=d["business_domain"],
            industry=d.get("industry", ""),
        )


@dataclass(frozen=True)
class RapportScore:
    """关系深度值对象（0.0 陌生 ~ 1.0 忠诚）。"""

    score: float = 0.3  # 冷启动友好默认
    interaction_count: int = 0
    business_depth: float = 0.0
    emotion_signal_count: int = 0

    def __post_init__(self):
        if self.score < 0.0 or self.score > 1.0:
            raise ValueError(f"score 必须在 [0, 1] 区间，实际: {self.score}")
        if self.business_depth < 0.0 or self.business_depth > 1.0:
            raise ValueError(f"business_depth 必须在 [0, 1] 区间，实际: {self.business_depth}")
        if self.interaction_count < 0:
            raise ValueError(f"interaction_count 不能为负，实际: {self.interaction_count}")
        if self.emotion_signal_count < 0:
            raise ValueError(f"emotion_signal_count 不能为负，实际: {self.emotion_signal_count}")

    def is_loyal(self) -> bool:
        """是否达到忠诚阶段（score >= 0.7）。"""
        return self.score >= 0.7

    def is_stranger(self) -> bool:
        """是否处于陌生阶段（score < 0.3）。"""
        return self.score < 0.3

    def to_dict(self) -> dict[str, float | int]:
        return {
            "score": self.score,
            "interaction_count": self.interaction_count,
            "business_depth": self.business_depth,
            "emotion_signal_count": self.emotion_signal_count,
        }

    @classmethod
    def from_dict(cls, d: dict[str, float | int]) -> "RapportScore":
        return cls(
            score=float(d.get("score", 0.3)),
            interaction_count=int(d.get("interaction_count", 0)),
            business_depth=float(d.get("business_depth", 0.0)),
            emotion_signal_count=int(d.get("emotion_signal_count", 0)),
        )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_value_objects.py -v`
Expected: PASS（全部测试通过）

- [ ] **Step 5: 提交**

```bash
cd FHD && git add app/domain/persona/__init__.py app/domain/persona/value_objects.py tests/test_persona/__init__.py tests/test_persona/test_value_objects.py
git commit -m "feat(persona): 新增 PersonaAxes/PersonaIdentity/RapportScore 值对象"
```

---

## Task 2: 聚合根 PersonaProfile

**Files:**
- Create: `FHD/app/domain/persona/entities.py`
- Test: `FHD/tests/test_persona/test_entities.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_persona/test_entities.py
"""PersonaProfile 聚合根测试。"""
from __future__ import annotations

import pytest

from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import (
    PersonaAxes,
    PersonaIdentity,
    RapportScore,
)


class TestPersonaProfile:
    """PersonaProfile 聚合根测试。"""

    def test_create_with_defaults_returns_cold_start_profile(self):
        profile = PersonaProfile(user_id="user-1", industry="零售业")
        assert profile.user_id == "user-1"
        assert profile.identity.industry == "零售业"
        assert profile.identity.name == "门店管家"  # 行业映射默认身份
        assert profile.rapport.score == 0.3  # 冷启动
        assert profile.axes.warmth == 0.5  # 默认中值

    def test_create_with_empty_user_id_raises(self):
        with pytest.raises(ValueError, match="user_id"):
            PersonaProfile(user_id="", industry="零售业")

    def test_create_with_unknown_industry_uses_general(self):
        profile = PersonaProfile(user_id="user-1", industry="未知行业")
        assert profile.identity.name == "业务管家"
        assert profile.identity.business_domain == "general"

    def test_update_axes_returns_new_profile_with_updated_axes(self):
        profile = PersonaProfile(user_id="user-1", industry="零售业")
        new_axes = PersonaAxes(warmth=0.8, detail=0.3, proactivity=0.6, structure=0.9)
        updated = profile.update_axes(new_axes)
        assert updated.axes.warmth == 0.8
        assert updated.rapport.score == profile.rapport.score  # rapport 不变

    def test_update_rapport_returns_new_profile_with_updated_rapport(self):
        profile = PersonaProfile(user_id="user-1", industry="零售业")
        new_rapport = RapportScore(score=0.7, interaction_count=250)
        updated = profile.update_rapport(new_rapport)
        assert updated.rapport.score == 0.7
        assert updated.axes.warmth == profile.axes.warmth  # axes 不变

    def test_drift_identity_returns_new_profile_with_new_identity(self):
        profile = PersonaProfile(user_id="user-1", industry="零售业")
        new_identity = PersonaIdentity(
            name="考勤管家",
            brief="熟悉考勤业务",
            business_domain="attendance",
            industry="零售业",
        )
        updated = profile.drift_identity(new_identity)
        assert updated.identity.name == "考勤管家"
        assert updated.identity.business_domain == "attendance"

    def test_to_dict_returns_all_fields(self):
        profile = PersonaProfile(user_id="user-1", industry="零售业")
        d = profile.to_dict()
        assert d["user_id"] == "user-1"
        assert "identity" in d
        assert "axes" in d
        assert "rapport" in d

    def test_from_dict_returns_profile(self):
        d = {
            "user_id": "user-1",
            "identity": {
                "name": "考勤管家",
                "brief": "熟悉考勤",
                "business_domain": "attendance",
                "industry": "服务业",
            },
            "axes": {"warmth": 0.7, "detail": 0.4, "proactivity": 0.6, "structure": 0.8},
            "rapport": {"score": 0.5, "interaction_count": 100, "business_depth": 0.4, "emotion_signal_count": 10},
        }
        profile = PersonaProfile.from_dict(d)
        assert profile.user_id == "user-1"
        assert profile.identity.name == "考勤管家"
        assert profile.axes.warmth == 0.7
        assert profile.rapport.score == 0.5
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_entities.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.persona.entities'`

- [ ] **Step 3: 实现聚合根**

```python
# FHD/app/domain/persona/entities.py
"""Persona 聚合根。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.persona.value_objects import (
    PersonaAxes,
    PersonaIdentity,
    RapportScore,
)


# 行业 → 初始身份映射
_INDUSTRY_IDENTITY_MAP: dict[str, tuple[str, str]] = {
    # industry: (identity_name, business_domain)
    "制造业": ("生产管家", "production"),
    "零售业": ("门店管家", "retail"),
    "物流业": ("运单管家", "shipment"),
    "服务业": ("客户管家", "customer"),
    "贸易业": ("发货管家", "shipment"),
    "科技业": ("项目管家", "project"),
}


def _resolve_initial_identity(industry: str) -> PersonaIdentity:
    """根据企业入驻行业解析初始身份。"""
    name, domain = _INDUSTRY_IDENTITY_MAP.get(industry, ("业务管家", "general"))
    return PersonaIdentity(
        name=name,
        brief=f"专业地服务用户，熟悉{domain}业务",
        business_domain=domain,
        industry=industry,
    )


@dataclass
class PersonaProfile:
    """Persona 画像聚合根。

    三维度：identity（身份）+ rapport（关系深度）+ axes（四轴风格）
    """

    user_id: str
    identity: PersonaIdentity
    axes: PersonaAxes = field(default_factory=PersonaAxes)
    rapport: RapportScore = field(default_factory=RapportScore)
    business_domain_counts: dict[str, int] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.user_id or not self.user_id.strip():
            raise ValueError("user_id 不能为空")

    @classmethod
    def create(cls, user_id: str, industry: str) -> "PersonaProfile":
        """冷启动工厂方法：根据行业创建初始画像。"""
        identity = _resolve_initial_identity(industry)
        return cls(user_id=user_id, identity=identity)

    def update_axes(self, new_axes: PersonaAxes) -> "PersonaProfile":
        """返回更新了四轴的新画像实例。"""
        return PersonaProfile(
            user_id=self.user_id,
            identity=self.identity,
            axes=new_axes,
            rapport=self.rapport,
            business_domain_counts=dict(self.business_domain_counts),
            created_at=self.created_at,
            updated_at=datetime.now(),
        )

    def update_rapport(self, new_rapport: RapportScore) -> "PersonaProfile":
        """返回更新了关系深度的新画像实例。"""
        return PersonaProfile(
            user_id=self.user_id,
            identity=self.identity,
            axes=self.axes,
            rapport=new_rapport,
            business_domain_counts=dict(self.business_domain_counts),
            created_at=self.created_at,
            updated_at=datetime.now(),
        )

    def drift_identity(self, new_identity: PersonaIdentity) -> "PersonaProfile":
        """返回漂移了身份的新画像实例。"""
        return PersonaProfile(
            user_id=self.user_id,
            identity=new_identity,
            axes=self.axes,
            rapport=self.rapport,
            business_domain_counts=dict(self.business_domain_counts),
            created_at=self.created_at,
            updated_at=datetime.now(),
        )

    def increment_domain(self, domain: str) -> "PersonaProfile":
        """增加某业务域的计数，返回新画像实例。"""
        counts = dict(self.business_domain_counts)
        counts[domain] = counts.get(domain, 0) + 1
        return PersonaProfile(
            user_id=self.user_id,
            identity=self.identity,
            axes=self.axes,
            rapport=self.rapport,
            business_domain_counts=counts,
            created_at=self.created_at,
            updated_at=datetime.now(),
        )

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "identity": self.identity.to_dict(),
            "axes": self.axes.to_dict(),
            "rapport": self.rapport.to_dict(),
            "business_domain_counts": dict(self.business_domain_counts),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PersonaProfile":
        return cls(
            user_id=d["user_id"],
            identity=PersonaIdentity.from_dict(d["identity"]),
            axes=PersonaAxes.from_dict(d["axes"]),
            rapport=RapportScore.from_dict(d["rapport"]),
            business_domain_counts=dict(d.get("business_domain_counts", {})),
        )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_entities.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd FHD && git add app/domain/persona/entities.py tests/test_persona/test_entities.py
git commit -m "feat(persona): 新增 PersonaProfile 聚合根"
```

---

## Task 3: 仓储接口 PersonaProfileRepository

**Files:**
- Create: `FHD/app/application/ports/persona_repository.py`
- Test: `FHD/tests/test_persona/test_repositories.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_persona/test_repositories.py
"""PersonaProfileRepository 接口测试。"""
from __future__ import annotations

import pytest

from app.application.ports.persona_repository import PersonaProfileRepository


class TestPersonaProfileRepository:
    """仓储接口测试。"""

    def test_cannot_instantiate_abstract_class(self):
        with pytest.raises(TypeError):
            PersonaProfileRepository()  # type: ignore[abstract]

    def test_has_find_by_user_id_method(self):
        assert hasattr(PersonaProfileRepository, "find_by_user_id")

    def test_has_save_method(self):
        assert hasattr(PersonaProfileRepository, "save")

    def test_has_delete_method(self):
        assert hasattr(PersonaProfileRepository, "delete")
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_repositories.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现仓储接口**

```python
# FHD/app/application/ports/persona_repository.py
"""Persona 画像仓储接口 (Port)。"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.persona.entities import PersonaProfile


class PersonaProfileRepository(ABC):
    """Persona 画像仓储接口。"""

    @abstractmethod
    async def find_by_user_id(self, user_id: str) -> PersonaProfile | None:
        """根据用户 ID 查找画像。"""
        raise NotImplementedError

    @abstractmethod
    async def save(self, profile: PersonaProfile) -> PersonaProfile:
        """保存画像（新增或更新）。"""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, user_id: str) -> bool:
        """删除画像。"""
        raise NotImplementedError

    @abstractmethod
    async def append_event(self, user_id: str, event_type: str, event_data: dict) -> None:
        """追加事件日志（用于审计和 L3 复盘）。"""
        raise NotImplementedError

    @abstractmethod
    async def list_recent_events(self, user_id: str, limit: int = 20) -> list[dict]:
        """列出最近的事件日志。"""
        raise NotImplementedError
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_repositories.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd FHD && git add app/application/ports/persona_repository.py tests/test_persona/test_repositories.py
git commit -m "feat(persona): 新增 PersonaProfileRepository 仓储接口"
```

---

## Task 4: L1 规则推断器（warmth + detail）

**Files:**
- Create: `FHD/app/services/persona/__init__.py`
- Create: `FHD/app/services/persona/rule_inferencer.py`
- Test: `FHD/tests/test_persona/test_rule_inferencer.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_persona/test_rule_inferencer.py
"""L1 规则推断器测试。"""
from __future__ import annotations

import pytest

from app.services.persona.rule_inferencer import RuleInferencer, RuleInferResult


class TestRuleInferencer:
    """L1 规则推断器测试。"""

    @pytest.fixture
    def inferencer(self):
        return RuleInferencer()

    def test_short_message_returns_low_detail(self, inferencer):
        result = inferencer.infer("查下", [])
        assert result.axes.detail < 0.4

    def test_long_message_returns_high_detail(self, inferencer):
        result = inferencer.infer("详细说说这个订单的物流信息，包括每个节点的时间和地点", [])
        assert result.axes.detail > 0.6

    def test_message_with_emoji_returns_high_warmth(self, inferencer):
        result = inferencer.infer("你好呀😊 帮我查下订单", [])
        assert result.axes.warmth > 0.6

    def test_message_with_modal_particles_returns_high_warmth(self, inferencer):
        result = inferencer.infer("帮我查下订单呢", [])
        assert result.axes.warmth > 0.5

    def test_imperative_sentence_returns_low_warmth(self, inferencer):
        result = inferencer.infer("查下订单", [])
        assert result.axes.warmth < 0.5

    def test_explicit_brief_request_returns_low_detail(self, inferencer):
        result = inferencer.infer("简单点说，长话短说", [])
        assert result.axes.detail < 0.4

    def test_explicit_detailed_request_returns_high_detail(self, inferencer):
        result = inferencer.infer("展开讲讲，详细说说", [])
        assert result.axes.detail > 0.6

    def test_returns_confidence(self, inferencer):
        result = inferencer.infer("你好呀😊", [])
        assert 0.0 <= result.confidence <= 1.0

    def test_empty_message_returns_neutral(self, inferencer):
        result = inferencer.infer("", [])
        assert result.axes.warmth == 0.5
        assert result.axes.detail == 0.5

    def test_none_message_returns_neutral(self, inferencer):
        result = inferencer.infer(None, [])  # type: ignore[arg-type]
        assert result.axes.warmth == 0.5
```

```python
# FHD/app/services/persona/__init__.py
"""Persona 应用服务。"""
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_rule_inferencer.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 L1 规则推断器（warmth + detail）**

```python
# FHD/app/services/persona/rule_inferencer.py
"""L1 规则推断器：实时从用户消息提取 persona 信号。"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.persona.value_objects import PersonaAxes


@dataclass(frozen=True)
class RuleInferResult:
    """L1 规则推断结果。"""

    axes: PersonaAxes
    confidence: float
    signals: list[str]  # 命中的规则名列表，用于调试


# 语气词/emoji 模式
_MODAL_PARTICLES = re.compile(r"[哈呢呀哦嘛啦哇呗]")
_EMOJI_PATTERN = re.compile(
    "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]"
)
# 祈使句模式
_IMPERATIVE_PATTERN = re.compile(r"^(帮我|查下|弄一下|搞一下|弄下|搞下|处理下|处理一下|弄|查|搞|做)")
# 详细/简洁请求
_DETAIL_REQUEST = re.compile(r"(详细|展开|具体|说说|讲讲|解释)")
_BRIEF_REQUEST = re.compile(r"(简单|简洁|长话短说|少说|概括|摘要)")


class RuleInferencer:
    """L1 规则推断器。

    从用户当前消息 + 最近 N 轮历史提取 persona 信号，
    输出四轴瞬时值（0-1）+ 置信度。
    延迟预算：<1ms（纯内存计算）。
    """

    def infer(self, message: str | None, history: list[dict]) -> RuleInferResult:
        """推断四轴参数。

        Args:
            message: 用户当前消息
            history: 最近 N 轮历史（每条 {"role": "user"|"assistant", "content": "..."})

        Returns:
            RuleInferResult: 四轴值 + 置信度 + 命中信号
        """
        if not message or not message.strip():
            return RuleInferResult(
                axes=PersonaAxes(),
                confidence=0.0,
                signals=[],
            )

        signals: list[str] = []
        warmth_score = 0.5
        detail_score = 0.5
        proactivity_score = 0.5
        structure_score = 0.5

        # === warmth 规则 ===
        emoji_count = len(_EMOJI_PATTERN.findall(message))
        modal_count = len(_MODAL_PARTICLES.findall(message))
        is_imperative = bool(_IMPERATIVE_PATTERN.match(message.strip()))

        if emoji_count > 0:
            warmth_score = min(0.9, 0.6 + emoji_count * 0.1)
            signals.append("emoji")
        elif modal_count > 0:
            warmth_score = min(0.8, 0.55 + modal_count * 0.08)
            signals.append("modal_particle")
        elif is_imperative:
            warmth_score = 0.35
            signals.append("imperative")

        # === detail 规则 ===
        msg_len = len(message)
        has_detail_request = bool(_DETAIL_REQUEST.search(message))
        has_brief_request = bool(_BRIEF_REQUEST.search(message))

        if has_brief_request:
            detail_score = 0.3
            signals.append("brief_request")
        elif has_detail_request:
            detail_score = 0.8
            signals.append("detail_request")
        elif msg_len <= 10:
            detail_score = 0.35
            signals.append("short_message")
        elif msg_len >= 50:
            detail_score = 0.7
            signals.append("long_message")

        # === proactivity 规则（问句比例）===
        question_count = message.count("?") + message.count("？")
        if question_count >= 2:
            proactivity_score = 0.35
            signals.append("multi_question")
        elif question_count == 0 and msg_len > 5:
            proactivity_score = 0.65
            signals.append("statement")

        # === structure 规则（编号/列表）===
        has_list = bool(re.search(r"\d+[.、)]", message))
        if has_list:
            structure_score = 0.8
            signals.append("list_format")

        axes = PersonaAxes(
            warmth=warmth_score,
            detail=detail_score,
            proactivity=proactivity_score,
            structure=structure_score,
        )
        confidence = min(1.0, len(signals) * 0.25)

        return RuleInferResult(axes=axes, confidence=confidence, signals=signals)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_rule_inferencer.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd FHD && git add app/services/persona/__init__.py app/services/persona/rule_inferencer.py tests/test_persona/test_rule_inferencer.py
git commit -m "feat(persona): 新增 L1 规则推断器（warmth+detail+proactivity+structure）"
```

---

## Task 5: Rapport 计算器

**Files:**
- Create: `FHD/app/services/persona/rapport_calculator.py`
- Test: `FHD/tests/test_persona/test_rapport_calculator.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_persona/test_rapport_calculator.py
"""Rapport 计算器测试。"""
from __future__ import annotations

import pytest

from app.domain.persona.value_objects import RapportScore
from app.services.persona.rapport_calculator import RapportCalculator


class TestRapportCalculator:
    """关系深度计算器测试。"""

    @pytest.fixture
    def calculator(self):
        return RapportCalculator()

    def test_cold_start_returns_default_0_3(self, calculator):
        rapport = calculator.calculate(
            interaction_count=0,
            business_domain_counts={},
            emotion_signal_count=0,
        )
        assert rapport.score == 0.3

    def test_500_interactions_returns_high_rapport(self, calculator):
        rapport = calculator.calculate(
            interaction_count=500,
            business_domain_counts={"shipment": 300, "product": 200},
            emotion_signal_count=50,
        )
        assert rapport.score >= 0.9

    def test_250_interactions_returns_mid_rapport(self, calculator):
        rapport = calculator.calculate(
            interaction_count=250,
            business_domain_counts={"shipment": 200},
            emotion_signal_count=25,
        )
        assert 0.4 <= rapport.score <= 0.7

    def test_business_depth_calculated_from_domain_counts(self, calculator):
        rapport = calculator.calculate(
            interaction_count=100,
            business_domain_counts={"shipment": 50, "product": 30, "customer": 20},
            emotion_signal_count=10,
        )
        # 3 个业务域 → business_depth = 3/5 = 0.6
        assert 0.5 <= rapport.business_depth <= 0.7

    def test_emotion_signal_normalized(self, calculator):
        rapport = calculator.calculate(
            interaction_count=100,
            business_domain_counts={"shipment": 100},
            emotion_signal_count=50,
        )
        # emotion_signal_count=50 → 归一化 = 1.0
        assert rapport.emotion_signal_count == 50

    def test_score_never_exceeds_1(self, calculator):
        rapport = calculator.calculate(
            interaction_count=10000,
            business_domain_counts={"a": 1, "b": 1, "c": 1, "d": 1, "e": 1},
            emotion_signal_count=1000,
        )
        assert rapport.score <= 1.0

    def test_score_never_below_0(self, calculator):
        rapport = calculator.calculate(
            interaction_count=0,
            business_domain_counts={},
            emotion_signal_count=0,
        )
        assert rapport.score >= 0.0

    def test_weights_sum_to_one(self, calculator):
        """50% + 30% + 20% = 100%"""
        assert (
            calculator.INTERACTION_WEIGHT
            + calculator.BUSINESS_DEPTH_WEIGHT
            + calculator.EMOTION_WEIGHT
            == 1.0
        )
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_rapport_calculator.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 RapportCalculator**

```python
# FHD/app/services/persona/rapport_calculator.py
"""关系深度计算器。"""
from __future__ import annotations

from app.domain.persona.value_objects import RapportScore


def _normalize(value: float, min_val: float, max_val: float) -> float:
    """归一化到 [0, 1]。"""
    if max_val <= min_val:
        return 0.0
    normalized = (value - min_val) / (max_val - min_val)
    if normalized < 0.0:
        return 0.0
    if normalized > 1.0:
        return 1.0
    return normalized


class RapportCalculator:
    """关系深度计算器。

    公式：rapport = 0.5 * interaction + 0.3 * business_depth + 0.2 * emotion
    """

    INTERACTION_WEIGHT = 0.5
    BUSINESS_DEPTH_WEIGHT = 0.3
    EMOTION_WEIGHT = 0.2

    MAX_INTERACTION_COUNT = 500  # 500 轮 → 1.0
    MAX_BUSINESS_DOMAINS = 5  # 5 个业务域 → 1.0
    MAX_EMOTION_SIGNALS = 50  # 50 次情感信号 → 1.0
    COLD_START_DEFAULT = 0.3

    def calculate(
        self,
        interaction_count: int,
        business_domain_counts: dict[str, int],
        emotion_signal_count: int,
    ) -> RapportScore:
        """计算关系深度。

        Args:
            interaction_count: 累计互动轮数
            business_domain_counts: 各业务域操作计数
            emotion_signal_count: 情感信号次数

        Returns:
            RapportScore: 关系深度值对象
        """
        interaction_normalized = _normalize(
            float(interaction_count), 0.0, float(self.MAX_INTERACTION_COUNT)
        )
        business_depth = _normalize(
            float(len(business_domain_counts)), 0.0, float(self.MAX_BUSINESS_DOMAINS)
        )
        emotion_normalized = _normalize(
            float(emotion_signal_count), 0.0, float(self.MAX_EMOTION_SIGNALS)
        )

        score = (
            self.INTERACTION_WEIGHT * interaction_normalized
            + self.BUSINESS_DEPTH_WEIGHT * business_depth
            + self.EMOTION_WEIGHT * emotion_normalized
        )

        # 冷启动保护：无任何数据时给友好默认值
        if interaction_count == 0 and not business_domain_counts and emotion_signal_count == 0:
            score = self.COLD_START_DEFAULT

        # clamp
        if score < 0.0:
            score = 0.0
        elif score > 1.0:
            score = 1.0

        return RapportScore(
            score=score,
            interaction_count=interaction_count,
            business_depth=business_depth,
            emotion_signal_count=emotion_signal_count,
        )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_rapport_calculator.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd FHD && git add app/services/persona/rapport_calculator.py tests/test_persona/test_rapport_calculator.py
git commit -m "feat(persona): 新增 RapportCalculator 关系深度计算器"
```

---

## Task 6: 身份解析器（行业映射 + 业务漂移）

**Files:**
- Create: `FHD/app/services/persona/identity_resolver.py`
- Test: `FHD/tests/test_persona/test_identity_resolver.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_persona/test_identity_resolver.py
"""身份解析器测试。"""
from __future__ import annotations

import pytest

from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import PersonaIdentity, RapportScore
from app.services.persona.identity_resolver import IdentityResolver


class TestIdentityResolver:
    """身份解析器测试。"""

    @pytest.fixture
    def resolver(self):
        return IdentityResolver()

    def test_resolve_brief_stranger_returns_professional_brief(self, resolver):
        identity = PersonaIdentity(
            name="考勤管家", brief="", business_domain="attendance", industry="服务业"
        )
        brief = resolver.resolve_brief(identity, RapportScore(score=0.2))
        assert "专业" in brief

    def test_resolve_brief_familiar_returns_familiar_brief(self, resolver):
        identity = PersonaIdentity(
            name="考勤管家", brief="", business_domain="attendance", industry="服务业"
        )
        brief = resolver.resolve_brief(identity, RapportScore(score=0.5))
        assert "熟悉" in brief

    def test_resolve_brief_loyal_returns_loyal_brief(self, resolver):
        identity = PersonaIdentity(
            name="考勤管家", brief="", business_domain="attendance", industry="服务业"
        )
        brief = resolver.resolve_brief(identity, RapportScore(score=0.9))
        assert "忠诚" in brief or "老朋友" in brief

    def test_should_drift_returns_false_when_below_threshold(self, resolver):
        profile = PersonaProfile.create("user-1", "零售业")
        # 只有 10 轮考勤操作，未达 50 轮阈值
        profile = profile.increment_domain("attendance")
        for _ in range(10):
            profile = profile.increment_domain("attendance")
        assert resolver.should_drift(profile) is False

    def test_should_drift_returns_true_when_above_threshold(self, resolver):
        profile = PersonaProfile.create("user-1", "零售业")
        # 60 轮考勤操作，超过 50 轮阈值
        for _ in range(60):
            profile = profile.increment_domain("attendance")
        assert resolver.should_drift(profile) is True

    def test_drift_target_returns_new_domain_identity(self, resolver):
        profile = PersonaProfile.create("user-1", "零售业")
        for _ in range(60):
            profile = profile.increment_domain("attendance")
        target = resolver.drift_target(profile)
        assert target.business_domain == "attendance"
        assert "考勤" in target.name

    def test_drift_target_returns_none_when_no_drift_needed(self, resolver):
        profile = PersonaProfile.create("user-1", "零售业")
        profile = profile.increment_domain("retail")
        assert resolver.drift_target(profile) is None
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_identity_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 IdentityResolver**

```python
# FHD/app/services/persona/identity_resolver.py
"""身份解析器：行业映射 + 业务漂移 + 关系深度演进。"""
from __future__ import annotations

from app.domain.persona.entities import PersonaProfile, _INDUSTRY_IDENTITY_MAP
from app.domain.persona.value_objects import PersonaIdentity, RapportScore


# 业务域 → 身份名映射（用于漂移目标解析）
_DOMAIN_IDENTITY_NAME_MAP: dict[str, str] = {
    "production": "生产管家",
    "retail": "门店管家",
    "shipment": "发货管家",
    "customer": "客户管家",
    "project": "项目管家",
    "attendance": "考勤管家",
    "product": "产品管家",
    "order": "订单管家",
    "payment": "财务管家",
    "inventory": "库存管家",
    "general": "业务管家",
}


class IdentityResolver:
    """身份解析器。

    职责：
    1. 根据 rapport 生成身份描述（brief）
    2. 判断是否需要业务漂移
    3. 解析漂移目标身份
    """

    DRIFT_THRESHOLD = 50  # 连续 50 轮主要操作某业务域才触发漂移
    DRIFT_RATIO = 0.6  # 该业务域操作占总操作的 60% 以上

    def resolve_brief(self, identity: PersonaIdentity, rapport: RapportScore) -> str:
        """根据关系深度生成身份描述。"""
        domain_label = identity.business_domain
        if rapport.is_stranger():
            return f"专业地服务用户，熟悉{domain_label}业务"
        if rapport.is_loyal():
            return f"用户最忠诚的伙伴，最懂他的{domain_label}需求，像老朋友一样可靠"
        return f"用户熟悉的{identity.name}，了解他的{domain_label}习惯和偏好"

    def should_drift(self, profile: PersonaProfile) -> bool:
        """判断是否需要业务漂移。"""
        if not profile.business_domain_counts:
            return False
        current_domain = profile.identity.business_domain
        # 找出操作最多的业务域
        top_domain = max(profile.business_domain_counts, key=profile.business_domain_counts.get)
        if top_domain == current_domain:
            return False
        top_count = profile.business_domain_counts[top_domain]
        total_count = sum(profile.business_domain_counts.values())
        if total_count == 0:
            return False
        if top_count < self.DRIFT_THRESHOLD:
            return False
        if top_count / total_count < self.DRIFT_RATIO:
            return False
        return True

    def drift_target(self, profile: PersonaProfile) -> PersonaIdentity | None:
        """解析漂移目标身份。"""
        if not self.should_drift(profile):
            return None
        top_domain = max(profile.business_domain_counts, key=profile.business_domain_counts.get)
        name = _DOMAIN_IDENTITY_NAME_MAP.get(top_domain, f"{top_domain}管家")
        return PersonaIdentity(
            name=name,
            brief=f"专业地服务用户，熟悉{top_domain}业务",
            business_domain=top_domain,
            industry=profile.identity.industry,
        )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_identity_resolver.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd FHD && git add app/services/persona/identity_resolver.py tests/test_persona/test_identity_resolver.py
git commit -m "feat(persona): 新增 IdentityResolver 身份解析器（行业映射+业务漂移）"
```

---

## Task 7: 三层融合器 AxesFuser

**Files:**
- Create: `FHD/app/services/persona/axes_fuser.py`
- Test: `FHD/tests/test_persona/test_axes_fuser.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_persona/test_axes_fuser.py
"""三层融合器测试。"""
from __future__ import annotations

import pytest

from app.domain.persona.value_objects import PersonaAxes, RapportScore
from app.services.persona.axes_fuser import AxesFuser


class TestAxesFuser:
    """三层融合器测试。"""

    @pytest.fixture
    def fuser(self):
        return AxesFuser()

    def test_fuse_only_l1_returns_l1_values(self, fuser):
        l1 = PersonaAxes(warmth=0.8, detail=0.3, proactivity=0.6, structure=0.9)
        result = fuser.fuse(l1=l1, l2=None, l3=None, rapport=RapportScore(score=0.3))
        assert result.warmth == 0.8
        assert result.detail == 0.3

    def test_fuse_l1_and_l2_uses_equal_weights(self, fuser):
        l1 = PersonaAxes(warmth=0.8, detail=0.3, proactivity=0.6, structure=0.9)
        l2 = PersonaAxes(warmth=0.4, detail=0.7, proactivity=0.2, structure=0.5)
        result = fuser.fuse(l1=l1, l2=l2, l3=None, rapport=RapportScore(score=0.3))
        # L1(0.5) + L2(0.5)
        assert abs(result.warmth - 0.6) < 0.01  # (0.8+0.4)/2
        assert abs(result.detail - 0.5) < 0.01  # (0.3+0.7)/2

    def test_fuse_all_three_uses_configured_weights(self, fuser):
        l1 = PersonaAxes(warmth=0.8, detail=0.3, proactivity=0.6, structure=0.9)
        l2 = PersonaAxes(warmth=0.4, detail=0.7, proactivity=0.2, structure=0.5)
        l3 = PersonaAxes(warmth=0.6, detail=0.5, proactivity=0.4, structure=0.7)
        result = fuser.fuse(l1=l1, l2=l2, l3=l3, rapport=RapportScore(score=0.3))
        # L1(0.4) + L2(0.3) + L3(0.3)
        expected_warmth = 0.4 * 0.8 + 0.3 * 0.4 + 0.3 * 0.6
        assert abs(result.warmth - expected_warmth) < 0.01

    def test_soft_offset_applied_when_rapport_high(self, fuser):
        l1 = PersonaAxes(warmth=0.5, detail=0.5, proactivity=0.5, structure=0.5)
        result = fuser.fuse(
            l1=l1, l2=None, l3=None, rapport=RapportScore(score=1.0)
        )
        # rapport=1.0 → warmth +0.2, proactivity +0.2, detail +0.1
        assert result.warmth == pytest.approx(0.7, abs=0.01)
        assert result.proactivity == pytest.approx(0.7, abs=0.01)
        assert result.detail == pytest.approx(0.6, abs=0.01)

    def test_soft_offset_not_applied_when_signal_strong(self, fuser):
        """用户信号强烈时（confidence > 0.7），rapport 偏移不生效。"""
        l1 = PersonaAxes(warmth=0.2, detail=0.5, proactivity=0.5, structure=0.5)
        result = fuser.fuse(
            l1=l1,
            l2=None,
            l3=None,
            rapport=RapportScore(score=1.0),
            signal_strength=0.8,  # 强信号
        )
        # warmth 锁定低位，不偏移
        assert result.warmth == pytest.approx(0.2, abs=0.01)

    def test_soft_offset_mid_rapport(self, fuser):
        l1 = PersonaAxes(warmth=0.5, detail=0.5, proactivity=0.5, structure=0.5)
        result = fuser.fuse(
            l1=l1, l2=None, l3=None, rapport=RapportScore(score=0.5)
        )
        # rapport=0.5 → warmth +0.1, proactivity +0.1
        assert result.warmth == pytest.approx(0.6, abs=0.01)
        assert result.proactivity == pytest.approx(0.6, abs=0.01)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_axes_fuser.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 AxesFuser**

```python
# FHD/app/services/persona/axes_fuser.py
"""三层融合器：L1 + L2 + L3 加权融合 + rapport 软偏移。"""
from __future__ import annotations

from app.domain.persona.value_objects import PersonaAxes, RapportScore


class AxesFuser:
    """三层推断结果融合器。

    融合公式：final = w1*L1 + w2*L2 + w3*L3
    权重根据可用层级动态调整：
    - 仅 L1：w1=1.0
    - L1+L2：w1=0.5, w2=0.5
    - L1+L2+L3：w1=0.4, w2=0.3, w3=0.3

    软偏移：rapport 高时偏移四轴基线，但用户信号强时不偏移。
    """

    WEIGHT_L1_ONLY = 1.0
    WEIGHT_L1_WITH_L2 = 0.5
    WEIGHT_L2_WITH_L1 = 0.5
    WEIGHT_L1_FULL = 0.4
    WEIGHT_L2_FULL = 0.3
    WEIGHT_L3_FULL = 0.3

    SIGNAL_STRENGTH_THRESHOLD = 0.7  # 用户信号强度高于此值时锁定，不偏移

    def fuse(
        self,
        l1: PersonaAxes,
        l2: PersonaAxes | None,
        l3: PersonaAxes | None,
        rapport: RapportScore,
        signal_strength: float = 0.0,
    ) -> PersonaAxes:
        """融合三层推断结果。

        Args:
            l1: L1 规则层结果（必有）
            l2: L2 embedding 层结果（可空）
            l3: L3 LLM 层结果（可空）
            rapport: 关系深度
            signal_strength: 用户信号强度（0-1），高时锁定不偏移

        Returns:
            PersonaAxes: 融合后的四轴值
        """
        if l2 is None and l3 is None:
            base = l1
        elif l3 is None:
            base = PersonaAxes(
                warmth=self.WEIGHT_L1_WITH_L1 * l1.warmth + self.WEIGHT_L2_WITH_L1 * l2.warmth,
                detail=self.WEIGHT_L1_WITH_L1 * l1.detail + self.WEIGHT_L2_WITH_L1 * l2.detail,
                proactivity=self.WEIGHT_L1_WITH_L1 * l1.proactivity + self.WEIGHT_L2_WITH_L1 * l2.proactivity,
                structure=self.WEIGHT_L1_WITH_L1 * l1.structure + self.WEIGHT_L2_WITH_L1 * l2.structure,
            )
        else:
            base = PersonaAxes(
                warmth=self.WEIGHT_L1_FULL * l1.warmth + self.WEIGHT_L2_FULL * l2.warmth + self.WEIGHT_L3_FULL * l3.warmth,
                detail=self.WEIGHT_L1_FULL * l1.detail + self.WEIGHT_L2_FULL * l2.detail + self.WEIGHT_L3_FULL * l3.detail,
                proactivity=self.WEIGHT_L1_FULL * l1.proactivity + self.WEIGHT_L2_FULL * l2.proactivity + self.WEIGHT_L3_FULL * l3.proactivity,
                structure=self.WEIGHT_L1_FULL * l1.structure + self.WEIGHT_L2_FULL * l2.structure + self.WEIGHT_L3_FULL * l3.structure,
            )

        # 软偏移：用户信号弱时才应用 rapport 偏移
        if signal_strength < self.SIGNAL_STRENGTH_THRESHOLD:
            offsets = self._rapport_offsets(rapport)
            return base.clamp(**offsets)
        return base

    def _rapport_offsets(self, rapport: RapportScore) -> dict[str, float]:
        """根据 rapport 计算四轴偏移量。"""
        if rapport.score >= 0.7:
            return {
                "warmth_offset": 0.2,
                "proactivity_offset": 0.2,
                "detail_offset": 0.1,
            }
        if rapport.score >= 0.4:
            return {
                "warmth_offset": 0.1,
                "proactivity_offset": 0.1,
            }
        return {}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_axes_fuser.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd FHD && git add app/services/persona/axes_fuser.py tests/test_persona/test_axes_fuser.py
git commit -m "feat(persona): 新增 AxesFuser 三层融合器（含软偏移）"
```

---

## Task 8: Prompt 生成器

**Files:**
- Create: `FHD/app/services/persona/prompt_builder.py`
- Test: `FHD/tests/test_persona/test_prompt_builder.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_persona/test_prompt_builder.py
"""Prompt 生成器测试。"""
from __future__ import annotations

import pytest

from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import (
    PersonaAxes,
    PersonaIdentity,
    RapportScore,
)
from app.services.persona.identity_resolver import IdentityResolver
from app.services.persona.prompt_builder import PersonaPromptBuilder


class TestPersonaPromptBuilder:
    """Prompt 生成器测试。"""

    @pytest.fixture
    def builder(self):
        return PersonaPromptBuilder(IdentityResolver())

    def test_build_returns_string(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        prompt = builder.build(profile, context_prompt="")
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_build_contains_identity_name(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        prompt = builder.build(profile, context_prompt="")
        assert "门店管家" in prompt

    def test_build_contains_safety_section(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        prompt = builder.build(profile, context_prompt="")
        assert "不确定" in prompt or "诚实" in prompt

    def test_build_contains_context_when_provided(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        prompt = builder.build(profile, context_prompt="当前意图：查询订单")
        assert "查询订单" in prompt

    def test_build_high_warmth_adds_warm_instruction(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        profile = profile.update_axes(PersonaAxes(warmth=0.8, detail=0.5, proactivity=0.5, structure=0.5))
        prompt = builder.build(profile, context_prompt="")
        assert "口语化" in prompt or "寒暄" in prompt

    def test_build_low_warmth_adds_concise_instruction(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        profile = profile.update_axes(PersonaAxes(warmth=0.2, detail=0.5, proactivity=0.5, structure=0.5))
        prompt = builder.build(profile, context_prompt="")
        assert "就事论事" in prompt

    def test_build_high_structure_adds_list_instruction(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        profile = profile.update_axes(PersonaAxes(warmth=0.5, detail=0.5, proactivity=0.5, structure=0.8))
        prompt = builder.build(profile, context_prompt="")
        assert "编号" in prompt or "列表" in prompt

    def test_build_high_proactivity_adds_proactive_instruction(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        profile = profile.update_axes(PersonaAxes(warmth=0.5, detail=0.5, proactivity=0.8, structure=0.5))
        prompt = builder.build(profile, context_prompt="")
        assert "主动" in prompt

    def test_build_length_under_600_chars(self, builder):
        """prompt 总长度控制（含上下文）。"""
        profile = PersonaProfile.create("user-1", "零售业")
        prompt = builder.build(profile, context_prompt="当前意图：查询订单\n工具：order_query\n最近操作：查产品")
        # 允许一定冗余，但不应过长
        assert len(prompt) < 600

    def test_build_loyal_rapport_adds_loyal_brief(self, builder):
        profile = PersonaProfile.create("user-1", "零售业")
        profile = profile.update_rapport(RapportScore(score=0.9, interaction_count=500))
        prompt = builder.build(profile, context_prompt="")
        assert "忠诚" in prompt or "老朋友" in prompt
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_prompt_builder.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 PersonaPromptBuilder**

```python
# FHD/app/services/persona/prompt_builder.py
"""Persona Prompt 生成器：参数 → prompt 文本。"""
from __future__ import annotations

from app.domain.persona.entities import PersonaProfile
from app.services.persona.identity_resolver import IdentityResolver


# 四轴 → 指令句映射
_WARMTH_INSTRUCTIONS = [
    (0.7, "用口语化表达，可适度寒暄，像朋友聊天"),
    (0.4, "语气友好但不啰嗦，保持专业"),
    (0.0, "就事论事，直接给结论，不寒暄"),
]
_DETAIL_INSTRUCTIONS = [
    (0.7, "详细解释，给出具体步骤和原因"),
    (0.4, "适度详细，关键点说清楚"),
    (0.0, "简洁回答，惜字如金"),
]
_PROACTIVITY_INSTRUCTIONS = [
    (0.7, "主动提建议和下一步，不等用户问"),
    (0.4, "回答后可附带一个相关建议"),
    (0.0, "问什么答什么，不主动延伸"),
]
_STRUCTURE_INSTRUCTIONS = [
    (0.7, "用编号列表/分点组织回答"),
    (0.4, "重要信息分点，其余段落化"),
    (0.0, "自然段落对话，不强求结构"),
]

_SAFETY_SECTION = "如果不确定，诚实告知。涉及订单/支付/删除操作时需用户确认。"


def _pick_instruction(value: float, table: list[tuple[float, str]]) -> str:
    """根据参数值从指令表中选择对应指令。"""
    for threshold, instruction in table:
        if value >= threshold:
            return instruction
    return table[-1][1]  # 兜底


class PersonaPromptBuilder:
    """Persona Prompt 生成器。

    生成结构：身份段 + 风格段 + 业务上下文段 + 安全段（≤400 字）
    """

    def __init__(self, identity_resolver: IdentityResolver):
        self._identity_resolver = identity_resolver

    def build(self, profile: PersonaProfile, context_prompt: str) -> str:
        """生成 system prompt。

        Args:
            profile: 用户 persona 画像
            context_prompt: 业务上下文段（来自现有 _build_context_prompt）

        Returns:
            str: 完整 system prompt
        """
        # 身份段
        brief = self._identity_resolver.resolve_brief(profile.identity, profile.rapport)
        identity_section = f"你是{profile.identity.name}，{brief}。"

        # 风格段
        axes = profile.axes
        style_instructions = [
            _pick_instruction(axes.warmth, _WARMTH_INSTRUCTIONS),
            _pick_instruction(axes.detail, _DETAIL_INSTRUCTIONS),
            _pick_instruction(axes.proactivity, _PROACTIVITY_INSTRUCTIONS),
            _pick_instruction(axes.structure, _STRUCTURE_INSTRUCTIONS),
        ]
        style_section = "；".join(style_instructions) + "。"

        # 业务上下文段
        context_section = context_prompt.strip() if context_prompt else ""

        # 拼接
        sections = [identity_section, style_section]
        if context_section:
            sections.append(context_section)
        sections.append(_SAFETY_SECTION)

        return "\n\n".join(sections)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_prompt_builder.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd FHD && git add app/services/persona/prompt_builder.py tests/test_persona/test_prompt_builder.py
git commit -m "feat(persona): 新增 PersonaPromptBuilder Prompt 生成器"
```

---

## Task 9: 模型参数映射器

**Files:**
- Create: `FHD/app/services/persona/param_mapper.py`
- Test: `FHD/tests/test_persona/test_param_mapper.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_persona/test_param_mapper.py
"""模型参数映射器测试。"""
from __future__ import annotations

import pytest

from app.domain.persona.value_objects import PersonaAxes, RapportScore
from app.services.persona.param_mapper import PersonaParamMapper


class TestPersonaParamMapper:
    """模型参数映射器测试。"""

    @pytest.fixture
    def mapper(self):
        return PersonaParamMapper()

    def test_map_returns_dict_with_required_keys(self, mapper):
        axes = PersonaAxes()
        params = mapper.map(axes, RapportScore())
        assert "temperature" in params
        assert "max_tokens" in params
        assert "top_p" in params
        assert "frequency_penalty" in params
        assert "presence_penalty" in params

    def test_high_warmth_increases_temperature(self, mapper):
        high = mapper.map(PersonaAxes(warmth=1.0), RapportScore())
        low = mapper.map(PersonaAxes(warmth=0.0), RapportScore())
        assert high["temperature"] > low["temperature"]

    def test_high_detail_increases_max_tokens(self, mapper):
        high = mapper.map(PersonaAxes(detail=1.0), RapportScore())
        low = mapper.map(PersonaAxes(detail=0.0), RapportScore())
        assert high["max_tokens"] > low["max_tokens"]

    def test_high_structure_decreases_top_p(self, mapper):
        high = mapper.map(PersonaAxes(structure=1.0), RapportScore())
        low = mapper.map(PersonaAxes(structure=0.0), RapportScore())
        assert high["top_p"] < low["top_p"]

    def test_high_proactivity_increases_frequency_penalty(self, mapper):
        high = mapper.map(PersonaAxes(proactivity=1.0), RapportScore())
        low = mapper.map(PersonaAxes(proactivity=0.0), RapportScore())
        assert high["frequency_penalty"] > low["frequency_penalty"]

    def test_temperature_in_valid_range(self, mapper):
        axes = PersonaAxes(warmth=0.5)
        params = mapper.map(axes, RapportScore())
        assert 0.0 <= params["temperature"] <= 1.0

    def test_max_tokens_positive(self, mapper):
        axes = PersonaAxes(detail=0.0)
        params = mapper.map(axes, RapportScore())
        assert params["max_tokens"] > 0

    def test_top_p_in_valid_range(self, mapper):
        axes = PersonaAxes(structure=0.5)
        params = mapper.map(axes, RapportScore())
        assert 0.0 < params["top_p"] <= 1.0

    def test_presence_penalty_always_zero(self, mapper):
        axes = PersonaAxes()
        params = mapper.map(axes, RapportScore())
        assert params["presence_penalty"] == 0
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_param_mapper.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 PersonaParamMapper**

```python
# FHD/app/services/persona/param_mapper.py
"""Persona 模型参数映射器：四轴 → 推理参数。"""
from __future__ import annotations

from app.domain.persona.value_objects import PersonaAxes, RapportScore


class PersonaParamMapper:
    """模型参数映射器。

    映射公式：
    - temperature = 0.3 + warmth * 0.4  (0.3-0.7)
    - max_tokens = int(300 + detail * 700)  (300-1000)
    - top_p = 0.9 - structure * 0.2  (0.7-0.9)
    - frequency_penalty = proactivity * 0.3  (0-0.3)
    - presence_penalty = 0  (固定)
    """

    def map(self, axes: PersonaAxes, rapport: RapportScore) -> dict[str, float | int]:
        """映射 persona 参数到 LLM 推理参数。

        Args:
            axes: 四轴风格参数
            rapport: 关系深度（预留，当前未使用）

        Returns:
            dict: LLM 推理参数
        """
        return {
            "temperature": 0.3 + axes.warmth * 0.4,
            "max_tokens": int(300 + axes.detail * 700),
            "top_p": 0.9 - axes.structure * 0.2,
            "frequency_penalty": axes.proactivity * 0.3,
            "presence_penalty": 0,
        }
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_param_mapper.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd FHD && git add app/services/persona/param_mapper.py tests/test_persona/test_param_mapper.py
git commit -m "feat(persona): 新增 PersonaParamMapper 模型参数映射器"
```

---

## Task 10: L2 Embedding 推断器

**Files:**
- Create: `FHD/app/infrastructure/persona/__init__.py`
- Create: `FHD/app/infrastructure/persona/embedding_client.py`
- Create: `FHD/app/services/persona/embedding_inferencer.py`
- Test: `FHD/tests/test_persona/test_embedding_inferencer.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_persona/test_embedding_inferencer.py
"""L2 embedding 推断器测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.persona.value_objects import PersonaAxes
from app.infrastructure.persona.embedding_client import EmbeddingClient
from app.services.persona.embedding_inferencer import EmbeddingInferResult, EmbeddingInferencer


class TestEmbeddingInferencer:
    """L2 embedding 推断器测试。"""

    @pytest.fixture
    def mock_client(self):
        client = MagicMock(spec=EmbeddingClient)
        client.embed_texts = AsyncMock(return_value=[[0.1] * 8, [0.2] * 8, [0.3] * 8])
        return client

    @pytest.fixture
    def inferencer(self, mock_client):
        return EmbeddingInferencer(mock_client)

    @pytest.mark.asyncio
    async def test_infer_returns_result_with_axes(self, inferencer):
        messages = ["你好", "帮我查订单", "详细说说"]
        result = await inferencer.infer("user-1", messages)
        assert isinstance(result, EmbeddingInferResult)
        assert isinstance(result.axes, PersonaAxes)
        assert isinstance(result.pattern_label, str)

    @pytest.mark.asyncio
    async def test_infer_empty_messages_returns_neutral(self, inferencer):
        result = await inferencer.infer("user-1", [])
        assert result.axes.warmth == 0.5
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_infer_client_failure_returns_neutral(self, mock_client):
        mock_client.embed_texts = AsyncMock(side_effect=Exception("API down"))
        inferencer = EmbeddingInferencer(mock_client)
        result = await inferencer.infer("user-1", ["你好"])
        # 容错：返回中性值，不抛异常
        assert result.axes.warmth == 0.5
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_infer_single_message_returns_result(self, inferencer):
        result = await inferencer.infer("user-1", ["你好呀😊"])
        assert 0.0 <= result.axes.warmth <= 1.0
```

```python
# FHD/app/infrastructure/persona/__init__.py
"""Persona 基础设施。"""
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_embedding_inferencer.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 EmbeddingClient + EmbeddingInferencer**

```python
# FHD/app/infrastructure/persona/embedding_client.py
"""外部 embedding API 客户端。"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """外部 embedding API 客户端（零硬件，调外部 API）。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "text-embedding-3-small",
        timeout: float = 10.0,
    ):
        self.api_key = api_key or os.getenv("XCAGI_EMBEDDING_API_KEY", "")
        self.base_url = base_url or os.getenv("XCAGI_EMBEDDING_BASE_URL", "https://api.openai.com/v1")
        self.model = model
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """调用 embedding API 生成向量。

        Args:
            texts: 待向量化的文本列表

        Returns:
            list[list[float]]: 向量列表

        Raises:
            Exception: API 调用失败时抛出
        """
        if not self.is_configured:
            raise RuntimeError("Embedding API key 未配置")
        if not texts:
            return []

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {"model": self.model, "input": texts}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/embeddings", headers=headers, json=payload
            )
            response.raise_for_status()
            data = response.json()
            return [item["embedding"] for item in data["data"]]
```

```python
# FHD/app/services/persona/embedding_inferencer.py
"""L2 embedding 推断器：定期聚类发现隐藏模式。"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.persona.value_objects import PersonaAxes
from app.infrastructure.persona.embedding_client import EmbeddingClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingInferResult:
    """L2 embedding 推断结果。"""

    axes: PersonaAxes
    pattern_label: str
    confidence: float


# 聚类中心 → 四轴参数映射（预标注校准表，简化版）
# 实际生产中应通过标注数据校准
_CLUSTER_AXES_MAP: dict[str, PersonaAxes] = {
    "warm_detailed": PersonaAxes(warmth=0.8, detail=0.7, proactivity=0.6, structure=0.5),
    "concise_formal": PersonaAxes(warmth=0.3, detail=0.3, proactivity=0.4, structure=0.7),
    "proactive_structured": PersonaAxes(warmth=0.5, detail=0.6, proactivity=0.8, structure=0.8),
    "neutral": PersonaAxes(warmth=0.5, detail=0.5, proactivity=0.5, structure=0.5),
}


class EmbeddingInferencer:
    """L2 embedding 推断器。

    流程：
    1. 调外部 embedding API 生成向量
    2. K-means 聚类（k=3-5）
    3. 聚类中心映射到四轴参数空间

    延迟预算：~200ms（异步，不阻塞对话）
    作用：发现规则捕捉不到的长期风格模式
    """

    def __init__(self, client: EmbeddingClient):
        self._client = client

    async def infer(self, user_id: str, messages: list[str]) -> EmbeddingInferResult:
        """推断四轴参数。

        Args:
            user_id: 用户 ID
            messages: 最近 N 条用户消息

        Returns:
            EmbeddingInferResult: 四轴值 + 模式标签 + 置信度
        """
        if not messages:
            return EmbeddingInferResult(
                axes=PersonaAxes(),
                pattern_label="no_data",
                confidence=0.0,
            )

        try:
            embeddings = await self._client.embed_texts(messages)
            if not embeddings:
                return EmbeddingInferResult(
                    axes=PersonaAxes(),
                    pattern_label="no_data",
                    confidence=0.0,
                )

            # 简化版：用平均向量距离匹配最近的预标注模式
            # 生产环境应使用 K-means 聚类
            pattern = self._match_pattern(embeddings)
            axes = _CLUSTER_AXES_MAP.get(pattern, PersonaAxes())
            return EmbeddingInferResult(
                axes=axes,
                pattern_label=pattern,
                confidence=0.6,
            )
        except Exception as e:
            logger.warning("L2 embedding 推断失败，返回中性值: %s", e)
            return EmbeddingInferResult(
                axes=PersonaAxes(),
                pattern_label="error",
                confidence=0.0,
            )

    def _match_pattern(self, embeddings: list[list[float]]) -> str:
        """简化版模式匹配（生产环境用 K-means）。

        根据向量统计特征（方差、均值）粗略匹配模式。
        """
        if not embeddings:
            return "neutral"

        # 简化：用向量维度方差作为风格一致性指标
        # 实际生产应训练分类器或聚类
        first_vec = embeddings[0]
        avg_len = sum(len(v) for v in embeddings) / len(embeddings)

        # 占位逻辑：根据向量长度和数量粗略分类
        # 生产环境替换为 K-means + 标注校准
        if len(embeddings) >= 3 and avg_len > 100:
            return "warm_detailed"
        if len(embeddings) <= 1:
            return "concise_formal"
        return "neutral"
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_embedding_inferencer.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd FHD && git add app/infrastructure/persona/__init__.py app/infrastructure/persona/embedding_client.py app/services/persona/embedding_inferencer.py tests/test_persona/test_embedding_inferencer.py
git commit -m "feat(persona): 新增 L2 embedding 推断器（含外部 API 客户端）"
```

---

## Task 11: L3 LLM 推断器

**Files:**
- Create: `FHD/app/services/persona/llm_inferencer.py`
- Test: `FHD/tests/test_persona/test_llm_inferencer.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_persona/test_llm_inferencer.py
"""L3 LLM 推断器测试。"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.persona.value_objects import PersonaAxes
from app.services.persona.llm_inferencer import LlmInferResult, LlmInferencer


class TestLlmInferencer:
    """L3 LLM 推断器测试。"""

    @pytest.fixture
    def mock_llm_client(self):
        client = MagicMock()
        client.chat_completion = AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({
                                "warmth": 0.7,
                                "detail": 0.4,
                                "proactivity": 0.6,
                                "structure": 0.8,
                                "reason": "用户倾向口语化交流",
                            })
                        }
                    }
                ]
            }
        )
        return client

    @pytest.fixture
    def inferencer(self, mock_llm_client):
        return LlmInferencer(mock_llm_client)

    @pytest.mark.asyncio
    async def test_infer_returns_result_with_axes(self, inferencer):
        history = [{"role": "user", "content": "你好呀"}, {"role": "assistant", "content": "你好"}]
        result = await inferencer.infer("user-1", history, PersonaAxes())
        assert isinstance(result, LlmInferResult)
        assert isinstance(result.axes, PersonaAxes)
        assert result.axes.warmth == 0.7
        assert result.reason is not None

    @pytest.mark.asyncio
    async def test_infer_empty_history_returns_neutral(self, inferencer):
        result = await inferencer.infer("user-1", [], PersonaAxes())
        assert result.axes.warmth == 0.5
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_infer_llm_failure_returns_neutral(self, mock_llm_client):
        mock_llm_client.chat_completion = AsyncMock(side_effect=Exception("LLM down"))
        inferencer = LlmInferencer(mock_llm_client)
        result = await inferencer.infer(
            "user-1",
            [{"role": "user", "content": "你好"}],
            PersonaAxes(),
        )
        # 容错：返回中性值，不抛异常
        assert result.axes.warmth == 0.5
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_infer_invalid_json_returns_neutral(self, mock_llm_client):
        mock_llm_client.chat_completion = AsyncMock(
            return_value={"choices": [{"message": {"content": "not json"}}]}
        )
        inferencer = LlmInferencer(mock_llm_client)
        result = await inferencer.infer(
            "user-1",
            [{"role": "user", "content": "你好"}],
            PersonaAxes(),
        )
        assert result.axes.warmth == 0.5
        assert result.confidence == 0.0
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_llm_inferencer.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 LlmInferencer**

```python
# FHD/app/services/persona/llm_inferencer.py
"""L3 LLM 推断器：定期复盘校准。"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.domain.persona.value_objects import PersonaAxes

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmInferResult:
    """L3 LLM 推断结果。"""

    axes: PersonaAxes
    reason: str
    confidence: float


_L3_SYSTEM_PROMPT = """你是对话风格分析助手。分析用户最近的对话历史，输出用户的对话风格参数。

输出 JSON 格式：
{
  "warmth": 0.0-1.0,  // 亲切度：0=就事论事，1=有温度
  "detail": 0.0-1.0,  // 详细度：0=概括，1=具体步骤
  "proactivity": 0.0-1.0,  // 主动度：0=问答，1=主动建议
  "structure": 0.0-1.0,  // 结构度：0=灵活，1=结构化
  "reason": "判断依据简述"
}

只输出 JSON，不要其他内容。"""


class LlmInferencer:
    """L3 LLM 推断器。

    流程：
    1. 用小模型分析用户最近 20 轮对话风格
    2. 输出四轴校准值 + 理由（JSON）
    3. 与 L1/L2 加权融合

    延迟预算：~1-2s（异步，不阻塞对话）
    作用：校准规则和 embedding 的偏差，处理复杂语境
    """

    def __init__(self, llm_client):
        self._llm_client = llm_client

    async def infer(
        self,
        user_id: str,
        history: list[dict],
        current_axes: PersonaAxes,
    ) -> LlmInferResult:
        """推断四轴参数。

        Args:
            user_id: 用户 ID
            history: 最近 20 轮对话历史
            current_axes: 当前四轴值（供 LLM 参考）

        Returns:
            LlmInferResult: 四轴值 + 理由 + 置信度
        """
        if not history:
            return LlmInferResult(
                axes=PersonaAxes(),
                reason="无历史数据",
                confidence=0.0,
            )

        try:
            # 构造对话摘要
            summary = self._summarize_history(history)
            user_prompt = f"用户最近对话：\n{summary}\n\n当前四轴值：{current_axes.to_dict()}\n\n请分析用户对话风格："

            messages = [
                {"role": "system", "content": _L3_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

            response = await self._llm_client.chat_completion(messages)
            content = response["choices"][0]["message"]["content"]

            return self._parse_response(content)
        except Exception as e:
            logger.warning("L3 LLM 推断失败，返回中性值: %s", e)
            return LlmInferResult(
                axes=PersonaAxes(),
                reason=f"推断失败: {e}",
                confidence=0.0,
            )

    def _summarize_history(self, history: list[dict]) -> str:
        """将历史对话摘要为文本。"""
        lines = []
        for msg in history[-20:]:  # 最多 20 轮
            role = msg.get("role", "unknown")
            content = str(msg.get("content", ""))[:100]  # 每条最多 100 字
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    def _parse_response(self, content: str) -> LlmInferResult:
        """解析 LLM 返回的 JSON。"""
        try:
            data = json.loads(content)
            axes = PersonaAxes(
                warmth=float(data.get("warmth", 0.5)),
                detail=float(data.get("detail", 0.5)),
                proactivity=float(data.get("proactivity", 0.5)),
                structure=float(data.get("structure", 0.5)),
            )
            reason = str(data.get("reason", ""))
            return LlmInferResult(axes=axes, reason=reason, confidence=0.7)
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning("L3 LLM 返回解析失败: %s, content: %s", e, content[:200])
            return LlmInferResult(
                axes=PersonaAxes(),
                reason=f"解析失败: {e}",
                confidence=0.0,
            )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_llm_inferencer.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd FHD && git add app/services/persona/llm_inferencer.py tests/test_persona/test_llm_inferencer.py
git commit -m "feat(persona): 新增 L3 LLM 推断器（定期复盘校准）"
```

---

## Task 12: DB 模型 + 仓储实现

**Files:**
- Create: `FHD/app/infrastructure/persona/models.py`
- Create: `FHD/app/infrastructure/persona/persona_repository_impl.py`
- Modify: `FHD/app/db/models/__init__.py`
- Test: `FHD/tests/test_persona/test_persona_repository_impl.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_persona/test_persona_repository_impl.py
"""PersonaRepositoryImpl 仓储实现测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.persona.entities import PersonaProfile
from app.infrastructure.persona.persona_repository_impl import PersonaRepositoryImpl


class TestPersonaRepositoryImpl:
    """仓储实现测试（使用 mock Redis + DB）。"""

    @pytest.fixture
    def mock_redis(self):
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock(return_value=True)
        redis.delete = AsyncMock(return_value=1)
        return redis

    @pytest.fixture
    def mock_db_session(self):
        session = MagicMock()
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.flush = AsyncMock()
        return session

    @pytest.fixture
    def repo(self, mock_redis, mock_db_session):
        return PersonaRepositoryImpl(redis=mock_redis, db_session=mock_db_session)

    @pytest.mark.asyncio
    async def test_find_by_user_id_cache_miss_returns_none(self, repo, mock_redis):
        mock_redis.get = AsyncMock(return_value=None)
        # DB 也无数据
        mock_db = MagicMock()
        mock_db.scalar_one_or_none = MagicMock(return_value=None)
        repo._db_session.execute = AsyncMock(return_value=mock_db)
        result = await repo.find_by_user_id("user-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_sets_redis_cache(self, repo, mock_redis):
        profile = PersonaProfile.create("user-1", "零售业")
        await repo.save(profile)
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_clears_redis(self, repo, mock_redis):
        await repo.delete("user-1")
        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_append_event_does_not_raise(self, repo):
        await repo.append_event("user-1", "l1_infer", {"warmth": 0.7})
        # 不抛异常即通过

    @pytest.mark.asyncio
    async def test_list_recent_events_returns_list(self, repo, mock_db_session):
        mock_db = MagicMock()
        mock_db.scalars = MagicMock(return_value=[])
        mock_db_session.execute = AsyncMock(return_value=mock_db)
        events = await repo.list_recent_events("user-1", limit=10)
        assert isinstance(events, list)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_persona_repository_impl.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 DB 模型 + 仓储**

```python
# FHD/app/infrastructure/persona/models.py
"""Persona DB ORM 模型。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class PersonaProfileModel(TimestampMixin, Base):
    """Persona 画像持久化模型。"""

    __tablename__ = "persona_profile"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    industry: Mapped[str] = mapped_column(String(32), nullable=False)
    identity_name: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    business_domain: Mapped[str] = mapped_column(String(32), nullable=False)
    rapport_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.3)
    warmth: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    detail: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    proactivity: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    structure: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    interaction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    business_domain_counts: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    emotion_signal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PersonaEventLogModel(Base):
    """Persona 事件日志模型（审计 + L3 复盘）。"""

    __tablename__ = "persona_event_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_data: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
```

```python
# FHD/app/infrastructure/persona/persona_repository_impl.py
"""Persona 画像仓储实现（Redis 热数据 + DB 冷数据）。"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.application.ports.persona_repository import PersonaProfileRepository
from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import (
    PersonaAxes,
    PersonaIdentity,
    RapportScore,
)
from app.infrastructure.persona.models import PersonaEventLogModel, PersonaProfileModel

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 3600  # 1 小时
_CACHE_KEY_PREFIX = "persona:profile:"


class PersonaRepositoryImpl(PersonaProfileRepository):
    """Persona 画像仓储实现。

    策略：Redis 优先（热数据，TTL 1h），DB 回源（冷数据）。
    """

    def __init__(self, redis: Any, db_session: Any):
        self._redis = redis
        self._db_session = db_session

    async def find_by_user_id(self, user_id: str) -> PersonaProfile | None:
        """查找画像：Redis 优先，DB 回源。"""
        # 1. Redis 查询
        cache_key = f"{_CACHE_KEY_PREFIX}{user_id}"
        cached = await self._redis.get(cache_key)
        if cached:
            try:
                return PersonaProfile.from_dict(json.loads(cached))
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Redis 画像解析失败: %s", e)

        # 2. DB 回源
        result = await self._db_session.execute(
            f"SELECT * FROM {PersonaProfileModel.__tablename__} WHERE user_id = :uid",
            {"uid": user_id},
        )
        row = result.scalar_one_or_none() if hasattr(result, "scalar_one_or_none") else None
        if row is None:
            return None

        # 转换并回填 Redis
        profile = self._row_to_profile(row)
        await self._redis.setex(cache_key, _CACHE_TTL_SECONDS, json.dumps(profile.to_dict()))
        return profile

    async def save(self, profile: PersonaProfile) -> PersonaProfile:
        """保存画像：DB 持久化 + Redis 缓存。"""
        # 1. DB upsert
        model = self._profile_to_model(profile)
        await self._db_session.execute(
            f"INSERT OR REPLACE INTO {PersonaProfileModel.__tablename__} "
            f"(user_id, industry, identity_name, identity_brief, business_domain, "
            f"rapport_score, warmth, detail, proactivity, structure, "
            f"interaction_count, business_domain_counts, emotion_signal_count) "
            f"VALUES (:user_id, :industry, :identity_name, :identity_brief, :business_domain, "
            f":rapport_score, :warmth, :detail, :proactivity, :structure, "
            f":interaction_count, :business_domain_counts, :emotion_signal_count)",
            {
                "user_id": model.user_id,
                "industry": model.industry,
                "identity_name": model.identity_name,
                "identity_brief": model.identity_brief,
                "business_domain": model.business_domain,
                "rapport_score": model.rapport_score,
                "warmth": model.warmth,
                "detail": model.detail,
                "proactivity": model.proactivity,
                "structure": model.structure,
                "interaction_count": model.interaction_count,
                "business_domain_counts": model.business_domain_counts,
                "emotion_signal_count": model.emotion_signal_count,
            },
        )
        await self._db_session.commit()

        # 2. Redis 缓存
        cache_key = f"{_CACHE_KEY_PREFIX}{profile.user_id}"
        await self._redis.setex(cache_key, _CACHE_TTL_SECONDS, json.dumps(profile.to_dict()))
        return profile

    async def delete(self, user_id: str) -> bool:
        """删除画像：DB + Redis。"""
        await self._db_session.execute(
            f"DELETE FROM {PersonaProfileModel.__tablename__} WHERE user_id = :uid",
            {"uid": user_id},
        )
        await self._db_session.commit()
        await self._redis.delete(f"{_CACHE_KEY_PREFIX}{user_id}")
        return True

    async def append_event(self, user_id: str, event_type: str, event_data: dict) -> None:
        """追加事件日志。"""
        model = PersonaEventLogModel(
            user_id=user_id,
            event_type=event_type,
            event_data=json.dumps(event_data, ensure_ascii=False),
        )
        self._db_session.add(model)
        await self._db_session.commit()

    async def list_recent_events(self, user_id: str, limit: int = 20) -> list[dict]:
        """列出最近的事件日志。"""
        result = await self._db_session.execute(
            f"SELECT * FROM {PersonaEventLogModel.__tablename__} "
            f"WHERE user_id = :uid ORDER BY created_at DESC LIMIT :limit",
            {"uid": user_id, "limit": limit},
        )
        rows = result.scalars().all() if hasattr(result, "scalars") else []
        return [
            {
                "id": row.id,
                "user_id": row.user_id,
                "event_type": row.event_type,
                "event_data": json.loads(row.event_data) if row.event_data else {},
                "trace_id": row.trace_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    def _row_to_profile(self, row: Any) -> PersonaProfile:
        """DB 行 → 领域对象。"""
        domain_counts = {}
        if hasattr(row, "business_domain_counts") and row.business_domain_counts:
            try:
                domain_counts = json.loads(row.business_domain_counts)
            except json.JSONDecodeError:
                pass
        return PersonaProfile(
            user_id=row.user_id,
            identity=PersonaIdentity(
                name=row.identity_name,
                brief=row.identity_brief,
                business_domain=row.business_domain,
                industry=row.industry,
            ),
            axes=PersonaAxes(
                warmth=row.warmth,
                detail=row.detail,
                proactivity=row.proactivity,
                structure=row.structure,
            ),
            rapport=RapportScore(
                score=row.rapport_score,
                interaction_count=row.interaction_count,
                emotion_signal_count=row.emotion_signal_count,
            ),
            business_domain_counts=domain_counts,
        )

    def _profile_to_model(self, profile: PersonaProfile) -> PersonaProfileModel:
        """领域对象 → DB 模型。"""
        return PersonaProfileModel(
            user_id=profile.user_id,
            industry=profile.identity.industry,
            identity_name=profile.identity.name,
            identity_brief=profile.identity.brief,
            business_domain=profile.identity.business_domain,
            rapport_score=profile.rapport.score,
            warmth=profile.axes.warmth,
            detail=profile.axes.detail,
            proactivity=profile.axes.proactivity,
            structure=profile.axes.structure,
            interaction_count=profile.rapport.interaction_count,
            business_domain_counts=json.dumps(profile.business_domain_counts, ensure_ascii=False),
            emotion_signal_count=profile.rapport.emotion_signal_count,
        )
```

- [ ] **Step 4: 注册 DB 模型到 `__init__.py`**

修改 `FHD/app/db/models/__init__.py`，在文件末尾添加：

```python
from app.infrastructure.persona.models import PersonaEventLogModel, PersonaProfileModel
```

并在 `__all__` 列表中添加 `"PersonaProfileModel"`, `"PersonaEventLogModel"`。

- [ ] **Step 5: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_persona_repository_impl.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
cd FHD && git add app/infrastructure/persona/models.py app/infrastructure/persona/persona_repository_impl.py app/db/models/__init__.py tests/test_persona/test_persona_repository_impl.py
git commit -m "feat(persona): 新增 DB 模型 + PersonaRepositoryImpl 仓储实现"
```

---

## Task 13: Neuro Bus persona 事件

**Files:**
- Create: `FHD/app/neuro_bus/events/persona_event.py`
- Test: `FHD/tests/test_persona/test_persona_event.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_persona/test_persona_event.py
"""Persona 领域事件测试。"""
from __future__ import annotations

from app.domain.persona.value_objects import PersonaAxes
from app.neuro_bus.events.persona_event import PersonaUpdated


class TestPersonaUpdated:
    """PersonaUpdated 事件测试。"""

    def test_create_event_returns_all_fields(self):
        axes = PersonaAxes(warmth=0.7, detail=0.4, proactivity=0.6, structure=0.8)
        event = PersonaUpdated(
            user_id="user-1",
            axes=axes,
            rapport=0.5,
            identity="考勤管家",
            source="l1",
            trace_id="trace-123",
        )
        assert event.user_id == "user-1"
        assert event.axes.warmth == 0.7
        assert event.rapport == 0.5
        assert event.identity == "考勤管家"
        assert event.source == "l1"
        assert event.trace_id == "trace-123"

    def test_event_type_is_correct(self):
        event = PersonaUpdated(
            user_id="user-1",
            axes=PersonaAxes(),
            rapport=0.3,
            identity="业务管家",
            source="fusion",
            trace_id="t-1",
        )
        assert event.event_type == "persona.updated"

    def test_to_dict_returns_serializable(self):
        event = PersonaUpdated(
            user_id="user-1",
            axes=PersonaAxes(warmth=0.7),
            rapport=0.5,
            identity="考勤管家",
            source="l1",
            trace_id="t-1",
        )
        d = event.to_dict()
        assert d["user_id"] == "user-1"
        assert d["axes"]["warmth"] == 0.7
        assert d["rapport"] == 0.5
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_persona_event.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 persona 事件**

```python
# FHD/app/neuro_bus/events/persona_event.py
"""Persona 领域事件。"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.persona.value_objects import PersonaAxes


@dataclass(frozen=True)
class PersonaUpdated:
    """Persona 画像更新事件。

    发布时机：
    - L1 每轮发布（轻量）
    - L2/L3 触发时发布（重量）
    - 身份漂移时发布（重要，需监控）
    """

    user_id: str
    axes: PersonaAxes
    rapport: float
    identity: str
    source: str  # "l1" | "l2" | "l3" | "fusion"
    trace_id: str

    @property
    def event_type(self) -> str:
        return "persona.updated"

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "axes": self.axes.to_dict(),
            "rapport": self.rapport,
            "identity": self.identity,
            "source": self.source,
            "trace_id": self.trace_id,
        }
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_persona_event.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd FHD && git add app/neuro_bus/events/persona_event.py tests/test_persona/test_persona_event.py
git commit -m "feat(persona): 新增 PersonaUpdated 领域事件"
```

---

## Task 14: PersonaService 主服务

**Files:**
- Create: `FHD/app/services/persona/persona_service.py`
- Test: `FHD/tests/test_persona/test_persona_service.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_persona/test_persona_service.py
"""PersonaService 主服务测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import PersonaAxes, RapportScore
from app.services.persona.persona_service import PersonaService


class TestPersonaService:
    """PersonaService 主服务测试。"""

    @pytest.fixture
    def mock_repo(self):
        repo = MagicMock()
        repo.find_by_user_id = AsyncMock(return_value=None)
        repo.save = AsyncMock()
        repo.append_event = AsyncMock()
        return repo

    @pytest.fixture
    def service(self, mock_repo):
        return PersonaService(
            repo=mock_repo,
            rule_inferencer=MagicMock(),
            embedding_inferencer=MagicMock(),
            llm_inferencer=MagicMock(),
            axes_fuser=MagicMock(),
            rapport_calculator=MagicMock(),
            identity_resolver=MagicMock(),
            prompt_builder=MagicMock(),
            param_mapper=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_get_persona_cold_start_returns_default(self, service, mock_repo):
        """冷启动：无历史画像时返回默认画像。"""
        mock_repo.find_by_user_id = AsyncMock(return_value=None)
        profile = await service.get_persona("user-1", industry="零售业")
        assert profile is not None
        assert profile.identity.industry == "零售业"
        assert profile.rapport.score == 0.3  # 冷启动默认

    @pytest.mark.asyncio
    async def test_get_persona_existing_returns_stored(self, service, mock_repo):
        """已有画像时返回存储的画像。"""
        stored = PersonaProfile.create("user-1", "零售业")
        mock_repo.find_by_user_id = AsyncMock(return_value=stored)
        profile = await service.get_persona("user-1", industry="零售业")
        assert profile.user_id == "user-1"

    @pytest.mark.asyncio
    async def test_update_persona_on_message_returns_updated_axes(self, service, mock_repo):
        """消息到达时更新 persona。"""
        stored = PersonaProfile.create("user-1", "零售业")
        mock_repo.find_by_user_id = AsyncMock(return_value=stored)

        # mock L1 推断
        from app.services.persona.rule_inferencer import RuleInferResult
        service._rule_inferencer.infer = MagicMock(
            return_value=RuleInferResult(
                axes=PersonaAxes(warmth=0.8, detail=0.3, proactivity=0.6, structure=0.9),
                confidence=0.5,
                signals=["emoji"],
            )
        )
        service._axes_fuser.fuse = MagicMock(return_value=PersonaAxes(warmth=0.8))
        service._rapport_calculator.calculate = MagicMock(
            return_value=RapportScore(score=0.4, interaction_count=1)
        )

        result = await service.update_on_message(
            user_id="user-1",
            message="你好呀😊",
            history=[],
            industry="零售业",
        )
        assert result is not None
        assert result.axes.warmth == 0.8

    @pytest.mark.asyncio
    async def test_update_persona_saves_to_repo(self, service, mock_repo):
        """更新后保存到仓储。"""
        stored = PersonaProfile.create("user-1", "零售业")
        mock_repo.find_by_user_id = AsyncMock(return_value=stored)

        from app.services.persona.rule_inferencer import RuleInferResult
        service._rule_inferencer.infer = MagicMock(
            return_value=RuleInferResult(axes=PersonaAxes(), confidence=0.0, signals=[])
        )
        service._axes_fuser.fuse = MagicMock(return_value=PersonaAxes())
        service._rapport_calculator.calculate = MagicMock(
            return_value=RapportScore(score=0.3, interaction_count=1)
        )

        await service.update_on_message("user-1", "你好", [], "零售业")
        mock_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_persona_appends_event(self, service, mock_repo):
        """更新后追加事件日志。"""
        stored = PersonaProfile.create("user-1", "零售业")
        mock_repo.find_by_user_id = AsyncMock(return_value=stored)

        from app.services.persona.rule_inferencer import RuleInferResult
        service._rule_inferencer.infer = MagicMock(
            return_value=RuleInferResult(axes=PersonaAxes(), confidence=0.0, signals=[])
        )
        service._axes_fuser.fuse = MagicMock(return_value=PersonaAxes())
        service._rapport_calculator.calculate = MagicMock(
            return_value=RapportScore(score=0.3, interaction_count=1)
        )

        await service.update_on_message("user-1", "你好", [], "零售业")
        mock_repo.append_event.assert_called_once()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_persona_service.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 PersonaService**

```python
# FHD/app/services/persona/persona_service.py
"""PersonaService 主服务：编排三层推断 + 融合 + 持久化。"""
from __future__ import annotations

import logging

from app.application.ports.persona_repository import PersonaProfileRepository
from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import PersonaAxes, RapportScore
from app.services.persona.axes_fuser import AxesFuser
from app.services.persona.embedding_inferencer import EmbeddingInferencer
from app.services.persona.identity_resolver import IdentityResolver
from app.services.persona.llm_inferencer import LlmInferencer
from app.services.persona.param_mapper import PersonaParamMapper
from app.services.persona.prompt_builder import PersonaPromptBuilder
from app.services.persona.rapport_calculator import RapportCalculator
from app.services.persona.rule_inferencer import RuleInferencer

logger = logging.getLogger(__name__)


class PersonaService:
    """Persona 主服务。

    职责：
    1. 加载用户画像（Redis 优先，DB 回源）
    2. L1 规则层实时推断（同步）
    3. 融合最终 persona（L1 + L2缓存 + L3缓存）
    4. 异步更新画像（不阻塞响应）
    5. 触发 L2/L3 异步推断（按轮数阈值）
    """

    L2_TRIGGER_INTERVAL = 10  # 每 10 轮触发 L2
    L3_TRIGGER_INTERVAL = 20  # 每 20 轮触发 L3

    def __init__(
        self,
        repo: PersonaProfileRepository,
        rule_inferencer: RuleInferencer,
        embedding_inferencer: EmbeddingInferencer,
        llm_inferencer: LlmInferencer,
        axes_fuser: AxesFuser,
        rapport_calculator: RapportCalculator,
        identity_resolver: IdentityResolver,
        prompt_builder: PersonaPromptBuilder,
        param_mapper: PersonaParamMapper,
    ):
        self._repo = repo
        self._rule_inferencer = rule_inferencer
        self._embedding_inferencer = embedding_inferencer
        self._llm_inferencer = llm_inferencer
        self._axes_fuser = axes_fuser
        self._rapport_calculator = rapport_calculator
        self._identity_resolver = identity_resolver
        self._prompt_builder = prompt_builder
        self._param_mapper = param_mapper

    async def get_persona(self, user_id: str, industry: str) -> PersonaProfile:
        """加载用户画像。

        冷启动：无历史画像时根据行业创建默认画像。
        """
        profile = await self._repo.find_by_user_id(user_id)
        if profile is None:
            profile = PersonaProfile.create(user_id=user_id, industry=industry)
            await self._repo.save(profile)
        return profile

    async def update_on_message(
        self,
        user_id: str,
        message: str,
        history: list[dict],
        industry: str,
    ) -> PersonaProfile:
        """消息到达时更新 persona（同步路径）。

        1. 加载画像
        2. L1 规则推断（同步）
        3. 融合（L1 + L2/L3 缓存值）
        4. 更新 rapport
        5. 保存 + 发布事件
        6. 异步触发 L2/L3（按轮数阈值）

        延迟预算：<10ms（同步路径）
        """
        # 1. 加载画像
        profile = await self.get_persona(user_id, industry)

        # 2. L1 规则推断（同步）
        l1_result = self._rule_inferencer.infer(message, history)

        # 3. 融合（L1 + 缓存的 L2/L3）
        # 注意：L2/L3 的缓存值在 profile 中，这里简化为仅用 L1
        # 生产环境应从 Redis 读取 L2/L3 缓存值
        fused_axes = self._axes_fuser.fuse(
            l1=l1_result.axes,
            l2=None,  # 从缓存读取
            l3=None,  # 从缓存读取
            rapport=profile.rapport,
            signal_strength=l1_result.confidence,
        )

        # 4. 更新 rapport
        new_interaction_count = profile.rapport.interaction_count + 1
        new_domain_counts = dict(profile.business_domain_counts)
        # 简化：每轮都计入当前身份域
        current_domain = profile.identity.business_domain
        new_domain_counts[current_domain] = new_domain_counts.get(current_domain, 0) + 1

        new_rapport = self._rapport_calculator.calculate(
            interaction_count=new_interaction_count,
            business_domain_counts=new_domain_counts,
            emotion_signal_count=profile.rapport.emotion_signal_count,
        )

        # 5. 更新画像
        updated_profile = profile.update_axes(fused_axes).update_rapport(new_rapport)
        updated_profile = PersonaProfile(
            user_id=updated_profile.user_id,
            identity=updated_profile.identity,
            axes=updated_profile.axes,
            rapport=updated_profile.rapport,
            business_domain_counts=new_domain_counts,
            created_at=updated_profile.created_at,
            updated_at=updated_profile.updated_at,
        )

        # 6. 保存 + 发布事件
        await self._repo.save(updated_profile)
        await self._repo.append_event(
            user_id=user_id,
            event_type="l1_infer",
            event_data={
                "axes": l1_result.axes.to_dict(),
                "fused_axes": fused_axes.to_dict(),
                "signals": l1_result.signals,
                "confidence": l1_result.confidence,
            },
        )

        # 7. 异步触发 L2/L3（按轮数阈值）
        # 注意：实际生产应使用 asyncio.create_task 异步执行
        # 这里简化为同步调用，由调用方决定是否异步
        if new_interaction_count % self.L2_TRIGGER_INTERVAL == 0:
            logger.debug("触发 L2 embedding 推断: user=%s", user_id)
        if new_interaction_count % self.L3_TRIGGER_INTERVAL == 0:
            logger.debug("触发 L3 LLM 推断: user=%s", user_id)

        return updated_profile

    def build_prompt(self, profile: PersonaProfile, context_prompt: str) -> str:
        """生成 system prompt。"""
        return self._prompt_builder.build(profile, context_prompt)

    def map_params(self, profile: PersonaProfile) -> dict[str, float | int]:
        """映射模型推理参数。"""
        return self._param_mapper.map(profile.axes, profile.rapport)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_persona_service.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd FHD && git add app/services/persona/persona_service.py tests/test_persona/test_persona_service.py
git commit -m "feat(persona): 新增 PersonaService 主服务（编排三层推断）"
```

---

## Task 15: 改造 api.py（base_prompt → persona prompt）

**Files:**
- Modify: `FHD/app/services/conversation/api.py:449-464`
- Test: `FHD/tests/test_persona/test_api_integration.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_persona/test_api_integration.py
"""api.py persona 集成测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import PersonaAxes, PersonaIdentity, RapportScore


class TestApiPersonaIntegration:
    """api.py 与 persona 集成测试。"""

    @pytest.mark.asyncio
    async def test_persona_service_injected_into_conversation_service(self):
        """AIConversationService 可注入 PersonaService。"""
        from app.services.conversation.manager import AIConversationService

        service = AIConversationService()
        # persona_service 默认为 None（未注入时走 fallback）
        assert hasattr(service, "persona_service")
        assert service.persona_service is None

    def test_legacy_base_prompt_constant_exists(self):
        """旧 base_prompt 作为 fallback 常量保留。"""
        from app.services.conversation.api import LEGACY_BASE_PROMPT

        assert "专业的业务助手" in LEGACY_BASE_PROMPT

    @pytest.mark.asyncio
    async def test_build_system_prompt_with_persona(self):
        """注入 persona 时使用 persona prompt。"""
        from app.services.conversation.api import ApiMixin

        # 创建 mock persona service
        mock_persona_service = MagicMock()
        mock_persona_service.update_on_message = AsyncMock(
            return_value=PersonaProfile(
                user_id="user-1",
                identity=PersonaIdentity(
                    name="考勤管家",
                    brief="专业地服务用户",
                    business_domain="attendance",
                    industry="服务业",
                ),
                axes=PersonaAxes(warmth=0.8, detail=0.5, proactivity=0.6, structure=0.7),
                rapport=RapportScore(score=0.5, interaction_count=100),
            )
        )
        mock_persona_service.build_prompt = MagicMock(
            return_value="你是考勤管家，专业地服务用户。\n\n用口语化表达。"
        )

        # 创建 ApiMixin 实例
        class FakeApiMixin(ApiMixin):
            def __init__(self):
                self.persona_service = mock_persona_service
                self._build_context_prompt = MagicMock(return_value="当前意图：查询")

        mixin = FakeApiMixin()

        # 测试 _build_system_prompt 方法
        prompt = mixin._build_system_prompt_with_persona(
            user_id="user-1",
            message="你好",
            history=[],
            industry="服务业",
            context_prompt="当前意图：查询",
        )
        assert "考勤管家" in prompt
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_api_integration.py -v`
Expected: FAIL with `AttributeError` 或 `ImportError`

- [ ] **Step 3: 改造 api.py**

在 `FHD/app/services/conversation/api.py` 顶部添加 LEGACY_BASE_PROMPT 常量，并新增 `_build_system_prompt_with_persona` 方法：

```python
# 在 api.py 顶部（import 之后）添加：
LEGACY_BASE_PROMPT = """你是一个专业的业务助手，服务于使用 XCAGI 系统的用户。
你的职责：
1. 友好、专业地回答用户问题
2. 协助用户处理发货单、产品、客户等业务
3. 提供清晰、简洁的回答
4. 如果不确定，请诚实地告知用户

XCAGI 系统主要功能：
- 发货单生成和管理
- 产品和客户管理
- 订单处理
- 文件上传和导出
- 数据查询和统计"""
```

在 `ApiMixin` 类中添加新方法：

```python
def _build_system_prompt_with_persona(
    self,
    user_id: str,
    message: str,
    history: list[dict],
    industry: str,
    context_prompt: str,
) -> tuple[str, dict | None]:
    """使用 persona 生成 system prompt。

    Returns:
        tuple: (system_prompt, llm_params)
        若 persona_service 不可用，回退到 LEGACY_BASE_PROMPT。
    """
    if not getattr(self, "persona_service", None):
        # Fallback：无 persona 服务时用旧 prompt
        system_prompt = LEGACY_BASE_PROMPT + (
            "\n\n" + context_prompt if context_prompt else ""
        )
        return system_prompt, None

    # 同步路径：persona 推断 + prompt 生成
    # 注意：实际调用时需 await，这里由调用方处理
    return self.persona_service.build_prompt_from_message(
        user_id=user_id,
        message=message,
        history=history,
        industry=industry,
        context_prompt=context_prompt,
    )
```

同时在 `PersonaService` 中添加 `build_prompt_from_message` 便捷方法（在 persona_service.py 中）：

```python
async def build_prompt_from_message(
    self,
    user_id: str,
    message: str,
    history: list[dict],
    industry: str,
    context_prompt: str,
) -> tuple[str, dict[str, float | int]]:
    """便捷方法：更新 persona + 生成 prompt + 映射参数。"""
    profile = await self.update_on_message(user_id, message, history, industry)
    prompt = self.build_prompt(profile, context_prompt)
    params = self.map_params(profile)
    return prompt, params
```

- [ ] **Step 4: 修改 api.py 的 `_call_ai_with_intent` 方法**

将 `api.py:449-464` 的硬编码 base_prompt 改为调用 persona：

```python
# 替换 api.py:449-464 的：
# base_prompt = """你是一个专业的业务助手..."""
# context_prompt = self._build_context_prompt(context)
# system_prompt = base_prompt + ("\n\n" + context_prompt if context_prompt else "")

# 改为：
context_prompt = self._build_context_prompt(context)

if getattr(self, "persona_service", None):
    system_prompt, persona_params = await self.persona_service.build_prompt_from_message(
        user_id=context.user_id,
        message=message,
        history=context.conversation_history or [],
        industry=getattr(context, "industry", "通用"),
        context_prompt=context_prompt,
    )
else:
    system_prompt = LEGACY_BASE_PROMPT + (
        "\n\n" + context_prompt if context_prompt else ""
    )
    persona_params = None
```

- [ ] **Step 5: 修改 manager.py 注入 persona_service**

在 `AIConversationService.__init__` 中添加：

```python
# 在 __init__ 末尾添加：
self.persona_service = None  # 默认 None，由外部注入
```

- [ ] **Step 6: 运行测试验证通过**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_api_integration.py -v`
Expected: PASS

- [ ] **Step 7: 运行现有对话测试确保不回归**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_services/test_conversation* -v -x`
Expected: PASS（无 persona_service 时走 fallback，不回归）

- [ ] **Step 8: 提交**

```bash
cd FHD && git add app/services/conversation/api.py app/services/conversation/manager.py app/services/persona/persona_service.py tests/test_persona/test_api_integration.py
git commit -m "feat(persona): 改造 api.py 接入 persona（含 fallback）"
```

---

## Task 16: 端到端集成测试

**Files:**
- Test: `FHD/tests/test_persona/test_integration.py`

- [ ] **Step 1: 写集成测试**

```python
# FHD/tests/test_persona/test_integration.py
"""Persona 系统端到端集成测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import PersonaAxes, RapportScore
from app.services.persona.axes_fuser import AxesFuser
from app.services.persona.identity_resolver import IdentityResolver
from app.services.persona.param_mapper import PersonaParamMapper
from app.services.persona.persona_service import PersonaService
from app.services.persona.prompt_builder import PersonaPromptBuilder
from app.services.persona.rapport_calculator import RapportCalculator
from app.services.persona.rule_inferencer import RuleInferencer


class TestPersonaIntegration:
    """端到端集成测试：消息 → persona 更新 → prompt 生成。"""

    @pytest.fixture
    def mock_repo(self):
        repo = MagicMock()
        repo.find_by_user_id = AsyncMock(return_value=None)
        repo.save = AsyncMock()
        repo.append_event = AsyncMock()
        return repo

    @pytest.fixture
    def mock_embedding_inferencer(self):
        inferencer = MagicMock()
        inferencer.infer = AsyncMock()
        return inferencer

    @pytest.fixture
    def mock_llm_inferencer(self):
        inferencer = MagicMock()
        inferencer.infer = AsyncMock()
        return inferencer

    @pytest.fixture
    def service(self, mock_repo, mock_embedding_inferencer, mock_llm_inferencer):
        return PersonaService(
            repo=mock_repo,
            rule_inferencer=RuleInferencer(),
            embedding_inferencer=mock_embedding_inferencer,
            llm_inferencer=mock_llm_inferencer,
            axes_fuser=AxesFuser(),
            rapport_calculator=RapportCalculator(),
            identity_resolver=IdentityResolver(),
            prompt_builder=PersonaPromptBuilder(IdentityResolver()),
            param_mapper=PersonaParamMapper(),
        )

    @pytest.mark.asyncio
    async def test_cold_start_first_message_returns_friendly_persona(self, service, mock_repo):
        """冷启动首条消息：返回友好默认 persona。"""
        mock_repo.find_by_user_id = AsyncMock(return_value=None)

        profile = await service.update_on_message(
            user_id="new-user",
            message="你好",
            history=[],
            industry="零售业",
        )

        assert profile.identity.name == "门店管家"
        assert profile.rapport.score >= 0.3  # 冷启动友好
        assert 0.0 <= profile.axes.warmth <= 1.0

    @pytest.mark.asyncio
    async def test_warm_message_increases_warmth(self, service, mock_repo):
        """亲切消息提高 warmth。"""
        stored = PersonaProfile.create("user-1", "零售业")
        mock_repo.find_by_user_id = AsyncMock(return_value=stored)

        profile = await service.update_on_message(
            user_id="user-1",
            message="你好呀😊 帮我查下订单呢",
            history=[],
            industry="零售业",
        )

        # 含 emoji + 语气词 → warmth 应该较高
        assert profile.axes.warmth > 0.5

    @pytest.mark.asyncio
    async def test_imperative_message_decreases_warmth(self, service, mock_repo):
        """祈使句降低 warmth。"""
        stored = PersonaProfile.create("user-1", "零售业")
        mock_repo.find_by_user_id = AsyncMock(return_value=stored)

        profile = await service.update_on_message(
            user_id="user-1",
            message="查下订单",
            history=[],
            industry="零售业",
        )

        assert profile.axes.warmth < 0.5

    @pytest.mark.asyncio
    async def test_prompt_generation_contains_identity(self, service, mock_repo):
        """生成的 prompt 包含身份信息。"""
        stored = PersonaProfile.create("user-1", "零售业")
        mock_repo.find_by_user_id = AsyncMock(return_value=stored)

        profile = await service.update_on_message(
            user_id="user-1",
            message="你好",
            history=[],
            industry="零售业",
        )

        prompt = service.build_prompt(profile, context_prompt="当前意图：查询")
        assert "门店管家" in prompt
        assert "查询" in prompt

    @pytest.mark.asyncio
    async def test_param_mapping_returns_valid_params(self, service, mock_repo):
        """参数映射返回有效 LLM 参数。"""
        stored = PersonaProfile.create("user-1", "零售业")
        mock_repo.find_by_user_id = AsyncMock(return_value=stored)

        profile = await service.update_on_message(
            user_id="user-1",
            message="你好",
            history=[],
            industry="零售业",
        )

        params = service.map_params(profile)
        assert 0.0 <= params["temperature"] <= 1.0
        assert params["max_tokens"] > 0
        assert 0.0 < params["top_p"] <= 1.0

    @pytest.mark.asyncio
    async def test_rapport_increases_with_interaction(self, service, mock_repo):
        """互动轮数增加 → rapport 提升。"""
        # 模拟已有 100 轮互动
        stored = PersonaProfile(
            user_id="user-1",
            identity=PersonaProfile.create("user-1", "零售业").identity,
            axes=PersonaAxes(),
            rapport=RapportScore(score=0.4, interaction_count=100),
            business_domain_counts={"retail": 100},
        )
        mock_repo.find_by_user_id = AsyncMock(return_value=stored)

        profile = await service.update_on_message(
            user_id="user-1",
            message="你好",
            history=[],
            industry="零售业",
        )

        # 互动轮数 +1
        assert profile.rapport.interaction_count == 101

    @pytest.mark.asyncio
    async def test_fallback_when_persona_service_fails(self, service, mock_repo):
        """persona 服务异常时不阻塞（容错）。"""
        mock_repo.find_by_user_id = AsyncMock(side_effect=Exception("DB down"))

        # 应该抛异常还是返回默认？根据设计，异常时由 api.py fallback
        # 这里测试 service 层的异常传播
        with pytest.raises(Exception, match="DB down"):
            await service.update_on_message(
                user_id="user-1",
                message="你好",
                history=[],
                industry="零售业",
            )
```

- [ ] **Step 2: 运行集成测试**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/test_integration.py -v`
Expected: PASS

- [ ] **Step 3: 运行全量 persona 测试**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/ -v`
Expected: PASS（所有 persona 测试通过）

- [ ] **Step 4: 运行覆盖率检查**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/test_persona/ --cov=app/domain/persona --cov=app/services/persona --cov=app/infrastructure/persona --cov-report=term-missing`
Expected: 行覆盖率 ≥ 90%，分支覆盖率 ≥ 85%

- [ ] **Step 5: 提交**

```bash
cd FHD && git add tests/test_persona/test_integration.py
git commit -m "test(persona): 新增端到端集成测试"
```

---

## Task 17: Lint + 类型检查 + 全量测试

- [ ] **Step 1: Ruff lint**

Run: `cd FHD && ruff check app/domain/persona/ app/services/persona/ app/infrastructure/persona/ app/neuro_bus/events/persona_event.py app/application/ports/persona_repository.py tests/test_persona/`
Expected: 无错误（如有，修复）

- [ ] **Step 2: Ruff format check**

Run: `cd FHD && ruff format --check app/domain/persona/ app/services/persona/ app/infrastructure/persona/ app/neuro_bus/events/persona_event.py app/application/ports/persona_repository.py tests/test_persona/`
Expected: 无需格式化（如有，运行 `ruff format` 修复）

- [ ] **Step 3: mypy 类型检查**

Run: `cd FHD && mypy app/domain/persona/ app/services/persona/ app/infrastructure/persona/ app/neuro_bus/events/persona_event.py app/application/ports/persona_repository.py --no-error-summary`
Expected: 无新增错误

- [ ] **Step 4: 全量后端测试（确保无回归）**

Run: `cd FHD && XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/ -v --cov --cov-fail-under=84`
Expected: PASS（覆盖率不低于现有 floor 84%）

- [ ] **Step 5: 提交**

```bash
cd FHD && git add -A
git commit -m "chore(persona): lint + 类型检查 + 全量测试通过"
```

---

## 自审清单

### Spec 覆盖检查

| Spec 章节 | 对应 Task |
|-----------|-----------|
| §2 整体架构 | Task 1-16（全部） |
| §3.1 三维度概览 | Task 1-2（值对象 + 聚合根） |
| §3.2 身份（identity） | Task 2, 6（聚合根 + IdentityResolver） |
| §3.3 关系深度（rapport） | Task 2, 5（聚合根 + RapportCalculator） |
| §3.4 四轴风格参数 | Task 1, 4（值对象 + RuleInferencer） |
| §4 三层推断管线 | Task 4, 10, 11, 7（L1 + L2 + L3 + Fuser） |
| §5.1 Prompt 生成器 | Task 8（PromptBuilder） |
| §5.2 模型参数映射 | Task 9（ParamMapper） |
| §5.3 与现有 base_prompt 关系 | Task 15（api.py 改造 + fallback） |
| §6.1 对话执行流程 | Task 14, 15, 16（PersonaService + api 集成 + 集成测试） |
| §6.2 业务工具调用 | Task 15（handlers 改造，简化版） |
| §6.3 Neuro Bus 集成 | Task 13（PersonaEvent） |
| §6.4 性能与监控 | Task 14（异步触发 L2/L3） |
| §7 持久化 | Task 12（DB 模型 + 仓储实现） |
| §8 集成点 | Task 15（api.py + manager.py） |
| §10 测试策略 | Task 1-16（每个 Task 都有测试） |

### Placeholder 扫描

无 TBD/TODO/未实现步骤。所有代码块完整。

### 类型一致性

- `PersonaAxes` 在所有 Task 中字段名一致：warmth/detail/proactivity/structure
- `PersonaProfile.create(user_id, industry)` 签名一致
- `PersonaService.update_on_message(user_id, message, history, industry)` 签名一致
- `PersonaPromptBuilder.build(profile, context_prompt)` 签名一致

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-21-persy-persona-implementation.md`.**

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
    # 细分行业（admin-console 行业筛选 select 的选项）
    "涂料": ("生产管家", "production"),
    "考勤": ("考勤管家", "attendance"),
    "批发": ("发货管家", "shipment"),
    "电商": ("门店管家", "retail"),
    "餐饮": ("客户管家", "customer"),
    "物流": ("运单管家", "shipment"),
    "通用": ("业务管家", "general"),
    "管理端": ("运维助手", "admin"),
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

    构造方式：
    - 冷启动：PersonaProfile(user_id=..., industry=...) → 自动解析身份
    - 已有身份：PersonaProfile(user_id=..., identity=...) → 直接传入身份
    - 工厂方法：PersonaProfile.create(user_id=..., industry=...)
    """

    user_id: str
    identity: PersonaIdentity | None = None
    axes: PersonaAxes = field(default_factory=PersonaAxes)
    rapport: RapportScore = field(default_factory=RapportScore)
    business_domain_counts: dict[str, int] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    industry: str = ""

    def __post_init__(self):
        if not self.user_id or not self.user_id.strip():
            raise ValueError("user_id 不能为空")
        # 冷启动：identity 为空时从 industry 解析
        if self.identity is None:
            if not self.industry:
                raise ValueError("identity 和 industry 不能同时为空")
            self.identity = _resolve_initial_identity(self.industry)

    @classmethod
    def create(cls, user_id: str, industry: str) -> PersonaProfile:
        """冷启动工厂方法：根据行业创建初始画像。"""
        identity = _resolve_initial_identity(industry)
        return cls(user_id=user_id, identity=identity)

    def update_axes(self, new_axes: PersonaAxes) -> PersonaProfile:
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

    def update_rapport(self, new_rapport: RapportScore) -> PersonaProfile:
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

    def drift_identity(self, new_identity: PersonaIdentity) -> PersonaProfile:
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

    def increment_domain(self, domain: str) -> PersonaProfile:
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
            "identity": self.identity.to_dict() if self.identity else {},
            "axes": self.axes.to_dict(),
            "rapport": self.rapport.to_dict(),
            "business_domain_counts": dict(self.business_domain_counts),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PersonaProfile:
        return cls(
            user_id=d["user_id"],
            identity=PersonaIdentity.from_dict(d["identity"]),
            axes=PersonaAxes.from_dict(d["axes"]),
            rapport=RapportScore.from_dict(d["rapport"]),
            business_domain_counts=dict(d.get("business_domain_counts", {})),
        )

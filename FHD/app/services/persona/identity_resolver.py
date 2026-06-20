"""身份解析器：行业映射 + 业务漂移 + 关系深度演进。"""

from __future__ import annotations

from app.domain.persona.entities import PersonaProfile
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
        if profile.identity is None:
            return False
        current_domain = profile.identity.business_domain
        # 找出操作最多的业务域
        top_domain = max(
            profile.business_domain_counts, key=lambda k: profile.business_domain_counts.get(k, 0)
        )
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
        if profile.identity is None:
            return None
        top_domain = max(
            profile.business_domain_counts, key=lambda k: profile.business_domain_counts.get(k, 0)
        )
        name = _DOMAIN_IDENTITY_NAME_MAP.get(top_domain, f"{top_domain}管家")
        return PersonaIdentity(
            name=name,
            brief=f"专业地服务用户，熟悉{top_domain}业务",
            business_domain=top_domain,
            industry=profile.identity.industry,
        )

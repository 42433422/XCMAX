"""Butler 身份目录 — 原子身份枚举 + MBTI 16 型亲和映射 + 四轴派生。

三层人格模型：
1. 身份层（Identity）：枚举+复合身份，决定职责边界
2. MBTI 层：4 维倾向分数（E/I、S/N、T/F、J/P），底层模型
3. 四轴层（派生）：亲切度/详细度/主动度/结构度，从 MBTI 映射
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# 原子身份枚举（10 个）
ATOMIC_IDENTITIES: Tuple[str, ...] = (
    "考勤管家",
    "发货管家",
    "忠诚伙伴",
    "财务顾问",
    "运营参谋",
    "客服先锋",
    "数据侦探",
    "氛围管家",
    "流程教练",
    "战略参谋",
)

# MBTI 16 型 → 亲和身份（按亲和度降序）
MBTI_TO_IDENTITIES: Dict[str, Tuple[str, ...]] = {
    "ESTJ": ("考勤管家", "发货管家", "流程教练"),
    "ESTP": ("客服先锋", "氛围管家", "发货管家"),
    "ESFJ": ("忠诚伙伴", "客服先锋", "考勤管家"),
    "ESFP": ("氛围管家", "客服先锋", "忠诚伙伴"),
    "ENTJ": ("战略参谋", "流程教练", "运营参谋"),
    "ENTP": ("数据侦探", "战略参谋", "运营参谋"),
    "ENFJ": ("忠诚伙伴", "运营参谋", "客服先锋"),
    "ENFP": ("氛围管家", "忠诚伙伴", "运营参谋"),
    "ISTJ": ("考勤管家", "发货管家", "财务顾问"),
    "ISTP": ("数据侦探", "流程教练", "发货管家"),
    "ISFJ": ("忠诚伙伴", "考勤管家", "客服先锋"),
    "ISFP": ("忠诚伙伴", "氛围管家", "客服先锋"),
    "INTJ": ("财务顾问", "战略参谋", "数据侦探"),
    "INTP": ("数据侦探", "战略参谋", "流程教练"),
    "INFJ": ("忠诚伙伴", "战略参谋", "流程教练"),
    "INFP": ("忠诚伙伴", "氛围管家", "客服先锋"),
}

# MBTI 维度默认值（新用户：ENFJ 管家型）
# 语义：jp=0 → 纯 J（结构化），jp=100 → 纯 P（感知型）
DEFAULT_MBTI_EI = 65  # 偏 E
DEFAULT_MBTI_SN = 60  # 偏 N
DEFAULT_MBTI_TF = 70  # 偏 F
DEFAULT_MBTI_JP = 40  # 偏 J（< 50 = J）

# 四轴映射权重
# 亲切度 = 0.7*tf + 0.3*ei（F 更亲切，E 略亲切）
# 详细度 = 0.7*sn + 0.3*jp（N 更发散，P 更探索）
# 主动度 = 0.7*ei + 0.3*(100-jp)（E 更主动，J 更推进）
# 结构度 = 0.7*(100-jp) + 0.3*(100-sn)（J 更结构化，S 更就事论事）


def derive_mbti_type(ei: int, sn: int, tf: int, jp: int) -> str:
    """从 4 维分数派生 16 型标签。"""
    e = "E" if ei >= 50 else "I"
    n = "N" if sn >= 50 else "S"
    f = "F" if tf >= 50 else "T"
    p = "P" if jp >= 50 else "J"
    return f"{e}{n}{f}{p}"


def derive_four_axes(ei: int, sn: int, tf: int, jp: int) -> Dict[str, int]:
    """从 MBTI 4 维派生四轴分数（0-100）。

    语义：jp=0 → 纯 J（结构化），jp=100 → 纯 P（感知型）

    亲切度 = 0.7*tf + 0.3*ei
    详细度 = 0.7*sn + 0.3*jp
    主动度 = 0.7*ei + 0.3*(100-jp)
    结构度 = 0.7*(100-jp) + 0.3*(100-sn)
    """
    warmth = round(0.7 * tf + 0.3 * ei)
    verbosity = round(0.7 * sn + 0.3 * jp)
    proactiveness = round(0.7 * ei + 0.3 * (100 - jp))
    structuredness = round(0.7 * (100 - jp) + 0.3 * (100 - sn))
    return {
        "warmth": _clamp(warmth),
        "verbosity": _clamp(verbosity),
        "proactiveness": _clamp(proactiveness),
        "structuredness": _clamp(structuredness),
    }


def get_identity_affinities(mbti_type: str) -> Dict[str, float]:
    """根据 MBTI 型返回各原子身份的亲和度（0-1）。

    亲和身份按顺序赋 0.9/0.7/0.5，其余 0.1。
    """
    ranked = MBTI_TO_IDENTITIES.get(mbti_type, ("忠诚伙伴", "客服先锋", "考勤管家"))
    scores: Dict[str, float] = dict.fromkeys(ATOMIC_IDENTITIES, 0.1)
    for idx, ident in enumerate(ranked):
        if idx == 0:
            scores[ident] = 0.9
        elif idx == 1:
            scores[ident] = 0.7
        else:
            scores[ident] = 0.5
    return scores


def pick_primary_identity(mbti_type: str, mod_hints: List[str] | None = None) -> str:
    """根据 MBTI 型 + MOD 提示选择主身份。

    若 mod_hints 中包含某原子身份关键词，优先选它；否则取亲和度最高的。
    """
    affinities = get_identity_affinities(mbti_type)
    if mod_hints:
        for hint in mod_hints:
            for ident in ATOMIC_IDENTITIES:
                if hint and hint in ident:
                    return ident
    return max(affinities, key=affinities.get)


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, value))


def clamp_mbti(value: int) -> int:
    """MBTI 分数钳到 0-100。"""
    return _clamp(value)

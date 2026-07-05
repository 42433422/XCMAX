"""Avatar taxonomy, prompt builder, and optional OpenAI-compatible image generation."""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


AVATAR_TYPES: Dict[str, Dict[str, Any]] = {
    "real_person": {
        "label": "真人头像",
        "aliases": ["真人", "自拍", "职业照", "生活照", "real", "photo", "portrait"],
        "intent": "真实、可信、亲近，适合需要人味和信任感的员工。",
        "visual": "realistic portrait photo, natural face, clean background",
    },
    "relationship": {
        "label": "关系型头像",
        "aliases": ["情侣", "家人", "朋友", "团队", "关系", "relationship", "team"],
        "intent": "表达关系、团队归属或协作感，适合部门、群组、搭档型员工。",
        "visual": "two-person or small-team symbolic portrait, warm relationship cues",
    },
    "anime_game": {
        "label": "动漫/游戏/虚拟角色",
        "aliases": ["动漫", "二次元", "游戏", "虚拟", "vtuber", "anime", "game", "oc"],
        "intent": "表达兴趣、性格和审美，同时保护隐私；适合原创 AI 员工形象。",
        "visual": "original anime character portrait, polished cel shading, expressive eyes",
    },
    "illustrated_self": {
        "label": "插画化本人",
        "aliases": ["插画化", "卡通化", "q版", "3d", "像素", "illustration", "cartoon"],
        "intent": "保留个人识别度，同时比真人更风格化。",
        "visual": "stylized illustrated portrait, friendly face, simplified features",
    },
    "professional_brand": {
        "label": "职业/品牌型头像",
        "aliases": ["品牌", "职业", "logo", "工牌", "公司", "business", "brand"],
        "intent": "强调专业、统一和品牌识别，适合 AI 员工矩阵。",
        "visual": "professional avatar, brand-color outfit, subtle role icon, SaaS product polish",
    },
    "pet_mascot": {
        "label": "动物/宠物/吉祥物",
        "aliases": ["宠物", "动物", "猫", "狗", "吉祥物", "mascot", "pet"],
        "intent": "亲和、可爱、轻松，适合陪伴、客服、社区运营类员工。",
        "visual": "cute mascot portrait, friendly animal-inspired character, clean icon silhouette",
    },
    "interest_symbol": {
        "label": "兴趣符号型",
        "aliases": ["兴趣", "符号", "车", "相机", "音乐", "代码", "咖啡", "hobby", "symbol"],
        "intent": "用爱好或职业符号表达身份，适合工具型和专家型员工。",
        "visual": "single symbolic object with character hints, crisp icon-like composition",
    },
    "abstract_mood": {
        "label": "抽象/氛围型",
        "aliases": ["抽象", "氛围", "风景", "背影", "剪影", "abstract", "mood"],
        "intent": "表达情绪、审美和神秘感，适合不需要强人脸识别的员工。",
        "visual": "abstract atmospheric avatar, cinematic silhouette, minimal details",
    },
    "minimal_default": {
        "label": "默认/极简型",
        "aliases": ["默认", "极简", "字母", "几何", "占位", "minimal", "default"],
        "intent": "低成本、统一、清爽，适合系统账号或批量员工占位。",
        "visual": "minimal geometric avatar, monogram-like shape, high contrast",
    },
}

ROLE_SYMBOLS = [
    ("客服", "headset, chat bubble"),
    ("助理", "small assistant badge, sparkle"),
    ("开发", "code brackets, terminal glow"),
    ("研发", "code brackets, terminal glow"),
    ("数据", "tiny chart glyph, dashboard light"),
    ("销售", "growth arrow, handshake cue"),
    ("获客", "magnet, growth arrow"),
    ("法务", "document shield, scale icon"),
    ("财务", "coin, ledger line"),
    ("设计", "pen nib, color swatch"),
    ("运营", "calendar, megaphone"),
    ("归档", "archive box, folder mark"),
]

NEGATIVE_PROMPT = (
    "low quality, blurry, noisy, deformed face, bad anatomy, extra fingers, text, watermark, "
    "logo, trademark, exact celebrity likeness, copied anime character, copyrighted character, NSFW"
)

PRESET_NEGATIVE_PROMPT = (
    "no words, no letters, no logos, no watermark, no UI labels, no captions, no duplicate faces, "
    "no copied anime character, no celebrity likeness, no hands covering the face, no muddy background"
)

PROMPT_PRESETS: Dict[str, Dict[str, Any]] = {
    "employee_avatar_sheet": {
        "label": "AI 员工批量头像表",
        "aliases": ["sheet", "sprite", "batch", "批量", "头像表", "员工头像表"],
        "usage": "一次生成 4x3 头像表，再裁成单张移动端头像。",
        "prompt_en": (
            "Create an original set of 12 beautiful anime-style profile avatars for AI employees. "
            "Each avatar is a distinct fictional character, polished and profile-ready. "
            "Subject: 12 head-and-shoulders anime portraits, varied hair colors, facial expressions, "
            "eyewear/headsets, modern work outfits, subtle role props like tiny document, code glyph, "
            "shield pin, chart pin, phone pin, database pin, but no text. "
            "Style: modern polished anime portrait, clean digital lineart, soft cel shading, luminous eyes, "
            "premium mobile app avatar quality. "
            "Composition: exact 4 columns x 3 rows sprite sheet, each cell contains one centered square avatar, "
            "face dominant, tight head-and-shoulders crop, clean white gutters, no overlap. "
            "Lighting: friendly, confident, soft rim light, crisp highlights. "
            "Color palette: varied vibrant gradients, readable at small sizes. "
            "Constraints: no letters, no words, no watermarks, no logos, no UI labels, no captions, "
            "no duplicate faces, no hands covering the face, no extra people. Keep the grid easy to crop."
        ),
        "prompt_zh": (
            "生成 12 个原创 AI 员工二次元头像，4 列 x 3 行头像表。每格一个居中的方形头像，"
            "头肩近景、脸占主体、干净留白分隔，方便裁成移动端联系人头像。角色要有不同发型、表情、"
            "眼镜/耳机、现代工作服和微小岗位徽章；禁止文字、字母、水印、Logo、重复脸和遮脸手势。"
        ),
        "postprocess": ["按 4x3 网格裁切", "每格缩放到 256x256 或 512x512", "保留圆角/圆形裁切安全边距"],
    },
    "xiaoc_human_aquatic": {
        "label": "小 C 人形鱼系助理头像",
        "aliases": ["小c", "xiaoc", "fish", "鱼", "水系", "aquatic"],
        "usage": "小 C 助理专用：人形 AI 助理，鱼类元素做发饰/发色/水纹，不做鱼脸吉祥物。",
        "prompt_en": (
            "Create one premium anime-style profile avatar for an AI assistant named Xiao C. "
            "The assistant should be human-like and beautiful, with subtle fish/aquatic design elements "
            "instead of a literal fish mascot. "
            "Subject: an original young adult anime AI assistant, androgynous friendly face, aqua-blue and "
            "pearl-white hair with fin-like layered bangs, tiny koi/fish hairpin, sleek headset earpiece, "
            "soft intelligent smile, bright blue eyes, clean modern assistant outfit with subtle wave collar. "
            "Style: premium modern anime portrait, high-end mobile contact avatar, clean digital lineart, "
            "soft cel shading, expressive luminous eyes, polished hair detail, elegant not childish. "
            "Composition: square 1:1, tight head-and-shoulders portrait, face dominant, centered, app avatar ready, "
            "safe crop inside rounded square. "
            "Lighting: warm, helpful, clever, calm, trustworthy, soft rim light. "
            "Color palette: aqua, cobalt blue, pearl white, tiny violet accent, clean light gradient background "
            "with subtle bubbles/water shimmer. "
            "Constraints: no words, no letters, no logos, no watermark, no UI, no captions, no animal face, "
            "no chibi mascot, no dark background, no realistic fish photo, no extra people, no hands covering face."
        ),
        "prompt_zh": (
            "为小 C 助理生成一张高级二次元移动端联系人头像：人形 AI 助理，蓝白水系发色，"
            "鱼鳍感层次刘海，小锦鲤/鱼形发饰，精致耳机，聪明温和微笑，现代助理服装和水纹领口。"
            "构图为 1:1 方图，头肩近景，脸占主体，圆角头像安全裁切。鱼类元素只能作为发饰、发色、"
            "水纹和气质，不要鱼脸、不要低龄吉祥物、不要文字水印。"
        ),
        "postprocess": ["直接缩放为 256x256/512x512", "检查小尺寸眼睛和鱼形发饰仍可识别"],
    },
    "mobile_contact_avatar": {
        "label": "单员工移动端联系人头像",
        "aliases": ["mobile", "contact", "single", "单人", "联系人", "员工头像"],
        "usage": "给单个 AI 员工生成可上架、可放聊天列表的头像。",
        "prompt_en": (
            "Create one premium anime-style mobile contact avatar for an AI employee named {employee_name}. "
            "Role: {employee_role}. Department: {department}. Personality: {personality}. "
            "Subject: an original fictional AI employee character, head-and-shoulders portrait, face dominant, "
            "modern work outfit, subtle role cue: {symbol}. "
            "Style: polished modern anime portrait, clean digital lineart, soft cel shading, expressive eyes, "
            "high-end app avatar quality. "
            "Composition: square 1:1, centered, tight head-and-shoulders crop, safe circular crop, readable at 48px. "
            "Lighting: friendly, capable, soft rim light, crisp highlights. "
            "Color palette: {palette}, clean gradient background. "
            "Constraints: no words, no letters, no logos, no watermark, no UI labels, no copied character, "
            "no celebrity likeness, no hands covering face, no extra people."
        ),
        "prompt_zh": (
            "为「{employee_name}」生成一张高级二次元移动端联系人头像。职位：{employee_role}；部门：{department}；"
            "性格：{personality}；岗位暗示：{symbol}；配色：{palette}。要求原创虚构角色、头肩近景、"
            "脸占主体、现代工作服、干净渐变背景、圆形裁切安全、小尺寸 48px 仍清晰。禁止文字、字母、Logo、"
            "水印、照搬角色、明星脸和遮脸手势。"
        ),
        "postprocess": ["缩放为 256x256/512x512", "列表页 48px 预览检查", "圆形和圆角裁切均不切掉脸"],
    },
}


def _text_blob(payload: Dict[str, Any]) -> str:
    parts = []
    for key in (
        "task",
        "prompt",
        "avatar_type",
        "style",
        "employee_name",
        "employee_role",
        "department",
        "personality",
        "color_palette",
        "reference_notes",
    ):
        val = payload.get(key)
        if isinstance(val, (str, int, float)):
            parts.append(str(val))
    return "\n".join(parts)


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "生成", "是"}:
        return True
    if text in {"0", "false", "no", "n", "off", "不生成", "否"}:
        return False
    return default


def normalize_avatar_type(payload: Dict[str, Any]) -> str:
    raw = str(payload.get("avatar_type") or payload.get("type") or "").strip().lower()
    text = (raw + "\n" + _text_blob(payload)).lower()
    for key, spec in AVATAR_TYPES.items():
        if raw == key:
            return key
        for alias in spec["aliases"]:
            if str(alias).lower() in text:
                return key
    if any(token in text for token in ("ai", "员工", "assistant", "管家", "助理")):
        return "anime_game"
    return "professional_brand"


def _first(payload: Dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        val = payload.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return default


def _role_symbol(role_text: str) -> str:
    for keyword, symbol in ROLE_SYMBOLS:
        if keyword in role_text:
            return symbol
    return "subtle AI circuit mark, small role badge"


def prompt_preset_catalog() -> List[Dict[str, Any]]:
    return [
        {
            "id": key,
            "label": spec["label"],
            "usage": spec["usage"],
            "aliases": list(spec.get("aliases") or []),
        }
        for key, spec in PROMPT_PRESETS.items()
    ]


def _format_preset_text(template: str, values: Dict[str, str]) -> str:
    try:
        return template.format(**values)
    except KeyError:
        return template


def _select_prompt_preset(payload: Dict[str, Any], employee_name: str, avatar_type: str) -> str:
    raw = str(
        payload.get("prompt_preset")
        or payload.get("preset")
        or payload.get("template")
        or ""
    ).strip().lower()
    text = "\n".join([raw, employee_name, _text_blob(payload)]).lower()
    for preset_id, spec in PROMPT_PRESETS.items():
        if raw == preset_id or raw.replace("-", "_") == preset_id:
            return preset_id
        for alias in spec.get("aliases") or []:
            if str(alias).lower() in text:
                return preset_id
    if "小c" in text or "小 c" in text or "xiaoc" in text:
        return "xiaoc_human_aquatic"
    if any(token in text for token in ("4x3", "4 x 3", "sprite", "sheet", "批量", "头像表")):
        return "employee_avatar_sheet"
    if avatar_type in {"anime_game", "professional_brand"} and any(
        token in text for token in ("ai", "员工", "assistant", "助理", "管家")
    ):
        return "mobile_contact_avatar"
    return ""


def _build_prompt_preset(
    preset_id: str,
    *,
    employee_name: str,
    employee_role: str,
    department: str,
    personality: str,
    palette: str,
    symbol: str,
) -> Dict[str, Any]:
    spec = PROMPT_PRESETS.get(preset_id)
    if not spec:
        return {}
    values = {
        "employee_name": employee_name,
        "employee_role": employee_role,
        "department": department,
        "personality": personality,
        "palette": palette,
        "symbol": symbol,
    }
    return {
        "id": preset_id,
        "label": spec["label"],
        "usage": spec["usage"],
        "prompt_zh": _format_preset_text(str(spec["prompt_zh"]), values),
        "prompt_en": _format_preset_text(str(spec["prompt_en"]), values),
        "negative_prompt": PRESET_NEGATIVE_PROMPT,
        "postprocess": list(spec.get("postprocess") or []),
    }


def _style_modifier(avatar_type: str, style: str) -> str:
    base = style.strip()
    if base:
        return base
    if avatar_type == "anime_game":
        return "clean original anime avatar, premium SaaS employee portrait"
    if avatar_type == "professional_brand":
        return "modern professional SaaS avatar, refined corporate visual identity"
    if avatar_type == "minimal_default":
        return "minimal vector avatar, strong silhouette"
    if avatar_type == "real_person":
        return "realistic professional portrait photography"
    return "polished social profile avatar"


def build_avatar_profile(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload or {})
    avatar_type = normalize_avatar_type(payload)
    spec = AVATAR_TYPES[avatar_type]
    employee_name = _first(payload, "employee_name", "name", "display_name", default="AI 员工")
    employee_role = _first(payload, "employee_role", "role", "job", default="企业 AI 员工")
    department = _first(payload, "department", "team", default="XC AGI")
    personality = _first(payload, "personality", "persona", default="可靠、聪明、清爽、有辨识度")
    palette = _first(payload, "color_palette", "palette", "colors", default="blue, violet, white")
    target_platform = _first(payload, "target_platform", "platform", default="AI 员工头像 / 移动端圆形头像")
    style = _style_modifier(avatar_type, _first(payload, "style", "art_style", default=""))
    role_text = f"{employee_role} {department} {_text_blob(payload)}"
    symbol = _first(payload, "symbol", "icon", default=_role_symbol(role_text))
    selected_preset = _select_prompt_preset(payload, employee_name, avatar_type)
    preset = _build_prompt_preset(
        selected_preset,
        employee_name=employee_name,
        employee_role=employee_role,
        department=department,
        personality=personality,
        palette=palette,
        symbol=symbol,
    )
    composition = (
        "single clear subject, centered head-and-shoulders, safe circular crop, strong silhouette, "
        "high contrast, readable at 48px, no small text"
    )
    identity = f"{employee_name}, {employee_role}, {department}"
    prompt_en = (
        f"Create an original profile avatar for {identity}. Avatar category: {spec['label']} "
        f"({spec['intent']}). Visual direction: {spec['visual']}. Style: {style}. "
        f"Personality: {personality}. Color palette: {palette}. Include subtle role symbol: {symbol}. "
        f"Composition: {composition}. 1:1 square, crisp edges, premium app icon quality, polished lighting."
    )
    prompt_zh = (
        f"为「{employee_name}」生成原创头像，职位/身份是「{employee_role}」，部门是「{department}」。"
        f"头像类型：{spec['label']}；用途：{target_platform}。"
        f"风格：{style}；性格：{personality}；配色：{palette}；职能符号：{symbol}。"
        "构图要求：单一主体，头肩近景，圆形裁切安全，高对比，小尺寸可读，禁止小字、商标、明星脸和具体 IP。"
    )
    if preset:
        prompt_en = str(preset["prompt_en"])
        prompt_zh = str(preset["prompt_zh"])
    return {
        "employee_name": employee_name,
        "employee_role": employee_role,
        "department": department,
        "avatar_type": avatar_type,
        "avatar_type_label": spec["label"],
        "avatar_type_intent": spec["intent"],
        "target_platform": target_platform,
        "style": style,
        "personality": personality,
        "color_palette": palette,
        "symbol": symbol,
        "composition": composition,
        "prompt": prompt_zh + "\n\nEnglish prompt:\n" + prompt_en,
        "prompt_zh": prompt_zh,
        "prompt_en": prompt_en,
        "prompt_preset": preset or None,
        "prompt_preset_catalog": prompt_preset_catalog(),
        "negative_prompt": NEGATIVE_PROMPT,
        "preset_negative_prompt": preset.get("negative_prompt") if preset else "",
        "crop_safety": {
            "aspect_ratio": "1:1",
            "safe_shape": "circle",
            "min_readable_size": "48px",
            "rules": ["主体居中", "脸/符号不要贴边", "背景不要抢主体", "不放文字水印"],
        },
        "taxonomy": [
            {"id": key, "label": item["label"], "intent": item["intent"]}
            for key, item in AVATAR_TYPES.items()
        ],
    }


def _image_credentials(provider: str) -> Tuple[str, str, str]:
    provider = (provider or "doubao").strip().lower()
    if provider == "doubao":
        return (
            os.environ.get("DOUBAO_API_KEY") or os.environ.get("ARK_API_KEY") or "",
            (os.environ.get("DOUBAO_BASE_URL") or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/"),
            "doubao-seedream-5-0-260128",
        )
    if provider == "openai":
        return (
            os.environ.get("OPENAI_API_KEY") or "",
            (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/"),
            "gpt-image-1",
        )
    return "", "", ""


def _write_data_url(data_url: str, output_path: Path, index: int) -> str:
    m = re.match(r"^data:image/([a-zA-Z0-9.+-]+);base64,(.+)$", data_url, re.S)
    if not m:
        return ""
    ext = "jpg" if m.group(1).lower() in {"jpeg", "jpg"} else "png"
    img_path = output_path.with_name(f"avatar_{index}.{ext}")
    img_path.write_bytes(base64.b64decode(m.group(2)))
    return str(img_path)


async def _generate_images(profile: Dict[str, Any], payload: Dict[str, Any], output_path: Path) -> Dict[str, Any]:
    provider = _first(payload, "provider", "image_provider", default="doubao").lower()
    key, base_url, default_model = _image_credentials(provider)
    model = _first(payload, "model", "image_model", default=default_model)
    size = _first(payload, "size", "image_size", default="1024x1024")
    try:
        n = max(1, min(int(payload.get("n") or payload.get("count") or 1), 4))
    except (TypeError, ValueError):
        n = 1
    if not key or not base_url:
        return {
            "ok": False,
            "images": [],
            "provider": provider,
            "model": model,
            "warning": f"供应商 {provider} 未配置生图 API Key，已返回提示词。",
        }
    try:
        import httpx
    except ImportError:
        return {
            "ok": False,
            "images": [],
            "provider": provider,
            "model": model,
            "warning": "httpx 不可用，已返回提示词。",
        }
    body = {"model": model, "prompt": profile["prompt_en"], "size": size, "n": n}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{base_url}/images/generations", headers=headers, json=body)
    if resp.status_code >= 400:
        return {
            "ok": False,
            "images": [],
            "provider": provider,
            "model": model,
            "status": resp.status_code,
            "warning": resp.text[:800],
        }
    data = resp.json()
    images: List[Dict[str, Any]] = []
    for idx, item in enumerate(data.get("data") or [], start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        b64 = str(item.get("b64_json") or "").strip()
        if url:
            images.append({"url": url, "local_path": ""})
        elif b64:
            data_url = f"data:image/png;base64,{b64}"
            images.append({"url": data_url, "local_path": _write_data_url(data_url, output_path, idx)})
    return {"ok": bool(images), "images": images, "provider": provider, "model": model, "raw": data}


async def convert_avatar_profile(
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    *,
    output_path: Path,
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    del ctx, rule_spec
    payload = dict(payload or {})
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    profile = build_avatar_profile(payload)
    warnings: List[str] = []
    image_result: Dict[str, Any] = {"ok": False, "images": [], "skipped": True}
    generate_image = _as_bool(payload.get("generate_image"), default=True)
    if generate_image:
        image_result = await _generate_images(profile, payload, output_path)
        if not image_result.get("ok"):
            warn = str(image_result.get("warning") or "生图未返回图片，已保留提示词。")
            warnings.append(warn)
    result = {
        "ok": True,
        "summary": f"已生成「{profile['avatar_type_label']}」头像方案：{profile['employee_name']} / {profile['employee_role']}",
        "profile": profile,
        "image_generation": image_result,
        "outputs": {
            "profile_json": str(output_path),
            "image_count": len(image_result.get("images") or []),
            "images": image_result.get("images") or [],
        },
        "warnings": warnings,
    }
    if _as_bool(payload.get("require_image"), default=False) and not (image_result.get("images") or []):
        result["ok"] = False
        result["summary"] = "已生成头像提示词，但未生成图片。"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result

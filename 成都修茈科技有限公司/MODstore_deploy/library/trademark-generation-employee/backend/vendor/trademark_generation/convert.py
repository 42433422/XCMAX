"""Trademark taxonomy, prompt builder, and optional OpenAI-compatible image generation."""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

TRADEMARK_TYPES: Dict[str, Dict[str, Any]] = {
    "wordmark": {
        "label": "文字商标",
        "aliases": ["文字", "字标", "wordmark", "字体", "品牌名", "中文名", "英文名"],
        "intent": "突出品牌名称和可读性，适合名称本身有记忆点的品牌。",
        "visual": "custom wordmark typography, unique letter rhythm, clean spacing",
    },
    "lettermark": {
        "label": "字母商标",
        "aliases": ["字母", "首字母", "monogram", "letter", "缩写", "initial"],
        "intent": "用缩写建立高识别度，适合长品牌名、集团和工具产品。",
        "visual": "distinct monogram symbol, geometric letter fusion, strong silhouette",
    },
    "pictorial_symbol": {
        "label": "图形商标",
        "aliases": ["图形", "图标", "icon", "symbol", "logo mark", "标志"],
        "intent": "用单一图形表达行业和品牌资产，便于 favicon、App 和包装使用。",
        "visual": "simple pictorial logo mark, memorable icon, balanced negative space",
    },
    "abstract_mark": {
        "label": "抽象商标",
        "aliases": ["抽象", "几何", "abstract", "shape", "符号化", "科技感"],
        "intent": "避开具体物象，用独特形状表达速度、连接、智能或可靠感。",
        "visual": "abstract geometric logo, proprietary shape language, crisp vector edges",
    },
    "mascot_mark": {
        "label": "吉祥物商标",
        "aliases": ["吉祥物", "mascot", "角色", "ip形象", "动物", "人物"],
        "intent": "强化亲和力和记忆点，适合客服、社区、餐饮和儿童/生活方式品牌。",
        "visual": "original mascot head logo, friendly expression, simplified vector character",
    },
    "combination_mark": {
        "label": "组合商标",
        "aliases": ["组合", "图文", "图文组合", "combination", "logo+文字", "商标"],
        "intent": "同时保留图形和品牌名，适合新品牌初期建立识别。",
        "visual": "logo mark plus wordmark lockup, scalable brand identity system",
    },
    "badge_seal": {
        "label": "徽章/印章",
        "aliases": ["徽章", "印章", "章", "badge", "seal", "认证", "协会"],
        "intent": "表达资质、传统、可信或会员体系，适合服务认证和活动标识。",
        "visual": "badge logo, simple seal geometry, official but modern layout",
    },
    "app_icon": {
        "label": "App 图标",
        "aliases": ["app", "应用", "icon", "图标", "favicon", "小程序", "移动端"],
        "intent": "在手机桌面、浏览器标签和应用市场中保持强识别。",
        "visual": "app icon logo, rounded-square safe composition, bold central glyph",
    },
    "package_label": {
        "label": "包装标签",
        "aliases": ["包装", "标签", "label", "瓶贴", "外卖", "店铺", "电商"],
        "intent": "用于商品包装、贴纸和店铺物料，强调货架可见性。",
        "visual": "package label mark, shelf-readable logo, print-safe composition",
    },
}

INDUSTRY_SYMBOLS = [
    ("ai", "neural node, spark, assistant glyph"),
    ("人工智能", "neural node, spark, assistant glyph"),
    ("科技", "connected nodes, clean circuit arc"),
    ("软件", "window glyph, code bracket, cursor point"),
    ("餐饮", "bowl, leaf, steam curve"),
    ("咖啡", "cup silhouette, bean curve"),
    ("教育", "open book, upward path"),
    ("法律", "shield, balanced scale, document corner"),
    ("法务", "shield, balanced scale, document corner"),
    ("财务", "ledger line, coin circle, secure check"),
    ("医疗", "cross-safe abstract care symbol"),
    ("美妆", "petal, mirror curve, soft sparkle"),
    ("服装", "thread loop, label tag, fabric fold"),
    ("物流", "route arrow, box, motion line"),
    ("电商", "tag, cart arc, package check"),
    ("游戏", "original controller-like glyph, energy shard"),
    ("设计", "pen nib, color tile, grid mark"),
]

NEGATIVE_PROMPT = (
    "existing logo, famous brand mark, trademark infringement, copied symbol, copyrighted character, "
    "government emblem, national flag, sports team logo, luxury brand style, app store icon clone, "
    "stock logo template, watermark, mockup text, tiny unreadable details, messy gradients, blurry, low quality"
)

PROMPT_PRESETS: Dict[str, Dict[str, Any]] = {
    "brand_mark_sheet": {
        "label": "商标方向九宫格",
        "aliases": ["九宫格", "多方案", "批量", "sheet", "brand sheet", "logo sheet"],
        "usage": "一次生成 9 个原创商标方向，便于挑选后再精修。",
        "prompt_en": (
            "Create a 3x3 exploration sheet of nine original logo/trademark concepts for {brand_name}. "
            "Industry: {industry}. Audience: {audience}. Brand values: {brand_values}. "
            "Each cell contains one distinct vector-style logo direction: wordmark, monogram, pictorial symbol, "
            "abstract mark, mascot mark, combination mark, badge/seal, app icon, package label. "
            "Use clean flat vector geometry, strong silhouettes, clear negative space, print-safe colors, "
            "and no resemblance to existing brands. No small text except optional placeholder brand name."
        ),
        "prompt_zh": (
            "为「{brand_name}」生成 3x3 商标方向九宫格。行业：{industry}；受众：{audience}；品牌价值：{brand_values}。"
            "九格分别探索文字商标、字母商标、图形商标、抽象商标、吉祥物商标、组合商标、徽章/印章、App 图标、包装标签。"
            "要求平面矢量感、轮廓强、负空间清楚、印刷安全、不要近似任何现有品牌。"
        ),
        "postprocess": [
            "选 1-2 个方向精修",
            "做黑白/反白/24px 小尺寸检查",
            "转 SVG 并清理锚点",
        ],
    },
    "startup_combination_mark": {
        "label": "新品牌图文组合商标",
        "aliases": ["startup", "新品牌", "图文组合", "组合商标", "公司商标"],
        "usage": "适合公司/产品初期，用图形 + 字标建立完整识别。",
        "prompt_en": (
            "Create one original combination logo/trademark for {brand_name}. Industry: {industry}. "
            "Audience: {audience}. Brand values: {brand_values}. Symbol cue: {symbol}. "
            "Design a unique geometric logo mark plus clean custom wordmark lockup. "
            "Style: {style}. Palette: {palette}. The mark must work in black and white, at 24px, on business card, "
            "website header, app splash screen, and package sticker. Avoid any resemblance to famous brands."
        ),
        "prompt_zh": (
            "为「{brand_name}」生成原创图文组合商标。行业：{industry}；受众：{audience}；品牌价值：{brand_values}；"
            "行业符号暗示：{symbol}；风格：{style}；配色：{palette}。"
            "输出要包含独特几何图形和清晰字标组合，黑白版、小尺寸 24px、名片、官网头部、启动页和贴纸都能使用，避免近似知名品牌。"
        ),
        "postprocess": ["拆分图形标和横版组合", "导出 SVG/PDF/PNG", "做黑白版和单色版"],
    },
    "app_icon_mark": {
        "label": "App 图标商标",
        "aliases": ["app icon", "应用图标", "favicon", "小程序图标", "手机桌面"],
        "usage": "适合 App、SaaS、插件和小程序入口图标。",
        "prompt_en": (
            "Create one original app icon trademark for {brand_name}. Industry: {industry}. "
            "Use a bold central glyph based on {symbol}, rounded-square safe composition, minimal vector geometry, "
            "high contrast, readable at 24px and 48px. Style: {style}. Palette: {palette}. "
            "No letters unless the brand explicitly requires a short monogram; no resemblance to existing app icons."
        ),
        "prompt_zh": (
            "为「{brand_name}」生成原创 App 图标商标。行业：{industry}；核心符号：{symbol}；风格：{style}；配色：{palette}。"
            "圆角方形安全构图，中心图形强，几何简洁，高对比，24px/48px 仍清晰。除非明确要求缩写，否则不要放字母；不要近似现有 App 图标。"
        ),
        "postprocess": [
            "导出 1024/512/256/128/64/32/16px",
            "检查圆角安全边距",
            "做 favicon 简化版",
        ],
    },
    "package_label_mark": {
        "label": "包装标签商标",
        "aliases": ["包装标签", "瓶贴", "贴纸", "货架", "package", "label"],
        "usage": "适合商品包装、外卖贴纸、瓶贴、门店和电商主图。",
        "prompt_en": (
            "Create one original package-label trademark for {brand_name}. Product/industry: {industry}. "
            "Audience: {audience}. Brand values: {brand_values}. Make it shelf-readable, print-safe, "
            "with a strong emblem or label shape, clear lockup, and optional short tagline area. "
            "Style: {style}. Palette: {palette}. Avoid stock label templates and famous brand similarity."
        ),
        "prompt_zh": (
            "为「{brand_name}」生成原创包装标签商标。产品/行业：{industry}；受众：{audience}；品牌价值：{brand_values}。"
            "要求货架可见、印刷安全、轮廓强，可用于贴纸/瓶贴/外卖包装/电商主图；风格：{style}；配色：{palette}。"
            "不要套用图库模板，不要近似知名品牌。"
        ),
        "postprocess": [
            "转 CMYK 前检查对比",
            "准备横版/竖版/圆形贴纸版本",
            "保留出血和安全边距",
        ],
    },
}


def _text_blob(payload: Dict[str, Any]) -> str:
    parts = []
    for key in (
        "task",
        "prompt",
        "trademark_type",
        "logo_type",
        "style",
        "brand_name",
        "industry",
        "audience",
        "brand_values",
        "reference_notes",
        "usage",
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


def _first(payload: Dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        val = payload.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return default


def normalize_trademark_type(payload: Dict[str, Any]) -> str:
    raw = (
        str(
            payload.get("trademark_type")
            or payload.get("logo_type")
            or payload.get("type")
            or ""
        )
        .strip()
        .lower()
    )
    text = (raw + "\n" + _text_blob(payload)).lower()
    if raw in TRADEMARK_TYPES:
        return raw
    if any(
        token in text
        for token in ("app", "favicon", "应用", "小程序", "移动端", "手机桌面")
    ):
        return "app_icon"
    if any(
        token in text
        for token in ("包装", "标签", "贴纸", "瓶贴", "货架", "package", "label")
    ):
        return "package_label"
    if any(
        token in text for token in ("字母", "缩写", "首字母", "monogram", "lettermark")
    ):
        return "lettermark"
    for key, spec in TRADEMARK_TYPES.items():
        for alias in spec["aliases"]:
            if str(alias).lower() in text:
                return key
    return "combination_mark"


def _industry_symbol(industry_text: str) -> str:
    low = industry_text.lower()
    for keyword, symbol in INDUSTRY_SYMBOLS:
        if keyword.lower() in low:
            return symbol
    return "simple proprietary geometric symbol, memorable negative space"


def _style_modifier(mark_type: str, style: str) -> str:
    base = style.strip()
    if base:
        return base
    if mark_type == "app_icon":
        return "modern SaaS app icon, flat vector, high contrast"
    if mark_type == "badge_seal":
        return "modern trustworthy badge, clean seal geometry"
    if mark_type == "mascot_mark":
        return "friendly original mascot logo, simplified vector character"
    if mark_type in {"wordmark", "lettermark"}:
        return "custom typography, refined spacing, premium brand identity"
    return "modern premium vector logo, simple geometry, distinctive silhouette"


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


def _select_prompt_preset(
    payload: Dict[str, Any], brand_name: str, mark_type: str
) -> str:
    raw = (
        str(
            payload.get("prompt_preset")
            or payload.get("preset")
            or payload.get("template")
            or ""
        )
        .strip()
        .lower()
    )
    text = "\n".join([raw, brand_name, _text_blob(payload)]).lower()
    for preset_id, spec in PROMPT_PRESETS.items():
        if raw == preset_id or raw.replace("-", "_") == preset_id:
            return preset_id
        for alias in spec.get("aliases") or []:
            if str(alias).lower() in text:
                return preset_id
    if any(token in text for token in ("九宫格", "多方案", "批量", "sheet")):
        return "brand_mark_sheet"
    if mark_type == "app_icon":
        return "app_icon_mark"
    if mark_type == "package_label":
        return "package_label_mark"
    return "startup_combination_mark"


def _build_prompt_preset(
    preset_id: str,
    *,
    brand_name: str,
    industry: str,
    audience: str,
    brand_values: str,
    style: str,
    palette: str,
    symbol: str,
) -> Dict[str, Any]:
    spec = PROMPT_PRESETS.get(preset_id)
    if not spec:
        return {}
    values = {
        "brand_name": brand_name,
        "industry": industry,
        "audience": audience,
        "brand_values": brand_values,
        "style": style,
        "palette": palette,
        "symbol": symbol,
    }
    return {
        "id": preset_id,
        "label": spec["label"],
        "usage": spec["usage"],
        "prompt_zh": _format_preset_text(str(spec["prompt_zh"]), values),
        "prompt_en": _format_preset_text(str(spec["prompt_en"]), values),
        "negative_prompt": NEGATIVE_PROMPT,
        "postprocess": list(spec.get("postprocess") or []),
    }


def _clearance_checklist(
    brand_name: str, industry: str, mark_type: str
) -> List[Dict[str, str]]:
    return [
        {
            "item": "名称近似检索",
            "action": f"检索「{brand_name}」及同音、近形、英文/拼音变体在 {industry} 相关类别中的近似商标。",
        },
        {
            "item": "图形近似检索",
            "action": "用最终图形做反向图片检索和商标图形要素检索，排查相似轮廓、负空间和组合结构。",
        },
        {
            "item": "禁用元素检查",
            "action": "确认没有国旗国徽、官方认证暗示、红十字等敏感符号，也没有知名品牌、平台、动漫游戏 IP 或体育队近似元素。",
        },
        {
            "item": "类别适配",
            "action": "根据商品/服务选择尼斯分类主类和防御类，避免只看视觉好看但类别不可用。",
        },
        {
            "item": "律师/代理复核",
            "action": "上线或申请前交给商标代理/法务做正式检索，本员工输出不构成法律意见，也不保证注册成功。",
        },
        {
            "item": "小尺寸可用性",
            "action": f"把 {TRADEMARK_TYPES[mark_type]['label']} 压到 24px、黑白、反白和单色场景检查可读性。",
        },
    ]


def build_trademark_profile(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload or {})
    mark_type = normalize_trademark_type(payload)
    spec = TRADEMARK_TYPES[mark_type]
    brand_name = _first(
        payload, "brand_name", "name", "company", "product_name", default="新品牌"
    )
    industry = _first(
        payload, "industry", "category", "business", default="AI 软件 / 企业服务"
    )
    audience = _first(
        payload,
        "audience",
        "target_user",
        "target_audience",
        default="企业客户和专业用户",
    )
    brand_values = _first(
        payload,
        "brand_values",
        "values",
        "personality",
        default="可靠、聪明、高效、有温度",
    )
    palette = _first(
        payload,
        "color_palette",
        "palette",
        "colors",
        default="deep blue, clean white, fresh green accent",
    )
    usage = _first(
        payload,
        "usage",
        "target_platform",
        "platform",
        default="官网、App 图标、名片、包装、市场页",
    )
    style = _style_modifier(
        mark_type, _first(payload, "style", "art_style", default="")
    )
    symbol = _first(
        payload,
        "symbol",
        "icon",
        default=_industry_symbol(f"{industry} {_text_blob(payload)}"),
    )
    selected_preset = _select_prompt_preset(payload, brand_name, mark_type)
    preset = _build_prompt_preset(
        selected_preset,
        brand_name=brand_name,
        industry=industry,
        audience=audience,
        brand_values=brand_values,
        style=style,
        palette=palette,
        symbol=symbol,
    )
    composition = (
        "vector-first logo, strong silhouette, clear negative space, black-and-white compatible, "
        "readable at 24px, no tiny details, scalable lockup"
    )
    prompt_en = (
        f"Create an original trademark/logo for {brand_name}. Trademark category: {spec['label']} "
        f"({spec['intent']}). Industry: {industry}. Audience: {audience}. Brand values: {brand_values}. "
        f"Visual direction: {spec['visual']}. Symbol cue: {symbol}. Style: {style}. Palette: {palette}. "
        f"Usage: {usage}. Composition: {composition}. Make it distinctive, simple, print-safe, and not similar "
        "to any existing brand, app icon, copyrighted character, government mark, or stock logo template."
    )
    prompt_zh = (
        f"为「{brand_name}」生成原创商标/Logo。商标类型：{spec['label']}；行业：{industry}；"
        f"受众：{audience}；品牌价值：{brand_values}；用途：{usage}；行业符号暗示：{symbol}；"
        f"风格：{style}；配色：{palette}。要求矢量优先、轮廓强、负空间清楚、黑白可用、24px 小尺寸可读，"
        "不要近似任何现有品牌、App 图标、受保护角色、政府标识或图库模板。"
    )
    if preset:
        prompt_en = str(preset["prompt_en"])
        prompt_zh = str(preset["prompt_zh"])
    return {
        "brand_name": brand_name,
        "industry": industry,
        "audience": audience,
        "brand_values": brand_values,
        "usage": usage,
        "trademark_type": mark_type,
        "trademark_type_label": spec["label"],
        "trademark_type_intent": spec["intent"],
        "style": style,
        "color_palette": palette,
        "symbol": symbol,
        "composition": composition,
        "prompt": prompt_zh + "\n\nEnglish prompt:\n" + prompt_en,
        "prompt_zh": prompt_zh,
        "prompt_en": prompt_en,
        "prompt_preset": preset or None,
        "prompt_preset_catalog": prompt_preset_catalog(),
        "negative_prompt": NEGATIVE_PROMPT,
        "clearance_checklist": _clearance_checklist(brand_name, industry, mark_type),
        "delivery_spec": {
            "source": ["SVG", "AI or PDF vector", "editable monochrome version"],
            "raster": [
                "PNG 1024/512/256/128/64/32/16",
                "transparent background",
                "white and dark background previews",
            ],
            "variants": [
                "horizontal lockup",
                "stacked lockup",
                "symbol-only",
                "black",
                "white",
                "single-color",
            ],
            "quality_gates": [
                "24px readability",
                "black-white contrast",
                "no tiny strokes",
                "safe margins for app icon and favicon",
            ],
        },
        "legal_note": "本结果是创意与初步自检，不构成法律意见，也不保证商标可注册；正式上线/申请前必须做商标检索和法务复核。",
        "taxonomy": [
            {"id": key, "label": item["label"], "intent": item["intent"]}
            for key, item in TRADEMARK_TYPES.items()
        ],
    }


def _image_credentials(provider: str) -> Tuple[str, str, str]:
    provider = (provider or "doubao").strip().lower()
    if provider == "doubao":
        return (
            os.environ.get("DOUBAO_API_KEY") or os.environ.get("ARK_API_KEY") or "",
            (
                os.environ.get("DOUBAO_BASE_URL")
                or "https://ark.cn-beijing.volces.com/api/v3"
            ).rstrip("/"),
            "doubao-seedream-5-0-260128",
        )
    if provider == "openai":
        return (
            os.environ.get("OPENAI_API_KEY") or "",
            (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip(
                "/"
            ),
            "gpt-image-1",
        )
    return "", "", ""


def _write_data_url(data_url: str, output_path: Path, index: int) -> str:
    m = re.match(r"^data:image/([a-zA-Z0-9.+-]+);base64,(.+)$", data_url, re.S)
    if not m:
        return ""
    ext = "jpg" if m.group(1).lower() in {"jpeg", "jpg"} else "png"
    img_path = output_path.with_name(f"trademark_{index}.{ext}")
    img_path.write_bytes(base64.b64decode(m.group(2)))
    return str(img_path)


async def _generate_images(
    profile: Dict[str, Any], payload: Dict[str, Any], output_path: Path
) -> Dict[str, Any]:
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
            "warning": f"供应商 {provider} 未配置生图 API Key，已返回商标方案和提示词。",
        }
    try:
        import httpx
    except ImportError:
        return {
            "ok": False,
            "images": [],
            "provider": provider,
            "model": model,
            "warning": "httpx 不可用，已返回商标方案和提示词。",
        }
    body = {"model": model, "prompt": profile["prompt_en"], "size": size, "n": n}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{base_url}/images/generations", headers=headers, json=body
        )
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
            images.append(
                {
                    "url": data_url,
                    "local_path": _write_data_url(data_url, output_path, idx),
                }
            )
    return {
        "ok": bool(images),
        "images": images,
        "provider": provider,
        "model": model,
        "raw": data,
    }


async def convert_trademark_profile(
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
    profile = build_trademark_profile(payload)
    warnings: List[str] = [profile["legal_note"]]
    image_result: Dict[str, Any] = {"ok": False, "images": [], "skipped": True}
    generate_image = _as_bool(payload.get("generate_image"), default=True)
    if generate_image:
        image_result = await _generate_images(profile, payload, output_path)
        if not image_result.get("ok"):
            warn = str(
                image_result.get("warning")
                or "生图未返回图片，已保留商标方案和提示词。"
            )
            warnings.append(warn)
    result = {
        "ok": True,
        "summary": f"已生成「{profile['trademark_type_label']}」商标方案：{profile['brand_name']} / {profile['industry']}",
        "profile": profile,
        "image_generation": image_result,
        "outputs": {
            "profile_json": str(output_path),
            "image_count": len(image_result.get("images") or []),
            "images": image_result.get("images") or [],
        },
        "warnings": warnings,
    }
    if _as_bool(payload.get("require_image"), default=False) and not (
        image_result.get("images") or []
    ):
        result["ok"] = False
        result["summary"] = "已生成商标方案和提示词，但未生成图片。"
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result

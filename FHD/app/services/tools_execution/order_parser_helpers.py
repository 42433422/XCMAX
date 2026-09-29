from __future__ import annotations

import re

CHINESE_DIGIT_MAP = {
    "零": "0",
    "〇": "0",
    "一": "1",
    "二": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
    "两": "2",
}

ASR_MODEL_SEGMENT_MAP = {
    "酒吧": "98",
}

_CN_NUMBER_MAP = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def parse_cn_number(token: str):
    t = (token or "").strip()
    if not t:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", t):
        return float(t) if "." in t else int(t)

    m = _CN_NUMBER_MAP
    if t in m:
        return m[t]
    if t == "十":
        return 10
    if re.fullmatch(r"[一二两三四五六七八九]十", t):
        return m[t[0]] * 10
    if re.fullmatch(r"十[一二三四五六七八九]", t):
        return 10 + m[t[1]]
    if re.fullmatch(r"[一二两三四五六七八九]十[一二三四五六七八九]", t):
        return m[t[0]] * 10 + m[t[2]]
    return None


def cleanup_unit_name(raw: str) -> str:
    s = (raw or "").strip()
    # 剥掉书名号/引号包裹：客户名常写成「客户A」「客户A」""客户A""，引号本身不是名称内容。
    # 用 str.strip 而非正则，避免「引号重复串」上的多项式回溯（CodeQL py/polynomial-redos）。
    s = s.lstrip("「『“\"'《【[")
    s = s.rstrip("」』”\"'》】]")
    s = re.sub(r"^(哎|嗯|啊|呃)[，,\s]*", "", s)
    s = re.sub(r"^(帮我|给我|请)?\s*打印(一下)?", "", s)
    s = re.sub(r"^(帮我|给我|请|给)?\s*(开一张|开单|打单|下单|出单)(一下)?", "", s)
    s = re.sub(r"(开单|打单|下单|出单)$", "", s)
    s = re.sub(r"^(把|给)?", "", s)
    s = re.sub(
        r"^(再加|还要|继续加|再补|加上|增加|加|减少|减去|减|删掉|删除|去掉|移除|改成|改为|改)\s*",
        "",
        s,
    )
    s = s.replace("发货单", "").replace("送货单", "").replace("出货单", "")
    for token in [
        "打印一下",
        "打印",
        "给我",
        "帮我",
        "一下",
        "哎",
        "嗯",
        "啊",
        "呃",
        "桶",
        "要",
        "来",
        "拿",
        "再加",
        "还要",
        "继续加",
        "再补",
        "减少",
        "减去",
        "减",
        "删掉",
        "删除",
        "去掉",
        "移除",
        "改成",
        "改为",
    ]:
        s = s.replace(token, "")
    s = re.sub(r"[0-9A-Za-z-]{3,16}", "", s)
    s = re.sub(r"\s+", "", s)
    s = s.rstrip("的").strip()
    return s


def build_missing_prompt(unit_name=None, model_number=None, tin_spec=None, quantity_tins=None):
    missing = []
    if not unit_name:
        missing.append("单位")
    if not quantity_tins:
        missing.append("桶数")
    if not model_number:
        missing.append("编号/型号")
    if not tin_spec:
        missing.append("规格")
    if not missing:
        return None
    recognized = []
    if unit_name:
        recognized.append(f"单位 {unit_name}")
    if model_number:
        recognized.append(f"编号 {model_number}")
    if tin_spec:
        recognized.append(f"规格 {tin_spec}")
    recognized_text = ("（已识别：" + "，".join(recognized) + "）") if recognized else ""
    if missing == ["桶数"]:
        return f"还缺少桶数，请告诉我需要多少桶？{recognized_text}"
    if missing == ["单位"]:
        return f"还缺少单位名称，请补充购买单位。{recognized_text}"
    if missing == ["规格"]:
        return f"还缺少规格，请补充规格数值。{recognized_text}"
    if missing == ["编号/型号"]:
        return f"还缺少编号/型号，请补充。{recognized_text}"
    return f"还缺少{'、'.join(missing)}，请补充。{recognized_text}"


def normalize_trailing_unit_name(name: str) -> str:
    return (name or "").strip().rstrip("的").strip()


def normalize_chinese_digits(token: str) -> str:
    token = (token or "").strip()
    if not token:
        return ""

    if re.fullmatch(r"\d+(?:\.\d+)?", token):
        return token

    if all(ch in CHINESE_DIGIT_MAP for ch in token):
        return "".join(CHINESE_DIGIT_MAP[ch] for ch in token)

    digits = []
    for ch in token:
        if ch in CHINESE_DIGIT_MAP:
            digits.append(CHINESE_DIGIT_MAP[ch])
    return "".join(digits)


def normalize_quantity_token(quantity_token: str):
    quantity_token = (quantity_token or "").strip()
    if not quantity_token:
        return None
    if re.fullmatch(r"\d+", quantity_token):
        return int(quantity_token)
    digits = normalize_chinese_digits(quantity_token)
    if digits.isdigit():
        return int(digits)
    return None


# 引号包裹的客户名（「客户A」/“客户A”/【客户A】）与键值写法（客户=客户A）优先级最高。
_QUOTED_UNIT = re.compile(r"[「『“\"'《【\[]([^」』”\"'》】\]]{1,120})[」』”\"'》】\]]")
_KEYED_UNIT = re.compile(r"(?:客户|购买单位|单位|公司)\s*[:：=]\s*([^\s，,。；;]{1,120})")
# 无分隔符的口语写法「客户 验收客户」「客户验收客户」：客户名与标签之间只有空格/直接相连。
# 名称必须像名字（≥2 字、非标签词、非数字串），避免把「客户编号」「客户列表」当成客户名。
_KEYED_UNIT_LOOSE = re.compile(r"(?:客户|购买单位|购货单位)\s{0,8}([^\s，,。；;:：=]{2,20})")
_UNIT_LABEL_TOKENS = frozenset(
    {
        "客户",
        "编号",
        "名称",
        "列表",
        "清单",
        "信息",
        "资料",
        "产品",
        "订单",
        "发货",
        "采购",
        "对象",
        "为",
        "是",
    }
)


# 会话填充词与助手话术，绝不能被当成客户名（#2067）。
_FILLER_FRAGMENTS = ("正在", "稍候", "确认执行", "处理", "发货单", "送货单", "出货单", "识别")
_CONVERSATIONAL_FILLERS = frozenset(
    {
        "好的",
        "好",
        "嗯",
        "行",
        "可以",
        "收到",
        "明白",
        "是的",
        "确认",
        "请确认",
        "已识别",
        "已识别订单",
        "生成",
        "执行",
        "正在执行",
        "处理",
        "处理中",
        "完成",
        "已收到",
        "订单确认",
        "稍候",
        "请稍候",
        "订单",
    }
)


def looks_like_conversational_filler(token: str) -> bool:
    """判断一个 token 是否为会话话术而非客户名。"""
    t = re.sub(r"\s+", "", token or "")
    if not t:
        return True
    if t in _CONVERSATIONAL_FILLERS:
        return True
    return any(frag in t for frag in _FILLER_FRAGMENTS)


_BILL_VERB_KEYWORDS = (
    "生成发货单",
    "开发货单",
    "开单",
    "打单",
    "下单",
    "出单",
    "发货单",
    "送货单",
    "出货单",
)


def strip_bill_keywords(text: str) -> str:
    """剥掉下单动词与单据名；「开发货单」整体剥，避免残留「开」被当成客户名。"""
    out = text
    for kw in _BILL_VERB_KEYWORDS:
        out = out.replace(kw, " ")
    return out


def looks_like_customer_name_token(token: str) -> bool:
    """判断 token 是否像客户名（用于末位兜底，拒绝动词残片与键值残片）。"""
    t = re.sub(r"\s+", "", token or "")
    if len(t) < 2 or t in _UNIT_LABEL_TOKENS:
        return False
    if re.search(r"\d", t) or re.search(r"[:：=]", t):
        return False
    # 兜底与口语键值只认可读中文名：避免把【shipment_generate】这类标识当成客户名（#2067）。
    if not re.search(r"[\u4e00-\u9fff]", t):
        return False
    return not looks_like_conversational_filler(t)


def extract_explicit_unit_name(text: str) -> str:
    """显式写法给出的客户名（引号/键值），无则返回空串。"""
    for pattern in (_QUOTED_UNIT, _KEYED_UNIT):
        m = pattern.search(text or "")
        if m:
            name = cleanup_unit_name(m.group(1))
            if name:
                return name
    # 口语键值写法「客户 验收客户」：只在名称像客户名时采信，避免「客户编号」等标签误伤。
    m = _KEYED_UNIT_LOOSE.search(text or "")
    if m:
        name = cleanup_unit_name(m.group(1))
        if looks_like_customer_name_token(name):
            return name
    return ""


def loose_order_fallback(text: str) -> dict | None:
    """末位兜底：仅当首个 token 像客户名时，按「客户名 + 产品名」兜底（#2067）。"""
    parts = (text or "").split()
    if len(parts) < 2:
        return None
    # 显式键值写法（「客户=X」「客户 X」）优先，避免「客户=某客户」整体被当成客户名；
    # 仍要走可读性校验，避免把助手话术里的【shipment_generate】当成客户名（#2067 回归）。
    unit = extract_explicit_unit_name(text or "")
    if unit and not looks_like_customer_name_token(unit):
        unit = ""
    if not unit and looks_like_customer_name_token(parts[0]):
        unit = parts[0].strip()
    if not unit:
        return None
    product_name = " ".join(parts[1:]).strip()
    product_name = re.sub(r"^(?:商品|产品)\s*[:：=]\s*", "", product_name)
    return {
        "success": True,
        "unit_name": unit,
        "products": [{"name": product_name, "quantity_tins": 1, "tin_spec": 10.0}],
    }


def normalize_model_number_token(model_token: str) -> str:
    token = (model_token or "").strip()
    if not token:
        return ""

    compact = re.sub(r"\s+", "", token)
    if re.fullmatch(r"[0-9A-Za-z-]+", compact):
        return compact.upper()

    for k, v in ASR_MODEL_SEGMENT_MAP.items():
        if k in token:
            token = token.replace(k, v)

    out: list[str] = []
    for ch in token:
        if ch.isdigit():
            out.append(ch)
        elif ch in CHINESE_DIGIT_MAP:
            out.append(CHINESE_DIGIT_MAP[ch])
        elif ch.isalpha():
            out.append(ch.upper())
        elif ch == "-":
            out.append(ch)
    return "".join(out)

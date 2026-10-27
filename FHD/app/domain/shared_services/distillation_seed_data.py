"""Seed intent labels and example utterances for distillation-data collection."""

from __future__ import annotations

INTENT_LABELS = [
    "shipment_generate",
    "customers",
    "products",
    "shipments",
    "wechat_send",
    "print_label",
    "upload_file",
    "materials",
    "shipment_template",
    "excel_decompose",
    "show_images",
    "show_videos",
    "greet",
    "goodbye",
    "help",
    "negation",
    "customer_export",
    "customer_edit",
    "customer_supplement",
]

SAMPLE_QUERIES = {
    "shipment_generate": [
        "生成发货单给七彩乐园",
        "开发货单，3桶规格20的PE白底漆",
        "帮侯雪梅开一张发货单",
        "做出货单，5桶20kg规格的",
        "打单给向总",
        "发货单七彩乐园2桶28规格",
        "我要给恒达公司开单",
        "生成一张发货单，客户是利民厂",
        "帮客户做发货单，数量3桶",
    ],
    "customers": [
        "查看客户列表",
        "购买单位有哪些",
        "显示所有客户",
        "我想看客户信息",
        "客户名单在哪",
        "都有哪些购买单位",
    ],
    "products": [
        "查看产品列表",
        "产品库有哪些",
        "显示产品规格",
        "产品型号有什么",
        "PE白底漆的规格",
        "查一下产品信息",
    ],
    "shipments": ["查看发货记录", "最近的发货单", "订单列表", "出货记录查询", "我的订单有哪些"],
    "wechat_send": ["发微信给客户", "发送微信消息", "发消息通知向总"],
    "print_label": ["打印标签", "导出商标", "标签打印", "产品标签怎么打印", "导出产品标签"],
    "upload_file": ["上传文件", "导入Excel", "解析发货单文件", "上传数据文件"],
    "materials": ["查看原材料库存", "材料库查询", "还有多少原料"],
    "shipment_template": ["发货单模板", "查看模板设置", "模板是什么"],
    "excel_decompose": ["分解Excel", "提取词条", "表头提取"],
    "show_images": ["查看图片", "产品图片", "显示图片"],
    "show_videos": ["查看视频", "产品视频"],
    "greet": ["你好", "您好", "早上好", "hello", "hi"],
    "goodbye": ["再见", "拜拜", "退出", "关闭"],
    "help": ["帮助", "怎么用", "功能介绍", "教我使用"],
    "negation": ["不要开单", "别发消息", "取消订单", "不要打印"],
    "customer_export": ["导出客户列表", "导出Excel", "下载客户数据"],
    "customer_edit": ["修改客户信息", "编辑客户", "更新客户资料"],
    "customer_supplement": ["补充客户信息", "添加联系人", "完善客户资料"],
}

__all__ = ["INTENT_LABELS", "SAMPLE_QUERIES"]

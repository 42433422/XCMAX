# 商标生成员

商标生成员用于为公司、产品、App、AI 员工和店铺生成原创商标/Logo 方向、提示词、矢量交付建议和初步近似风险自检。

它覆盖九类常见商标方向：文字商标、字母商标、图形商标、抽象商标、吉祥物商标、组合商标、徽章/印章、App 图标、包装标签。

## 内置提示词预设

- `brand_mark_sheet`：商标方向九宫格，一次生成 9 个原创方向，便于挑选后精修。
- `startup_combination_mark`：新品牌图文组合商标，适合公司/产品初期建立识别。
- `app_icon_mark`：App、SaaS、插件和小程序入口图标。
- `package_label_mark`：商品包装、外卖贴纸、瓶贴、门店和电商主图。

输入示例：

```json
{
  "brand_name": "修茈云工坊",
  "industry": "AI 软件 / 企业服务",
  "audience": "中小企业老板和运营团队",
  "brand_values": "可靠、聪明、高效、有温度",
  "style": "modern SaaS, premium vector",
  "color_palette": "deep blue, clean white, fresh green accent",
  "prompt_preset": "startup_combination_mark",
  "generate_image": true
}
```

多方向探索示例：

```json
{
  "brand_name": "XC AGI",
  "task": "做一组 3x3 商标方向九宫格",
  "prompt_preset": "brand_mark_sheet",
  "generate_image": true,
  "n": 1
}
```

输出写入 `outputs/trademark_profile.json`，包含商标类型、构图建议、预设 ID、正向提示词、负面提示词、初步近似风险自检清单、矢量交付建议、可用时的图片 URL 或 data URL。

注意：本员工输出是创意与初步自检，不构成法律意见，也不保证商标可注册。正式上线或申请前必须做商标检索和法务复核。

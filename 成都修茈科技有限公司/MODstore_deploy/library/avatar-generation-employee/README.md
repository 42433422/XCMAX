# 头像生成员

头像生成员用于给 AI 员工生成头像方案、提示词和可选生图结果。它覆盖人类常用头像类型：真人、关系、动漫游戏、插画化本人、职业品牌、宠物吉祥物、兴趣符号、抽象氛围、默认极简。

## 内置提示词预设

- `employee_avatar_sheet`：批量 AI 员工头像表，生成 `4 列 x 3 行` 的 12 张二次元联系人头像，后续裁成单张头像。
- `xiaoc_human_aquatic`：小 C 专用，人形二次元 AI 助理 + 鱼类/水系元素，禁止鱼脸吉祥物。
- `mobile_contact_avatar`：单个 AI 员工移动端联系人头像，强调头肩近景、脸占主体、干净背景、圆形裁切安全。

输入示例：

```json
{
  "employee_name": "小 C 助理",
  "employee_role": "企业 AI 助手",
  "department": "超级开发部",
  "avatar_type": "anime_game",
  "style": "clean anime, premium SaaS",
  "personality": "聪明、可靠、有一点少年感",
  "color_palette": "blue, violet, white",
  "prompt_preset": "xiaoc_human_aquatic",
  "generate_image": true
}
```

批量员工头像表示例：

```json
{
  "task": "给一批 AI 员工生成头像表",
  "prompt_preset": "employee_avatar_sheet",
  "generate_image": true,
  "n": 1
}
```

输出写入 `outputs/avatar_profile.json`，包含头像类型、构图建议、预设 ID、正向提示词、负面提示词、后处理建议、可用时的图片 URL 或 data URL。

# skill-xcemp-interview-rubric

## 输入（建议由调用方 JSON 提供）

- `manifest_excerpt`：字符串，`employee_config_v2` 与 `depends_on` 相关片段即可。
- `sync_test_log`：可选，同步测试或沙盒报错摘要。
- `target_role`：可选，候选包对外显示名。

## 必查项（勾选心智模型）

- [ ] `id` / `artifact: employee_pack` / `version` 一致且合法。
- [ ] `employee_config_v2.actions.handlers` 非空且与真实能力一致。
- [ ] `system_prompt` 是否唯一、可执行、含拒答/不确定策略。
- [ ] `depends_on` 中的 ID 在编制矩阵或目录中可解析。
- [ ] **运行依赖**：岗位 `README.md` 是否用表格或列表声明对外部 API、知识库或其它 AI 岗位的依赖及失效行为（可与 `employee_config_v2.metadata.runtime_dependencies` 互参）；缺失则「有条件录用」并列为复试题。
- [ ] 无脚手架长文、无重复拼接的 `behavior_rules`。
- [ ] 温度与岗位风险是否匹配。

## 输出结构（Markdown）

1. **结论**：录用 / 有条件录用 / 驳回（一句 + 三条以内理由）。
2. **阻塞项**：必须修复后才能上架的条目（编号）。
3. **建议补丁**：可交给策展员的 manifest 修改方向（不写虚构 diff）。
4. **复试题**：若信息不足，列出需要补充的最少字段。

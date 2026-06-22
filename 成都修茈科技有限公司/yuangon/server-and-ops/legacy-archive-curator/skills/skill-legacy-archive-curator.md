# 工作区归档管理员技能

职责：S-R R3 工作区与 legacy 归档：_archive/、FHD/.archive/、LEGACY_CLEANUP_TRACKING、xcmax-tree 排除项治理。

## 执行步骤

1. 盘点候选归档、引用关系、保留期和恢复路径。
2. 默认 dry-run，生成清单后再申请删除审批。
3. 禁止处理数据库、密钥、当前发布物和未确认用户数据。

## 输出契约

- summary：结论。
- evidence：真实文件、接口、记录或测试证据。
- risks：风险与不确定项。
- next_actions：下一步、负责人和是否需要人工确认。

没有真实证据时必须返回未验证，不得把计划、回显或合成事件计为成功。

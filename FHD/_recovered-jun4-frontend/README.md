# 6 月 4 日管理员前端恢复包

**未在 git 中提交**；`git clean -fd frontend/` 删除的是工作区未跟踪文件。Git blob / lost-found **未**找到这些源码。

## 源码（推荐）

来自 Cursor 会话 transcript 最后一次 `Write` 载荷：
`~/.cursor/projects/Users-a4243342-Desktop-XCMAX/agent-transcripts/981f464f-0c03-4f86-ae0d-cb0927c3f41d/981f464f-0c03-4f86-ae0d-cb0927c3f41d.jsonl`

| 文件 | transcript 行号 | 大小(B) |
|------|-----------------|--------|
| `frontend/src/components/admin/XCmaxAdminDutyTab.vue` | 711 | 2947 |
| `frontend/src/components/admin/XCmaxAdminInfraTab.vue` | 711 | 5366 |
| `frontend/src/components/workflow/DutyRosterGraphPanel.vue` | 711 | 2889 |
| `frontend/src/constants/adminOperatorNav.ts` | 339 | 868 |
| `frontend/src/views/AutomationPolicyView.vue` | 607 | 866 |
| `frontend/src/views/DutyRosterGraphView.vue` | 737 | 448 |

## 构建产物（仅 minified）

| 文件 | 来源 |
|------|------|
| `vue-dist/assets/js/index-zqbM2t0a.js` | `/Users/a4243342/XCMAX-archives/m0-fhd-bulk-20260605/FHD/templates/vue-dist/` 2026-06-05 01:53 |
| `vue-dist/assets/js/AutomationPolicyView-QJ4iNy4T.js` | 同上 |

**无 `.map` source map**；DutyRoster 等可能打进 index 主包，无独立 chunk 文件名。

## 恢复到工作区

```bash
cd /Users/a4243342/Desktop/XCMAX/FHD
rsync -a _recovered-jun4-frontend/frontend/src/ frontend/src/
```

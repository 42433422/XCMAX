/** 智脑视图静态常量（拆分自 BrainView.vue，内容不变） */

export const BRAIN_AGENT_SESSION_KEY = 'xcagi_brain_agent_session_id'
export const BRAIN_LAYOUT_MQ = '(max-width: 960px)'

export const tabs = [
  { id: 'architecture', label: '架构' },
  { id: 'api', label: 'API' },
  { id: 'skills', label: 'Skill' }
]

export const architectureDiagram = `┌─────────────────────────────────────────────────────────┐
│  Level 3: Page (页面层)     ← Vue3 前端交互             │
│  - CodeEditorView.vue       ← 主页面                     │
│  - DiffViewer.vue          ← Diff 对比                   │
│  - FileTree.vue            ← 文件树                      │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│  Level 2: API (接口层)      ← FastAPI 提供接口           │
│  POST /api/code-editor/analyze   ← 分析代码            │
│  POST /api/code-editor/edit      ← 生成修改建议        │
│  GET  /api/code-editor/diff/{id} ← 获取 Diff          │
│  POST /api/code-editor/apply/{id} ← 应用修改          │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│  Level 1: Skill (能力层)    ← 底层代码处理能力           │
│  - CodeAnalyzerSkill    ← 分析/解释/审查代码            │
│  - CodeEditorSkill      ← 生成修改建议                 │
│  - BackupManager        ← 备份/恢复机制                │
└─────────────────────────────────────────────────────────┘`

export const skillRows = [
  {
    id: 'CodeAnalyzerSkill',
    desc: '分析、解释、审查代码',
    status: '✅ 已实现 v1.0'
  },
  {
    id: 'CodeEditorSkill',
    desc: '生成修改建议',
    status: '✅ 已实现 v1.0'
  },
  {
    id: 'BackupManager',
    desc: '备份与恢复',
    status: '✅ 已实现 v1.0'
  }
]

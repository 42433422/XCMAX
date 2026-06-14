import type { TutorialBuildContext, TutorialTrackMeta } from './types'
import { collectModTutorialTracks } from './buildModSteps'

const HOST_TRACKS: TutorialTrackMeta[] = [
  {
    id: 'basic',
    title: '宿主入门',
    summary: '认识XC → 行业定型 → 补基础线（三步引导）',
    description:
      '打开首次设置向导：默认只有智能对话与智能生态，先定行业，再按需补基础 Mod。',
    kind: 'curated',
    recommended: true,
  },
  {
    id: 'advanced',
    title: '进阶教程',
    summary: '按当前侧栏菜单逐项认路与页内功能',
    description:
      '按当前侧栏菜单逐项认路；末尾在「智能生态 → 员工商店」装齐办公员工包（表格/文档基础能力，兼作教学演示）。侧栏精简或安装 Mod 后路线会自动调整。',
    kind: 'nav',
  },
]

export function getTrackMetas(ctx: TutorialBuildContext): TutorialTrackMeta[] {
  const modTracks = collectModTutorialTracks(ctx.mods as never[], ctx.modMenuKeys)
  return [...HOST_TRACKS, ...modTracks]
}

export function getTrackLabel(trackId: string | null | undefined, ctx: TutorialBuildContext): string {
  if (!trackId) return ''
  const hit = getTrackMetas(ctx).find((t) => t.id === trackId)
  return hit?.title || trackId
}

export function formatAdvancedTrackHint(visibleNames: string[], max = 5): string {
  if (!visibleNames.length) return '按侧栏生成步骤。'
  return `含 ${visibleNames.length} 个菜单项。`
}

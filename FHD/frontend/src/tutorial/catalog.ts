import type { TutorialBuildContext, TutorialTrackMeta } from './types'
import { collectModTutorialTracks } from './buildModSteps'

const HOST_TRACKS: TutorialTrackMeta[] = [
  {
    id: 'basic',
    title: '宿主入门',
    summary: '认识XC → 行业定型 → 准备菜单（三步引导）',
    description: '打开首次设置向导：默认只有智能对话与智能生态，先定行业，再一键装齐侧栏菜单。',
    kind: 'curated',
    recommended: true,
  },
  {
    id: 'advanced',
    title: '进阶教程',
    summary: '五门真实业务实训：亲自操作，后端验证结果',
    description: '进入独立教学空间，完成任务工作区、主数据、销售到收款、业务文件导入和证据追踪。不会写入正式企业数据。',
    kind: 'curated',
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

export function formatAdvancedTrackHint(_visibleNames: string[], _max = 5): string {
  return '5 门真实业务实训 · 亲自操作 · 服务端验证'
}

export type EltRunTab = 'upload' | 'mapping' | 'preview' | 'history'

export function tabForRunStatus(status: string): EltRunTab {
  if (['queued', 'previewing'].includes(status)) return 'upload'
  if (status === 'preview_ready') return 'preview'
  return 'history'
}

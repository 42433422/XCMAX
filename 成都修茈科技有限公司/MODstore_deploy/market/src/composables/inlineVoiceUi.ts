export type InlineVoiceUiPhase = 'idle' | 'recording' | 'recognizing' | 'permission'

export function isMicPermissionError(msg: string): boolean {
  return /麦克风|Permission|NotAllowed|getUserMedia|授权|占用|允许麦克风/i.test(msg || '')
}

export function resolveInlineVoicePhase(
  listening: boolean,
  recognizing: boolean,
  permissionHint: string,
): InlineVoiceUiPhase {
  if (permissionHint.trim()) return 'permission'
  if (listening) return 'recording'
  if (recognizing) return 'recognizing'
  return 'idle'
}

export function inlineVoiceAriaLabel(
  phase: InlineVoiceUiPhase,
  mobile: boolean,
  cancelIntent = false,
): string {
  switch (phase) {
    case 'recording':
      return cancelIntent ? '松开取消录音' : '录音中…'
    case 'recognizing':
      return '识别中…'
    case 'permission':
      return '需要麦克风权限'
    default:
      return mobile ? '按住说话，松手发送' : '语音输入（长按切换说模式）'
  }
}

export function inlineVoiceStatusLabel(
  phase: InlineVoiceUiPhase,
  mobile: boolean,
  cancelIntent: boolean,
  permissionHint: string,
  loadingHint: string,
): string {
  if (phase === 'permission') return permissionHint.trim() || '需要麦克风权限，请在系统设置中允许后重试。'
  if (phase === 'recording') {
    if (mobile) return cancelIntent ? '松开取消' : '松开发送 · 上滑取消'
    return loadingHint.trim() || '录音中…'
  }
  if (phase === 'recognizing') return '识别中…'
  return ''
}

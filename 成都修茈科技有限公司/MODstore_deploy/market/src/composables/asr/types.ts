export type ASRBackendId = 'vosk' | 'funasr' | 'whisper-web' | 'webspeech'

/** FunASR 2pass：online=流式 partial；offline=可靠句号 */
export type ASRSegmentMode = 'online' | 'offline' | 'other'

export interface ASRResult {
  text: string
  isFinal: boolean
  segmentMode?: ASRSegmentMode
}

export interface ASRBackendInfo {
  id: ASRBackendId
  label: string
  available: boolean
  loading: boolean
}

export interface ASRBackend {
  id: ASRBackendId
  label: string
  isAvailable(): boolean
  isLoading(): boolean
  start(
    onResult: (r: ASRResult) => void,
    onError: (msg: string) => void,
    onAudioLevel?: (level: number) => void,
    onReady?: () => void,
    onMicReady?: () => void,
    mediaStream?: MediaStream,
  ): Promise<void>
  /** 断句取最终结果，麦克风/WebSocket 保持连接（持续聆听） */
  flushUtterance?(): Promise<string>
  stop(): Promise<string>
  abort(): void
}

export type StartListeningOptions = {
  /** 持续聆听模式：跳过不适合长听的 Whisper 本地模型 */
  continuous?: boolean
  /** 用户手势内预取的麦克风流 */
  mediaStream?: MediaStream | Promise<MediaStream>
}

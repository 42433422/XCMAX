import { ref, onBeforeUnmount } from 'vue'
import { type ASRBackend, type ASRResult, type StartListeningOptions } from './asr/types'
import { WebSpeechBackend } from './asr/WebSpeechBackend'
import { FunASRBackend } from './asr/FunASRBackend'
import { WhisperWebBackend } from './asr/WhisperWebBackend'
import { probeWhisperHubReady } from './asr/hfHub'
import { releaseSharedMicCapture, wakeSharedMicCapture } from './asr/sharedMicCapture'

type BackendEntry = {
  id: string
  create: () => ASRBackend
  startHint: string
  timeoutMs: number
}

const BACKEND_CHAIN: BackendEntry[] = [
  { id: 'funasr', create: () => new FunASRBackend(), startHint: '正在连接语音服务…', timeoutMs: 15000 },
  { id: 'webspeech', create: () => new WebSpeechBackend(), startHint: '正在尝试浏览器语音…', timeoutMs: 12000 },
  { id: 'whisper-web', create: () => new WhisperWebBackend(), startHint: '正在加载本地识别模型…', timeoutMs: 30000 },
]

function isMobileDevice(): boolean {
  if (typeof navigator === 'undefined') return false
  return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent)
}

export function useSpeechRecognition() {
  const error = ref('')
  const interimText = ref('')
  const audioLevel = ref(0)
  const loadingHint = ref('')
  const activeBackendId = ref('')
  const sessionReady = ref(false)

  let currentBackend: ASRBackend | null = null
  let _onResult: ((r: ASRResult) => void) | null = null
  let _onError: ((msg: string) => void) | null = null
  let _onAudioLevel: ((level: number) => void) | null = null
  let _resultTimeout: ReturnType<typeof setTimeout> | null = null
  let _gotAnyResult = false
  let _sessionId = 0

  let _lastRecognizedText = ''
  let _startTask: Promise<void> | null = null
  let _activeChainIndex = 0
  let _continuousMode = false
  let _funasrRetryCount = 0
  const FUNASR_CONTINUOUS_MAX_RETRY = 4
  let _prefetchedStream: MediaStream | undefined
  let _prefetchedStreamPromise: Promise<MediaStream> | undefined

  function continuousFunasrFailMsg(): string {
    return '服务端语音识别不可用，请检查网络后重试；国内环境请勿依赖浏览器识别。'
  }

  function micStartupFailMsg(startupError?: string): string {
    const err = (startupError || '').trim()
    if (/请先登录|认证|token/i.test(err)) return err || '请先登录后再使用语音识别。'
    if (/麦克风|Permission|NotAllowed|getUserMedia|授权|占用/i.test(err)) {
      return isMobileDevice()
        ? '请先点击右下角麦克风按钮，在系统弹窗中允许麦克风后再说话。'
        : err || '麦克风不可用，请检查权限或使用文字输入。'
    }
    return continuousFunasrFailMsg()
  }

  function mobileContinuousHint(): string {
    return '持续聆听需 FunASR 服务端或浏览器语音识别；移动端请确认已允许麦克风，或使用 Chrome / Edge。'
  }

  function stopCurrentBackend() {
    if (!currentBackend) return
    try {
      currentBackend.abort()
    } catch { /* */ }
    currentBackend = null
    activeBackendId.value = ''
    sessionReady.value = false
    audioLevel.value = 0
  }

  function clearResultTimeout() {
    if (_resultTimeout) {
      clearTimeout(_resultTimeout)
      _resultTimeout = null
    }
  }

  function startResultTimeout(chainIndex: number, sessionId: number) {
    clearResultTimeout()
    const entry = BACKEND_CHAIN[chainIndex]
    if (_continuousMode && (entry?.id === 'webspeech' || entry?.id === 'funasr')) {
      // 持续聆听：仅连接阶段超时，就绪后不因静音降级（移动网络放宽）
      const connectMs =
        entry.id === 'funasr'
          ? isMobileDevice()
            ? 35000
            : 20000
          : 8000
      _resultTimeout = setTimeout(() => {
        void handleResultTimeout(chainIndex, sessionId)
      }, connectMs)
      return
    }
    _gotAnyResult = false
    const timeoutMs = entry?.timeoutMs ?? 12000
    _resultTimeout = setTimeout(() => {
      void handleResultTimeout(chainIndex, sessionId)
    }, timeoutMs)
  }

  async function handleResultTimeout(chainIndex: number, sessionId: number) {
    if (sessionId !== _sessionId || _gotAnyResult) return
    stopCurrentBackend()
    loadingHint.value = ''
    const entry = BACKEND_CHAIN[chainIndex]
    if (_continuousMode && entry?.id === 'funasr') {
      if (_funasrRetryCount < FUNASR_CONTINUOUS_MAX_RETRY) {
        _funasrRetryCount += 1
        loadingHint.value = '正在重连语音服务…'
        await new Promise((r) => setTimeout(r, 600 + _funasrRetryCount * 400))
        if (sessionId !== _sessionId) return
        await tryBackendChain(0, sessionId)
        return
      }
      const msg = continuousFunasrFailMsg()
      error.value = msg
      _onError?.(msg)
      return
    }
    if (chainIndex + 1 < BACKEND_CHAIN.length) {
      loadingHint.value = '正在切换识别方案…'
      await tryBackendChain(chainIndex + 1, sessionId)
      return
    }
    const msg = _continuousMode && isMobileDevice()
      ? mobileContinuousHint()
      : '语音识别无响应，请检查麦克风或使用文字输入。'
    error.value = msg
    _onError?.(msg)
  }

  async function tryBackendChain(chainIndex: number, sessionId: number): Promise<void> {
    if (sessionId !== _sessionId) return

    if (chainIndex >= BACKEND_CHAIN.length) {
      loadingHint.value = ''
      const msg = _continuousMode && isMobileDevice()
        ? mobileContinuousHint()
        : '语音识别不可用。请检查麦克风权限或使用文字输入。'
      error.value = msg
      _onError?.(msg)
      return
    }

    const entry = BACKEND_CHAIN[chainIndex]
    // 持续聆听只用 FunASR，不降级 WebSpeech（国内 Chrome 无法访问 Google 语音）
    if (_continuousMode && entry.id === 'webspeech') {
      loadingHint.value = ''
      const msg = continuousFunasrFailMsg()
      error.value = msg
      _onError?.(msg)
      return
    }
    if (entry.id === 'whisper-web') {
      if (_continuousMode) {
        await tryBackendChain(chainIndex + 1, sessionId)
        return
      }
      if (isMobileDevice()) {
        await tryBackendChain(chainIndex + 1, sessionId)
        return
      }
      const hubOk = await probeWhisperHubReady()
      if (!hubOk) {
        await tryBackendChain(chainIndex + 1, sessionId)
        return
      }
    }
    const backend = entry.create()
    if (!backend.isAvailable()) {
      await tryBackendChain(chainIndex + 1, sessionId)
      return
    }

    loadingHint.value =
      entry.id === 'funasr' ? '请允许麦克风权限…' : entry.startHint
    try {
      await tryBackend(backend, entry.id, chainIndex, sessionId)
    } catch {
      if (sessionId !== _sessionId) return
      await tryBackendChain(chainIndex + 1, sessionId)
    }
  }

  async function startListening(
    onResult: (r: ASRResult) => void,
    onError: (msg: string) => void,
    onAudioLevel?: (level: number) => void,
    options?: StartListeningOptions,
  ) {
    error.value = ''
    interimText.value = ''
    loadingHint.value = ''
    sessionReady.value = false
    _onResult = onResult
    _onError = onError
    _onAudioLevel = onAudioLevel ?? null
    _continuousMode = options?.continuous ?? false
    _funasrRetryCount = 0
    _prefetchedStream = undefined
    _prefetchedStreamPromise = undefined
    if (options?.mediaStream) {
      if (options.mediaStream instanceof MediaStream) {
        _prefetchedStream = options.mediaStream
      } else {
        _prefetchedStreamPromise = options.mediaStream
      }
    }
    _sessionId += 1
    const sessionId = _sessionId
    if (!options?.continuous) {
      _lastRecognizedText = ''
    }

    _startTask = tryBackendChain(0, sessionId).finally(() => {
      _startTask = null
    })
    await _startTask
  }

  async function tryBackend(
    backend: ASRBackend,
    id: string,
    chainIndex: number,
    sessionId: number,
  ) {
    if (sessionId !== _sessionId) return

    stopCurrentBackend()
    currentBackend = backend
    activeBackendId.value = id
    sessionReady.value = false
    _activeChainIndex = chainIndex

    const chainId = BACKEND_CHAIN[chainIndex]?.id
    if (_continuousMode && (chainId === 'webspeech' || chainId === 'funasr')) {
      startResultTimeout(chainIndex, sessionId)
    }

    let mediaStream = _prefetchedStream
    if (!mediaStream && _prefetchedStreamPromise) {
      try {
        mediaStream = await _prefetchedStreamPromise
        if (mediaStream) _prefetchedStream = mediaStream
      } catch {
        mediaStream = undefined
      }
    }

    let startupError = ''

    await (id === 'funasr'
      ? (backend as FunASRBackend).start(
          (r: ASRResult) => {
            if (sessionId !== _sessionId) return
            if (r.text.trim()) {
              _lastRecognizedText = r.text.trim()
              interimText.value = _lastRecognizedText
              _gotAnyResult = true
              if (!_continuousMode) {
                clearResultTimeout()
              }
              loadingHint.value = ''
            }
            _onResult?.(r)
          },
          async (msg: string) => {
            if (sessionId !== _sessionId) return
            clearResultTimeout()
            loadingHint.value = ''
            const savedPartial = _lastRecognizedText

            if (!sessionReady.value) {
              startupError = msg
              return
            }

            stopCurrentBackend()

            if (
              _continuousMode &&
              chainIndex === 0 &&
              _funasrRetryCount < FUNASR_CONTINUOUS_MAX_RETRY
            ) {
              _funasrRetryCount += 1
              loadingHint.value = '正在重连语音服务…'
              if (savedPartial) interimText.value = savedPartial
              await new Promise((r) => setTimeout(r, 600 + _funasrRetryCount * 400))
              if (sessionId !== _sessionId) return
              await tryBackendChain(0, sessionId)
              return
            }

            if (_continuousMode && chainIndex === 0) {
              error.value = continuousFunasrFailMsg()
              _onError?.(continuousFunasrFailMsg())
              return
            }

            if (chainIndex + 1 < BACKEND_CHAIN.length) {
              loadingHint.value = '正在切换识别方案…'
              if (savedPartial) interimText.value = savedPartial
              await tryBackendChain(chainIndex + 1, sessionId)
              return
            }
            error.value = msg
            _onError?.(msg)
          },
          (level: number) => {
            if (sessionId !== _sessionId) return
            audioLevel.value = level
            _onAudioLevel?.(level)
          },
          () => {
            if (sessionId !== _sessionId) return
            if (_continuousMode && chainId === 'funasr') {
              _funasrRetryCount = 0
            }
            clearResultTimeout()
            sessionReady.value = true
            loadingHint.value = '请开始说话…'
            wakeSharedMicCapture()
            if (!_continuousMode) {
              startResultTimeout(chainIndex, sessionId)
            }
          },
          id === 'funasr'
            ? () => {
                if (sessionId !== _sessionId) return
                loadingHint.value = '正在连接语音服务…'
              }
            : undefined,
          mediaStream,
          { persistentMic: _continuousMode },
        )
      : backend.start(
      (r: ASRResult) => {
        if (sessionId !== _sessionId) return
        if (r.text.trim()) {
          _lastRecognizedText = r.text.trim()
          interimText.value = _lastRecognizedText
          _gotAnyResult = true
          if (!_continuousMode) {
            clearResultTimeout()
          }
          loadingHint.value = ''
        }
        _onResult?.(r)
      },
      async (msg: string) => {
        if (sessionId !== _sessionId) return
        clearResultTimeout()
        loadingHint.value = ''
        const savedPartial = _lastRecognizedText

        // 启动阶段失败：由 tryBackend 在 start() 返回后同步重试
        if (!sessionReady.value) {
          startupError = msg
          return
        }

        stopCurrentBackend()

        if (
          _continuousMode &&
          chainIndex === 0 &&
          _funasrRetryCount < FUNASR_CONTINUOUS_MAX_RETRY
        ) {
          _funasrRetryCount += 1
          loadingHint.value = '正在重连语音服务…'
          if (savedPartial) interimText.value = savedPartial
          await new Promise((r) => setTimeout(r, 600 + _funasrRetryCount * 400))
          if (sessionId !== _sessionId) return
          await tryBackendChain(0, sessionId)
          return
        }

        if (_continuousMode && chainIndex === 0) {
          error.value = continuousFunasrFailMsg()
          _onError?.(continuousFunasrFailMsg())
          return
        }

        if (chainIndex + 1 < BACKEND_CHAIN.length) {
          loadingHint.value = '正在切换识别方案…'
          if (savedPartial) interimText.value = savedPartial
          await tryBackendChain(chainIndex + 1, sessionId)
          return
        }
        error.value = msg
        _onError?.(msg)
      },
      (level: number) => {
        if (sessionId !== _sessionId) return
        audioLevel.value = level
        _onAudioLevel?.(level)
      },
      () => {
        if (sessionId !== _sessionId) return
        if (_continuousMode && chainId === 'funasr') {
          _funasrRetryCount = 0
        }
        clearResultTimeout()
        sessionReady.value = true
        loadingHint.value = '请开始说话…'
        wakeSharedMicCapture()
        if (!_continuousMode) {
          startResultTimeout(chainIndex, sessionId)
        }
      },
      id === 'funasr'
        ? () => {
            if (sessionId !== _sessionId) return
            loadingHint.value = '正在连接语音服务…'
          }
        : undefined,
      mediaStream,
    ))

    if (sessionId !== _sessionId) return

    if (!sessionReady.value && currentBackend === backend) {
      stopCurrentBackend()
      if (
        _continuousMode &&
        chainIndex === 0 &&
        _funasrRetryCount < FUNASR_CONTINUOUS_MAX_RETRY
      ) {
        _funasrRetryCount += 1
        loadingHint.value = '正在重连语音服务…'
        await new Promise((r) => setTimeout(r, 600 + _funasrRetryCount * 400))
        if (sessionId !== _sessionId) return
        const retryEntry = BACKEND_CHAIN[chainIndex]
        if (!retryEntry) return
        return tryBackend(retryEntry.create(), retryEntry.id, chainIndex, sessionId)
      }
      if (_continuousMode && chainIndex === 0) {
        const msg = micStartupFailMsg(startupError)
        error.value = msg
        _onError?.(msg)
        return
      }
      if (chainIndex + 1 < BACKEND_CHAIN.length) {
        loadingHint.value = '正在切换识别方案…'
        await tryBackendChain(chainIndex + 1, sessionId)
        return
      }
      const msg = startupError || '语音识别启动失败，请检查麦克风后重试。'
      error.value = msg
      _onError?.(msg)
      return
    }

    if (currentBackend === backend) {
      const skipListenTimer =
        _continuousMode &&
        (chainId === 'webspeech' || chainId === 'funasr')
      if (!skipListenTimer) {
        startResultTimeout(chainIndex, sessionId)
      }
    }
  }

  function signalEndOfSpeech(): void {
    const backend = currentBackend as ASRBackend & { signalEndOfSpeech?: () => void }
    backend?.signalEndOfSpeech?.()
  }

  async function flushListening(): Promise<string> {
    if (!currentBackend) return _lastRecognizedText.trim()
    const backend = currentBackend as ASRBackend & { flushUtterance?: () => Promise<string> }
    if (typeof backend.flushUtterance === 'function') {
      const text = (await backend.flushUtterance()).trim()
      if (text) _lastRecognizedText = text
      return text
    }
    return _lastRecognizedText.trim()
  }

  async function stopListening(): Promise<string> {
    clearResultTimeout()
    if (_startTask) {
      try {
        await _startTask
      } catch {
        /* start failed */
      }
    }
    if (!currentBackend) {
      const cached = _lastRecognizedText.trim()
      _lastRecognizedText = ''
      loadingHint.value = ''
      if (_continuousMode) releaseSharedMicCapture()
      return cached
    }
    const text = await currentBackend.stop()
    const final = (text || _lastRecognizedText).trim()
    _lastRecognizedText = ''
    stopCurrentBackend()
    loadingHint.value = ''
    sessionReady.value = false
    if (_continuousMode) releaseSharedMicCapture()
    return final
  }

  function abort(opts?: { keepMic?: boolean }) {
    _sessionId += 1
    _startTask = null
    clearResultTimeout()
    stopCurrentBackend()
    if (!opts?.keepMic) releaseSharedMicCapture()
    interimText.value = ''
    loadingHint.value = ''
    sessionReady.value = false
  }

  onBeforeUnmount(() => { abort() })

  return {
    error,
    interimText,
    audioLevel,
    activeBackendId,
    sessionReady,
    loadingHint,
    startListening,
    flushListening,
    signalEndOfSpeech,
    stopListening,
    abort,
  }
}

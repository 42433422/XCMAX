/**
 * 离线 TTS 引擎：使用 transformers.js + Meta MMS-TTS 中文模型。
 *
 * - 首次调用时动态 import `@huggingface/transformers`（避免主包体积暴涨）
 * - 从 HuggingFace Hub 下载 `Xenova/mms-tts-cmn` 的量化 ONNX 权重（≈40–60MB）
 * - 可通过 VITE_HF_REMOTE_HOST 指定 Hub 镜像；官方域名遇 401/403 时会自动改试 hf-mirror.com
 * - transformers.js 内部走浏览器 Cache API，后续访问完全离线
 * - 合成结果是 Float32Array PCM（采样率 16000Hz），用 Web AudioContext 播放
 *
 * 为什么选 MMS-TTS？
 * - 覆盖 1000+ 语种，含 Mandarin Chinese（ISO 639-3: `cmn`）
 * - 非自回归，合成快，适合纯 CPU WASM 推理
 * - 模型体积小，用户等待可接受
 *
 * 局限：
 * - MMS-TTS 不分多说话人，音色偏"普通话女声"，达不到 Azure 云希的自然度
 * - 长文本一次合成内存占用高，这里做了按标点切分的分段合成
 */

type TtsPipeline = (text: string, opts?: Record<string, unknown>) => Promise<{ audio: Float32Array; sampling_rate: number }>

const MODEL_ID = 'Xenova/mms-tts-cmn'
// 备选：如果 cmn 不可用，可切换到 `Xenova/mms-tts-zho`
// 若用户需要更好音质且能接受更大模型，可替换为 'Xenova/vits-zh-*'（约 100MB+）

/** 国内常用 Hub 镜像（与官方 path 模板一致，见 @huggingface/transformers env.remotePathTemplate） */
const HF_MIRROR_REMOTE_HOST = 'https://hf-mirror.com/'

function normalizeHubRemoteHost(raw: string): string {
  const t = raw.trim()
  if (!t) return ''
  try {
    const u = new URL(/\/$/.test(t) ? t : `${t}/`)
    return u.toString()
  } catch {
    return ''
  }
}

/** 未配置或指向官方域名时，401/403 可自动 fallback 到 HF_MIRROR_REMOTE_HOST */
function isOfficialHuggingFaceRemoteHost(host: string): boolean {
  const h = host.trim().toLowerCase()
  if (!h) return true
  try {
    const { hostname } = new URL(h)
    return (
      hostname === 'huggingface.co'
      || hostname === 'www.huggingface.co'
      || hostname === 'hf.co'
    )
  } catch {
    return false
  }
}

/** transformers.js 将 Hub 401/403 映射为英文文案 */
function isHubAuthOrForbiddenError(e: unknown): boolean {
  const msg = e instanceof Error ? e.message : String(e)
  return (
    /Unauthorized access to file/i.test(msg)
    || /Forbidden access to file/i.test(msg)
  )
}

function formatOfflineDownloadError(original: unknown, afterMirrorRetry: boolean): Error {
  const base = original instanceof Error ? original.message : String(original)
  let hint: string
  if (afterMirrorRetry) {
    hint = '已自动尝试 hf-mirror 镜像仍失败。请检查网络代理/VPN，或在 frontend/.env.local 设置 VITE_HF_REMOTE_HOST 为可用的 Hub 镜像地址。'
  } else if (isHubAuthOrForbiddenError(original)) {
    hint = '若处于受限网络，可在 frontend/.env.local 设置 VITE_HF_REMOTE_HOST=https://hf-mirror.com/ 后重新构建或重启 dev。'
  } else {
    hint = '若持续无法连接 Hugging Face，可配置 VITE_HF_REMOTE_HOST（见 frontend/.env.example）。'
  }
  return new Error(`${base}\n${hint}`)
}

let pipelineSingleton: TtsPipeline | null = null
let readyState: 'idle' | 'loading' | 'ready' | 'error' = 'idle'
let lastError: unknown = null
let progress = 0 // 0..1

let audioCtx: AudioContext | null = null
let currentSource: AudioBufferSourceNode | null = null

function getAudioContext(): AudioContext {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)()
  }
  return audioCtx
}

export function isOfflineReady(): boolean { return readyState === 'ready' }
export function isOfflineLoading(): boolean { return readyState === 'loading' }
export function getOfflineProgress(): number { return progress }
export function getOfflineError(): unknown { return lastError }

/**
 * 加载/下载离线模型。进度回调 0..1。
 * 可重复调用，已就绪则直接返回。
 */
export async function ensureOfflineReady(onProgress?: (p: number) => void): Promise<void> {
  if (readyState === 'ready' && pipelineSingleton) return
  if (readyState === 'loading') {
    // 等待上一次加载完成
    await new Promise<void>((resolve) => {
      const t = setInterval(() => {
        if ((readyState as string) !== 'loading') { clearInterval(t); resolve() }
      }, 200)
    })
    if ((readyState as string) === 'ready') return
  }

  readyState = 'loading'
  progress = 0
  onProgress?.(0)
  lastError = null

  try {
    // 动态加载，避免主 bundle 体积过大
    const mod: any = await import('@huggingface/transformers')

    if (mod.env) {
      mod.env.allowRemoteModels = true
      mod.env.allowLocalModels = false
      const fromVite = normalizeHubRemoteHost(String(import.meta.env.VITE_HF_REMOTE_HOST || ''))
      if (fromVite) {
        mod.env.remoteHost = fromVite
      }
      if (mod.env.backends?.onnx?.wasm) {
        mod.env.backends.onnx.wasm.proxy = false
      }
    }

    const pipeline = mod.pipeline as (
      task: string,
      model: string,
      opts?: Record<string, unknown>
    ) => Promise<TtsPipeline>

    const pipelineOpts: Record<string, unknown> = {
      dtype: 'q8',
      progress_callback: (info: any) => {
        if (info && typeof info.progress === 'number') {
          progress = Math.max(progress, Math.min(1, info.progress / 100))
          onProgress?.(progress)
        } else if (info?.status === 'done') {
          progress = 1
          onProgress?.(1)
        }
      },
    }

    let synth: TtsPipeline
    try {
      synth = await pipeline('text-to-speech', MODEL_ID, pipelineOpts)
    } catch (e) {
      const currentHost = String(mod.env?.remoteHost ?? '')
      if (isHubAuthOrForbiddenError(e) && isOfficialHuggingFaceRemoteHost(currentHost) && mod.env) {
        mod.env.remoteHost = HF_MIRROR_REMOTE_HOST
        progress = 0
        onProgress?.(0)
        try {
          synth = await pipeline('text-to-speech', MODEL_ID, pipelineOpts)
        } catch (e2) {
          throw formatOfflineDownloadError(e2, true)
        }
      } else {
        throw formatOfflineDownloadError(e, false)
      }
    }

    pipelineSingleton = synth
    readyState = 'ready'
    progress = 1
    onProgress?.(1)
  } catch (e) {
    lastError = e
    readyState = 'error'
    throw e
  }
}

/** 按中/英文常见断句符号把长文本切成便于合成的短片段。 */
function splitForSynthesis(text: string, maxLen = 80): string[] {
  const normalized = text.replace(/\s+/g, ' ').trim()
  if (!normalized) return []
  const parts: string[] = []
  const re = /[^。！？!?；;\n]+[。！？!?；;\n]?/g
  let m: RegExpExecArray | null
  while ((m = re.exec(normalized)) !== null) {
    const seg = m[0].trim()
    if (!seg) continue
    if (seg.length <= maxLen) {
      parts.push(seg)
    } else {
      // 按逗号继续切
      const sub = seg.split(/[，,、]/).map((s) => s.trim()).filter(Boolean)
      let buf = ''
      for (const s of sub) {
        if ((buf + s).length > maxLen && buf) { parts.push(buf); buf = s }
        else { buf = buf ? `${buf}，${s}` : s }
      }
      if (buf) parts.push(buf)
    }
  }
  return parts
}

/** 合成一整段文本（内部会按标点分段，然后拼成一条 Float32Array）。 */
export async function synthesizeOffline(text: string): Promise<{ audio: Float32Array; samplingRate: number }> {
  if (!pipelineSingleton) throw new Error('离线 TTS 尚未加载，请先调用 ensureOfflineReady()')
  const segments = splitForSynthesis(text)
  if (!segments.length) return { audio: new Float32Array(0), samplingRate: 16000 }

  const chunks: Float32Array[] = []
  let samplingRate = 16000
  for (const seg of segments) {
    const out = await pipelineSingleton(seg)
    if (out?.audio?.length) {
      chunks.push(out.audio)
      if (out.sampling_rate) samplingRate = out.sampling_rate
    }
  }
  const total = chunks.reduce((sum, c) => sum + c.length, 0)
  const merged = new Float32Array(total)
  let off = 0
  for (const c of chunks) { merged.set(c, off); off += c.length }
  return { audio: merged, samplingRate }
}

/** 用 Web Audio 播放 PCM；返回 Promise 在 ended 时 resolve。 */
export function playOfflinePcm(pcm: Float32Array, samplingRate: number): Promise<void> {
  return new Promise((resolve) => {
    if (!pcm || !pcm.length) { resolve(); return }
    try {
      const ctx = getAudioContext()
      const buffer = ctx.createBuffer(1, pcm.length, samplingRate)
      // TS DOM 类型要求 Float32Array<ArrayBuffer>，此处先拷贝到一个新实例以满足类型
      const safePcm = new Float32Array(pcm.length)
      safePcm.set(pcm)
      buffer.copyToChannel(safePcm, 0)
      const src = ctx.createBufferSource()
      src.buffer = buffer
      src.connect(ctx.destination)
      src.onended = () => {
        if (currentSource === src) currentSource = null
        resolve()
      }
      currentSource = src
      src.start()
    } catch {
      resolve()
    }
  })
}

export function stopOffline(): void {
  try {
    if (currentSource) { currentSource.stop(); currentSource.disconnect() }
  } catch { /* ignore */ }
  currentSource = null
}

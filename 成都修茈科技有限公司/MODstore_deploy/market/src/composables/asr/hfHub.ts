/**
 * Hugging Face Hub 模型根 URL（浏览器 Worker 拉取 ONNX 权重）。
 * 生产环境走同源 /market/hf-hub/（nginx 静态目录 /data/hf-hub/），不依赖 huggingface.co。
 */
export function resolveHfRemoteHost(): string {
  const override = import.meta.env.VITE_HF_REMOTE_HOST as string | undefined
  if (override?.trim()) return override.trim().replace(/\/$/, '')

  try {
    const origin =
      typeof self !== 'undefined' && 'location' in self
        ? (self as typeof globalThis).location?.origin
        : typeof globalThis.location !== 'undefined'
          ? globalThis.location.origin
          : ''
    if (origin && origin !== 'null' && /^https?:\/\//.test(origin)) {
      const base = (import.meta.env.BASE_URL || '/').replace(/\/$/, '')
      return `${origin}${base}/hf-hub`
    }
  } catch {
    /* Worker */
  }

  return 'https://huggingface.co'
}

/** 探测同源 Whisper 模型与 ONNX WASM 是否已部署 */
export async function probeWhisperHubReady(): Promise<boolean> {
  try {
    const host = resolveHfRemoteHost()
    const base = (import.meta.env.BASE_URL || '/market/').replace(/\/?$/, '/')
    const origin =
      typeof window !== 'undefined' && window.location?.origin
        ? window.location.origin
        : ''
    const checks = [
      `${host}/onnx-community/whisper-base/resolve/main/config.json`,
    ]
    if (origin && origin !== 'null') {
      checks.push(`${origin}${base}asr-ort/ort-wasm-simd-threaded.asyncify.wasm`)
    }
    const results = await Promise.all(
      checks.map(async (url) => {
        try {
          const res = await fetch(url, { method: 'GET', cache: 'no-store' })
          return res.ok
        } catch {
          return false
        }
      }),
    )
    return results.every(Boolean)
  } catch {
    return false
  }
}

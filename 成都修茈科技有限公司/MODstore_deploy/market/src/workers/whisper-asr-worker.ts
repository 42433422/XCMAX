import { pipeline, env } from '@huggingface/transformers'
import { resolveHfRemoteHost } from '../composables/asr/hfHub'

env.allowLocalModels = false
env.remoteHost = resolveHfRemoteHost()
env.remotePathTemplate = '{model}/resolve/{revision}/'

function resolveOrtWasmBase(): string {
  const base = (import.meta.env.BASE_URL || '/market/').replace(/\/?$/, '/')
  try {
    const origin =
      typeof self !== 'undefined' && 'location' in self
        ? (self as typeof globalThis).location?.origin
        : ''
    if (origin && origin !== 'null') return `${origin}${base}asr-ort/`
  } catch {
    /* ignore */
  }
  return `${base}asr-ort/`
}

const ortRoot = resolveOrtWasmBase()
const wasmBackend = env.backends.onnx.wasm
if (!wasmBackend) {
  throw new Error('ONNX WASM backend is unavailable')
}
wasmBackend.wasmPaths = {
  mjs: `${ortRoot}ort-wasm-simd-threaded.asyncify.mjs`,
  wasm: `${ortRoot}ort-wasm-simd-threaded.asyncify.wasm`,
}

interface WhisperTranscriber {
  (audio: unknown, options: Record<string, unknown>): Promise<{ text?: string }>
}

let transcriber: WhisperTranscriber | null = null
let loadPromise: Promise<WhisperTranscriber> | null = null
let loadError: string | null = null
/** 递增 jobId；新任务 supersede 旧任务，避免 chunk/flush 结果串线 */
let jobSeq = 0
let activeJobId = 0

async function getTranscriber(): Promise<WhisperTranscriber> {
  if (transcriber) return transcriber
  if (loadError) throw new Error(loadError)
  if (loadPromise) return loadPromise
  loadPromise = (async () => {
    try {
      transcriber = (await pipeline('automatic-speech-recognition', 'onnx-community/whisper-base', {
        dtype: {
          encoder_model: 'fp32',
          decoder_model_merged: 'q8',
        },
        device: 'wasm',
        progress_callback: (p: unknown) => {
          self.postMessage({ type: 'progress', data: p })
        },
      })) as unknown as WhisperTranscriber
      self.postMessage({ type: 'ready' })
      return transcriber
    } catch (e: unknown) {
      loadError = e instanceof Error ? e.message : String(e)
      self.postMessage({ type: 'error', data: loadError })
      throw e
    } finally {
      loadPromise = null
    }
  })()
  return loadPromise
}

self.onmessage = async (e: MessageEvent) => {
  const { type, data, jobId: reqJobId } = e.data
  if (type === 'init') {
    try {
      await getTranscriber()
    } catch {
      /* error message already posted */
    }
    return
  }
  if (type === 'transcribe') {
    const jobId = typeof reqJobId === 'number' ? reqJobId : ++jobSeq
    activeJobId = jobId
    try {
      const t = await getTranscriber()
      if (jobId !== activeJobId) return
      const result = await t(data.audio, {
        language: 'chinese',
        task: 'transcribe',
        chunk_length_s: 30,
        stride_length_s: 5,
        return_timestamps: false,
      })
      if (jobId !== activeJobId) return
      self.postMessage({ type: 'result', jobId, data: result.text || '' })
    } catch (err: unknown) {
      if (jobId !== activeJobId) return
      self.postMessage({ type: 'error', jobId, data: err instanceof Error ? err.message : String(err) })
    }
  }
}

import { afterEach, describe, expect, it, vi } from 'vitest'

const mockEnv = {
  allowLocalModels: true,
  remoteHost: '',
  remotePathTemplate: '',
  backends: {
    onnx: {
      wasm: {
        wasmPaths: {},
      },
    },
  },
}
const mockPipeline = vi.fn()

vi.mock('@huggingface/transformers', () => ({
  env: mockEnv,
  pipeline: (...args: unknown[]) => mockPipeline(...args),
}))

vi.mock('./composables/asr/hfHub', () => ({
  resolveHfRemoteHost: () => 'https://hf.example.com',
}))

afterEach(() => {
  mockPipeline.mockReset()
  mockEnv.allowLocalModels = true
  mockEnv.remoteHost = ''
  mockEnv.remotePathTemplate = ''
  mockEnv.backends.onnx.wasm.wasmPaths = {}
  vi.resetModules()
  vi.restoreAllMocks()
  ;(self as unknown as { onmessage?: unknown }).onmessage = undefined
})

describe('whisper worker coverage', () => {
  it('initializes transformers, forwards progress, and posts transcription results', async () => {
    const messages: unknown[] = []
    vi.spyOn(self, 'postMessage').mockImplementation((message) => {
      messages.push(message)
    })
    const transcriber = vi.fn(async () => ({ text: '识别文本' }))
    mockPipeline.mockImplementation(async (_task, _model, opts) => {
      opts.progress_callback({ status: 'loading' })
      return transcriber
    })

    await import('./workers/whisper-asr-worker')
    const handler = (self as unknown as { onmessage: (event: MessageEvent) => Promise<void> }).onmessage

    expect(mockEnv.allowLocalModels).toBe(false)
    expect(mockEnv.remoteHost).toBe('https://hf.example.com')
    expect(mockEnv.remotePathTemplate).toBe('{model}/resolve/{revision}/')
    expect(mockEnv.backends.onnx.wasm.wasmPaths).toEqual({
      mjs: expect.stringContaining('/asr-ort/ort-wasm-simd-threaded.asyncify.mjs'),
      wasm: expect.stringContaining('/asr-ort/ort-wasm-simd-threaded.asyncify.wasm'),
    })

    await handler({ data: { type: 'init' } } as MessageEvent)
    expect(mockPipeline).toHaveBeenCalledWith(
      'automatic-speech-recognition',
      'onnx-community/whisper-base',
      expect.objectContaining({
        device: 'wasm',
        progress_callback: expect.any(Function),
      }),
    )
    expect(messages).toContainEqual({ type: 'progress', data: { status: 'loading' } })
    expect(messages).toContainEqual({ type: 'ready' })

    await handler({ data: { type: 'transcribe', jobId: 7, data: { audio: new Float32Array([0.1]) } } } as MessageEvent)
    expect(transcriber).toHaveBeenCalledWith(new Float32Array([0.1]), {
      language: 'chinese',
      task: 'transcribe',
      chunk_length_s: 30,
      stride_length_s: 5,
      return_timestamps: false,
    })
    expect(messages).toContainEqual({ type: 'result', jobId: 7, data: '识别文本' })
  })

  it('caches load errors and reports them for later transcribe jobs', async () => {
    const messages: unknown[] = []
    vi.spyOn(self, 'postMessage').mockImplementation((message) => {
      messages.push(message)
    })
    mockPipeline.mockRejectedValueOnce(new Error('model offline'))

    await import('./workers/whisper-asr-worker')
    const handler = (self as unknown as { onmessage: (event: MessageEvent) => Promise<void> }).onmessage

    await handler({ data: { type: 'init' } } as MessageEvent)
    expect(messages).toContainEqual({ type: 'error', data: 'model offline' })

    await handler({ data: { type: 'transcribe', jobId: 8, data: { audio: [] } } } as MessageEvent)
    expect(messages).toContainEqual({ type: 'error', jobId: 8, data: 'model offline' })
  })
})

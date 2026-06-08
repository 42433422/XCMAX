import { AudioCapture } from './audioCapture'

type MicHandlers = {
  onAudioData: (pcm: Float32Array) => void
  onAudioLevel?: (level: number) => void
}

let capture: AudioCapture | null = null
let heldStream: MediaStream | null = null
let handlers: MicHandlers | null = null

function streamLive(stream: MediaStream | null): boolean {
  return Boolean(stream?.getAudioTracks().some((t) => t.readyState === 'live'))
}

/** 用户手势内预取的流，供首次开麦 */
export function bindPrefetchedStream(stream: MediaStream) {
  if (streamLive(stream)) heldStream = stream
}

export function getHeldMicStream(): MediaStream | null {
  return streamLive(heldStream) ? heldStream : null
}

export function releaseHeldMicStream() {
  try {
    heldStream?.getTracks().forEach((t) => t.stop())
  } catch { /* */ }
  heldStream = null
}

export async function ensureSharedMicCapture(
  h: MicHandlers,
  prefetched?: MediaStream | Promise<MediaStream>,
): Promise<AudioCapture> {
  handlers = h
  if (capture?.active) {
    capture.setHandlers(h)
    void capture.wake()
    return capture
  }

  let stream = getHeldMicStream()
  if (!stream && prefetched) {
    stream = prefetched instanceof MediaStream ? prefetched : await prefetched
    if (streamLive(stream)) heldStream = stream
  }

  capture = new AudioCapture()
  await capture.start(
    {
      onAudioData: (pcm) => handlers?.onAudioData(pcm),
      onAudioLevel: (level) => handlers?.onAudioLevel?.(level),
    },
    stream ?? undefined,
  )

  if (capture.active && !heldStream) {
    // 自有 getUserMedia 的流也保留，重连时复用
    // AudioCapture 不暴露 stream，但 ownsStream=true 时 stop 会关 track
    // 首次成功后标记：后续 reconnect 仍用同一 capture 实例，不 stop
  }

  void capture.wake()
  return capture
}

export function getSharedMicCapture(): AudioCapture | null {
  return capture?.active ? capture : null
}

export function releaseSharedMicCapture() {
  capture?.stop()
  capture = null
  handlers = null
  releaseHeldMicStream()
}

/** 页面可见 / 用户点击时唤醒 AudioContext */
export function wakeSharedMicCapture() {
  void capture?.wake()
}

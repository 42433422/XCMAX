import { bindPrefetchedStream, getHeldMicStream } from './sharedMicCapture'

let pendingMic: Promise<MediaStream> | null = null

/** 必须在用户点击事件的同步调用栈里 invoke */
export function requestMicInUserGesture(): Promise<MediaStream> | null {
  if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) return null
  pendingMic = navigator.mediaDevices
    .getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    })
    .catch(() => navigator.mediaDevices.getUserMedia({ audio: true }))
  void pendingMic.then((s) => bindPrefetchedStream(s)).catch(() => {})
  return pendingMic
}

export function takeMicPreflight(): Promise<MediaStream> | null {
  const held = getHeldMicStream()
  if (held) return Promise.resolve(held)
  const p = pendingMic
  pendingMic = null
  if (p) {
    void p.then((s) => bindPrefetchedStream(s)).catch(() => {})
  }
  return p
}

export function clearMicPreflight() {
  pendingMic = null
}

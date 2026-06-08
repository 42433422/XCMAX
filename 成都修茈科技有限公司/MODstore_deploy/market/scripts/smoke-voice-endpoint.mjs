/**
 * 语音断句逻辑冒烟（不依赖浏览器麦克风）
 * 运行: node scripts/smoke-voice-endpoint.mjs
 */
const VOICE_ENDPOINT = {
  silenceMs: 700,
  speechLevel: 0.024,
  partialStableMs: 1300,
  partialMinChars: 6,
}

function makeHarness() {
  let audioSpeaking = false
  let lastSpeechAt = 0
  let lastAsrContentChangeAt = 0
  let lastAsrAt = 0
  let hadSpeech = false
  let listenPartial = ''
  let lastSubmittedText = ''
  let lastSubmittedAt = 0

  function silenceIdleMs(now) {
    if (audioSpeaking) return 0
    if (lastSpeechAt > 0) return now - lastSpeechAt
    if (listenPartial.trim() && lastAsrContentChangeAt > 0) {
      return now - lastAsrContentChangeAt
    }
    const asrAnchor = lastAsrContentChangeAt || lastAsrAt
    return asrAnchor > 0 ? now - asrAnchor : 0
  }

  function hasFreshCapture(text) {
    const t = text.trim()
    if (!t) return false
    if (t !== lastSubmittedText) return true
    return lastAsrAt > lastSubmittedAt
  }

  function shouldFlushUtterance(now) {
    if (audioSpeaking) return false
    if (silenceIdleMs(now) < VOICE_ENDPOINT.silenceMs - 80) return false
    const text = listenPartial.trim()
    if (!text) return false
    if (text.length < VOICE_ENDPOINT.partialMinChars) return false
    if (hasFreshCapture(text)) return true
    if (lastAsrContentChangeAt > 0 || hadSpeech) return true
    return false
  }

  function onAudioLevel(level, now) {
    const speaking = level >= VOICE_ENDPOINT.speechLevel
    if (speaking) {
      hadSpeech = true
      audioSpeaking = true
      lastSpeechAt = now
      return
    }
    if (audioSpeaking) {
      audioSpeaking = false
      lastSpeechAt = now
    }
  }

  function onAsrText(text, now) {
    if (!text.trim()) return
    const changed = text.trim() !== listenPartial
    listenPartial = text.trim()
    lastAsrAt = now
    lastSpeechAt = now
    if (changed) lastAsrContentChangeAt = now
    hadSpeech = true
  }

  return {
    onAudioLevel,
    onAsrText,
    shouldFlushUtterance,
    markSubmitted: (t) => {
      lastSubmittedText = t
      lastSubmittedAt = Date.now()
      listenPartial = ''
      hadSpeech = false
      audioSpeaking = false
      lastSpeechAt = 0
      lastAsrContentChangeAt = 0
    },
  }
}

function assert(name, cond) {
  if (!cond) throw new Error(`FAIL: ${name}`)
  console.log(`OK: ${name}`)
}

const h = makeHarness()
let t = 1000

h.onAudioLevel(0.05, t)
t += 200
h.onAsrText('你好世界测试语句够长', t)
t += 100
h.onAudioLevel(0.06, t)
assert('说话时不断句', !h.shouldFlushUtterance(t))

t += 100
h.onAudioLevel(0.001, t)
assert('刚停顿时还未到阈值', !h.shouldFlushUtterance(t + 400))
assert('停顿足够长后自动发送', h.shouldFlushUtterance(t + VOICE_ENDPOINT.silenceMs))

h.markSubmitted('你好世界测试语句够长')
t += 2000
h.onAudioLevel(0.001, t)
assert('已发送后不会重复发送', !h.shouldFlushUtterance(t + VOICE_ENDPOINT.silenceMs))

h.onAsrText('短', t + 3000)
assert('低于 partialMinChars 不发送', !h.shouldFlushUtterance(t + 3000 + VOICE_ENDPOINT.silenceMs))

const h2 = makeHarness()
let t2 = 5000
h2.onAsrText('现在听得到吗', t2)
h2.onAudioLevel(0.001, t2 + 200)
assert('7 字短问句停顿后可发送', h2.shouldFlushUtterance(t2 + VOICE_ENDPOINT.silenceMs))

console.log('\n全部断句冒烟通过')

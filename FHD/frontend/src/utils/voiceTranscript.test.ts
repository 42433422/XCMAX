import { describe, expect, it } from 'vitest'
import {
  hasTranscriptContent,
  isDuplicateTranscript,
  isLowInformationTranscript,
  normalizeVoiceTranscript,
} from '@/utils/voiceTranscript'

describe('voiceTranscript', () => {
  it('剥离语种占位标签与零宽字符', () => {
    expect(normalizeVoiceTranscript('<chinese>帮我查库存\u200b</chinese>')).toBe('帮我查库存')
  })

  it('全角字母数字转半角并在中英文之间补空格', () => {
    expect(normalizeVoiceTranscript('打开ＣＲＭ系统')).toBe('打开 CRM 系统')
  })

  it('收敛重复标点', () => {
    expect(normalizeVoiceTranscript('好的。。。')).toBe('好的。')
  })

  it('判定低信息量结果', () => {
    expect(isLowInformationTranscript('')).toBe(true)
    expect(isLowInformationTranscript('，。')).toBe(true)
    expect(isLowInformationTranscript('嗯')).toBe(true)
    expect(isLowInformationTranscript('库存')).toBe(false)
    expect(hasTranscriptContent('12')).toBe(true)
  })

  it('窗口内重复转写被丢弃，窗口外放行', () => {
    const previous = { text: '帮我查库存', at: 1_000 }
    expect(isDuplicateTranscript('帮我查库存。', previous, 3_000, 2_000)).toBe(true)
    expect(isDuplicateTranscript('帮我查库存', previous, 3_000, 5_000)).toBe(false)
    expect(isDuplicateTranscript('帮我查订单', previous, 3_000, 2_000)).toBe(false)
    expect(isDuplicateTranscript('帮我查库存', null, 3_000, 2_000)).toBe(false)
  })
})

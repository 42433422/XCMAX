import { describe, expect, it } from 'vitest'
import {
  modelSupportsVisionInput,
  flattenTextForLlmContext,
  buildUserMultimodalContent,
  isImageFileForVision,
} from './visionMultimodal'

describe('modelSupportsVisionInput', () => {
  it('returns false for empty model', () => {
    expect(modelSupportsVisionInput('openai', '', null)).toBe(false)
  })

  it('returns true for model matching vision regex', () => {
    expect(modelSupportsVisionInput('openai', 'gpt-4o', null)).toBe(true)
    expect(modelSupportsVisionInput('openai', 'gpt-4-turbo', null)).toBe(true)
    expect(modelSupportsVisionInput('google', 'gemini-2.0-flash', null)).toBe(true)
    expect(modelSupportsVisionInput('anthropic', 'claude-3-opus', null)).toBe(true)
    expect(modelSupportsVisionInput('anthropic', 'claude-sonnet-4', null)).toBe(true)
  })

  it('returns false for non-vision model', () => {
    expect(modelSupportsVisionInput('openai', 'gpt-3.5-turbo', null)).toBe(false)
    expect(modelSupportsVisionInput('openai', 'text-embedding-ada-002', null)).toBe(false)
  })

  it('returns true when catalog has vlm category', () => {
    const catalog = {
      providers: [{
        provider: 'openai',
        models_detailed: [{ id: 'custom-vlm', category: 'vlm' }],
      }],
    }
    expect(modelSupportsVisionInput('openai', 'custom-vlm', catalog)).toBe(true)
  })

  it('returns false when catalog has non-vlm category', () => {
    const catalog = {
      providers: [{
        provider: 'openai',
        models_detailed: [{ id: 'gpt-3.5', category: 'llm' }],
      }],
    }
    expect(modelSupportsVisionInput('openai', 'gpt-3.5', catalog)).toBe(false)
  })

  it('handles null catalog gracefully', () => {
    expect(modelSupportsVisionInput('openai', 'gpt-4o', null)).toBe(true)
    expect(modelSupportsVisionInput('openai', 'gpt-3.5', null)).toBe(false)
  })
})

describe('flattenTextForLlmContext', () => {
  it('returns text when no parts', () => {
    expect(flattenTextForLlmContext('hello', undefined)).toBe('hello')
  })

  it('returns text when parts is empty', () => {
    expect(flattenTextForLlmContext('hello', [])).toBe('hello')
  })

  it('combines text with text parts', () => {
    const parts = [{ type: 'text' as const, text: 'world' }]
    expect(flattenTextForLlmContext('hello', parts)).toBe('hello\nworld')
  })

  it('ignores non-text parts', () => {
    const parts = [
      { type: 'image_url' as const, image_url: { url: 'http://img.png' } },
      { type: 'text' as const, text: 'caption' },
    ]
    expect(flattenTextForLlmContext('hello', parts)).toBe('hello\ncaption')
  })

  it('filters out empty text parts', () => {
    const parts = [{ type: 'text' as const, text: '' }, { type: 'text' as const, text: 'content' }]
    expect(flattenTextForLlmContext('main', parts)).toBe('main\ncontent')
  })
})

describe('buildUserMultimodalContent', () => {
  it('returns plain text when no images', () => {
    expect(buildUserMultimodalContent('hello', [])).toBe('hello')
  })

  it('returns plain text when no images and no text', () => {
    expect(buildUserMultimodalContent('', [])).toBe('')
  })

  it('returns parts array with text and images', () => {
    const result = buildUserMultimodalContent('hello', ['data:image/png;base64,abc'])
    expect(Array.isArray(result)).toBe(true)
    const parts = result as Array<{ type: string }>
    expect(parts).toHaveLength(2)
    expect(parts[0].type).toBe('text')
    expect(parts[1].type).toBe('image_url')
  })

  it('returns parts array with only images when no text', () => {
    const result = buildUserMultimodalContent('', ['data:image/png;base64,abc'])
    expect(Array.isArray(result)).toBe(true)
    const parts = result as Array<{ type: string }>
    expect(parts).toHaveLength(1)
    expect(parts[0].type).toBe('image_url')
  })

  it('filters empty image URLs', () => {
    const result = buildUserMultimodalContent('hello', ['', '  ', 'data:image/png;base64,abc'])
    const parts = result as Array<{ type: string }>
    expect(parts).toHaveLength(2)
  })

  it('returns plain text when only text and no images', () => {
    const result = buildUserMultimodalContent('hello only', [])
    expect(typeof result).toBe('string')
    expect(result).toBe('hello only')
  })
})

describe('isImageFileForVision', () => {
  it('detects image mime types', () => {
    expect(isImageFileForVision(new File([], 'test.png', { type: 'image/png' }))).toBe(true)
    expect(isImageFileForVision(new File([], 'test.jpg', { type: 'image/jpeg' }))).toBe(true)
    expect(isImageFileForVision(new File([], 'test.webp', { type: 'image/webp' }))).toBe(true)
  })

  it('detects image extensions when no mime type', () => {
    expect(isImageFileForVision(new File([], 'photo.png'))).toBe(true)
    expect(isImageFileForVision(new File([], 'photo.jpg'))).toBe(true)
    expect(isImageFileForVision(new File([], 'photo.jpeg'))).toBe(true)
    expect(isImageFileForVision(new File([], 'photo.webp'))).toBe(true)
    expect(isImageFileForVision(new File([], 'photo.gif'))).toBe(true)
    expect(isImageFileForVision(new File([], 'photo.bmp'))).toBe(true)
  })

  it('rejects non-image files', () => {
    expect(isImageFileForVision(new File([], 'doc.pdf', { type: 'application/pdf' }))).toBe(false)
    expect(isImageFileForVision(new File([], 'data.csv'))).toBe(false)
    expect(isImageFileForVision(new File([], 'script.js', { type: 'text/javascript' }))).toBe(false)
  })

  it('handles files without extension', () => {
    expect(isImageFileForVision(new File([], 'noext', { type: 'text/plain' }))).toBe(false)
  })
})

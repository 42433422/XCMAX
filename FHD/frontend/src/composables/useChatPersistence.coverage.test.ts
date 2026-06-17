/**
 * Coverage ramp 测试：useChatPersistence
 *
 * 目标：覆盖 useChatPersistence.ts 中尚未被现有 useChatPersistence.test.ts 触达的
 *   - readPersistedTaskPanelState / persistTaskPanelState / clearPersistedTaskPanelState
 *   - toPlainText / isWelcomeMessage / toHistoryTimestamp
 *   - useChatHistoryPersistence（normalizeHistorySessions / readLocalMessagesBySession /
 *     readLocalSessionMeta / deriveLocalSessionTitle / buildLocalHistorySession /
 *     listLocalHistorySessions / mergeHistorySessions / clearLocalHistoryCache）
 *   - useChatTaskPanelPersistence（persistTaskPanelStateForSession /
 *     applyPersistedTaskPanelStateForSession）
 *
 * 铁律3：覆盖 happy path、空值/None、边界值、异常路径（JSON 解析错误、storage 不可用）。
 * 铁律4：仅 mock 外部边界（localStorage / sessionStorage / pinia store），被测 composable 真实调用。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'
import {
  readPersistedExcelAnalysisContext,
  persistExcelAnalysisContext,
  resolveExcelFilePathFromAnalysis,
  resolveExcelSheetOptionsFromContext,
  resolveLinkedSheetGridPreview,
  extractLikelyProductQueryKeyword,
  readPersistedTaskPanelState,
  persistTaskPanelState,
  clearPersistedTaskPanelState,
  toPlainText,
  isWelcomeMessage,
  toHistoryTimestamp,
  useChatHistoryPersistence,
  useChatTaskPanelPersistence,
  EXCEL_ANALYSIS_STORAGE_PREFIX,
  CHAT_TASK_PANEL_STORAGE_PREFIX,
  TASK_HISTORY_LIMIT,
  type TaskItem,
  type PersistedTaskPanelState,
} from './useChatPersistence'

// 仅 mock 外部边界：chatStorageKeys 的 build*Key / extractSessionIdForActiveMod
// 真实调用被测 composable 本身。
const mockBuildChatMessagesKey = vi.fn(
  (sid: string, _modId?: string) => `xcagi_chat_messages_${sid}`,
)
const mockBuildChatSessionMetaKey = vi.fn(
  (sid: string, _modId?: string) => `xcagi_chat_session_meta_${sid}`,
)
const mockExtractSessionIdForActiveMod = vi.fn(
  (prefix: string, key: string, _modId?: string) => {
    // Mimic real behavior: only return sessionId when key starts with prefix
    const raw = String(key || '')
    if (!raw.startsWith(prefix)) return null
    const rest = raw.slice(prefix.length)
    return rest || null
  },
)

vi.mock('@/utils/chatStorageKeys', () => ({
  CHAT_MESSAGES_STORAGE_PREFIX: 'xcagi_chat_messages_',
  CHAT_SESSION_META_PREFIX: 'xcagi_chat_session_meta_',
  buildChatMessagesKey: (...args: unknown[]) => mockBuildChatMessagesKey(...args),
  buildChatSessionMetaKey: (...args: unknown[]) => mockBuildChatSessionMetaKey(...args),
  extractSessionIdForActiveMod: (...args: unknown[]) =>
    mockExtractSessionIdForActiveMod(...args),
}))

// isIndustryWelcomePlainText 真实模块依赖 hostConfig；用 stub 隔离以避免拉起整个 store
vi.mock('@/constants/industryPresets', () => ({
  isIndustryWelcomePlainText: (plain: string) => {
    const t = String(plain || '').trim()
    if (!t) return false
    return t.startsWith('你好，我是业务助手。') || t.startsWith('您好！我是您的')
  },
}))

describe('useChatPersistence — coverage ramp', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    localStorage.clear()
    mockBuildChatMessagesKey.mockClear()
    mockBuildChatSessionMetaKey.mockClear()
    mockExtractSessionIdForActiveMod.mockClear()
    mockBuildChatMessagesKey.mockImplementation(
      (sid: string, _modId?: string) => `xcagi_chat_messages_${sid}`,
    )
    mockBuildChatSessionMetaKey.mockImplementation(
      (sid: string, _modId?: string) => `xcagi_chat_session_meta_${sid}`,
    )
    mockExtractSessionIdForActiveMod.mockImplementation(
      (prefix: string, key: string, _modId?: string) => {
        const raw = String(key || '')
        if (!raw.startsWith(prefix)) return null
        const rest = raw.slice(prefix.length)
        return rest || null
      },
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // -----------------------------------------------------------------------
  // readPersistedExcelAnalysisContext — 异常路径补强
  // -----------------------------------------------------------------------
  describe('readPersistedExcelAnalysisContext — edge cases', () => {
    it('returns null when sessionKey is empty', () => {
      expect(readPersistedExcelAnalysisContext('')).toBeNull()
    })

    it('returns null when stored value is not an object (string)', () => {
      sessionStorage.setItem(EXCEL_ANALYSIS_STORAGE_PREFIX + 's1', JSON.stringify('hello'))
      expect(readPersistedExcelAnalysisContext('s1')).toBeNull()
    })

    it('returns the array as-is when stored value is an array (arrays are objects in JS)', () => {
      // Note: typeof [] === 'object', so arrays pass the object check
      sessionStorage.setItem(EXCEL_ANALYSIS_STORAGE_PREFIX + 's1', JSON.stringify([1, 2]))
      const result = readPersistedExcelAnalysisContext('s1')
      expect(result).toEqual([1, 2])
    })

    it('returns null when stored value is not an object (number)', () => {
      sessionStorage.setItem(EXCEL_ANALYSIS_STORAGE_PREFIX + 's1', JSON.stringify(42))
      expect(readPersistedExcelAnalysisContext('s1')).toBeNull()
    })

    it('returns object when stored value is a valid object', () => {
      sessionStorage.setItem(
        EXCEL_ANALYSIS_STORAGE_PREFIX + 's1',
        JSON.stringify({ a: 1, nested: { b: 2 } }),
      )
      expect(readPersistedExcelAnalysisContext('s1')).toEqual({ a: 1, nested: { b: 2 } })
    })

    it('returns null when JSON.parse throws (corrupted data)', () => {
      sessionStorage.setItem(EXCEL_ANALYSIS_STORAGE_PREFIX + 's1', '{not-json')
      expect(readPersistedExcelAnalysisContext('s1')).toBeNull()
    })
  })

  // -----------------------------------------------------------------------
  // persistExcelAnalysisContext — 异常路径补强
  // -----------------------------------------------------------------------
  describe('persistExcelAnalysisContext — edge cases', () => {
    it('stores with empty key prefix when sessionKey is empty (no early return)', () => {
      // Source does not early-return on empty sessionKey; it just uses '' as the key
      persistExcelAnalysisContext('', { a: 1 })
      expect(sessionStorage.getItem(EXCEL_ANALYSIS_STORAGE_PREFIX)).toBe(
        JSON.stringify({ a: 1 }),
      )
    })

    it('removes key when ctx is null', () => {
      sessionStorage.setItem(EXCEL_ANALYSIS_STORAGE_PREFIX + 's1', 'old')
      persistExcelAnalysisContext('s1', null)
      expect(sessionStorage.getItem(EXCEL_ANALYSIS_STORAGE_PREFIX + 's1')).toBeNull()
    })

    it('stores stringified object when ctx is provided', () => {
      persistExcelAnalysisContext('s1', { file_path: '/x.xlsx' })
      expect(sessionStorage.getItem(EXCEL_ANALYSIS_STORAGE_PREFIX + 's1')).toBe(
        JSON.stringify({ file_path: '/x.xlsx' }),
      )
    })

    it('swallows quota errors silently', () => {
      const orig = sessionStorage.setItem
      sessionStorage.setItem = vi.fn(() => {
        throw new Error('QuotaExceededError')
      })
      expect(() => persistExcelAnalysisContext('s1', { a: 1 })).not.toThrow()
      sessionStorage.setItem = orig
    })
  })

  // -----------------------------------------------------------------------
  // resolveExcelFilePathFromAnalysis — 边界值补强
  // -----------------------------------------------------------------------
  describe('resolveExcelFilePathFromAnalysis — edge cases', () => {
    it('returns empty string for undefined', () => {
      expect(resolveExcelFilePathFromAnalysis(undefined)).toBe('')
    })

    it('returns empty string when all candidates are empty', () => {
      expect(resolveExcelFilePathFromAnalysis({})).toBe('')
    })

    it('trims whitespace from file_path', () => {
      expect(resolveExcelFilePathFromAnalysis({ file_path: '  /a.xlsx  ' })).toBe('/a.xlsx')
    })

    it('returns first non-empty candidate (data.preview_data.file_path)', () => {
      expect(
        resolveExcelFilePathFromAnalysis({
          data: { preview_data: { file_path: '/inner.xlsx' } },
        }),
      ).toBe('/inner.xlsx')
    })

    it('returns file_path from data.preview_data.file_path when top-level missing', () => {
      expect(
        resolveExcelFilePathFromAnalysis({
          data: { preview_data: { file_path: '/deep.xlsx' } },
        }),
      ).toBe('/deep.xlsx')
    })

    it('returns file_path from upload.file_path', () => {
      expect(resolveExcelFilePathFromAnalysis({ upload: { file_path: '/u.xlsx' } })).toBe(
        '/u.xlsx',
      )
    })

    it('returns file_path from source.file_path', () => {
      expect(resolveExcelFilePathFromAnalysis({ source: { file_path: '/s.xlsx' } })).toBe(
        '/s.xlsx',
      )
    })

    it('returns file_path from document.file_path (not filepath)', () => {
      expect(
        resolveExcelFilePathFromAnalysis({ document: { file_path: '/df.xlsx' } }),
      ).toBe('/df.xlsx')
    })

    it('skips empty string candidates and returns first non-empty', () => {
      expect(
        resolveExcelFilePathFromAnalysis({
          file_path: '',
          preview_data: { file_path: '' },
          data: { file_path: '/real.xlsx' },
        }),
      ).toBe('/real.xlsx')
    })
  })

  // -----------------------------------------------------------------------
  // resolveExcelSheetOptionsFromContext — 边界值补强
  // -----------------------------------------------------------------------
  describe('resolveExcelSheetOptionsFromContext — edge cases', () => {
    it('returns empty array for non-object ctx (number)', () => {
      expect(resolveExcelSheetOptionsFromContext(42)).toEqual([])
    })

    it('returns empty array for non-object ctx (string)', () => {
      expect(resolveExcelSheetOptionsFromContext('hello')).toEqual([])
    })

    it('returns empty array when preview_data is not object', () => {
      expect(resolveExcelSheetOptionsFromContext({ preview_data: 'nope' })).toEqual([])
    })

    it('returns empty array when all_sheets is empty', () => {
      expect(resolveExcelSheetOptionsFromContext({ preview_data: { all_sheets: [] } })).toEqual(
        [],
      )
    })

    it('uses idx+1 when sheet_index missing or invalid', () => {
      const result = resolveExcelSheetOptionsFromContext({
        preview_data: {
          all_sheets: [{ sheet_name: 'A' }, { sheet_name: 'B', sheet_index: 'bad' }],
        },
      })
      expect(result).toEqual([
        { sheet_name: 'A', sheet_index: 1 },
        { sheet_name: 'B', sheet_index: 2 },
      ])
    })

    it('skips entries with empty/whitespace sheet_name', () => {
      const result = resolveExcelSheetOptionsFromContext({
        preview_data: {
          all_sheets: [
            { sheet_name: '   ', sheet_index: 1 },
            { sheet_name: 'B', sheet_index: 2 },
          ],
        },
      })
      expect(result).toEqual([{ sheet_name: 'B', sheet_index: 2 }])
    })

    it('falls back to sheet_names when all_sheets absent', () => {
      const result = resolveExcelSheetOptionsFromContext({
        preview_data: { sheet_names: ['X', 'Y'] },
      })
      expect(result).toEqual([
        { sheet_name: 'X', sheet_index: 1 },
        { sheet_name: 'Y', sheet_index: 2 },
      ])
    })

    it('skips empty entries in sheet_names', () => {
      const result = resolveExcelSheetOptionsFromContext({
        preview_data: { sheet_names: ['', 'Y'] },
      })
      expect(result).toEqual([{ sheet_name: 'Y', sheet_index: 2 }])
    })

    it('returns empty array when sheet_names is not array', () => {
      expect(
        resolveExcelSheetOptionsFromContext({ preview_data: { sheet_names: 'nope' } }),
      ).toEqual([])
    })
  })

  // -----------------------------------------------------------------------
  // resolveLinkedSheetGridPreview — 边界值补强
  // -----------------------------------------------------------------------
  describe('resolveLinkedSheetGridPreview — edge cases', () => {
    it('returns null when linkedSheet has empty sheet_name', () => {
      expect(
        resolveLinkedSheetGridPreview({ preview_data: {} }, { sheet_name: '', sheet_index: 1 }),
      ).toBeNull()
    })

    it('returns null when linkedSheet is null', () => {
      expect(resolveLinkedSheetGridPreview({}, null)).toBeNull()
    })

    it('returns null when ctx is a primitive', () => {
      expect(
        resolveLinkedSheetGridPreview('hello', { sheet_name: 'A', sheet_index: 1 }),
      ).toBeNull()
    })

    it('matches by sheet_index when sheet_name mismatch', () => {
      const ctx = {
        preview_data: {
          all_sheets: [
            { sheet_name: 'AAA', sheet_index: 5, fields: [{ label: 'F1' }] },
          ],
        },
      }
      const result = resolveLinkedSheetGridPreview(ctx, { sheet_name: 'BBB', sheet_index: 5 })
      expect(result).not.toBeNull()
      expect(result!.sheet_name).toBe('BBB')
      expect(result!.sheet_index).toBe(5)
    })

    it('uses field name when label missing', () => {
      const ctx = {
        preview_data: {
          all_sheets: [
            {
              sheet_name: 'S1',
              sheet_index: 1,
              fields: [{ name: 'FieldOnly' }],
            },
          ],
        },
      }
      const result = resolveLinkedSheetGridPreview(ctx, { sheet_name: 'S1', sheet_index: 1 })
      expect(result!.field_names).toContain('FieldOnly')
    })

    it('truncates sample_rows to 8', () => {
      const rows = Array.from({ length: 20 }, (_, i) => ({ i }))
      const ctx = {
        preview_data: {
          all_sheets: [{ sheet_name: 'S1', sheet_index: 1, sample_rows: rows }],
        },
      }
      const result = resolveLinkedSheetGridPreview(ctx, { sheet_name: 'S1', sheet_index: 1 })
      expect(result!.sample_rows).toHaveLength(8)
    })

    it('truncates grid_preview rows to 60', () => {
      const rows = Array.from({ length: 100 }, (_, i) => ({ i }))
      const ctx = {
        preview_data: {
          all_sheets: [
            {
              sheet_name: 'S1',
              sheet_index: 1,
              grid_preview: { rows },
            },
          ],
        },
      }
      const result = resolveLinkedSheetGridPreview(ctx, { sheet_name: 'S1', sheet_index: 1 })
      expect(result!.grid_preview_rows).toHaveLength(60)
    })

    it('truncates fields to 40', () => {
      const fields = Array.from({ length: 50 }, (_, i) => ({ label: `F${i}` }))
      const ctx = {
        preview_data: {
          all_sheets: [{ sheet_name: 'S1', sheet_index: 1, fields }],
        },
      }
      const result = resolveLinkedSheetGridPreview(ctx, { sheet_name: 'S1', sheet_index: 1 })
      expect(result!.field_names).toHaveLength(40)
    })

    it('preview_text contains sheet name and index', () => {
      const ctx = {
        preview_data: {
          all_sheets: [{ sheet_name: 'MySheet', sheet_index: 3 }],
        },
      }
      const result = resolveLinkedSheetGridPreview(ctx, { sheet_name: 'MySheet', sheet_index: 3 })
      expect(result!.preview_text).toContain('Sheet 3')
      expect(result!.preview_text).toContain('MySheet')
    })
  })

  // -----------------------------------------------------------------------
  // extractLikelyProductQueryKeyword — 边界值补强
  // -----------------------------------------------------------------------
  describe('extractLikelyProductQueryKeyword — edge cases', () => {
    it('returns null for empty string', () => {
      expect(extractLikelyProductQueryKeyword('')).toBeNull()
    })

    it('returns null for whitespace-only', () => {
      expect(extractLikelyProductQueryKeyword('   ')).toBeNull()
    })

    it('returns null for exactly 2 chars (boundary)', () => {
      // length 2 is allowed but no pattern matches
      expect(extractLikelyProductQueryKeyword('查询')).toBeNull()
    })

    it('returns null for exactly 201 chars', () => {
      expect(extractLikelyProductQueryKeyword('x'.repeat(201))).toBeNull()
    })

    it('returns null for input starting with 为什么', () => {
      expect(extractLikelyProductQueryKeyword('为什么价格这么贵')).toBeNull()
    })

    it('returns null for input starting with 能否', () => {
      expect(extractLikelyProductQueryKeyword('能否帮我查一下')).toBeNull()
    })

    it('returns null for input starting with 请', () => {
      expect(extractLikelyProductQueryKeyword('请查询 X100')).toBeNull()
    })

    it('returns null for input starting with 帮', () => {
      expect(extractLikelyProductQueryKeyword('帮我查 X100')).toBeNull()
    })

    it('returns null for input containing 工作流', () => {
      expect(extractLikelyProductQueryKeyword('工作流执行')).toBeNull()
    })

    it('returns null for input containing 数据库', () => {
      expect(extractLikelyProductQueryKeyword('数据库备份')).toBeNull()
    })

    it('returns null for input containing 导入', () => {
      expect(extractLikelyProductQueryKeyword('导入Excel文件')).toBeNull()
    })

    it('returns null for input containing 上传', () => {
      expect(extractLikelyProductQueryKeyword('上传文件')).toBeNull()
    })

    it('returns null for input containing 打印标签', () => {
      expect(extractLikelyProductQueryKeyword('打印标签A001')).toBeNull()
    })

    it('returns null for input containing 有哪些客户', () => {
      expect(extractLikelyProductQueryKeyword('有哪些客户')).toBeNull()
    })

    it('extracts keyword from 查询 pattern', () => {
      expect(extractLikelyProductQueryKeyword('查询XCD-100')).toBe('XCD-100')
    })

    it('strips quotes from extracted keyword (「」)', () => {
      expect(extractLikelyProductQueryKeyword('查询「XCD-100」')).toBe('XCD-100')
    })

    it('strips quotes from extracted keyword ("")', () => {
      expect(extractLikelyProductQueryKeyword('查询"XCD-100"')).toBe('XCD-100')
    })

    it('strips quotes from extracted keyword (『』)', () => {
      expect(extractLikelyProductQueryKeyword('查询『XCD-100』')).toBe('XCD-100')
    })

    it('strips 产品 prefix from extracted keyword (with separator)', () => {
      // Regex requires separator after prefix: /^(产品|型号|货号)[是为：:\s]+/
      expect(extractLikelyProductQueryKeyword('查询产品：XCD-100')).toBe('XCD-100')
    })

    it('strips 型号 prefix from extracted keyword (with separator)', () => {
      expect(extractLikelyProductQueryKeyword('查询型号 XCD-100')).toBe('XCD-100')
    })

    it('strips 货号 prefix from extracted keyword (with separator)', () => {
      expect(extractLikelyProductQueryKeyword('查询货号：XCD-100')).toBe('XCD-100')
    })

    it('does not strip 产品 prefix when no separator follows', () => {
      // Without separator, prefix is not stripped
      const result = extractLikelyProductQueryKeyword('查询产品XCD-100')
      expect(result).toBe('产品XCD-100')
    })

    it('strips trailing punctuation from extracted keyword', () => {
      expect(extractLikelyProductQueryKeyword('查询XCD-100。。。')).toBe('XCD-100')
    })

    it('extracts keyword from 查一下 pattern with 价格', () => {
      expect(extractLikelyProductQueryKeyword('查一下XCD-200的价格')).toBe('XCD-200')
    })

    it('extracts keyword from 查一下 pattern without 价格', () => {
      expect(extractLikelyProductQueryKeyword('查一下XCD-200')).toBe('XCD-200')
    })

    it('returns null when extracted keyword is too long (>120 chars)', () => {
      const long = 'X'.repeat(121)
      expect(extractLikelyProductQueryKeyword(`查询${long}`)).toBeNull()
    })

    it('returns null when extracted keyword is empty after trim', () => {
      expect(extractLikelyProductQueryKeyword('查询')).toBeNull()
    })

    it('returns null for non-matching input', () => {
      expect(extractLikelyProductQueryKeyword('普通对话内容')).toBeNull()
    })
  })

  // -----------------------------------------------------------------------
  // toPlainText
  // -----------------------------------------------------------------------
  describe('toPlainText', () => {
    it('returns empty string for null', () => {
      expect(toPlainText(null)).toBe('')
    })

    it('returns empty string for undefined', () => {
      expect(toPlainText(undefined)).toBe('')
    })

    it('returns empty string for empty string', () => {
      expect(toPlainText('')).toBe('')
    })

    it('returns string as-is when no HTML', () => {
      expect(toPlainText('hello world')).toBe('hello world')
    })

    it('converts <br> to newline', () => {
      expect(toPlainText('a<br>b')).toBe('a\nb')
    })

    it('converts <br/> to newline', () => {
      expect(toPlainText('a<br/>b')).toBe('a\nb')
    })

    it('converts <br /> to newline', () => {
      expect(toPlainText('a<br />b')).toBe('a\nb')
    })

    it('strips HTML tags', () => {
      expect(toPlainText('<p>hello</p>')).toBe('hello')
    })

    it('converts &nbsp; to space', () => {
      expect(toPlainText('a&nbsp;b')).toBe('a b')
    })

    it('trims leading/trailing whitespace', () => {
      expect(toPlainText('  hello  ')).toBe('hello')
    })

    it('converts number to string', () => {
      expect(toPlainText(42)).toBe('42')
    })
  })

  // -----------------------------------------------------------------------
  // isWelcomeMessage
  // -----------------------------------------------------------------------
  describe('isWelcomeMessage', () => {
    it('returns false when role is not ai', () => {
      expect(isWelcomeMessage({ role: 'user', content: '你好，我是业务助手。' })).toBe(false)
    })

    it('returns false when role is missing', () => {
      expect(isWelcomeMessage({ content: '你好，我是业务助手。' })).toBe(false)
    })

    it('returns true for ai role with welcome content', () => {
      expect(isWelcomeMessage({ role: 'ai', content: '你好，我是业务助手。请说出需求。' })).toBe(
        true,
      )
    })

    it('returns true for ai role with 您好 prefix', () => {
      expect(isWelcomeMessage({ role: 'ai', content: '您好！我是您的智能助手' })).toBe(true)
    })

    it('returns false for ai role with non-welcome content', () => {
      expect(isWelcomeMessage({ role: 'ai', content: '普通回复' })).toBe(false)
    })

    it('returns false for empty content', () => {
      expect(isWelcomeMessage({ role: 'ai', content: '' })).toBe(false)
    })

    it('handles HTML content by stripping tags first', () => {
      expect(
        isWelcomeMessage({ role: 'ai', content: '<p>你好，我是业务助手。</p>' }),
      ).toBe(true)
    })
  })

  // -----------------------------------------------------------------------
  // toHistoryTimestamp
  // -----------------------------------------------------------------------
  describe('toHistoryTimestamp', () => {
    it('returns 0 for null', () => {
      expect(toHistoryTimestamp(null)).toBe(0)
    })

    it('returns 0 for undefined', () => {
      expect(toHistoryTimestamp(undefined)).toBe(0)
    })

    it('returns 0 for empty string', () => {
      expect(toHistoryTimestamp('')).toBe(0)
    })

    it('returns 0 for invalid date string', () => {
      expect(toHistoryTimestamp('not-a-date')).toBe(0)
    })

    it('returns timestamp for valid ISO date', () => {
      expect(toHistoryTimestamp('2026-01-01T00:00:00Z')).toBe(Date.parse('2026-01-01T00:00:00Z'))
    })

    it('returns timestamp for valid date string', () => {
      const ts = toHistoryTimestamp('2026-06-15')
      expect(ts).toBe(Date.parse('2026-06-15'))
      expect(Number.isFinite(ts)).toBe(true)
    })

    it('trims whitespace before parsing', () => {
      expect(toHistoryTimestamp('  2026-01-01  ')).toBe(Date.parse('2026-01-01'))
    })
  })

  // -----------------------------------------------------------------------
  // readPersistedTaskPanelState
  // -----------------------------------------------------------------------
  describe('readPersistedTaskPanelState', () => {
    it('returns null when sessionKey is empty', () => {
      expect(readPersistedTaskPanelState('')).toBeNull()
    })

    it('returns null when sessionKey is whitespace', () => {
      expect(readPersistedTaskPanelState('   ')).toBeNull()
    })

    it('returns null when no stored value', () => {
      expect(readPersistedTaskPanelState('s1')).toBeNull()
    })

    it('returns null when stored value is not valid JSON', () => {
      sessionStorage.setItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 's1', '{not-json')
      expect(readPersistedTaskPanelState('s1')).toBeNull()
    })

    it('returns null when parsed value is not an object (string)', () => {
      sessionStorage.setItem(
        CHAT_TASK_PANEL_STORAGE_PREFIX + 's1',
        JSON.stringify('hello'),
      )
      expect(readPersistedTaskPanelState('s1')).toBeNull()
    })

    it('returns normalized state when parsed value is an array (arrays are objects)', () => {
      // typeof [] === 'object', so arrays pass the object check; fields default
      sessionStorage.setItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 's1', JSON.stringify([1, 2]))
      const result = readPersistedTaskPanelState('s1')
      expect(result).not.toBeNull()
      expect(result!.taskList).toEqual([])
      expect(result!.activeTaskId).toBe('')
      expect(result!.taskFilter).toBe('all')
    })

    it('returns normalized state with defaults when fields missing', () => {
      sessionStorage.setItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 's1', JSON.stringify({}))
      const result = readPersistedTaskPanelState('s1')
      expect(result).not.toBeNull()
      expect(result!.taskList).toEqual([])
      expect(result!.activeTaskId).toBe('')
      expect(result!.expandedTaskIds).toEqual([])
      expect(result!.taskFilter).toBe('all')
      expect(result!.currentTask).toBeNull()
      expect(result!.savedAt).toBe(0)
    })

    it('returns full state when all fields present', () => {
      const state: PersistedTaskPanelState = {
        taskList: [{ id: 't1', type: 'shipment', title: 'T1', source: 'shipment', status: 'success', startedAt: 1, updatedAt: 2 }],
        activeTaskId: 't1',
        expandedTaskIds: ['t1', 't2'],
        taskFilter: 'running',
        currentTask: { type: 'shipment_generate' },
        savedAt: 12345,
      }
      sessionStorage.setItem(
        CHAT_TASK_PANEL_STORAGE_PREFIX + 's1',
        JSON.stringify(state),
      )
      const result = readPersistedTaskPanelState('s1')
      expect(result).toEqual(state)
    })

    it('filters out empty/whitespace expandedTaskIds', () => {
      sessionStorage.setItem(
        CHAT_TASK_PANEL_STORAGE_PREFIX + 's1',
        JSON.stringify({
          expandedTaskIds: ['t1', '', '  ', 't2'],
        }),
      )
      const result = readPersistedTaskPanelState('s1')
      expect(result!.expandedTaskIds).toEqual(['t1', 't2'])
    })

    it('falls back to "all" when taskFilter is invalid', () => {
      sessionStorage.setItem(
        CHAT_TASK_PANEL_STORAGE_PREFIX + 's1',
        JSON.stringify({ taskFilter: 'invalid' }),
      )
      const result = readPersistedTaskPanelState('s1')
      expect(result!.taskFilter).toBe('all')
    })

    it('returns null currentTask when not an object', () => {
      sessionStorage.setItem(
        CHAT_TASK_PANEL_STORAGE_PREFIX + 's1',
        JSON.stringify({ currentTask: 'not-object' }),
      )
      const result = readPersistedTaskPanelState('s1')
      expect(result!.currentTask).toBeNull()
    })

    it('returns 0 savedAt when not finite', () => {
      sessionStorage.setItem(
        CHAT_TASK_PANEL_STORAGE_PREFIX + 's1',
        JSON.stringify({ savedAt: 'NaN' }),
      )
      const result = readPersistedTaskPanelState('s1')
      expect(result!.savedAt).toBe(0)
    })

    it('returns empty taskList when not an array', () => {
      sessionStorage.setItem(
        CHAT_TASK_PANEL_STORAGE_PREFIX + 's1',
        JSON.stringify({ taskList: 'not-array' }),
      )
      const result = readPersistedTaskPanelState('s1')
      expect(result!.taskList).toEqual([])
    })
  })

  // -----------------------------------------------------------------------
  // persistTaskPanelState
  // -----------------------------------------------------------------------
  describe('persistTaskPanelState', () => {
    it('does nothing when sessionKey is empty', () => {
      persistTaskPanelState('', {
        taskList: [],
        activeTaskId: '',
        expandedTaskIds: [],
        taskFilter: 'all',
        currentTask: null,
        savedAt: 1,
      })
      expect(sessionStorage.length).toBe(0)
    })

    it('stores state as JSON', () => {
      const state: PersistedTaskPanelState = {
        taskList: [],
        activeTaskId: 'a',
        expandedTaskIds: [],
        taskFilter: 'all',
        currentTask: null,
        savedAt: 99,
      }
      persistTaskPanelState('s1', state)
      expect(sessionStorage.getItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 's1')).toBe(
        JSON.stringify(state),
      )
    })

    it('swallows quota errors silently', () => {
      const orig = sessionStorage.setItem
      sessionStorage.setItem = vi.fn(() => {
        throw new Error('QuotaExceededError')
      })
      expect(() =>
        persistTaskPanelState('s1', {
          taskList: [],
          activeTaskId: '',
          expandedTaskIds: [],
          taskFilter: 'all',
          currentTask: null,
          savedAt: 1,
        }),
      ).not.toThrow()
      sessionStorage.setItem = orig
    })
  })

  // -----------------------------------------------------------------------
  // clearPersistedTaskPanelState
  // -----------------------------------------------------------------------
  describe('clearPersistedTaskPanelState', () => {
    it('does nothing when sessionKey is empty', () => {
      clearPersistedTaskPanelState('')
      expect(sessionStorage.length).toBe(0)
    })

    it('removes stored value when exists', () => {
      sessionStorage.setItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 's1', 'old')
      clearPersistedTaskPanelState('s1')
      expect(sessionStorage.getItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 's1')).toBeNull()
    })

    it('does not throw when key does not exist', () => {
      expect(() => clearPersistedTaskPanelState('nonexistent')).not.toThrow()
    })

    it('swallows removeItem errors silently', () => {
      const orig = sessionStorage.removeItem
      sessionStorage.removeItem = vi.fn(() => {
        throw new Error('boom')
      })
      expect(() => clearPersistedTaskPanelState('s1')).not.toThrow()
      sessionStorage.removeItem = orig
    })
  })

  // -----------------------------------------------------------------------
  // useChatHistoryPersistence
  // -----------------------------------------------------------------------
  describe('useChatHistoryPersistence', () => {
    function makeDeps(activeModId = '') {
      const sessionId = ref('active-sid')
      const getActiveModId = () => activeModId
      return { sessionId, getActiveModId }
    }

    describe('normalizeHistorySessions', () => {
      it('returns empty array for non-array input', () => {
        const { normalizeHistorySessions } = useChatHistoryPersistence(makeDeps())
        expect(normalizeHistorySessions('nope' as unknown as never[])).toEqual([])
      })

      it('returns empty array for null input', () => {
        const { normalizeHistorySessions } = useChatHistoryPersistence(makeDeps())
        expect(normalizeHistorySessions(null as unknown as never[])).toEqual([])
      })

      it('filters out sessions without session_id or id', () => {
        const { normalizeHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = normalizeHistorySessions([
          { session_id: 's1', title: 'T1' },
          { id: 's2', title: 'T2' },
          { title: 'no id' },
          {},
        ])
        expect(result).toHaveLength(2)
        expect(result[0].session_id).toBe('s1')
        expect(result[1].session_id).toBe('s2')
      })

      it('uses summary as title when title missing', () => {
        const { normalizeHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = normalizeHistorySessions([{ session_id: 's1', summary: 'Summary' }])
        expect(result[0].title).toBe('Summary')
      })

      it('falls back to "会话 N" when title and summary missing', () => {
        const { normalizeHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = normalizeHistorySessions([{ session_id: 's1' }, { session_id: 's2' }])
        expect(result[0].title).toBe('会话 1')
        expect(result[1].title).toBe('会话 2')
      })

      it('uses message_count when present', () => {
        const { normalizeHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = normalizeHistorySessions([
          { session_id: 's1', message_count: 5 },
        ])
        expect(result[0].message_count).toBe(5)
      })

      it('falls back to messages.length when message_count missing', () => {
        const { normalizeHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = normalizeHistorySessions([
          { session_id: 's1', messages: [1, 2, 3] },
        ])
        expect(result[0].message_count).toBe(3)
      })

      it('falls back to 0 when message_count is not finite', () => {
        const { normalizeHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = normalizeHistorySessions([
          { session_id: 's1', message_count: 'NaN' },
        ])
        expect(result[0].message_count).toBe(0)
      })

      it('uses last_message_at when present', () => {
        const { normalizeHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = normalizeHistorySessions([
          { session_id: 's1', last_message_at: '2026-01-01' },
        ])
        expect(result[0].last_message_at).toBe('2026-01-01')
      })

      it('falls back to updated_at then created_at', () => {
        const { normalizeHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = normalizeHistorySessions([
          { session_id: 's1', updated_at: '2026-01-02', created_at: '2026-01-01' },
        ])
        expect(result[0].last_message_at).toBe('2026-01-02')
      })

      it('sets is_local_only to false', () => {
        const { normalizeHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = normalizeHistorySessions([{ session_id: 's1' }])
        expect(result[0].is_local_only).toBe(false)
      })

      it('preserves extra fields via spread', () => {
        const { normalizeHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = normalizeHistorySessions([
          { session_id: 's1', custom_field: 'hello' },
        ])
        expect((result[0] as Record<string, unknown>).custom_field).toBe('hello')
      })
    })

    describe('readLocalMessagesBySession', () => {
      it('returns empty array when sessionId is empty', () => {
        const { readLocalMessagesBySession } = useChatHistoryPersistence(makeDeps())
        expect(readLocalMessagesBySession('')).toEqual([])
      })

      it('returns empty array when no stored value', () => {
        const { readLocalMessagesBySession } = useChatHistoryPersistence(makeDeps())
        expect(readLocalMessagesBySession('s1')).toEqual([])
      })

      it('returns empty array when stored value is not valid JSON', () => {
        localStorage.setItem('xcagi_chat_messages_s1', '{not-json')
        const { readLocalMessagesBySession } = useChatHistoryPersistence(makeDeps())
        expect(readLocalMessagesBySession('s1')).toEqual([])
      })

      it('returns empty array when parsed value is not an array', () => {
        localStorage.setItem('xcagi_chat_messages_s1', JSON.stringify({ not: 'array' }))
        const { readLocalMessagesBySession } = useChatHistoryPersistence(makeDeps())
        expect(readLocalMessagesBySession('s1')).toEqual([])
      })

      it('returns empty array when parsed array is empty', () => {
        localStorage.setItem('xcagi_chat_messages_s1', '[]')
        const { readLocalMessagesBySession } = useChatHistoryPersistence(makeDeps())
        expect(readLocalMessagesBySession('s1')).toEqual([])
      })

      it('normalizes role to ai when not user/task', () => {
        localStorage.setItem(
          'xcagi_chat_messages_s1',
          JSON.stringify([
            { role: 'user', content: 'hi' },
            { role: 'task', content: 'task' },
            { role: 'assistant', content: 'ai reply' },
            { content: 'no role' },
          ]),
        )
        const { readLocalMessagesBySession } = useChatHistoryPersistence(makeDeps())
        const result = readLocalMessagesBySession('s1')
        expect(result.map((m) => m.role)).toEqual(['user', 'task', 'ai', 'ai'])
      })

      it('fills time when missing', () => {
        localStorage.setItem(
          'xcagi_chat_messages_s1',
          JSON.stringify([{ role: 'ai', content: 'hello' }]),
        )
        const { readLocalMessagesBySession } = useChatHistoryPersistence(makeDeps())
        const result = readLocalMessagesBySession('s1')
        expect(result[0].time).toBeTruthy()
      })

      it('preserves time when present', () => {
        localStorage.setItem(
          'xcagi_chat_messages_s1',
          JSON.stringify([{ role: 'ai', content: 'hello', time: '12:34' }]),
        )
        const { readLocalMessagesBySession } = useChatHistoryPersistence(makeDeps())
        const result = readLocalMessagesBySession('s1')
        expect(result[0].time).toBe('12:34')
      })

      it('filters out messages with empty plain content', () => {
        localStorage.setItem(
          'xcagi_chat_messages_s1',
          JSON.stringify([
            { role: 'ai', content: 'hello' },
            { role: 'ai', content: '' },
            { role: 'ai', content: '<p></p>' },
            { role: 'ai', content: '   ' },
          ]),
        )
        const { readLocalMessagesBySession } = useChatHistoryPersistence(makeDeps())
        const result = readLocalMessagesBySession('s1')
        expect(result).toHaveLength(1)
        expect(result[0].content).toBe('hello')
      })

      it('uses content string when content is non-string', () => {
        localStorage.setItem(
          'xcagi_chat_messages_s1',
          JSON.stringify([{ role: 'ai', content: 42 }]),
        )
        const { readLocalMessagesBySession } = useChatHistoryPersistence(makeDeps())
        const result = readLocalMessagesBySession('s1')
        expect(result[0].content).toBe('42')
      })
    })

    describe('readLocalSessionMeta', () => {
      it('returns null when sessionId is empty', () => {
        const { readLocalSessionMeta } = useChatHistoryPersistence(makeDeps())
        expect(readLocalSessionMeta('')).toBeNull()
      })

      it('returns null when no stored value', () => {
        const { readLocalSessionMeta } = useChatHistoryPersistence(makeDeps())
        expect(readLocalSessionMeta('s1')).toBeNull()
      })

      it('returns null when stored value is not valid JSON', () => {
        localStorage.setItem('xcagi_chat_session_meta_s1', '{not-json')
        const { readLocalSessionMeta } = useChatHistoryPersistence(makeDeps())
        expect(readLocalSessionMeta('s1')).toBeNull()
      })

      it('returns null when parsed value is not an object (string)', () => {
        localStorage.setItem('xcagi_chat_session_meta_s1', JSON.stringify('hello'))
        const { readLocalSessionMeta } = useChatHistoryPersistence(makeDeps())
        expect(readLocalSessionMeta('s1')).toBeNull()
      })

      it('returns parsed object when valid', () => {
        localStorage.setItem(
          'xcagi_chat_session_meta_s1',
          JSON.stringify({ title: 'T1', updated_at: '2026-01-01' }),
        )
        const { readLocalSessionMeta } = useChatHistoryPersistence(makeDeps())
        expect(readLocalSessionMeta('s1')).toEqual({
          title: 'T1',
          updated_at: '2026-01-01',
        })
      })
    })

    describe('deriveLocalSessionTitle', () => {
      it('returns fallback when provided', () => {
        const { deriveLocalSessionTitle } = useChatHistoryPersistence(makeDeps())
        expect(deriveLocalSessionTitle([], 'My Title')).toBe('My Title')
      })

      it('returns fallback when messages empty', () => {
        const { deriveLocalSessionTitle } = useChatHistoryPersistence(makeDeps())
        expect(deriveLocalSessionTitle([], '')).toBe('新会话')
      })

      it('returns "新会话" when all messages are welcome messages', () => {
        const { deriveLocalSessionTitle } = useChatHistoryPersistence(makeDeps())
        expect(
          deriveLocalSessionTitle([{ role: 'ai', content: '你好，我是业务助手。' }], ''),
        ).toBe('新会话')
      })

      it('returns "新会话" when all messages have empty content', () => {
        const { deriveLocalSessionTitle } = useChatHistoryPersistence(makeDeps())
        expect(deriveLocalSessionTitle([{ role: 'user', content: '' }], '')).toBe('新会话')
      })

      it('prefers first user message as title', () => {
        const { deriveLocalSessionTitle } = useChatHistoryPersistence(makeDeps())
        const result = deriveLocalSessionTitle(
          [
            { role: 'ai', content: '你好，我是业务助手。' },
            { role: 'user', content: '帮我查价' },
            { role: 'ai', content: '好的' },
          ],
          '',
        )
        expect(result).toBe('帮我查价')
      })

      it('falls back to first meaningful message when no user message', () => {
        const { deriveLocalSessionTitle } = useChatHistoryPersistence(makeDeps())
        const result = deriveLocalSessionTitle(
          [{ role: 'ai', content: 'AI 回复内容' }],
          '',
        )
        expect(result).toBe('AI 回复内容')
      })

      it('truncates title longer than 32 chars', () => {
        const long = 'x'.repeat(50)
        const { deriveLocalSessionTitle } = useChatHistoryPersistence(makeDeps())
        const result = deriveLocalSessionTitle([{ role: 'user', content: long }], '')
        expect(result).toBe(`${'x'.repeat(32)}...`)
      })

      it('does not truncate title exactly 32 chars', () => {
        const exact = 'x'.repeat(32)
        const { deriveLocalSessionTitle } = useChatHistoryPersistence(makeDeps())
        const result = deriveLocalSessionTitle([{ role: 'user', content: exact }], '')
        expect(result).toBe(exact)
      })

      it('collapses whitespace in title', () => {
        const { deriveLocalSessionTitle } = useChatHistoryPersistence(makeDeps())
        const result = deriveLocalSessionTitle(
          [{ role: 'user', content: '  hello   world  ' }],
          '',
        )
        expect(result).toBe('hello world')
      })

      it('strips HTML tags from content before deriving title', () => {
        const { deriveLocalSessionTitle } = useChatHistoryPersistence(makeDeps())
        const result = deriveLocalSessionTitle(
          [{ role: 'user', content: '<p>hello</p>' }],
          '',
        )
        expect(result).toBe('hello')
      })
    })

    describe('buildLocalHistorySession', () => {
      it('returns null when sessionId is empty', () => {
        const { buildLocalHistorySession } = useChatHistoryPersistence(makeDeps())
        expect(buildLocalHistorySession('')).toBeNull()
      })

      it('returns null when no meaningful messages', () => {
        localStorage.setItem(
          'xcagi_chat_messages_s1',
          JSON.stringify([{ role: 'ai', content: '你好，我是业务助手。' }]),
        )
        const { buildLocalHistorySession } = useChatHistoryPersistence(makeDeps())
        expect(buildLocalHistorySession('s1')).toBeNull()
      })

      it('returns null when no messages at all', () => {
        const { buildLocalHistorySession } = useChatHistoryPersistence(makeDeps())
        expect(buildLocalHistorySession('s1')).toBeNull()
      })

      it('returns session with derived title from messages', () => {
        localStorage.setItem(
          'xcagi_chat_messages_s1',
          JSON.stringify([
            { role: 'ai', content: '你好，我是业务助手。' },
            { role: 'user', content: '帮我查价' },
          ]),
        )
        const { buildLocalHistorySession } = useChatHistoryPersistence(makeDeps())
        const result = buildLocalHistorySession('s1')
        expect(result).not.toBeNull()
        expect(result!.session_id).toBe('s1')
        expect(result!.title).toBe('帮我查价')
        expect(result!.is_local_only).toBe(true)
      })

      it('uses meta.title when present', () => {
        localStorage.setItem(
          'xcagi_chat_messages_s1',
          JSON.stringify([{ role: 'user', content: '帮我查价' }]),
        )
        localStorage.setItem(
          'xcagi_chat_session_meta_s1',
          JSON.stringify({ title: 'Meta Title', updated_at: '2026-01-01' }),
        )
        const { buildLocalHistorySession } = useChatHistoryPersistence(makeDeps())
        const result = buildLocalHistorySession('s1')
        expect(result!.title).toBe('Meta Title')
        expect(result!.last_message_at).toBe('2026-01-01')
      })

      it('uses meaningful.length when meta.message_count missing', () => {
        localStorage.setItem(
          'xcagi_chat_messages_s1',
          JSON.stringify([
            { role: 'user', content: 'msg1' },
            { role: 'user', content: 'msg2' },
          ]),
        )
        const { buildLocalHistorySession } = useChatHistoryPersistence(makeDeps())
        const result = buildLocalHistorySession('s1')
        expect(result!.message_count).toBe(2)
      })

      it('falls back to current ISO time when meta.updated_at missing', () => {
        localStorage.setItem(
          'xcagi_chat_messages_s1',
          JSON.stringify([{ role: 'user', content: 'msg1' }]),
        )
        const { buildLocalHistorySession } = useChatHistoryPersistence(makeDeps())
        const result = buildLocalHistorySession('s1')
        expect(result!.last_message_at).toBeTruthy()
        // ISO string should contain 'T'
        expect(String(result!.last_message_at)).toContain('T')
      })
    })

    describe('listLocalHistorySessions', () => {
      it('returns empty array when no localStorage entries', () => {
        const { listLocalHistorySessions } = useChatHistoryPersistence(makeDeps())
        expect(listLocalHistorySessions()).toEqual([])
      })

      it('returns sessions sorted by last_message_at desc', () => {
        localStorage.setItem(
          'xcagi_chat_messages_old',
          JSON.stringify([{ role: 'user', content: 'old' }]),
        )
        localStorage.setItem(
          'xcagi_chat_messages_new',
          JSON.stringify([{ role: 'user', content: 'new' }]),
        )
        localStorage.setItem(
          'xcagi_chat_session_meta_old',
          JSON.stringify({ updated_at: '2026-01-01' }),
        )
        localStorage.setItem(
          'xcagi_chat_session_meta_new',
          JSON.stringify({ updated_at: '2026-06-01' }),
        )
        const { listLocalHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = listLocalHistorySessions()
        expect(result).toHaveLength(2)
        // newer first
        expect(String(result[0].session_id)).toBe('new')
        expect(String(result[1].session_id)).toBe('old')
      })

      it('respects limit parameter', () => {
        for (let i = 0; i < 5; i++) {
          localStorage.setItem(
            `xcagi_chat_messages_s${i}`,
            JSON.stringify([{ role: 'user', content: `msg${i}` }]),
          )
          localStorage.setItem(
            `xcagi_chat_session_meta_s${i}`,
            JSON.stringify({ updated_at: `2026-01-0${i + 1}` }),
          )
        }
        const { listLocalHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = listLocalHistorySessions(3)
        expect(result).toHaveLength(3)
      })

      it('uses minimum limit of 1', () => {
        localStorage.setItem(
          'xcagi_chat_messages_s1',
          JSON.stringify([{ role: 'user', content: 'msg1' }]),
        )
        const { listLocalHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = listLocalHistorySessions(0)
        expect(result).toHaveLength(1)
      })

      it('dedupes sessions found via both messages and meta keys', () => {
        localStorage.setItem(
          'xcagi_chat_messages_s1',
          JSON.stringify([{ role: 'user', content: 'msg1' }]),
        )
        localStorage.setItem(
          'xcagi_chat_session_meta_s1',
          JSON.stringify({ updated_at: '2026-01-01' }),
        )
        const { listLocalHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = listLocalHistorySessions()
        expect(result).toHaveLength(1)
      })

      it('skips localStorage entries that do not match prefix pattern', () => {
        localStorage.setItem('unrelated_key', 'value')
        localStorage.setItem(
          'xcagi_chat_messages_s1',
          JSON.stringify([{ role: 'user', content: 'msg1' }]),
        )
        const { listLocalHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = listLocalHistorySessions()
        expect(result).toHaveLength(1)
      })
    })

    describe('mergeHistorySessions', () => {
      it('returns empty array when no server and no local sessions', () => {
        const { mergeHistorySessions } = useChatHistoryPersistence(makeDeps())
        expect(mergeHistorySessions([])).toEqual([])
      })

      it('returns local sessions when server provides none', () => {
        localStorage.setItem(
          'xcagi_chat_messages_s1',
          JSON.stringify([{ role: 'user', content: 'msg1' }]),
        )
        const { mergeHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = mergeHistorySessions([])
        expect(result).toHaveLength(1)
        expect(result[0].is_local_only).toBe(true)
      })

      it('merges server sessions with local sessions', () => {
        localStorage.setItem(
          'xcagi_chat_messages_local1',
          JSON.stringify([{ role: 'user', content: 'local msg' }]),
        )
        const { mergeHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = mergeHistorySessions([
          { session_id: 'server1', title: 'Server 1' },
          { session_id: 'local1', title: 'Server override' },
        ])
        // 1 local + 1 server-only = 2
        expect(result).toHaveLength(2)
        const localEntry = result.find((r) => String(r.session_id) === 'local1')
        expect(localEntry).toBeDefined()
        expect(localEntry!.is_local_only).toBe(false)
        expect(localEntry!.title).toBe('Server override')
      })

      it('includes active session fallback when not in server/local', () => {
        const sessionId = ref('active-only')
        const { mergeHistorySessions } = useChatHistoryPersistence({
          sessionId,
          getActiveModId: () => '',
        })
        // No local storage for active-only, no server entry
        const result = mergeHistorySessions([])
        // Active session has no local messages, so buildLocalHistorySession returns null
        expect(result).toEqual([])
      })

      it('includes active session when it has local messages', () => {
        const sessionId = ref('active-with-msgs')
        localStorage.setItem(
          'xcagi_chat_messages_active-with-msgs',
          JSON.stringify([{ role: 'user', content: 'active msg' }]),
        )
        const { mergeHistorySessions } = useChatHistoryPersistence({
          sessionId,
          getActiveModId: () => '',
        })
        const result = mergeHistorySessions([])
        expect(result).toHaveLength(1)
        expect(String(result[0].session_id)).toBe('active-with-msgs')
      })

      it('sorts merged sessions by last_message_at desc', () => {
        localStorage.setItem(
          'xcagi_chat_messages_old',
          JSON.stringify([{ role: 'user', content: 'old' }]),
        )
        localStorage.setItem(
          'xcagi_chat_session_meta_old',
          JSON.stringify({ updated_at: '2026-01-01' }),
        )
        const { mergeHistorySessions } = useChatHistoryPersistence(makeDeps())
        const result = mergeHistorySessions([
          { session_id: 'new', title: 'New', last_message_at: '2026-06-01' },
        ])
        expect(String(result[0].session_id)).toBe('new')
        expect(String(result[1].session_id)).toBe('old')
      })
    })

    describe('clearLocalHistoryCache', () => {
      it('does nothing when no matching keys', () => {
        localStorage.setItem('unrelated', 'value')
        const { clearLocalHistoryCache } = useChatHistoryPersistence(makeDeps())
        clearLocalHistoryCache()
        expect(localStorage.getItem('unrelated')).toBe('value')
      })

      it('removes only chat messages and meta keys', () => {
        localStorage.setItem('xcagi_chat_messages_s1', 'a')
        localStorage.setItem('xcagi_chat_session_meta_s1', 'b')
        localStorage.setItem('unrelated', 'c')
        const { clearLocalHistoryCache } = useChatHistoryPersistence(makeDeps())
        clearLocalHistoryCache()
        expect(localStorage.getItem('xcagi_chat_messages_s1')).toBeNull()
        expect(localStorage.getItem('xcagi_chat_session_meta_s1')).toBeNull()
        expect(localStorage.getItem('unrelated')).toBe('c')
      })

      it('does not throw when localStorage is empty', () => {
        const { clearLocalHistoryCache } = useChatHistoryPersistence(makeDeps())
        expect(() => clearLocalHistoryCache()).not.toThrow()
      })
    })
  })

  // -----------------------------------------------------------------------
  // useChatTaskPanelPersistence
  // -----------------------------------------------------------------------
  describe('useChatTaskPanelPersistence', () => {
    function makeTaskItem(id: string, status: TaskItem['status'] = 'success'): TaskItem {
      return {
        id,
        type: 'shipment',
        title: `Task ${id}`,
        source: 'shipment',
        status,
        startedAt: 1,
        updatedAt: 2,
      }
    }

    function makeDeps(overrides: Partial<{
      sessionId: string
      taskList: TaskItem[]
      activeTaskId: string
      expandedTaskIds: string[]
      taskFilter: 'all' | 'running' | 'success' | 'failed'
      currentTask: Record<string, unknown> | null
    }> = {}) {
      const sessionId = ref(overrides.sessionId ?? 's1')
      const taskList = ref<TaskItem[]>(overrides.taskList ?? [])
      const activeTaskId = ref(overrides.activeTaskId ?? '')
      const expandedTaskIds = ref<string[]>(overrides.expandedTaskIds ?? [])
      const taskFilter = ref<'all' | 'running' | 'success' | 'failed'>(
        overrides.taskFilter ?? 'all',
      )
      const currentTask = ref<Record<string, unknown> | null>(overrides.currentTask ?? null)
      const sortTaskList = vi.fn()
      return {
        sessionId,
        taskList,
        activeTaskId,
        expandedTaskIds,
        taskFilter,
        currentTask: currentTask as never,
        sortTaskList,
      }
    }

    describe('persistTaskPanelStateForSession', () => {
      it('uses "default" when targetSessionId is empty and sessionId is empty', () => {
        const deps = makeDeps({ sessionId: '' })
        const { persistTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        persistTaskPanelStateForSession()
        expect(sessionStorage.getItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 'default')).not.toBeNull()
      })

      it('uses provided targetSessionId when given', () => {
        const deps = makeDeps({ sessionId: 'other' })
        const { persistTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        persistTaskPanelStateForSession('target-sid')
        expect(sessionStorage.getItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 'target-sid')).not.toBeNull()
        expect(sessionStorage.getItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 'other')).toBeNull()
      })

      it('uses sessionId.value when targetSessionId is empty', () => {
        const deps = makeDeps({ sessionId: 'from-ref' })
        const { persistTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        persistTaskPanelStateForSession()
        expect(sessionStorage.getItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 'from-ref')).not.toBeNull()
      })

      it('truncates taskList to TASK_HISTORY_LIMIT', () => {
        const longList = Array.from({ length: TASK_HISTORY_LIMIT + 10 }, (_, i) =>
          makeTaskItem(`t${i}`),
        )
        const deps = makeDeps({ taskList: longList })
        const { persistTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        persistTaskPanelStateForSession('s1')
        const stored = JSON.parse(
          sessionStorage.getItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 's1')!,
        )
        expect(stored.taskList).toHaveLength(TASK_HISTORY_LIMIT)
      })

      it('truncates expandedTaskIds to 80', () => {
        const longExpanded = Array.from({ length: 100 }, (_, i) => `t${i}`)
        const deps = makeDeps({ expandedTaskIds: longExpanded })
        const { persistTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        persistTaskPanelStateForSession('s1')
        const stored = JSON.parse(
          sessionStorage.getItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 's1')!,
        )
        expect(stored.expandedTaskIds).toHaveLength(80)
      })

      it('clones currentTask when persisting', () => {
        const task = { type: 'shipment_generate', custom: 'value' }
        const deps = makeDeps({ currentTask: task })
        const { persistTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        persistTaskPanelStateForSession('s1')
        const stored = JSON.parse(
          sessionStorage.getItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 's1')!,
        )
        expect(stored.currentTask).toEqual(task)
        // Mutating original should not affect stored
        ;(task as Record<string, unknown>).custom = 'changed'
        expect(stored.currentTask.custom).toBe('value')
      })

      it('stores null currentTask when currentTask is null', () => {
        const deps = makeDeps({ currentTask: null })
        const { persistTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        persistTaskPanelStateForSession('s1')
        const stored = JSON.parse(
          sessionStorage.getItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 's1')!,
        )
        expect(stored.currentTask).toBeNull()
      })

      it('trims activeTaskId when persisting', () => {
        const deps = makeDeps({ activeTaskId: '  t1  ' })
        const { persistTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        persistTaskPanelStateForSession('s1')
        const stored = JSON.parse(
          sessionStorage.getItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 's1')!,
        )
        expect(stored.activeTaskId).toBe('t1')
      })

      it('stores savedAt as number', () => {
        const deps = makeDeps()
        const { persistTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        const before = Date.now()
        persistTaskPanelStateForSession('s1')
        const stored = JSON.parse(
          sessionStorage.getItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 's1')!,
        )
        expect(stored.savedAt).toBeGreaterThanOrEqual(before)
        expect(typeof stored.savedAt).toBe('number')
      })
    })

    describe('applyPersistedTaskPanelStateForSession', () => {
      it('resets to defaults when no persisted state (sortTaskList not called on early return)', () => {
        const deps = makeDeps({
          taskList: [makeTaskItem('t1')],
          activeTaskId: 't1',
          expandedTaskIds: ['t1'],
          taskFilter: 'success',
          currentTask: { type: 'x' },
        })
        const { applyPersistedTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        applyPersistedTaskPanelStateForSession('no-such-sid')
        expect(deps.taskList.value).toEqual([])
        expect(deps.activeTaskId.value).toBe('')
        expect(deps.expandedTaskIds.value).toEqual([])
        expect(deps.taskFilter.value).toBe('all')
        expect(deps.currentTask.value).toBeNull()
        // Source early-returns before sortTaskList when no persisted state
        expect(deps.sortTaskList).not.toHaveBeenCalled()
      })

      it('applies persisted state when present', () => {
        const state: PersistedTaskPanelState = {
          taskList: [makeTaskItem('t1'), makeTaskItem('t2')],
          activeTaskId: 't2',
          expandedTaskIds: ['t1', 't2'],
          taskFilter: 'running',
          currentTask: { type: 'shipment_generate' },
          savedAt: 1,
        }
        sessionStorage.setItem(
          CHAT_TASK_PANEL_STORAGE_PREFIX + 's1',
          JSON.stringify(state),
        )
        const deps = makeDeps()
        const { applyPersistedTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        applyPersistedTaskPanelStateForSession('s1')
        expect(deps.taskList.value).toHaveLength(2)
        expect(deps.activeTaskId.value).toBe('t2')
        expect(deps.expandedTaskIds.value).toEqual(['t1', 't2'])
        expect(deps.taskFilter.value).toBe('running')
        expect(deps.currentTask.value).toEqual({ type: 'shipment_generate' })
        expect(deps.sortTaskList).toHaveBeenCalled()
      })

      it('truncates taskList to TASK_HISTORY_LIMIT when applying', () => {
        const longList = Array.from({ length: TASK_HISTORY_LIMIT + 5 }, (_, i) =>
          makeTaskItem(`t${i}`),
        )
        const state: PersistedTaskPanelState = {
          taskList: longList,
          activeTaskId: '',
          expandedTaskIds: [],
          taskFilter: 'all',
          currentTask: null,
          savedAt: 1,
        }
        sessionStorage.setItem(
          CHAT_TASK_PANEL_STORAGE_PREFIX + 's1',
          JSON.stringify(state),
        )
        const deps = makeDeps()
        const { applyPersistedTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        applyPersistedTaskPanelStateForSession('s1')
        expect(deps.taskList.value).toHaveLength(TASK_HISTORY_LIMIT)
      })

      it('filters expandedTaskIds to those present in taskList', () => {
        const state: PersistedTaskPanelState = {
          taskList: [makeTaskItem('t1')],
          activeTaskId: '',
          expandedTaskIds: ['t1', 't2-orphan', 't3-orphan'],
          taskFilter: 'all',
          currentTask: null,
          savedAt: 1,
        }
        sessionStorage.setItem(
          CHAT_TASK_PANEL_STORAGE_PREFIX + 's1',
          JSON.stringify(state),
        )
        const deps = makeDeps()
        const { applyPersistedTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        applyPersistedTaskPanelStateForSession('s1')
        expect(deps.expandedTaskIds.value).toEqual(['t1'])
      })

      it('filters expandedTaskIds to those in taskList (capped at TASK_HISTORY_LIMIT=20)', () => {
        // taskList is truncated to TASK_HISTORY_LIMIT (20), so idSet has at most 20 IDs.
        // expandedTaskIds filter then slice(0, 80) — but only 20 can match.
        const taskList = Array.from({ length: 100 }, (_, i) => makeTaskItem(`t${i}`))
        const expanded = Array.from({ length: 100 }, (_, i) => `t${i}`)
        const state: PersistedTaskPanelState = {
          taskList,
          activeTaskId: '',
          expandedTaskIds: expanded,
          taskFilter: 'all',
          currentTask: null,
          savedAt: 1,
        }
        sessionStorage.setItem(
          CHAT_TASK_PANEL_STORAGE_PREFIX + 's1',
          JSON.stringify(state),
        )
        const deps = makeDeps()
        const { applyPersistedTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        applyPersistedTaskPanelStateForSession('s1')
        // taskList truncated to 20, so only first 20 expanded IDs match
        expect(deps.taskList.value).toHaveLength(TASK_HISTORY_LIMIT)
        expect(deps.expandedTaskIds.value).toHaveLength(TASK_HISTORY_LIMIT)
        expect(deps.expandedTaskIds.value).toEqual(
          Array.from({ length: TASK_HISTORY_LIMIT }, (_, i) => `t${i}`),
        )
      })

      it('resets activeTaskId to first task when persisted activeTaskId not in taskList', () => {
        const state: PersistedTaskPanelState = {
          taskList: [makeTaskItem('t1'), makeTaskItem('t2')],
          activeTaskId: 'orphan',
          expandedTaskIds: [],
          taskFilter: 'all',
          currentTask: null,
          savedAt: 1,
        }
        sessionStorage.setItem(
          CHAT_TASK_PANEL_STORAGE_PREFIX + 's1',
          JSON.stringify(state),
        )
        const deps = makeDeps()
        const { applyPersistedTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        applyPersistedTaskPanelStateForSession('s1')
        expect(deps.activeTaskId.value).toBe('t1')
      })

      it('resets activeTaskId to empty when taskList is empty', () => {
        const state: PersistedTaskPanelState = {
          taskList: [],
          activeTaskId: 'orphan',
          expandedTaskIds: [],
          taskFilter: 'all',
          currentTask: null,
          savedAt: 1,
        }
        sessionStorage.setItem(
          CHAT_TASK_PANEL_STORAGE_PREFIX + 's1',
          JSON.stringify(state),
        )
        const deps = makeDeps()
        const { applyPersistedTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        applyPersistedTaskPanelStateForSession('s1')
        expect(deps.activeTaskId.value).toBe('')
      })

      it('uses "default" when targetSessionId is empty and sessionId is empty', () => {
        const state: PersistedTaskPanelState = {
          taskList: [makeTaskItem('t1')],
          activeTaskId: 't1',
          expandedTaskIds: [],
          taskFilter: 'all',
          currentTask: null,
          savedAt: 1,
        }
        sessionStorage.setItem(
          CHAT_TASK_PANEL_STORAGE_PREFIX + 'default',
          JSON.stringify(state),
        )
        const deps = makeDeps({ sessionId: '' })
        const { applyPersistedTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        applyPersistedTaskPanelStateForSession()
        expect(deps.taskList.value).toHaveLength(1)
      })

      it('uses sessionId.value when targetSessionId is empty', () => {
        const state: PersistedTaskPanelState = {
          taskList: [makeTaskItem('t1')],
          activeTaskId: 't1',
          expandedTaskIds: [],
          taskFilter: 'all',
          currentTask: null,
          savedAt: 1,
        }
        sessionStorage.setItem(
          CHAT_TASK_PANEL_STORAGE_PREFIX + 'from-ref',
          JSON.stringify(state),
        )
        const deps = makeDeps({ sessionId: 'from-ref' })
        const { applyPersistedTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        applyPersistedTaskPanelStateForSession()
        expect(deps.taskList.value).toHaveLength(1)
      })

      it('handles taskList not being an array in persisted state', () => {
        // Manually craft malformed persisted state
        sessionStorage.setItem(
          CHAT_TASK_PANEL_STORAGE_PREFIX + 's1',
          JSON.stringify({
            taskList: 'not-array',
            activeTaskId: '',
            expandedTaskIds: [],
            taskFilter: 'all',
            currentTask: null,
            savedAt: 1,
          }),
        )
        const deps = makeDeps()
        const { applyPersistedTaskPanelStateForSession } = useChatTaskPanelPersistence(deps)
        applyPersistedTaskPanelStateForSession('s1')
        // readPersistedTaskPanelState normalizes taskList to []
        expect(deps.taskList.value).toEqual([])
      })
    })
  })
})

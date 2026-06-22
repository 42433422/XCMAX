/**
 * officeEmployeeReadApi.ts 覆盖率补齐测试
 *
 * 目标：将 src/utils/officeEmployeeReadApi.ts 的覆盖率从 39.3% 提升到 95%+
 * 覆盖范围：
 * - 所有导出函数（uploadChatOfficeFile / uploadTutorialOfficeFile / isOfficeExcelReadInstalled /
 *   runOfficeEmployeeRead / mapOfficeExcelReadToAnalysisResult / summarizeOfficeExcelRead /
 *   readExcelViaOfficePack / readWordViaOfficePack）
 * - 内部辅助函数（resolveWorkspaceRoot / uploadOfficeFile / isMissingPlatformShellUpload /
 *   uploadViaExtractGrid / ensureCsrf / workbookPayloadFromEmployeeData / toExcelCellValue）
 * - 分支：happy path / 空值 / 边界值 / 异常路径 / 回退逻辑 / 缓存
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

// ── mock 函数（hoisted-safe，vi.mock 工厂在 resetModules 后仍引用同一实例）──
const mocks = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  primeCsrfCookie: vi.fn(),
  readCsrfTokenFromCookie: vi.fn(),
  fetchEmployeePlannerStatus: vi.fn(),
  resolveOfficeInstalledPackIds: vi.fn(),
}))

vi.mock('@/api/core', () => ({ primeCsrfCookie: mocks.primeCsrfCookie }))
vi.mock('@/utils/apiBase', () => ({ apiFetch: mocks.apiFetch }))
vi.mock('@/utils/csrfCookie', () => ({ readCsrfTokenFromCookie: mocks.readCsrfTokenFromCookie }))
vi.mock('@/utils/platformShellApi', () => ({ fetchEmployeePlannerStatus: mocks.fetchEmployeePlannerStatus }))
vi.mock('@/utils/officeToolDeskRows', () => ({ resolveOfficeInstalledPackIds: mocks.resolveOfficeInstalledPackIds }))

// ── 辅助函数 ──

/** 创建模拟 Response */
function jsonRes(body: unknown, opts: { ok?: boolean; status?: number } = {}): Response {
  const { ok = true, status = 200 } = opts
  return {
    ok,
    status,
    json: async () => body,
  } as unknown as Response
}

/** 创建 Response，json() 抛错以测试 catch 分支 */
function throwingJsonRes(opts: { ok?: boolean; status?: number } = {}): Response {
  const { ok = false, status = 500 } = opts
  return {
    ok,
    status,
    json: async () => {
      throw new Error('Invalid JSON')
    },
  } as unknown as Response
}

/** 创建测试文件 */
function makeFile(name = 'test.xlsx'): File {
  return new File(['content'], name, {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
}

let mod: typeof import('./officeEmployeeReadApi')

beforeEach(async () => {
  // 重置模块缓存以清除模块级状态（cachedWorkspaceRoot）
  vi.resetModules()
  mod = await import('./officeEmployeeReadApi')
  mocks.apiFetch.mockReset()
  mocks.primeCsrfCookie.mockReset().mockResolvedValue(undefined)
  mocks.readCsrfTokenFromCookie.mockReset().mockReturnValue('csrf-token')
  mocks.fetchEmployeePlannerStatus.mockReset()
  mocks.resolveOfficeInstalledPackIds.mockReset()
})

// ── uploadChatOfficeFile ──

describe('uploadChatOfficeFile', () => {
  it('CHAT 上传成功时直接返回结果（含 filename）', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path/to/file.xlsx', workspace_root: '/root', filename: 'custom.xlsx' },
      }),
    )

    const result = await mod.uploadChatOfficeFile(makeFile())

    expect(result).toEqual({
      file_path: '/path/to/file.xlsx',
      workspace_root: '/root',
      filename: 'custom.xlsx',
    })
    expect(mocks.apiFetch).toHaveBeenCalledTimes(1)
  })

  it('CHAT 上传成功但无 filename 时使用 file.name', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path', workspace_root: '/root' },
      }),
    )

    const result = await mod.uploadChatOfficeFile(makeFile('my-file.xlsx'))

    expect(result.filename).toBe('my-file.xlsx')
  })

  it('CHAT 上传成功但 filename 为空白时使用 file.name', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path', workspace_root: '/root', filename: '   ' },
      }),
    )

    const result = await mod.uploadChatOfficeFile(makeFile('fallback.xlsx'))

    expect(result.filename).toBe('fallback.xlsx')
  })

  it('上传响应 body.data 为空时回退到 body 本身', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        file_path: '/path',
        workspace_root: '/root',
      }),
    )

    const result = await mod.uploadChatOfficeFile(makeFile())

    expect(result.file_path).toBe('/path')
  })

  it('CHAT 返回 404 时回退到 TUTORIAL', async () => {
    mocks.apiFetch.mockResolvedValueOnce(jsonRes({}, { ok: false, status: 404 }))
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path', workspace_root: '/root' },
      }),
    )

    const result = await mod.uploadChatOfficeFile(makeFile())

    expect(result.file_path).toBe('/path')
    expect(mocks.apiFetch).toHaveBeenCalledTimes(2)
  })

  it('CHAT 返回 "Not Found" 消息时回退到 TUTORIAL', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({ message: 'Not Found' }, { ok: false, status: 500 }),
    )
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path', workspace_root: '/root' },
      }),
    )

    const result = await mod.uploadChatOfficeFile(makeFile())

    expect(result.file_path).toBe('/path')
  })

  it('CHAT 返回 "Method Not Allowed" 消息时回退到 TUTORIAL', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({ message: 'Method Not Allowed' }, { ok: false, status: 500 }),
    )
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path', workspace_root: '/root' },
      }),
    )

    const result = await mod.uploadChatOfficeFile(makeFile())

    expect(result.file_path).toBe('/path')
  })

  it('CHAT 和 TUTORIAL 都返回 405 时回退到 extract-grid', async () => {
    mocks.apiFetch.mockResolvedValueOnce(jsonRes({}, { ok: false, status: 405 }))
    mocks.apiFetch.mockResolvedValueOnce(jsonRes({}, { ok: false, status: 405 }))
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        file_path: '/path',
        workspace_root: '/root',
        template_name: 'template.xlsx',
      }),
    )

    const result = await mod.uploadChatOfficeFile(makeFile())

    expect(result.file_path).toBe('/path')
    expect(result.filename).toBe('template.xlsx')
    expect(mocks.apiFetch).toHaveBeenCalledTimes(3)
  })

  it('extract-grid 从 preview_data.file_path 获取路径', async () => {
    mocks.apiFetch.mockResolvedValueOnce(jsonRes({}, { ok: false, status: 404 }))
    mocks.apiFetch.mockResolvedValueOnce(jsonRes({}, { ok: false, status: 405 }))
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        preview_data: { file_path: '/preview/path' },
        workspace_root: '/root',
      }),
    )

    const result = await mod.uploadChatOfficeFile(makeFile())

    expect(result.file_path).toBe('/preview/path')
  })

  it('extract-grid 无 template_name 时使用 file.name', async () => {
    mocks.apiFetch.mockResolvedValueOnce(jsonRes({}, { ok: false, status: 404 }))
    mocks.apiFetch.mockResolvedValueOnce(jsonRes({}, { ok: false, status: 405 }))
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        file_path: '/path',
        workspace_root: '/root',
      }),
    )

    const result = await mod.uploadChatOfficeFile(makeFile('my-file.xlsx'))

    expect(result.filename).toBe('my-file.xlsx')
  })

  it('CHAT 返回 500 时直接抛出（不回退）', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({ message: 'Server Error' }, { ok: false, status: 500 }),
    )

    await expect(mod.uploadChatOfficeFile(makeFile())).rejects.toThrow('Server Error')
    expect(mocks.apiFetch).toHaveBeenCalledTimes(1)
  })

  it('TUTORIAL 返回非 404/405 错误时直接抛出', async () => {
    mocks.apiFetch.mockResolvedValueOnce(jsonRes({}, { ok: false, status: 404 }))
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({ message: 'Server Error' }, { ok: false, status: 500 }),
    )

    await expect(mod.uploadChatOfficeFile(makeFile())).rejects.toThrow('Server Error')
    expect(mocks.apiFetch).toHaveBeenCalledTimes(2)
  })

  it('extract-grid 返回错误时抛出（使用 body.detail）', async () => {
    mocks.apiFetch.mockResolvedValueOnce(jsonRes({}, { ok: false, status: 404 }))
    mocks.apiFetch.mockResolvedValueOnce(jsonRes({}, { ok: false, status: 405 }))
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({ detail: 'extract-grid error' }, { ok: false, status: 500 }),
    )

    await expect(mod.uploadChatOfficeFile(makeFile())).rejects.toThrow('extract-grid error')
  })

  it('extract-grid success=false 时抛出', async () => {
    mocks.apiFetch.mockResolvedValueOnce(jsonRes({}, { ok: false, status: 404 }))
    mocks.apiFetch.mockResolvedValueOnce(jsonRes({}, { ok: false, status: 405 }))
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({ success: false, detail: 'extract-grid 拒绝' }),
    )

    await expect(mod.uploadChatOfficeFile(makeFile())).rejects.toThrow('extract-grid 拒绝')
  })

  it('上传成功但未返回 file_path 时抛出', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { workspace_root: '/root' },
      }),
    )

    await expect(mod.uploadChatOfficeFile(makeFile())).rejects.toThrow(
      '上传成功但未返回 file_path / workspace_root',
    )
  })

  it('extract-grid 上传成功但无 file_path 时抛出', async () => {
    mocks.apiFetch.mockResolvedValueOnce(jsonRes({}, { ok: false, status: 404 }))
    mocks.apiFetch.mockResolvedValueOnce(jsonRes({}, { ok: false, status: 405 }))
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        workspace_root: '/root',
      }),
    )

    await expect(mod.uploadChatOfficeFile(makeFile())).rejects.toThrow(
      'extract-grid 上传成功但未返回 file_path / workspace_root',
    )
  })

  it('上传 success=false 时抛出（使用 body.error）', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: false,
        error: '上传被拒',
      }),
    )

    await expect(mod.uploadChatOfficeFile(makeFile())).rejects.toThrow('上传被拒')
  })

  it('res.json() 抛错时使用空对象并按 HTTP 状态码报错', async () => {
    mocks.apiFetch.mockResolvedValueOnce(throwingJsonRes({ ok: false, status: 500 }))

    await expect(mod.uploadChatOfficeFile(makeFile())).rejects.toThrow('上传失败 HTTP 500')
  })
})

// ── uploadTutorialOfficeFile ──

describe('uploadTutorialOfficeFile', () => {
  it('TUTORIAL 上传成功', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path', workspace_root: '/root', filename: 'tut.xlsx' },
      }),
    )

    const result = await mod.uploadTutorialOfficeFile(makeFile())

    expect(result).toEqual({
      file_path: '/path',
      workspace_root: '/root',
      filename: 'tut.xlsx',
    })
  })

  it('TUTORIAL 上传失败时抛出', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({ message: 'rejected' }, { ok: false, status: 400 }),
    )

    await expect(mod.uploadTutorialOfficeFile(makeFile())).rejects.toThrow('rejected')
  })
})

// ── isOfficeExcelReadInstalled ──

describe('isOfficeExcelReadInstalled', () => {
  it('已安装时返回 true', async () => {
    mocks.fetchEmployeePlannerStatus.mockResolvedValue({ office_ready: true })
    mocks.resolveOfficeInstalledPackIds.mockReturnValue(['excel-full-read-employee'])

    const result = await mod.isOfficeExcelReadInstalled()

    expect(result).toBe(true)
    expect(mocks.fetchEmployeePlannerStatus).toHaveBeenCalledWith(false)
  })

  it('未安装时返回 false', async () => {
    mocks.fetchEmployeePlannerStatus.mockResolvedValue({ office_ready: false })
    mocks.resolveOfficeInstalledPackIds.mockReturnValue([])

    const result = await mod.isOfficeExcelReadInstalled()

    expect(result).toBe(false)
  })

  it('force=true 时传递给 fetchEmployeePlannerStatus', async () => {
    mocks.fetchEmployeePlannerStatus.mockResolvedValue({})
    mocks.resolveOfficeInstalledPackIds.mockReturnValue([])

    await mod.isOfficeExcelReadInstalled(true)

    expect(mocks.fetchEmployeePlannerStatus).toHaveBeenCalledWith(true)
  })

  it('fetchEmployeePlannerStatus 抛错时返回 false', async () => {
    mocks.fetchEmployeePlannerStatus.mockRejectedValue(new Error('network error'))

    const result = await mod.isOfficeExcelReadInstalled()

    expect(result).toBe(false)
  })
})

// ── runOfficeEmployeeRead ──

describe('runOfficeEmployeeRead', () => {
  it('Excel 员工执行成功', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { sheets: [], summary: 'ok' },
      }),
    )

    const result = await mod.runOfficeEmployeeRead('excel-full-read-employee', '/path', '/root')

    expect(result).toEqual({ sheets: [], summary: 'ok' })
    expect(mocks.apiFetch).toHaveBeenCalledWith(
      '/api/mod/excel-full-read-employee/employees/excel-full-read-employee/run',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          file_path: '/path',
          workspace_root: '/root',
          action: 'convert',
        }),
      }),
    )
  })

  it('Word 员工执行成功', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { ok: true, summary: 'word ok' },
      }),
    )

    const result = await mod.runOfficeEmployeeRead('word-full-read-employee', '/path', '/root')

    expect(result).toEqual({ ok: true, summary: 'word ok' })
  })

  it('未知员工 ID 时抛出', async () => {
    await expect(mod.runOfficeEmployeeRead('unknown', '/path', '/root')).rejects.toThrow(
      '未知办公员工：unknown',
    )
    expect(mocks.apiFetch).not.toHaveBeenCalled()
  })

  it('HTTP 错误时抛出（使用 body.message）', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({ message: '执行失败' }, { ok: false, status: 500 }),
    )

    await expect(
      mod.runOfficeEmployeeRead('excel-full-read-employee', '/path', '/root'),
    ).rejects.toThrow('执行失败')
  })

  it('success=false 时抛出（使用 body.error）', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({ success: false, error: '员工错误' }),
    )

    await expect(
      mod.runOfficeEmployeeRead('excel-full-read-employee', '/path', '/root'),
    ).rejects.toThrow('员工错误')
  })

  it('res.json() 抛错时使用 HTTP 状态码', async () => {
    mocks.apiFetch.mockResolvedValueOnce(throwingJsonRes({ ok: false, status: 502 }))

    await expect(
      mod.runOfficeEmployeeRead('excel-full-read-employee', '/path', '/root'),
    ).rejects.toThrow('员工执行失败 HTTP 502')
  })

  it('返回 body.data 为空时回退到 body', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        custom_field: 'value',
      }),
    )

    const result = await mod.runOfficeEmployeeRead('excel-full-read-employee', '/path', '/root')

    // 源代码：return asRecord(body?.data || body) —— data 为空时回退到整个 body
    expect(result).toEqual({ success: true, custom_field: 'value' })
  })
})

// ── mapOfficeExcelReadToAnalysisResult ──

describe('mapOfficeExcelReadToAnalysisResult', () => {
  const upload = { file_path: '/path/to/file.xlsx', workspace_root: '/root', filename: 'test.xlsx' }

  it('空 sheets 时返回空结果', () => {
    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, { sheets: [] })

    expect(result.sheets).toEqual([])
    // 源代码：first?.fields?.map(...) —— first 为 undefined 时返回 undefined
    expect(result.fields).toBeUndefined()
    expect(result.preview_data?.file_path).toBe('/path/to/file.xlsx')
    expect(result.preview_data?.sheet_name).toBeUndefined()
    expect(result.preview_data?.sheet_names).toEqual([])
    expect(result.preview_data?.all_sheets).toEqual([])
  })

  it('无 sheets 字段时返回空结果', () => {
    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, {})

    expect(result.sheets).toEqual([])
  })

  it('完整 sheets 映射（含 headers / rows / cells）', () => {
    const employeeData = {
      sheets: [
        {
          name: 'Sheet1',
          headers: [{ display: '姓名' }, { value: '年龄' }, { display: '', value: '' }],
          rows: [{ cells: { 姓名: '张三', 年龄: 25 } }, { 姓名: '李四', 年龄: 30 }],
        },
      ],
    }

    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, employeeData)

    expect(result.sheets).toHaveLength(1)
    const sheet = result.sheets![0]
    expect(sheet.sheet_index).toBe(1)
    expect(sheet.sheet_name).toBe('Sheet1')
    expect(sheet.fields).toEqual([
      { name: '姓名', label: '姓名', type: 'dynamic' },
      { name: '年龄', label: '年龄', type: 'dynamic' },
    ])
    expect(sheet.sample_rows).toHaveLength(2)
    expect(sheet.sample_rows![0]).toEqual({ 姓名: '张三', 年龄: 25 })
    expect(sheet.sample_rows![1]).toEqual({ 姓名: '李四', 年龄: 30 })
    expect(sheet.grid_preview?.rows).toHaveLength(3) // header + 2 rows
    expect(sheet.tables).toEqual([])
  })

  it('sheet 无 name 时使用 Sheet{idx+1}', () => {
    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, {
      sheets: [{ headers: [], rows: [] }],
    })

    expect(result.sheets![0].sheet_name).toBe('Sheet1')
  })

  it('header 优先使用 display，无 display 时使用 value', () => {
    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, {
      sheets: [
        {
          headers: [{ display: '显示名', value: '内部值' }, { value: '仅值' }],
        },
      ],
    })

    expect(result.sheets![0].fields).toEqual([
      { name: '显示名', label: '显示名', type: 'dynamic' },
      { name: '仅值', label: '仅值', type: 'dynamic' },
    ])
  })

  it('header 空白字符串被过滤', () => {
    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, {
      sheets: [
        {
          headers: [{ display: '   ' }, { display: '有效' }],
        },
      ],
    })

    expect(result.sheets![0].fields).toHaveLength(1)
    expect(result.sheets![0].fields![0].name).toBe('有效')
  })

  it('rows 无 cells 时使用 row 本身作为 source', () => {
    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, {
      sheets: [
        {
          headers: [{ display: 'A' }],
          rows: [{ A: 'value1' }, { cells: {}, A: 'value2' }],
        },
      ],
    })

    // 源代码：cells = asRecord(row.cells)；Object.keys(cells).length 为 0 时 source = row
    // 第二个 row 的 cells 是空对象 {}，所以 source = row 本身（包含空 cells 字段）
    expect(result.sheets![0].sample_rows).toEqual([
      { A: 'value1' },
      { cells: {}, A: 'value2' },
    ])
  })

  it('toExcelCellValue: 处理各种值类型（null/string/number/boolean/array/object/undefined/function）', () => {
    const fn = () => 'test'
    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, {
      sheets: [
        {
          headers: [
            { display: 'A' },
            { display: 'B' },
            { display: 'C' },
            { display: 'D' },
            { display: 'E' },
            { display: 'F' },
            { display: 'G' },
            { display: 'H' },
          ],
          rows: [
            {
              cells: {
                A: 'text',
                B: 42,
                C: true,
                D: null,
                E: [1, 'two', { three: 3 }],
                F: { nested: 'value' },
                G: undefined,
                H: fn,
              },
            },
          ],
        },
      ],
    })

    const row = result.sheets![0].sample_rows![0] as Record<string, unknown>
    expect(row.A).toBe('text')
    expect(row.B).toBe(42)
    expect(row.C).toBe(true)
    expect(row.D).toBeNull()
    expect(row.E).toEqual([1, 'two', { three: 3 }])
    expect(row.F).toEqual({ nested: 'value' })
    expect(row.G).toBeNull() // undefined → null
    expect(row.H).toBe(String(fn)) // function → String(value)
  })

  it('grid_preview: null/undefined 值转为空字符串', () => {
    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, {
      sheets: [
        {
          headers: [{ display: 'A' }, { display: 'B' }],
          rows: [{ cells: { A: null, B: 'text' } }],
        },
      ],
    })

    const gridRows = result.sheets![0].grid_preview!.rows!
    expect(gridRows[0]).toEqual(['A', 'B']) // header row
    expect(gridRows[1]).toEqual(['', 'text']) // null → ''
  })

  it('grid_preview: 最多 20 行 sample_rows', () => {
    const rows = Array.from({ length: 25 }, (_, i) => ({ cells: { A: `val${i}` } }))
    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, {
      sheets: [{ headers: [{ display: 'A' }], rows }],
    })

    const gridRows = result.sheets![0].grid_preview!.rows!
    expect(gridRows).toHaveLength(21) // 1 header + 20 data rows
  })

  it('多个 sheets 时 preview_data 包含所有 sheet_names', () => {
    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, {
      sheets: [
        { name: 'Sheet1', headers: [], rows: [] },
        { name: 'Sheet2', headers: [], rows: [] },
      ],
    })

    expect(result.preview_data?.sheet_names).toEqual(['Sheet1', 'Sheet2'])
    expect(result.preview_data?.sheet_name).toBe('Sheet1')
    expect(result.preview_data?.all_sheets).toHaveLength(2)
  })

  it('workbookPayloadFromEmployeeData: 从 items 中提取含 sheets 的项', () => {
    const employeeData = {
      items: [
        { name: 'item1', sheets: [{ name: 'FromItem', headers: [], rows: [] }] },
        { name: 'item2' },
      ],
    }

    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, employeeData)

    expect(result.sheets).toHaveLength(1)
    expect(result.sheets![0].sheet_name).toBe('FromItem')
  })

  it('workbookPayloadFromEmployeeData: items 中无含 sheets 的项时回退到 data.sheets', () => {
    const employeeData = {
      items: [{ name: 'item1' }],
      sheets: [{ name: 'FromData', headers: [], rows: [] }],
    }

    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, employeeData)

    expect(result.sheets).toHaveLength(1)
    expect(result.sheets![0].sheet_name).toBe('FromData')
  })

  it('workbookPayloadFromEmployeeData: summary 为 JSON 字符串时解析', () => {
    const employeeData = {
      summary: JSON.stringify({ sheets: [{ name: 'FromSummary', headers: [], rows: [] }] }),
    }

    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, employeeData)

    expect(result.sheets).toHaveLength(1)
    expect(result.sheets![0].sheet_name).toBe('FromSummary')
  })

  it('workbookPayloadFromEmployeeData: summary 为无效 JSON 时回退到 data', () => {
    const employeeData = {
      summary: '{invalid json',
      sheets: [{ name: 'Fallback', headers: [], rows: [] }],
    }

    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, employeeData)

    expect(result.sheets).toHaveLength(1)
    expect(result.sheets![0].sheet_name).toBe('Fallback')
  })

  it('workbookPayloadFromEmployeeData: summary 不以 { 开头时返回 data', () => {
    const employeeData = {
      summary: 'plain text summary',
      sheets: [{ name: 'PlainSheet', headers: [], rows: [] }],
    }

    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, employeeData)

    expect(result.sheets).toHaveLength(1)
    expect(result.sheets![0].sheet_name).toBe('PlainSheet')
  })

  it('workbookPayloadFromEmployeeData: summary 为有效 JSON 但无 sheets 时返回解析结果', () => {
    const employeeData = {
      summary: JSON.stringify({ other_field: 'value' }),
    }

    const result = mod.mapOfficeExcelReadToAnalysisResult(upload, employeeData)

    expect(result.sheets).toEqual([]) // 解析结果无 sheets
  })
})

// ── summarizeOfficeExcelRead ──

describe('summarizeOfficeExcelRead', () => {
  it('完整摘要：含 sheets 和 summary', () => {
    const employeeData = {
      summary: '读取完成',
      sheets: [
        { name: 'Sheet1', headers: [{ display: 'A' }], rows: [{ A: '1' }, { A: '2' }] },
        { name: 'Sheet2', headers: [{ display: 'B' }], rows: [{ B: '1' }] },
      ],
    }

    const summary = mod.summarizeOfficeExcelRead('test.xlsx', employeeData)

    expect(summary).toContain('Excel 读取完成（办公包 · Excel 读取员）')
    expect(summary).toContain('文件：test.xlsx')
    expect(summary).toContain('工作表总数：2')
    expect(summary).toContain('分表摘要：')
    expect(summary).toContain('Sheet 1（Sheet1）：词条1，数据行2')
    expect(summary).toContain('Sheet 2（Sheet2）：词条1，数据行1')
    expect(summary).toContain('员工摘要：读取完成')
  })

  it('空 sheets 时显示工作表总数 1', () => {
    const summary = mod.summarizeOfficeExcelRead('empty.xlsx', { sheets: [] })

    expect(summary).toContain('工作表总数：1')
    expect(summary).not.toContain('分表摘要：')
  })

  it('无 summary 时不包含员工摘要', () => {
    const summary = mod.summarizeOfficeExcelRead('test.xlsx', {
      sheets: [{ name: 'S1', headers: [], rows: [] }],
    })

    expect(summary).not.toContain('员工摘要：')
  })

  it('summary 超过 400 字符时截断', () => {
    const longSummary = 'A'.repeat(500)
    const summary = mod.summarizeOfficeExcelRead('test.xlsx', {
      summary: longSummary,
      sheets: [],
    })

    expect(summary).toContain('员工摘要：' + 'A'.repeat(400))
    expect(summary).not.toContain('A'.repeat(401))
  })

  it('超过 12 个 sheets 时只摘要前 12 个', () => {
    const sheets = Array.from({ length: 15 }, (_, i) => ({
      name: `Sheet${i + 1}`,
      headers: [],
      rows: [],
    }))

    const summary = mod.summarizeOfficeExcelRead('test.xlsx', { sheets })

    expect(summary).toContain('工作表总数：15')
    expect(summary).toContain('Sheet 1（Sheet1）')
    expect(summary).toContain('Sheet 12（Sheet12）')
    expect(summary).not.toContain('Sheet 13（Sheet13）')
  })

  it('sheet 无 name 时使用 Sheet{idx+1}', () => {
    const summary = mod.summarizeOfficeExcelRead('test.xlsx', {
      sheets: [{ headers: [], rows: [] }],
    })

    expect(summary).toContain('Sheet 1（Sheet1）')
  })

  it('workbookPayloadFromEmployeeData: 从 items 提取', () => {
    const employeeData = {
      items: [
        { sheets: [{ name: 'ItemSheet', headers: [{ display: 'X' }], rows: [{ X: '1' }] }] },
      ],
    }

    const summary = mod.summarizeOfficeExcelRead('test.xlsx', employeeData)

    expect(summary).toContain('Sheet 1（ItemSheet）')
  })
})

// ── readExcelViaOfficePack ──

describe('readExcelViaOfficePack', () => {
  it('完整 Excel 读取流程', async () => {
    // uploadChatOfficeFile
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path', workspace_root: '/root', filename: 'test.xlsx' },
      }),
    )
    // runOfficeEmployeeRead
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: {
          ok: true,
          sheets: [{ name: 'Sheet1', headers: [{ display: 'A' }], rows: [{ cells: { A: '1' } }] }],
          summary: '读取成功',
        },
      }),
    )

    const result = await mod.readExcelViaOfficePack(makeFile('test.xlsx'))

    expect(result.upload.file_path).toBe('/path')
    expect(result.employeeData.ok).toBe(true)
    expect(result.result.sheets).toHaveLength(1)
    expect(result.summary).toContain('Excel 读取完成')
    expect(result.summary).toContain('员工摘要：读取成功')
  })

  it('employeeData.ok === false 时抛出（使用 error）', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path', workspace_root: '/root' },
      }),
    )
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { ok: false, error: '读取失败' },
      }),
    )

    await expect(mod.readExcelViaOfficePack(makeFile())).rejects.toThrow('读取失败')
  })

  it('employeeData.ok === false 且无 error 时使用 summary', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path', workspace_root: '/root' },
      }),
    )
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { ok: false, summary: '执行失败摘要' },
      }),
    )

    await expect(mod.readExcelViaOfficePack(makeFile())).rejects.toThrow('执行失败摘要')
  })

  it('employeeData.ok === false 且无 error/summary 时使用默认消息', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path', workspace_root: '/root' },
      }),
    )
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { ok: false },
      }),
    )

    await expect(mod.readExcelViaOfficePack(makeFile())).rejects.toThrow('Excel 读取员执行失败')
  })
})

// ── readWordViaOfficePack ──

describe('readWordViaOfficePack', () => {
  it('使用传入的 uploaded 时跳过上传', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { ok: true, summary: 'Word 读取完成' },
      }),
    )

    const result = await mod.readWordViaOfficePack(makeFile(), {
      file_path: '/path',
      workspace_root: '/root',
      filename: 'test.docx',
    })

    expect(result.ok).toBe(true)
    expect(result.summary).toBe('Word 读取完成')
    expect(mocks.apiFetch).toHaveBeenCalledTimes(1) // 只调用 runOfficeEmployeeRead
  })

  it('未传入 uploaded 时调用 uploadTutorialOfficeFile', async () => {
    // uploadTutorialOfficeFile
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path', workspace_root: '/root' },
      }),
    )
    // runOfficeEmployeeRead
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { ok: true, summary: 'Word ok' },
      }),
    )

    const result = await mod.readWordViaOfficePack(makeFile())

    expect(result.ok).toBe(true)
    expect(result.summary).toBe('Word ok')
  })

  it('uploaded.workspace_root 为空时抛出', async () => {
    await expect(
      mod.readWordViaOfficePack(makeFile(), {
        file_path: '/path',
        workspace_root: '',
        filename: 'test.docx',
      }),
    ).rejects.toThrow('办公样本上传未返回 workspace_root')
  })

  it('employeeData.ok === false 时返回 ok=false', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { ok: false, summary: '失败摘要' },
      }),
    )

    const result = await mod.readWordViaOfficePack(makeFile(), {
      file_path: '/path',
      workspace_root: '/root',
      filename: 'test.docx',
    })

    expect(result.ok).toBe(false)
    expect(result.summary).toBe('失败摘要')
  })

  it('employeeData.ok !== false 且无 summary 时使用默认成功摘要', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { ok: true },
      }),
    )

    const result = await mod.readWordViaOfficePack(makeFile(), {
      file_path: '/path',
      workspace_root: '/root',
      filename: 'test.docx',
    })

    expect(result.ok).toBe(true)
    expect(result.summary).toBe('Word 读取完成')
  })

  it('ok=false 且无 summary 时使用默认失败摘要', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { ok: false },
      }),
    )

    const result = await mod.readWordViaOfficePack(makeFile(), {
      file_path: '/path',
      workspace_root: '/root',
      filename: 'test.docx',
    })

    expect(result.ok).toBe(false)
    expect(result.summary).toBe('Word 读取失败')
  })

  it('使用 employeeData.error 作为 summary', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { ok: false, error: '错误信息' },
      }),
    )

    const result = await mod.readWordViaOfficePack(makeFile(), {
      file_path: '/path',
      workspace_root: '/root',
      filename: 'test.docx',
    })

    expect(result.ok).toBe(false)
    expect(result.summary).toBe('错误信息')
  })
})

// ── resolveWorkspaceRoot（间接测试缓存行为）──

describe('resolveWorkspaceRoot 缓存行为', () => {
  it('上传响应含 workspace_root 时直接使用（不查缓存/不请求 API）', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path', workspace_root: '/direct-root' },
      }),
    )

    const result = await mod.uploadTutorialOfficeFile(makeFile())

    expect(result.workspace_root).toBe('/direct-root')
    expect(mocks.apiFetch).toHaveBeenCalledTimes(1) // 只调用 upload
  })

  it('上传响应无 workspace_root 时从 workspace-root API 获取并缓存', async () => {
    // upload 调用
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path' },
      }),
    )
    // workspace-root API 调用
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        data: { workspace_root: '/api-root' },
      }),
    )

    const result = await mod.uploadTutorialOfficeFile(makeFile())

    expect(result.workspace_root).toBe('/api-root')
    expect(mocks.apiFetch).toHaveBeenCalledTimes(2)
  })

  it('缓存命中：第二次调用不重新请求 workspace-root API', async () => {
    // 第一次 upload：无 workspace_root → 请求 API → 设置缓存
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path1' },
      }),
    )
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        data: { workspace_root: '/cached-root' },
      }),
    )

    const result1 = await mod.uploadTutorialOfficeFile(makeFile('file1.xlsx'))
    expect(result1.workspace_root).toBe('/cached-root')
    expect(mocks.apiFetch).toHaveBeenCalledTimes(2)

    // 第二次 upload：无 workspace_root → 缓存命中 → 不请求 API
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path2' },
      }),
    )

    const result2 = await mod.uploadTutorialOfficeFile(makeFile('file2.xlsx'))
    expect(result2.workspace_root).toBe('/cached-root') // 来自缓存
    expect(mocks.apiFetch).toHaveBeenCalledTimes(3) // 只多了 upload 调用
  })

  it('workspace-root API 返回空时返回空字符串（导致后续抛错）', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path' },
      }),
    )
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        data: {},
      }),
    )

    await expect(mod.uploadTutorialOfficeFile(makeFile())).rejects.toThrow(
      '上传成功但未返回 file_path / workspace_root',
    )
  })

  it('workspace-root API res.json() 抛错时返回空字符串', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path' },
      }),
    )
    mocks.apiFetch.mockResolvedValueOnce(throwingJsonRes({ ok: true, status: 200 }))

    await expect(mod.uploadTutorialOfficeFile(makeFile())).rejects.toThrow(
      '上传成功但未返回 file_path / workspace_root',
    )
  })
})

// ── ensureCsrf（间接测试）──

describe('ensureCsrf 行为', () => {
  it('有 CSRF cookie 时不调用 primeCsrfCookie', async () => {
    mocks.readCsrfTokenFromCookie.mockReturnValue('csrf-token')
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path', workspace_root: '/root' },
      }),
    )

    await mod.uploadTutorialOfficeFile(makeFile())

    expect(mocks.primeCsrfCookie).not.toHaveBeenCalled()
  })

  it('无 CSRF cookie 时调用 primeCsrfCookie', async () => {
    mocks.readCsrfTokenFromCookie.mockReturnValue(null)
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path', workspace_root: '/root' },
      }),
    )

    await mod.uploadTutorialOfficeFile(makeFile())

    expect(mocks.primeCsrfCookie).toHaveBeenCalled()
  })

  it('CSRF cookie 为空字符串时调用 primeCsrfCookie', async () => {
    mocks.readCsrfTokenFromCookie.mockReturnValue('')
    mocks.apiFetch.mockResolvedValueOnce(
      jsonRes({
        success: true,
        data: { file_path: '/path', workspace_root: '/root' },
      }),
    )

    await mod.uploadTutorialOfficeFile(makeFile())

    expect(mocks.primeCsrfCookie).toHaveBeenCalled()
  })
})

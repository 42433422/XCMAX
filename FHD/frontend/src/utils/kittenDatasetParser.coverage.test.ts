import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as XLSX from 'xlsx'
import type { ParsedDatasetFile } from './kittenDatasetParser'

function createFile(content: string, name: string): File {
  const file = new File([content], name)
  Object.defineProperties(file, {
    text: { value: async () => content, configurable: true },
    arrayBuffer: { value: async () => new TextEncoder().encode(content).buffer, configurable: true },
  })
  return file
}
const empty = { rows: 0, columns: [], preview: [], sampleRows: [], fieldProfiles: [] }
let parse: typeof import('./kittenDatasetParser').parseDatasetFile
let sampleLimit: number
let workers: ParserWorker[]
class ParserWorker extends EventTarget {
  postMessage = vi.fn()
  removeEventListener = vi.fn(super.removeEventListener.bind(this))
  constructor(public url: URL, public options: WorkerOptions) { super(); workers.push(this) }
  respond(data: unknown) { this.dispatchEvent(new MessageEvent('message', { data })) }
}
beforeEach(async () => {
  vi.resetModules()
  workers = []
  vi.stubGlobal('Worker', ParserWorker)
  const api = await import('./kittenDatasetParser')
  parse = api.parseDatasetFile
  sampleLimit = api.KITTEN_DATASET_SAMPLE_LIMIT
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe('dataset parsing and profiles', () => {
  it('uses a bounded 1000-row sample', async () => {
    expect(sampleLimit).toBe(1000)
    const result = await parse(createFile('name\n' + Array.from({ length: 1500 }, (_, i) => `user${i}`).join('\n'), 'large.csv'))
    expect(result.rows).toBe(1500)
    expect(result.sampleRows).toHaveLength(sampleLimit)
    expect(result.sampleRows.at(-1)).toEqual({ name: 'user999' })
  })
  it('parses CSV rows, headers, preview and complete field profiles', async () => {
    const result = await parse(createFile('name,age\nAlice,30\nBob,25\nCharlie,35', 'people.csv'))
    expect(result).toEqual({
      rows: 3, columns: ['name', 'age'],
      preview: [['name', 'age'], ['Alice', 30], ['Bob', 25]],
      sampleRows: [{ name: 'Alice', age: 30 }, { name: 'Bob', age: 25 }, { name: 'Charlie', age: 35 }],
      fieldProfiles: [{ name: 'name', type: 'category', nonEmpty: 3, uniqueCount: 3 }, { name: 'age', type: 'number', nonEmpty: 3, uniqueCount: 3 }],
    })
  })
  it.each(['txt', 'CSV'])('parses %s using CSV normalization', async (ext) => {
    expect((await parse(createFile('name,age\nAlice,30', `test.${ext}`))).columns).toEqual(['name', 'age'])
  })
  it.each([
    ['objects', [{ name: 'Alice', age: 30 }, { name: 'Bob', age: 25 }], 2, ['name', 'age']],
    ['values', [1, 2, 3], 3, ['value']],
    ['mixed values', [1, null, false, ['x']], 4, ['value']],
    ['object', { name: 'Alice', age: 30 }, 1, ['name', 'age']],
    ['wrapped', { data: [{ name: 'Alice' }, { name: 'Bob' }] }, 2, ['name']],
  ])('normalizes JSON %s', async (_label, payload, rows, columns) => {
    const result = await parse(createFile(JSON.stringify(payload), 'data.json'))
    expect(result.rows).toBe(rows)
    expect(result.columns).toEqual(columns)
    expect(result.sampleRows).toHaveLength(rows as number)
    expect(result.preview).toEqual(result.sampleRows.slice(0, 3))
  })
  it('normalizes empty JSON arrays and the blank header of an empty CSV', async () => {
    expect(await parse(createFile('[]', 'empty.json'))).toEqual(empty)
    expect(await parse(createFile('', 'empty.csv'))).toEqual({ ...empty, columns: [''], preview: [['']], fieldProfiles: [{ name: '', type: 'category', nonEmpty: 0, uniqueCount: 0 }] })
  })
  it.each(['not valid json', '"just a string"', '123', 'true', 'null'])('rejects unsupported JSON %s', async (text) => {
    await expect(parse(createFile(text, 'bad.json'))).rejects.toThrow('JSON 解析失败，请检查文件格式是否正确。')
  })
  it.each(['xlsx', 'xls'] as const)('reads genuine %s workbook bytes', async (bookType) => {
    const workbook = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet([{ name: 'Alice', age: 30 }]), 'People')
    const buffer = XLSX.write(workbook, { type: 'array', bookType }) as ArrayBuffer
    const file = { name: `people.${bookType}`, size: buffer.byteLength, arrayBuffer: async () => buffer } as File
    expect(await parse(file)).toMatchObject({ rows: 1, columns: ['name', 'age'], sampleRows: [{ name: 'Alice', age: 30 }] })
  })
  it.each(['test.pdf', 'noext', 'test.doc'])('rejects unsupported file %s', async (name) => {
    await expect(parse(createFile('x', name))).rejects.toThrow(`暂不支持该文件类型: .${name.includes('.') ? name.split('.').at(-1) : 'unknown'}`)
  })
  it.each([
    ['number', [30, 25, 35]], ['number', ['￥1,000', '20%', ' 30 ']],
    ['date', ['2024-01-01', '2024-02-01', '2024-03-01']],
    ['text', Array.from({ length: 25 }, (_, i) => `user${i}`)],
    ['category', Array.from({ length: 20 }, (_, i) => i < 10 ? 'active' : 'inactive')],
    ['category', [null, '', '   ']], ['category', [false, {}, 'not-a-date', '¥ %']],
  ])('profiles %s fields from %j', async (type, values) => {
    const result = await parse(createFile(JSON.stringify((values as unknown[]).map((value) => ({ value }))), 'profile.json'))
    expect(result.fieldProfiles[0].type).toBe(type)
  })
  it('limits previews and discovers columns across differently shaped objects', async () => {
    const rows = Array.from({ length: 1001 }, (_, i) => i === 49 ? { name: `n${i}`, extra: 'yes' } : { name: `n${i}` })
    const result = await parse(createFile(JSON.stringify(rows), 'rows.json'))
    expect(result.columns).toEqual(['name', 'extra'])
    expect(result.preview).toHaveLength(3)
    expect(result.sampleRows).toHaveLength(1000)
    expect(result.fieldProfiles[1]).toEqual({ name: 'extra', type: 'category', nonEmpty: 1, uniqueCount: 1 })
  })
  it('preserves Chinese headers and fills missing CSV cells', async () => {
    const result = await parse(createFile('姓名,年龄\n张三,30\n李四', 'chinese.csv'))
    expect(result.columns).toEqual(['姓名', '年龄'])
    expect(result.sampleRows[1]).toEqual({ 姓名: '李四', 年龄: '' })
  })
  it('decodes UTF-8 when File.text is unavailable', async () => {
    const file = createFile('[{"姓名":"张三"}]', 'fallback.json')
    Reflect.deleteProperty(file, 'text')
    expect((await parse(file)).sampleRows).toEqual([{ 姓名: '张三' }])
  })
})

describe('large-file Worker lifecycle', () => {
  const largeFile = () => createFile(JSON.stringify([{ value: 'x'.repeat(100_000) }]), 'large.json')
  const payload: ParsedDatasetFile = { rows: 1, columns: ['value'], preview: [{ value: 7 }], sampleRows: [{ value: 7 }], fieldProfiles: [{ name: 'value', type: 'number', nonEmpty: 1, uniqueCount: 1 }] }
  it('matches response IDs, cleans listeners and reuses its worker for later requests', async () => {
    const file = largeFile()
    const pending = parse(file)
    const worker = workers[0]
    expect(worker.options).toEqual({ type: 'module' })
    expect(worker.url.pathname).toContain('datasetParser.worker.ts')
    expect(worker.postMessage).toHaveBeenCalledWith({ requestId: 1, file, ext: 'json' })
    worker.respond(null)
    worker.respond({ requestId: 99, ok: true, payload: empty })
    expect(worker.removeEventListener).not.toHaveBeenCalled()
    worker.respond({ requestId: 1, ok: true, payload })
    expect(await pending).toEqual(payload)
    expect(worker.removeEventListener).toHaveBeenCalledWith('message', expect.any(Function))
    const again = parse(file)
    expect(workers).toHaveLength(1)
    worker.respond({ requestId: 2, ok: true, payload: empty })
    expect(await again).toEqual(empty)
  })
  it.each([{ ok: false, error: 'invalid worker result' }, { ok: false }, { ok: true }])('falls back to parsing file content for %j', async (failure) => {
    const pending = parse(largeFile())
    workers[0].respond({ requestId: 1, ...failure })
    expect((await pending).sampleRows).toEqual([{ value: 'x'.repeat(100_000) }])
    expect(workers[0].removeEventListener).toHaveBeenCalledOnce()
  })
  it('falls back after the worker timeout and replaces a worker after its error event', async () => {
    vi.useFakeTimers()
    const pending = parse(largeFile())
    workers[0].dispatchEvent(new Event('error'))
    await vi.advanceTimersByTimeAsync(30_000)
    expect((await pending).rows).toBe(1)
    expect(workers[0].removeEventListener).toHaveBeenCalledOnce()
    expect(vi.getTimerCount()).toBe(0)
    const next = parse(largeFile())
    expect(workers).toHaveLength(2)
    workers[1].respond({ requestId: 2, ok: true, payload })
    expect(await next).toEqual(payload)
  })
  it('falls back to CSV parsing when worker construction is unavailable', async () => {
    vi.stubGlobal('Worker', class { constructor() { throw new Error('Worker disabled') } })
    const file = createFile('name,age\n' + Array.from({ length: 9000 }, (_, i) => `user${i},${i}`).join('\n'), 'big.csv')
    expect(file.size).toBeGreaterThanOrEqual(96 * 1024)
    const result = await parse(file)
    expect(result.rows).toBe(9000)
    expect(result.sampleRows).toHaveLength(1000)
  })
})

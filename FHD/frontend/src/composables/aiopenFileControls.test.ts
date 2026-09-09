import { afterEach, expect, it, vi } from 'vitest'
import { captureScreenFileSelection, clearScreenFiles, fileInputAvailable, listScreenFiles, rememberScreenFiles, setScreenFiles } from './aiopenFileControls'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

afterEach(() => { clearScreenFiles(); document.body.replaceChildren(); vi.useRealTimers() })

function input() {
  const element = document.createElement('input')
  element.type = 'file'
  document.body.appendChild(element)
  return element
}

function catalog() { return listScreenFiles().files as Array<{ file_id: string; name: string }> }

it('keeps only file references, deduplicates objects and retires them on account changes', () => {
  const file = new File(['private content'], 'example.csv', { type: 'text/csv' })
  rememberScreenFiles([file, file])
  expect(catalog()).toHaveLength(1)
  expect(JSON.stringify(listScreenFiles())).not.toContain('private content')
  productReadAccountEpoch.value++
  expect(catalog()).toEqual([])
})

it('bounds retained files and expires references', () => {
  vi.useFakeTimers()
  rememberScreenFiles(Array.from({ length: 40 }, (_, i) => new File(['x'], `${i}.csv`)))
  expect(catalog()).toHaveLength(32)
  expect(catalog()[0]!.name).toBe('8.csv')
  vi.advanceTimersByTime(15 * 60 * 1000)
  expect(catalog()).toEqual([])
})

it('does not adopt synthetic file selection events', () => {
  const element = input()
  Object.defineProperty(element, 'files', { value: [new File(['x'], 'fake.csv')] })
  element.addEventListener('change', captureScreenFileSelection)
  element.dispatchEvent(new Event('change'))
  expect(catalog()).toEqual([])
})

it('allows an intentionally hidden native picker but denies hidden containers and private fields', () => {
  const element = input()
  element.hidden = true
  expect(fileInputAvailable(element)).toBe(true)
  element.disabled = true
  expect(fileInputAvailable(element)).toBe(false)
  element.disabled = false
  const wrapper = document.createElement('div')
  document.body.appendChild(wrapper)
  wrapper.appendChild(element)
  wrapper.hidden = true
  expect(fileInputAvailable(element)).toBe(false)
  wrapper.hidden = false
  wrapper.dataset.aiPrivate = ''
  expect(fileInputAvailable(element)).toBe(false)
})

it('validates the full selection before mutating the input', async () => {
  const element = input()
  rememberScreenFiles([new File(['a'], 'a.csv', { type: 'text/csv' }), new File(['b'], 'b.pdf', { type: 'application/pdf' })])
  const ids = catalog().map(row => row.file_id)
  const current = vi.fn()
  expect((await setScreenFiles(element, { file_ids: ['missing'] }, current)).success).toBe(false)
  expect((await setScreenFiles(element, { file_ids: ids }, current)).success).toBe(false)
  element.accept = '.csv'
  expect((await setScreenFiles(element, { file_ids: [ids[1]] }, current)).success).toBe(false)
  expect((await setScreenFiles(element, { file_ids: [ids[0], ids[0]] }, current)).success).toBe(false)
  expect(element.files).toHaveLength(0)
  expect(current).not.toHaveBeenCalled()
})

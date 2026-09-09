/** Window-local references to files selected by the user; never persisted or sent as model content. */
import { nextTick } from 'vue'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { ensureEditable, privateControl } from './aiopenScreenControls'

const files = new Map<string, { file: File; expiresAt: number }>()
const TTL_MS = 15 * 60 * 1000
let epoch = productReadAccountEpoch.value

function fileId(): string {
  // LAN HTTP pages may lack randomUUID; getRandomValues remains available.
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')
}

export function clearScreenFiles(): void {
  files.clear()
  epoch = productReadAccountEpoch.value
}

function prune(): void {
  if (epoch !== productReadAccountEpoch.value) clearScreenFiles()
  for (const [id, row] of files) if (row.expiresAt <= Date.now()) files.delete(id)
}

export function rememberScreenFiles(selected: FileList | File[]): void {
  prune()
  for (const file of Array.from(selected)) {
    const existing = [...files].find(([, row]) => row.file === file)?.[0]
    files.set(existing ?? fileId(), { file, expiresAt: Date.now() + TTL_MS })
    while (files.size > 32) files.delete(files.keys().next().value!)
  }
}

export function captureScreenFileSelection(event: Event): void {
  const input = event.target
  if (!event.isTrusted || !(input instanceof HTMLInputElement) || input.type !== 'file' || privateControl(input)) return
  if (input.files) rememberScreenFiles(input.files)
}

export function listScreenFiles(): Record<string, unknown> {
  prune()
  return {
    success: true,
    files: [...files].map(([file_id, row]) => ({ file_id, name: row.file.name, size: row.file.size, type: row.file.type, expires_at: row.expiresAt })),
    instruction: '仅列出用户在本窗口开启软件控制后选过的文件，最多保留 32 个、15 分钟；账号切换或关闭控制即清除。无文件时请用户先选择文件。',
  }
}

export function fileInputAvailable(el: Element): boolean {
  if (!(el instanceof HTMLInputElement) || el.type !== 'file' || !el.isConnected || privateControl(el)) return false
  if (el.matches(':disabled') || el.readOnly || el.getAttribute('aria-disabled') === 'true' || el.closest('[inert]')) return false
  // Native pickers commonly use a hidden input inside a visible upload panel.
  // Only the input itself may be hidden; a hidden/inactive ancestor is denied.
  if (!el.parentElement) return false
  try { ensureEditable(el.parentElement); return true } catch { return false }
}

function accepts(input: HTMLInputElement, file: File): boolean {
  const tokens = input.accept.split(',').map(value => value.trim().toLowerCase()).filter(Boolean)
  return !tokens.length || tokens.some(token => token.startsWith('.')
    ? file.name.toLowerCase().endsWith(token)
    : token.endsWith('/*') ? file.type.toLowerCase().startsWith(token.slice(0, -1))
      : file.type.toLowerCase() === token)
}

export async function setScreenFiles(el: HTMLElement, params: Record<string, unknown>, assertCurrent: () => void): Promise<Record<string, unknown>> {
  prune()
  if (!fileInputAvailable(el)) return { success: false, message: '文件控件不可用、已禁用或属于隐藏/私密区域' }
  const input = el as HTMLInputElement
  const ids = params.file_ids
  if (!Array.isArray(ids) || ids.some(id => typeof id !== 'string') || new Set(ids).size !== ids.length) {
    return { success: false, message: 'file_ids 必须是无重复的文件编号数组' }
  }
  if (!input.multiple && ids.length > 1) return { success: false, message: '该控件只接受一个文件' }
  const selected = ids.map(id => files.get(id)?.file)
  if (selected.some(file => !file)) return { success: false, message: '文件编号不存在或已过期，请重新读取文件目录' }
  const selectedFiles = selected as File[]
  if (selectedFiles.some(file => !accepts(input, file))) return { success: false, message: '文件不符合控件 accept 类型限制' }
  if (typeof DataTransfer === 'undefined') return { success: false, message: '当前浏览器不支持文件控件赋值' }
  const transfer = new DataTransfer()
  for (const file of selectedFiles) transfer.items.add(file)
  assertCurrent()
  input.files = transfer.files
  input.dispatchEvent(new Event('input', { bubbles: true }))
  assertCurrent()
  if (!input.isConnected) throw new Error('文件控件已被页面移除，未继续触发上传')
  input.dispatchEvent(new Event('change', { bubbles: true }))
  await nextTick()
  assertCurrent()
  const actual = Array.from(input.files ?? [])
  return {
    success: actual.length === selectedFiles.length && actual.every((file, index) => file === selectedFiles[index]),
    files: actual.map(file => ({ name: file.name, size: file.size, type: file.type })),
    verification: 'file_selection_readback',
    instruction: '这里只验证文件控件。上传、导入或业务保存是否完成必须另行回读；页面可能消费后清空控件，请勿盲目重复提交。',
  }
}

import {
  clearTutorialOfficeUploadPaths,
  readTutorialOfficeUploadPaths,
  TUTORIAL_QUICKSTART_EXCEL_A,
  TUTORIAL_QUICKSTART_EXCEL_B,
  TUTORIAL_QUICKSTART_WORD,
  trackTutorialOfficeUploadPath,
} from '@/constants/tutorialSamples'
import { readWordViaOfficePack, uploadTutorialOfficeFile } from '@/utils/officeEmployeeReadApi'
import { sleep } from './demoHelpers'

export async function fetchTutorialSampleFile(url: string, filename: string): Promise<File> {
  const res = await fetch(url, { credentials: 'same-origin' })
  if (!res.ok) throw new Error(`样本下载失败 HTTP ${res.status}`)
  const blob = await res.blob()
  return new File([blob], filename, { type: blob.type || 'application/octet-stream' })
}

function chatFileInput(): HTMLInputElement | null {
  return document.querySelector<HTMLInputElement>('#view-chat input[type="file"]')
}

export function assignFileToInput(input: HTMLInputElement, file: File): void {
  const dt = new DataTransfer()
  dt.items.add(file)
  input.files = dt.files
  input.dispatchEvent(new Event('change', { bubbles: true }))
}

export async function injectExcelAnalyzeSample(url: string, filename: string): Promise<void> {
  const input = chatFileInput()
  if (!input) throw new Error('未找到对话页上传控件')
  const file = await fetchTutorialSampleFile(url, filename)
  assignFileToInput(input, file)
}

export async function uploadOfficeSampleForPath(file: File): Promise<string> {
  const uploaded = await uploadTutorialOfficeFile(file)
  trackTutorialOfficeUploadPath(uploaded.file_path)
  return uploaded.file_path
}

export async function readWordSampleViaOfficePack(file: File): Promise<{ ok: boolean; summary: string }> {
  const uploaded = await uploadTutorialOfficeFile(file)
  trackTutorialOfficeUploadPath(uploaded.file_path)
  return readWordViaOfficePack(file, uploaded)
}

export async function runQuickStartExcelDemo(which: 'a' | 'b'): Promise<void> {
  const url = which === 'a' ? TUTORIAL_QUICKSTART_EXCEL_A : TUTORIAL_QUICKSTART_EXCEL_B
  const name = which === 'a' ? 'xcagi-quickstart-sample-a.xlsx' : 'xcagi-quickstart-sample-b.xlsx'
  await injectExcelAnalyzeSample(url, name)
}

export async function runQuickStartWordDemo(): Promise<void> {
  const file = await fetchTutorialSampleFile(TUTORIAL_QUICKSTART_WORD, 'xcagi-quickstart-sample.docx')
  const { ok, summary } = await readWordSampleViaOfficePack(file)
  window.dispatchEvent(
    new CustomEvent('xcagi:tutorial-chat-line', {
      detail: {
        role: ok ? 'ai' : 'task',
        content: ok
          ? `Word 读取完成（教程样本）\n${summary.slice(0, 800)}`
          : `Word 读取未完成：${summary.slice(0, 400)}`,
      },
    }),
  )
}

export async function waitForChatContains(text: string, maxMs = 120_000): Promise<boolean> {
  const needle = String(text || '').trim()
  if (!needle) return true
  const start = Date.now()
  while (Date.now() - start < maxMs) {
    const thread = document.querySelector('#view-chat .chat-container, [data-tour="chat-thread"]')
    if (thread && (thread.textContent || '').includes(needle)) return true
    await sleep(400)
  }
  return false
}

export async function cleanupQuickStartImportDemo(): Promise<void> {
  const paths = readTutorialOfficeUploadPaths()
  if (paths.length) {
    await fetch('/api/platform-shell/office-sample-cleanup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ file_paths: paths }),
    }).catch(() => {})
  }
  clearTutorialOfficeUploadPaths()
  const btn = document.getElementById('newConversationBtn')
  btn?.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
}

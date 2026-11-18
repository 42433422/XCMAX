/**
 * 文件类型图标：扩展名 → VS Code 文件图标。
 *
 * 成熟组件复用：`vscode-icons-js`（扩展名映射）与 `@iconify-json/vscode-icons`
 * （图标数据）、`@iconify/vue`（渲染），三者均为 MIT。图标集按需动态加载成
 * 独立 chunk，不进入首屏包。
 */
import { addCollection } from '@iconify/vue'
import { DEFAULT_FILE, getIconForFile } from 'vscode-icons-js'

const VSCODE_PREFIX = 'vscode-icons:'

/** 只有业务分类、没有真实文件名时，用代表扩展名取图标。 */
const KIND_SAMPLE_FILES: Record<string, string> = {
  excel: 'file.xlsx',
  word: 'file.docx',
  csv: 'file.csv',
  pdf: 'file.pdf',
  image: 'file.png',
  powerpoint: 'file.pptx',
  markdown: 'file.md',
  text: 'file.txt',
  json: 'file.json',
  zip: 'file.zip',
}

export function fileIconName(filename: string, kind = ''): string {
  const name = String(filename || '').trim()
  const sample = KIND_SAMPLE_FILES[String(kind || '').trim().toLowerCase()] || ''
  const target = name || sample
  const icon = (target ? getIconForFile(target) : '') || DEFAULT_FILE
  return `${VSCODE_PREFIX}${icon.replace(/\.svg$/i, '').replace(/_/g, '-')}`
}

let collection: Promise<void> | null = null

/** 首次渲染文件图标时加载完整 VS Code 图标集；重复调用只加载一次。 */
export function ensureFileTypeIcons(): Promise<void> {
  if (!collection) {
    collection = import('@iconify-json/vscode-icons/icons.json')
      .then((mod) => {
        const data = (mod as { default?: unknown }).default ?? mod
        addCollection(data as Parameters<typeof addCollection>[0])
      })
      .catch(() => undefined)
  }
  return collection
}

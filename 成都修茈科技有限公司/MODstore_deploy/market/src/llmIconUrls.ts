/**
 * 厂商 SVG 图标地址（jsDelivr + simple-icons 固定版本）。
 * Simple Icons 未收录的 slug 返回 null，由 UI 用字首色块展示。
 */
import { llmUiMeta } from './llmModels'

const SIMPLE_ICONS_VER = '15.22.0'
const SIMPLE_ICONS_CDN = `https://cdn.jsdelivr.net/npm/simple-icons@${SIMPLE_ICONS_VER}/icons`
const XIAOMI_ICON_SVG = [
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">',
  '<rect width="64" height="64" rx="16" fill="#ff6900"/>',
  '<path fill="#fff" d="M18 22h5.8v20H18V22Zm9.2 0h5.5c5.1 0 7.7 2.6 7.7 7.7V42h-5.8V30.1c0-2.1-.9-3.1-3-3.1H33v15h-5.8V22Zm18.1 0H51v20h-5.7V22Z"/>',
  '</svg>',
].join('')
const XIAOMI_ICON_DATA_URL = `data:image/svg+xml,${encodeURIComponent(XIAOMI_ICON_SVG)}`

/**
 * 在 SIMPLE_ICONS_VER 下不存在对应 svg 的 slug（cdn.jsdelivr.net 返回 404）。
 * 见 simple-icons 仓库：DeepSeek 等因品牌条款未收录；Groq / Together 等部分版本缺失。
 */
const SI_MISSING_SLUGS = new Set(['deepseek', 'groq', 'togethercomputer'])

/**
 */
export function llmProviderIconImgSrc(providerId: string): string | null {
  if (providerId === 'xiaomi') return XIAOMI_ICON_DATA_URL
  const { iconSlug } = llmUiMeta(providerId)
  if (SI_MISSING_SLUGS.has(iconSlug)) return null
  return `${SIMPLE_ICONS_CDN}/${iconSlug}.svg`
}

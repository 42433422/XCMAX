/** 数据来源卡片图标：优先彩色 PNG 插画，缺失时回退单色 SVG 字形。 */

const ART_DIR = '../data-sources/icons/'

const artModules = import.meta.glob('../data-sources/icons/*.png', {
  eager: true,
  import: 'default',
}) as Record<string, string>

const glyphModules = import.meta.glob('../data-sources/icons/*.svg', {
  eager: true,
  query: '?raw',
  import: 'default',
}) as Record<string, string>

function normalize(name: string): string {
  return String(name || '').trim()
}

export function dataSourceHasArtIcon(name: string): boolean {
  const id = normalize(name)
  return Boolean(id && artModules[`${ART_DIR}${id}.png`])
}

export function dataSourceIconMarkup(name: string): string {
  const id = normalize(name)
  if (!id) return ''
  const art = artModules[`${ART_DIR}${id}.png`]
  if (art) {
    return `<img class="data-source-card-icon data-source-card-icon--art" src="${art}" alt="" loading="lazy" draggable="false">`
  }
  const svg = glyphModules[`${ART_DIR}${id}.svg`]
  if (!svg) return ''
  if (svg.includes('data-source-card-icon')) return svg
  return svg.replace('<svg', '<svg class="data-source-card-icon"')
}

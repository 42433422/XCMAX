/** 数据来源卡片内联 SVG。 */

const iconModules = import.meta.glob('../data-sources/icons/*.svg', {
  eager: true,
  query: '?raw',
  import: 'default',
}) as Record<string, string>

function iconPath(name: string): string {
  const id = String(name || '').trim()
  return `../data-sources/icons/${id}.svg`
}

export function dataSourceIconMarkup(name: string): string {
  const svg = iconModules[iconPath(name)]
  if (!svg) return ''
  if (svg.includes('data-source-card-icon')) return svg
  return svg.replace('<svg', '<svg class="data-source-card-icon"')
}

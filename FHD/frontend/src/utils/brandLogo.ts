/** 开屏 / 侧栏 / 悬浮窗共用的修茈品牌静态资源（Vite `public/startup`）。 */

export function startupAssetUrl(fileName: string): string {
  const base = String(import.meta.env.BASE_URL || '/')
  return `${base}startup/${fileName}`.replace(/([^:]\/)\/+/g, '$1')
}

/** 侧栏字标：PNG 透明底优先，JPG 兜底 */
export const BRAND_LOGO_WORDMARK_CANDIDATES: readonly string[] = [
  startupAssetUrl('xc-logo-text.png'),
  startupAssetUrl('xc-logo-text.jpg'),
  startupAssetUrl('xc-logo-base.jpg'),
]

/** 悬浮入口等小尺寸图标 */
export const BRAND_LOGO_ICON_CANDIDATES: readonly string[] = [
  startupAssetUrl('xc-logo-base.jpg'),
  startupAssetUrl('xc-logo-text.png'),
  startupAssetUrl('xc-logo-text.jpg'),
]

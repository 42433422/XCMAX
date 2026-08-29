/** Resolve a Vite `public/` asset under the current build base (for example `/admin/`). */
export function publicAssetUrl(path: string, baseUrl: string = import.meta.env.BASE_URL): string {
  const base = String(baseUrl || '/').replace(/\/+$/, '')
  const relativePath = String(path || '').replace(/^\/+/, '')
  return `${base}/${relativePath}`
}

import { xcmaxAdminApi, type MarketAdminUser } from '@/api/xcmaxAdmin'

const PAGE_SIZE = 200
const MAX_PAGES = 100

type MarketUsersPayload = {
  users: MarketAdminUser[]
  total: number | null
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}

export function extractMarketUsersPage(raw: unknown): MarketUsersPayload {
  const body = record(raw)
  const nested = record(body.data)
  const rows = Array.isArray(body.users) ? body.users : Array.isArray(nested.users) ? nested.users : []
  const rawTotal = body.total ?? nested.total
  const parsedTotal = Number(rawTotal)
  return {
    users: rows as MarketAdminUser[],
    total: Number.isFinite(parsedTotal) && parsedTotal >= 0 ? parsedTotal : null,
  }
}

/** Fetch every enterprise account; no first-page-only delivery roster is allowed. */
export async function fetchAllEnterpriseUsers(): Promise<MarketAdminUser[]> {
  const users = new Map<number, MarketAdminUser>()
  let offset = 0

  for (let pageNumber = 0; pageNumber < MAX_PAGES; pageNumber += 1) {
    const page = extractMarketUsersPage(
      await xcmaxAdminApi.listUsers(PAGE_SIZE, offset, true),
    )
    for (const user of page.users) {
      if (Number.isFinite(Number(user.id))) users.set(Number(user.id), user)
    }
    if (!page.users.length) break

    offset += page.users.length
    if (page.total !== null && offset >= page.total) break
    if (page.total === null && page.users.length < PAGE_SIZE) break

    if (pageNumber === MAX_PAGES - 1) {
      throw new Error('企业客户数量超过安全分页上限，未能完整加载')
    }
  }

  return [...users.values()]
    .filter((user) => user.is_enterprise === true)
    .sort((left, right) => String(left.company || left.username).localeCompare(
      String(right.company || right.username),
      'zh-CN',
    ))
}

import type { LevelProfileDict } from '../accountLevel'

export interface AuthTokens {
  ok?: boolean
  access_token?: string
  refresh_token?: string
  user?: {
    id: number
    username?: string
    email?: string
  }
}

/**
 * 与 modstore_server/market_api.py `api_me` 返回保持一致；
 * Java 网关可能多包一层 `{ user: {...} }`，在 `domain/accountLevel.ts#normalizeMeResponse` 处压平。
 */
export interface CurrentUser {
  id: number
  username: string
  email?: string
  phone?: string
  is_admin?: boolean
  /** ISO 字符串；后端无注册时间则为空串 */
  created_at?: string
  /** 累计经验值（整数） */
  experience?: number
  /** 后端会同时返回 `level_profile`；前端兜底使用 `buildLevelProfileDict` 计算 */
  level_profile?: LevelProfileDict
  /** 相对 API 路径，如 `/api/auth/avatar/file?v=1`；需带 Authorization 拉取 */
  avatar_url?: string | null
}

/**
 * 网关也可能直接吐 `{ user: {...} }`，保留联合类型供 store/api 调用方使用。
 */
export type MeResponse = CurrentUser | { user: CurrentUser }

/**
 * Runtime API barrel: modular `api/index` is the SSOT; legacy monolith fills unmigrated endpoints.
 */
import { api as modularApi } from './api/index'
import { legacyApi } from './api/legacyMonolith'

export const api = { ...legacyApi, ...modularApi }

export { clearAuthTokens, setTokensFromAuthResponse } from './api/index'
export * from './api/index'
export * from './application'

import { requestJson } from '../infrastructure/http/client'

/** 与主站 API 一致：携带 Bearer、Cookie、CSRF，否则 POST /api/sandbox/* 会 401/403，自动连接无效。 */
export const sandboxApi = {
  async connectHost(hostUrl: string) {
    return requestJson<Record<string, unknown>>('/api/sandbox/connect', {
      method: 'POST',
      body: JSON.stringify({ host_url: hostUrl }),
    })
  },

  async pushAndTest(hostUrl: string, modId: string) {
    return requestJson<Record<string, unknown>>('/api/sandbox/push-and-test', {
      method: 'POST',
      body: JSON.stringify({ host_url: hostUrl, mod_id: modId }),
    })
  },

  async getHostStatus() {
    return requestJson<Record<string, unknown>>('/api/sandbox/host-status')
  },
}

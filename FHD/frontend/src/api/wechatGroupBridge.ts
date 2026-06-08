export const wechatGroupBridgeApi = {
  async syncGroups(_body?: Record<string, unknown>) {
    return { success: true }
  },
  async getContactContext(_contactId: string | number, _opts?: { refresh?: boolean }) {
    return { success: true, messages: [] }
  },
}

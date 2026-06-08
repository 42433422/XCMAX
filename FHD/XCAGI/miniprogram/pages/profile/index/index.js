const app = getApp()
const api = require('../../../api/index')

Page({
  data: {
    userInfo: {},
    orderStats: { all: 0, pending: 0, shipped: 0, completed: 0 },
    unreadCount: 0,
  },

  onShow() {
    this.loadUserInfo()
    this.loadOrderStats()
    this.loadUnreadCount()
  },

  async loadUserInfo() {
    if (!app.globalData.isLoggedIn) return
    try {
      const res = await api.getUserInfo()
      if (res.success) {
        app.globalData.userInfo = res.data
        this.setData({ userInfo: res.data })
      }
    } catch (e) {}
  },

  async loadOrderStats() {
    if (!app.globalData.isLoggedIn) return
    try {
      const [allRes, pendingRes, shippedRes] = await Promise.all([
        api.getOrderList({ page_size: 1 }),
        api.getOrderList({ status: 'pending', page_size: 1 }),
        api.getOrderList({ status: 'shipped', page_size: 1 }),
      ])
      this.setData({
        'orderStats.all': allRes.success ? allRes.data.pagination.total : 0,
        'orderStats.pending': pendingRes.success ? pendingRes.data.pagination.total : 0,
        'orderStats.shipped': shippedRes.success ? shippedRes.data.pagination.total : 0,
      })
    } catch (e) {}
  },

  async loadUnreadCount() {
    try {
      const res = await api.getUnreadCount()
      if (res.success) this.setData({ unreadCount: res.data.count })
    } catch (e) {}
  },

  goInfo() { wx.navigateTo({ url: '/pages/profile/info/info' }) },
  goFavorite() { wx.navigateTo({ url: '/pages/profile/favorite/favorite' }) },
  goHistory() { wx.navigateTo({ url: '/pages/profile/history/history' }) },
  goAddress() { wx.navigateTo({ url: '/pages/address/list/list' }) },
  goMessage() { wx.navigateTo({ url: '/pages/message/list/list' }) },
  goFeedback() { wx.navigateTo({ url: '/pages/profile/feedback/feedback' }) },
  goChat() { wx.navigateTo({ url: '/pages/chat/chat' }) },
  goOrders(e) {
    const status = e.currentTarget.dataset.status
    wx.navigateTo({ url: `/pages/order/list/list?status=${status || ''}` })
  },
})

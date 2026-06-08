const api = require('../../api/index')
Page({
  data: { keyword: '', products: [], loading: false, hasSearched: false, history: [], totalCount: 0, hotWords: [
    { word: '底漆', color: '#ff4d4f' }, { word: '面漆', color: '#faad14' }, { word: '防腐涂料', color: '#1890ff' },
    { word: '环氧树脂', color: '#52c41a' }, { word: '稀释剂', color: '#722ed1' },
    { word: '固化剂', color: '#13c2c2' }, { word: '白色', color: '#eb2f96' },
  ]},
  onLoad() { this.setData({ history: wx.getStorageSync('search_history') || [] }) },
  onInput(e) { this.setData({ keyword: e.detail.value }) },
  clearInput() { this.setData({ keyword: '' }) },
  goBack() { wx.navigateBack() },

  doSearch() {
    const kw = this.data.keyword.trim()
    if (!kw) return
    let h = [...this.data.history]; h = h.filter(x => x !== kw); h.unshift(kw)
    if (h.length > 10) h = h.slice(0, 10)
    wx.setStorageSync('search_history', h)
    this.setData({ history: h, hasSearched: true, products: [], page: 1 })
    this.search(kw)
  },

  quickSearch(e) {
    this.setData({ keyword: e.currentTarget.dataset.word }); this.doSearch()
  },

  async search(keyword) {
    this.setData({ loading: true })
    try {
      const r = await api.searchProducts(keyword, 1)
      if (r.success) this.setData({ products: r.data.items || [], totalCount: r.data.pagination?.total || 0 })
    } catch (e) {}
    finally { this.setData({ loading: false }) }
  },

  clearHistory() { this.setData({ history: [] }); wx.removeStorageSync('search_history') },
  clearAndReset() { this.setData({ keyword: '', hasSearched: false, products: [] }) },
  goDetail(e) { wx.navigateTo({ url: `/pages/product/detail/detail?id=${e.currentTarget.dataset.id}` }) }
})

const api = require('../../api/index')
Page({
  data: { categories: [], products: [], currentCat: -1, page: 1 },
  onShow() { this.loadCategories(); this.loadProducts() },
  async loadCategories() { try { const r = await api.getProductCategories(); if (r.success) this.setData({ categories: r.data }) } catch(e){} },
  selectCat(e) { this.setData({ currentCat: e.currentTarget.dataset.id, page: 1, products: [] }); this.loadProducts() },
  async loadProducts() {
    const params = { page: this.data.page }
    if (this.data.currentCat >= 0) params.category = this.data.categories[this.data.currentCat]
    try { const r = await api.getProductList(params); if (r.success) this.setData({ products: [...this.data.products, ...(r.data.items||[])] }) } catch(e){}
  },
  goDetail(e) { wx.navigateTo({ url: `/pages/product/detail/detail?id=${e.currentTarget.dataset.id}` }) },
  onReachBottom() { this.setData({page:this.data.page+1}); this.loadProducts() },
})

const api = require('../../../api/index')
const app = getApp()

Page({
  data: { address: null, items: [], remark: '', summary: { productAmount: '0.00', freight: '0.00', totalAmount: '0.00' } },

  onShow() { this.loadData() },

  async loadData() {
    try {
      const [cartRes, addrRes] = await Promise.all([api.getCartList(), api.getAddressList()])
      if (cartRes.success) {
        const selectedItems = (cartRes.data.items || []).filter(i => i.selected)
        const productAmount = selectedItems.reduce((s, i) => s + Number(i.subtotal), 0).toFixed(2)
        this.setData({ items: selectedItems, summary: { ...this.data.summary, productAmount, totalAmount: productAmount } })
      }
      if (addrRes.success && addrRes.data.length > 0) {
        const defaultAddr = addrRes.data.find(a => a.is_default) || addrRes.data[0]
        this.setData({ address: defaultAddr })
      }
    } catch (e) { console.error(e) }
  },

  selectAddress() { wx.navigateTo({ url: '/pages/address/select/select' }) },

  onRemarkInput(e) { this.setData({ remark: e.detail.value }) },

  async submitOrder() {
    if (!this.data.address) { wx.showToast({ title: '请选择收货地址', icon: 'none' }); return }
    if (!this.data.items.length) { wx.showToast({ title: '没有可结算的商品', icon: 'none' }); return }
    wx.showLoading({ title: '提交中...' })
    try {
      const cartItemIds = this.data.items.map(i => i.cart_id)
      const res = await api.createOrder({
        address_id: this.data.address.id,
        remark: this.data.remark,
        cart_item_ids: cartItemIds,
      })
      wx.hideLoading()
      if (res.success) {
        wx.redirectTo({ url: `/pages/order/result/result?orderId=${res.data.order_id}&orderNo=${res.data.order_no}` })
      }
    } catch (e) { wx.hideLoading(); wx.showToast({ title: '提交失败', icon: 'none' }) }
  },
})

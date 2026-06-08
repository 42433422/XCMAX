const api = require('../../../api/index')
const { getStatusText } = require('../../../utils/util')
Page({
  data: { order: {} },
  onLoad(e) { if (e.id) this.loadDetail(e.id) },
  async loadDetail(id) {
    try {
      const r = await api.getOrderDetail(id)
      if (r.success) this.setData({ order: {...r.data, _statusText: getStatusText(r.data.status)} })
      wx.setNavigationBarTitle({ title: `订单${r.data.order_no}` })
    } catch(e){}
  }
})

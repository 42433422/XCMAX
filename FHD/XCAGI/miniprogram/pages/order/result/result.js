Page({
  data:{orderNo:''},
  onLoad(e){this.setData({orderId:e.orderId,orderNo:e.orderNo||''})},
  goOrder(){wx.redirectTo({url:`/pages/order/detail/detail?id=${this.data.orderId}`})},
  goHome(){wx.switchTab({url:'/pages/index/index'})}
})
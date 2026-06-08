const api = require('../../../api/index')
Page({
  data:{addresses:[]},
  onShow(){this.load()},
  async load(){try{const r=await api.getAddressList();if(r.success)this.setData({addresses:r.data})}catch(e){}},
  addAddr(){wx.navigateTo({url:'/pages/address/edit/edit'})},
  editAddr(e){wx.navigateTo({url:`/pages/address/edit/edit?id=${e.currentTarget.dataset.id}`})},
  chooseAddr(e){
    const pages=getCurrentPages()
    const prev=pages[pages.length-2]
    if(prev&&prev.route.includes('order/confirm')){wx.navigateBack()}
  },
  deleteAddr(e){
    const that=this
    wx.showModal({title:'确认',content:'确定删除该地址？',async success(r){if(r.confirm){try{await api.deleteAddress(e.currentTarget.dataset.id);that.load()}catch(e){}}}})
  }
})

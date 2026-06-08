const api = require('../../../api/index')
Page({data:{addresses:[]},
onShow(){this.load()},
async load(){try{const r=await api.getAddressList();if(r.success)this.setData({addresses:r.data})}catch(e){}},
selectAddr(e){const pages=getCurrentPages();const prev=pages[pages.length-2];if(prev&&prev.route.includes('order/confirm')){prev.setData({address:this.data.addresses.find(a=>a.id==e.currentTarget.dataset.id)});wx.navigateBack()}},
addNew(){wx.navigateTo({url:'/pages/address/edit/edit'})}
})

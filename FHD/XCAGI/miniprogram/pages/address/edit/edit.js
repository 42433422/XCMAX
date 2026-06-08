const api = require('../../../api/index')
Page({data:{form:{},editId:null},
onLoad(e){if(e.id){this.setData({editId:e.id});this.loadAddr(e.id)}},
async loadAddr(id){try{const r=await api.getAddressList();if(r.success){const addr=r.data.find(a=>a.id==id);if(addr)this.setData({form:addr})}}catch(e){}},
onSwitch(e){this.setData({'form.is_default':e.detail.value})},
async submitForm(e){const d=e.detail.value;if(!d.contact_name||!d.contact_phone||!d.detail_address)return wx.showToast({title:'请填写完整',icon:'none'})
try{if(this.editId){await api.updateAddress(this.editId,d)}else{await api.createAddress(d)}wx.showToast({title:'保存成功'});setTimeout(()=>wx.navigateBack(),1000)}catch(e){}}
})

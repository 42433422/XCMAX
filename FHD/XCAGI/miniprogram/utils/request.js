const app = getApp()

function request(options) {
  return new Promise((resolve, reject) => {
    const header = {
      'Content-Type': 'application/json',
    }
    if (app.globalData.token && !options.noAuth) {
      header['Authorization'] = `Bearer ${app.globalData.token}`
    }

    wx.request({
      url: `${app.globalData.baseUrl}${options.url}`,
      method: options.method || 'GET',
      data: options.data,
      header: header,
      success(res) {
        if (res.statusCode === 401) {
          app.clearToken()
          wx.reLaunch({ url: '/pages/index/index' })
          reject({ code: 401, message: '登录已过期' })
          return
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
        } else {
          reject(res.data || { message: '请求失败' })
        }
      },
      fail(err) {
        wx.showToast({ title: '网络错误', icon: 'none' })
        reject(err)
      }
    })
  })
}

function get(url, data) {
  return request({ url, method: 'GET', data })
}

function post(url, data) {
  return request({ url, method: 'POST', data })
}

function put(url, data) {
  return request({ url, method: 'PUT', data })
}

function del(url, data) {
  return request({ url, method: 'DELETE', data })
}

module.exports = { request, get, post, put, del }

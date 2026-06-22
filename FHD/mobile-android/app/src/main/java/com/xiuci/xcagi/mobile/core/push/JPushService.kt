package com.xiuci.xcagi.mobile.core.push

import cn.jpush.android.service.JCommonService

/**
 * JPush SDK 5.x 要求的 Service 入口。
 *
 * JPush SDK 5.x 起将推送长连接与消息分发放在 JCommonService 中运行，
 * 开发者必须提供一个继承 JCommonService 的 Service 并在 AndroidManifest.xml 注册，
 * 否则 SDK 报错 "missing required service: cn.jpush.android.service.JCommonService"
 * 且推送通道无法建立。
 *
 * 该 Service 由 SDK 内部调度，无需开发者实现任何方法。
 */
class JPushService : JCommonService()

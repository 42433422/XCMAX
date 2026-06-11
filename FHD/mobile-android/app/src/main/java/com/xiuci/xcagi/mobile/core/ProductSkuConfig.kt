package com.xiuci.xcagi.mobile.core

import com.xiuci.xcagi.mobile.BuildConfig

/** 安装包 SKU：与桌面 personal / enterprise 对齐。 */
object ProductSkuConfig {
    val sku: String
        get() = BuildConfig.PRODUCT_SKU

    val isEnterprise: Boolean
        get() = effectiveSku == "enterprise"

    val isPersonal: Boolean
        get() = effectiveSku == "personal"

    /** 个人版隐藏 ERP / 审批等企业向底部导航。 */
    val showsEnterpriseNav: Boolean
        get() = isEnterprise

    val accountKind: String
        get() = if (isEnterprise) "enterprise" else "personal"

    val displayEditionLabel: String
        get() = if (isEnterprise) "企业版" else "个人版"

    /** 运行时有效 SKU：优先使用后端返回值（防止装错 flavor）， 兜底使用编译时 BuildConfig 值。 */
    var remoteSku: String = ""
        internal set

    private val effectiveSku: String
        get() = remoteSku.ifBlank { sku }
}

# XCAGI FastAPI

**版本**: 5.0.0

XCAGI 智能助手系统 - FastAPI 版本

## 📋 目录

- [AI分析](#ai分析)
  - [POST /api/ai/analyze/analyze](#post--api-ai-analyze-analyze) - AI综合分析
  - [POST /api/ai/analyze/compare](#post--api-ai-analyze-compare) - AI对比分析
  - [POST /api/ai/analyze/image](#post--api-ai-analyze-image) - AI图像分析
  - [POST /api/ai/analyze/sentiment](#post--api-ai-analyze-sentiment) - 情感分析
  - [POST /api/ai/analyze/summary](#post--api-ai-analyze-summary) - 文本摘要
  - [POST /api/ai/analyze/text](#post--api-ai-analyze-text) - AI文本分析
- [AI聊天](#ai聊天)
  - [POST /api/ai/approval/approve](#post--api-ai-approval-approve) - 审批通过
  - [GET /api/ai/approval/pending](#get--api-ai-approval-pending) - 待审批列表
  - [POST /api/ai/approval/reject](#post--api-ai-approval-reject) - 审批拒绝
  - [POST /api/ai/approval/request](#post--api-ai-approval-request) - 审批请求
  - [POST /api/ai/chat](#post--api-ai-chat) - AI聊天（专业版）
  - [POST /api/ai/chat-unified](#post--api-ai-chat-unified) - 统一聊天（普通版+专业版）
  - [POST /api/ai/chat-unified/batch](#post--api-ai-chat-unified-batch) - 统一批量聊天（兼容路径）
  - [POST /api/ai/chat/batch](#post--api-ai-chat-batch) - 批量聊天（专业版）
  - [POST /api/ai/chat/stream](#post--api-ai-chat-stream) - 流式聊天
  - [POST /api/ai/chat/v2](#post--api-ai-chat-v2) - AI聊天V2（兼容路径）
  - [POST /api/ai/chat/v2/batch](#post--api-ai-chat-v2-batch) - 批量聊天V2（兼容路径）
  - [GET /api/ai/config](#get--api-ai-config) - 获取AI配置
  - [GET /api/ai/config/approval](#get--api-ai-config-approval) - 获取审批配置
  - [POST /api/ai/config/approval](#post--api-ai-config-approval) - 设置审批配置
  - [GET /api/ai/context](#get--api-ai-context) - 获取对话上下文
  - [POST /api/ai/context/clear](#post--api-ai-context-clear) - 清除对话上下文
  - [POST /api/ai/conversation/new](#post--api-ai-conversation-new) - 新建对话
  - [POST /api/ai/file/analyze](#post--api-ai-file-analyze) - 文件分析
  - [POST /api/ai/intent/test](#post--api-ai-intent-test) - 意图测试
  - [GET /api/ai/kitten/business-snapshot](#get--api-ai-kitten-business-snapshot) - 业务快照
  - [GET /api/ai/kitten/charts/{chart_type}](#get--api-ai-kitten-charts-{chart-type}) - 图表数据
  - [POST /api/ai/kitten/financial/report](#post--api-ai-kitten-financial-report) - 财务报表
  - [POST /api/ai/kitten/report/export](#post--api-ai-kitten-report-export) - 报表导出
  - [GET /api/ai/kitten/saved/list](#get--api-ai-kitten-saved-list) - 已保存分析列表
  - [GET /api/ai/kitten/saved/{analysis_id}](#get--api-ai-kitten-saved-{analysis-id}) - 获取已保存分析
  - [DELETE /api/ai/kitten/saved/{analysis_id}](#delete--api-ai-kitten-saved-{analysis-id}) - 删除已保存分析
  - [GET /api/ai/kitten/saved/{analysis_id}/export](#get--api-ai-kitten-saved-{analysis-id}-export) - 导出已保存分析
  - [POST /api/ai/qclaw/openclaw/chat](#post--api-ai-qclaw-openclaw-chat) - OpenClaw聊天
  - [POST /api/ai/qclaw/openclaw/config](#post--api-ai-qclaw-openclaw-config) - OpenClaw配置
  - [GET /api/ai/qclaw/panel](#get--api-ai-qclaw-panel) - QClaw面板
  - [GET /api/ai/qclaw/routes](#get--api-ai-qclaw-routes) - QClaw路由列表
  - [POST /api/ai/qclaw/test-route](#post--api-ai-qclaw-test-route) - QClaw测试路由
  - [POST /api/ai/qclaw/wechat-gateway](#post--api-ai-qclaw-wechat-gateway) - QClaw微信网关
  - [POST /api/ai/qclaw/whitelist](#post--api-ai-qclaw-whitelist) - QClaw白名单更新
  - [POST /api/ai/sqlite/import_unit_products](#post--api-ai-sqlite-import-unit-products) - 导入单位产品
  - [GET /api/ai/test](#get--api-ai-test) - AI服务测试
  - [POST /api/ai/unified_chat](#post--api-ai-unified-chat) - 统一聊天（兼容路径）
  - [POST /api/ai/unified_chat/batch](#post--api-ai-unified-chat-batch) - 统一批量聊天
- [AI解析](#ai解析)
  - [POST /api/ai/parse/batch](#post--api-ai-parse-batch) - AI批量解析
  - [POST /api/ai/parse/customer](#post--api-ai-parse-customer) - AI解析客户
  - [POST /api/ai/parse/extract-fields](#post--api-ai-parse-extract-fields) - AI字段提取
  - [POST /api/ai/parse/order](#post--api-ai-parse-order) - AI解析订单
  - [POST /api/ai/parse/product](#post--api-ai-parse-product) - AI解析产品
  - [POST /api/ai/parse/shipment](#post--api-ai-parse-shipment) - AI解析发货单
- [Excel处理](#excel处理)
  - [POST /api/excel/extract](#post--api-excel-extract) - Excel数据提取
  - [POST /api/excel/extract/logs](#post--api-excel-extract-logs) - 获取提取日志
  - [POST /api/excel/templates/create](#post--api-excel-templates-create) - 创建Excel模板
  - [GET /api/excel/templates/list](#get--api-excel-templates-list) - 获取Excel模板列表
  - [GET /api/excel/templates/{template_id}](#get--api-excel-templates-{template-id}) - 获取Excel模板详情
  - [DELETE /api/excel/templates/{template_id}](#delete--api-excel-templates-{template-id}) - 删除Excel模板
  - [POST /api/excel/upload](#post--api-excel-upload) - 上传Excel文件
  - [POST /api/excel/vector/index](#post--api-excel-vector-index) - 创建向量索引
  - [GET /api/excel/vector/indices](#get--api-excel-vector-indices) - 获取向量索引列表
  - [DELETE /api/excel/vector/indices/{index_id}](#delete--api-excel-vector-indices-{index-id}) - 删除向量索引
  - [POST /api/excel/vector/search](#post--api-excel-vector-search) - 向量检索
- [MOD 商店](#mod-商店)
  - [GET /api/mod-store/mod-store/catalog](#get--api-mod-store-mod-store-catalog) - 获取 MOD 目录
  - [GET /api/mod-store/mod-store/dependencies](#get--api-mod-store-mod-store-dependencies) - 解析依赖关系
  - [POST /api/mod-store/mod-store/index/rebuild](#post--api-mod-store-mod-store-index-rebuild) - 重建索引
  - [POST /api/mod-store/mod-store/install](#post--api-mod-store-mod-store-install) - 安装 MOD
  - [GET /api/mod-store/mod-store/mod/{mod_id}/details](#get--api-mod-store-mod-store-mod-{mod-id}-details) - MOD 详情
  - [POST /api/mod-store/mod-store/mod/{mod_id}/rate](#post--api-mod-store-mod-store-mod-{mod-id}-rate) - 评分 MOD
  - [GET /api/mod-store/mod-store/package/{mod_id}](#get--api-mod-store-mod-store-package-{mod-id}) - 获取 MOD 包信息
  - [DELETE /api/mod-store/mod-store/package/{package_file}](#delete--api-mod-store-mod-store-package-{package-file}) - 删除 MOD 包
  - [POST /api/mod-store/mod-store/package/{package_file}/download](#post--api-mod-store-mod-store-package-{package-file}-download) - 下载 MOD 包
  - [GET /api/mod-store/mod-store/popular](#get--api-mod-store-mod-store-popular) - 热门 MOD
  - [GET /api/mod-store/mod-store/recent](#get--api-mod-store-mod-store-recent) - 最新 MOD
  - [GET /api/mod-store/mod-store/search](#get--api-mod-store-mod-store-search) - 搜索 MOD
  - [POST /api/mod-store/mod-store/uninstall](#post--api-mod-store-mod-store-uninstall) - 卸载 MOD
  - [POST /api/mod-store/mod-store/update](#post--api-mod-store-mod-store-update) - 更新 MOD
  - [GET /api/mod-store/mod-store/updates](#get--api-mod-store-mod-store-updates) - 检查可用更新
  - [POST /api/mod-store/mod-store/upload](#post--api-mod-store-mod-store-upload) - 上传 MOD 包
  - [GET /api/mod-store/mod-store/validate](#get--api-mod-store-mod-store-validate) - 验证 MOD 包
- [OCR](#ocr)
  - [POST /api/ocr/batch](#post--api-ocr-batch) - 批量OCR识别
  - [GET /api/ocr/history](#get--api-ocr-history) - OCR识别历史
  - [POST /api/ocr/idcard](#post--api-ocr-idcard) - 身份证OCR识别
  - [POST /api/ocr/invoice](#post--api-ocr-invoice) - 发票OCR识别
  - [POST /api/ocr/recognize](#post--api-ocr-recognize) - 通用OCR识别
  - [GET /api/ocr/status](#get--api-ocr-status) - OCR服务状态
- [TTS语音](#tts语音)
  - [POST /api/tts/synthesize](#post--api-tts-synthesize) - 语音合成
  - [GET /api/tts/synthesize](#get--api-tts-synthesize) - 语音合成（GET）
  - [GET /api/tts/voices](#get--api-tts-voices) - 获取可用语音列表
  - [POST /api/tts/warmup](#post--api-tts-warmup) - 预热TTS服务
- [compat](#compat)
  - [GET /api/db/mode](#get--api-db-mode) - Compat Db Mode Get
  - [POST /api/db/mode](#post--api-db-mode) - Compat Db Mode Post
  - [POST /api/db/reset-test](#post--api-db-reset-test) - Compat Db Reset Test
  - [GET /api/preferences](#get--api-preferences) - Get Preferences
  - [POST /api/preferences](#post--api-preferences) - Set Preference
  - [GET /api/printers](#get--api-printers) - Compat Printers List
  - [POST /api/state/client-mods-off](#post--api-state-client-mods-off) - Xcagi Client Mods Off
- [产品管理](#产品管理)
  - [POST /api/products/add](#post--api-products-add) - 添加产品
  - [POST /api/products/batch](#post--api-products-batch) - 批量创建产品
  - [POST /api/products/batch-delete](#post--api-products-batch-delete) - 批量删除产品
  - [GET /api/products/categories/list](#get--api-products-categories-list) - 获取分类列表
  - [POST /api/products/create](#post--api-products-create) - 创建产品
  - [POST /api/products/delete](#post--api-products-delete) - 删除产品（POST兼容）
  - [POST /api/products/export](#post--api-products-export) - 导出产品
  - [GET /api/products/export.docx](#get--api-products-export.docx) - 导出 Word 报价表（路径含扩展名，兼容旧链接）
  - [GET /api/products/export.docx/](#get--api-products-export.docx-) - 导出 Word 报价表（路径含扩展名，兼容旧链接）
  - [GET /api/products/export.xlsx](#get--api-products-export.xlsx) - 导出产品Excel
  - [POST /api/products/import](#post--api-products-import) - 导入产品
  - [GET /api/products/list](#get--api-products-list) - 获取产品列表
  - [GET /api/products/price-list-export](#get--api-products-price-list-export) - 导出 Word 报价表（424/模板.docx）
  - [GET /api/products/price-list-export/](#get--api-products-price-list-export-) - 导出 Word 报价表（424/模板.docx）
  - [GET /api/products/price-list-template-preview](#get--api-products-price-list-template-preview) - 价格表 Word 模板首表预览（与 price-list-export 同源）
  - [GET /api/products/price-list-template-preview/](#get--api-products-price-list-template-preview-) - 价格表 Word 模板首表预览（与 price-list-export 同源）
  - [GET /api/products/product_names](#get--api-products-product-names) - 获取产品名称列表
  - [GET /api/products/product_names/search](#get--api-products-product-names-search) - 搜索产品名称
  - [GET /api/products/search/{keyword}](#get--api-products-search-{keyword}) - 搜索产品
  - [GET /api/products/units](#get--api-products-units) - 获取单位列表
  - [POST /api/products/update](#post--api-products-update) - 更新产品（POST兼容）
  - [GET /api/products/{product_id}](#get--api-products-{product-id}) - 获取产品详情
  - [PUT /api/products/{product_id}](#put--api-products-{product-id}) - 更新产品（PUT）
  - [DELETE /api/products/{product_id}](#delete--api-products-{product-id}) - 删除产品
- [价格表](#价格表)
  - [GET /api/price-list/download](#get--api-price-list-download) - Download Price List
  - [POST /api/price-list/generate](#post--api-price-list-generate) - Generate Price List
  - [POST /api/price-list/print](#post--api-price-list-print) - Print Price List
- [会话](#会话)
  - [POST /api/conversations/export](#post--api-conversations-export) - 导出会话
  - [POST /api/conversations/feedback](#post--api-conversations-feedback) - 会话反馈
  - [GET /api/conversations/list](#get--api-conversations-list) - 获取会话列表（兼容路径）
  - [POST /api/conversations/message](#post--api-conversations-message) - 发送会话消息
  - [POST /api/conversations/search](#post--api-conversations-search) - 搜索会话
  - [GET /api/conversations/sessions](#get--api-conversations-sessions) - 获取会话列表
  - [POST /api/conversations/sessions/clear](#post--api-conversations-sessions-clear) - 清除所有会话
  - [GET /api/conversations/stats](#get--api-conversations-stats) - 会话统计
  - [GET /api/conversations/{conversation_id}](#get--api-conversations-{conversation-id}) - 获取会话详情
  - [DELETE /api/conversations/{conversation_id}](#delete--api-conversations-{conversation-id}) - 删除会话
- [传统模式](#传统模式)
  - [GET /api/traditional-mode/customers](#get--api-traditional-mode-customers) - 传统模式客户列表
  - [POST /api/traditional-mode/delete](#post--api-traditional-mode-delete) - 删除文件或文件夹
  - [GET /api/traditional-mode/download](#get--api-traditional-mode-download) - 下载文件
  - [POST /api/traditional-mode/induct](#post--api-traditional-mode-induct) - 手动归纳
  - [GET /api/traditional-mode/list](#get--api-traditional-mode-list) - 列出目录（相对工作区根）
  - [POST /api/traditional-mode/mkdir](#post--api-traditional-mode-mkdir) - 新建文件夹
  - [POST /api/traditional-mode/product/add](#post--api-traditional-mode-product-add) - 传统模式手动添加产品
  - [POST /api/traditional-mode/product/batch-add](#post--api-traditional-mode-product-batch-add) - 传统模式批量添加产品
  - [GET /api/traditional-mode/products](#get--api-traditional-mode-products) - 传统模式产品列表
  - [GET /api/traditional-mode/read](#get--api-traditional-mode-read) - 读取文件
  - [POST /api/traditional-mode/rename](#post--api-traditional-mode-rename) - 重命名
  - [POST /api/traditional-mode/shipment/create](#post--api-traditional-mode-shipment-create) - 传统模式创建发货单
  - [GET /api/traditional-mode/stats](#get--api-traditional-mode-stats) - 传统模式统计
  - [POST /api/traditional-mode/upload](#post--api-traditional-mode-upload) - 上传文件到指定目录
  - [GET /api/traditional-mode/watch](#get--api-traditional-mode-watch) - 目录变更流（text/event-stream）
  - [POST /api/traditional-mode/write](#post--api-traditional-mode-write) - 写入文件
- [健康检查](#健康检查)
  - [GET /api/health](#get--api-health) - 健康检查
  - [GET /api/live](#get--api-live) - 存活检查
  - [GET /api/ready](#get--api-ready) - 就绪检查
- [其他](#其他)
  - [POST /api/context](#post--api-context) - 获取上下文
  - [POST /api/context/update](#post--api-context-update) - 更新上下文
  - [GET /api/db-tools](#get--api-db-tools) - 工具表目录（别名，供 ToolsView 优先请求）
  - [GET /api/industries](#get--api-industries) - 获取行业列表
  - [GET /api/industries/current](#get--api-industries-current) - 获取当前行业
  - [GET /api/industries/{industry_id}](#get--api-industries-{industry-id}) - 获取行业详情
  - [POST /api/manual-induct](#post--api-manual-induct) - 手动归纳
  - [GET /api/mods/list](#get--api-mods-list) - 获取模块列表
  - [POST /api/mods/toggle](#post--api-mods-toggle) - 切换模块
  - [GET /api/settings](#get--api-settings) - 获取设置
  - [POST /api/settings](#post--api-settings) - 保存设置
  - [POST /api/skills/execute](#post--api-skills-execute) - 执行技能
  - [GET /api/skills/list](#get--api-skills-list) - 获取技能列表
  - [GET /api/state](#get--api-state) - 获取应用状态
  - [POST /api/state/update](#post--api-state-update) - 更新应用状态
  - [GET /api/system/config](#get--api-system-config) - 获取系统配置 (兼容)
  - [GET /api/system/industries](#get--api-system-industries) - 获取行业列表 (兼容)
  - [GET /api/system/industry](#get--api-system-industry) - 获取当前行业 (兼容)
  - [POST /api/system/industry](#post--api-system-industry) - 设置当前行业 (兼容)
  - [GET /api/system/industry/{industry_id}](#get--api-system-industry-{industry-id}) - 获取行业详情 (兼容)
  - [GET /api/system/mode](#get--api-system-mode) - 获取系统模式
  - [POST /api/system/mode](#post--api-system-mode) - 设置系统模式
  - [GET /api/templates/list](#get--api-templates-list) - 获取模板列表
  - [GET /api/templates/{template_id}](#get--api-templates-{template-id}) - 获取模板详情
  - [GET /api/tool-categories](#get--api-tool-categories) - 工具分类列表
  - [GET /api/tools](#get--api-tools) - 工具表目录（与前端工具页、Flask 测试对齐）
  - [POST /api/tools/execute](#post--api-tools-execute) - 执行工具
  - [POST /api/upload](#post--api-upload) - 文件上传
- [原材料](#原材料)
  - [GET /api/materials](#get--api-materials) - 兼容：原材料列表（同 /list，供 MaterialsView GET /api/materials）
  - [POST /api/materials](#post--api-materials) - 兼容：创建原材料（同 /create）
  - [POST /api/materials/batch-delete](#post--api-materials-batch-delete) - 批量删除原材料
  - [GET /api/materials/categories/list](#get--api-materials-categories-list) - 获取原材料分类
  - [POST /api/materials/create](#post--api-materials-create) - 创建原材料
  - [POST /api/materials/import](#post--api-materials-import) - 导入原材料
  - [GET /api/materials/list](#get--api-materials-list) - 获取原材料列表
  - [POST /api/materials/{material_id}](#post--api-materials-{material-id}) - 兼容：更新原材料（MaterialsView 使用 POST）
  - [GET /api/materials/{material_id}](#get--api-materials-{material-id}) - 获取原材料详情
  - [PUT /api/materials/{material_id}](#put--api-materials-{material-id}) - 更新原材料
  - [DELETE /api/materials/{material_id}](#delete--api-materials-{material-id}) - 删除原材料
- [发货管理](#发货管理)
  - [POST /api/shipment/shipment/generate](#post--api-shipment-shipment-generate) - 生成发货单
  - [POST /api/shipment/shipment/generate-batch](#post--api-shipment-shipment-generate-batch) - 批量生成发货单
  - [POST /api/shipment/shipment/print](#post--api-shipment-shipment-print) - 打印发货单
  - [POST /api/shipment/shipment/print/cancel](#post--api-shipment-shipment-print-cancel) - 取消打印任务
  - [POST /api/shipment/shipment/print/label](#post--api-shipment-shipment-print-label) - 打印标签
  - [GET /api/shipment/shipment/print/status/{print_job_id}](#get--api-shipment-shipment-print-status-{print-job-id}) - 查询打印状态
  - [GET /api/shipment/shipment/sequence/sequence/get](#get--api-shipment-shipment-sequence-sequence-get) - 获取订单号序列
  - [POST /api/shipment/shipment/sequence/sequence/reset](#post--api-shipment-shipment-sequence-sequence-reset) - 重置订单号序列
  - [POST /api/shipment/shipment/sequence/sequence/set](#post--api-shipment-shipment-sequence-sequence-set) - 设置订单号序列
  - [GET /api/shipment/shipment/shipment-records/records](#get--api-shipment-shipment-shipment-records-records) - 获取发货记录列表
  - [PATCH /api/shipment/shipment/shipment-records/records](#patch--api-shipment-shipment-shipment-records-records) - 更新发货记录
  - [DELETE /api/shipment/shipment/shipment-records/records](#delete--api-shipment-shipment-shipment-records-records) - 删除发货记录
  - [GET /api/shipment/shipment/shipment-records/records/statistics](#get--api-shipment-shipment-shipment-records-records-statistics) - 获取发货统计
  - [GET /api/shipment/shipment/shipment-records/records/units](#get--api-shipment-shipment-shipment-records-records-units) - 获取发货记录单位列表
  - [GET /api/shipment/shipment/shipment-records/records/{record_id}](#get--api-shipment-shipment-shipment-records-records-{record-id}) - 获取发货记录详情
- [媒体](#媒体)
  - [GET /api/media/images](#get--api-media-images) - 获取图片列表
  - [POST /api/media/upload](#post--api-media-upload) - 上传媒体文件
  - [GET /api/media/videos](#get--api-media-videos) - 获取视频列表
- [客户管理](#客户管理)
  - [POST /api/customers/batch-delete](#post--api-customers-batch-delete) - 批量删除客户
  - [POST /api/customers/create](#post--api-customers-create) - 创建客户
  - [POST /api/customers/export](#post--api-customers-export) - 导出客户
  - [POST /api/customers/import](#post--api-customers-import) - 导入客户
  - [GET /api/customers/list](#get--api-customers-list) - 获取客户列表
  - [GET /api/customers/search/{keyword}](#get--api-customers-search-{keyword}) - 搜索客户
  - [GET /api/customers/{customer_id}](#get--api-customers-{customer-id}) - 获取客户详情
  - [PUT /api/customers/{customer_id}](#put--api-customers-{customer-id}) - 更新客户
  - [DELETE /api/customers/{customer_id}](#delete--api-customers-{customer-id}) - 删除客户
- [小程序](#小程序)
  - [POST /api/mp/v1/ai/chat](#post--api-mp-v1-ai-chat) - 小程序AI聊天
  - [POST /api/mp/v1/form/submit](#post--api-mp-v1-form-submit) - 小程序表单提交
  - [POST /api/mp/v1/login](#post--api-mp-v1-login) - 小程序登录
  - [POST /api/mp/v1/message/send](#post--api-mp-v1-message-send) - 小程序消息发送
  - [POST /api/mp/v1/order/create](#post--api-mp-v1-order-create) - 小程序下单
  - [GET /api/mp/v1/order/list](#get--api-mp-v1-order-list) - 小程序订单列表
  - [POST /api/mp/v1/product/search](#post--api-mp-v1-product-search) - 小程序产品搜索
  - [GET /api/mp/v1/qrcode](#get--api-mp-v1-qrcode) - 获取小程序码
  - [POST /api/mp/v1/subscribe/send](#post--api-mp-v1-subscribe-send) - 小程序订阅消息
  - [GET /api/mp/v1/user/info](#get--api-mp-v1-user-info) - 获取小程序用户信息
- [库存管理](#库存管理)
  - [POST /api/inventory/adjust](#post--api-inventory-adjust) - 调整库存
  - [GET /api/inventory/alerts](#get--api-inventory-alerts) - 库存预警
  - [POST /api/inventory/check](#post--api-inventory-check) - 检查库存
  - [POST /api/inventory/export](#post--api-inventory-export) - 导出库存
  - [POST /api/inventory/import](#post--api-inventory-import) - 导入库存
  - [GET /api/inventory/list](#get--api-inventory-list) - 获取库存列表
  - [GET /api/inventory/locations](#get--api-inventory-locations) - 库位列表（MaterialsView 兼容）
  - [POST /api/inventory/reserve](#post--api-inventory-reserve) - 预留库存
  - [GET /api/inventory/stats](#get--api-inventory-stats) - 库存统计
  - [GET /api/inventory/transactions](#get--api-inventory-transactions) - 出入库流水（MaterialsView 兼容）
  - [GET /api/inventory/warehouses](#get--api-inventory-warehouses) - 仓库列表（MaterialsView 兼容）
- [微信](#微信)
  - [POST /api/wechat/auto-reply](#post--api-wechat-auto-reply) - 微信自动回复
  - [POST /api/wechat/callback](#post--api-wechat-callback) - 微信回调
  - [GET /api/wechat/contacts/list](#get--api-wechat-contacts-list) - 获取微信联系人列表
  - [POST /api/wechat/contacts/sync](#post--api-wechat-contacts-sync) - 同步微信联系人
  - [GET /api/wechat/contacts/{contact_id}](#get--api-wechat-contacts-{contact-id}) - 获取微信联系人详情
  - [POST /api/wechat/gateway](#post--api-wechat-gateway) - 微信网关
  - [GET /api/wechat/groups/list](#get--api-wechat-groups-list) - 获取微信群列表
  - [POST /api/wechat/groups/{group_id}/send](#post--api-wechat-groups-{group-id}-send) - 微信群发消息
  - [GET /api/wechat/menu](#get--api-wechat-menu) - 获取微信菜单
  - [POST /api/wechat/menu](#post--api-wechat-menu) - 设置微信菜单
  - [POST /api/wechat/send](#post--api-wechat-send) - 发送微信消息
  - [POST /api/wechat/send-template](#post--api-wechat-send-template) - 发送模板消息
  - [GET /api/wechat/status](#get--api-wechat-status) - 微信服务状态
- [性能监控](#性能监控)
  - [GET /api/performance/circuit-breakers](#get--api-performance-circuit-breakers) - 获取熔断器状态
  - [GET /api/performance/compensation](#get--api-performance-compensation) - 获取误差补偿状态
  - [GET /api/performance/health-check](#get--api-performance-health-check) - 全组件健康检查
  - [GET /api/performance/metrics](#get--api-performance-metrics) - 获取性能指标
  - [GET /api/performance/neuro-bus](#get--api-performance-neuro-bus) - 获取Neuro总线性能
  - [GET /api/performance/rate-limiters](#get--api-performance-rate-limiters) - 获取限流器状态
  - [GET /api/performance/sandbox](#get--api-performance-sandbox) - 获取沙盒状态
  - [GET /api/performance/sla](#get--api-performance-sla) - 获取SLA指标
  - [GET /api/performance/snapshots](#get--api-performance-snapshots) - 获取快照状态
  - [GET /api/performance/traces](#get--api-performance-traces) - 获取链路追踪
- [意图包](#意图包)
  - [GET /api/intent-packages](#get--api-intent-packages) - 获取意图包列表
  - [POST /api/intent-packages](#post--api-intent-packages) - 创建意图包
  - [PUT /api/intent-packages/{package_id}](#put--api-intent-packages-{package-id}) - 更新意图包
- [意图识别](#意图识别)
  - [POST /api/intent/feedback](#post--api-intent-feedback) - 意图反馈
  - [GET /api/intent/intents](#get--api-intent-intents) - 获取意图列表
  - [GET /api/intent/models](#get--api-intent-models) - 获取意图模型列表
  - [POST /api/intent/predict](#post--api-intent-predict) - 意图预测
  - [POST /api/intent/predict/batch](#post--api-intent-predict-batch) - 批量意图预测
  - [POST /api/intent/reload](#post--api-intent-reload) - 重载意图模型
  - [GET /api/intent/status](#get--api-intent-status) - 意图服务状态
  - [POST /api/intent/train](#post--api-intent-train) - 意图模型训练
- [打印](#打印)
  - [GET /api/print/default](#get--api-print-default) - 获取默认打印机
  - [POST /api/print/document](#post--api-print-document) - 打印文档
  - [GET /api/print/document-printer](#get--api-print-document-printer) - 获取文档打印机
  - [POST /api/print/job/create](#post--api-print-job-create) - 创建打印任务
  - [GET /api/print/job/{job_id}](#get--api-print-job-{job-id}) - 获取打印任务状态
  - [POST /api/print/job/{job_id}/cancel](#post--api-print-job-{job-id}-cancel) - 取消打印任务
  - [GET /api/print/jobs/list](#get--api-print-jobs-list) - 获取打印任务列表
  - [POST /api/print/label](#post--api-print-label) - 打印标签
  - [GET /api/print/label-printer](#get--api-print-label-printer) - 获取标签打印机
  - [GET /api/print/list_labels](#get--api-print-list-labels) - 获取标签列表
  - [POST /api/print/preview](#post--api-print-preview) - 打印预览
  - [GET /api/print/printer-selection](#get--api-print-printer-selection) - 获取打印机选择
  - [PUT /api/print/printer-selection](#put--api-print-printer-selection) - 设置打印机选择
  - [GET /api/print/printers](#get--api-print-printers) - 获取打印机列表
  - [POST /api/print/single_label](#post--api-print-single-label) - 打印单个标签
  - [GET /api/print/templates/list](#get--api-print-templates-list) - 获取打印模板列表
  - [GET /api/print/validate](#get--api-print-validate) - 验证打印服务
  - [POST /api/print/{filename}](#post--api-print-{filename}) - 按文件名打印
- [报表](#报表)
  - [POST /api/report/custom](#post--api-report-custom) - 自定义报表
  - [GET /api/report/customer](#get--api-report-customer) - 客户报表
  - [POST /api/report/export](#post--api-report-export) - 导出报表
  - [GET /api/report/inventory](#get--api-report-inventory) - 库存报表
  - [GET /api/report/overview](#get--api-report-overview) - 总览报表
  - [GET /api/report/purchase](#get--api-report-purchase) - 采购报表
  - [GET /api/report/sales](#get--api-report-sales) - 销售报表
  - [GET /api/report/shipment](#get--api-report-shipment) - 发货报表
- [控制管理](#控制管理)
  - [POST /api/control/api/control/input](#post--api-control-api-control-input) - 发送控制指令
  - [GET /api/control/api/control/input/latest](#get--api-control-api-control-input-latest) - 获取最新未处理指令
  - [POST /api/control/api/control/input/{cmd_id}/ack](#post--api-control-api-control-input-{cmd-id}-ack) - 确认指令已处理
- [模块扩展](#模块扩展)
  - [GET /api/mods/](#get--api-mods-) - 获取模块列表
  - [GET /api/mods/loading-status](#get--api-mods-loading-status) - 获取模块加载状态
  - [GET /api/mods/routes](#get--api-mods-routes) - 获取模块路由
- [模板管理](#模板管理)
  - [POST /api/templates/analyze/excel](#post--api-templates-analyze-excel) - 分析 Excel 文件
  - [POST /api/templates/analyze/grid](#post--api-templates-analyze-grid) - 提取 Excel 网格预览
  - [POST /api/templates/analyze/style-cache](#post--api-templates-analyze-style-cache) - 提取 Excel 样式缓存
  - [GET /api/templates/preview/file](#get--api-templates-preview-file) - 预览 Excel 文件
  - [GET /api/templates/preview/grid](#get--api-templates-preview-grid) - 预览 Excel 网格
  - [GET /api/templates/preview/style-cache](#get--api-templates-preview-style-cache) - 获取样式缓存
  - [GET /api/templates/validators/rules](#get--api-templates-validators-rules) - 获取校验规则
  - [GET /api/templates/validators/terms/equivalents/{term}](#get--api-templates-validators-terms-equivalents-{term}) - 获取同义词
  - [POST /api/templates/validators/terms/normalize](#post--api-templates-validators-terms-normalize) - 标准化词条
  - [POST /api/templates/validators/validate](#post--api-templates-validators-validate) - 校验模板
- [系统管理](#系统管理)
  - [POST /api/system/cache/clear](#post--api-system-cache-clear) - 清除缓存
  - [POST /api/system/config](#post--api-system-config) - 设置系统配置
  - [GET /api/system/domains](#get--api-system-domains) - 获取域列表
  - [GET /api/system/info](#get--api-system-info) - 获取系统信息
  - [GET /api/system/logs](#get--api-system-logs) - 获取系统日志
  - [GET /api/system/neuro/status](#get--api-system-neuro-status) - 获取Neuro总线状态
  - [POST /api/system/restart](#post--api-system-restart) - 重启服务
  - [POST /api/system/test-db/disable](#post--api-system-test-db-disable) - 停用测试数据库，切回真实库
  - [POST /api/system/test-db/enable](#post--api-system-test-db-enable) - 启用测试数据库 products_test.db
  - [GET /api/system/test-db/status](#get--api-system-test-db-status) - 测试数据库状态（与 SettingsView 一致）
- [蒸馏模型](#蒸馏模型)
  - [GET /api/distillation/config](#get--api-distillation-config) - 获取蒸馏配置
  - [POST /api/distillation/config](#post--api-distillation-config) - 设置蒸馏配置
  - [POST /api/distillation/data/upload](#post--api-distillation-data-upload) - 上传蒸馏数据
  - [GET /api/distillation/models](#get--api-distillation-models) - 获取蒸馏模型列表
  - [POST /api/distillation/start](#post--api-distillation-start) - 启动蒸馏任务
  - [GET /api/distillation/tasks](#get--api-distillation-tasks) - 获取蒸馏任务列表
  - [GET /api/distillation/tasks/{task_id}](#get--api-distillation-tasks-{task-id}) - 获取蒸馏任务详情
  - [POST /api/distillation/tasks/{task_id}/cancel](#post--api-distillation-tasks-{task-id}-cancel) - 取消蒸馏任务
  - [GET /api/distillation/versions](#get--api-distillation-versions) - 获取蒸馏版本列表
- [订单管理](#订单管理)
  - [GET /api/orders](#get--api-orders) - 获取订单列表
  - [DELETE /api/orders/clear-all](#delete--api-orders-clear-all) - 清除所有订单
  - [GET /api/orders/latest](#get--api-orders-latest) - 获取最新订单
  - [GET /api/orders/next_number](#get--api-orders-next-number) - 获取下一个订单号
  - [GET /api/orders/purchase-units](#get--api-orders-purchase-units) - 获取采购单位
  - [GET /api/orders/search](#get--api-orders-search) - 搜索订单
  - [GET /api/orders/{order_number}](#get--api-orders-{order-number}) - 获取订单详情
- [认证](#认证)
  - [POST /api/auth/login](#post--api-auth-login) - 用户登录
  - [POST /api/auth/logout](#post--api-auth-logout) - 用户登出
  - [GET /api/auth/me](#get--api-auth-me) - 获取当前用户信息
  - [POST /api/auth/refresh](#post--api-auth-refresh) - 刷新Token
- [采购管理](#采购管理)
  - [POST /api/purchase/batch-delete](#post--api-purchase-batch-delete) - 批量删除采购单
  - [POST /api/purchase/create](#post--api-purchase-create) - 创建采购单
  - [POST /api/purchase/export](#post--api-purchase-export) - 导出采购数据
  - [GET /api/purchase/list](#get--api-purchase-list) - 获取采购单列表
  - [POST /api/purchase/parse](#post--api-purchase-parse) - AI解析采购单
  - [GET /api/purchase/stats](#get--api-purchase-stats) - 采购统计
  - [POST /api/purchase/suppliers/list](#post--api-purchase-suppliers-list) - 获取供应商列表
  - [GET /api/purchase/{purchase_id}](#get--api-purchase-{purchase-id}) - 获取采购单详情
  - [PUT /api/purchase/{purchase_id}](#put--api-purchase-{purchase-id}) - 更新采购单
  - [DELETE /api/purchase/{purchase_id}](#delete--api-purchase-{purchase-id}) - 删除采购单
- [销售合同](#销售合同)
  - [GET /api/sales-contract/download](#get--api-sales-contract-download) - 下载销售合同(by filepath)
  - [GET /api/sales-contract/download/{filename}](#get--api-sales-contract-download-{filename}) - 下载销售合同
  - [POST /api/sales-contract/generate](#post--api-sales-contract-generate) - 生成销售合同
  - [GET /api/sales-contract/list](#get--api-sales-contract-list) - 获取销售合同列表
  - [GET /api/sales-contract/preview/{filename}](#get--api-sales-contract-preview-{filename}) - 预览销售合同
  - [POST /api/sales-contract/print](#post--api-sales-contract-print) - 打印销售合同

## AI分析

### POST /api/ai/analyze/analyze

**AI综合分析**

#### 请求体

```json
{
  "text": "string",
  "image_base64": "string",
  "analysis_type": "string",
  "user_id": "string",
  "context": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ai/analyze/compare

**AI对比分析**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/analyze/image

**AI图像分析**

#### 请求体

```json
{
  "image_base64": "string",
  "analysis_type": "string",
  "user_id": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ai/analyze/sentiment

**情感分析**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/analyze/summary

**文本摘要**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/analyze/text

**AI文本分析**

#### 请求体

```json
{
  "text": "string",
  "analysis_type": "string",
  "user_id": "string",
  "context": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## AI聊天

### POST /api/ai/approval/approve

**审批通过**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/ai/approval/pending

**待审批列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/approval/reject

**审批拒绝**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/approval/request

**审批请求**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/chat

**AI聊天（专业版）**

#### 请求体

```json
{
  "message": "string",
  "user_id": "string",
  "context": "string",
  "source": "string",
  "mode": "string",
  "file_context": "string",
  "excel_index_id": "string",
  "excel_top_k": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ai/chat-unified

**统一聊天（普通版+专业版）**

#### 请求体

```json
{
  "message": "string",
  "user_id": "string",
  "context": "string",
  "source": "string",
  "mode": "string",
  "file_context": "string",
  "excel_index_id": "string",
  "excel_top_k": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ai/chat-unified/batch

**统一批量聊天（兼容路径）**

#### 请求体

```json
{
  "messages": [
    "string"
  ],
  "user_id": "string",
  "context": "string",
  "source": "string",
  "mode": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ai/chat/batch

**批量聊天（专业版）**

#### 请求体

```json
{
  "messages": [
    "string"
  ],
  "user_id": "string",
  "context": "string",
  "source": "string",
  "mode": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ai/chat/stream

**流式聊天**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/chat/v2

**AI聊天V2（兼容路径）**

#### 请求体

```json
{
  "message": "string",
  "user_id": "string",
  "context": "string",
  "source": "string",
  "mode": "string",
  "file_context": "string",
  "excel_index_id": "string",
  "excel_top_k": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ai/chat/v2/batch

**批量聊天V2（兼容路径）**

#### 请求体

```json
{
  "messages": [
    "string"
  ],
  "user_id": "string",
  "context": "string",
  "source": "string",
  "mode": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/ai/config

**获取AI配置**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/ai/config/approval

**获取审批配置**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/config/approval

**设置审批配置**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/ai/context

**获取对话上下文**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| user_id | query | string | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ai/context/clear

**清除对话上下文**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| user_id | query | string | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ai/conversation/new

**新建对话**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/file/analyze

**文件分析**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/intent/test

**意图测试**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/ai/kitten/business-snapshot

**业务快照**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/ai/kitten/charts/{chart_type}

**图表数据**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| chart_type | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ai/kitten/financial/report

**财务报表**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/kitten/report/export

**报表导出**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/ai/kitten/saved/list

**已保存分析列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/ai/kitten/saved/{analysis_id}

**获取已保存分析**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| analysis_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### DELETE /api/ai/kitten/saved/{analysis_id}

**删除已保存分析**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| analysis_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/ai/kitten/saved/{analysis_id}/export

**导出已保存分析**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| analysis_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ai/qclaw/openclaw/chat

**OpenClaw聊天**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/qclaw/openclaw/config

**OpenClaw配置**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/ai/qclaw/panel

**QClaw面板**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/ai/qclaw/routes

**QClaw路由列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/qclaw/test-route

**QClaw测试路由**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/qclaw/wechat-gateway

**QClaw微信网关**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/qclaw/whitelist

**QClaw白名单更新**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/sqlite/import_unit_products

**导入单位产品**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/ai/test

**AI服务测试**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/unified_chat

**统一聊天（兼容路径）**

#### 请求体

```json
{
  "message": "string",
  "user_id": "string",
  "context": "string",
  "source": "string",
  "mode": "string",
  "file_context": "string",
  "excel_index_id": "string",
  "excel_top_k": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ai/unified_chat/batch

**统一批量聊天**

#### 请求体

```json
{
  "messages": [
    "string"
  ],
  "user_id": "string",
  "context": "string",
  "source": "string",
  "mode": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## AI解析

### POST /api/ai/parse/batch

**AI批量解析**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/parse/customer

**AI解析客户**

#### 请求体

```json
{
  "text": "string",
  "user_id": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ai/parse/extract-fields

**AI字段提取**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ai/parse/order

**AI解析订单**

#### 请求体

```json
{
  "text": "string",
  "user_id": "string",
  "context": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ai/parse/product

**AI解析产品**

#### 请求体

```json
{
  "text": "string",
  "user_id": "string",
  "context": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ai/parse/shipment

**AI解析发货单**

#### 请求体

```json
{
  "text": "string",
  "user_id": "string",
  "context": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## Excel处理

### POST /api/excel/extract

**Excel数据提取**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/excel/extract/logs

**获取提取日志**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/excel/templates/create

**创建Excel模板**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/excel/templates/list

**获取Excel模板列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/excel/templates/{template_id}

**获取Excel模板详情**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| template_id | path | integer | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### DELETE /api/excel/templates/{template_id}

**删除Excel模板**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| template_id | path | integer | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/excel/upload

**上传Excel文件**

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/excel/vector/index

**创建向量索引**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/excel/vector/indices

**获取向量索引列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### DELETE /api/excel/vector/indices/{index_id}

**删除向量索引**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| index_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/excel/vector/search

**向量检索**

#### 响应

**200** - Successful Response

```json
string
```

---

## MOD 商店

### GET /api/mod-store/mod-store/catalog

**获取 MOD 目录**

获取所有可用 MOD 的目录列表

返回已安装和未安装的 MOD 信息

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/mod-store/mod-store/dependencies

**解析依赖关系**

解析 MOD 包的依赖关系

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| package_file | query | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/mod-store/mod-store/index/rebuild

**重建索引**

重建 MOD 索引（管理员操作）

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/mod-store/mod-store/install

**安装 MOD**

安装已上传的 MOD 包

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/mod-store/mod-store/mod/{mod_id}/details

**MOD 详情**

获取 MOD 详细信息（包括统计和评分）

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| mod_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/mod-store/mod-store/mod/{mod_id}/rate

**评分 MOD**

对 MOD 进行评分

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| mod_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/mod-store/mod-store/package/{mod_id}

**获取 MOD 包信息**

获取指定 MOD 包的详细信息

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| mod_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### DELETE /api/mod-store/mod-store/package/{package_file}

**删除 MOD 包**

从商店中删除 MOD 包（不影响已安装的 MOD）

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| package_file | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/mod-store/mod-store/package/{package_file}/download

**下载 MOD 包**

下载 MOD 包文件

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| package_file | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/mod-store/mod-store/popular

**热门 MOD**

获取热门 MOD 排行榜

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| limit | query | integer | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/mod-store/mod-store/recent

**最新 MOD**

获取最新上架的 MOD

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| limit | query | integer | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/mod-store/mod-store/search

**搜索 MOD**

搜索 MOD

- q: 搜索关键词（名称、描述、作者）
- author: 按作者筛选
- installed: 是否只显示已安装的 MOD

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| q | query |  | 否 |  |
| author | query |  | 否 |  |
| installed | query | boolean | 否 |  |
| limit | query | integer | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/mod-store/mod-store/uninstall

**卸载 MOD**

卸载已安装的 MOD

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/mod-store/mod-store/update

**更新 MOD**

更新已安装的 MOD

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/mod-store/mod-store/updates

**检查可用更新**

检查已安装 MOD 的可用更新

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/mod-store/mod-store/upload

**上传 MOD 包**

上传 MOD 包到商店

- 支持 .xcmod 格式
- 自动验证包完整性
- 可选择是否立即激活

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/mod-store/mod-store/validate

**验证 MOD 包**

验证 MOD 包的有效性

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| package_file | query | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## OCR

### POST /api/ocr/batch

**批量OCR识别**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/ocr/history

**OCR识别历史**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/ocr/idcard

**身份证OCR识别**

#### 请求体

```json
{
  "image_base64": "string",
  "side": "front",
  "user_id": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ocr/invoice

**发票OCR识别**

#### 请求体

```json
{
  "image_base64": "string",
  "user_id": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/ocr/recognize

**通用OCR识别**

#### 请求体

```json
{
  "image_base64": "string",
  "ocr_type": "string",
  "user_id": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/ocr/status

**OCR服务状态**

#### 响应

**200** - Successful Response

```json
string
```

---

## TTS语音

### POST /api/tts/synthesize

**语音合成**

#### 请求体

```json
{
  "text": "string",
  "voice": "string",
  "speaker_id": "string",
  "lang": "zh",
  "rate": "string",
  "pitch": "string"
}
```

#### 响应

**200** - Successful Response

```json
{
  "success": true,
  "message": "",
  "data": "string",
  "error": "string"
}
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/tts/synthesize

**语音合成（GET）**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| text | query | string | 是 | 要合成的文本 |
| voice | query |  | 否 | 语音类型 |
| speaker_id | query |  | 否 | 说话人ID |
| lang | query |  | 否 | 语言 |
| rate | query |  | 否 | 语速 |
| pitch | query |  | 否 | 音调 |

#### 响应

**200** - Successful Response

```json
{
  "success": true,
  "message": "",
  "data": "string",
  "error": "string"
}
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/tts/voices

**获取可用语音列表**

#### 响应

**200** - Successful Response

```json
{
  "success": true,
  "message": "",
  "data": "string",
  "error": "string"
}
```

---

### POST /api/tts/warmup

**预热TTS服务**

#### 响应

**200** - Successful Response

```json
{
  "success": true,
  "message": "",
  "data": "string",
  "error": "string"
}
```

---

## compat

### GET /api/db/mode

**Compat Db Mode Get**

兼容独立后端 GET /api/db/mode；映射到 TestDbManager 的测试库开关。

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/db/mode

**Compat Db Mode Post**

兼容独立后端 POST /api/db/mode。

#### 请求体

```json
{
  "mode": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/db/reset-test

**Compat Db Reset Test**

兼容独立后端 POST /api/db/reset-test。

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/preferences

**Get Preferences**

获取用户偏好设置

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| user_id | query | string | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/preferences

**Set Preference**

设置用户偏好

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/printers

**Compat Printers List**

与 GET /api/print/printers 等价；兼容旧前端与 Vite 中对 /api/printers 的代理登记。

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/state/client-mods-off

**Xcagi Client Mods Off**

frontend/src/utils/apiBase.ts — syncClientModsStateToBackend

#### 响应

**200** - Successful Response

```json
string
```

---

## 产品管理

### POST /api/products/add

**添加产品**

#### 请求体

```json
{
  "unit_name": "string",
  "product_name": "string",
  "price": 0.0,
  "description": "string",
  "model_number": "string",
  "specification": "string",
  "category": "string",
  "brand": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/products/batch

**批量创建产品**

#### 请求体

```json
{
  "products": [
    "{...}"
  ]
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/products/batch-delete

**批量删除产品**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/products/categories/list

**获取分类列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/products/create

**创建产品**

#### 请求体

```json
{
  "unit_name": "string",
  "product_name": "string",
  "price": 0.0,
  "description": "string",
  "model_number": "string",
  "specification": "string",
  "category": "string",
  "brand": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/products/delete

**删除产品（POST兼容）**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/products/export

**导出产品**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/products/export.docx

**导出 Word 报价表（路径含扩展名，兼容旧链接）**

与独立 ``backend.http_app`` 中 ``/api/products/price-list-export`` 一致。
必须在 ``/{product_id}`` 之前注册，否则会被动态段吞掉并 404。

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| unit | query |  | 否 |  |
| keyword | query |  | 否 |  |
| date | query |  | 否 | 报价日期 YYYY-MM-DD，默认当天 |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/products/export.docx/

**导出 Word 报价表（路径含扩展名，兼容旧链接）**

与独立 ``backend.http_app`` 中 ``/api/products/price-list-export`` 一致。
必须在 ``/{product_id}`` 之前注册，否则会被动态段吞掉并 404。

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| unit | query |  | 否 |  |
| keyword | query |  | 否 |  |
| date | query |  | 否 | 报价日期 YYYY-MM-DD，默认当天 |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/products/export.xlsx

**导出产品Excel**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/products/import

**导入产品**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/products/list

**获取产品列表**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| page | query | integer | 否 |  |
| per_page | query | integer | 否 |  |
| unit_name | query |  | 否 |  |
| unit | query |  | 否 | 与 unit_name 等价，兼容前端 ?unit= |
| keyword | query |  | 否 |  |
| model_number | query |  | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/products/price-list-export

**导出 Word 报价表（424/模板.docx）**

与独立 ``backend.http_app`` 中 ``/api/products/price-list-export`` 一致。
必须在 ``/{product_id}`` 之前注册，否则会被动态段吞掉并 404。

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| unit | query |  | 否 |  |
| keyword | query |  | 否 |  |
| date | query |  | 否 | 报价日期 YYYY-MM-DD，默认当天 |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/products/price-list-export/

**导出 Word 报价表（424/模板.docx）**

与独立 ``backend.http_app`` 中 ``/api/products/price-list-export`` 一致。
必须在 ``/{product_id}`` 之前注册，否则会被动态段吞掉并 404。

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| unit | query |  | 否 |  |
| keyword | query |  | 否 |  |
| date | query |  | 否 | 报价日期 YYYY-MM-DD，默认当天 |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/products/price-list-template-preview

**价格表 Word 模板首表预览（与 price-list-export 同源）**

与 ``backend.http_app`` / ``xcagi_compat`` 中 ``/api/products/price-list-template-preview`` 一致。

#### 响应

**200** - Successful Response

```json
{}
```

---

### GET /api/products/price-list-template-preview/

**价格表 Word 模板首表预览（与 price-list-export 同源）**

与 ``backend.http_app`` / ``xcagi_compat`` 中 ``/api/products/price-list-template-preview`` 一致。

#### 响应

**200** - Successful Response

```json
{}
```

---

### GET /api/products/product_names

**获取产品名称列表**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| keyword | query |  | 否 |  |
| unit_name | query |  | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/products/product_names/search

**搜索产品名称**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| keyword | query | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/products/search/{keyword}

**搜索产品**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| keyword | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/products/units

**获取单位列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/products/update

**更新产品（POST兼容）**

#### 请求体

```json
{
  "id": "string",
  "product_name": "string",
  "price": "string",
  "description": "string",
  "model_number": "string",
  "specification": "string",
  "category": "string",
  "brand": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/products/{product_id}

**获取产品详情**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| product_id | path | integer | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### PUT /api/products/{product_id}

**更新产品（PUT）**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| product_id | path | integer | 是 |  |

#### 请求体

```json
{
  "id": "string",
  "product_name": "string",
  "price": "string",
  "description": "string",
  "model_number": "string",
  "specification": "string",
  "category": "string",
  "brand": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### DELETE /api/products/{product_id}

**删除产品**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| product_id | path | integer | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 价格表

### GET /api/price-list/download

**Download Price List**

下载价格表文件

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| filepath | query | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/price-list/generate

**Generate Price List**

生成客户价格表并打印

#### 请求体

```json
{
  "customer_name": "string",
  "products": [
    "{...}"
  ],
  "printer_name": "string"
}
```

#### 响应

**200** - Successful Response

```json
{
  "success": true,
  "filename": "string",
  "filepath": "string",
  "message": "string",
  "error": "string"
}
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/price-list/print

**Print Price List**

打印价格表

#### 请求体

```json
{
  "filename": "string",
  "printer_name": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 会话

### POST /api/conversations/export

**导出会话**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/conversations/feedback

**会话反馈**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/conversations/list

**获取会话列表（兼容路径）**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| page | query | integer | 否 |  |
| per_page | query | integer | 否 |  |
| user_id | query |  | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/conversations/message

**发送会话消息**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/conversations/search

**搜索会话**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/conversations/sessions

**获取会话列表**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| page | query | integer | 否 |  |
| per_page | query | integer | 否 |  |
| user_id | query |  | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/conversations/sessions/clear

**清除所有会话**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/conversations/stats

**会话统计**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/conversations/{conversation_id}

**获取会话详情**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| conversation_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### DELETE /api/conversations/{conversation_id}

**删除会话**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| conversation_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 传统模式

### GET /api/traditional-mode/customers

**传统模式客户列表**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| page | query | integer | 否 |  |
| per_page | query | integer | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/traditional-mode/delete

**删除文件或文件夹**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/traditional-mode/download

**下载文件**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| file | query | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/traditional-mode/induct

**手动归纳**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/traditional-mode/list

**列出目录（相对工作区根）**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| path | query | string | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/traditional-mode/mkdir

**新建文件夹**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/traditional-mode/product/add

**传统模式手动添加产品**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/traditional-mode/product/batch-add

**传统模式批量添加产品**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/traditional-mode/products

**传统模式产品列表**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| page | query | integer | 否 |  |
| per_page | query | integer | 否 |  |
| keyword | query |  | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/traditional-mode/read

**读取文件**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| file | query | string | 是 | 相对工作区根的文件路径 |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/traditional-mode/rename

**重命名**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/traditional-mode/shipment/create

**传统模式创建发货单**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/traditional-mode/stats

**传统模式统计**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/traditional-mode/upload

**上传文件到指定目录**

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/traditional-mode/watch

**目录变更流（text/event-stream）**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| path | query | string | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/traditional-mode/write

**写入文件**

#### 响应

**200** - Successful Response

```json
string
```

---

## 健康检查

### GET /api/health

**健康检查**

应用健康检查接口

返回应用状态、版本信息和框架信息

#### 响应

**200** - Successful Response

```json
{
  "status": "string",
  "timestamp": "string",
  "version": "string",
  "framework": "string"
}
```

---

### GET /api/live

**存活检查**

应用存活检查接口

检查应用是否仍在运行

#### 响应

**200** - Successful Response

```json
{
  "status": "string",
  "timestamp": "string",
  "version": "string",
  "framework": "string"
}
```

---

### GET /api/ready

**就绪检查**

应用就绪检查接口

检查应用是否准备好处理请求

#### 响应

**200** - Successful Response

```json
{
  "status": "string",
  "timestamp": "string",
  "version": "string",
  "framework": "string"
}
```

---

## 其他

### POST /api/context

**获取上下文**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/context/update

**更新上下文**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/db-tools

**工具表目录（别名，供 ToolsView 优先请求）**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/industries

**获取行业列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/industries/current

**获取当前行业**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/industries/{industry_id}

**获取行业详情**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| industry_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/manual-induct

**手动归纳**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/mods/list

**获取模块列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/mods/toggle

**切换模块**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/settings

**获取设置**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/settings

**保存设置**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/skills/execute

**执行技能**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/skills/list

**获取技能列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/state

**获取应用状态**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/state/update

**更新应用状态**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/system/config

**获取系统配置 (兼容)**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/system/industries

**获取行业列表 (兼容)**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/system/industry

**获取当前行业 (兼容)**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/system/industry

**设置当前行业 (兼容)**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/system/industry/{industry_id}

**获取行业详情 (兼容)**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| industry_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/system/mode

**获取系统模式**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/system/mode

**设置系统模式**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/templates/list

**获取模板列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/templates/{template_id}

**获取模板详情**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| template_id | path | integer | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/tool-categories

**工具分类列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/tools

**工具表目录（与前端工具页、Flask 测试对齐）**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/tools/execute

**执行工具**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/upload

**文件上传**

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 原材料

### GET /api/materials

**兼容：原材料列表（同 /list，供 MaterialsView GET /api/materials）**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| page | query | integer | 否 |  |
| per_page | query | integer | 否 |  |
| search | query |  | 否 |  |
| keyword | query |  | 否 |  |
| category | query |  | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/materials

**兼容：创建原材料（同 /create）**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/materials/batch-delete

**批量删除原材料**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/materials/categories/list

**获取原材料分类**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/materials/create

**创建原材料**

#### 请求体

```json
{
  "name": "string",
  "unit": "string",
  "specification": "string",
  "category": "string",
  "stock_quantity": 0,
  "min_quantity": 0,
  "unit_price": "string",
  "supplier": "string",
  "notes": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/materials/import

**导入原材料**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/materials/list

**获取原材料列表**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| page | query | integer | 否 |  |
| per_page | query | integer | 否 |  |
| keyword | query |  | 否 |  |
| category | query |  | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/materials/{material_id}

**兼容：更新原材料（MaterialsView 使用 POST）**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| material_id | path | integer | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/materials/{material_id}

**获取原材料详情**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| material_id | path | integer | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### PUT /api/materials/{material_id}

**更新原材料**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| material_id | path | integer | 是 |  |

#### 请求体

```json
{
  "name": "string",
  "unit": "string",
  "specification": "string",
  "category": "string",
  "stock_quantity": "string",
  "min_quantity": "string",
  "unit_price": "string",
  "supplier": "string",
  "notes": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### DELETE /api/materials/{material_id}

**删除原材料**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| material_id | path | integer | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 发货管理

### POST /api/shipment/shipment/generate

**生成发货单**

生成发货单

根据客户信息和商品列表自动生成发货单，支持自定义模板。

**功能**:
- 自动计算总金额
- 生成唯一订单号
- 支持自定义模板
- Neuro-DDD 架构处理

**请求参数**:
- `customer_name`: 客户名称（可选）
- `items`: 商品列表，每项包含 `product_id`, `quantity`, `unit_price`
- `order_text`: 订单文本描述（可选）
- `template_id`: 模板 ID（可选，默认使用系统模板）
- `notes`: 备注信息（可选）

**返回示例**:
```json
{
  "success": true,
  "shipment_id": 12345,
  "order_number": "SO20260412001",
  "created_at": "2026-04-12T10:30:00"
}
```

**错误码**:
- `400`: 请求参数错误
- `401`: 未认证
- `500`: 服务器内部错误

**安全**:
- 需要 Bearer Token 认证

#### 请求体

```json
{
  "customer_name": "string",
  "items": "string",
  "order_text": "string",
  "template_id": "string",
  "notes": "string"
}
```

#### 响应

**200** - Successful Response

```json
{
  "success": true,
  "shipment_id": "string",
  "order_number": "string",
  "created_at": "string",
  "error": "string"
}
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/shipment/shipment/generate-batch

**批量生成发货单**

批量生成发货单

一次性生成多个发货单，适用于批量导入场景。

**请求参数**:
- `shipments`: 发货单列表，每项包含 `customer_name`, `items` 等

**返回示例**:
```json
{
  "success": true,
  "results": [
    {"shipment_id": 12345, "order_number": "SO20260412001"},
    {"shipment_id": 12346, "order_number": "SO20260412002"}
  ],
  "total": 2
}
```

#### 请求体

```json
{}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/shipment/shipment/print

**打印发货单**

打印发货单

将发货单发送到指定打印机进行打印，支持标签打印和普通文档打印。

**功能**:
- 自动选择打印机
- 支持标签打印
- 支持多份打印
- 打印任务跟踪

**请求参数**:
- `shipment_id`: 发货单 ID
- `filename`: 文件名（可选，系统自动生成）
- `printer_name`: 打印机名称（可选，默认自动选择）
- `label_data`: 标签数据（可选，用于标签打印）
- `copies`: 打印份数（默认 1 份）

**返回示例**:
```json
{
  "success": true,
  "print_job_id": "PJ20260412001",
  "status": "queued",
  "message": "打印任务已创建"
}
```

**错误码**:
- `400`: 请求参数错误
- `404`: 发货单不存在
- `500`: 打印机错误

**安全**:
- 需要 Bearer Token 认证

#### 请求体

```json
{
  "shipment_id": "string",
  "filename": "string",
  "printer_name": "string",
  "label_data": "string",
  "copies": 1
}
```

#### 响应

**200** - Successful Response

```json
{
  "success": true,
  "print_job_id": "string",
  "status": "string",
  "error": "string"
}
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/shipment/shipment/print/cancel

**取消打印任务**

取消打印任务

**请求参数**:
- `print_job_id`: 打印任务 ID

**返回示例**:
```json
{
  "success": true,
  "message": "打印任务已取消"
}
```

#### 请求体

```json
{}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/shipment/shipment/print/label

**打印标签**

打印产品标签

根据产品信息生成并打印标签，支持条码、二维码等。

**请求参数**:
- `product_id`: 产品 ID
- `quantity`: 标签数量
- `label_type`: 标签类型（barcode/qr_code）
- `printer_name`: 打印机名称

**返回示例**:
```json
{
  "success": true,
  "print_job_id": "PJ20260412002",
  "labels_printed": 10
}
```

#### 请求体

```json
{}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/shipment/shipment/print/status/{print_job_id}

**查询打印状态**

查询打印任务状态

**参数**:
- `print_job_id`: 打印任务 ID

**返回示例**:
```json
{
  "success": true,
  "status": "completed",
  "progress": 100,
  "message": "打印完成"
}
```

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| print_job_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/shipment/shipment/sequence/sequence/get

**获取订单号序列**

获取当前订单号序列配置

**返回示例**:
```json
{
  "success": true,
  "sequence": {
    "current": 1001,
    "prefix": "SO",
    "date_format": "YYYYMMDD"
  }
}
```

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/shipment/shipment/sequence/sequence/reset

**重置订单号序列**

重置订单号序列

**请求参数**:
- `new_start`: 新的起始值

**注意**:
- 重置操作会影响后续订单号生成
- 需要管理员权限

**返回示例**:
```json
{
  "success": true,
  "message": "订单号序列已重置",
  "new_start": 2000
}
```

**安全**:
- 需要管理员权限

#### 请求体

```json
{}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/shipment/shipment/sequence/sequence/set

**设置订单号序列**

设置订单号序列

用于批量设置订单的发货顺序，支持自定义序列号。

**请求参数**:
- `order_ids`: 订单 ID 列表（按顺序排列）
- `sequence`: 起始序列号

**返回示例**:
```json
{
  "success": true,
  "message": "订单号序列已设置",
  "updated_count": 10
}
```

**安全**:
- 需要 Bearer Token 认证

#### 请求体

```json
{
  "order_ids": [
    0
  ],
  "sequence": 0
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/shipment/shipment/shipment-records/records

**获取发货记录列表**

分页获取发货记录列表

**查询参数**:
- `page`: 页码（从 1 开始）
- `per_page`: 每页数量（1-100）
- `unit_name`: 客户名称（可选，模糊查询）
- `start_date`: 开始日期（可选，格式：YYYY-MM-DD）
- `end_date`: 结束日期（可选，格式：YYYY-MM-DD）
- `status`: 状态（可选，pending/shipped/delivered/cancelled）

**返回示例**:
```json
{
  "success": true,
  "records": [
    {
      "id": 12345,
      "order_number": "SO20260412001",
      "customer_name": "测试客户",
      "total_amount": 2550.0,
      "status": "pending",
      "created_at": "2026-04-12T10:30:00"
    }
  ],
  "total": 100,
  "page": 1,
  "per_page": 20,
  "total_pages": 5
}
```

**安全**:
- 需要 Bearer Token 认证

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| page | query | integer | 否 | 页码 |
| per_page | query | integer | 否 | 每页数量 |
| unit_name | query |  | 否 | 客户名称 |
| start_date | query |  | 否 | 开始日期 (YYYY-MM-DD) |
| end_date | query |  | 否 | 结束日期 (YYYY-MM-DD) |
| status | query |  | 否 | 状态 |

#### 响应

**200** - Successful Response

```json
{
  "success": true,
  "records": [
    "{...}"
  ],
  "total": 0,
  "page": 1,
  "per_page": 20,
  "total_pages": 0
}
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### PATCH /api/shipment/shipment/shipment-records/records

**更新发货记录**

更新发货记录

**请求参数**:
- `record_id`: 记录 ID
- `data`: 更新数据（支持部分更新）
  - `status`: 状态（pending/shipped/delivered/cancelled）
  - `notes`: 备注
  - `tracking_number`: 物流单号
  - 其他字段

**返回示例**:
```json
{
  "success": true,
  "message": "发货记录已更新"
}
```

**安全**:
- 需要 Bearer Token 认证

#### 请求体

```json
{
  "record_id": 0,
  "data": "{...}"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### DELETE /api/shipment/shipment/shipment-records/records

**删除发货记录**

删除发货记录

**请求参数**:
- `record_id`: 记录 ID

**注意**:
- 删除操作不可恢复
- 只允许删除未发货的记录

**返回示例**:
```json
{
  "success": true,
  "message": "发货记录已删除"
}
```

**安全**:
- 需要 Bearer Token 认证

#### 请求体

```json
{
  "record_id": 0
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/shipment/shipment/shipment-records/records/statistics

**获取发货统计**

获取发货统计数据

**查询参数**:
- `start_date`: 开始日期
- `end_date`: 结束日期
- `unit_name`: 客户名称

**返回示例**:
```json
{
  "success": true,
  "statistics": {
    "total_shipments": 100,
    "total_amount": 255000.0,
    "pending_count": 10,
    "shipped_count": 80,
    "delivered_count": 10
  }
}
```

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| start_date | query |  | 否 | 开始日期 |
| end_date | query |  | 否 | 结束日期 |
| unit_name | query |  | 否 | 客户名称 |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/shipment/shipment/shipment-records/records/units

**获取发货记录单位列表**

获取所有客户列表（用于下拉选择）

**返回示例**:
```json
{
  "success": true,
  "units": [
    {"id": 1, "name": "测试客户 A"},
    {"id": 2, "name": "测试客户 B"}
  ]
}
```

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/shipment/shipment/shipment-records/records/{record_id}

**获取发货记录详情**

获取发货记录详细信息

**参数**:
- `record_id`: 发货记录 ID

**返回示例**:
```json
{
  "success": true,
  "record": {
    "id": 12345,
    "order_number": "SO20260412001",
    "customer_name": "测试客户",
    "items": [...],
    "total_amount": 2550.0,
    "status": "pending",
    "notes": "加急订单"
  }
}
```

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| record_id | path | integer | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 媒体

### GET /api/media/images

**获取图片列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/media/upload

**上传媒体文件**

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/media/videos

**获取视频列表**

#### 响应

**200** - Successful Response

```json
string
```

---

## 客户管理

### POST /api/customers/batch-delete

**批量删除客户**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/customers/create

**创建客户**

#### 请求体

```json
{
  "name": "string",
  "contact": "string",
  "phone": "string",
  "address": "string",
  "level": "string",
  "notes": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/customers/export

**导出客户**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/customers/import

**导入客户**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/customers/list

**获取客户列表**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| page | query | integer | 否 |  |
| per_page | query | integer | 否 |  |
| keyword | query |  | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/customers/search/{keyword}

**搜索客户**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| keyword | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/customers/{customer_id}

**获取客户详情**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| customer_id | path | integer | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### PUT /api/customers/{customer_id}

**更新客户**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| customer_id | path | integer | 是 |  |

#### 请求体

```json
{
  "name": "string",
  "contact": "string",
  "phone": "string",
  "address": "string",
  "level": "string",
  "notes": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### DELETE /api/customers/{customer_id}

**删除客户**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| customer_id | path | integer | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 小程序

### POST /api/mp/v1/ai/chat

**小程序AI聊天**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/mp/v1/form/submit

**小程序表单提交**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/mp/v1/login

**小程序登录**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/mp/v1/message/send

**小程序消息发送**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/mp/v1/order/create

**小程序下单**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/mp/v1/order/list

**小程序订单列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/mp/v1/product/search

**小程序产品搜索**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/mp/v1/qrcode

**获取小程序码**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/mp/v1/subscribe/send

**小程序订阅消息**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/mp/v1/user/info

**获取小程序用户信息**

#### 响应

**200** - Successful Response

```json
string
```

---

## 库存管理

### POST /api/inventory/adjust

**调整库存**

#### 请求体

```json
{
  "product_id": 0,
  "quantity": 0.0,
  "reason": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/inventory/alerts

**库存预警**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/inventory/check

**检查库存**

#### 请求体

```json
{
  "product_ids": "string",
  "product_names": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/inventory/export

**导出库存**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/inventory/import

**导入库存**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/inventory/list

**获取库存列表**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| page | query | integer | 否 |  |
| per_page | query | integer | 否 |  |
| keyword | query |  | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/inventory/locations

**库位列表（MaterialsView 兼容）**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| warehouse_id | query |  | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/inventory/reserve

**预留库存**

#### 请求体

```json
{
  "items": [
    "{...}"
  ],
  "order_id": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/inventory/stats

**库存统计**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/inventory/transactions

**出入库流水（MaterialsView 兼容）**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| page | query | integer | 否 |  |
| per_page | query | integer | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/inventory/warehouses

**仓库列表（MaterialsView 兼容）**

#### 响应

**200** - Successful Response

```json
string
```

---

## 微信

### POST /api/wechat/auto-reply

**微信自动回复**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/wechat/callback

**微信回调**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/wechat/contacts/list

**获取微信联系人列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/wechat/contacts/sync

**同步微信联系人**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/wechat/contacts/{contact_id}

**获取微信联系人详情**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| contact_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/wechat/gateway

**微信网关**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/wechat/groups/list

**获取微信群列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/wechat/groups/{group_id}/send

**微信群发消息**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| group_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/wechat/menu

**获取微信菜单**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/wechat/menu

**设置微信菜单**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/wechat/send

**发送微信消息**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/wechat/send-template

**发送模板消息**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/wechat/status

**微信服务状态**

#### 响应

**200** - Successful Response

```json
string
```

---

## 性能监控

### GET /api/performance/circuit-breakers

**获取熔断器状态**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/performance/compensation

**获取误差补偿状态**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/performance/health-check

**全组件健康检查**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/performance/metrics

**获取性能指标**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/performance/neuro-bus

**获取Neuro总线性能**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/performance/rate-limiters

**获取限流器状态**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/performance/sandbox

**获取沙盒状态**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/performance/sla

**获取SLA指标**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/performance/snapshots

**获取快照状态**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/performance/traces

**获取链路追踪**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| trace_id | query |  | 否 |  |
| limit | query | integer | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 意图包

### GET /api/intent-packages

**获取意图包列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/intent-packages

**创建意图包**

#### 响应

**200** - Successful Response

```json
string
```

---

### PUT /api/intent-packages/{package_id}

**更新意图包**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| package_id | path | integer | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 意图识别

### POST /api/intent/feedback

**意图反馈**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/intent/intents

**获取意图列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/intent/models

**获取意图模型列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/intent/predict

**意图预测**

#### 请求体

```json
{
  "text": "string",
  "user_id": "string",
  "context": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/intent/predict/batch

**批量意图预测**

#### 请求体

```json
{
  "texts": [
    "string"
  ],
  "user_id": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/intent/reload

**重载意图模型**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/intent/status

**意图服务状态**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/intent/train

**意图模型训练**

#### 请求体

```json
{
  "texts": [
    "string"
  ],
  "labels": [
    "string"
  ],
  "model_name": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 打印

### GET /api/print/default

**获取默认打印机**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/print/document

**打印文档**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/print/document-printer

**获取文档打印机**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/print/job/create

**创建打印任务**

#### 请求体

```json
{
  "print_type": "string",
  "data": "{...}",
  "printer_name": "string",
  "template_id": "string",
  "copies": 1
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/print/job/{job_id}

**获取打印任务状态**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| job_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/print/job/{job_id}/cancel

**取消打印任务**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| job_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/print/jobs/list

**获取打印任务列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/print/label

**打印标签**

#### 请求体

```json
{
  "label_data": "{...}",
  "printer_name": "string",
  "template_id": "string",
  "copies": 1
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/print/label-printer

**获取标签打印机**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/print/list_labels

**获取标签列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/print/preview

**打印预览**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/print/printer-selection

**获取打印机选择**

#### 响应

**200** - Successful Response

```json
string
```

---

### PUT /api/print/printer-selection

**设置打印机选择**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/print/printers

**获取打印机列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/print/single_label

**打印单个标签**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/print/templates/list

**获取打印模板列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/print/validate

**验证打印服务**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/print/{filename}

**按文件名打印**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| filename | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 报表

### POST /api/report/custom

**自定义报表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/report/customer

**客户报表**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| start_date | query |  | 否 |  |
| end_date | query |  | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/report/export

**导出报表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/report/inventory

**库存报表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/report/overview

**总览报表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/report/purchase

**采购报表**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| start_date | query |  | 否 |  |
| end_date | query |  | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/report/sales

**销售报表**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| start_date | query |  | 否 |  |
| end_date | query |  | 否 |  |
| group_by | query |  | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/report/shipment

**发货报表**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| start_date | query |  | 否 |  |
| end_date | query |  | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 控制管理

### POST /api/control/api/control/input

**发送控制指令**

QClaw 调用：发送要填到前端输入框的内容

- **target**: 目标输入框标识（默认：main_input）
- **text**: 要填充的内容（不能为空）
- **action**: 操作类型
  - `parse_and_generate`: 解析并生成
  - `fill_only`: 仅填充
  - `none`: 无操作

#### 请求体

```json
{
  "target": "main_input",
  "text": "string",
  "action": "none"
}
```

#### 响应

**200** - Successful Response

```json
{
  "success": true,
  "data": "string",
  "error": "string"
}
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/control/api/control/input/latest

**获取最新未处理指令**

前端轮询：获取某个 target 的最新未处理指令

- **target**: 目标输入框标识（默认：main_input）

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| target | query | string | 否 |  |

#### 响应

**200** - Successful Response

```json
{
  "success": true,
  "data": "string",
  "error": "string"
}
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/control/api/control/input/{cmd_id}/ack

**确认指令已处理**

前端处理完指令后确认，避免重复执行

- **cmd_id**: 指令 ID
- **target**: 目标输入框标识（默认：main_input）

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| cmd_id | path | string | 是 |  |
| target | query | string | 否 | 目标输入框标识 |

#### 响应

**200** - Successful Response

```json
{
  "success": true,
  "data": "string",
  "error": "string"
}
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 模块扩展

### GET /api/mods/

**获取模块列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/mods/loading-status

**获取模块加载状态**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/mods/routes

**获取模块路由**

#### 响应

**200** - Successful Response

```json
string
```

---

## 模板管理

### POST /api/templates/analyze/excel

**分析 Excel 文件**

分析上传的 Excel 文件，自动识别表头行并提取样例数据。

**功能**:
- 自动识别表头行（基于文本比例、唯一性评分）
- 提取前 6 行样例数据
- 返回字段定义和数据结构

**返回示例**:
```json
{
  "success": true,
  "data": {
    "sheet_name": "Sheet1",
    "fields": [
      {"label": "产品型号", "value": "", "type": "dynamic"},
      {"label": "产品名称", "value": "", "type": "dynamic"}
    ],
    "sample_rows": [
      {"产品型号": "26-0200006A", "产品名称": "PE 白底漆"},
      {"产品型号": "26-0200008A", "产品名称": "PU 哑白面固化剂"}
    ]
  }
}
```

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| sheet_name | query |  | 否 | 工作表名称 |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/templates/analyze/grid

**提取 Excel 网格预览**

提取 Excel 网格数据用于前端预览（包含合并单元格信息）。

**返回示例**:
```json
{
  "success": true,
  "data": {
    "sheet_name": "Sheet1",
    "rows": [
      [
        {"row": 1, "col": 1, "text": "产品型号", "rowspan": 1, "colspan": 1},
        {"row": 1, "col": 2, "text": "产品名称", "rowspan": 1, "colspan": 1}
      ]
    ]
  }
}
```

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| sheet_name | query |  | 否 | 工作表名称 |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/templates/analyze/style-cache

**提取 Excel 样式缓存**

提取 Excel 样式信息用于前端缓存（字体、填充、边框等）。

**返回示例**:
```json
{
  "success": true,
  "data": {
    "sheet_name": "Sheet1",
    "styles": {
      "style_1": {
        "font": {"name": "宋体", "size": 12, "bold": true},
        "fill": {"fill_type": "solid", "fg_color": "FFFF00"},
        "alignment": {"horizontal": "center", "vertical": "center"}
      }
    },
    "cell_style_refs": {"1,1": "style_1"}
  }
}
```

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| sheet_name | query |  | 否 | 工作表名称 |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/templates/preview/file

**预览 Excel 文件**

预览指定 Excel 文件的内容。

**参数**:
- `file_path`: Excel 文件绝对路径
- `sheet_name`: 可选，指定工作表名称

**返回示例**:
```json
{
  "success": true,
  "data": {
    "sheet_name": "Sheet1",
    "fields": [...],
    "sample_rows": [...]
  }
}
```

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| file_path | query | string | 是 | Excel 文件路径 |
| sheet_name | query |  | 否 | 工作表名称 |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/templates/preview/grid

**预览 Excel 网格**

预览 Excel 网格结构（包含合并单元格）。

**返回示例**:
```json
{
  "success": true,
  "data": {
    "sheet_name": "Sheet1",
    "rows": [
      [
        {"row": 1, "col": 1, "text": "标题", "rowspan": 1, "colspan": 3}
      ]
    ]
  }
}
```

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| file_path | query | string | 是 | Excel 文件路径 |
| sheet_name | query |  | 否 | 工作表名称 |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/templates/preview/style-cache

**获取样式缓存**

获取 Excel 样式缓存数据。

**返回示例**:
```json
{
  "success": true,
  "data": {
    "sheet_name": "Sheet1",
    "styles": {...},
    "cell_style_refs": {...}
  }
}
```

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| file_path | query | string | 是 | Excel 文件路径 |
| sheet_name | query |  | 否 | 工作表名称 |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/templates/validators/rules

**获取校验规则**

获取所有模板作用域的校验规则。

**返回示例**:
```json
{
  "success": true,
  "data": {
    "orders": {
      "templateType": "发货单",
      "requiredTerms": ["产品型号", "产品名称", "数量", "单价", "金额"]
    },
    "shipmentRecords": {
      "templateType": "出货记录",
      "requiredTerms": ["客户", "产品名称", "型号", "数量", "单价", "金额"]
    }
  }
}
```

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/templates/validators/terms/equivalents/{term}

**获取同义词**

获取指定词条的所有同义词。

**参数**:
- `term`: 原始词条

**返回示例**:
```json
{
  "success": true,
  "data": {
    "term": "产品型号",
    "equivalents": ["产品型号", "型号", "产品编码"]
  }
}
```

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| term | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/templates/validators/terms/normalize

**标准化词条**

标准化词条（去除空格、转小写）。

**请求示例**:
```json
{
  "terms": ["产品型号", " 产品名称 ", "规格型号"]
}
```

**返回示例**:
```json
{
  "success": true,
  "data": {
    "normalized": ["产品型号", "产品名称", "规格型号"]
  }
}
```

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/templates/validators/validate

**校验模板**

校验模板是否满足业务规则要求。

**校验规则**:
- 检查是否包含所有必需的业务词条
- 支持同义词匹配（如"产品型号"="型号"="产品编码"）

**作用域说明**:
- `orders`: 发货单 - 必需词条：产品型号、产品名称、数量、单价、金额
- `shipmentRecords`: 出货记录 - 必需词条：客户、产品名称、型号、数量、单价、金额
- `products`: 产品清单 - 必需词条：产品型号、产品名称、规格、价格
- `materials`: 原材料清单 - 必需词条：原材料编码、名称、分类、规格、单位、库存数量、单价、供应商
- `customers`: 客户清单 - 必需词条：客户名称、联系人、电话、地址

**返回示例**:
```json
{
  "success": true,
  "data": {
    "valid": true,
    "missing_terms": []
  }
}
```

或校验失败:
```json
{
  "success": true,
  "data": {
    "valid": false,
    "missing_terms": ["产品型号", "数量"]
  }
}
```

#### 请求体

```json
{
  "cells": "{...}",
  "fields": [
    "string"
  ],
  "template_scope": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 系统管理

### POST /api/system/cache/clear

**清除缓存**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/system/config

**设置系统配置**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/system/domains

**获取域列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/system/info

**获取系统信息**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/system/logs

**获取系统日志**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/system/neuro/status

**获取Neuro总线状态**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/system/restart

**重启服务**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/system/test-db/disable

**停用测试数据库，切回真实库**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/system/test-db/enable

**启用测试数据库 products_test.db**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/system/test-db/status

**测试数据库状态（与 SettingsView 一致）**

返回 data.enabled / data.current_db 等，供前端系统设置页加载与展示。

#### 响应

**200** - Successful Response

```json
string
```

---

## 蒸馏模型

### GET /api/distillation/config

**获取蒸馏配置**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/distillation/config

**设置蒸馏配置**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/distillation/data/upload

**上传蒸馏数据**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/distillation/models

**获取蒸馏模型列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/distillation/start

**启动蒸馏任务**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/distillation/tasks

**获取蒸馏任务列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/distillation/tasks/{task_id}

**获取蒸馏任务详情**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| task_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/distillation/tasks/{task_id}/cancel

**取消蒸馏任务**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| task_id | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/distillation/versions

**获取蒸馏版本列表**

#### 响应

**200** - Successful Response

```json
string
```

---

## 订单管理

### GET /api/orders

**获取订单列表**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| page | query | integer | 否 |  |
| per_page | query | integer | 否 |  |
| keyword | query |  | 否 |  |
| status | query |  | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### DELETE /api/orders/clear-all

**清除所有订单**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/orders/latest

**获取最新订单**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/orders/next_number

**获取下一个订单号**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| suffix | query | string | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/orders/purchase-units

**获取采购单位**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/orders/search

**搜索订单**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| keyword | query | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/orders/{order_number}

**获取订单详情**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| order_number | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 认证

### POST /api/auth/login

**用户登录**

#### 请求体

```json
{
  "username": "string",
  "password": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/auth/logout

**用户登出**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/auth/me

**获取当前用户信息**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/auth/refresh

**刷新Token**

#### 请求体

```json
{
  "refresh_token": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 采购管理

### POST /api/purchase/batch-delete

**批量删除采购单**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/purchase/create

**创建采购单**

#### 请求体

```json
{
  "supplier_name": "string",
  "items": "string",
  "order_text": "string",
  "notes": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/purchase/export

**导出采购数据**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/purchase/list

**获取采购单列表**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| page | query | integer | 否 |  |
| per_page | query | integer | 否 |  |
| supplier_name | query |  | 否 |  |
| start_date | query |  | 否 |  |
| end_date | query |  | 否 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/purchase/parse

**AI解析采购单**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/purchase/stats

**采购统计**

#### 响应

**200** - Successful Response

```json
string
```

---

### POST /api/purchase/suppliers/list

**获取供应商列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/purchase/{purchase_id}

**获取采购单详情**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| purchase_id | path | integer | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### PUT /api/purchase/{purchase_id}

**更新采购单**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| purchase_id | path | integer | 是 |  |

#### 请求体

```json
{
  "data": "{...}"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### DELETE /api/purchase/{purchase_id}

**删除采购单**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| purchase_id | path | integer | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 销售合同

### GET /api/sales-contract/download

**下载销售合同(by filepath)**

通过完整文件路径下载销售合同

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| filepath | query | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/sales-contract/download/{filename}

**下载销售合同**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| filename | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/sales-contract/generate

**生成销售合同**

#### 请求体

```json
{
  "customer_name": "string",
  "customer_phone": "",
  "contract_date": "string",
  "products": [
    "{...}"
  ],
  "return_buckets_expected": 0,
  "return_buckets_actual": 0
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### GET /api/sales-contract/list

**获取销售合同列表**

#### 响应

**200** - Successful Response

```json
string
```

---

### GET /api/sales-contract/preview/{filename}

**预览销售合同**

#### 请求参数

| 参数名 | 位置 | 类型 | 必填 | 描述 |
|--------|------|------|------|------|
| filename | path | string | 是 |  |

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

### POST /api/sales-contract/print

**打印销售合同**

#### 请求体

```json
{
  "filename": "string",
  "printer_name": "string"
}
```

#### 响应

**200** - Successful Response

```json
string
```

**422** - Validation Error

```json
{
  "detail": [
    "{...}"
  ]
}
```

---

## 📚 数据模型

### AnalyzeRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| text |  | 否 |  |
| image_base64 |  | 否 |  |
| analysis_type |  | 否 |  |
| user_id |  | 否 |  |
| context |  | 否 |  |


### BatchChatRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| messages | array<string> | 是 |  |
| user_id |  | 否 |  |
| context |  | 否 |  |
| source |  | 否 |  |
| mode |  | 否 |  |


### Body_analyze_excel_api_templates_analyze_excel_post

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| file | string | 是 | Excel 文件 |


### Body_analyze_grid_api_templates_analyze_grid_post

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| file | string | 是 | Excel 文件 |


### Body_analyze_style_cache_api_templates_analyze_style_cache_post

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| file | string | 是 | Excel 文件 |


### Body_excel_upload_api_excel_upload_post

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| file | string | 是 |  |


### Body_file_upload_api_upload_post

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| file | string | 是 |  |


### Body_install_mod_api_mod_store_mod_store_install_post

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| package_file | string | 是 | MOD 包文件名 |
| activate | boolean | 否 | 是否立即激活 |
| verify_signature | boolean | 否 | 是否验证签名 |


### Body_media_upload_api_media_upload_post

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| file | string | 是 |  |


### Body_rate_mod_api_mod_store_mod_store_mod__mod_id__rate_post

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| rating | integer | 是 | 评分 (1-5) |
| comment | string | 否 | 评论 |
| user_id | string | 否 | 用户 ID |


### Body_traditional_fs_upload_api_traditional_mode_upload_post

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| path | string | 否 |  |
| file | string | 是 |  |


### Body_uninstall_mod_api_mod_store_mod_store_uninstall_post

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| mod_id | string | 是 | MOD ID |
| remove_files | boolean | 否 | 是否删除文件 |


### Body_update_mod_api_mod_store_mod_store_update_post

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| mod_id | string | 是 | MOD ID |
| package_file | string | 是 | MOD 包文件名 |
| verify_signature | boolean | 否 | 是否验证签名 |


### Body_upload_mod_package_api_mod_store_mod_store_upload_post

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| file | string | 是 | MOD 包文件 (.xcmod) |
| activate | boolean | 否 | 上传后是否立即激活 |


### ChatRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| message | string | 是 |  |
| user_id |  | 否 |  |
| context |  | 否 |  |
| source |  | 否 |  |
| mode |  | 否 |  |
| file_context |  | 否 |  |
| excel_index_id |  | 否 |  |
| excel_top_k |  | 否 |  |


### ControlCommandData

控制指令数据模型

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| id | string | 是 | 指令 ID |
| target | string | 是 | 目标输入框标识 |
| text | string | 是 | 指令内容 |
| action | string | 是 | 操作类型 |
| created_at | string | 是 | 创建时间（ISO 8601） |
| handled | boolean | 否 | 是否已处理 |


### ControlInputRequest

控制指令请求模型

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| target | string | 否 | 目标输入框标识 |
| text | string | 是 | 要填充到输入框的内容 |
| action | string | 否 | 操作类型：parse_and_generate / fill_only / none |


### ControlInputResponse

控制指令响应模型

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| success | boolean | 否 | 是否成功 |
| data |  | 否 | 返回数据 |
| error |  | 否 | 错误信息 |


### ControlLatestResponse

获取最新指令响应模型

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| success | boolean | 否 | 是否成功 |
| data |  | 否 | 指令数据 |
| error |  | 否 | 错误信息 |


### CustomerCreateRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| name | string | 是 |  |
| contact |  | 否 |  |
| phone |  | 否 |  |
| address |  | 否 |  |
| level |  | 否 |  |
| notes |  | 否 |  |


### CustomerUpdateRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| name |  | 否 |  |
| contact |  | 否 |  |
| phone |  | 否 |  |
| address |  | 否 |  |
| level |  | 否 |  |
| notes |  | 否 |  |


### GeneratePriceListRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| customer_name | string | 是 |  |
| products | array<object> | 是 |  |
| printer_name |  | 否 |  |


### GeneratePriceListResponse

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| success | boolean | 是 |  |
| filename |  | 否 |  |
| filepath |  | 否 |  |
| message |  | 否 |  |
| error |  | 否 |  |


### HTTPValidationError

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| detail | array<object> | 否 |  |


### HealthResponse

健康检查响应模型

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| status | string | 是 |  |
| timestamp | string | 是 |  |
| version | string | 是 |  |
| framework | string | 是 |  |


### ImageAnalyzeRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| image_base64 | string | 是 |  |
| analysis_type |  | 否 |  |
| user_id |  | 否 |  |


### IntentPredictBatchRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| texts | array<string> | 是 |  |
| user_id |  | 否 |  |


### IntentPredictRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| text | string | 是 |  |
| user_id |  | 否 |  |
| context |  | 否 |  |


### IntentTrainRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| texts | array<string> | 是 |  |
| labels | array<string> | 是 |  |
| model_name |  | 否 |  |


### InventoryAdjustRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| product_id | integer | 是 |  |
| quantity | number | 是 |  |
| reason |  | 否 |  |


### InventoryCheckRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| product_ids |  | 否 |  |
| product_names |  | 否 |  |


### InventoryReserveRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| items | array<object> | 是 |  |
| order_id |  | 否 |  |


### LabelPrintRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| label_data | object | 是 |  |
| printer_name |  | 否 |  |
| template_id |  | 否 |  |
| copies |  | 否 |  |


### LoginRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| username | string | 是 |  |
| password | string | 是 |  |


### MaterialCreateRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| name | string | 是 |  |
| unit |  | 否 |  |
| specification |  | 否 |  |
| category |  | 否 |  |
| stock_quantity |  | 否 |  |
| min_quantity |  | 否 |  |
| unit_price |  | 否 |  |
| supplier |  | 否 |  |
| notes |  | 否 |  |


### MaterialUpdateRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| name |  | 否 |  |
| unit |  | 否 |  |
| specification |  | 否 |  |
| category |  | 否 |  |
| stock_quantity |  | 否 |  |
| min_quantity |  | 否 |  |
| unit_price |  | 否 |  |
| supplier |  | 否 |  |
| notes |  | 否 |  |


### OCRIdCardRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| image_base64 | string | 是 |  |
| side |  | 否 |  |
| user_id |  | 否 |  |


### OCRInvoiceRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| image_base64 | string | 是 |  |
| user_id |  | 否 |  |


### OCRRecognizeRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| image_base64 | string | 是 |  |
| ocr_type |  | 否 |  |
| user_id |  | 否 |  |


### ParseCustomerRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| text | string | 是 |  |
| user_id |  | 否 |  |


### ParseOrderRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| text | string | 是 |  |
| user_id |  | 否 |  |
| context |  | 否 |  |


### ParseProductRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| text | string | 是 |  |
| user_id |  | 否 |  |
| context |  | 否 |  |


### ParseShipmentRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| text | string | 是 |  |
| user_id |  | 否 |  |
| context |  | 否 |  |


### PriceListItem

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| model_number | string | 是 |  |
| name | string | 是 |  |
| spec | string | 是 |  |
| unit | string | 是 |  |
| unit_price | string | 是 |  |


### PriceListPrintRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| filename | string | 是 |  |
| printer_name |  | 否 |  |


### PrintJobRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| print_type | string | 是 |  |
| data | object | 是 |  |
| printer_name |  | 否 |  |
| template_id |  | 否 |  |
| copies |  | 否 |  |


### ProductBatchCreateRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| products | array<object> | 是 |  |


### ProductCreateRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| unit_name | string | 是 |  |
| product_name | string | 是 |  |
| price | number | 是 |  |
| description |  | 否 |  |
| model_number |  | 否 |  |
| specification |  | 否 |  |
| category |  | 否 |  |
| brand |  | 否 |  |


### ProductUpdateRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| id |  | 否 |  |
| product_name |  | 否 |  |
| price |  | 否 |  |
| description |  | 否 |  |
| model_number |  | 否 |  |
| specification |  | 否 |  |
| category |  | 否 |  |
| brand |  | 否 |  |


### PurchaseCreateRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| supplier_name |  | 否 |  |
| items |  | 否 |  |
| order_text |  | 否 |  |
| notes |  | 否 |  |


### PurchaseUpdateRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| data | object | 是 |  |


### SalesContractGenerateRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| customer_name | string | 是 |  |
| customer_phone |  | 否 |  |
| contract_date |  | 否 |  |
| products | array<object> | 是 |  |
| return_buckets_expected | integer | 否 |  |
| return_buckets_actual | integer | 否 |  |


### SalesContractPrintRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| filename | string | 是 |  |
| printer_name |  | 否 |  |


### SalesContractProductItem

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| model_number | string | 是 |  |
| name | string | 是 |  |
| spec | string | 是 |  |
| unit | string | 是 |  |
| quantity | string | 是 |  |
| unit_price | string | 是 |  |
| amount | string | 是 |  |


### ShipmentDeleteRequest

发货记录删除请求

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| record_id | integer | 是 | 记录 ID |


### ShipmentGenerateRequest

发货单生成请求

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| customer_name |  | 否 | 客户名称 |
| items |  | 否 | 商品列表 |
| order_text |  | 否 | 订单文本描述 |
| template_id |  | 否 | 模板 ID |
| notes |  | 否 | 备注信息 |


### ShipmentGenerateResponse

发货单生成响应

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| success | boolean | 否 | 是否成功 |
| shipment_id |  | 否 | 发货单 ID |
| order_number |  | 否 | 订单号 |
| created_at |  | 否 | 创建时间 |
| error |  | 否 | 错误信息 |


### ShipmentItem

发货单项

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| product_id | integer | 是 | 产品 ID |
| product_name |  | 否 | 产品名称 |
| quantity | number | 是 | 数量 |
| unit_price |  | 否 | 单价 |
| amount |  | 否 | 金额 |


### ShipmentPrintRequest

发货单打印请求

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| shipment_id |  | 否 | 发货单 ID |
| filename |  | 否 | 文件名 |
| printer_name |  | 否 | 打印机名称 |
| label_data |  | 否 | 标签数据 |
| copies | integer | 否 | 打印份数 |


### ShipmentPrintResponse

发货单打印响应

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| success | boolean | 否 | 是否成功 |
| print_job_id |  | 否 | 打印任务 ID |
| status |  | 否 | 打印状态 |
| error |  | 否 | 错误信息 |


### ShipmentRecord

发货记录

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| id | integer | 是 | 记录 ID |
| order_number | string | 是 | 订单号 |
| customer_name | string | 是 | 客户名称 |
| total_amount | number | 否 | 总金额 |
| status | string | 否 | 状态 |
| created_at | string | 是 | 创建时间 |
| updated_at |  | 否 | 更新时间 |


### ShipmentRecordListResponse

发货记录列表响应

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| success | boolean | 否 | 是否成功 |
| records | array<object> | 否 | 记录列表 |
| total | integer | 否 | 总数 |
| page | integer | 否 | 当前页 |
| per_page | integer | 否 | 每页数量 |
| total_pages | integer | 否 | 总页数 |


### ShipmentSequenceRequest

订单号序列设置请求

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| order_ids | array<integer> | 是 | 订单 ID 列表 |
| sequence | integer | 是 | 序列号 |


### ShipmentUpdateRequest

发货记录更新请求

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| record_id | integer | 是 | 记录 ID |
| data | object | 否 | 更新数据 |


### TTSRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| text | string | 是 |  |
| voice |  | 否 |  |
| speaker_id |  | 否 |  |
| lang |  | 否 |  |
| rate |  | 否 |  |
| pitch |  | 否 |  |


### TTSResponse

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| success | boolean | 是 |  |
| message | string | 否 |  |
| data |  | 否 |  |
| error |  | 否 |  |


### TemplateValidationRequest

模板校验请求

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| cells | object | 否 | 单元格数据 |
| fields | array<object> | 否 | 字段列表 |
| template_scope | string | 是 | 模板作用域 (orders/shipmentRecords/products/materials/customers) |


### TextAnalyzeRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| text | string | 是 |  |
| analysis_type |  | 否 |  |
| user_id |  | 否 |  |
| context |  | 否 |  |


### TokenRefreshRequest

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| refresh_token | string | 是 |  |


### ValidationError

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| loc | array<object> | 是 |  |
| msg | string | 是 |  |
| type | string | 是 |  |


### _DbModeBody

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| mode | string | 是 | production 或 test |

---

## 智能搜索 V0

- [GET /api/search/v0](#get--api-search-v0) - 跨域只读搜索（产品/客户/Excel 向量）

### GET /api/search/v0

**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| q | string | "" | 检索词 |
| scope | string | products | products \| customers \| excel \| all |
| per_page | int | 20 | 1–50 |

**响应示例**

```json
{
  "success": true,
  "query": "七彩",
  "scope": "all",
  "results": {
    "products": { "success": true, "data": [] },
    "customers": { "success": true, "data": [] }
  }
}
```


/** Labels shared by candidate intake and its approval receipts. */
export function targetLabel(type: string) {
  return ({ auto: '智能识别（推荐）', template_review: '模板审阅', template_classification: '文件分类',
    customers: '客户', customer: '客户', products: '产品', customer_products: '客户及产品',
    shipment_records: '发货记录', purchase_orders: '采购订单', attendance: '考勤', knowledge: '知识库',
    export_xlsx: 'Excel 导出', export_csv: 'CSV 导出', webhook: '外部系统' } as Record<string, string>)[type] || '其他业务目标'
}

export function autoIngestStatusLabel(status?: string) {
  return ({ running: '入库处理中', awaiting_confirmation: '知识已处理，业务待确认', applied: '批次处理结束，请核对分项结果', failed: '入库失败，请核对已写入部分', withdrawn: '已撤回' } as Record<string, string>)[status || ''] || '状态待核对'
}

export function actionLabel(action: string) {
  return ({ new: '新增', update: '更新', skip: '跳过', error: '错误' } as Record<string, string>)[action] || action
}


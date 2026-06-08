# 错误返回字段统一修复总结

## 修复内容

统一后端 API 错误返回格式，将 `"error"` 字段全部改为 `"message"`，解决前后端字段名不一致问题。

## 修复统计

| 文件路径 | 修复字段数 |
|---------|-----------|
| `app/application/workflow/planner.py` | 25 |
| `app/application/auth_app_service.py` | 10 |
| `app/services/auth_service.py` | 10 |
| `app/infrastructure/skills/excel_toolkit/excel_toolkit.py` | 9 |
| `app/auth_decorators.py` | 7 |
| `app/services/skills/label_template_generator/label_template_generator.py` | 6 |
| `app/services/kitten_report/save_service.py` | 6 |
| `app/services/user_service.py` | 6 |
| `app/services/kitten_report/chart_data_service.py` | 5 |
| `app/infrastructure/skills/excel_analyzer/excel_template_analyzer.py` | 5 |
| `app/utils/error_handling.py` | 11 |
| `app/services/system_service.py` | 3 |
| `app/utils/system_service.py` | 3 |
| `app/infrastructure/skills/__init__.py` | 3 |
| `app/services/printer_service.py` | 3 |
| `app/utils/security_middleware.py` | 2 |
| `app/services/kitten_report/financial_plugins.py` | 2 |
| `app/decorators/mp_auth.py` | 2 |
| `app/application/ai_chat_app_service.py` | 1 |
| `app/application/customer_app_service.py` | 1 |
| `app/application/user_app_service.py` | 5 |
| `app/ai_engines/bert/intent_service.py` | 1 |
| `app/services/rasa_nlu_service.py` | 1 |
| `app/utils/decorators.py` | 1 |
| `app/utils/mobile_api.py` | 1 |
| `app/services/bert_intent_service.py` | 1 |
| `app/services/task_agent.py` | 1 |
| `app/services/ai_conversation_service.py` | 1 |
| `app/infrastructure/documents/price_list_generator.py` | 1 |
| **总计** | **141** |

## 统一后的格式

### 变更前（混乱）
```json
// 版本 A：使用 error
{ "success": false, "error": "缺少参数" }

// 版本 B：使用 message  
{ "success": false, "message": "服务不可用" }

// 版本 C：两者混用
{ "success": false, "error": "详细错误", "message": "用户提示" }
```

### 变更后（统一）
```json
{
  "success": false,
  "message": "人类可读的错误信息",
  "error_code": "machine_readable_error_code"
}
```

## 前端适配建议

### 1. 立即修改（向后兼容）
```typescript
// 临时兼容方案（过渡期间）
const errorMsg = response.message || (response as any).error || '操作失败';
```

### 2. 推荐修改（标准用法）
```typescript
// 直接使用 message 字段
const errorMsg = response.message || '操作失败';

// 使用 error_code 做精细化处理
if (response.error_code === 'missing_customer_name') {
  openCustomerSelector();
} else if (response.error_code === 'database_locked') {
  showRetryToast();
} else {
  message.error(response.message);
}
```

### 3. 统一使用 Toast
```typescript
// 推荐：所有错误都用 Toast（替代 Alert）
import { message } from 'antd';

function handleApiResponse(response: ApiResponse) {
  if (!response.success) {
    message.error(response.message); // 3秒后自动消失
  }
}
```

## 提供的工具

1. **`frontend/error-handler.ts`** - 前端统一错误处理工具
   - `handleApiError()` - 处理单个错误响应
   - `summarizeBatchErrors()` - 批量错误汇总
   - 错误码映射表和自动化处理

2. **`API_ERROR_FORMAT_CHANGELOG.md`** - API 格式变更文档
   - 完整的错误码列表
   - 前端适配指南
   - 向后兼容性说明

## 下一步行动

### 高优先级（建议本周完成）
1. 前端统一改用 `message` 字段获取错误信息
2. 移除对 `error` 字段的依赖

### 中优先级（建议本月完成）
1. 根据 `error_code` 实现精细化 UX
   - `missing_customer_name` → 自动打开客户选择器
   - `missing_unit_name` → 高亮单位输入框
   - `database_locked` → 自动重试 + Toast 提示
   - `service_unavailable` → 显示维护中提示

### 低优先级（建议下月完成）
1. 统一使用 Toast 组件替代 Alert 弹窗
2. 错误提示用户体验优化

## 注意事项

1. 此修改只影响 `"error":` 作为返回字段名的情况
2. `.get("error")` 读取其他对象属性的代码不受影响（如从子服务读取错误）
3. 所有修改都是向后兼容的，`message` 和 `error_code` 都是可选字段

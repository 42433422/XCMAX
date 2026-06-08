# API 错误返回格式变更日志

## 变更概述

统一后端 API 错误返回格式，解决 `error` vs `message` 字段名不一致问题。

## 变更前格式（混乱）

```typescript
// 有些地方用 error
{ success: false, error: "缺少参数" }

// 有些地方用 message
{ success: false, message: "服务不可用" }

// 有些地方两者都用
{ success: false, error: "详细错误", message: "用户提示" }
```

## 变更后格式（统一）

```typescript
{
  success: false,
  message: "人类可读的错误信息",     // 统一使用 message 字段
  error_code: "missing_customer_name" // 机器可读的错误码（可选）
}
```

## 主要变更文件

- `app/application/workflow/planner.py` - 25 处 `error` 改为 `message`
- `app/application/ai_chat_app_service.py` - 1 处修改
- `app/application/auth_app_service.py` - 10 处修改
- `app/application/customer_app_service.py` - 1 处修改
- `app/application/user_app_service.py` - 5 处修改

## 前端适配指南

### 1. 错误字段获取方式变更

```typescript
// 变更前（需要判断多个字段）
const errorMsg = response.error || response.message || '未知错误';

// 变更后（直接使用 message）
const errorMsg = response.message || '未知错误';
```

### 2. 使用 error_code 做精细化 UX

```typescript
const ERROR_HANDLERS: Record<string, (msg: string) => void> = {
  'missing_customer_name': (msg) => {
    // 自动打开客户选择弹窗
    openCustomerSelector();
  },
  'missing_unit_name': (msg) => {
    // 高亮单位输入框
    highlightField('unit_name');
  },
  'database_locked': (msg) => {
    // 显示"正在重试"提示
    showRetryToast(msg);
  },
  'service_unavailable': (msg) => {
    // 显示"服务维护中"
    showServiceDownAlert();
  },
};

function handleError(response: ApiResponse) {
  if (!response.success) {
    const handler = ERROR_HANDLERS[response.error_code];
    if (handler) {
      handler(response.message);
    } else {
      // 默认 Toast 提示
      showToast(response.message);
    }
  }
}
```

### 3. 统一 Toast 组件使用

```typescript
// 建议所有错误提示都使用 Toast（替代 Alert）
import { message } from 'antd'; // 或你的 UI 库

function showError(response: ApiResponse) {
  if (!response.success) {
    message.error(response.message); // 使用 Toast 而非 Modal
  }
}
```

## 错误码列表

| error_code | 含义 | 建议前端处理 |
|------------|------|-------------|
| `missing_customer_name` | 缺少客户名称 | 打开客户选择器 |
| `missing_unit_name` | 缺少单位名称 | 高亮单位输入框 |
| `missing_file_path` | 缺少文件路径 | 提示重新选择文件 |
| `missing_products` | 缺少产品数据 | 提示添加产品 |
| `missing_order_params` | 缺少订单参数 | 高亮订单输入区 |
| `unknown_tool_action` | 未知工具/操作 | 显示"功能不可用" |
| `service_unavailable` | 服务不可用 | 显示维护提示 |
| `validation_error` | 数据验证失败 | 高亮错误字段 |
| `duplicate_error` | 数据重复 | 显示重复警告 |
| `database_locked` | 数据库锁定 | 自动重试或提示稍后 |
| `database_busy` | 数据库繁忙 | 延迟重试 |
| `file_not_found` | 文件未找到 | 提示重新选择 |
| `file_io_error` | 文件读写错误 | 提示检查权限 |
| `foreign_key_violation` | 外键约束违反 | 显示数据关联错误 |
| `general_error` | 通用错误 | 默认 Toast 提示 |

## 向后兼容性

虽然字段名已统一为 `message`，但为了向后兼容：

```typescript
// 建议前端同时兼容两种字段（过渡期间）
const errorMsg = response.message || (response as any).error || '操作失败';
```

## 下一步建议

1. **高优先级**：前端统一改用 `message` 字段
2. **中优先级**：根据 `error_code` 实现精细化 UX（自动填充、字段高亮等）
3. **低优先级**：统一使用 Toast 组件替代 Alert 弹窗

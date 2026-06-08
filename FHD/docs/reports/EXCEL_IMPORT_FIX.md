# Excel 导入断链问题修复说明

## 问题描述

### 症状 1：聊天记录中断导致确认失效
用户上传 Excel → 系统分析 → 显示确认卡片 → 用户点击确认时，聊天记录中断/刷新后，确认按钮失效，提示找不到待导入数据。

**根本原因**：
- `pending_excel_imports` 存储在服务器内存中（`ai_chat_app_service` 实例变量）
- 当聊天记录中断、页面刷新、切换会话时，内存数据丢失
- 前端点击确认时，后端找不到对应的 `pending_import_id`

### 症状 2：输入令牌后对话中断
当系统要求输入数据库写入令牌时，用户输入后系统会**重新发送整个聊天请求**或**重新连接流式会话**，导致：
- Excel 导入的确认任务丢失
- 对话历史中断
- 流式响应被切断
- 需要重新上传和分析 Excel

**根本原因**：
- 非流式：令牌输入后的重试逻辑调用 `requestChatByModeWithTimeout(remoteMessages[0], ...)`
- 流式：令牌输入后执行 `continue streamRetry` 重新连接 SSE 流
- 这两种方式都会重新发送用户原始消息，触发完整的 AI 对话流程
- 而不是直接执行 pending 的导入任务

## 修复方案

### 核心思路
将待导入的 Excel 数据持久化到前端 `sessionStorage`，不再依赖服务器内存。
当用户输入令牌后，**直接执行 pending 的导入任务**，而不是重新发送聊天请求。

### 修改内容

#### 1. 新增持久化工具
**文件**: `frontend/src/utils/excelImportPersistence.ts`

功能：
- `savePendingImport()` - 保存待导入数据到 sessionStorage 和 localStorage
- `getPendingImport()` - 从持久化存储读取数据
- `removePendingImport()` - 导入成功后清除数据
- `cleanupExpiredImports()` - 清理超过 24 小时的过期数据

#### 2. 后端修改
**文件**: `app/application/ai_chat_app_service.py`

修改点：
```python
# 在生成 pending_import_id 时，把 records 和 excel_analysis 也传给前端
"task": {
    "payload": {
        "params": {
            "pending_import_id": pending_id,
            "record_count": len(records),
            # 新增：把完整记录传给前端持久化
            "records": records,
            "excel_analysis": excel_analysis,
        }
    }
}
```

#### 3. 前端修改
**文件**: `frontend/src/composables/useChatView.ts`

**修改点 1**: 导入持久化工具
```typescript
import { savePendingImport, getPendingImport, removePendingImport } from '@/utils/excelImportPersistence'
```

**修改点 2**: 在 `showTaskConfirm()` 中保存数据
```typescript
if (nextTask?.type === 'excel_import') {
  const pendingId = nextTask?.payload?.params?.pending_import_id
  const records = nextTask?.payload?.params?.records
  const excelAnalysis = nextTask?.payload?.params?.excel_analysis
  
  if (pendingId && records && Array.isArray(records)) {
    savePendingImport({
      pending_id: pendingId,
      records: records,
      excel_analysis: excelAnalysis || {},
      created_at: Date.now(),
      session_id: String(sessionId.value || 'default')
    })
  }
  return
}
```

**修改点 3**: 在 `executeExcelImportConfirm()` 中读取数据
```typescript
async function executeExcelImportConfirm(task: any): Promise<void> {
  const pendingImportId = task?.payload?.params?.pending_import_id
  
  // 从持久化存储中读取待导入数据
  const pendingData = getPendingImport(pendingImportId)
  if (!pendingData) {
    await addAndSaveMessage(
      '❌ Excel 导入失败：找不到待导入数据（可能已过期或聊天记录被清理）\n\n' +
      '解决方案：请重新上传 Excel 文件并分析，然后再次执行导入。',
      'ai'
    )
    return
  }

  // 将完整的记录数据传给后端，避免依赖服务器内存
  const response = await fetch('/api/tools/execute', {
    method: 'POST',
    body: JSON.stringify({
      tool_id: 'excel_import',
      action: 'execute_import',
      params: {
        pending_import_id: pendingImportId,
        records: pendingData.records,        // 新增
        excel_analysis: pendingData.excel_analysis  // 新增
      }
    })
  })
  
  // ... 导入成功后调用 removePendingImport(pendingImportId)
}
```

**修改点 4**: 在流式响应中直接执行导入（`frontend/src/composables/useChatView.ts`）

这是**最关键的修复**，确保输入令牌后聊天不会中断：

```typescript
// 在 consumePlannerSse 返回 needs_write_token 时
if (consumed.outcome === 'needs_write_token') {
  // 检查是否有 pending 的 Excel 导入任务
  const hasPendingExcelImport = currentTask.value?.type === 'excel_import'
  
  if (hasPendingExcelImport) {
    // 有 pending 的 Excel 导入，直接执行导入，不重新连接流式会话
    const pendingImportId = currentTask.value?.payload?.params?.pending_import_id
    const pendingData = getPendingImport(pendingImportId)
    
    if (pendingData) {
      // 打开令牌窗口
      await openDbImportWriteKeyModal({...})
      const token = resolveDbWriteTokenForRequest()
      
      // 直接调用导入 API（不重新连接 SSE）
      const response = await fetch('/api/tools/execute', {
        method: 'POST',
        body: JSON.stringify({
          tool_id: 'excel_import',
          action: 'execute_import',
          params: {
            pending_import_id: pendingImportId,
            records: pendingData.records,
            excel_analysis: pendingData.excel_analysis,
            db_write_token: token
          }
        })
      })
      
      // 直接返回导入结果，不继续 streamRetry
      if (response.ok) {
        return { success: true, response: '✅ Excel 导入完成...', ... }
      }
    }
  }
  
  // 没有 pending 的导入，按原逻辑重新连接流式会话
}
```

**关键改进**：
- ✅ 检测到 pending Excel 导入时，**不执行** `continue streamRetry`
- ✅ 直接在当前流式上下文中执行导入
- ✅ 保持 SSE 连接不断开
- ✅ 用户看到的是一条连续的对话流

## 测试步骤

### 测试场景 1：正常流程
1. 上传 Excel 文件（如 `枫驰报价 26 年.xlsx`）
2. 点击"分析 Excel"
3. 等待分析完成，系统显示确认卡片
4. 点击"确认执行"
5. **预期**：导入成功，显示导入结果

### 测试场景 2：聊天记录中断后恢复
1. 上传 Excel 文件并分析
2. 系统显示确认卡片
3. **刷新页面** 或 **切换会话** 或 **网络中断**
4. 恢复后，找到之前的确认卡片（从历史记录或任务列表）
5. 点击"确认执行"
6. **预期**：导入成功，不报错

### 测试场景 3：跨会话恢复
1. 在会话 A 中上传并分析 Excel
2. 看到确认卡片
3. 切换到会话 B（新建对话）
4. 切换回会话 A
5. 点击确认卡片
6. **预期**：导入成功

### 测试场景 4：过期清理
1. 上传 Excel 并分析，但不执行导入
2. 等待超过 24 小时
3. 尝试点击确认
4. **预期**：提示数据已过期，需要重新上传

### 测试场景 5：输入令牌后继续执行（关键场景）
1. 上传 Excel 并分析
2. 系统显示确认卡片
3. 点击"确认执行"
4. 系统提示需要数据库写入授权令牌
5. **输入正确的令牌**
6. **预期**：
   - ✅ 不重新发送聊天请求
   - ✅ 对话历史保持完整
   - ✅ 直接执行导入
   - ✅ 显示导入结果

### 测试场景 6：令牌错误后的处理
1. 上传 Excel 并分析
2. 系统显示确认卡片
3. 点击"确认执行"
4. 系统提示需要数据库写入授权令牌
5. **输入错误的令牌**
6. **预期**：
   - ✅ 提示令牌错误
   - ✅ 可以重新输入正确令牌
   - ✅ 仍不需要重新上传 Excel

## 技术细节

### 存储策略
- **sessionStorage**: 优先存储，页面会话期间有效
- **localStorage**: 备份存储，防止页面刷新丢失
- **过期时间**: 24 小时
- **存储键名**: `xcagi_excel_pending_import_{pending_id}`

### 数据安全性
- 数据仅存储在客户端浏览器
- 每次导入成功后自动清除
- 定期清理过期数据（>24 小时）

### 向后兼容
- 保留了后端的 `_pending_excel_imports` 内存存储
- 如果前端持久化失败，仍可尝试从后端内存读取（如果还在）

## 已知限制

1. **浏览器限制**: 如果用户清除浏览器缓存，待导入数据会丢失
2. **跨设备**: 不支持跨设备同步（因为数据存储在本地）
3. **数据大小**: sessionStorage 有容量限制（通常 5-10MB），超大 Excel 文件可能无法存储

## 后续优化建议

### 方案二（架构级改进）
如果需要更彻底的解决方案，可以考虑：

1. **后端持久化**: 把 pending_import 数据存储到数据库或 Redis
2. **用户关联**: 待导入数据与用户 ID 绑定，支持跨设备访问
3. **状态管理**: 引入正式的状态管理工具（如 Pinia）管理导入任务状态

### 实现成本
- 当前方案：**低**（仅修改前端 + 少量后端）
- 方案二：**中 - 高**（需要数据库迁移、API 设计等）

## 回滚方案

如果修复引入问题，可以快速回滚：

1. 删除 `frontend/src/utils/excelImportPersistence.ts`
2. 还原 `frontend/src/composables/useChatView.ts` 的修改
3. 还原 `app/application/ai_chat_app_service.py` 的修改

## 相关文件清单

- ✅ `frontend/src/utils/excelImportPersistence.ts` (新增)
- ✅ `frontend/src/composables/useChatView.ts` (修改)
- ✅ `app/application/ai_chat_app_service.py` (修改)
- ✅ `frontend/src/composables/useChatView.ts` (修改 - 令牌重试逻辑)

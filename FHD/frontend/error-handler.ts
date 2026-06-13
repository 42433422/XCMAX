/**
 * 前端统一错误处理工具
 *
 * 使用后端统一返回的 { success, message, error_code } 格式
 * 替代之前混用的 error/message 字段
 */

import type { ApiErrorResponse, ApiResponse } from './src/types/api';

// 错误码映射表 - 用于精细化 UX 处理
const ERROR_CODE_MAP: Record<string, { level: 'error' | 'warning' | 'info'; action: string }> = {
  // 缺少参数类
  'missing_customer_name': { level: 'warning', action: 'prompt_for_customer' },
  'missing_unit_name': { level: 'warning', action: 'prompt_for_unit' },
  'missing_file_path': { level: 'error', action: 'alert' },
  'missing_products': { level: 'warning', action: 'prompt_for_products' },
  'missing_order_params': { level: 'warning', action: 'prompt_for_order' },
  
  // 服务不可用
  'service_unavailable': { level: 'error', action: 'retry_or_fallback' },
  'unknown_tool_action': { level: 'error', action: 'alert' },
  
  // 数据错误
  'validation_error': { level: 'warning', action: 'highlight_fields' },
  'duplicate_error': { level: 'warning', action: 'show_duplicate_warning' },
  'foreign_key_violation': { level: 'error', action: 'show_data_integrity_error' },
  
  // 数据库错误
  'database_locked': { level: 'error', action: 'auto_retry' },
  'database_busy': { level: 'warning', action: 'retry_with_delay' },
  
  // 文件错误
  'file_not_found': { level: 'error', action: 'prompt_reselect_file' },
  'file_io_error': { level: 'error', action: 'alert' },
  
  // 默认
  'general_error': { level: 'error', action: 'toast' },
};

interface ErrorHandlerOptions {
  useToast?: boolean;      // 使用 Toast 而非 Alert
  autoRetry?: boolean;     // 自动重试可重试的错误
  showDetails?: boolean;   // 显示详细错误信息
}

/**
 * 统一错误处理函数
 * 
 * 后端现在统一返回格式：
 * {
 *   success: false,
 *   message: "人类可读的错误信息",
 *   error_code: "machine_readable_error_code"
 * }
 */
export function handleApiError(
  response: ApiErrorResponse,
  options: ErrorHandlerOptions = {}
): { handled: boolean; userMessage: string; action?: string } {
  const { useToast = true, autoRetry = true, showDetails = false } = options;
  
  // 成功响应直接返回
  if (response.success) {
    return { handled: false, userMessage: '' };
  }
  
  // 获取错误信息（现在统一使用 message 字段）
  const errorCode = response.error_code || 'general_error';
  const message = response.message || '操作失败';
  
  // 查找错误码配置
  const config = ERROR_CODE_MAP[errorCode] || ERROR_CODE_MAP['general_error'];
  
  // 根据错误级别和动作处理
  let userMessage = message;
  let action = config.action;
  
  switch (config.action) {
    case 'prompt_for_customer':
      userMessage = '请输入客户名称';
      // 可以触发前端客户选择弹窗
      break;
      
    case 'prompt_for_unit':
      userMessage = '请选择购买单位';
      break;
      
    case 'auto_retry':
      if (autoRetry) {
        userMessage = '数据库繁忙，正在自动重试...';
        // 触发自动重试逻辑
      } else {
        userMessage = '数据库繁忙，请稍后重试';
      }
      break;
      
    case 'highlight_fields':
      userMessage = message; // 保持原错误信息
      // 触发表单字段高亮
      break;
      
    case 'alert':
    default:
      // 使用 Toast 或 Alert 显示
      if (useToast) {
        showToast(message, config.level);
      } else {
        showAlert(message, config.level);
      }
      break;
  }
  
  // 开发环境显示详细错误码
  if (showDetails && process.env.NODE_ENV === 'development') {
    userMessage = `[${errorCode}] ${userMessage}`;
  }
  
  return { handled: true, userMessage, action };
}

/**
 * 显示 Toast 提示
 */
function showToast(message: string, level: 'error' | 'warning' | 'info' = 'error') {
  // 替换为你的 Toast 组件
  console.log(`[Toast ${level}]`, message);
  // 例如：antd message, Element Plus ElMessage, 或自定义 Toast
  // message[level](message);
}

/**
 * 显示 Alert 弹窗
 */
function showAlert(message: string, level: 'error' | 'warning' | 'info' = 'error') {
  // 替换为你的 Alert 组件
  console.log(`[Alert ${level}]`, message);
  // 例如：Modal.error({ title: '错误', content: message });
}

/**
 * 批量操作错误汇总
 * 
 * 用于 Excel 导入等批量操作，汇总多个错误
 */
export function summarizeBatchErrors(
  responses: ApiResponse[],
  options: ErrorHandlerOptions = {}
): { hasErrors: boolean; summary: string; details: string[] } {
  const errors = responses.filter(r => !r.success);
  
  if (errors.length === 0) {
    return { hasErrors: false, summary: '', details: [] };
  }
  
  // 按 error_code 分组统计
  const errorGroups = new Map<string, number>();
  errors.forEach(err => {
    const code = err.error_code || 'general_error';
    errorGroups.set(code, (errorGroups.get(code) || 0) + 1);
  });
  
  // 生成汇总信息
  const totalErrors = errors.length;
  const summary = `操作完成，${totalErrors} 项失败`;
  
  // 详细错误列表（去重）
  const uniqueMessages = [...new Set(errors.map(e => e.message))];
  
  return {
    hasErrors: true,
    summary,
    details: uniqueMessages.filter(Boolean) as string[]
  };
}

/**
 * 使用示例
 */
export function exampleUsage() {
  // 示例 1：处理单个错误
  const response1: ApiResponse = {
    success: false,
    message: '缺少 customer_name 参数',
    error_code: 'missing_customer_name'
  };
  
  const result1 = handleApiError(response1, { useToast: true });
  console.log(result1.userMessage); // "请输入客户名称"
  
  // 示例 2：批量导入错误汇总
  const batchResponses: ApiResponse[] = [
    { success: true, data: {} },
    { success: false, message: '产品已存在', error_code: 'duplicate_error' },
    { success: false, message: '产品已存在', error_code: 'duplicate_error' },
    { success: false, message: '缺少单位名称', error_code: 'missing_unit_name' },
  ];
  
  const summary = summarizeBatchErrors(batchResponses);
  console.log(summary.summary); // "操作完成，3 项失败"
  console.log(summary.details);   // ["产品已存在", "缺少单位名称"]
}

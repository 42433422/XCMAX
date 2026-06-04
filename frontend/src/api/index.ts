// 统一导出所有 API 模块
import api, { ApiError, getRuntimeApiBase } from './core';

export { ApiError, getRuntimeApiBase };
export { api };
export default api;
export const apiDefault = api;

/** 与 `api.get` / `api.post` 等价，供 `import { get, post } from '@/api'` 使用 */
export const get = api.get.bind(api);
export const post = api.post.bind(api);
export const put = api.put.bind(api);

// 业务 API 模块
export { chatApi, parseChatStreamErrorResponse, type PlannerSseEvent } from './chat';
export { productsApi } from './products';
export { customersApi } from './customers';
export { materialsApi } from './materials';
export { ordersApi } from './orders';
export { printApi } from './print';
export { ocrApi } from './ocr';
export { excelApi, normalizeTemplateDtoList } from './excel';
export { wechatApi } from './wechat';
export { mediaApi } from './media';
export { systemApi } from './system';
export { intentPackagesApi } from './intentPackages';
export { privateDbAssistantApi } from './privateDbAssistant';
export { authApi } from './auth';
export { approvalApi } from './approval';
export * as modStoreApi from './modStore';
export * as marketAccountApi from './marketAccount';
export { modelPaymentApi } from './modelPayment';
export { kittenApi } from './kitten';
export { lanGateApi } from '@amin/primary-key-guard/api/lanGate';
export { manualInductApi } from './manualInduct';
export * as documentTemplatesApi from './documentTemplates';
export { templatePreviewApi } from './templatePreview';
export * as priceListApi from './priceList';
export { salesContractApi } from './salesContract';
export { traditionalApi } from './traditional';

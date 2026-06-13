// API 响应基础结构（与后端 response_envelope / common_schema 对齐）
export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  message?: string;
  total?: number;
  code?: number;
  error_code?: string;
}

/** 带扩展字段的错误响应（用于 error-handler 等边界解析） */
export type ApiErrorResponse = ApiResponse & Record<string, unknown>;

// 分页参数
export interface PaginationParams {
  page?: number;
  limit?: number;
  search?: string;
  sort?: string;
  order?: 'asc' | 'desc';
}

// 通用 CRUD API 接口
export interface CrudApi<T, CreateDTO = Partial<T>, UpdateDTO = Partial<T>> {
  getAll(params?: PaginationParams): Promise<ApiResponse<T[]>>;
  getById(id: number | string): Promise<ApiResponse<T>>;
  create(data: CreateDTO): Promise<ApiResponse<T>>;
  update(id: number | string, data: UpdateDTO): Promise<ApiResponse<T>>;
  delete(id: number | string): Promise<ApiResponse<void>>;
  batchDelete?(ids: (number | string)[]): Promise<ApiResponse<void>>;
}

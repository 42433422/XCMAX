/** API 层聊天消息（/api/ai、/api/conversations 协议） */
export interface ApiChatMessage {
  id?: number;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: string;
  session_id?: string;
  metadata?: {
    intent?: string;
    tool_calls?: unknown[];
    [key: string]: unknown;
  };
}

/** @deprecated 使用 ApiChatMessage */
export type ChatMessage = ApiChatMessage;

export interface ChatSession {
  id: string;
  title?: string;
  messages: ApiChatMessage[];
  created_at?: string;
  updated_at?: string;
  metadata?: Record<string, unknown>;
}

export interface ChatRequest {
  message: string;
  session_id?: string;
  stream?: boolean;
  user_id?: string;
  source?: string;
  mode?: string;
  file_context?: Record<string, unknown>;
  /**
   * 可含 ``excel_analysis`` 等；多模态见 ``multimodal_attachments``：
   * ``{ kind: 'image'|'pdf', filename, mime_type, data_url }[]``（``data_url`` 为 data:…;base64,…）。
   */
  context?: Record<string, unknown> | KittenRequestContext;
}

export interface ChatResponse {
  message: ApiChatMessage;
  session_id: string;
  intent?: string;
  tool_results?: unknown[];
}

export interface KittenDatasetContext {
  file_name?: string;
  name?: string;
  rows?: number;
  columns?: number;
  fields?: string[];
  field_names?: string[];
  preview_text?: string;
}

export interface KittenRequestContext {
  kitten_analyzer?: boolean;
  has_dataset?: boolean;
  kitten_dataset?: KittenDatasetContext | null;
  [key: string]: any;
}

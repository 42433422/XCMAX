import type { StringMap } from './json';

export interface WechatTask {
  id: number;
  type: string;
  content: string;
  status: 'pending' | 'confirmed' | 'ignored' | 'completed';
  created_at?: string;
  [key: string]: unknown;
}

export interface WechatContact {
  id: number;
  name: string;
  wechat_id?: string;
  phone?: string;
  tags?: string[];
  is_starred: boolean;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export type WechatContactInput = Partial<
  Pick<WechatContact, 'name' | 'wechat_id' | 'phone' | 'tags' | 'is_starred'>
> &
  StringMap;

export interface WechatContactCacheResult {
  skipped?: boolean;
  imported?: number;
  message?: string;
  [key: string]: unknown;
}

export interface WechatMessageContext {
  messages?: StringMap[];
  summary?: string;
  [key: string]: unknown;
}

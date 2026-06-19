export interface UserDto {
  id?: number;
  username?: string;
  display_name?: string;
  email?: string;
  role?: string;
  is_active?: boolean;
  avatar_url?: string;
}

export interface MobileEnvelope<T> {
  code?: number;
  message?: string;
  success?: boolean;
  data?: T;
}

export interface MobileLoginData {
  user?: UserDto;
  session_id?: string;
  access_token?: string;
  refresh_token?: string;
  account_kind?: string;
  company_brand?: string;
  market_is_admin?: boolean;
  market_is_enterprise?: boolean;
  expires_in?: number;
}

export interface MobileMeData {
  user?: UserDto;
  permissions?: string[];
  account_kind?: string;
  company_brand?: string;
  mods?: ModSummary[];
}

export interface ModSummary {
  id?: string;
}

export interface ModIndustry {
  id?: string;
  name?: string;
}

export interface ModMenuItem {
  id?: string;
  label?: string;
  icon?: string;
  path?: string;
}

export interface WorkflowEmployeeInfo {
  id?: string;
  label?: string;
  panel_title?: string;
  panel_summary?: string;
  api_base_path?: string;
  phone_channel?: string;
  workflow_placeholder?: boolean;
}

export interface ModInfo {
  id?: string;
  name?: string;
  version?: string;
  author?: string;
  description?: string;
  primary?: boolean;
  industry?: ModIndustry;
  frontend_menu?: ModMenuItem[];
  menu?: ModMenuItem[];
  workflow_employees?: WorkflowEmployeeInfo[];
}

export interface MobileModsData {
  items?: ModInfo[];
}

export interface MobileHomeData {
  mods?: ModInfo[];
  sync?: SyncStatusData;
}

export interface SyncStatusData {
  status?: string;
  cursor?: number;
  updated_at?: string;
  error?: string;
}

export interface PairingExchangeData {
  host?: string;
  port?: number;
  api_base_url?: string;
  base_url?: string;
  hint?: string;
}

export interface ChatPayload {
  reply?: string;
  content?: string;
  message?: string;
}

export interface ChatResponseData {
  success?: boolean;
  reply?: string;
  message?: string;
  data?: ChatPayload;
}

export interface ConversationSummary {
  id: string;
  title: string;
  subtitle: string;
  badge: string;
  avatar: string;
  source: string;
  employeeKey: string;
}

export interface AiEmployeeProfile {
  key: string;
  modId: string;
  modName: string;
  modAuthor: string;
  employeeId: string;
  name: string;
  title: string;
  summary: string;
  apiBasePath: string;
  phoneChannel: string;
  placeholder: boolean;
  avatarText: string;
}

export interface ChatMessage {
  role: string;
  text: string;
}

export function cleanText(value: string | undefined, fallback: string = ''): string {
  const text = (value || '').trim();
  return text.length > 0 ? text : fallback;
}

export function firstChar(value: string, fallback: string = 'AI'): string {
  const text = value.trim();
  if (text.length === 0) {
    return fallback;
  }
  return text.substring(0, 1);
}

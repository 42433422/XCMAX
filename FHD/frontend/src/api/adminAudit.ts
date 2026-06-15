import api from '@/api/core';

export type AuditLogEntry = Record<string, unknown>;

export type AuditLogsResponse = {
  items: AuditLogEntry[];
  total: number;
  path_configured?: boolean;
};

export const adminAuditApi = {
  list(limit = 50, offset = 0) {
    return api.get<{ success: boolean; data: AuditLogsResponse }>(
      '/api/admin/audit-logs',
      { limit, offset },
    );
  },

  csvDownloadUrl(limit = 500) {
    const base = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') || '';
    const q = new URLSearchParams({ format: 'csv', limit: String(limit) });
    return `${base}/api/admin/audit-logs?${q.toString()}`;
  },
};

export default adminAuditApi;

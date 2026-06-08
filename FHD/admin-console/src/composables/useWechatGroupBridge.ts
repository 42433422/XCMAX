import { ref } from 'vue';
import {
  wechatGroupBridgeApi,
  type WechatGroupSyncBody,
} from '@/api/wechatGroupBridge';

export type WechatFeedFormattedRow = {
  contactId: number;
  name: string;
  subtitle: string;
  timeLabel: string;
};

function formatTimeLabel(tsRaw: unknown): string {
  if (tsRaw == null || tsRaw === '') return '';
  let ms: number;
  if (typeof tsRaw === 'number') {
    ms = tsRaw < 1e12 ? tsRaw * 1000 : tsRaw;
  } else {
    const d = new Date(String(tsRaw));
    ms = d.getTime();
  }
  if (Number.isNaN(ms)) return '';
  const d = new Date(ms);
  const now = new Date();
  const isToday =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (isToday) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function normalizeSyncBody(
  bodyOrMarketUserId: WechatGroupSyncBody | number,
): WechatGroupSyncBody {
  if (typeof bodyOrMarketUserId === 'number') {
    return {
      market_user_id: bodyOrMarketUserId,
      force_refresh: true,
      message_limit: 80,
    };
  }
  return bodyOrMarketUserId;
}

export function useWechatGroupBridge() {
  const feed = ref<Record<string, unknown>[]>([]);
  const loading = ref(false);
  const syncing = ref(false);

  async function loadFeed(
    marketUserId: number,
    limit = 20,
    opts: { sync?: boolean } = {},
  ) {
    if (!marketUserId) {
      feed.value = [];
      return;
    }
    loading.value = true;
    try {
      const res = await wechatGroupBridgeApi.loadStarredGroupFeed(marketUserId, limit, {
        sync: opts.sync ?? false,
      });
      const page = (res as { data?: unknown[] })?.data;
      feed.value = Array.isArray(page)
        ? (page as Record<string, unknown>[])
        : [];
    } catch {
      feed.value = [];
    } finally {
      loading.value = false;
    }
  }

  async function syncGroups(bodyOrMarketUserId: WechatGroupSyncBody | number = {}) {
    syncing.value = true;
    try {
      const body = normalizeSyncBody(bodyOrMarketUserId);
      return await wechatGroupBridgeApi.syncGroups(body);
    } finally {
      syncing.value = false;
    }
  }

  function formatFeedItem(item: unknown): WechatFeedFormattedRow {
    const row = (item && typeof item === 'object' ? item : {}) as Record<string, unknown>;
    const contactId = Number(row.contact_id ?? row.contactId ?? 0);
    const name = String(row.contact_name || row.nickname || '群聊').trim();
    const raw = String(
      row.content || row.message || row.last_message_preview || '',
    ).trim();
    const sender = String(row.sender_display || '').trim();
    let subtitle = raw;
    if (sender && raw) subtitle = `${sender}: ${raw}`;
    else if (sender) subtitle = sender;
    const timeLabel = formatTimeLabel(
      row.last_message_time ?? row.timestamp ?? row.created_at,
    );
    return { contactId, name, subtitle, timeLabel };
  }

  return {
    feed,
    loading,
    syncing,
    loadFeed,
    syncGroups,
    formatFeedItem,
  };
}

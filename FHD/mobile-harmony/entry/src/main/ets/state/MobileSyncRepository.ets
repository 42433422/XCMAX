import { MobileApiClient } from '../api/MobileApiClient';
import { SyncAiChange, SyncApprovalRow, SyncPullData } from '../models/MobileModels';
import { OfflineDb } from './OfflineDb';
import { SessionStore } from './SessionStore';

// 增量同步仓库，对齐 Android core/sync/MobileSyncRepository.kt：
// 读 cursor → POST /sync/pull → 把 ai_changes 写 chat_cache、approvals 写 approval_cache →
// 更新 cursor + last_sync_at。需后端 /sync/pull（已存在）。真机/真后端联调未验。

export interface SyncSummary {
  ok: boolean;
  cursor: number;
  lastSyncAt: string;
  aiCount: number;
  approvalCount: number;
  error: string;
}

export class MobileSyncRepository {
  private api: MobileApiClient;
  private db: OfflineDb;
  private session: SessionStore;

  constructor(api: MobileApiClient, db: OfflineDb, session: SessionStore) {
    this.api = api;
    this.db = db;
    this.session = session;
  }

  async pullAndCache(): Promise<SyncSummary> {
    try {
      const since = await this.session.syncCursor();
      const data: SyncPullData = await this.api.syncPull(since);
      const cursor = data.cursor !== undefined && data.cursor !== null ? data.cursor : since;
      const now = new Date().toISOString();
      await this.session.setSyncCursor(cursor, now);

      let ts = new Date().getTime();
      const ai: SyncAiChange[] = data.ai_changes !== undefined && data.ai_changes !== null ? data.ai_changes : [];
      for (const c of ai) {
        await this.db.cacheChat(c.session_id, c.role, c.content, ts);
        ts += 1;
      }
      const approvals: SyncApprovalRow[] = data.approvals !== undefined && data.approvals !== null ? data.approvals : [];
      for (const a of approvals) {
        await this.db.cacheApproval(a.id, a.title, a.status, JSON.stringify(a), ts);
        ts += 1;
      }

      return {
        ok: true,
        cursor: cursor,
        lastSyncAt: now,
        aiCount: ai.length,
        approvalCount: approvals.length,
        error: ''
      };
    } catch (e) {
      const msg = (e as Error).message;
      return {
        ok: false,
        cursor: 0,
        lastSyncAt: '',
        aiCount: 0,
        approvalCount: 0,
        error: msg !== undefined && msg !== null && msg.length > 0 ? msg : '同步失败'
      };
    }
  }
}

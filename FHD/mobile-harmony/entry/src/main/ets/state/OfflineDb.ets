import relationalStore from '@ohos.data.relationalStore';
import common from '@ohos.app.ability.common';

// 离线缓存 DB，对齐 Android core/db/XcagiDatabase.kt（Room）：
// 缓存对话(chat_cache) + 审批(approval_cache)，供冷启动秒出与 sync 增量同步复用。
// 用 @ohos.data.relationalStore（SQLite）。真机持久化未验，本机仅保证编译与 SQL 契约。

export interface CachedChat {
  role: string;
  text: string;
  ts: number;
}

const DB_CONFIG: relationalStore.StoreConfig = {
  name: 'xcagi_cache.db',
  securityLevel: relationalStore.SecurityLevel.S1
};

const DDL_CHAT =
  'CREATE TABLE IF NOT EXISTS chat_cache (' +
  'id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, text TEXT, ts INTEGER)';
const DDL_APPROVAL =
  'CREATE TABLE IF NOT EXISTS approval_cache (' +
  'request_id INTEGER PRIMARY KEY, title TEXT, status TEXT, json TEXT, ts INTEGER)';

export class OfflineDb {
  private store: relationalStore.RdbStore | null = null;

  async init(context: common.Context): Promise<void> {
    if (this.store !== null) {
      return;
    }
    const s = await relationalStore.getRdbStore(context, DB_CONFIG);
    await s.executeSql(DDL_CHAT);
    await s.executeSql(DDL_APPROVAL);
    this.store = s;
  }

  async cacheChat(sessionId: string, role: string, text: string, ts: number): Promise<void> {
    const s = this.store;
    if (s === null) {
      return;
    }
    const vb: relationalStore.ValuesBucket = {
      session_id: sessionId,
      role: role,
      text: text,
      ts: ts
    };
    await s.insert('chat_cache', vb);
  }

  async recentChats(sessionId: string, limit: number): Promise<CachedChat[]> {
    const s = this.store;
    if (s === null) {
      return [];
    }
    const args: Array<relationalStore.ValueType> = [sessionId, limit];
    const rs = await s.querySql(
      'SELECT role, text, ts FROM chat_cache WHERE session_id = ? ORDER BY ts DESC LIMIT ?',
      args
    );
    const out: CachedChat[] = [];
    while (rs.goToNextRow()) {
      out.push({
        role: rs.getString(rs.getColumnIndex('role')),
        text: rs.getString(rs.getColumnIndex('text')),
        ts: rs.getLong(rs.getColumnIndex('ts'))
      });
    }
    rs.close();
    return out.reverse(); // 倒序取出后反转为时间正序
  }

  async cacheApproval(
    requestId: number,
    title: string,
    status: string,
    json: string,
    ts: number
  ): Promise<void> {
    const s = this.store;
    if (s === null) {
      return;
    }
    const vb: relationalStore.ValuesBucket = {
      request_id: requestId,
      title: title,
      status: status,
      json: json,
      ts: ts
    };
    await s.insert('approval_cache', vb, relationalStore.ConflictResolution.ON_CONFLICT_REPLACE);
  }

  async cachedApprovalsJson(): Promise<string[]> {
    const s = this.store;
    if (s === null) {
      return [];
    }
    const rs = await s.querySql('SELECT json FROM approval_cache ORDER BY ts DESC', []);
    const out: string[] = [];
    while (rs.goToNextRow()) {
      out.push(rs.getString(rs.getColumnIndex('json')));
    }
    rs.close();
    return out;
  }

  async clear(): Promise<void> {
    const s = this.store;
    if (s === null) {
      return;
    }
    await s.executeSql('DELETE FROM chat_cache');
    await s.executeSql('DELETE FROM approval_cache');
  }
}

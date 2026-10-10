import '../api/mobile_api.dart';
import '../api/mobile_models.dart';

/// 一次手动同步的结果；[conflicts] 为 `sync/conflicts` 的 items 原样行。
class MobileSyncResult {
  const MobileSyncResult(this.pushed, this.pulled, this.conflicts);

  final int pushed;
  final int pulled;
  final List<Map<String, Object?>> conflicts;

  String get summary => '已同步：推送 $pushed 条，拉取 $pulled 条变更，'
      '${conflicts.isEmpty ? '无冲突' : '${conflicts.length} 条冲突待处理'}';
}

/// 「同步」按钮：状态 → 推送 → 拉取（推进游标，只进不退）→ 冲突。
/// App 暂无离线写入队列，推送 items 为空，但会让服务端应用待处理收件箱。
/// 任一步失败抛出 `<步骤>失败：<原因>`，不推进游标。
Future<MobileSyncResult> runMobileSync(MobileApiClient api) async {
  Future<Map<String, Object?>> step(
    String label,
    Future<MobileEnvelope<Map<String, Object?>>> Function() call,
  ) async {
    try {
      final env = await call();
      if (env.success) return env.data ?? const {};
      throw env.message.ifEmpty('服务端返回失败');
    } on MobileApiException catch (e) {
      throw '$label失败：${e.message.ifEmpty('HTTP ${e.statusCode}')}';
    } catch (e) {
      throw '$label失败：$e';
    }
  }

  final since = (await api.loadSession()).syncCursor;
  await step('检查同步状态', api.syncStatus);
  final push = await step('推送本地变更', () => api.syncPush(const []));
  final pull = await step('拉取云端变更', () => api.syncPull(sinceCursor: since));
  final items = (await step('读取同步冲突', api.syncConflicts))['items'];
  final cursor = int.tryParse('${pull['cursor']}') ?? 0;
  await api.saveSyncState(
    syncCursor: cursor > since ? cursor : since,
    lastSyncAt: DateTime.now().toIso8601String(),
  );
  final changes = pull['changes'];
  return MobileSyncResult(
    int.tryParse('${push['written']}') ?? 0,
    changes is List ? changes.length : 0,
    [
      if (items is List)
        for (final row in items.whereType<Map>()) row.cast<String, Object?>(),
    ],
  );
}

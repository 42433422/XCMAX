part of 'profile_screen.dart';

// 同步冲突列表（只读展示；冲突由服务端/桌面端处理）。
Future<void> showMobileSyncConflictsSheet(
  BuildContext context,
  List<MobileSyncConflict> conflicts,
) {
  return showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    builder: (sheetContext) {
      final colors = AppTheme.colors(sheetContext);
      return SafeArea(
        child: ListView(
          key: const ValueKey('profile_sync_conflicts_sheet'),
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          children: [
            Text(
              '同步冲突（${conflicts.length}）',
              style: TextStyle(
                color: colors.textPrimary,
                fontSize: 16,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              '以下变更与云端记录冲突，未自动覆盖；请在电脑端或管理后台核对处理。',
              style: TextStyle(color: colors.textSecondary, fontSize: 12),
            ),
            const SizedBox(height: 8),
            for (final c in conflicts)
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Icon(Icons.sync_problem, color: colors.warning),
                title: Text(c.title),
                subtitle: Text(
                  [
                    if (c.note.isNotEmpty) c.note,
                    if (c.receivedAt.isNotEmpty) c.receivedAt,
                  ].join(' · ').ifEmpty('无说明'),
                ),
              ),
          ],
        ),
      );
    },
  );
}

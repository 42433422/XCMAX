import 'package:flutter/material.dart';

import '../../api/mobile_models.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

class NotificationListScreen extends StatefulWidget {
  const NotificationListScreen({super.key, this.repository});

  final MobileRepository? repository;

  @override
  State<NotificationListScreen> createState() => _NotificationListScreenState();
}

class _NotificationListScreenState extends State<NotificationListScreen> {
  late final MobileRepository _repository;
  late Future<List<_NotificationItem>> _future;
  final _readIds = <String>{};

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _future = _load();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const WeTopBar(title: '通知与公告'),
            Expanded(
              child: FutureBuilder<List<_NotificationItem>>(
                future: _future,
                builder: (context, snapshot) {
                  if (snapshot.connectionState != ConnectionState.done) {
                    return Center(
                      child: CircularProgressIndicator(color: colors.brand),
                    );
                  }
                  final items = snapshot.data ?? const <_NotificationItem>[];
                  if (items.isEmpty) {
                    return Center(
                      child: Text(
                        '暂无通知',
                        style: TextStyle(
                          color: colors.textSecondary,
                          fontSize: 16,
                          height: 1.38,
                          letterSpacing: 0,
                        ),
                      ),
                    );
                  }
                  return RefreshIndicator(
                    color: colors.brand,
                    onRefresh: _refresh,
                    child: ListView.builder(
                      physics: const AlwaysScrollableScrollPhysics(),
                      itemBuilder: (context, index) {
                        final item = items[index];
                        return _NotificationCell(
                          item: item,
                          isRead: item.read || _readIds.contains(item.id),
                          onTap: () => setState(() => _readIds.add(item.id)),
                        );
                      },
                      itemCount: items.length,
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<List<_NotificationItem>> _load() async {
    try {
      final notifications = await _repository.loadPendingNotifications();
      return notifications.map(_NotificationItem.fromPending).toList();
    } catch (_) {
      // Honest empty state — do not mask API failure with demo rows.
      return const <_NotificationItem>[];
    }
  }

  Future<void> _refresh() async {
    final future = _load();
    setState(() {
      _future = future;
    });
    await future;
  }
}

class _NotificationCell extends StatelessWidget {
  const _NotificationCell({
    required this.item,
    required this.isRead,
    required this.onTap,
  });

  final _NotificationItem item;
  final bool isRead;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final tint = item.type.tint(colors);
    return Material(
      color: isRead
          ? colors.surface
          : colors.brandContainer.withValues(alpha: 0.3),
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: tint.withValues(alpha: 0.12),
                  shape: BoxShape.circle,
                ),
                alignment: Alignment.center,
                child: Icon(item.type.icon, color: tint, size: 22),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            item.title,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              color: colors.textPrimary,
                              fontSize: 15,
                              height: 1.33,
                              fontWeight:
                                  isRead ? FontWeight.w500 : FontWeight.w700,
                              letterSpacing: 0,
                            ),
                          ),
                        ),
                        if (!isRead)
                          Container(
                            width: 8,
                            height: 8,
                            decoration: BoxDecoration(
                              color: colors.danger,
                              shape: BoxShape.circle,
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      item.content,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: colors.textSecondary,
                        fontSize: 14,
                        height: 1.36,
                        letterSpacing: 0,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      item.dateText,
                      style: TextStyle(
                        color: colors.textTertiary,
                        fontSize: 11,
                        height: 1.27,
                        letterSpacing: 0,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

enum _NotificationType {
  system(Icons.info),
  announcement(Icons.campaign),
  update(Icons.build),
  alert(Icons.warning),
  success(Icons.check_circle);

  const _NotificationType(this.icon);

  final IconData icon;

  Color tint(XcagiThemeColors colors) {
    return switch (this) {
      _NotificationType.system => colors.brand,
      _NotificationType.announcement => colors.brand,
      _NotificationType.update => colors.success,
      _NotificationType.alert => colors.danger,
      _NotificationType.success => colors.success,
    };
  }
}

class _NotificationItem {
  const _NotificationItem({
    required this.id,
    required this.type,
    required this.title,
    required this.content,
    required this.dateText,
  });

  final String id;
  final _NotificationType type;
  final String title;
  final String content;
  final String dateText;
  final bool read = false;

  factory _NotificationItem.fromPending(PendingNotification notification) {
    return _NotificationItem(
      id: '${notification.id}',
      type: _typeFromChannel(notification.channel),
      title: notification.title.ifEmpty('系统通知'),
      content: notification.body,
      dateText: '刚刚',
    );
  }
}

_NotificationType _typeFromChannel(String channel) {
  final key = channel.trim().toLowerCase();
  if (key.contains('announce')) return _NotificationType.announcement;
  if (key.contains('update')) return _NotificationType.update;
  if (key.contains('alert') || key.contains('warning')) {
    return _NotificationType.alert;
  }
  if (key.contains('success') || key.contains('task')) {
    return _NotificationType.success;
  }
  return _NotificationType.system;
}

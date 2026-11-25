import 'dart:async';

import 'package:flutter/material.dart';
import '../../api/mobile_session_store.dart' show MobileSessionData;
import '../../policy/mobile_error_policy.dart';

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

class _NotificationListScreenState extends State<NotificationListScreen>
    with WidgetsBindingObserver {
  late final MobileRepository _repository;
  late Future<List<_NotificationItem>> _future;
  late final int _generation;
  StreamSubscription<MobileSessionData>? _sessionSubscription;
  Timer? _poll;
  bool _loading = false;
  bool _marking = false;
  bool get _revoked => _generation != _repository.client.authGeneration;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _generation = _repository.client.authGeneration;
    _sessionSubscription = _repository.client.sessionChanges.listen((_) {
      if (mounted && _revoked) setState(() {});
    });
    WidgetsBinding.instance.addObserver(this);
    _future = _load();
    _startPolling();
  }

  void _startPolling() {
    _poll?.cancel();
    _poll = Timer.periodic(const Duration(seconds: 10), (_) {
      if (mounted && !_revoked && ModalRoute.of(context)?.isCurrent != false) {
        unawaited(_refresh());
      }
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      unawaited(_refresh());
      _startPolling();
    } else {
      _poll?.cancel();
    }
  }

  @override
  void dispose() {
    _poll?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    unawaited(_sessionSubscription?.cancel());
    super.dispose();
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
            WeTopBar(title: '通知与公告', actions: [
              IconButton(onPressed: _revoked ? null : _refresh,
                  icon: const Icon(Icons.refresh), tooltip: '刷新通知'),
            ]),
            Expanded(
              child: FutureBuilder<List<_NotificationItem>>(
                future: _future,
                builder: (context, snapshot) {
                  if (_revoked) return const Center(child: Text('账号已切换，请重新打开通知'));
                  if (snapshot.hasError) {
                    return Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
                      Text(mobileErrorText(snapshot.error)),
                      TextButton(onPressed: _refresh, child: const Text('重试')),
                    ]));
                  }
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
                          isRead: item.read,
                          onTap: () => unawaited(_markRead(item)),
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
    if (_revoked) throw StateError('账号已切换');
    final notifications = await _repository.loadNotificationInbox();
    if (_revoked) throw StateError('账号已切换');
    final unique = {for (final item in notifications) if (item.id > 0) item.id: _NotificationItem.fromPending(item)};
    return unique.values.toList();
  }

  Future<void> _refresh() async {
    if (!mounted || _revoked || _loading || _marking) return;
    _loading = true;
    final future = _load();
    setState(() => _future = future);
    try { await future; } catch (_) {
      // FutureBuilder renders the real error.
    } finally { _loading = false; }
  }

  Future<void> _markRead(_NotificationItem item) async {
    if (_revoked || _marking || _loading || item.read) return;
    final id = int.tryParse(item.id);
    if (id == null || id <= 0) return;
    _marking = true;
    try {
      await _repository.markNotificationRead(id);
    } catch (error) {
      if (mounted && !_revoked) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(mobileErrorText(error))));
      }
    } finally {
      _marking = false;
      await _refresh();
    }
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
    required this.read,
  });

  final String id;
  final _NotificationType type;
  final String title;
  final String content;
  final String dateText;
  final bool read;

  factory _NotificationItem.fromPending(PendingNotification notification) {
    return _NotificationItem(
      id: '${notification.id}',
      type: _typeFromChannel(notification.channel),
      title: notification.title.ifEmpty('系统通知'),
      content: notification.body,
      dateText: notification.createdAt,
      read: notification.isRead,
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

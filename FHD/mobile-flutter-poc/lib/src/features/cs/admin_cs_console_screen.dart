import 'package:flutter/material.dart';

import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../models/conversation.dart';
import '../../policy/avatar_policy.dart';
import '../../theme/app_theme.dart';
import '../../theme/message_avatar_layout.dart';
import '../../widgets/app_avatar.dart';
import '../../widgets/we_ui.dart';

class AdminCsConsoleScreen extends StatefulWidget {
  const AdminCsConsoleScreen({super.key, this.repository, this.initialInbox});

  final MobileRepository? repository;
  final List<AdminCsInboxItem>? initialInbox;

  @override
  State<AdminCsConsoleScreen> createState() => _AdminCsConsoleScreenState();
}

class _AdminCsConsoleScreenState extends State<AdminCsConsoleScreen> {
  late final MobileRepository _repository;
  late Future<List<AdminCsInboxItem>> _inboxFuture;
  AdminCsInboxItem? _selected;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _inboxFuture = _loadInbox();
  }

  @override
  Widget build(BuildContext context) {
    final selected = _selected;
    if (selected != null) {
      return _AdminCsConversationScreen(
        repository: _repository,
        conversation: selected,
        onBack: () => setState(() => _selected = null),
      );
    }

    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.surface,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: '客户客服',
              showBack: Navigator.of(context).canPop(),
              onBack: Navigator.of(context).canPop()
                  ? () => Navigator.of(context).maybePop()
                  : null,
              actions: [
                IconButton(
                  onPressed: _refreshInbox,
                  icon: const Icon(Icons.refresh),
                  color: colors.textPrimary,
                  tooltip: '刷新',
                ),
              ],
            ),
            Expanded(
              child: FutureBuilder<List<AdminCsInboxItem>>(
                future: _inboxFuture,
                builder: (context, snapshot) {
                  final loading =
                      snapshot.connectionState == ConnectionState.waiting;
                  final items =
                      snapshot.data ?? widget.initialInbox ?? const [];
                  if (loading && items.isEmpty) {
                    return Center(
                      child: CircularProgressIndicator(color: colors.brand),
                    );
                  }
                  return RefreshIndicator(
                    color: colors.brand,
                    onRefresh: _refreshInbox,
                    child: items.isEmpty
                        ? _AdminCsEmptyInbox()
                        : ListView.separated(
                            physics: const AlwaysScrollableScrollPhysics(),
                            itemCount: items.length,
                            separatorBuilder: (_, __) => Divider(
                              height: 0.5,
                              thickness: 0.5,
                              indent:
                                  MessageAvatarLayout.conversationDividerStart,
                              color: Theme.of(
                                context,
                              ).colorScheme.outlineVariant,
                            ),
                            itemBuilder: (context, index) {
                              final item = items[index];
                              return _AdminCsInboxRow(
                                item: item,
                                onTap: () => setState(() => _selected = item),
                              );
                            },
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

  Future<List<AdminCsInboxItem>> _loadInbox() async {
    return widget.initialInbox ?? _repository.loadAdminCsInbox();
  }

  Future<void> _refreshInbox() async {
    final future = _repository.loadAdminCsInbox();
    setState(() => _inboxFuture = future);
    await future;
  }
}

class _AdminCsInboxRow extends StatelessWidget {
  const _AdminCsInboxRow({required this.item, required this.onTap});

  final AdminCsInboxItem item;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final name = item.customerName.ifEmpty('客户');
    final time = item.lastMessageAt.replaceAll('T', ' ').take(19);
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          children: [
            _CustomerAvatar(name: name),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: colors.textPrimary,
                      fontSize: 16,
                      height: 1.3,
                      fontWeight: FontWeight.w600,
                      letterSpacing: 0,
                    ),
                  ),
                  if (time.isNotEmpty) ...[
                    const SizedBox(height: 3),
                    Text(
                      time,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: colors.textTertiary,
                        fontSize: 13,
                        height: 1.31,
                        letterSpacing: 0,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            if (item.unreadCount > 0)
              Container(
                constraints: const BoxConstraints(minWidth: 22, minHeight: 22),
                padding: const EdgeInsets.symmetric(horizontal: 6),
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: colors.danger,
                  borderRadius: BorderRadius.circular(11),
                ),
                child: Text(
                  '${item.unreadCount}',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 12,
                    height: 1,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _AdminCsEmptyInbox extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: [
        SizedBox(height: MediaQuery.sizeOf(context).height * 0.24),
        Icon(Icons.support_agent, size: 48, color: colors.textTertiary),
        const SizedBox(height: 14),
        Text(
          '暂无客户咨询',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: colors.textSecondary,
            fontSize: 15,
            height: 1.4,
            letterSpacing: 0,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          '客户在「专属客服」发起咨询后会出现在这里',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: colors.textTertiary,
            fontSize: 13,
            height: 1.31,
            letterSpacing: 0,
          ),
        ),
      ],
    );
  }
}

part 'admin_cs_console_conversation.part.dart';
part 'admin_cs_console_widgets.part.dart';

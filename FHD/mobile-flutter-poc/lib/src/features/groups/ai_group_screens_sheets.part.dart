part of 'ai_group_screens.dart';

// 动作面板与群聊/群列表空状态组件。
class _AiGroupSheetAction {
  const _AiGroupSheetAction({
    required this.label,
    required this.onTap,
    this.danger = false,
  });

  final String label;
  final VoidCallback onTap;
  final bool danger;
}

class _AiGroupActionSheet extends StatelessWidget {
  const _AiGroupActionSheet({required this.title, required this.actions});

  final String title;
  final List<_AiGroupSheetAction> actions;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (title.isNotEmpty) ...[
              Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: 20,
                  vertical: 12,
                ),
                child: Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: colors.textSecondary,
                    fontSize: 13,
                    height: 1.31,
                    fontWeight: FontWeight.w500,
                    letterSpacing: 0,
                  ),
                ),
              ),
              const Divider(height: 1),
            ],
            for (var index = 0; index < actions.length; index++) ...[
              SizedBox(
                height: 52,
                width: double.infinity,
                child: TextButton(
                  onPressed: actions[index].onTap,
                  style: TextButton.styleFrom(
                    foregroundColor: actions[index].danger
                        ? colors.danger
                        : colors.textPrimary,
                    shape: const RoundedRectangleBorder(),
                  ),
                  child: Text(
                    actions[index].label,
                    style: TextStyle(
                      color: actions[index].danger
                          ? colors.danger
                          : colors.textPrimary,
                      fontSize: 16,
                      height: 1.35,
                      fontWeight: FontWeight.w400,
                      letterSpacing: 0,
                    ),
                  ),
                ),
              ),
              if (index < actions.length - 1) const Divider(height: 1),
            ],
          ],
        ),
      ),
    );
  }
}

class _GroupEmptyState extends StatelessWidget {
  const _GroupEmptyState();

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Center(
      child: Text('暂无群聊，点右上角创建', style: TextStyle(color: colors.textSecondary)),
    );
  }
}

class _GroupChatEmptyState extends StatelessWidget {
  const _GroupChatEmptyState({required this.group});

  final AiGroupConversation group;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final emptyMembers = group.memberCount == 0;
    return Center(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(40, 0, 40, 40),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            GroupGridAvatar(members: group.members, size: 64),
            const SizedBox(height: 16),
            Text(
              emptyMembers ? '群里还没有 AI 成员' : '群里安静得很',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: colors.textPrimary,
                fontSize: 16,
                height: 1.38,
                fontWeight: FontWeight.w500,
                letterSpacing: 0,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              emptyMembers ? '点右上角把 AI 员工拉进群，然后开聊' : '发条消息，群成员会各自回复你',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: colors.textSecondary,
                fontSize: 14,
                height: 1.36,
                letterSpacing: 0,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

extension on String {
  String ifEmpty(String fallback) => trim().isEmpty ? fallback : this;

  String take(int length) {
    final value = trim();
    return value.length <= length ? value : value.substring(0, length);
  }
}

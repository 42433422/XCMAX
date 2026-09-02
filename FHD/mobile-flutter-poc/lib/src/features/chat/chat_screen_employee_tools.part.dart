part of 'chat_screen.dart';

// 超级员工会话解析与工具卡片组件。
class _EmployeeConversationRef {
  const _EmployeeConversationRef({
    required this.modId,
    required this.employeeId,
  });

  final String modId;
  final String employeeId;
}

_EmployeeConversationRef? _parseEmployeeConversationRef(
  String? conversationId,
) {
  final raw = conversationId?.trim() ?? '';
  if (!raw.startsWith('employee:')) return null;
  final parts = raw.split(':');
  if (parts.length != 3) return null;
  final modId = parts[1].trim();
  final employeeId = parts[2].trim();
  if (modId.isEmpty || employeeId.isEmpty) return null;
  return _EmployeeConversationRef(modId: modId, employeeId: employeeId);
}

AiEmployeeProfile? _findEmployeeProfile(
  List<AiEmployeeProfile> employees,
  _EmployeeConversationRef ref,
) {
  for (final employee in employees) {
    if (employee.modId == ref.modId && employee.employeeId == ref.employeeId) {
      return employee;
    }
  }
  return null;
}

AiEmployeeProfile? _employeePlaceholderFromRef(_EmployeeConversationRef? ref) {
  if (ref == null) return null;
  return AiEmployeeProfile(
    modId: ref.modId,
    modName: ref.modId,
    modDescription: '',
    modVersion: '',
    modAuthor: '',
    industryName: '',
    employeeId: ref.employeeId,
    name: ref.employeeId,
    title: ref.employeeId,
    summary: '稍后刷新或从企业端同步数据',
    apiBasePath: '',
    phoneChannel: '',
    workflowPlaceholder: false,
    profileSource: 'conversation-ref',
    marketConnected: false,
    marketPkgId: '',
    marketVersion: '',
    marketAuthor: '',
    marketMaterialCategory: '',
    marketLicenseScope: '',
    marketSecurityLevel: '',
  );
}

String _shortGitBranchLabel(String branch) {
  final clean = branch.trim();
  final index = clean.lastIndexOf('/');
  if (index < 0 || index == clean.length - 1) return clean;
  return clean.substring(index + 1);
}

String _take(String value, int maxLength) {
  final text = value.trim();
  if (text.length <= maxLength) return text;
  return text.substring(0, maxLength);
}

class _ChatToolAction {
  const _ChatToolAction({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;
}

class _ChatToolCardPanel extends StatelessWidget {
  const _ChatToolCardPanel({required this.actions});

  final List<_ChatToolAction> actions;

  @override
  Widget build(BuildContext context) {
    const columns = 4;
    final rows = <List<_ChatToolAction>>[];
    for (var start = 0; start < actions.length; start += columns) {
      final end = (start + columns).clamp(0, actions.length);
      rows.add(actions.sublist(start, end));
    }

    return Padding(
      key: const ValueKey('chat_tool_card_panel'),
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 20),
      child: Column(
        children: [
          for (var rowIndex = 0; rowIndex < rows.length; rowIndex++) ...[
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (var index = 0; index < columns; index++) ...[
                  Expanded(
                    child: index < rows[rowIndex].length
                        ? _ChatToolCard(action: rows[rowIndex][index])
                        : const SizedBox(height: 92),
                  ),
                  if (index != columns - 1) const SizedBox(width: 12),
                ],
              ],
            ),
            if (rowIndex != rows.length - 1) const SizedBox(height: 18),
          ],
        ],
      ),
    );
  }
}

class _ChatToolCard extends StatelessWidget {
  const _ChatToolCard({required this.action});

  final _ChatToolAction action;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return SizedBox(
      key: ValueKey('chat_tool_card_${action.title}'),
      height: 92,
      child: Material(
        color: Colors.transparent,
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          onTap: action.onTap,
          borderRadius: BorderRadius.circular(8),
          child: Padding(
            padding: const EdgeInsets.only(top: 1),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Container(
                  key: ValueKey('chat_tool_icon_box_${action.title}'),
                  width: 62,
                  height: 62,
                  decoration: BoxDecoration(
                    color: colors.surfaceHigh.withValues(alpha: 0.62),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  alignment: Alignment.center,
                  child: Icon(
                    action.icon,
                    size: 27,
                    color: colors.textPrimary,
                    semanticLabel: action.title,
                  ),
                ),
                const SizedBox(height: 8),
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 82),
                  child: Text(
                    action.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.center,
                    style: textTheme.labelMedium?.copyWith(
                      color: colors.textSecondary,
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SendPill extends StatelessWidget {
  const _SendPill({
    required this.canStop,
    required this.onSend,
    required this.onStop,
  });

  final bool canStop;
  final VoidCallback onSend;
  final VoidCallback onStop;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return Material(
      color:
          canStop ? Theme.of(context).colorScheme.errorContainer : colors.brand,
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        onTap: canStop ? onStop : onSend,
        borderRadius: BorderRadius.circular(8),
        child: SizedBox(
          height: 38,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 17),
            child: Center(
              child: Text(
                canStop ? '停止' : '发送',
                style: textTheme.labelLarge?.copyWith(
                  color: canStop ? colors.danger : Colors.white,
                  fontSize: 15,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

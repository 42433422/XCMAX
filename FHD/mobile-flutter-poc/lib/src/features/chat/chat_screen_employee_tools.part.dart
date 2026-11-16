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
    summary: '',
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
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final VoidCallback onTap;
}

class _ChatToolCardPanel extends StatelessWidget {
  const _ChatToolCardPanel({required this.actions});

  final List<_ChatToolAction> actions;

  @override
  Widget build(BuildContext context) {
    final fontSize = MediaQuery.textScalerOf(context).scale(13);
    final lineHeight =
        fontSize * (Theme.of(context).textTheme.labelMedium?.height ?? 1.3);
    return Padding(
      key: const ValueKey('chat_tool_card_panel'),
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 20),
      child: LayoutBuilder(builder: (context, constraints) {
        final columns =
            ((constraints.maxWidth + 12) / (max(82.0, fontSize * 5) + 12))
                .floor()
                .clamp(1, 4);
        final compact = columns == 4 && fontSize <= 13;
        final height = compact ? 92.0 : max(92.0, 75 + lineHeight * 2);
        return Column(
          children: [
            for (var start = 0; start < actions.length; start += columns) ...[
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (var index = 0; index < columns; index++) ...[
                    Expanded(
                      child: start + index < actions.length
                          ? _ChatToolCard(
                              action: actions[start + index],
                              height: height,
                              maxLines: compact ? 1 : 2)
                          : SizedBox(height: height),
                    ),
                    if (index != columns - 1) const SizedBox(width: 12),
                  ],
                ],
              ),
              if (start + columns < actions.length) const SizedBox(height: 18),
            ],
          ],
        );
      }),
    );
  }
}

class _ChatToolCard extends StatelessWidget {
  const _ChatToolCard(
      {required this.action, required this.height, required this.maxLines});

  final _ChatToolAction action;
  final double height;
  final int maxLines;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return SizedBox(
      key: ValueKey('chat_tool_card_${action.title}'),
      height: height,
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
                  constraints: BoxConstraints(
                      maxWidth: maxLines == 1 ? 82 : double.infinity),
                  child: Text(
                    action.title,
                    maxLines: maxLines,
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

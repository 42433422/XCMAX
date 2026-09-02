part of 'ai_group_screens.dart';

// 群聊输入栏、发送按钮与工具面板组件。
class _GroupInputBar extends StatelessWidget {
  const _GroupInputBar({
    required this.controller,
    required this.sending,
    required this.showTools,
    required this.selectedBranch,
    required this.workMode,
    required this.onToggleTools,
    required this.onVoice,
    required this.onSend,
    required this.onBranch,
    required this.onMembers,
    required this.onSelectMode,
    required this.onClearMode,
  });

  final TextEditingController controller;
  final bool sending;
  final bool showTools;
  final String selectedBranch;
  final GroupWorkMode? workMode;
  final VoidCallback onToggleTools;
  final VoidCallback onVoice;
  final VoidCallback onSend;
  final VoidCallback onBranch;
  final VoidCallback onMembers;
  final ValueChanged<GroupWorkMode> onSelectMode;
  final VoidCallback onClearMode;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final textTheme = theme.textTheme;
    final branchLabel =
        selectedBranch.trim().isEmpty ? '自动新建' : selectedBranch.split('/').last;
    final toolActions = [
      _GroupToolAction(Icons.call_merge, '工作分支', onBranch),
      _GroupToolAction(Icons.group_add, '群成员', onMembers),
      _GroupToolAction(Icons.mic, '语音输入', onVoice),
      _GroupToolAction(
        Icons.groups,
        '任务派工',
        () => onSelectMode(GroupWorkMode.dispatch),
      ),
      _GroupToolAction(
        Icons.check,
        '验收回访',
        () => onSelectMode(GroupWorkMode.followup),
      ),
      _GroupToolAction(
        Icons.refresh,
        '问题修复',
        () => onSelectMode(GroupWorkMode.bugfix),
      ),
    ];
    return SafeArea(
      top: false,
      child: Container(
        key: const ValueKey('group_input_bar_surface'),
        decoration: BoxDecoration(
          color: colors.surface,
          border: Border(
            top: BorderSide(color: colorScheme.outlineVariant, width: 0.5),
          ),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: double.infinity,
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 8,
                ),
                child: Row(
                  children: [
                    _ComposerChip(
                      key: const ValueKey('group_branch_chip'),
                      icon: Icons.call_merge,
                      label: '工作分支 · $branchLabel',
                      onTap: onBranch,
                    ),
                    if (workMode != null) ...[
                      const SizedBox(width: 8),
                      _ComposerChip(
                        key: const ValueKey('group_work_mode_chip'),
                        icon: workMode!.icon,
                        label: '工作模式 · ${workMode!.label}',
                        active: true,
                        trailingIcon: Icons.close,
                        onTap: onClearMode,
                      ),
                    ],
                  ],
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
              child: ValueListenableBuilder<TextEditingValue>(
                valueListenable: controller,
                builder: (context, value, _) {
                  final canSend = (value.text.trim().isNotEmpty ||
                          workMode == GroupWorkMode.followup) &&
                      !sending;
                  return Row(
                    children: [
                      _GroupComposerIconButton(
                        icon: Icons.mic,
                        tooltip: '语音',
                        onTap: onVoice,
                      ),
                      const SizedBox(width: 6),
                      Expanded(
                        child: SizedBox(
                          height: 38,
                          child: DecoratedBox(
                            decoration: BoxDecoration(
                              color: colors.surface,
                              borderRadius: BorderRadius.circular(10),
                            ),
                            child: TextField(
                              controller: controller,
                              maxLines: 1,
                              textInputAction: TextInputAction.send,
                              onSubmitted: (_) {
                                if (canSend) onSend();
                              },
                              decoration: InputDecoration(
                                isCollapsed: true,
                                contentPadding: const EdgeInsets.symmetric(
                                  horizontal: 12,
                                  vertical: 9,
                                ),
                                border: InputBorder.none,
                                hintText:
                                    workMode?.placeholder ?? '发群消息（@成员 可单独点名）',
                                hintMaxLines: 1,
                                hintStyle: textTheme.bodyMedium?.copyWith(
                                  color: colors.textSecondary,
                                  fontSize: 15,
                                ),
                              ),
                              style: textTheme.bodyMedium?.copyWith(
                                color: colors.textPrimary,
                                fontSize: 15,
                              ),
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 6),
                      _GroupComposerIconButton(
                        icon: Icons.add,
                        iconSize: 26,
                        selected: showTools,
                        tooltip: '更多工具',
                        onTap: onToggleTools,
                      ),
                      if (canSend) ...[
                        const SizedBox(width: 6),
                        _GroupSendPill(onTap: onSend),
                      ],
                    ],
                  );
                },
              ),
            ),
            if (showTools)
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 8, 12, 16),
                child: _GroupToolPanel(actions: toolActions),
              ),
          ],
        ),
      ),
    );
  }
}

class _GroupComposerIconButton extends StatelessWidget {
  const _GroupComposerIconButton({
    required this.icon,
    required this.tooltip,
    required this.onTap,
    this.selected = false,
    this.iconSize = 22,
  });

  final IconData icon;
  final String tooltip;
  final VoidCallback onTap;
  final bool selected;
  final double iconSize;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return IconButton(
      onPressed: onTap,
      tooltip: tooltip,
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints.tightFor(width: 38, height: 38),
      style: IconButton.styleFrom(
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
      ),
      icon: Icon(
        icon,
        size: iconSize,
        color: selected ? colors.brand : colors.textPrimary,
      ),
    );
  }
}

class _GroupSendPill extends StatelessWidget {
  const _GroupSendPill({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        height: 38,
        padding: const EdgeInsets.symmetric(horizontal: 17),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: colors.brand,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          '发送',
          style: textTheme.labelLarge?.copyWith(
            color: colors.surface,
            fontSize: 15,
            fontWeight: FontWeight.w500,
          ),
        ),
      ),
    );
  }
}

class _GroupToolAction {
  const _GroupToolAction(this.icon, this.label, this.onTap);

  final IconData icon;
  final String label;
  final VoidCallback onTap;
}

class _GroupToolPanel extends StatelessWidget {
  const _GroupToolPanel({required this.actions});

  final List<_GroupToolAction> actions;

  @override
  Widget build(BuildContext context) {
    final rows = <Widget>[];
    for (var index = 0; index < actions.length; index += 4) {
      final rowActions = actions.skip(index).take(4).toList();
      rows.add(
        Row(
          children: [
            for (var i = 0; i < 4; i++) ...[
              if (i > 0) const SizedBox(width: 12),
              Expanded(
                child: i < rowActions.length
                    ? _ToolTile(rowActions[i])
                    : const SizedBox.shrink(),
              ),
            ],
          ],
        ),
      );
      if (index + 4 < actions.length) {
        rows.add(const SizedBox(height: 18));
      }
    }
    return Column(mainAxisSize: MainAxisSize.min, children: rows);
  }
}

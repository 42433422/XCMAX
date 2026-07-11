import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';

enum MeetingMinutesOrganizationMode { smart, local }

Future<MeetingMinutesOrganizationMode?>
    showMeetingMinutesOrganizationModePicker(
  BuildContext context,
) {
  final colors = AppTheme.colors(context);
  return showModalBottomSheet<MeetingMinutesOrganizationMode>(
    context: context,
    showDragHandle: true,
    backgroundColor: colors.surface,
    builder: (context) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(18, 4, 18, 18),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '选择 Word 整理方式',
              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    color: colors.textPrimary,
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: 6),
            Text(
              '你可以使用小C智能整理，也可以完全不上传转写文本。',
              style: TextStyle(color: colors.textSecondary),
            ),
            const SizedBox(height: 14),
            _OrganizationChoice(
              key: const ValueKey('meeting_mode_smart'),
              icon: Icons.auto_awesome_outlined,
              title: '小C智能整理（推荐）',
              description: '转写文本会发送到当前企业服务，并按系统审计策略留痕。',
              onTap: () => Navigator.pop(
                context,
                MeetingMinutesOrganizationMode.smart,
              ),
            ),
            const SizedBox(height: 10),
            _OrganizationChoice(
              key: const ValueKey('meeting_mode_local'),
              icon: Icons.phone_android_outlined,
              title: '仅本地生成',
              description: '不上传转写文本，按当前内容生成基础 Word，可继续编辑。',
              onTap: () => Navigator.pop(
                context,
                MeetingMinutesOrganizationMode.local,
              ),
            ),
          ],
        ),
      ),
    ),
  );
}

class _OrganizationChoice extends StatelessWidget {
  const _OrganizationChoice({
    super.key,
    required this.icon,
    required this.title,
    required this.description,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String description;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Material(
      color: colors.page,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              Icon(icon, color: colors.brand),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: TextStyle(
                        color: colors.textPrimary,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      description,
                      style: TextStyle(
                        color: colors.textSecondary,
                        fontSize: 13,
                      ),
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: colors.textSecondary),
            ],
          ),
        ),
      ),
    );
  }
}

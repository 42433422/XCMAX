import 'package:flutter/material.dart';

import '../../data/ai_employee_profile.dart';
import '../../data/mobile_repository.dart';
import '../../models/conversation.dart';
import '../../policy/avatar_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/app_avatar.dart';
import '../../widgets/we_ui.dart';
import '../bridge/bridge_screen.dart';
import '../circle/ai_circle_screen.dart';
import '../chat/chat_screen.dart';

class AiEmployeeProfileScreen extends StatefulWidget {
  const AiEmployeeProfileScreen({
    super.key,
    required AiEmployeeProfile employee,
    this.repository,
  }) : initialEmployee = employee;

  final AiEmployeeProfile initialEmployee;
  final MobileRepository? repository;

  AiEmployeeProfile get employee => initialEmployee;
  String get modId => initialEmployee.modId;
  String get employeeId => initialEmployee.employeeId;

  @override
  State<AiEmployeeProfileScreen> createState() =>
      _AiEmployeeProfileScreenState();
}

class _AiEmployeeProfileScreenState extends State<AiEmployeeProfileScreen> {
  late final MobileRepository _repository;
  late Future<AiEmployeeProfile?> _employeeFuture;

  @override
  void initState() {
    super.initState();
    _repository = widget.repository ?? MobileRepository();
    _employeeFuture = _loadEmployee();
  }

  Future<AiEmployeeProfile?> _loadEmployee() async {
    if (widget.repository == null) {
      return widget.initialEmployee;
    }
    final employees = await _repository.loadAiEmployees();
    for (final employee in employees) {
      if (employee.modId == widget.modId &&
          employee.employeeId == widget.employeeId) {
        return employee;
      }
    }
    return null;
  }

  void _refresh() {
    setState(() {
      _employeeFuture = _loadEmployee();
    });
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: FutureBuilder<AiEmployeeProfile?>(
          future: _employeeFuture,
          builder: (context, snapshot) {
            final employee = snapshot.data ??
                (snapshot.connectionState == ConnectionState.done
                    ? null
                    : widget.initialEmployee);
            return Column(
              children: [
                WeTopBar(
                  title: '',
                  showBack: true,
                  onBack: () => Navigator.of(context).maybePop(),
                ),
                Expanded(
                  child: employee == null
                      ? _EmployeeNotFoundState(onRetry: _refresh)
                      : _EmployeeProfileBody(
                          employee: employee,
                          onOpenChat: () => _openChat(context, employee),
                          onOpenCircle: () => _openCircle(context),
                        ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  void _openChat(BuildContext context, AiEmployeeProfile employee) {
    if (employee.employeeId.trim() == 'user-customer-service-officer') {
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => BridgeScreen.customerService(repository: _repository),
        ),
      );
      return;
    }
    final conversation = ConversationItem(
      id: 'employee:${employee.modId}:${employee.employeeId}',
      type: ConversationType.aiTask,
      title: employee.name,
      subtitle: employee.summary,
      timestampText: '',
    );
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ChatScreen(
          conversation: conversation,
          initialMessages: const [],
          repository: _repository,
        ),
      ),
    );
  }

  void _openCircle(BuildContext context) {
    Navigator.of(context).push(
      MaterialPageRoute(
          builder: (_) => AiCircleScreen(repository: _repository)),
    );
  }
}

class _EmployeeProfileBody extends StatelessWidget {
  const _EmployeeProfileBody({
    required this.employee,
    required this.onOpenChat,
    required this.onOpenCircle,
  });

  final AiEmployeeProfile employee;
  final VoidCallback onOpenChat;
  final VoidCallback onOpenCircle;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.only(bottom: 28),
      children: [
        _ContactHeader(employee: employee),
        const SizedBox(height: 8),
        _PlainCell(
          title: '员工资料',
          subtitle: employee.summary,
          showArrow: true,
        ),
        const SizedBox(height: 8),
        _CirclePreview(
          employee: employee,
          onTap: onOpenCircle,
        ),
        const SizedBox(height: 8),
        _PlainCell(
          title: '能做什么',
          subtitle: employee.abilityLabels().join('、'),
        ),
        const SizedBox(height: 8),
        _PlainCell(title: '来源', subtitle: employee.sourceLabel),
        const SizedBox(height: 8),
        _ActionRow(
          text: '发消息',
          icon: Icons.chat,
          onTap: onOpenChat,
        ),
        const SizedBox(height: 8),
        _ActionRow(
          text: '进入 AI 交流圈',
          icon: Icons.forum,
          onTap: onOpenCircle,
        ),
      ],
    );
  }
}

class _EmployeeNotFoundState extends StatelessWidget {
  const _EmployeeNotFoundState({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              padding: const EdgeInsets.all(18),
              decoration: BoxDecoration(
                color: colors.surfaceHigh,
                borderRadius: BorderRadius.circular(18),
              ),
              child: Icon(
                Icons.inbox,
                color: colors.textSecondary,
              ),
            ),
            const SizedBox(height: 16),
            Text(
              '未找到该 AI 员工',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: colors.textPrimary,
                fontSize: 17,
                height: 1.29,
                fontWeight: FontWeight.w500,
                letterSpacing: 0,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              '稍后刷新或从企业端同步数据',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: colors.textSecondary,
                fontSize: 13,
                height: 1.38,
                letterSpacing: 0,
              ),
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: onRetry,
              style: ElevatedButton.styleFrom(
                backgroundColor: colors.brand,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
              ),
              child: const Text('刷新'),
            ),
          ],
        ),
      ),
    );
  }
}

class _ContactHeader extends StatelessWidget {
  const _ContactHeader({required this.employee});

  final AiEmployeeProfile employee;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      color: colors.surface,
      padding: const EdgeInsets.fromLTRB(24, 18, 22, 18),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AppAvatar(
            imageSource: employee.avatarUrl,
            fallback: employeeAvatarFallback(
              employeeId: employee.employeeId,
              name: employee.name,
            ),
            size: 62,
            borderRadius: BorderRadius.circular(31),
            contentDescription: employee.name,
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  employee.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: colors.textPrimary,
                    fontSize: 18,
                    height: 1.33,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 0,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  '昵称：${employee.title}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: _bodyStyle(colors),
                ),
                const SizedBox(height: 5),
                Text(
                  'AI号：${employee.employeeId}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: _bodyStyle(colors),
                ),
                const SizedBox(height: 5),
                Text(
                  '来源：${employee.sourceLabel}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
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
        ],
      ),
    );
  }
}

class _PlainCell extends StatelessWidget {
  const _PlainCell({
    required this.title,
    required this.subtitle,
    this.showArrow = false,
  });

  final String title;
  final String subtitle;
  final bool showArrow;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      color: colors.surface,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: _titleStyle(colors)),
                if (subtitle.trim().isNotEmpty) ...[
                  const SizedBox(height: 6),
                  Text(
                    subtitle,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: colors.textSecondary,
                      fontSize: 14,
                      height: 1.36,
                      letterSpacing: 0,
                    ),
                  ),
                ],
              ],
            ),
          ),
          if (showArrow)
            Icon(Icons.chevron_right, size: 20, color: colors.textSecondary),
        ],
      ),
    );
  }
}

class _CirclePreview extends StatelessWidget {
  const _CirclePreview({required this.employee, required this.onTap});

  final AiEmployeeProfile employee;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final abilities = employee.abilityLabels().take(3).toList(growable: false);
    return Material(
      color: colors.surface,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          child: Column(
            children: [
              Row(
                children: [
                  Icon(
                    Icons.forum,
                    size: 20,
                    color: colors.momentAccent,
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('AI交流圈', style: _titleStyle(colors)),
                        const SizedBox(height: 2),
                        Text(
                          '进入交流圈 · 查看 ${employee.name} 的动态与能力更新',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: _bodyStyle(colors),
                        ),
                      ],
                    ),
                  ),
                  Icon(Icons.chevron_right,
                      size: 20, color: colors.textSecondary),
                ],
              ),
              if (abilities.isNotEmpty) ...[
                const SizedBox(height: 12),
                Padding(
                  padding: const EdgeInsets.only(left: 30),
                  child: Row(
                    children: [
                      for (final ability in abilities) ...[
                        _PreviewTile(
                          label: ability,
                          color: _aiEmployeeAvatarColor(
                            '${employee.key}:$ability',
                          ),
                        ),
                        const SizedBox(width: 8),
                      ],
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _PreviewTile extends StatelessWidget {
  const _PreviewTile({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 44,
      height: 44,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.16),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        label.characters.take(2).toString(),
        style: TextStyle(
          color: color,
          fontSize: 11,
          height: 1.27,
          fontWeight: FontWeight.w600,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

class _ActionRow extends StatelessWidget {
  const _ActionRow({required this.text, required this.icon, this.onTap});

  final String text;
  final IconData icon;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Material(
      color: colors.surface,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 14),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 22, color: colors.brand),
              const SizedBox(width: 10),
              Text(
                text,
                style: TextStyle(
                  color: colors.brand,
                  fontSize: 17,
                  height: 1.29,
                  fontWeight: FontWeight.w500,
                  letterSpacing: 0,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

Color _aiEmployeeAvatarColor(String key) {
  const colors = [
    Color(0xFF3370FF),
    Color(0xFF00B578),
    Color(0xFF8B5CF6),
    Color(0xFF00ACC1),
    Color(0xFFED7B2F),
    Color(0xFF494E56),
  ];
  return colors[_floorMod(_javaStringHash(key), colors.length)];
}

int _javaStringHash(String value) {
  var hash = 0;
  for (final codeUnit in value.codeUnits) {
    hash = (31 * hash + codeUnit) & 0xFFFFFFFF;
  }
  return hash >= 0x80000000 ? hash - 0x100000000 : hash;
}

int _floorMod(int value, int mod) {
  final remainder = value % mod;
  return remainder < 0 ? remainder + mod : remainder;
}

TextStyle _titleStyle(XcagiThemeColors colors) {
  return TextStyle(
    color: colors.textPrimary,
    fontSize: 17,
    height: 1.29,
    fontWeight: FontWeight.w500,
    letterSpacing: 0,
  );
}

TextStyle _bodyStyle(XcagiThemeColors colors) {
  return TextStyle(
    color: colors.textSecondary,
    fontSize: 15,
    height: 1.4,
    letterSpacing: 0,
  );
}

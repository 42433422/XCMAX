import 'package:flutter/material.dart';

import '../../data/ai_employee_profile.dart';
import '../../data/mobile_repository.dart';
import '../../models/conversation.dart';
import '../../policy/avatar_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/app_avatar.dart';
import '../../widgets/we_ui.dart';
import '../circle/ai_circle_screen.dart';
import '../chat/chat_screen.dart';
import '../cs/admin_cs_console_screen.dart';
import 'employee_questions_screen.dart';
part 'employee_profile_widgets.part.dart';
part 'employee_profile_cells.part.dart';

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
                          onOpenQuestions: () =>
                              _openQuestions(context, employee),
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
          builder: (_) => AdminCsConsoleScreen(repository: _repository),
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
        builder: (_) => AiCircleScreen(repository: _repository),
      ),
    );
  }

  void _openQuestions(BuildContext context, AiEmployeeProfile employee) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => EmployeeQuestionsScreen(
          repository: _repository,
          employeeId: employee.employeeId,
        ),
      ),
    );
  }
}

class _EmployeeProfileBody extends StatelessWidget {
  const _EmployeeProfileBody({
    required this.employee,
    required this.onOpenChat,
    required this.onOpenCircle,
    required this.onOpenQuestions,
  });

  final AiEmployeeProfile employee;
  final VoidCallback onOpenChat;
  final VoidCallback onOpenCircle;
  final VoidCallback onOpenQuestions;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.only(bottom: 28),
      children: [
        _ContactHeader(employee: employee),
        const SizedBox(height: 8),
        _PlainCell(title: '员工资料', subtitle: employee.summary, showArrow: true),
        const SizedBox(height: 8),
        _CirclePreview(employee: employee, onTap: onOpenCircle),
        const SizedBox(height: 8),
        _PlainCell(title: '能做什么', subtitle: employee.abilityLabels().join('、')),
        const SizedBox(height: 8),
        _PlainCell(title: '来源', subtitle: employee.sourceLabel),
        const SizedBox(height: 8),
        _ActionRow(text: '发消息', icon: Icons.chat, onTap: onOpenChat),
        const SizedBox(height: 8),
        _ActionRow(
          text: '问他/她的待回答问题',
          icon: Icons.question_answer_outlined,
          onTap: onOpenQuestions,
        ),
        const SizedBox(height: 8),
        _ActionRow(text: '进入 AI 交流圈', icon: Icons.forum, onTap: onOpenCircle),
      ],
    );
  }
}

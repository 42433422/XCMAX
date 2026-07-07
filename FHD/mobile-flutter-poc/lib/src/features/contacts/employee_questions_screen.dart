import 'package:flutter/material.dart';

import '../../api/mobile_models.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

/// 员工任务中心：Phase-D 主动提问列表 + 老板回答。
///
/// 对齐 Android `navigation/EmployeeQuestionsScreen.kt`：
/// 员工通过 cognition 输出 requires_human=true 时写入 PendingHumanQuestion，
/// 老板在这里一条条点开回答。employeeId 为空拉全部员工。
class EmployeeQuestionsScreen extends StatefulWidget {
  const EmployeeQuestionsScreen({
    super.key,
    this.repository,
    this.employeeId,
  });

  final MobileRepository? repository;
  final String? employeeId;

  @override
  State<EmployeeQuestionsScreen> createState() =>
      _EmployeeQuestionsScreenState();
}

class _EmployeeQuestionsScreenState extends State<EmployeeQuestionsScreen> {
  late final MobileRepository _repository;
  final _answerController = TextEditingController();
  var _questions = const <EmployeePendingQuestion>[];
  var _loading = false;
  var _error = '';
  int? _answeringId;
  var _submitting = false;

  String get _cleanEmployeeId => widget.employeeId?.trim() ?? '';

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _reload();
  }

  @override
  void dispose() {
    _answerController.dispose();
    super.dispose();
  }

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = '';
    });
    try {
      final questions = await _repository.loadEmployeePendingQuestions(
        includeHistory: false,
        employeeId: _cleanEmployeeId.isEmpty ? null : _cleanEmployeeId,
      );
      if (!mounted) return;
      setState(() => _questions = questions);
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _submitAnswer(EmployeePendingQuestion question) async {
    final text = _answerController.text.trim();
    if (text.isEmpty || _submitting) return;
    setState(() => _submitting = true);
    try {
      await _repository.answerEmployeePendingQuestion(
        questionId: question.id,
        answer: text,
      );
      if (!mounted) return;
      setState(() {
        _answeringId = null;
        _answerController.clear();
      });
      await _reload();
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final title = _cleanEmployeeId.isEmpty ? '员工任务中心' : '$_cleanEmployeeId 的提问';
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: title,
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
              actions: [
                IconButton(
                  onPressed: _reload,
                  icon: const Icon(Icons.question_answer_outlined),
                  color: colors.textPrimary,
                  tooltip: '刷新',
                ),
              ],
            ),
            Expanded(child: _buildBody(colors)),
          ],
        ),
      ),
    );
  }

  Widget _buildBody(XcagiThemeColors colors) {
    if (_loading && _questions.isEmpty) {
      return Center(child: CircularProgressIndicator(color: colors.brand));
    }
    if (_error.trim().isNotEmpty && _questions.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                '拉不到员工提问：$_error',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: colors.danger,
                  fontSize: 14,
                  height: 1.38,
                  letterSpacing: 0,
                ),
              ),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: _reload,
                style: FilledButton.styleFrom(backgroundColor: colors.brand),
                child: const Text('重试'),
              ),
            ],
          ),
        ),
      );
    }
    if (_questions.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                Icons.question_answer_outlined,
                size: 48,
                color: colors.textTertiary,
              ),
              const SizedBox(height: 8),
              Text(
                '暂无员工主动提问',
                style: TextStyle(
                  color: colors.textSecondary,
                  fontSize: 15,
                  height: 1.38,
                  letterSpacing: 0,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                '员工遇到需要老板决策的事会主动在这里问你',
                style: TextStyle(
                  color: colors.textTertiary,
                  fontSize: 12,
                  height: 1.33,
                  letterSpacing: 0,
                ),
              ),
            ],
          ),
        ),
      );
    }
    return RefreshIndicator(
      color: colors.brand,
      onRefresh: _reload,
      child: ListView.separated(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(12),
        itemCount: _questions.length,
        separatorBuilder: (_, __) => const SizedBox(height: 10),
        itemBuilder: (context, index) {
          final question = _questions[index];
          return _QuestionCard(
            key: ValueKey('employee_question_${question.id}'),
            question: question,
            isAnswering: _answeringId == question.id,
            answerController: _answerController,
            submitting: _submitting,
            onStartAnswer: () => setState(() {
              _answeringId = question.id;
              _answerController.clear();
            }),
            onCancelAnswer: () => setState(() {
              _answeringId = null;
              _answerController.clear();
            }),
            onSubmitAnswer: () => _submitAnswer(question),
          );
        },
      ),
    );
  }
}

class _QuestionCard extends StatelessWidget {
  const _QuestionCard({
    super.key,
    required this.question,
    required this.isAnswering,
    required this.answerController,
    required this.submitting,
    required this.onStartAnswer,
    required this.onCancelAnswer,
    required this.onSubmitAnswer,
  });

  final EmployeePendingQuestion question;
  final bool isAnswering;
  final TextEditingController answerController;
  final bool submitting;
  final VoidCallback onStartAnswer;
  final VoidCallback onCancelAnswer;
  final VoidCallback onSubmitAnswer;

  // Android EmployeeQuestionsScreen 状态色：橙=待回答 / 绿=已回答 / 灰=超时未答。
  static const _pendingColor = Color(0xFFE65100);
  static const _answeredColor = Color(0xFF2E7D32);
  static const _expiredColor = Color(0xFF9E9E9E);

  String get _statusText {
    switch (question.status) {
      case 'pending':
        return '待回答';
      case 'answered':
        return '已回答';
      case 'expired':
        return '超时未答';
      default:
        return question.status;
    }
  }

  Color _statusColor(XcagiThemeColors colors) {
    switch (question.status) {
      case 'pending':
        return _pendingColor;
      case 'answered':
        return _answeredColor;
      case 'expired':
        return _expiredColor;
      default:
        return colors.textTertiary;
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final statusColor = _statusColor(colors);
    final isPending = question.isPending;
    return Container(
      decoration: BoxDecoration(
        color: isPending
            ? colors.brandContainer.withValues(alpha: 0.4)
            : colors.surface,
        borderRadius: BorderRadius.circular(12),
      ),
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                '@${question.employeeId}',
                style: TextStyle(
                  color: colors.brand,
                  fontSize: 13,
                  height: 1.38,
                  fontWeight: FontWeight.w500,
                  letterSpacing: 0,
                ),
              ),
              Container(
                decoration: BoxDecoration(
                  color: statusColor.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(10),
                ),
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                child: Text(
                  _statusText,
                  style: TextStyle(
                    color: statusColor,
                    fontSize: 11,
                    height: 1.27,
                    fontWeight: FontWeight.w500,
                    letterSpacing: 0,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          if (question.task.trim().isNotEmpty) ...[
            Text(
              '原任务：${question.task}',
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: colors.textTertiary,
                fontSize: 12,
                height: 1.33,
                letterSpacing: 0,
              ),
            ),
            const SizedBox(height: 6),
          ],
          Container(
            width: double.infinity,
            decoration: BoxDecoration(
              color: colors.surfaceHigh.withValues(alpha: 0.5),
              borderRadius: BorderRadius.circular(8),
            ),
            padding: const EdgeInsets.all(10),
            child: Text(
              question.question,
              style: TextStyle(
                color: colors.textPrimary,
                fontSize: 14,
                height: 1.4,
                letterSpacing: 0,
              ),
            ),
          ),
          if (question.status == 'answered' &&
              question.answer.trim().isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              '你之前的回答：${question.answer}',
              style: TextStyle(
                color: colors.textTertiary,
                fontSize: 12,
                height: 1.33,
                letterSpacing: 0,
              ),
            ),
          ],
          const SizedBox(height: 6),
          Text(
            '提问时间：${question.askedAt}',
            style: TextStyle(
              color: colors.textTertiary,
              fontSize: 11,
              height: 1.27,
              letterSpacing: 0,
            ),
          ),
          if (isPending) ...[
            const SizedBox(height: 8),
            if (isAnswering) ...[
              WeField(
                controller: answerController,
                placeholder: '你的回答',
                singleLine: false,
              ),
              const SizedBox(height: 8),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: submitting ? null : onCancelAnswer,
                    child: Text(
                      '取消',
                      style: TextStyle(color: colors.textSecondary),
                    ),
                  ),
                  const SizedBox(width: 8),
                  ValueListenableBuilder<TextEditingValue>(
                    valueListenable: answerController,
                    builder: (context, value, _) => FilledButton(
                      onPressed: submitting || value.text.trim().isEmpty
                          ? null
                          : onSubmitAnswer,
                      style: FilledButton.styleFrom(
                        backgroundColor: colors.brand,
                      ),
                      child: Text(submitting ? '发送中' : '发送回答'),
                    ),
                  ),
                ],
              ),
            ] else
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  FilledButton(
                    onPressed: onStartAnswer,
                    style: FilledButton.styleFrom(
                      backgroundColor: colors.brand,
                    ),
                    child: const Text('回答'),
                  ),
                ],
              ),
          ],
        ],
      ),
    );
  }
}

import 'package:flutter/material.dart';

import '../../data/employee_pending_question.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

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
  final _questions = <EmployeePendingQuestion>[];
  var _loading = false;
  var _error = '';
  int? _answeringId;
  final _answerController = TextEditingController();
  var _submitting = false;

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

  String get _title {
    final employeeId = widget.employeeId?.trim() ?? '';
    return employeeId.isEmpty ? '员工任务中心' : '$employeeId 的提问';
  }

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = '';
    });
    try {
      final items = await _repository.loadEmployeePendingQuestions(
        employeeId: widget.employeeId,
      );
      if (!mounted) return;
      setState(() {
        _questions
          ..clear()
          ..addAll(items);
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _submitAnswer(EmployeePendingQuestion question) async {
    final answer = _answerController.text.trim();
    if (answer.isEmpty) return;
    setState(() => _submitting = true);
    try {
      await _repository.answerEmployeePendingQuestion(
        questionId: question.id,
        answer: answer,
      );
      if (!mounted) return;
      setState(() {
        final index = _questions.indexWhere((item) => item.id == question.id);
        if (index >= 0) {
          _questions[index] = question.copyWith(
            status: 'answered',
            answer: answer,
            answeredAt: DateTime.now().toIso8601String(),
          );
        }
        _answeringId = null;
        _answerController.clear();
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('回答已发送')),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error.toString())),
      );
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
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
            WeTopBar(
              title: _title,
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
              actions: [
                IconButton(
                  onPressed: _loading ? null : _reload,
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
      return const Center(child: CircularProgressIndicator(strokeWidth: 2.4));
    }
    if (_error.isNotEmpty && _questions.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                '拉不到员工提问：$_error',
                textAlign: TextAlign.center,
                style: TextStyle(color: colors.danger, fontSize: 14),
              ),
              const SizedBox(height: 12),
              ElevatedButton(onPressed: _reload, child: const Text('重试')),
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
                style: TextStyle(color: colors.textTertiary, fontSize: 16),
              ),
              const SizedBox(height: 4),
              Text(
                '员工遇到需要老板决策的事会主动在这里问你',
                textAlign: TextAlign.center,
                style: TextStyle(color: colors.textTertiary, fontSize: 12),
              ),
            ],
          ),
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView.separated(
        padding: const EdgeInsets.all(12),
        itemCount: _questions.length,
        separatorBuilder: (_, __) => const SizedBox(height: 10),
        itemBuilder: (context, index) {
          final question = _questions[index];
          return _QuestionCard(
            question: question,
            isAnswering: _answeringId == question.id,
            answerController: _answerController,
            submitting: _submitting,
            onStartAnswer: () {
              setState(() {
                _answeringId = question.id;
                _answerController.clear();
              });
            },
            onCancelAnswer: () {
              setState(() {
                _answeringId = null;
                _answerController.clear();
              });
            },
            onSubmitAnswer: () => _submitAnswer(question),
            onAnswerChanged: () => setState(() {}),
          );
        },
      ),
    );
  }
}

class _QuestionCard extends StatelessWidget {
  const _QuestionCard({
    required this.question,
    required this.isAnswering,
    required this.answerController,
    required this.submitting,
    required this.onStartAnswer,
    required this.onCancelAnswer,
    required this.onSubmitAnswer,
    this.onAnswerChanged = _noop,
  });

  final EmployeePendingQuestion question;
  final bool isAnswering;
  final TextEditingController answerController;
  final bool submitting;
  final VoidCallback onStartAnswer;
  final VoidCallback onCancelAnswer;
  final VoidCallback onSubmitAnswer;
  final VoidCallback onAnswerChanged;

  static void _noop() {}

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final statusColor = switch (question.status) {
      'pending' => const Color(0xFFE65100),
      'answered' => const Color(0xFF2E7D32),
      'expired' => const Color(0xFF9E9E9E),
      _ => colors.textTertiary,
    };
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: question.isPending
            ? colors.brandContainer.withValues(alpha: 0.35)
            : colors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '@${question.employeeId}',
                  style: TextStyle(
                    color: colors.brand,
                    fontWeight: FontWeight.w600,
                    fontSize: 13,
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: statusColor.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  question.statusLabel,
                  style: TextStyle(
                    color: statusColor,
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
          if (question.task.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              '原任务：${question.task}',
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(color: colors.textSecondary, fontSize: 12),
            ),
          ],
          const SizedBox(height: 6),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: colors.surfaceHigh.withValues(alpha: 0.5),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              question.question,
              style: TextStyle(color: colors.textPrimary, fontSize: 14),
            ),
          ),
          if (question.status == 'answered' && question.answer.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              '你之前的回答：${question.answer}',
              style: TextStyle(color: colors.textSecondary, fontSize: 12),
            ),
          ],
          const SizedBox(height: 6),
          Text(
            '提问时间：${question.askedAt}',
            style: TextStyle(color: colors.textTertiary, fontSize: 11),
          ),
          if (question.isPending) ...[
            if (isAnswering) ...[
              const SizedBox(height: 8),
              WeField(
                controller: answerController,
                placeholder: '你的回答',
                singleLine: false,
                maxLength: 2000,
                onChanged: (_) => onAnswerChanged(),
              ),
              const SizedBox(height: 8),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: submitting ? null : onCancelAnswer,
                    child: const Text('取消'),
                  ),
                  const SizedBox(width: 8),
                  ElevatedButton(
                    onPressed:
                        submitting || answerController.text.trim().isEmpty
                            ? null
                            : onSubmitAnswer,
                    child: Text(submitting ? '发送中' : '发送回答'),
                  ),
                ],
              ),
            ] else ...[
              const SizedBox(height: 8),
              Align(
                alignment: Alignment.centerRight,
                child: ElevatedButton(
                  onPressed: onStartAnswer,
                  child: const Text('回答'),
                ),
              ),
            ],
          ],
        ],
      ),
    );
  }
}

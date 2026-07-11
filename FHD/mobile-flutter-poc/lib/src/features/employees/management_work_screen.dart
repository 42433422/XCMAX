import 'dart:async';

import 'package:flutter/material.dart';

import '../../data/management_work.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

/// Mobile management inbox backed by the same persistent task_id as desktop.
class ManagementWorkScreen extends StatefulWidget {
  const ManagementWorkScreen({super.key, this.repository, this.initialTaskId});

  final MobileRepository? repository;
  final String? initialTaskId;

  @override
  State<ManagementWorkScreen> createState() => _ManagementWorkScreenState();
}

class _ManagementWorkScreenState extends State<ManagementWorkScreen> {
  late final MobileRepository _mobileRepository;
  late final ManagementWorkRepository _repository;
  final _messengerKey = GlobalKey<ScaffoldMessengerState>();
  Timer? _pollTimer;
  var _bootstrapEpoch = 0;
  var _refreshEpoch = 0;
  var _detailEpoch = 0;
  var _refreshInFlight = false;
  var _refreshQueued = false;
  var _snapshot = const ManagementWorkSnapshot(
    items: [],
    summary: ManagementWorkSummary(
      byStatus: {},
      active: 0,
      pendingDecisions: 0,
      accepted: 0,
      blocked: 0,
    ),
  );
  var _filter = 'active';
  var _loading = true;
  var _acting = false;
  var _error = '';
  var _accessError = '';
  var _accessGranted = false;
  String? _selectedTaskId;
  ManagementWorkItem? _detail;
  var _employees = const <ManagementDutyEmployee>[];
  Map<String, String>? _seenAttentionStates;

  void _showSnackBar(SnackBar snackBar) {
    final messenger = _messengerKey.currentState;
    if (messenger == null) return;
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(snackBar);
  }

  @override
  void initState() {
    super.initState();
    _mobileRepository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _repository = ManagementWorkRepository(_mobileRepository.client);
    _selectedTaskId = widget.initialTaskId?.trim().isEmpty ?? true
        ? null
        : widget.initialTaskId?.trim();
    if (_selectedTaskId != null) _filter = 'all';
    unawaited(_bootstrap());
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _bootstrapEpoch += 1;
    _refreshEpoch += 1;
    _detailEpoch += 1;
    super.dispose();
  }

  Future<void> _bootstrap() async {
    final epoch = ++_bootstrapEpoch;
    _pollTimer?.cancel();
    if (mounted) {
      setState(() {
        _loading = true;
        _accessError = '';
        _accessGranted = false;
      });
    }
    try {
      final session = await _mobileRepository.client.loadSession();
      if (!mounted || epoch != _bootstrapEpoch) return;
      final accountKind = session.accountKind.trim().toLowerCase();
      if (!const {'admin', 'admin_portal'}.contains(accountKind)) {
        setState(() {
          _loading = false;
          _accessError = '员工待办与交付仅向管理端管理员开放，当前企业端账号不能查看。';
        });
        return;
      }
      if (!session.hasVerifiedManagementPairing) {
        setState(() {
          _loading = false;
          _accessError = '尚未连接管理端电脑，请在电脑端打开“管理端手机配对”并重新扫码。';
        });
        return;
      }
      setState(() => _accessGranted = true);
      await _refresh(showSpinner: true);
      await _loadEmployees();
      if (!mounted || epoch != _bootstrapEpoch) return;
      _pollTimer = Timer.periodic(
        const Duration(seconds: 5),
        (_) => unawaited(_refresh()),
      );
    } catch (error) {
      if (!mounted || epoch != _bootstrapEpoch) return;
      setState(() {
        _loading = false;
        _accessError = managementWorkUserMessage(error);
      });
    }
  }

  List<ManagementWorkItem> get _visibleItems {
    late final List<ManagementWorkItem> items;
    switch (_filter) {
      case 'attention':
        items = _snapshot.items.where((item) => item.needsAttention).toList();
        break;
      case 'accepted':
        items =
            _snapshot.items.where((item) => item.status == 'accepted').toList();
        break;
      case 'all':
        items = _snapshot.items;
        break;
      case 'active':
      default:
        items = _snapshot.items
            .where((item) => !item.isTerminal && item.status != 'failed')
            .toList();
        break;
    }
    final selected = _selectedTaskId;
    final detail = _detail;
    if (selected != null &&
        detail != null &&
        detail.taskId == selected &&
        !items.any((item) => item.taskId == selected)) {
      return [detail, ...items];
    }
    return items;
  }

  Future<void> _refresh({bool showSpinner = false}) async {
    if (!_accessGranted) return;
    if (_refreshInFlight) {
      _refreshQueued = true;
      return;
    }
    _refreshInFlight = true;
    try {
      do {
        _refreshQueued = false;
        final epoch = ++_refreshEpoch;
        if (showSpinner && mounted) setState(() => _loading = true);
        try {
          final next = await _repository.load();
          if (!mounted || epoch != _refreshEpoch) return;
          _notifyAttentionTransitions(next.items);
          setState(() {
            _snapshot = next;
            _error = '';
          });
          final selected = _selectedTaskId;
          if (selected != null && selected.isNotEmpty) {
            await _loadDetail(selected, quiet: true);
          }
        } catch (error) {
          if (!mounted || epoch != _refreshEpoch) return;
          setState(() => _error = managementWorkUserMessage(error));
        } finally {
          if (mounted && epoch == _refreshEpoch) {
            setState(() => _loading = false);
          }
        }
      } while (_refreshQueued && mounted);
    } finally {
      _refreshInFlight = false;
    }
  }

  Future<void> _loadEmployees() async {
    try {
      final employees = await _repository.employees();
      if (mounted) setState(() => _employees = employees);
    } catch (_) {
      // 列表、决策和验收仍可使用；点击改派时会再次加载并显示错误。
    }
  }

  void _notifyAttentionTransitions(List<ManagementWorkItem> items) {
    final next = <String, String>{
      for (final item in items.where((item) => item.needsAttention))
        item.taskId: _attentionFingerprint(item),
    };
    final previous = _seenAttentionStates;
    _seenAttentionStates = next;
    if (previous == null) return;
    for (final item in items) {
      if (!item.needsAttention ||
          previous[item.taskId] == _attentionFingerprint(item)) {
        continue;
      }
      _showSnackBar(
        SnackBar(
          content: Text('${item.title}：${item.statusLabel}'),
          action: SnackBarAction(
            label: '查看',
            onPressed: () => unawaited(_openDetail(item.taskId)),
          ),
        ),
      );
      break;
    }
  }

  Future<void> _openDetail(String taskId) async {
    _detailEpoch += 1;
    setState(() {
      _selectedTaskId = taskId;
      _detail = null;
    });
    await _loadDetail(taskId);
  }

  Future<void> _loadDetail(String taskId, {bool quiet = false}) async {
    final epoch = ++_detailEpoch;
    try {
      final detail = await _repository.detail(taskId);
      if (!mounted || epoch != _detailEpoch || _selectedTaskId != taskId) {
        return;
      }
      setState(() {
        _detail = detail;
        _error = '';
      });
    } catch (error) {
      if (!mounted || epoch != _detailEpoch || quiet) return;
      _showSnackBar(
        SnackBar(content: Text(managementWorkUserMessage(error))),
      );
    }
  }

  Future<void> _runAction(Future<void> Function() action) async {
    if (_acting) return;
    setState(() => _acting = true);
    try {
      await action();
      await _refresh();
    } catch (error) {
      if (!mounted) return;
      _showSnackBar(
        SnackBar(content: Text(managementWorkUserMessage(error))),
      );
    } finally {
      if (mounted) setState(() => _acting = false);
    }
  }

  Future<void> _answerDecision(ManagementDecision decision) async {
    final controller = TextEditingController();
    final answer = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('回复员工决策'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(decision.question),
              if (decision.recommendation.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(
                  '员工建议：${decision.recommendation}',
                  style: Theme.of(dialogContext).textTheme.bodySmall,
                ),
              ],
              if (decision.options.isNotEmpty) ...[
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 6,
                  children: decision.options
                      .map((option) => ActionChip(
                            label: Text('$option'),
                            onPressed: () =>
                                Navigator.pop(dialogContext, '$option'),
                          ))
                      .toList(growable: false),
                ),
              ],
              const SizedBox(height: 12),
              TextField(
                controller: controller,
                autofocus: decision.options.isEmpty,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(
                  labelText: '你的决定',
                  border: OutlineInputBorder(),
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () =>
                Navigator.pop(dialogContext, controller.text.trim()),
            child: const Text('发送'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (answer == null || answer.trim().isEmpty) return;
    await _runAction(
      () => _repository.resolveDecision(
        decisionId: decision.decisionId,
        decision: answer,
      ),
    );
  }

  Future<void> _review(bool accepted) async {
    final detail = _detail;
    if (detail == null) return;
    if (accepted && !detail.canAcceptDelivery) {
      _showSnackBar(
        SnackBar(content: Text(detail.acceptanceGateMessage)),
      );
      return;
    }
    final controller = TextEditingController();
    final feedback = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(accepted ? '验收通过' : '退回返工'),
        content: TextField(
          controller: controller,
          autofocus: true,
          minLines: 2,
          maxLines: 4,
          decoration: InputDecoration(
            hintText: accepted ? '可填写验收意见' : '请说明需要返工的内容',
            border: const OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () =>
                Navigator.pop(dialogContext, controller.text.trim()),
            child: Text(accepted ? '确认通过' : '确认退回'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (feedback == null) return;
    if (!accepted && feedback.trim().isEmpty) {
      if (!mounted) return;
      _showSnackBar(
        const SnackBar(content: Text('退回返工时请填写需要修改的内容')),
      );
      return;
    }
    await _runAction(
      () => _repository.review(
        taskId: detail.taskId,
        accepted: accepted,
        feedback: feedback,
        item: detail,
      ),
    );
  }

  Future<void> _cancel(ManagementWorkItem item) async {
    final controller = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('请求停止任务'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              item.status == 'running'
                  ? '立即禁止后续验收和交付；已启动的外部动作可能需要短暂收尾。'
                  : '停止后保留已有执行记录，不会伪装成交付完成。',
            ),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              minLines: 2,
              maxLines: 4,
              decoration: const InputDecoration(
                labelText: '停止原因（写入审计时间线）',
                border: OutlineInputBorder(),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('返回'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('确认停止'),
          ),
        ],
      ),
    );
    final reason = controller.text.trim();
    controller.dispose();
    if (confirmed != true) return;
    await _runAction(() => _repository.cancel(item.taskId, reason: reason));
  }

  Future<void> _reassign(ManagementWorkItem item) async {
    if (_employees.isEmpty) {
      try {
        final employees = await _repository.employees();
        if (!mounted) return;
        setState(() => _employees = employees);
      } catch (error) {
        if (!mounted) return;
        _showSnackBar(
          SnackBar(content: Text(managementWorkUserMessage(error))),
        );
        return;
      }
    }
    String selected = '';
    final controller = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('改派管理端员工'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButtonFormField<String>(
                initialValue: null,
                isExpanded: true,
                decoration: const InputDecoration(
                  labelText: '新负责人',
                  border: OutlineInputBorder(),
                ),
                items: _employees
                    .where((employee) =>
                        employee.employeeId != item.ownerEmployeeId)
                    .map(
                      (employee) => DropdownMenuItem(
                        value: employee.employeeId,
                        child: Text(
                          '${employee.name} · ${employee.area}',
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    )
                    .toList(growable: false),
                onChanged: (value) =>
                    setDialogState(() => selected = value ?? ''),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: controller,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(
                  labelText: '改派原因',
                  border: OutlineInputBorder(),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: selected.isEmpty
                  ? null
                  : () => Navigator.pop(dialogContext, true),
              child: const Text('确认改派'),
            ),
          ],
        ),
      ),
    );
    final reason = controller.text.trim();
    controller.dispose();
    if (confirmed != true || selected.isEmpty) return;
    await _runAction(
      () => _repository.reassign(
        taskId: item.taskId,
        newEmployeeId: selected,
        reason: reason,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final screen = Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: '员工待办与交付',
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
              actions: [
                IconButton(
                  onPressed:
                      _loading ? null : () => _refresh(showSpinner: true),
                  icon: const Icon(Icons.refresh),
                  tooltip: '刷新',
                ),
              ],
            ),
            Expanded(
              child: _accessError.isNotEmpty
                  ? _ManagementAccessState(
                      message: _accessError,
                      onRetry: _bootstrap,
                    )
                  : RefreshIndicator(
                      onRefresh: () => _refresh(),
                      child: ListView(
                        physics: const AlwaysScrollableScrollPhysics(),
                        padding: const EdgeInsets.fromLTRB(12, 14, 12, 28),
                        children: [
                          _SummaryGrid(summary: _snapshot.summary),
                          const SizedBox(height: 14),
                          _FilterBar(
                            selected: _filter,
                            onSelected: (value) => setState(() {
                              _filter = value;
                              _selectedTaskId = null;
                              _detailEpoch += 1;
                              _detail = null;
                            }),
                          ),
                          if (_error.isNotEmpty) ...[
                            const SizedBox(height: 12),
                            _ErrorCard(message: _error, onRetry: _refresh),
                          ],
                          if (_loading && _snapshot.items.isEmpty) ...[
                            const SizedBox(height: 72),
                            const Center(
                              child:
                                  CircularProgressIndicator(strokeWidth: 2.4),
                            ),
                          ] else if (_visibleItems.isEmpty) ...[
                            const SizedBox(height: 72),
                            const _EmptyState(),
                          ] else ...[
                            const SizedBox(height: 10),
                            for (final item in _visibleItems) ...[
                              _WorkCard(
                                item: item,
                                expanded: _selectedTaskId == item.taskId,
                                detail: _selectedTaskId == item.taskId
                                    ? _detail
                                    : null,
                                acting: _acting,
                                onTap: () {
                                  if (_selectedTaskId == item.taskId) {
                                    setState(() {
                                      _selectedTaskId = null;
                                      _detailEpoch += 1;
                                      _detail = null;
                                    });
                                  } else {
                                    unawaited(_openDetail(item.taskId));
                                  }
                                },
                                onDecision: _answerDecision,
                                onReview: _review,
                                onRetry: () => _runAction(
                                  () => _repository.retry(item.taskId),
                                ),
                                onCancel: _cancel,
                                onReassign: _reassign,
                              ),
                              const SizedBox(height: 9),
                            ],
                          ],
                        ],
                      ),
                    ),
            ),
          ],
        ),
      ),
    );
    return ScaffoldMessenger(key: _messengerKey, child: screen);
  }
}

class _SummaryGrid extends StatelessWidget {
  const _SummaryGrid({required this.summary});

  final ManagementWorkSummary summary;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(child: _SummaryCell(label: '正在推进', value: summary.active)),
        const SizedBox(width: 7),
        Expanded(
          child: _SummaryCell(
            label: '等你决策',
            value: summary.pendingDecisions,
            color: const Color(0xFFD97706),
          ),
        ),
        const SizedBox(width: 7),
        Expanded(
          child: _SummaryCell(
            label: '待验收',
            value: summary.delivered,
            color: const Color(0xFF2563EB),
          ),
        ),
        const SizedBox(width: 7),
        Expanded(
          child: _SummaryCell(
            label: '需介入',
            value: summary.blocked,
            color: const Color(0xFFDC2626),
          ),
        ),
      ],
    );
  }
}

class _ManagementAccessState extends StatelessWidget {
  const _ManagementAccessState({required this.message, required this.onRetry});

  final String message;
  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.admin_panel_settings_outlined,
                size: 52, color: colors.textSecondary),
            const SizedBox(height: 14),
            Text(
              message,
              textAlign: TextAlign.center,
              style: TextStyle(color: colors.textSecondary, height: 1.5),
            ),
            const SizedBox(height: 18),
            OutlinedButton.icon(
              onPressed: () => unawaited(onRetry()),
              icon: const Icon(Icons.refresh, size: 18),
              label: const Text('重新检查连接'),
            ),
          ],
        ),
      ),
    );
  }
}

class _SummaryCell extends StatelessWidget {
  const _SummaryCell({
    required this.label,
    required this.value,
    this.color,
  });

  final String label;
  final int value;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colors.divider.withValues(alpha: .7)),
      ),
      child: Column(
        children: [
          Text(
            '$value',
            style: Theme.of(context).textTheme.titleLarge?.copyWith(
                  color: color ?? colors.textPrimary,
                  fontWeight: FontWeight.w700,
                ),
          ),
          const SizedBox(height: 3),
          Text(
            label,
            maxLines: 1,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: colors.textSecondary,
                  fontSize: 10,
                ),
          ),
        ],
      ),
    );
  }
}

class _FilterBar extends StatelessWidget {
  const _FilterBar({required this.selected, required this.onSelected});

  final String selected;
  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    const filters = {
      'active': '进行中',
      'attention': '等我处理',
      'accepted': '已验收',
      'all': '全部',
    };
    return Wrap(
      spacing: 7,
      children: filters.entries
          .map(
            (entry) => ChoiceChip(
              label: Text(entry.value),
              selected: selected == entry.key,
              onSelected: (_) => onSelected(entry.key),
            ),
          )
          .toList(growable: false),
    );
  }
}

class _WorkCard extends StatelessWidget {
  const _WorkCard({
    required this.item,
    required this.expanded,
    required this.detail,
    required this.acting,
    required this.onTap,
    required this.onDecision,
    required this.onReview,
    required this.onRetry,
    required this.onCancel,
    required this.onReassign,
  });

  final ManagementWorkItem item;
  final bool expanded;
  final ManagementWorkItem? detail;
  final bool acting;
  final VoidCallback onTap;
  final ValueChanged<ManagementDecision> onDecision;
  final ValueChanged<bool> onReview;
  final VoidCallback onRetry;
  final ValueChanged<ManagementWorkItem> onCancel;
  final ValueChanged<ManagementWorkItem> onReassign;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final statusColor = _statusColor(item.status, colors);
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: colors.divider.withValues(alpha: .75)),
      ),
      child: Column(
        children: [
          InkWell(
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.all(13),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 7, vertical: 3),
                        decoration: BoxDecoration(
                          color: statusColor.withValues(alpha: .12),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          '${item.priority} · ${item.statusLabel}',
                          style: TextStyle(
                            color: statusColor,
                            fontSize: 10,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                      const Spacer(),
                      Text(
                        '${item.progress}%',
                        style: TextStyle(
                            color: colors.textSecondary, fontSize: 11),
                      ),
                      Icon(
                        expanded ? Icons.expand_less : Icons.expand_more,
                        color: colors.textSecondary,
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    item.title,
                    style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                          fontWeight: FontWeight.w600,
                          color: colors.textPrimary,
                        ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${item.ownerEmployeeId} · ${item.currentStage.ifEmpty('等待员工领取')}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: colors.textSecondary,
                        ),
                  ),
                  const SizedBox(height: 9),
                  LinearProgressIndicator(
                    value: item.progress / 100,
                    minHeight: 4,
                    color: statusColor,
                    backgroundColor: colors.divider.withValues(alpha: .45),
                    borderRadius: BorderRadius.circular(8),
                  ),
                ],
              ),
            ),
          ),
          if (expanded) ...[
            Divider(height: .5, color: colors.divider),
            if (detail == null)
              const Padding(
                padding: EdgeInsets.all(20),
                child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
              )
            else
              _WorkDetail(
                item: detail!,
                acting: acting,
                onDecision: onDecision,
                onReview: onReview,
                onRetry: onRetry,
                onCancel: onCancel,
                onReassign: onReassign,
              ),
          ],
        ],
      ),
    );
  }
}

class _WorkDetail extends StatelessWidget {
  const _WorkDetail({
    required this.item,
    required this.acting,
    required this.onDecision,
    required this.onReview,
    required this.onRetry,
    required this.onCancel,
    required this.onReassign,
  });

  final ManagementWorkItem item;
  final bool acting;
  final ValueChanged<ManagementDecision> onDecision;
  final ValueChanged<bool> onReview;
  final VoidCallback onRetry;
  final ValueChanged<ManagementWorkItem> onCancel;
  final ValueChanged<ManagementWorkItem> onReassign;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final decision = item.pendingDecision;
    return Padding(
      padding: const EdgeInsets.all(13),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _DetailFacts(item: item),
          if (item.description.isNotEmpty) ...[
            const SizedBox(height: 10),
            _StructuredSection(
              title: '任务说明',
              values: [item.description],
            ),
          ],
          if (item.acceptanceCriteria.isNotEmpty) ...[
            const SizedBox(height: 10),
            _StructuredSection(
              title: item.acceptanceRequired ? '验收标准（必须核对）' : '验收参考',
              values: item.acceptanceCriteria,
              accent: const Color(0xFFD97706),
            ),
          ],
          if (item.lastUpdate.isNotEmpty) ...[
            const SizedBox(height: 10),
            _MessageBox(text: item.lastUpdate, color: const Color(0xFF2563EB)),
          ],
          if (item.error.isNotEmpty) ...[
            const SizedBox(height: 10),
            _MessageBox(text: item.error, color: colors.danger),
          ],
          if (item.evidence.isNotEmpty) ...[
            const SizedBox(height: 10),
            _StructuredSection(
              title: '执行证据',
              values: item.evidence,
              accent: const Color(0xFF2563EB),
            ),
          ],
          if (item.artifacts.isNotEmpty) ...[
            const SizedBox(height: 10),
            _StructuredSection(
              title: '交付产物',
              values: item.artifacts,
              accent: colors.success,
            ),
          ],
          const SizedBox(height: 10),
          _IndependentFactEvidenceSection(item: item),
          const SizedBox(height: 10),
          _VerificationReceiptSection(item: item),
          const SizedBox(height: 10),
          _OperationRecoverySection(item: item),
          if (decision != null) ...[
            const SizedBox(height: 12),
            const Text(
              '员工正在等你',
              style: TextStyle(
                color: Color(0xFFD97706),
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 5),
            Text(decision.question),
            if (decision.recommendation.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 5),
                child: Text(
                  '建议：${decision.recommendation}',
                  style: TextStyle(color: colors.textSecondary, fontSize: 12),
                ),
              ),
            if (decision.dueAt.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 5),
                child: Text(
                  '请在 ${decision.dueAt} 前处理',
                  style: TextStyle(color: colors.textSecondary, fontSize: 12),
                ),
              ),
            const SizedBox(height: 9),
            FilledButton.icon(
              onPressed: acting ? null : () => onDecision(decision),
              icon: const Icon(Icons.question_answer_outlined, size: 18),
              label: const Text('回复员工'),
            ),
          ],
          if (item.status == 'delivered') ...[
            const SizedBox(height: 12),
            Text(
              item.resultSummary.ifEmpty('员工已提交执行结果'),
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 9),
            Row(
              children: [
                Expanded(
                  child: FilledButton(
                    onPressed: acting || !item.canAcceptDelivery
                        ? null
                        : () => onReview(true),
                    child: const Text('验收通过'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton(
                    onPressed: acting ? null : () => onReview(false),
                    child: const Text('退回返工'),
                  ),
                ),
              ],
            ),
          ],
          if (const {'blocked', 'failed'}.contains(item.status)) ...[
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: acting ? null : onRetry,
                style: FilledButton.styleFrom(backgroundColor: colors.danger),
                icon: const Icon(Icons.replay, size: 18),
                label: const Text('修复后重新派发'),
              ),
            ),
          ],
          if (item.status == 'cancel_requested') ...[
            const SizedBox(height: 12),
            const _MessageBox(
              text: '台账已禁止后续验收和交付；已启动的当前步骤返回后安全收口。',
              color: Color(0xFFEA580C),
            ),
          ],
          if (item.canCancel || item.canReassign) ...[
            const SizedBox(height: 12),
            Text(
              '老板控制',
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: 7),
            Row(
              children: [
                if (item.canReassign)
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: acting ? null : () => onReassign(item),
                      icon: const Icon(Icons.person_search_outlined, size: 18),
                      label: const Text('改派员工'),
                    ),
                  ),
                if (item.canReassign && item.canCancel)
                  const SizedBox(width: 8),
                if (item.canCancel)
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: acting ? null : () => onCancel(item),
                      style: FilledButton.styleFrom(
                        backgroundColor: colors.danger,
                      ),
                      icon: const Icon(Icons.stop_circle_outlined, size: 18),
                      label: const Text('请求停止'),
                    ),
                  ),
              ],
            ),
          ],
          if (item.events.isNotEmpty) ...[
            const SizedBox(height: 14),
            Text(
              '执行记录',
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                    color: colors.textSecondary,
                  ),
            ),
            const SizedBox(height: 5),
            for (final event in item.events.reversed.take(8))
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      width: 7,
                      height: 7,
                      margin: const EdgeInsets.only(top: 5, right: 8),
                      decoration: const BoxDecoration(
                        color: Color(0xFF2563EB),
                        shape: BoxShape.circle,
                      ),
                    ),
                    Expanded(
                      child: Text(
                        '${event.label}${event.message.isEmpty ? '' : ' · ${event.message}'}',
                        style: TextStyle(
                            color: colors.textSecondary, fontSize: 12),
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _IndependentFactEvidenceSection extends StatelessWidget {
  const _IndependentFactEvidenceSection({required this.item});

  final ManagementWorkItem item;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final current = item.currentAttemptFactEvidence;
    final historicalCount = item.factEvidence.length - current.length;
    return _TruthPanel(
      title: '独立事实证据',
      subtitle: '由员工进程之外的事实采集器生成 · 当前第 ${item.attemptCount} 次执行',
      icon: Icons.fact_check_outlined,
      accent: current.any(
        (row) => !row.isAcceptableForTaskAttempt(
          item.taskId,
          item.attemptCount,
        ),
      )
          ? colors.danger
          : const Color(0xFF2563EB),
      children: [
        if (current.isEmpty)
          Text(
            '当前轮次没有独立事实明细；是否允许验收仍以本轮独立 PASS 回执为准。',
            style: TextStyle(color: colors.textSecondary, fontSize: 12),
          )
        else
          for (final evidence in current)
            _FactEvidenceRow(
              evidence: evidence,
              expectedTaskId: item.taskId,
              expectedAttempt: item.attemptCount,
            ),
        if (historicalCount > 0)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              '另有 $historicalCount 条历史轮次证据，仅供追溯，不授权当前验收。',
              style: TextStyle(color: colors.textTertiary, fontSize: 11),
            ),
          ),
      ],
    );
  }
}

class _FactEvidenceRow extends StatelessWidget {
  const _FactEvidenceRow({
    required this.evidence,
    required this.expectedTaskId,
    required this.expectedAttempt,
  });

  final ManagementFactEvidence evidence;
  final String expectedTaskId;
  final int expectedAttempt;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final valid = evidence.isAcceptableForTaskAttempt(
      expectedTaskId,
      expectedAttempt,
    );
    final tint = valid ? colors.success : colors.danger;
    final expiryLabel = !evidence.hasParseableExpiry
        ? '有效期无效'
        : evidence.isExpired
            ? '已过期'
            : '有效至 ${evidence.expiresAt}';
    final payloadSummary = _factEvidencePayloadSummary(evidence);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(9),
        decoration: BoxDecoration(
          color: tint.withValues(alpha: .06),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: tint.withValues(alpha: .2)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  valid ? Icons.verified_outlined : Icons.error_outline,
                  color: tint,
                  size: 17,
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    '${evidence.statusLabel} · $expiryLabel · ${evidence.kind.ifEmpty('unknown')} · ${evidence.checkId.ifEmpty(evidence.evidenceId)}',
                    style: TextStyle(
                      color: tint,
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
            if (evidence.sourceRef.isNotEmpty) ...[
              const SizedBox(height: 4),
              SelectableText(
                '来源：${evidence.sourceRef}',
                style: TextStyle(color: colors.textSecondary, fontSize: 11),
              ),
            ],
            if (evidence.criterionIds.isNotEmpty) ...[
              const SizedBox(height: 3),
              Text(
                '覆盖标准：${evidence.criterionIds.join('、')}',
                style: TextStyle(color: colors.textSecondary, fontSize: 11),
              ),
            ],
            if (payloadSummary.isNotEmpty) ...[
              const SizedBox(height: 4),
              SelectableText(
                payloadSummary,
                style: TextStyle(
                  color: colors.textPrimary,
                  fontSize: 11,
                  height: 1.4,
                ),
              ),
            ],
            const SizedBox(height: 4),
            SelectableText(
              '证据 ${evidence.evidenceId.ifEmpty('未编号')} · SHA256 ${_shortDigest(evidence.payloadSha256)}${evidence.observedAt.isEmpty ? '' : ' · ${evidence.observedAt}'}',
              style: TextStyle(color: colors.textTertiary, fontSize: 10),
            ),
          ],
        ),
      ),
    );
  }
}

class _VerificationReceiptSection extends StatelessWidget {
  const _VerificationReceiptSection({required this.item});

  final ManagementWorkItem item;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final current = item.currentAttemptVerificationReceipt;
    final passed = item.hasCurrentPassingVerificationReceipt;
    final tint = passed
        ? colors.success
        : current == null
            ? const Color(0xFFD97706)
            : colors.danger;
    final history = item.verificationReceipts
        .where((receipt) => receipt.attempt != item.attemptCount)
        .toList(growable: false);
    return _TruthPanel(
      title: '独立验收回执',
      subtitle: item.acceptanceGateMessage,
      icon: passed ? Icons.verified_user_outlined : Icons.gpp_maybe_outlined,
      accent: tint,
      children: [
        if (current == null)
          Text(
            '未找到与 task_id 和当前 attempt 同时匹配的验收回执。',
            style: TextStyle(color: colors.textSecondary, fontSize: 12),
          )
        else
          _VerificationReceiptRow(receipt: current, currentAttempt: true),
        if (history.isNotEmpty) ...[
          const SizedBox(height: 7),
          Text(
            '历史回执（不可授权当前验收）',
            style: TextStyle(
              color: colors.textSecondary,
              fontSize: 11,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 4),
          for (final receipt in history.reversed.take(5))
            _VerificationReceiptRow(
              receipt: receipt,
              currentAttempt: false,
            ),
        ],
      ],
    );
  }
}

class _VerificationReceiptRow extends StatelessWidget {
  const _VerificationReceiptRow({
    required this.receipt,
    required this.currentAttempt,
  });

  final ManagementVerificationReceipt receipt;
  final bool currentAttempt;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final trusted = currentAttempt ? receipt.isStrictPass : receipt.passed;
    final tint = trusted ? colors.success : colors.danger;
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(9),
        decoration: BoxDecoration(
          color: tint.withValues(alpha: currentAttempt ? .07 : .035),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: tint.withValues(alpha: .2)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '第 ${receipt.attempt} 次 · ${trusted ? receipt.statusLabel : currentAttempt && receipt.passed ? 'INVALID · 回执字段不可信' : receipt.statusLabel}${currentAttempt ? ' · 当前轮次' : ''}',
              style: TextStyle(
                color: tint,
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              '事实核验：${receipt.factOutcomeLabel} · 语义验收：${receipt.auditOutcomeLabel} · 验收员：${receipt.verifierEmployeeId.ifEmpty('未登记')}',
              style: TextStyle(color: colors.textSecondary, fontSize: 11),
            ),
            if (receipt.reason.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                '说明：${receipt.reason}',
                style: TextStyle(color: colors.textPrimary, fontSize: 11),
              ),
            ],
            const SizedBox(height: 4),
            SelectableText(
              '回执 ${receipt.receiptId.ifEmpty('未编号')} · 结果 ${_shortDigest(receipt.resultDigest)} · 事实包 ${_shortDigest(receipt.factBundleDigest)}',
              style: TextStyle(color: colors.textTertiary, fontSize: 10),
            ),
          ],
        ),
      ),
    );
  }
}

class _OperationRecoverySection extends StatelessWidget {
  const _OperationRecoverySection({required this.item});

  final ManagementWorkItem item;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final unresolved = item.operationsNeedingRecovery.length;
    final tint = unresolved > 0 ? colors.danger : const Color(0xFF0F766E);
    return _TruthPanel(
      title: '副作用操作与恢复状态',
      subtitle: item.operations.isEmpty
          ? '未登记外部副作用操作'
          : '${item.operations.length} 项操作 · ${unresolved == 0 ? '没有待恢复项' : '$unresolved 项需要恢复或人工核对'}',
      icon: Icons.settings_backup_restore_outlined,
      accent: tint,
      children: [
        if (item.operations.isEmpty)
          Text(
            '当前详情没有 operation 台账；这表示没有登记到可追踪的外部副作用，不等同于员工口头声明“没有副作用”。',
            style: TextStyle(color: colors.textSecondary, fontSize: 12),
          )
        else
          for (final operation in item.operations.reversed.take(20))
            _OperationRecoveryRow(
              operation: operation,
              expectedTaskId: item.taskId,
            ),
      ],
    );
  }
}

class _OperationRecoveryRow extends StatelessWidget {
  const _OperationRecoveryRow({
    required this.operation,
    required this.expectedTaskId,
  });

  final ManagementWorkOperation operation;
  final String expectedTaskId;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final recovered =
        operation.compensationStatus.toLowerCase() == 'compensated';
    final tint = operation.blocksAcceptanceForTask(expectedTaskId)
        ? colors.danger
        : recovered
            ? const Color(0xFF0F766E)
            : colors.success;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(9),
        decoration: BoxDecoration(
          color: tint.withValues(alpha: .055),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: tint.withValues(alpha: .18)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${operation.kind.ifEmpty('unknown')} · ${operation.logicalStep.ifEmpty('未命名步骤')}',
              style: TextStyle(
                color: tint,
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              '第 ${operation.attempt} 次执行 · ${operation.statusLabel} · ${operation.recoveryStatusLabel}',
              style: TextStyle(color: colors.textSecondary, fontSize: 11),
            ),
            if (operation.target.isNotEmpty) ...[
              const SizedBox(height: 3),
              SelectableText(
                '目标：${operation.target}',
                style: TextStyle(color: colors.textPrimary, fontSize: 11),
              ),
            ],
            if (operation.externalRef.isNotEmpty) ...[
              const SizedBox(height: 3),
              SelectableText(
                '外部回执：${operation.externalRef}',
                style: TextStyle(color: colors.textPrimary, fontSize: 11),
              ),
            ],
            if (operation.error.isNotEmpty) ...[
              const SizedBox(height: 3),
              Text(
                '异常：${operation.error}',
                style: TextStyle(color: colors.danger, fontSize: 11),
              ),
            ],
            const SizedBox(height: 4),
            SelectableText(
              'Operation ${operation.operationId.ifEmpty('未编号')} · 请求 ${_shortDigest(operation.requestDigest)}',
              style: TextStyle(color: colors.textTertiary, fontSize: 10),
            ),
          ],
        ),
      ),
    );
  }
}

class _TruthPanel extends StatelessWidget {
  const _TruthPanel({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.accent,
    required this.children,
  });

  final String title;
  final String subtitle;
  final IconData icon;
  final Color accent;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: accent.withValues(alpha: .045),
        borderRadius: BorderRadius.circular(9),
        border: Border.all(color: accent.withValues(alpha: .18)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, color: accent, size: 18),
              const SizedBox(width: 6),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: TextStyle(
                        color: accent,
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      subtitle,
                      style: TextStyle(
                        color: colors.textSecondary,
                        fontSize: 11,
                        height: 1.35,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          ...children,
        ],
      ),
    );
  }
}

class _DetailFacts extends StatelessWidget {
  const _DetailFacts({required this.item});

  final ManagementWorkItem item;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Wrap(
      spacing: 7,
      runSpacing: 7,
      children: [
        _Fact(label: '阶段', value: item.currentStage.ifEmpty('等待领取')),
        _Fact(label: '风险', value: _riskLabel(item.riskLevel)),
        _Fact(label: '执行', value: '${item.attemptCount}/${item.maxAttempts}'),
        _Fact(label: '任务编号', value: item.taskId),
      ]
          .map((child) => DefaultTextStyle.merge(
                style: TextStyle(color: colors.textSecondary),
                child: child,
              ))
          .toList(growable: false),
    );
  }
}

class _StructuredSection extends StatelessWidget {
  const _StructuredSection({
    required this.title,
    required this.values,
    this.accent,
  });

  final String title;
  final List<Object?> values;
  final Color? accent;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final tint = accent ?? colors.textSecondary;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: tint.withValues(alpha: .06),
        borderRadius: BorderRadius.circular(9),
        border: Border.all(color: tint.withValues(alpha: .18)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: TextStyle(
              color: tint,
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 6),
          for (final value in values.take(20))
            Padding(
              padding: const EdgeInsets.only(bottom: 5),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('• ', style: TextStyle(color: tint)),
                  Expanded(
                    child: SelectableText(
                      _structuredValueText(value),
                      style: TextStyle(
                        color: colors.textPrimary,
                        fontSize: 12,
                        height: 1.45,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          if (values.length > 20)
            Text(
              '另有 ${values.length - 20} 项，请在电脑端查看完整内容',
              style: TextStyle(color: colors.textSecondary, fontSize: 11),
            ),
        ],
      ),
    );
  }
}

class _Fact extends StatelessWidget {
  const _Fact({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      constraints: const BoxConstraints(maxWidth: 210),
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 7),
      decoration: BoxDecoration(
        color: colors.page,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        '$label：$value',
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: const TextStyle(fontSize: 11),
      ),
    );
  }
}

class _MessageBox extends StatelessWidget {
  const _MessageBox({required this.text, required this.color});

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .08),
        border: Border(left: BorderSide(color: color, width: 3)),
      ),
      child: Text(text, style: const TextStyle(fontSize: 12)),
    );
  }
}

class _ErrorCard extends StatelessWidget {
  const _ErrorCard({required this.message, required this.onRetry});

  final String message;
  final Future<void> Function({bool showSpinner}) onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colors.danger.withValues(alpha: .08),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(message,
                style: TextStyle(color: colors.danger, fontSize: 12)),
          ),
          TextButton(
            onPressed: () => onRetry(showSpinner: true),
            child: const Text('重试'),
          ),
        ],
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Column(
      children: [
        Icon(Icons.task_alt, size: 44, color: colors.success),
        const SizedBox(height: 8),
        Text('当前没有需要处理的任务', style: TextStyle(color: colors.textSecondary)),
        const SizedBox(height: 4),
        Text(
          '桌面安排的工作会以同一个 task_id 持续同步到这里',
          textAlign: TextAlign.center,
          style: TextStyle(color: colors.textTertiary, fontSize: 12),
        ),
      ],
    );
  }
}

Color _statusColor(String status, XcagiThemeColors colors) {
  return switch (status) {
    'running' || 'verifying' => const Color(0xFF2563EB),
    'cancel_requested' => const Color(0xFFEA580C),
    'waiting_decision' || 'delivered' => const Color(0xFFD97706),
    'accepted' => colors.success,
    'blocked' || 'failed' => colors.danger,
    _ => colors.textSecondary,
  };
}

String _attentionFingerprint(ManagementWorkItem item) {
  return [
    item.status,
    item.currentStage,
    item.pendingDecision?.decisionId ?? '',
    item.updatedAt,
    item.resultSummary,
    item.error,
  ].join('|');
}

String _riskLabel(String raw) {
  return switch (raw.trim().toLowerCase()) {
    'critical' => '极高',
    'high' => '高',
    'low' => '低',
    _ => '中',
  };
}

String _structuredValueText(Object? value) {
  if (value == null) return '未提供内容';
  if (value is String) return _boundedText(value);
  if (value is Map) {
    const preferredKeys = [
      'name',
      'title',
      'summary',
      'description',
      'path',
      'url',
      'uri',
      'sha256',
      'content',
      'message',
    ];
    final parts = <String>[];
    for (final key in preferredKeys) {
      final item = value[key];
      final text = item?.toString().trim() ?? '';
      if (text.isNotEmpty) parts.add('$key：$text');
    }
    if (parts.isEmpty) {
      for (final entry in value.entries.take(8)) {
        final text = entry.value?.toString().trim() ?? '';
        if (text.isNotEmpty) parts.add('${entry.key}：$text');
      }
    }
    return _boundedText(parts.join(' · '));
  }
  if (value is Iterable) {
    return _boundedText(value.map((item) => '$item').join('、'));
  }
  return _boundedText('$value');
}

String _factEvidencePayloadSummary(ManagementFactEvidence evidence) {
  final payload = evidence.payload;
  final parts = <String>[];
  final strength = payload['strength']?.toString().trim() ?? '';
  if (strength.isNotEmpty) parts.add('强度：$strength');
  final verified = payload['verified'];
  if (verified is bool) parts.add('独立复核：${verified ? '已确认' : '未确认'}');
  final error = payload['error']?.toString().trim() ?? '';
  if (error.isNotEmpty) parts.add('原因：$error');
  final checks = payload['checks'];
  if (checks is Map && checks.isNotEmpty) {
    final passed = checks.entries
        .where((entry) => entry.value == true)
        .map((entry) => '${entry.key}')
        .toList(growable: false);
    final failed = checks.entries
        .where((entry) => entry.value != true)
        .map((entry) => '${entry.key}')
        .toList(growable: false);
    if (passed.isNotEmpty) parts.add('检查通过：${passed.join('、')}');
    if (failed.isNotEmpty) parts.add('检查未通过：${failed.join('、')}');
  }
  return _boundedText(parts.join(' · '));
}

String _shortDigest(String raw) {
  final value = raw.trim();
  if (value.isEmpty) return '未提供';
  return value.length <= 16 ? value : '${value.substring(0, 16)}…';
}

String _boundedText(String raw) {
  final text = raw.trim();
  return text.length <= 800 ? text : '${text.substring(0, 800)}…';
}

extension on String {
  String ifEmpty(String fallback) => isEmpty ? fallback : this;
}

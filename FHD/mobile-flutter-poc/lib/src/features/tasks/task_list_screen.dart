import 'package:flutter/material.dart';

import '../../api/mobile_models.dart';
import '../../policy/mobile_error_policy.dart';
import 'native_task_workspace_screen.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../approval/approval_screens.dart';

class TaskListScreen extends StatefulWidget {
  const TaskListScreen({super.key, this.repository});

  final MobileRepository? repository;

  @override
  State<TaskListScreen> createState() => _TaskListScreenState();
}

class _TaskListScreenState extends State<TaskListScreen> {
  late final MobileRepository _repository;
  late Future<List<MobileTaskSummary>> _tasksFuture;
  late Future<List<MobileDesktopDevice>> _devicesFuture;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _tasksFuture = _repository.loadTasks();
    _devicesFuture = _repository.loadDesktopDevices().catchError(
          (_) => const <MobileDesktopDevice>[],
        );
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
              title: '任务',
              onBack: () => Navigator.of(context).maybePop(),
            ),
            Expanded(
              child: FutureBuilder<List<MobileTaskSummary>>(
                future: _tasksFuture,
                builder: (context, snapshot) {
                  final tasks = snapshot.data ?? const <MobileTaskSummary>[];
                  if (snapshot.connectionState != ConnectionState.done) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  final pendingApprovals =
                      tasks.where((task) => task.approvalRequired).length;
                  return RefreshIndicator(
                    color: colors.brand,
                    onRefresh: _refresh,
                    child: ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.only(bottom: 24),
                      children: [
                        if (snapshot.hasError || tasks.isEmpty)
                          ListTile(
                            title: Text(
                              snapshot.hasError
                                  ? mobileErrorText(snapshot.error)
                                  : '暂无任务',
                            ),
                            subtitle: const Text('下拉刷新，或点击重试'),
                            trailing: const Icon(Icons.refresh),
                            onTap: _refresh,
                          ),
                        if (pendingApprovals > 0) ...[
                          WeCellGroup(
                            children: [
                              WeCell(
                                title: '待审批',
                                subtitle: '$pendingApprovals 项任务需要你确认',
                                icon: Icons.fact_check_outlined,
                                iconColor: colors.brand,
                                iconBg: colors.brandContainer,
                                showDivider: false,
                                onTap: _openApprovals,
                              ),
                            ],
                          ),
                          const SizedBox(height: 8),
                        ],
                        WeCellGroup(
                          children: [
                            for (var i = 0; i < tasks.length; i += 1)
                              _TaskCell(
                                task: tasks[i],
                                onTap: tasks[i].taskId.isEmpty
                                    ? null
                                    : () => _openTask(tasks[i]),
                                showDivider: i != tasks.length - 1,
                              ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        _DesktopStatusLine(future: _devicesFuture),
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _refresh() async {
    final tasksFuture = _repository.loadTasks();
    final devicesFuture = _repository.loadDesktopDevices().catchError(
          (_) => const <MobileDesktopDevice>[],
        );
    setState(() {
      _tasksFuture = tasksFuture;
      _devicesFuture = devicesFuture;
    });
    // FutureBuilder owns the error state, including failed pull-to-refresh.
    await Future.wait([
      tasksFuture,
      devicesFuture,
    ]).then<void>((_) {}, onError: (Object _, StackTrace __) {});
  }

  Future<void> _openTask(MobileTaskSummary task) async {
    await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => NativeTaskWorkspaceScreen(
            taskId: task.taskId,
            activeModId: task.activeModId,
            repository: _repository)));
    if (mounted) await _refresh();
  }

  void _openApprovals() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ApprovalListScreen(repository: _repository),
      ),
    );
  }
}

class _TaskCell extends StatelessWidget {
  const _TaskCell({required this.task, required this.showDivider, this.onTap});

  final MobileTaskSummary task;
  final VoidCallback? onTap;
  final bool showDivider;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final statusText = _statusText(task);
    return WeCell(
      title: task.title.isEmpty ? '未命名任务' : task.title,
      subtitle: statusText,
      onTap: onTap,
      icon: Icons.task_alt,
      iconColor: colors.textSecondary,
      iconBg: colors.surfaceHigh,
      showDivider: showDivider,
      trailing: Text(
        _targetLabel(task.executionTarget),
        style: TextStyle(
          color: colors.textTertiary,
          fontSize: 12,
          height: 1.27,
          letterSpacing: 0,
        ),
      ),
    );
  }

  static String _statusText(MobileTaskSummary task) {
    if (task.approvalRequired ||
        task.attentionState == 'approval_required' ||
        task.status == 'waiting_user') {
      return '待审批';
    }
    if (task.attentionState == 'result_unread') return '有结果待查看';
    if (task.status == 'running' || task.status == 'claimed') {
      return '进行中 ${task.progressPercent.clamp(0, 100)}%';
    }
    return const {
          'queued': '排队中',
          'planning': '规划中',
          'retrying': '重试中',
          'completed': '已完成',
          'failed': '执行失败',
          'paused': '已暂停',
          'cancelled': '已取消',
          'blocked': '已阻断',
          'pending': '待执行',
          'skipped': '已跳过',
        }[task.status] ??
        '状态待同步';
  }

  static String _targetLabel(String target) {
    final value = target.trim();
    if (value.isEmpty || value == 'cloud') return '云端';
    if (value.startsWith('desktop:')) return '桌面端';
    return value;
  }
}

class _DesktopStatusLine extends StatelessWidget {
  const _DesktopStatusLine({required this.future});

  final Future<List<MobileDesktopDevice>> future;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return FutureBuilder<List<MobileDesktopDevice>>(
      future: future,
      builder: (context, snapshot) {
        final devices = snapshot.data ?? const <MobileDesktopDevice>[];
        if (devices.isEmpty) return const SizedBox.shrink();
        final online = devices.where((device) => device.online).length;
        final names = devices
            .where((device) => device.online)
            .map((device) => device.label.isEmpty ? '桌面端' : device.label)
            .join('、');
        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Text(
            online > 0 ? '桌面在线：$names' : '桌面端当前不在线',
            style: TextStyle(
              color: colors.textTertiary,
              fontSize: 12,
              height: 1.27,
              letterSpacing: 0,
            ),
          ),
        );
      },
    );
  }
}

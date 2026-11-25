import 'dart:async';

import 'package:flutter/material.dart';

import '../../api/mobile_models.dart';
import '../../policy/mobile_error_policy.dart';
import 'native_task_workspace_screen.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../approval/approval_screens.dart';
import '../workspace/native_workspace_session.dart';

class TaskListScreen extends StatefulWidget {
  const TaskListScreen({super.key, this.repository});

  final MobileRepository? repository;

  @override
  State<TaskListScreen> createState() => _TaskListScreenState();
}

class _TaskListScreenState extends State<TaskListScreen>
    with WidgetsBindingObserver {
  late final MobileRepository _repository;
  late Future<List<MobileTaskSummary>> _tasksFuture;
  late Future<List<MobileDesktopDevice>> _devicesFuture;
  late final NativeWorkspaceSession _session;
  Timer? _poll;
  bool _foreground = true;
  bool _refreshing = false;
  int _failures = 0;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    WidgetsBinding.instance.addObserver(this);
    _session = NativeWorkspaceSession(_repository.client)
      ..addListener(_invalidate);
    _tasksFuture = _loadScoped(_repository.loadTasks);
    _devicesFuture = _loadScoped(_repository.loadDesktopDevices)
        .catchError((_) => const <MobileDesktopDevice>[]);
    unawaited(_observeRefresh());
  }

  Future<T> _loadScoped<T>(Future<T> Function() load) async {
    await _session.ready;
    if (!_session.active ||
        _session.generation != _repository.client.authGeneration) {
      throw StateError('账号或连接已切换，请重新打开任务');
    }
    final value = await load();
    final base = await _repository.client.resolveSessionBaseUrl();
    if (!_session.active ||
        _session.generation != _repository.client.authGeneration ||
        base != _session.base) {
      throw StateError('账号或连接已切换，请重新打开任务');
    }
    return value;
  }

  void _invalidate() {
    _poll?.cancel();
    if (mounted) setState(() {});
  }

  Future<void> _observeRefresh() async {
    _refreshing = true;
    try {
      await Future.wait([_tasksFuture, _devicesFuture]);
      _failures = 0;
    } catch (_) {
      if (_failures < 5) _failures++;
    } finally {
      _refreshing = false;
      _schedulePoll();
    }
  }

  void _schedulePoll() {
    _poll?.cancel();
    if (!mounted || !_foreground || !_session.active) return;
    const delays = [5, 10, 20, 40, 60];
    final seconds = _failures == 0 ? 15 : delays[_failures - 1];
    _poll = Timer(Duration(seconds: seconds), () {
      if (!mounted || !_foreground || !_session.active) return;
      if (ModalRoute.of(context)?.isCurrent == true) {
        unawaited(_refresh());
      } else {
        _schedulePoll();
      }
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    _poll?.cancel();
    if (_foreground && ModalRoute.of(context)?.isCurrent == true) {
      unawaited(_refresh());
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _poll?.cancel();
    _session.dispose();
    super.dispose();
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
            if (!_session.active)
              const Expanded(
                child: Center(child: Text('账号或连接已切换，请返回后重新打开任务')),
              )
            else
              Expanded(
              child: FutureBuilder<List<MobileTaskSummary>>(
                future: _tasksFuture,
                builder: (context, snapshot) {
                  final tasks = snapshot.data ?? const <MobileTaskSummary>[];
                  final refreshing =
                      snapshot.connectionState != ConnectionState.done;
                  if (refreshing && tasks.isEmpty) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  var pendingApprovals = 0;
                  final taskIndexById = <String, int>{};
                  for (var i = 0; i < tasks.length; i++) {
                    final task = tasks[i];
                    if (task.approvalRequired) pendingApprovals++;
                    if (task.taskId.isNotEmpty) {
                      taskIndexById.putIfAbsent(task.taskId, () => i);
                    }
                  }
                  final radius = Radius.circular(XcagiShapeTokens.large);
                  return RefreshIndicator(
                    color: colors.brand,
                    onRefresh: _refresh,
                    child: CustomScrollView(
                      key: const PageStorageKey<String>('mobile-task-list'),
                      physics: const AlwaysScrollableScrollPhysics(),
                      slivers: [
                        if (refreshing)
                          const SliverToBoxAdapter(
                            child: LinearProgressIndicator(),
                          ),
                        if (snapshot.hasError || tasks.isEmpty)
                          SliverToBoxAdapter(
                            child: ListTile(
                              title: Text(
                                snapshot.hasError
                                    ? mobileErrorText(snapshot.error)
                                    : '暂无任务',
                              ),
                              subtitle: const Text('下拉刷新，或点击重试'),
                              trailing: const Icon(Icons.refresh),
                              onTap: _refresh,
                            ),
                          ),
                        if (pendingApprovals > 0)
                          SliverToBoxAdapter(
                            child: Padding(
                              padding: const EdgeInsets.only(bottom: 8),
                              child: WeCellGroup(
                                children: [
                                  WeCell(
                                    title: '待审批',
                                    subtitle: '$pendingApprovals 项任务需要你确认',
                                    icon: Icons.fact_check_outlined,
                                    iconColor: colors.brand,
                                    iconBg: colors.brandContainer,
                                    showDivider: false,
                                    onTap: refreshing ? null : _openApprovals,
                                  ),
                                ],
                              ),
                            ),
                          ),
                        if (tasks.isNotEmpty)
                          SliverPadding(
                            padding: const EdgeInsets.symmetric(horizontal: 16),
                            sliver: DecoratedSliver(
                              decoration: BoxDecoration(
                                color: colors.surface,
                                borderRadius: BorderRadius.all(radius),
                                border: Border.all(
                                  color: colors.divider.withValues(alpha: 0.45),
                                ),
                              ),
                              sliver: SliverPadding(
                                padding: const EdgeInsets.all(1),
                                sliver: SliverList(
                                  delegate: SliverChildBuilderDelegate(
                                    (context, index) {
                                      final task = tasks[index];
                                      final isFirst = index == 0;
                                      final isLast = index == tasks.length - 1;
                                      final cell = _TaskCell(
                                        task: task,
                                        onTap: refreshing || task.taskId.isEmpty
                                            ? null
                                            : () => _openTask(task),
                                        showDivider: !isLast,
                                      );
                                      // Valid unique identities survive reorder.
                                      // Malformed duplicate or empty IDs cannot
                                      // provide stable identity; use a local key.
                                      final key = taskIndexById[task.taskId] == index
                                          ? ValueKey<String>(task.taskId)
                                          : ValueKey<int>(index);
                                      return KeyedSubtree(
                                        key: key,
                                        child: isFirst || isLast
                                            ? ClipRRect(
                                                borderRadius:
                                                    BorderRadius.vertical(
                                                  top: isFirst
                                                      ? radius
                                                      : Radius.zero,
                                                  bottom: isLast
                                                      ? radius
                                                      : Radius.zero,
                                                ),
                                                child: cell,
                                              )
                                            : cell,
                                      );
                                    },
                                    childCount: tasks.length,
                                    addAutomaticKeepAlives: false,
                                    findChildIndexCallback: (key) =>
                                        key is ValueKey<String>
                                            ? taskIndexById[key.value]
                                            : null,
                                  ),
                                ),
                              ),
                            ),
                          ),
                        SliverToBoxAdapter(
                          child: Padding(
                            padding: const EdgeInsets.only(top: 8, bottom: 24),
                            child: _DesktopStatusLine(future: _devicesFuture),
                          ),
                        ),
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
    if (!mounted || !_session.active || _refreshing) return;
    _poll?.cancel();
    setState(() {
      _tasksFuture = _loadScoped(_repository.loadTasks);
      _devicesFuture = _loadScoped(_repository.loadDesktopDevices)
          .catchError((_) => const <MobileDesktopDevice>[]);
    });
    await _observeRefresh();
  }

  Future<void> _openTask(MobileTaskSummary task) async {
    if (!_session.active || _refreshing) return;
    await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => NativeTaskWorkspaceScreen(
            taskId: task.taskId,
            activeModId: task.activeModId,
            repository: _repository)));
    if (mounted) await _refresh();
  }

  void _openApprovals() {
    if (!_session.active || _refreshing) return;
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

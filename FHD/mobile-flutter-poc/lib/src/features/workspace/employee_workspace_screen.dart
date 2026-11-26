import 'dart:async';

import 'package:flutter/material.dart';

import '../../api/mobile_models.dart';
import '../../api/mobile_session_store.dart';
import '../../data/ai_employee_profile.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../policy/mobile_error_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../../widgets/app_avatar.dart';
import '../../policy/avatar_policy.dart';
import '../contacts/employee_profile_screen.dart';
import '../tasks/task_list_screen.dart';

/// Native counterpart of EmployeeWorkspaceView: account employees, shared
/// workspace switches and task status. Never renders a desktop document.
class EmployeeWorkspaceScreen extends StatefulWidget {
  const EmployeeWorkspaceScreen({super.key, this.repository});
  final MobileRepository? repository;

  @override
  State<EmployeeWorkspaceScreen> createState() =>
      _EmployeeWorkspaceScreenState();
}

class _EmployeeWorkspaceScreenState extends State<EmployeeWorkspaceScreen> with WidgetsBindingObserver {
  late final MobileRepository _repository;
  late final bool _ownsRepository;
  StreamSubscription<MobileSessionData>? _subscription;
  final _search = TextEditingController();
  List<AiEmployeeProfile>? _employees;
  List<MobileTaskSummary>? _tasks;
  Map<String, bool>? _enabled;
  String? _employeeError, _prefsError, _taskError, _scope, _base, _saving;
  var _loadId = 0;
  var _generation = 0;
  var _loading = true;
  var _blocked = false;
  var _onlyEnabled = false;
  Timer? _statusTimer;
  bool _refreshing = false;
  bool _foreground = true;
  DateTime? _taskVerifiedAt;
  int _prefsRevision = 0;

  String _key(MobileSessionData session) =>
      '${_repository.client.authGeneration}|${session.serverMode}|${session.fhdHost}|${session.localBaseUrl}';

  @override
  void initState() {
    super.initState();
    _ownsRepository = widget.repository == null &&
        MobileRepositoryScope.maybeRead(context) == null;
    _repository =
        MobileRepositoryScope.resolve(context, explicit: widget.repository);
    _subscription = _repository.client.sessionChanges.listen((session) {
      if (mounted && _scope != null && _key(session) != _scope) {
        ++_loadId;
        setState(() {
          _blocked = true;
          _employees = null;
          _tasks = null;
          _enabled = null;
        });
      }
    });
    WidgetsBinding.instance.addObserver(this);
    _statusTimer = Timer.periodic(const Duration(seconds: 15), (_) {
      if (mounted && _foreground && (ModalRoute.of(context)?.isCurrent ?? true)) unawaited(_refreshStatus());
    });
    unawaited(_load());
  }

  @override
  void dispose() {
    _statusTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    _subscription?.cancel();
    _search.dispose();
    if (_ownsRepository) unawaited(_repository.dispose());
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    if (_foreground && mounted && (ModalRoute.of(context)?.isCurrent ?? true)) unawaited(_refreshStatus());
  }

  Future<void> _refreshStatus() async {
    if (_blocked || _loading || _refreshing || _scope == null) return;
    _refreshing = true;
    final loadId = _loadId;
    final revision = _prefsRevision;
    final api = _repository.client;
    bool active() => mounted && !_blocked && loadId == _loadId && _generation == api.authGeneration;
    bool prefsActive() => active() && _saving == null && revision == _prefsRevision;
    try {
      await Future.wait([
        _repository.loadTasks(limit: 200).then((rows) {
          if (active()) setState(() { _tasks = rows; _taskError = null; _taskVerifiedAt = DateTime.now(); });
        }).catchError((Object error) {
          if (active()) setState(() { _taskError = mobileErrorText(error); });
        }),
        if (_saving == null)
          api.workspacePreferences().then((response) {
            if (prefsActive()) {
              final values = _preferences(response);
              setState(() { _enabled = values; _prefsError = null; });
            }
          }).catchError((Object error) {
            if (prefsActive()) setState(() { _enabled = null; _prefsError = mobileErrorText(error); });
          }),
      ]);
    } finally {
      _refreshing = false;
    }
  }

  Future<void> _load() async {
    if (_blocked || _saving != null) return;
    final loadId = ++_loadId;
    setState(() {
      _loading = true;
    });
    final api = _repository.client;
    final generation = api.authGeneration;
    bool active() =>
        mounted &&
        !_blocked &&
        loadId == _loadId &&
        generation == api.authGeneration;
    try {
      final session = await api.loadSession();
      final base = await api.resolveSessionBaseUrl();
      if (!active()) return;
      _scope = _key(session);
      _base = base;
      _generation = generation;
      await Future.wait([
        _repository.loadAiEmployees().then((rows) {
          if (active()) {
            setState(() {
              _employees = rows;
              _employeeError = null;
            });
          }
        }).catchError((Object error) {
          if (active()) {
            setState(() {
              _employees = null;
              _employeeError = mobileErrorText(error);
            });
          }
        }),
        api.workspacePreferences().then((response) {
          final values = _preferences(response);
          if (active()) {
            setState(() {
              _enabled = values;
              _prefsError = null;
            });
          }
        }).catchError((Object error) {
          if (active()) {
            setState(() {
              _enabled = null;
              _prefsError = mobileErrorText(error);
            });
          }
        }),
        _repository.loadTasks(limit: 200).then((rows) {
          if (active()) {
            setState(() {
              _tasks = rows;
              _taskError = null;
              _taskVerifiedAt = DateTime.now();
            });
          }
        }).catchError((Object error) {
          if (active()) {
            setState(() {
              _tasks = null;
              _taskError = mobileErrorText(error);
            });
          }
        }),
      ]);
    } catch (error) {
      if (active()) {
        setState(() {
          _employeeError = mobileErrorText(error);
        });
      }
    } finally {
      if (active()) {
        setState(() {
          _loading = false;
        });
      }
    }
  }

  Map<String, bool> _preferences(Map<String, Object?> response) {
    if (response['success'] != true || response['owner_id'] == null) {
      throw StateError('无法确认工作区归属，请重新登录');
    }
    final data = response['data'];
    final values = data is Map ? data['workflow_ai_employees'] : null;
    return {
      if (values is Map)
        for (final entry in values.entries)
          if (entry.value is bool) entry.key.toString(): entry.value as bool
    };
  }

  Future<void> _toggle(AiEmployeeProfile employee, bool enabled) async {
    if (_blocked || _enabled == null || _saving != null || _base == null) {
      return;
    }
    final scope = _scope;
    ++_prefsRevision;
    setState(() {
      _saving = employee.employeeId;
    });
    try {
      final session = await _repository.client.loadSession();
      if (!mounted || _blocked || _key(session) != scope) return;
      final response = await _repository.client.setWorkspaceEmployeeEnabled(
        employee.employeeId,
        enabled,
        expectedGeneration: _generation,
        expectedBase: _base!,
      );
      if (!mounted || _blocked || _scope != scope) return;
      final values = _preferences(response);
      if (values[employee.employeeId] != enabled) throw StateError('服务器未确认托管状态');
      setState(() {
        _enabled = values;
        _prefsError = null;
      });
    } catch (error) {
      if (mounted && !_blocked && _scope == scope) {
        setState(() { _enabled = null; _prefsError = mobileErrorText(error); });
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(mobileErrorText(error))));
      }
    } finally {
      if (mounted) {
        setState(() {
          _saving = null;
        });
      }
    }
  }

  Widget _employeeTasks(AiEmployeeProfile employee) {
    final colors = AppTheme.colors(context);
    final tasks = (_tasks ?? const <MobileTaskSummary>[]).where((task) => task.employeeIds.contains(employee.employeeId)).toList();
    final active = tasks.where((task) => !const {'completed', 'cancelled', 'skipped'}.contains(task.employeeStatus(employee.employeeId))).toList();
    final visible = active.isNotEmpty ? active : tasks;
    const labels = {'running': '执行中', 'planning': '分析中', 'queued': '待执行', 'pending': '待处理', 'waiting_user': '待确认', 'waiting_approval': '待审批', 'awaiting_approval': '待审批', 'completed': '已完成', 'blocked': '阻塞', 'failed': '失败', 'paused': '已暂停', 'unknown': '结果待核对', 'cancelled': '已取消', 'skipped': '已跳过'};
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(_tasks == null || _taskError != null ? '任务状态待核实' : visible.isEmpty ? '最近任务中暂无该员工的关联记录' : '关联任务 ${tasks.length} · 待处理 ${active.length}', style: TextStyle(color: colors.textSecondary)),
        for (final task in visible.take(3)) ...[
          const SizedBox(height: 6),
          Text('${_taskError != null ? '上次记录' : labels[task.employeeStatus(employee.employeeId)] ?? '状态待核对'} · ${task.title}', maxLines: 2, overflow: TextOverflow.ellipsis),
          if (!task.outcomeUncertain && _taskError == null && task.employeeIds.length == 1 && task.progressPercent > 0)
            Text('任务进度 ${task.progressPercent}%', style: TextStyle(color: colors.textSecondary)),
        ],
        if (visible.length > 3) Text('另有 ${visible.length - 3} 项 · 在任务列表查看', style: TextStyle(color: colors.textSecondary)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final keyword = _search.text.trim().toLowerCase();
    final employees = (_employees ?? const <AiEmployeeProfile>[])
        .where((employee) =>
            (!_onlyEnabled || _enabled?[employee.employeeId] == true) &&
            (keyword.isEmpty ||
                '${employee.name} ${employee.summary} ${employee.modName}'
                    .toLowerCase()
                    .contains(keyword)))
        .toList();
    final enabledCount = _enabled == null || _employees == null
        ? null
        : _employees!
            .where((employee) => _enabled![employee.employeeId] == true)
            .length;
    final activeTasks = _taskError != null ? null : _tasks
        ?.where((task) => !task.outcomeUncertain && const {'queued', 'planning', 'running', 'retrying', 'in_progress', 'processing'}.contains(task.status)).length;
    final pending = _taskError != null ? null : _tasks?.where((task) => task.approvalRequired || task.attentionState == 'approval_required' || task.status == 'waiting_user').length;
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
          child: Column(children: [
        WeTopBar(
            title: '员工空间',
            showBack: true,
            onBack: () => Navigator.of(context).maybePop(),
            actions: [
              IconButton(
                  tooltip: '刷新',
                  onPressed: _blocked || _loading ? null : _load,
                  icon: const Icon(Icons.refresh))
            ]),
        if (_blocked)
          const Expanded(child: Center(child: Text('账号或连接已切换，请重新打开工作台')))
        else
          Expanded(
              child: RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                    children: [
                      Text('员工与任务',
                          style: Theme.of(context)
                              .textTheme
                              .headlineSmall
                              ?.copyWith(fontWeight: FontWeight.w700)),
                      const SizedBox(height: 6),
                      Text('查看员工、管理托管，跟进每一项任务。',
                          style: TextStyle(color: colors.textSecondary)),
                      const SizedBox(height: 20),
                      Text(_taskError != null ? '任务状态待核实 · 保留上次记录' : _taskVerifiedAt == null ? '正在同步任务' : '每 15 秒核对 · 最近最多 200 条任务', style: TextStyle(color: colors.textSecondary)),
                      const SizedBox(height: 12),
                      LayoutBuilder(
                          builder: (context, constraints) =>
                              Wrap(spacing: 10, runSpacing: 10, children: [
                                for (final metric in [
                                  ('员工', _employees?.length),
                                  ('已托管', enabledCount),
                                  ('进行中任务', activeTasks),
                                  ('待确认', pending)
                                ])
                                  SizedBox(
                                      width: (constraints.maxWidth - 10) / 2,
                                      child: Card(
                                          margin: EdgeInsets.zero,
                                          child: Padding(
                                              padding: const EdgeInsets.all(16),
                                              child: Column(
                                                  crossAxisAlignment:
                                                      CrossAxisAlignment.start,
                                                  children: [
                                                    Text(metric.$1,
                                                        style: TextStyle(
                                                            color: colors
                                                                .textSecondary)),
                                                    const SizedBox(height: 8),
                                                    Text(
                                                        metric.$2?.toString() ??
                                                            '—',
                                                        style: Theme.of(context)
                                                            .textTheme
                                                            .headlineSmall
                                                            ?.copyWith(
                                                                fontWeight:
                                                                    FontWeight
                                                                        .w700)),
                                                  ]))))
                              ])),
                      const SizedBox(height: 16),
                      WeCellGroup(children: [
                        WeCell(
                            title: '任务与处理结果',
                            subtitle: _taskError == null
                                ? '查看进度、待确认事项与结果'
                                : '任务暂未同步，可打开后重试',
                            icon: Icons.task_alt,
                            showDivider: false,
                            onTap: () => Navigator.of(context).push(
                                MaterialPageRoute(
                                    builder: (_) => TaskListScreen(
                                        repository: _repository))))
                      ]),
                      const SizedBox(height: 20),
                      TextField(
                          controller: _search,
                          onChanged: (_) => setState(() {}),
                          decoration: const InputDecoration(
                              prefixIcon: Icon(Icons.search),
                              hintText: '搜索员工、能力或所属应用',
                              border: OutlineInputBorder())),
                      const SizedBox(height: 10),
                      Wrap(spacing: 8, children: [
                        ChoiceChip(
                            label: const Text('全部员工'),
                            selected: !_onlyEnabled,
                            onSelected: (_) => setState(() {
                                  _onlyEnabled = false;
                                })),
                        ChoiceChip(
                            label: const Text('已托管'),
                            selected: _onlyEnabled,
                            onSelected: _enabled == null
                                ? null
                                : (_) => setState(() {
                                      _onlyEnabled = true;
                                    })),
                      ]),
                      if (_prefsError != null)
                        Padding(
                            padding: const EdgeInsets.symmetric(vertical: 12),
                            child: Text('托管状态未同步：$_prefsError',
                                style: TextStyle(color: colors.textSecondary))),
                      if (_loading)
                        const Padding(
                            padding: EdgeInsets.all(20),
                            child: Center(child: CircularProgressIndicator())),
                      if (_employeeError != null)
                        Padding(
                            padding: const EdgeInsets.all(16),
                            child: Column(children: [
                              Text(_employeeError!),
                              TextButton(
                                  onPressed: _load, child: const Text('重试'))
                            ]))
                      else if (!_loading && employees.isEmpty)
                        const Padding(
                            padding: EdgeInsets.all(28),
                            child: Center(child: Text('暂无符合条件的员工'))),
                      for (final employee in employees)
                        Card(
                            margin: const EdgeInsets.only(top: 10),
                            child: Column(children: [
                              ListTile(
                                  contentPadding:
                                      const EdgeInsets.fromLTRB(16, 8, 16, 0),
                                  leading: AppAvatar(
                                      imageSource: employee.avatarUrl,
                                      fallback: employeeAvatarFallback(employeeId: employee.employeeId, name: employee.name),
                                      size: 42,
                                      borderRadius: BorderRadius.circular(21),
                                      contentDescription: employee.name),
                                  title: Text(employee.name),
                                  subtitle: Text(employee.modName),
                                  trailing: const Icon(Icons.chevron_right),
                                  onTap: () => Navigator.of(context).push(
                                      MaterialPageRoute(
                                          builder: (_) =>
                                              AiEmployeeProfileScreen(
                                                  employee: employee,
                                                  repository: _repository)))),
                              Padding(
                                  padding: const EdgeInsets.symmetric(
                                      horizontal: 16, vertical: 8),
                                  child: Align(
                                      alignment: Alignment.centerLeft,
                                      child: Text(employee.summary,
                                          maxLines: 3,
                                          overflow: TextOverflow.ellipsis,
                                          style: TextStyle(
                                              color: colors.textSecondary)))),
                              _employeeTasks(employee),
                              SwitchListTile.adaptive(
                                  title: const Text('托管'),
                                  subtitle: Text(_enabled == null
                                      ? '等待状态同步'
                                      : _enabled![employee.employeeId] == true
                                          ? '已开启，与桌面工作区同步'
                                          : '未开启'),
                                  value: _enabled?[employee.employeeId] == true,
                                  onChanged: _enabled == null || _saving != null
                                      ? null
                                      : (value) => _toggle(employee, value)),
                            ])),
                    ],
                  ))),
      ])),
    );
  }
}

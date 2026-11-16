import 'dart:async';

import 'package:flutter/material.dart';

import '../../api/mobile_api.dart';
import '../../data/mobile_repository.dart';
import '../../platform/workspace_file_export.dart';
import '../../policy/mobile_error_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../workspace/native_workspace_session.dart';

class NativeTaskWorkspaceScreen extends StatefulWidget {
  const NativeTaskWorkspaceScreen(
      {super.key,
      required this.taskId,
      required this.repository,
      this.activeModId = ''});
  final String taskId;
  final String activeModId;
  final MobileRepository repository;
  @override
  State<NativeTaskWorkspaceScreen> createState() =>
      _NativeTaskWorkspaceScreenState();
}

class _NativeTaskWorkspaceScreenState extends State<NativeTaskWorkspaceScreen>
    with WidgetsBindingObserver {
  late final NativeWorkspaceSession _session;
  Timer? _timer;
  Map<String, Object?>? _task;
  String? _error, _message;
  bool _loading = false, _busy = false, _stale = true;
  static const _base = 'api/mobile/v1/workspace/agent';
  String get _path => '$_base/tasks/${Uri.encodeComponent(widget.taskId)}';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _session = NativeWorkspaceSession(widget.repository.client,
        activeModId: widget.activeModId)
      ..addListener(_invalidate);
    unawaited(_load());
    _startPolling();
  }

  void _startPolling() {
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 15), (_) {
      if (!_busy && !_loading && _session.active) unawaited(_load());
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      unawaited(_load());
      _startPolling();
    } else {
      _timer?.cancel();
    }
  }

  void _invalidate() {
    if (mounted) {
      setState(() {
        _task = null;
        _stale = true;
        _error = '账号或连接已切换，请返回后重新打开';
      });
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _timer?.cancel();
    _session.dispose();
    super.dispose();
  }

  Future<Map<String, Object?>?> _load() async {
    if (_loading || !_session.active) return null;
    setState(() {
      _loading = true;
    });
    try {
      final result = await _session.request(_path);
      final task = _map(result['data']);
      if (task['task_id'] != widget.taskId) throw StateError('任务不存在或无权查看');
      if (!mounted || !_session.active) return null;
      setState(() {
        _task = task;
        _stale = false;
        _error = null;
      });
      return task;
    } catch (error) {
      if (mounted && _session.active) {
        setState(() {
          _error = mobileErrorText(error);
          _stale = true;
        });
      }
      return null;
    } finally {
      if (mounted) {
        setState(() {
          _loading = false;
        });
      }
    }
  }

  Future<void> _action(String action) async {
    if (_busy || _stale || !_session.active) return;
    if (['cancel', 'retry', 'approve'].contains(action)) {
      final yes = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
                title: Text('${_actions[action]}？'),
                content: Text(action == 'approve'
                    ? '将批准当前等待确认的步骤并继续执行。请先核对下方执行内容。'
                    : action == 'retry'
                        ? '将重新尝试这项任务。'
                        : '将请求停止这项任务，已经完成的操作不会撤销。'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('返回')),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('确认'))
                ],
              ));
      if (yes != true || !mounted || !_session.active) return;
    }
    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      final task = await _load();
      if (task == null || _map(task['capabilities'])[action] != true) {
        throw StateError('任务状态已变化，请核对后操作');
      }
      final runId =
          '${task['active_run_id'] ?? _map(task['active_run'])['run_id'] ?? ''}';
      if (runId.isEmpty) throw StateError('任务还没有可操作的执行记录');
      final path = '$_base/runs/${Uri.encodeComponent(runId)}';
      if (action == 'approve') {
        Future<void> approve() async {
          final snapshot = await _session.request(path);
          final grant = '${_map(snapshot['approval'])['grant'] ?? ''}';
          if (grant.isEmpty) throw StateError('当前步骤没有可用的确认凭证，请刷新');
          await _session.request('$path/continue',
              method: 'POST', body: {'approval_grant': grant});
        }

        try {
          await approve();
        } on MobileApiException catch (error) {
          if (error.statusCode != 403) rethrow;
          await approve();
        }
      } else {
        await _session.request('$path/$action',
            method: 'POST',
            body: action == 'resume'
                ? {'runtime_context': <String, Object?>{}}
                : {});
      }
      if (mounted && _session.active) {
        setState(() {
          _message = '请求已提交，正在核对执行状态';
        });
        await _load();
      }
    } catch (error) {
      if (mounted && _session.active) {
        setState(() {
          _error = '${mobileErrorText(error)}。请刷新核对状态，避免重复提交。';
          _stale = true;
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
        });
      }
    }
  }

  Future<void> _download(
      Map<String, Object?> run, Map<String, Object?> file) async {
    if (_busy || _stale || !_session.active) return;
    final runId = '${run['run_id'] ?? ''}', id = '${file['artifact_id'] ?? ''}';
    if (runId.isEmpty || id.isEmpty) return;
    setState(() {
      _busy = true;
    });
    try {
      final bytes = await _session.download(
          '$_base/runs/${Uri.encodeComponent(runId)}/artifacts/${Uri.encodeComponent(id)}');
      await shareWorkspaceFile('${file['name'] ?? '任务结果'}', bytes,
          isCurrent: () => mounted && _session.active);
    } catch (error) {
      if (mounted && _session.active) {
        setState(() {
          _error = mobileErrorText(error);
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final task = _task;
    final active = _map(task?['active_run']);
    final progress = _map(task?['progress']);
    final percent = num.tryParse('${progress['percent']}');
    final runs = _maps(task?['runs']);
    return Scaffold(
        backgroundColor: AppTheme.colors(context).page,
        body: SafeArea(
            child: Column(children: [
          WeTopBar(
              title: '任务结果与操作',
              showBack: true,
              onBack: () => Navigator.maybePop(context),
              actions: [
                IconButton(
                    onPressed:
                        _loading || _busy || !_session.active ? null : _load,
                    tooltip: '刷新任务',
                    icon: const Icon(Icons.refresh))
              ]),
          if (_loading || _busy) const LinearProgressIndicator(),
          Expanded(
              child: RefreshIndicator(
                  onRefresh: () async {
                    await _load();
                  },
                  child: ListView(
                      padding: const EdgeInsets.all(20),
                      physics: const AlwaysScrollableScrollPhysics(),
                      children: [
                        if (_error != null)
                          Padding(
                              padding: const EdgeInsets.only(bottom: 16),
                              child: Text(_error!,
                                  key: const ValueKey('task-error'))),
                        if (task != null && _session.active) ...[
                          Text('${task['title'] ?? '任务'}',
                              style: Theme.of(context).textTheme.headlineSmall),
                          const SizedBox(height: 12),
                          Text('状态：${_status(task['status'])}'),
                          if (percent != null)
                            Padding(
                                padding:
                                    const EdgeInsets.symmetric(vertical: 12),
                                child: LinearProgressIndicator(
                                    value: percent.clamp(0, 100) / 100)),
                          if (progress['detail'] != null)
                            Text('${progress['detail']}'),
                          if (_message != null) Text(_message!),
                          const SizedBox(height: 12),
                          Wrap(spacing: 8, runSpacing: 8, children: [
                            for (final action in _actions.entries)
                              if (_map(task['capabilities'])[action.key] ==
                                  true)
                                OutlinedButton(
                                    onPressed: _stale || _busy || _loading
                                        ? null
                                        : () => _action(action.key),
                                    child: Text(action.value))
                          ]),
                          if (active.isNotEmpty) ..._runWidgets(active),
                          if (runs.length > 1) ...[
                            const WeSectionCaption('执行历史'),
                            for (final run in runs)
                              ExpansionTile(
                                  title: Text(
                                      '${_status(run['status'])} · ${run['created_at'] ?? ''}'),
                                  children: _runWidgets(run)),
                          ],
                        ],
                      ]))),
        ])));
  }

  List<Widget> _runWidgets(Map<String, Object?> run) => [
        if ('${run['error'] ?? ''}'.isNotEmpty)
          Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Text('执行说明：${run['error']}')),
        if (_map(run['final_output']).isNotEmpty)
          Card(
              child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('处理结果'),
                        const SizedBox(height: 8),
                        ..._values(_map(run['final_output']))
                      ]))),
        for (final step in _maps(run['steps']))
          Card(
              child: ExpansionTile(
                  title: Text(
                      '${step['description'] ?? step['action'] ?? '处理步骤'}'),
                  subtitle: Text(_status(step['status'])),
                  childrenPadding: const EdgeInsets.all(16),
                  children: [
                if (step['risk'] != null) Text('风险：${step['risk']}'),
                ..._values(_map(step['params'])),
                ..._values(_map(step['output'])),
                if (step['error'] != null) Text('${step['error']}'),
              ])),
        for (final file in _maps(run['artifacts']))
          ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.description_outlined),
              title: Text('${file['name'] ?? '处理结果'}'),
              subtitle: Text('${file['summary'] ?? ''}'),
              trailing: file['artifact_type'] == 'file'
                  ? IconButton(
                      tooltip: '保存或分享文件',
                      onPressed:
                          _busy || _stale ? null : () => _download(run, file),
                      icon: const Icon(Icons.download_outlined))
                  : null),
        if (_maps(run['events']).isNotEmpty)
          ExpansionTile(title: const Text('处理记录'), children: [
            for (final event in _maps(run['events']))
              ListTile(
                  title:
                      Text('${event['message'] ?? event['event_type'] ?? ''}'),
                  subtitle: Text('${event['created_at'] ?? ''}'))
          ]),
      ];
  List<Widget> _values(Map<String, Object?> values) => [
        for (final entry in values.entries)
          if (!entry.key.startsWith('_'))
            Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: SelectableText(
                    '${_labels[entry.key] ?? entry.key}：${_text(entry.value)}'))
      ];
}

Map<String, Object?> _map(Object? value) =>
    value is Map ? Map<String, Object?>.from(value) : {};
List<Map<String, Object?>> _maps(Object? value) => value is List
    ? value.whereType<Map>().map((v) => Map<String, Object?>.from(v)).toList()
    : [];
String _text(Object? value) => value is Map
    ? value.entries
        .map((e) => '${_labels[e.key] ?? e.key}：${_text(e.value)}')
        .join('\n')
    : value is List
        ? value.map(_text).join('\n')
        : '${value ?? '—'}';
String _status(Object? value) =>
    const {
      'queued': '等待执行',
      'running': '正在处理',
      'completed': '已完成',
      'failed': '失败',
      'blocked': '受阻',
      'waiting_user': '等待确认',
      'paused': '已暂停',
      'cancelled': '已取消',
      'pending': '等待处理',
      'succeeded': '成功'
    }[value] ??
    '${value ?? '未知'}';
const _actions = {
  'pause': '暂停',
  'resume': '继续',
  'cancel': '取消任务',
  'retry': '重试任务',
  'approve': '审批并执行'
};
const _labels = {
  'message': '说明',
  'summary': '摘要',
  'response': '回复',
  'result': '结果',
  'status': '状态',
  'success': '成功',
  'count': '数量',
  'name': '名称',
  'title': '标题',
  'reason': '原因',
  'error': '错误',
  'amount': '金额',
  'file_name': '文件名',
  'customer_name': '客户',
  'quantity': '数量'
};

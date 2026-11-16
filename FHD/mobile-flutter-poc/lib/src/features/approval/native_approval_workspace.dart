import 'dart:async';
import 'package:flutter/material.dart';
import '../../data/mobile_repository.dart';
import '../../policy/mobile_error_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../workspace/native_workspace_session.dart';

part 'native_approval_flow_form.part.dart';

class NativeApprovalWorkspace extends StatefulWidget {
  const NativeApprovalWorkspace(
      {super.key,
      required this.repository,
      this.apiBase = 'api/approval',
      this.initialTab = 0});
  final MobileRepository repository;
  final String apiBase;
  final int initialTab;
  @override
  State<NativeApprovalWorkspace> createState() =>
      _NativeApprovalWorkspaceState();
}

class _NativeApprovalWorkspaceState extends State<NativeApprovalWorkspace> {
  late final NativeWorkspaceSession _session;
  List<Map<String, Object?>> _rows = [];
  int _userId = 0, _tab = 0, _page = 1, _pages = 1, _ticket = 0;
  bool _loading = true, _busy = false;
  String? _error;
  bool get _enabled => _session.active && !_loading && !_busy && _error == null;
  @override
  void initState() {
    super.initState();
    _tab = widget.initialTab;
    _session = NativeWorkspaceSession(widget.repository.client,
        activeModId: widget.apiBase.startsWith('api/mod/')
            ? widget.apiBase.split('/').last
            : '')
      ..addListener(_invalidate);
    unawaited(_load());
  }

  void _invalidate() {
    if (mounted) {
      setState(() {
        ++_ticket;
        _rows = [];
        _userId = 0;
      });
    }
  }

  @override
  void dispose() {
    _session.dispose();
    super.dispose();
  }

  Future<void> _load({int page = 1}) async {
    final ticket = ++_ticket, tab = _tab;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      // Approval identities are local business users, not market account IDs.
      final identity = await _session.request('api/auth/session/validate');
      final data = _map(identity['data']);
      final id = [
        identity['local_user_id'],
        data['local_user_id'],
        data['user_id'],
        identity['user_id']
      ]
          .map((v) => int.tryParse('$v') ?? 0)
          .firstWhere((v) => v > 0, orElse: () => 0);
      if (id <= 0) throw StateError('无法确认当前审批账号，请重新登录');
      final result = await _session.request(
          '${widget.apiBase}/${tab == 2 ? 'flows' : 'requests'}',
          query: tab == 2
              ? {}
              : {
                  tab == 0 ? 'approver_id' : 'applicant_id': '$id',
                  'page': '$page',
                  'page_size': '50',
                });
      final rows = _maps(result['data']);
      final total =
          int.tryParse('${_map(result['pagination'])['total']}') ?? rows.length;
      if (mounted && _session.active && ticket == _ticket) {
        setState(() {
          _userId = id;
          _rows = rows;
          _page = page;
          _pages = ((total + 49) ~/ 50).clamp(1, 1000000);
        });
      }
    } catch (error) {
      if (mounted && _session.active && ticket == _ticket) {
        setState(() {
          _error = mobileErrorText(error);
        });
      }
    } finally {
      if (mounted && ticket == _ticket) {
        setState(() {
          _loading = false;
        });
      }
    }
  }

  Future<void> _detail(Map<String, Object?> row) async {
    if (!_enabled) return;
    await Navigator.push(
        context,
        MaterialPageRoute(
            builder: (_) => _ApprovalDetail(
                session: _session,
                apiBase: widget.apiBase,
                id: '${row['id']}',
                userId: _userId)));
    if (mounted && _session.active) await _load(page: _page);
  }

  Future<void> _flow([Map<String, Object?>? row]) async {
    if (!_enabled) return;
    await Navigator.push(
        context,
        MaterialPageRoute(
            builder: (_) => _ApprovalFlowForm(
                session: _session, apiBase: widget.apiBase, initial: row)));
    if (mounted && _session.active) await _load();
  }

  Future<void> _flowAction(Map<String, Object?> row, bool delete) async {
    if (!_enabled) return;
    final title = delete
        ? '删除流程？'
        : row['is_active'] == true
            ? '停用流程？'
            : '启用流程？';
    if (await _confirm(context, title, '${row['flow_name'] ?? ''}') != true ||
        !mounted ||
        !_enabled) {
      return;
    }
    setState(() {
      _busy = true;
    });
    try {
      await _session.request(
          '${widget.apiBase}/flows/${row['id']}${delete ? '' : '/active'}',
          method: delete ? 'DELETE' : 'PATCH',
          body: delete ? null : {'is_active': row['is_active'] != true});
      if (mounted && _session.active) await _load();
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

  Future<void> _cleanup() async {
    if (!_enabled) return;
    setState(() {
      _busy = true;
    });
    final body = <String, Object?>{
      'statuses': _finalStatuses,
      'before_days': 0,
      'scope': 'self'
    };
    try {
      final preview = await _session.request(
          '${widget.apiBase}/requests/cleanup',
          method: 'POST',
          body: {...body, 'dry_run': true});
      final count = int.tryParse('${_map(preview['data'])['matched']}') ?? 0;
      if (!mounted || !_session.active) return;
      if (count == 0) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('暂无可清理的已完成记录')));
        return;
      }
      if (await _confirm(
                  context, '清理 $count 条审批记录？', '仅清理自己发起且已结束的记录，删除后无法恢复。') !=
              true ||
          !_session.active) {
        return;
      }
      final result = await _session.request(
          '${widget.apiBase}/requests/cleanup',
          method: 'POST',
          body: {...body, 'dry_run': false});
      if (mounted && _session.active) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('已清理 ${_map(result['data'])['deleted'] ?? 0} 条记录')));
        await _load();
      }
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
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: AppTheme.colors(context).page,
        body: SafeArea(
            child: Column(children: [
          WeTopBar(
              title: '审批工作台',
              showBack: true,
              onBack: () => Navigator.maybePop(context),
              actions: [
                IconButton(
                    onPressed:
                        _loading || _busy ? null : () => _load(page: _page),
                    icon: const Icon(Icons.refresh),
                    tooltip: '刷新'),
              ]),
          if (!_session.active)
            const Expanded(child: Center(child: Text('账号或连接已切换，请重新打开')))
          else ...[
            Padding(
                padding: const EdgeInsets.all(16),
                child: SegmentedButton<int>(
                    segments: const [
                      ButtonSegment(value: 0, label: Text('待我审批')),
                      ButtonSegment(value: 1, label: Text('我发起的')),
                      ButtonSegment(value: 2, label: Text('流程管理')),
                    ],
                    selected: {
                      _tab
                    },
                    showSelectedIcon: false,
                    onSelectionChanged: _busy
                        ? null
                        : (value) {
                            setState(() {
                              _tab = value.first;
                              _rows = [];
                            });
                            unawaited(_load());
                          })),
            if (_tab == 2)
              Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: Align(
                      alignment: Alignment.centerRight,
                      child: FilledButton.icon(
                          onPressed: _enabled ? () => _flow() : null,
                          icon: const Icon(Icons.add),
                          label: const Text('新建流程')))),
            if (_tab == 1)
              Align(
                  alignment: Alignment.centerRight,
                  child: TextButton(
                      onPressed: _enabled ? _cleanup : null,
                      child: const Text('清理已完成'))),
            if (_loading || _busy) const LinearProgressIndicator(),
            if (_error != null)
              ListTile(
                  title: Text(_error!),
                  trailing: TextButton(
                      onPressed:
                          _loading || _busy ? null : () => _load(page: _page),
                      child: const Text('重试'))),
            Expanded(
                child: RefreshIndicator(
                    onRefresh: () => _load(page: _page),
                    child: ListView(
                        physics: const AlwaysScrollableScrollPhysics(),
                        padding: const EdgeInsets.all(16),
                        children: [
                          if (!_loading && _error == null && _rows.isEmpty)
                            const Padding(
                                padding: EdgeInsets.all(40),
                                child: Center(child: Text('暂无记录'))),
                          for (final row in _rows)
                            Card(
                                child: Padding(
                                    padding: const EdgeInsets.all(16),
                                    child: Column(
                                        crossAxisAlignment:
                                            CrossAxisAlignment.start,
                                        children: [
                                          Text(
                                              '${row[_tab == 2 ? 'flow_name' : 'title'] ?? '未命名'}',
                                              style: Theme.of(context)
                                                  .textTheme
                                                  .titleMedium),
                                          const SizedBox(height: 8),
                                          Text(_tab == 2
                                              ? '${row['is_active'] == true ? '已启用' : '已停用'} · ${_businessLabel(row['business_type'])}'
                                              : '${_status(row['status'])} · ${row['request_no'] ?? ''}'),
                                          if (row['description'] != null)
                                            Padding(
                                                padding: const EdgeInsets.only(
                                                    top: 8),
                                                child: Text(
                                                    '${row['description']}')),
                                          if (_tab != 2)
                                            Text('${row['created_at'] ?? ''}'),
                                          Wrap(
                                              spacing: 12,
                                              children: _tab == 2
                                                  ? [
                                                      TextButton(
                                                          onPressed: _enabled
                                                              ? () => _flow(row)
                                                              : null,
                                                          child: const Text(
                                                              '编辑流程')),
                                                      TextButton(
                                                          onPressed: _enabled
                                                              ? () =>
                                                                  _flowAction(
                                                                      row,
                                                                      false)
                                                              : null,
                                                          child: Text(
                                                              row['is_active'] ==
                                                                      true
                                                                  ? '停用'
                                                                  : '启用')),
                                                      TextButton(
                                                          onPressed: _enabled
                                                              ? () =>
                                                                  _flowAction(
                                                                      row, true)
                                                              : null,
                                                          child:
                                                              const Text('删除')),
                                                    ]
                                                  : [
                                                      TextButton(
                                                          onPressed: _enabled
                                                              ? () =>
                                                                  _detail(row)
                                                              : null,
                                                          child: const Text(
                                                              '查看详情'))
                                                    ]),
                                        ]))),
                          if (_tab != 2)
                            Row(
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: [
                                  TextButton(
                                      onPressed: _enabled && _page > 1
                                          ? () => _load(page: _page - 1)
                                          : null,
                                      child: const Text('上一页')),
                                  Text('$_page / $_pages'),
                                  TextButton(
                                      onPressed: _enabled && _page < _pages
                                          ? () => _load(page: _page + 1)
                                          : null,
                                      child: const Text('下一页')),
                                ]),
                        ]))),
          ],
        ])),
      );
}

class _ApprovalDetail extends StatefulWidget {
  const _ApprovalDetail(
      {required this.session,
      required this.apiBase,
      required this.id,
      required this.userId});
  final NativeWorkspaceSession session;
  final String apiBase, id;
  final int userId;
  @override
  State<_ApprovalDetail> createState() => _ApprovalDetailState();
}

class _ApprovalDetailState extends State<_ApprovalDetail> {
  Map<String, Object?>? _detail;
  bool _loading = true, _busy = false;
  String? _error;
  String get _path =>
      '${widget.apiBase}/requests/${Uri.encodeComponent(widget.id)}';
  bool get _enabled =>
      widget.session.active &&
      !_loading &&
      !_busy &&
      _error == null &&
      _detail != null;
  bool _canApprove(Map<String, Object?> detail) =>
      !_finalStatuses.contains(detail['status']) &&
      ((detail['current_approvers'] is List &&
              (detail['current_approvers'] as List).contains(widget.userId)) ||
          detail['business_type'] == 'workflow_tool' &&
              detail['current_node_id'] == null);
  bool _owns(Map<String, Object?> detail) =>
      detail['applicant_id'] == widget.userId;
  bool _can(String action, Map<String, Object?> detail) => switch (action) {
        'approve' || 'reject' => _canApprove(detail),
        'withdraw' => _owns(detail) &&
            const ['pending', 'in_progress'].contains(detail['status']),
        'delete' => _owns(detail) && _finalStatuses.contains(detail['status']),
        _ => false,
      };
  @override
  void initState() {
    super.initState();
    widget.session.addListener(_invalidate);
    unawaited(_load());
  }

  void _invalidate() {
    if (mounted) {
      setState(() {
        _detail = null;
      });
    }
  }

  @override
  void dispose() {
    widget.session.removeListener(_invalidate);
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await widget.session.request(_path);
      if (mounted && widget.session.active) {
        setState(() {
          _detail = _map(result['data']);
        });
      }
    } catch (error) {
      if (mounted && widget.session.active) {
        setState(() {
          _error = mobileErrorText(error);
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          _loading = false;
        });
      }
    }
  }

  Future<void> _action(String action) async {
    if (!_enabled || !_can(action, _detail!)) return;
    final label = _actionLabel[action]!;
    final opinion = action == 'approve' || action == 'reject'
        ? await _opinion(context, label, action == 'approve' ? '同意' : '')
        : await _confirm(context, '$label这条审批？',
                    action == 'delete' ? '删除后无法恢复。' : '撤回后审批将结束。') ==
                true
            ? ''
            : null;
    if (opinion == null || !mounted || !_enabled) return;
    setState(() {
      _busy = true;
    });
    try {
      // Re-read immediately before a consequential decision; the server remains authoritative.
      final fresh = _map((await widget.session.request(_path))['data']);
      if (!_can(action, fresh)) throw StateError('审批状态或权限已变化，请刷新后查看');
      final result = await widget.session
          .request('$_path${action == 'delete' ? '' : '/$action'}',
              method: action == 'delete' ? 'DELETE' : 'POST',
              body: action == 'delete'
                  ? null
                  : {
                      if (action == 'approve' || action == 'reject')
                        'approver_id': widget.userId,
                      if (action == 'approve') 'opinion': opinion,
                      if (action == 'reject') 'reason': opinion,
                    });
      if (!mounted || !widget.session.active) return;
      if (action == 'delete') {
        Navigator.pop(context);
        return;
      }
      await _load();
      // Some actions return execution receipts that are not persisted in detail.
      final receipt = _map(result['data'])['workflow_execution'];
      if (mounted &&
          widget.session.active &&
          receipt != null &&
          _detail != null) {
        setState(() {
          _detail = {..._detail!, 'workflow_execution': receipt};
        });
      }
    } catch (error) {
      if (mounted && widget.session.active) {
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
  Widget build(BuildContext context) => Scaffold(
      backgroundColor: AppTheme.colors(context).page,
      body: SafeArea(
          child: Column(children: [
        WeTopBar(
            title: '审批详情',
            showBack: true,
            onBack: () => Navigator.maybePop(context),
            actions: [
              IconButton(
                  onPressed: _busy ? null : _load,
                  icon: const Icon(Icons.refresh),
                  tooltip: '刷新')
            ]),
        if (_loading || _busy) const LinearProgressIndicator(),
        Expanded(
            child: !widget.session.active
                ? const Center(child: Text('账号或连接已切换，请重新打开'))
                : ListView(padding: const EdgeInsets.all(16), children: [
                    if (_error != null)
                      ListTile(
                          title: Text(_error!),
                          trailing: TextButton(
                              onPressed: _busy ? null : _load,
                              child: const Text('重试'))),
                    if (_detail case final detail?) ...[
                      Card(
                          child: Padding(
                              padding: const EdgeInsets.all(16),
                              child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text('${detail['title'] ?? ''}',
                                        style: Theme.of(context)
                                            .textTheme
                                            .titleLarge),
                                    const SizedBox(height: 12),
                                    Text(_status(detail['status'])),
                                    Text(
                                        '${detail['request_no'] ?? ''} · ${_businessLabel(detail['business_type'])}'),
                                    Text('${detail['description'] ?? ''}'),
                                    Text(
                                        '发起时间：${detail['created_at'] ?? '未提供'}'),
                                    if (detail['current_node_name'] != null)
                                      Text(
                                          '当前节点：${detail['current_node_name']}'),
                                  ]))),
                      if (_map(detail['business_data']).isNotEmpty)
                        _recordCard('申请内容', _map(detail['business_data'])),
                      for (final record in _maps(detail['records']))
                        _recordCard(
                            '${record['node_name'] ?? '处理记录'} · ${_status(record['action'])}',
                            {
                              '处理人': record['approver_name'] ??
                                  record['approver_id'],
                              '意见': record['opinion'],
                              '时间': record['created_at'],
                            }),
                      if (_map(detail['workflow_execution']).isNotEmpty)
                        _recordCard(
                            '工作流执行结果', _map(detail['workflow_execution'])),
                      Wrap(spacing: 12, runSpacing: 8, children: [
                        for (final action in _actionLabel.keys)
                          if (_can(action, detail))
                            FilledButton(
                                onPressed:
                                    _enabled ? () => _action(action) : null,
                                child: Text(_actionLabel[action]!)),
                      ]),
                    ],
                  ])),
      ])));
}

const _finalStatuses = ['approved', 'rejected', 'withdrawn', 'cancelled'];
const _actionLabel = {
  'approve': '通过',
  'reject': '拒绝',
  'withdraw': '撤回',
  'delete': '删除'
};
const _businessTypes = {
  'shipment': '出货单',
  'purchase': '采购',
  'expense': '费用报销',
  'contract': '合同',
  'general': '通用',
  'workflow_tool': 'AI 对话操作'
};
String _businessLabel(Object? value) => _businessTypes['$value'] ?? '$value';
String _status(Object? value) =>
    const {
      'pending': '待审批',
      'in_progress': '审批中',
      'approved': '已通过',
      'approve': '通过',
      'rejected': '已拒绝',
      'reject': '拒绝',
      'withdrawn': '已撤回',
      'cancelled': '已取消',
      'completed': '已完成',
      'expired': '已失效',
      'draft': '草稿'
    }['$value'] ??
    '${value ?? '未知状态'}';
Map<String, Object?> _map(Object? value) =>
    value is Map ? Map<String, Object?>.from(value) : {};
List<Map<String, Object?>> _maps(Object? value) => value is List
    ? value.whereType<Map>().map((v) => Map<String, Object?>.from(v)).toList()
    : [];
Future<bool?> _confirm(BuildContext context, String title, String message) =>
    showDialog<bool>(
        context: context,
        builder: (context) =>
            AlertDialog(title: Text(title), content: Text(message), actions: [
              TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('取消')),
              FilledButton(
                  onPressed: () => Navigator.pop(context, true),
                  child: const Text('确认'))
            ]));
Future<String?> _opinion(
    BuildContext context, String title, String initial) async {
  final controller = TextEditingController(text: initial);
  final form = GlobalKey<FormState>();
  final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
              title: Text('$title审批'),
              content: Form(
                  key: form,
                  child: TextFormField(
                      controller: controller,
                      autofocus: true,
                      maxLines: 3,
                      decoration: const InputDecoration(labelText: '审批意见'),
                      validator: (v) =>
                          v == null || v.trim().isEmpty ? '请填写审批意见' : null)),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('取消')),
                FilledButton(
                    onPressed: () {
                      if (form.currentState!.validate()) {
                        Navigator.pop(context, controller.text.trim());
                      }
                    },
                    child: Text('确认$title'))
              ]));
  // Wait for the dialog's reverse transition before releasing its controller.
  await Future<void>.delayed(const Duration(milliseconds: 300));
  controller.dispose();
  return result;
}

Widget _recordCard(String title, Map<String, Object?> data) => Card(
    child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          ..._recordFields(data)
        ])));
Iterable<Widget> _recordFields(Map<String, Object?> data,
    [int depth = 0]) sync* {
  const labels = {
    'tool_id': '工具',
    'action': '操作',
    'params': '业务参数',
    'payload': '内容',
    'order': '订单',
    'items': '明细',
    'customer_name': '客户',
    'product_name': '产品',
    'quantity': '数量',
    'unit_price': '单价',
    'amount': '金额',
    'currency': '币种',
    'workflow_executed': '是否触发执行',
    'success': '执行成功',
    'message': '结果说明',
    'nodes_executed': '已执行节点',
    'nodes_total': '总节点',
    'node_results': '节点结果',
    'error': '错误',
    'recovery_hint': '处理建议'
  };
  for (final entry in data.entries) {
    final label = labels[entry.key] ?? entry.key, value = entry.value;
    if (value == null) continue;
    if (depth < 8 && (value is Map || value is List)) {
      yield Padding(
          padding: const EdgeInsets.only(top: 8),
          child:
              Text(label, style: const TextStyle(fontWeight: FontWeight.w500)));
      yield Padding(
          padding: const EdgeInsets.only(left: 12),
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            ..._recordFields(
                value is Map
                    ? _map(value)
                    : {
                        for (var i = 0; i < (value as List).length; i++)
                          '${i + 1}': value[i]
                      },
                depth + 1),
          ]));
    } else {
      yield SelectableText(
          '$label：${value is bool ? (value ? '是' : '否') : value}');
    }
  }
}

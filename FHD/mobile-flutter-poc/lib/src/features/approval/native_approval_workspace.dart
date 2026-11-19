import 'dart:async';
import 'package:flutter/material.dart';
import '../../data/mobile_repository.dart';
import '../../policy/mobile_error_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../workspace/native_workspace_session.dart';
import '../workspace/workspace_ui.dart';

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
  final _search = TextEditingController();
  String _statusFilter = '';
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
    _search.dispose();
    super.dispose();
  }

  Future<void> _load({int page = 1}) async {
    final ticket = ++_ticket, tab = _tab, status = _statusFilter;
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
                  if (tab == 1 && status.isNotEmpty) 'status': status,
                });
      final rows = _maps(result['data']);
      final total =
          int.tryParse('${_map(result['pagination'])['total']}') ?? rows.length;
      if (mounted && _session.active && ticket == _ticket) {
        final pages = ((total + 49) ~/ 50).clamp(1, 1000000);
        if (page > pages) {
          await _load(page: pages);
          return;
        }
        setState(() {
          _userId = id;
          _rows = rows;
          _page = page;
          _pages = pages;
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

  void _selectTab(int tab) {
    if (tab == _tab || _busy) return;
    setState(() {
      _tab = tab;
      _page = _pages = 1;
      _rows = [];
      _statusFilter = '';
      _search.clear();
    });
    unawaited(_load());
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return WorkspaceScaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        child: Column(
          children: [
            WeTopBar(
              title: '审批工作台',
              showBack: true,
              onBack: () => Navigator.maybePop(context),
              actions: [
                if (_session.active && _tab == 1)
                  IconButton(
                    tooltip: '清理已完成',
                    onPressed: _enabled ? _cleanup : null,
                    icon: const Icon(Icons.cleaning_services_outlined),
                  ),
                IconButton(
                  onPressed: _session.active && !_loading && !_busy
                      ? () => _load(page: _page)
                      : null,
                  icon: const Icon(Icons.refresh),
                  tooltip: '刷新',
                ),
              ],
            ),
            if (!_session.active)
              const Expanded(
                child: Center(child: Text('账号或连接已切换，请重新打开')),
              )
            else ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 4),
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: Wrap(
                    spacing: 8,
                    children: [
                      for (final (tab, label) in const [
                        (0, '待我审批'),
                        (1, '我发起的'),
                        (2, '流程管理'),
                      ])
                        ChoiceChip(
                          label: Text(label),
                          selected: _tab == tab,
                          showCheckmark: false,
                          materialTapTargetSize: MaterialTapTargetSize.padded,
                          onSelected: _busy ? null : (_) => _selectTab(tab),
                        ),
                    ],
                  ),
                ),
              ),
              if (_loading || _busy)
                const LinearProgressIndicator()
              else
                const SizedBox(height: 4),
              Expanded(
                child: WorkspaceTransition(
                  child: RefreshIndicator(
                    key: ValueKey(_tab),
                    onRefresh: () => _load(page: _page),
                    child: _list(),
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _list() {
    final text = Theme.of(context).textTheme;
    final query = _search.text.trim().toLowerCase();
    final matches = _rows
        .where((row) =>
            _tab == 2 ||
            '${row['title'] ?? ''} ${row['request_no'] ?? ''}'
                .toLowerCase()
                .contains(query))
        .toList();
    return ListView(
      key: PageStorageKey((_tab, _page)),
      keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      children: [
        if (_tab == 2)
          OverflowBar(
            alignment: MainAxisAlignment.spaceBetween,
            overflowAlignment: OverflowBarAlignment.start,
            spacing: 12,
            overflowSpacing: 8,
            children: [
              Text('审批流程', style: text.titleMedium),
              FilledButton.icon(
                onPressed: _enabled ? () => _flow() : null,
                icon: const Icon(Icons.add),
                label: const Text('新建流程'),
              ),
            ],
          )
        else ...[
          TextField(
            controller: _search,
            onChanged: (_) => setState(() {}),
            textInputAction: TextInputAction.search,
            decoration: InputDecoration(
              labelText: _pages > 1 ? '搜索本页标题或编号' : '搜索标题或编号',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: _search.text.isEmpty
                  ? null
                  : IconButton(
                      tooltip: '清空搜索',
                      icon: const Icon(Icons.clear),
                      onPressed: () => setState(_search.clear),
                    ),
            ),
          ),
          if (_tab == 1)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: DropdownMenu<String>(
                initialSelection: _statusFilter,
                enabled: !_busy,
                expandedInsets: EdgeInsets.zero,
                label: const Text('审批状态'),
                dropdownMenuEntries: [
                  const DropdownMenuEntry(value: '', label: '全部状态'),
                  for (final status in const [
                    'pending',
                    'in_progress',
                    ..._finalStatuses,
                  ])
                    DropdownMenuEntry(value: status, label: _status(status)),
                ],
                onSelected: (value) {
                  if (value == null || value == _statusFilter) return;
                  setState(() {
                    _statusFilter = value;
                    _page = _pages = 1;
                    _rows = [];
                  });
                  unawaited(_load());
                },
              ),
            ),
        ],
        const SizedBox(height: 12),
        if (_error != null)
          WorkspacePanel(
            child: ListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(_error!),
              trailing: TextButton(
                onPressed: _loading || _busy ? null : () => _load(page: _page),
                child: const Text('重试'),
              ),
            ),
          ),
        if (!_loading && _error == null && matches.isEmpty)
          WorkspacePanel(
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 16),
              child: Column(
                children: [
                  Icon(
                    query.isEmpty ? Icons.inbox_outlined : Icons.search_off,
                    color: AppTheme.colors(context).textSecondary,
                  ),
                  const SizedBox(height: 8),
                  Text(query.isNotEmpty
                      ? '本页没有匹配的审批'
                      : switch (_tab) {
                          0 => '暂无待审批事项',
                          1 => '暂无符合条件的审批',
                          _ => '暂无审批流程',
                        }),
                ],
              ),
            ),
          ),
        for (final row in matches)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: _rowCard(row),
          ),
        if (_tab != 2 && _pages > 1)
          OverflowBar(
            alignment: MainAxisAlignment.center,
            spacing: 8,
            children: [
              TextButton(
                onPressed:
                    _enabled && _page > 1 ? () => _load(page: _page - 1) : null,
                child: const Text('上一页'),
              ),
              Text('$_page / $_pages'),
              TextButton(
                onPressed: _enabled && _page < _pages
                    ? () => _load(page: _page + 1)
                    : null,
                child: const Text('下一页'),
              ),
            ],
          ),
      ],
    );
  }

  Widget _rowCard(Map<String, Object?> row) {
    final theme = Theme.of(context).textTheme;
    final colors = AppTheme.colors(context);
    final isFlow = _tab == 2;
    final isActive = row['is_active'] == true;
    final title =
        row[isFlow ? 'flow_name' : 'title'] ?? (isFlow ? '未命名流程' : '未命名审批');
    final description = '${row['description'] ?? ''}'.trim();
    final metadata = [
      if (row['business_type'] != null) _businessLabel(row['business_type']),
      if (row['request_no'] case final String number when number.isNotEmpty)
        number,
      if (row['created_at'] case final String date
          when !isFlow && date.isNotEmpty)
        _approvalTime(date),
    ];
    return WorkspacePanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('$title', style: theme.titleMedium),
          const SizedBox(height: 8),
          WorkspaceBadge(
            label: isFlow ? (isActive ? '已启用' : '已停用') : _status(row['status']),
            color: isFlow
                ? (isActive ? colors.success : colors.textSecondary)
                : _statusColor(colors, row['status']),
          ),
          if (metadata.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(metadata.join(' · '),
                style: theme.bodySmall?.copyWith(color: colors.textSecondary)),
          ],
          if (description.isNotEmpty &&
              (isFlow || row['business_type'] != 'workflow_tool')) ...[
            const SizedBox(height: 8),
            Text(description, maxLines: 2, overflow: TextOverflow.ellipsis),
          ],
          OverflowBar(
            alignment: MainAxisAlignment.end,
            spacing: 4,
            children: isFlow
                ? [
                    TextButton(
                      onPressed:
                          _enabled ? () => _flowAction(row, false) : null,
                      child: Text(isActive ? '停用' : '启用'),
                    ),
                    TextButton(
                      onPressed: _enabled ? () => _flowAction(row, true) : null,
                      style:
                          TextButton.styleFrom(foregroundColor: colors.danger),
                      child: const Text('删除'),
                    ),
                    FilledButton.tonal(
                      onPressed: _enabled ? () => _flow(row) : null,
                      child: const Text('编辑流程'),
                    ),
                  ]
                : [
                    TextButton(
                      onPressed: _enabled ? () => _detail(row) : null,
                      child: const Text('查看详情'),
                    )
                  ],
          ),
        ],
      ),
    );
  }
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
  bool _requiresRefresh = false;
  String get _path =>
      '${widget.apiBase}/requests/${Uri.encodeComponent(widget.id)}';
  bool get _enabled =>
      widget.session.active &&
      !_loading &&
      !_busy &&
      !_requiresRefresh &&
      _detail != null;
  bool _canReview(Map<String, Object?> detail) =>
      _decisionStatuses.contains(detail['status']) &&
      ((detail['current_approvers'] is List &&
              (detail['current_approvers'] as List).contains(widget.userId)) ||
          detail['business_type'] == 'workflow_tool' &&
              detail['current_node_id'] == null);
  bool _owns(Map<String, Object?> detail) =>
      detail['applicant_id'] == widget.userId;
  bool _can(String action, Map<String, Object?> detail) => switch (action) {
        'approve' => _canReview(detail) && !_runtimeExpired(detail),
        'reject' => _canReview(detail),
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
      _requiresRefresh = true;
    });
    try {
      final result = await widget.session.request(_path);
      if (mounted && widget.session.active) {
        setState(() {
          _detail = _map(result['data']);
          _requiresRefresh = false;
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
      _error = null;
    });
    try {
      // Re-read immediately before a consequential decision; the server remains authoritative.
      final fresh = _map((await widget.session.request(_path))['data']);
      if (!_can(action, fresh)) {
        if (mounted && widget.session.active) {
          setState(() {
            _detail = fresh;
            _error = action == 'approve' && _runtimeExpired(fresh)
                ? '工作流已过期，无法通过'
                : '审批状态或权限已变化，请刷新后查看';
          });
        }
        return;
      }
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
          _requiresRefresh = true;
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
    final colors = AppTheme.colors(context);
    final detail = _detail;
    final actions = !widget.session.active || detail == null
        ? const <String>[]
        : _actionLabel.keys.where((action) => _can(action, detail)).toList();
    return WorkspaceScaffold(
      backgroundColor: colors.page,
      bottomNavigationBar: actions.isEmpty
          ? null
          : Material(
              color: colors.surface,
              child: SafeArea(
                top: false,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                  child: OverflowBar(
                    alignment: MainAxisAlignment.end,
                    spacing: 12,
                    overflowAlignment: OverflowBarAlignment.end,
                    overflowSpacing: 8,
                    children: [
                      for (final action in actions)
                        if (action == 'approve')
                          FilledButton.icon(
                            style: FilledButton.styleFrom(
                              minimumSize: const Size(96, 48),
                            ),
                            onPressed: _enabled ? () => _action(action) : null,
                            icon: const Icon(Icons.check),
                            label: Text(_actionLabel[action]!),
                          )
                        else
                          OutlinedButton(
                            style: OutlinedButton.styleFrom(
                              foregroundColor: colors.danger,
                              minimumSize: const Size(96, 48),
                            ),
                            onPressed: _enabled ? () => _action(action) : null,
                            child: Text(_actionLabel[action]!),
                          ),
                    ],
                  ),
                ),
              ),
            ),
      body: SafeArea(
        bottom: actions.isEmpty,
        child: Column(
          children: [
            WeTopBar(
              title: '审批详情',
              showBack: true,
              onBack: () => Navigator.maybePop(context),
              actions: [
                IconButton(
                  onPressed: widget.session.active && !_busy && !_loading
                      ? _load
                      : null,
                  icon: const Icon(Icons.refresh),
                  tooltip: '刷新',
                ),
              ],
            ),
            if (_loading || _busy)
              const LinearProgressIndicator()
            else
              const SizedBox(height: 4),
            Expanded(
              child: widget.session.active
                  ? ListView(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
                      children: [
                        if (_error != null)
                          WorkspacePanel(
                            child: ListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(_error!),
                              trailing: TextButton(
                                onPressed: _busy || _loading ? null : _load,
                                child: const Text('重试'),
                              ),
                            ),
                          ),
                        if (detail != null) ..._detailPanels(detail),
                      ],
                    )
                  : const Center(child: Text('账号或连接已切换，请重新打开')),
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _detailPanels(Map<String, Object?> detail) {
    final text = Theme.of(context).textTheme;
    final colors = AppTheme.colors(context);
    final description = '${detail['description'] ?? ''}'.trim();
    final data = _map(detail['business_data']);
    final sales = _salesApproval(detail['business_type'], data);
    final records = _maps(detail['records']);
    final execution = _map(detail['workflow_execution']);
    final expired = _runtimeExpired(detail);
    return [
      WorkspacePanel(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (detail['request_no'] != null)
              Text('${detail['request_no']}',
                  style:
                      text.labelMedium?.copyWith(color: colors.textSecondary)),
            Text(sales?.operation ?? '${detail['title'] ?? '审批申请'}',
                style: text.titleLarge),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                WorkspaceBadge(
                  label: _status(detail['status']),
                  color: _statusColor(colors, detail['status']),
                ),
                if (detail['business_type'] != null)
                  WorkspaceBadge(
                      label: sales == null
                          ? _businessLabel(detail['business_type'])
                          : '销售业务'),
              ],
            ),
            if (detail['created_at'] case final String date
                when date.isNotEmpty)
              _detailFact('发起时间', _approvalTime(date)),
            if (detail['current_node_name'] != null)
              _detailFact('当前节点', '${detail['current_node_name']}'),
            if (sales == null && description.isNotEmpty && data.isEmpty) ...[
              const SizedBox(height: 12),
              SelectableText(description),
            ],
          ],
        ),
      ),
      if (expired) ...[
        const SizedBox(height: 12),
        Semantics(
          liveRegion: true,
          child: WorkspacePanel(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.info_outline, color: colors.warning),
                const SizedBox(width: 12),
                const Expanded(
                  child: Text('工作流已过期。请拒绝这条申请，然后重新发起任务。'),
                ),
              ],
            ),
          ),
        ),
      ],
      if (sales != null) ...[
        const SizedBox(height: 12),
        _salesPanel(sales),
      ],
      if (data.isNotEmpty) ...[
        const SizedBox(height: 12),
        _approvalDisclosure(
          sales == null ? '申请内容' : '原始参数',
          [
            if (sales == null && description.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: SelectableText(description),
              ),
            ..._recordFields(data),
          ],
          initiallyExpanded: sales == null,
        ),
      ],
      if (execution.isNotEmpty) ...[
        const SizedBox(height: 12),
        _approvalDisclosure(
          '工作流执行结果',
          _recordFields(execution),
          subtitle:
              execution['message'] is String ? '${execution['message']}' : null,
        ),
      ],
      if (records.isNotEmpty) ...[
        const SizedBox(height: 12),
        _approvalDisclosure('处理记录（${records.length}）', [
          for (final record in records)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                      '${record['node_name'] ?? '审批节点'} · ${_status(record['action'])}',
                      style: text.titleSmall),
                  if (record['approver_name'] != null ||
                      record['approver_id'] != null)
                    _detailFact('处理人',
                        '${record['approver_name'] ?? record['approver_id']}'),
                  if (record['opinion'] case final String opinion
                      when opinion.isNotEmpty)
                    _detailFact('意见', opinion),
                  if (record['created_at'] case final String date
                      when date.isNotEmpty)
                    _detailFact('时间', _approvalTime(date)),
                ],
              ),
            ),
        ]),
      ],
    ];
  }

  Widget _salesPanel(_SalesApproval sale) {
    final text = Theme.of(context).textTheme;
    final colors = AppTheme.colors(context);
    return WorkspacePanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('销售明细', style: text.titleMedium),
          _detailFact('客户', sale.customer),
          if (sale.items.isEmpty) _detailFact('商品', '未填写'),
          for (final item in sale.items) ...[
            const SizedBox(height: 12),
            Text(_display(item['product_name'] ?? item['product_id']),
                style: text.titleSmall),
            _detailFact('型号', _display(item['model_number'])),
            _detailFact('数量', _display(item['quantity'])),
            _detailFact('单价', _display(item['unit_price'])),
          ],
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 8),
            child: Divider(),
          ),
          _detailFact(
            '总金额（参数合计）',
            sale.amount == null ? '金额待确认' : '${sale.amount} ${sale.currency}',
            valueStyle: text.titleMedium?.copyWith(color: colors.textPrimary),
          ),
        ],
      ),
    );
  }
}

const _decisionStatuses = ['pending', 'in_progress'];
const _finalStatuses = ['approved', 'rejected', 'withdrawn', 'cancelled'];
const _actionLabel = {
  'reject': '拒绝',
  'approve': '通过',
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
bool _runtimeExpired(Map<String, Object?> detail) =>
    _decisionStatuses.contains(detail['status']) &&
    detail['runtime_available'] == false;

Color _statusColor(XcagiThemeColors colors, Object? status) => switch (status) {
      'approved' => colors.success,
      'pending' => colors.warning,
      'in_progress' => colors.brand,
      'rejected' || 'expired' => colors.danger,
      _ => colors.textSecondary,
    };

String _approvalTime(String raw) {
  final date = DateTime.tryParse(raw)?.toLocal();
  if (date == null) return raw;
  String two(int value) => value.toString().padLeft(2, '0');
  return '${date.year}-${two(date.month)}-${two(date.day)} ${two(date.hour)}:${two(date.minute)}';
}

String _display(Object? value) => switch (value) {
      final String text when text.trim().isNotEmpty => text,
      final num number => '$number',
      _ => '未填写',
    };

Widget _detailFact(String label, String value, {TextStyle? valueStyle}) =>
    Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Wrap(
        spacing: 8,
        runSpacing: 4,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          Text(label),
          SelectableText(value, style: valueStyle),
        ],
      ),
    );

Widget _approvalDisclosure(
  String title,
  Iterable<Widget> content, {
  bool initiallyExpanded = false,
  String? subtitle,
}) =>
    WorkspacePanel(
      padding: EdgeInsets.zero,
      child: ExpansionTile(
        key: PageStorageKey(title),
        initiallyExpanded: initiallyExpanded,
        title: Text(title),
        subtitle: subtitle == null ? null : Text(subtitle),
        expandedAlignment: Alignment.centerLeft,
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        children: content.toList(),
      ),
    );

typedef _SalesApproval = ({
  String operation,
  String customer,
  String currency,
  List<Map<String, Object?>> items,
  String? amount,
});

_SalesApproval? _salesApproval(
    Object? businessType, Map<String, Object?> data) {
  const salesActions = {
    'create_order': '创建销售订单',
    'quote': '创建销售报价',
    'execute_closed_loop': '销售闭环',
  };
  final operation = salesActions[data['action']];
  if (businessType != 'workflow_tool' ||
      data['tool_id'] != 'sales' ||
      operation == null ||
      data['params'] is! Map) {
    return null;
  }

  final params = _map(data['params']);
  final payload = _map(params['payload']);
  final order = payload['order'] is Map ? _map(payload['order']) : params;
  final rawItems = order['items'];
  final items =
      rawItems is List ? rawItems.map(_map).toList() : <Map<String, Object?>>[];
  return (
    operation: operation,
    customer: _display(order['customer_name']),
    items: items,
    amount: _salesTotal(items),
    currency: switch (order['currency']) {
      final String currency when currency.trim().isNotEmpty => currency,
      null => 'CNY',
      _ => '币种待确认',
    },
  );
}

final _decimalPattern = RegExp(r'^\d+(?:\.\d+)?$');

({BigInt value, int scale})? _decimalTerm(Object? input) {
  final text = input is num || input is String ? '$input'.trim() : '';
  if (text.length > 40 || !_decimalPattern.hasMatch(text)) return null;
  final parts = text.split('.');
  final scale = parts.length == 2 ? parts[1].length : 0;
  return (value: BigInt.parse(parts.join()), scale: scale);
}

String? _salesTotal(List<Map<String, Object?>> items) {
  if (items.isEmpty) return null;
  var total = BigInt.zero;
  var scale = 2;
  for (final item in items) {
    final quantity = _decimalTerm(item['quantity']);
    final price = _decimalTerm(item['unit_price']);
    if (quantity == null || quantity.value <= BigInt.zero || price == null) {
      return null;
    }
    final termScale = quantity.scale + price.scale;
    if (termScale > scale) {
      total *= BigInt.from(10).pow(termScale - scale);
      scale = termScale;
    }
    total +=
        quantity.value * price.value * BigInt.from(10).pow(scale - termScale);
  }
  final digits = total.toString().padLeft(scale + 1, '0');
  final decimalIndex = digits.length - scale;
  return '${digits.substring(0, decimalIndex)}.${digits.substring(decimalIndex)}';
}

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

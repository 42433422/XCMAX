import 'dart:async';
import 'package:flutter/material.dart';
import '../../data/mobile_repository.dart';
import '../../platform/workspace_file_export.dart';
import '../../policy/mobile_error_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../workspace/native_workspace_session.dart';
import '../workspace/workspace_ui.dart';
import 'native_catalog_screen.dart';

part 'native_order_form.part.dart';

class NativeOrdersScreen extends StatefulWidget {
  const NativeOrdersScreen(
      {super.key, required this.repository, required this.apiBase});
  final MobileRepository repository;
  final String apiBase;
  @override
  State<NativeOrdersScreen> createState() => _NativeOrdersScreenState();
}

class _NativeOrdersScreenState extends State<NativeOrdersScreen> {
  late final NativeWorkspaceSession _session;
  final _search = TextEditingController();
  List<Map<String, Object?>> _rows = [];
  bool _loading = true, _busy = false;
  int _ticket = 0;
  String? _error;
  bool get _editable =>
      !_loading && !_busy && _error == null && _session.active;
  @override
  void initState() {
    super.initState();
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
        _rows = [];
        _search.clear();
        ++_ticket;
      });
    }
  }

  @override
  void dispose() {
    _session.dispose();
    _search.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    if (!_session.active) return;
    final ticket = ++_ticket, query = _search.text.trim();
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await _session.request(
          '${widget.apiBase}/orders${query.isEmpty ? '' : '/search'}',
          query: query.isEmpty ? {'limit': '200'} : {'q': query});
      final rows = _records(result);
      if (mounted && _session.active && ticket == _ticket) {
        setState(() {
          _rows = rows;
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

  Future<void> _delete({int? id, String? number}) async {
    if (!_editable) return;
    final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
                title: Text(id == null ? '清空全部出货记录？' : '删除订单 ${number ?? id}？'),
                content: Text(id == null
                    ? '将清空当前业务空间的全部出货记录，包括筛选外的记录，此操作无法撤销。'
                    : '此操作无法撤销。'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('确认删除'))
                ]));
    if (confirmed != true || !mounted || !_editable) return;
    setState(() {
      _busy = true;
    });
    try {
      await _session.request(
          id == null
              ? '${widget.apiBase}/orders/clear-all'
              : '${widget.apiBase}/shipment/orders/$id',
          method: 'DELETE');
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

  Future<void> _create() async {
    await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => NativeOrderFormScreen(
            repository: widget.repository,
            apiBase: widget.apiBase,
            session: _session)));
    if (mounted && _session.active) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final scheme = Theme.of(context).colorScheme;
    return WorkspaceScaffold(
      backgroundColor: colors.page,
      bottomNavigationBar: !_session.active
          ? null
          : Material(
              color: colors.surface,
              elevation: 2,
              child: SafeArea(
                minimum: const EdgeInsets.fromLTRB(16, 10, 16, 10),
                child: FilledButton.icon(
                  onPressed: _editable ? _create : null,
                  icon: const Icon(Icons.add),
                  label: const Text('新建订单'),
                ),
              ),
            ),
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: '出货单记录',
              showBack: true,
              onBack: () => Navigator.maybePop(context),
              actions: [
                PopupMenuButton<String>(
                  tooltip: '订单操作',
                  enabled: _editable && _rows.isNotEmpty,
                  onSelected: (_) => _delete(),
                  itemBuilder: (_) => const [
                    PopupMenuItem(
                      value: 'clear',
                      child: Text('清空全部出货记录'),
                    ),
                  ],
                ),
                IconButton(
                  tooltip: '刷新',
                  onPressed: _session.active && !_busy ? _load : null,
                  icon: const Icon(Icons.refresh),
                ),
              ],
            ),
            if (_loading || _busy) const LinearProgressIndicator(minHeight: 2),
            if (!_session.active)
              const Expanded(
                child: Center(child: Text('账号或连接已切换，请返回后重新打开')),
              )
            else
              Expanded(
                child: RefreshIndicator(
                  onRefresh: _load,
                  child: CustomScrollView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    slivers: [
                      SliverPadding(
                        padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                        sliver: SliverToBoxAdapter(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              TextField(
                                controller: _search,
                                onSubmitted: (_) => _load(),
                                textInputAction: TextInputAction.search,
                                decoration: InputDecoration(
                                  border: const OutlineInputBorder(),
                                  hintText: '搜索客户名或单号',
                                  prefixIcon: const Icon(Icons.search),
                                  suffixIcon: IconButton(
                                    tooltip: '清空搜索',
                                    onPressed: _busy
                                        ? null
                                        : () {
                                            _search.clear();
                                            _load();
                                          },
                                    icon: const Icon(Icons.clear),
                                  ),
                                ),
                              ),
                              const SizedBox(height: 16),
                              WorkspaceBadge(label: '已读取 ${_rows.length} 条'),
                              if (_error != null || !_loading && _rows.isEmpty)
                                Padding(
                                  padding: const EdgeInsets.only(top: 16),
                                  child: WorkspaceTransition(
                                    child: WorkspacePanel(
                                      key: ValueKey(_error),
                                      child: ListTile(
                                        contentPadding: EdgeInsets.zero,
                                        leading: Icon(
                                          _error == null
                                              ? Icons.receipt_long_outlined
                                              : Icons.error_outline,
                                          color: _error == null
                                              ? scheme.primary
                                              : scheme.error,
                                        ),
                                        title: Text(_error ?? '暂无出货记录'),
                                        trailing: _error == null
                                            ? null
                                            : TextButton(
                                                onPressed: _load,
                                                child: const Text('重试'),
                                              ),
                                      ),
                                    ),
                                  ),
                                ),
                            ],
                          ),
                        ),
                      ),
                      SliverPadding(
                        padding: const EdgeInsets.fromLTRB(16, 4, 16, 20),
                        sliver: SliverList.separated(
                          itemCount: _rows.length,
                          separatorBuilder: (_, index) =>
                              const SizedBox(height: 8),
                          itemBuilder: (context, index) =>
                              _record(_rows[index]),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _record(Map<String, Object?> row) {
    final theme = Theme.of(context);
    final parsedId = int.tryParse('${row['id']}');
    final id = parsedId != null && parsedId > 0 ? parsedId : null;
    final number = '${row['order_number'] ?? id ?? '订单'}';
    final customer = row['customer_name'] ??
        row['purchase_unit'] ??
        row['purchase_unit_name'];
    final date = row['date'] ?? row['created_at'];
    final amount = row['total_amount'];
    final status = switch (row['status']) {
      'pending' => '未打印',
      'printed' => '已打印',
      'completed' => '已完成',
      final Object value => value.toString(),
      null => '状态未提供',
    };
    return WorkspacePanel(
      key: ValueKey(id ?? row),
      padding: EdgeInsets.zero,
      child: ListTile(
        leading:
            Icon(Icons.receipt_long_outlined, color: theme.colorScheme.primary),
        title: Text(number, style: theme.textTheme.titleMedium),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (customer != null) Text('$customer'),
            if (date != null) Text('$date'),
            if (amount != null)
              Text('¥$amount', style: theme.textTheme.titleMedium),
            const SizedBox(height: 5),
            WorkspaceBadge(label: status),
          ],
        ),
        trailing: id == null
            ? null
            : PopupMenuButton<String>(
                tooltip: '订单 $number 的操作',
                enabled: _editable,
                onSelected: (_) => _delete(id: id, number: number),
                itemBuilder: (_) => const [
                  PopupMenuItem(value: 'delete', child: Text('删除')),
                ],
              ),
      ),
    );
  }
}

Map<String, Object?> _object(Object? value) =>
    value is Map ? Map<String, Object?>.from(value) : {};
List<Map<String, Object?>> _records(Object? value, [int depth = 0]) {
  if (depth > 4) throw StateError('记录格式无效');
  if (value is List) {
    return value
        .whereType<Map>()
        .map((row) => Map<String, Object?>.from(row))
        .toList();
  }
  final map = _object(value);
  if (map['success'] == false) throw StateError('${map['message'] ?? '读取失败'}');
  final data = map['data'] ?? map['orders'];
  if (data == null) throw StateError('服务未返回有效记录');
  return _records(data, depth + 1);
}

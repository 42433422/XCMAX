import 'dart:async';
import 'package:flutter/material.dart';
import '../../data/mobile_repository.dart';
import '../../platform/workspace_file_export.dart';
import '../../policy/mobile_error_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../workspace/native_record_editor.dart';
import '../workspace/native_workspace_session.dart';

class NativeMaterialsScreen extends StatefulWidget {
  const NativeMaterialsScreen(
      {super.key,
      required this.repository,
      required this.title,
      this.activeModId = ''});
  final MobileRepository repository;
  final String title, activeModId;
  @override
  State<NativeMaterialsScreen> createState() => _NativeMaterialsScreenState();
}

class _NativeMaterialsScreenState extends State<NativeMaterialsScreen> {
  late final NativeWorkspaceSession _session;
  final _search = TextEditingController();
  String _tab = 'materials', _category = '', _industry = '';
  List<String> _categories = [];
  List<Map<String, Object?>> _rows = [];
  Map<String, Object?>? _warehouse;
  bool _loading = true, _busy = false;
  int _ticket = 0;
  String? _error;
  bool get _enabled => _session.active && !_loading && !_busy && _error == null;
  static const _paths = {
    'materials': 'api/materials',
    'warehouses': 'api/inventory/warehouses',
    'locations': 'api/inventory/locations',
    'transactions': 'api/inventory/transactions',
    'suppliers': 'api/purchase/suppliers'
  };
  Map<String, String> get _tabs => {
        'materials': _industry == '考勤'
            ? '资源明细'
            : _industry == '涂料'
                ? '原材料'
                : _industry == '电商'
                    ? '商品'
                    : '库存',
        'warehouses': _industry == '考勤' ? '场所库位' : '仓库库位',
        'transactions': _industry == '考勤' ? '调拨' : '出入库',
        'suppliers': _industry == '考勤' ? '协作方' : '供应商'
      };
  String get _title =>
      _tab == 'locations' ? '${_warehouse?['name'] ?? ''} · 库位' : _tabs[_tab]!;
  @override
  void initState() {
    super.initState();
    _session = NativeWorkspaceSession(widget.repository.client,
        activeModId: widget.activeModId)
      ..addListener(_invalidate);
    unawaited(_load());
  }

  void _invalidate() {
    if (mounted) {
      setState(() {
        ++_ticket;
        _rows = [];
        _warehouse = null;
        _search.clear();
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
    final ticket = ++_ticket, tab = _tab;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final industry = await _session.request('api/system/industry');
      final result = await _session.request(_paths[tab]!, query: {
        if (tab == 'materials' && _search.text.trim().isNotEmpty)
          'search': _search.text.trim(),
        if (tab == 'materials' && _category.isNotEmpty) 'category': _category,
        if (tab == 'locations') 'warehouse_id': '${_warehouse!['id']}',
        if (tab == 'transactions') 'per_page': '100',
      });
      if (mounted && _session.active && ticket == _ticket) {
        setState(() {
          _industry = '${_map(industry['data'])['id'] ?? ''}';
          _rows = _maps(result['data']);
          if (tab == 'materials' && result['categories'] is List) {
            _categories = (result['categories'] as List)
                .map((v) => '$v')
                .toSet()
                .toList();
          }
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

  Future<void> _edit([Map<String, Object?>? row]) async {
    if (!_enabled || _tab == 'transactions') return;
    final tab = _tab, warehouse = _warehouse;
    final changed = await Navigator.push<bool>(
        context,
        MaterialPageRoute(
            builder: (_) => NativeRecordEditor(
                  session: _session,
                  title: '${row == null ? '添加' : '编辑'}$_title',
                  fields: _fields[tab]!,
                  initial: row ?? {},
                  save: (body) async {
                    await _session.request(
                        '${_paths[tab]}${row == null ? '' : '/${row['id']}'}',
                        method: row == null ? 'POST' : 'PUT',
                        body: {
                          ...body,
                          if (row != null) 'id': row['id'],
                          if (tab == 'materials')
                            'min_stock': row?['min_stock'] ?? 0,
                          if (tab == 'locations')
                            'warehouse_id': warehouse!['id'],
                        });
                  },
                )));
    if (changed == true && mounted && _session.active) await _load();
  }

  Future<void> _delete(Map<String, Object?> row) async {
    if (!_enabled) return;
    final yes = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
                title: const Text('删除这条资源？'),
                content: Text('${row['name']}\n删除后无法撤销。'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('确认删除'))
                ]));
    if (yes != true || !mounted || !_enabled) return;
    await _perform(() async {
      await _session.request('api/materials/${row['id']}', method: 'DELETE');
    });
  }

  Future<void> _perform(Future<void> Function() action) async {
    setState(() {
      _busy = true;
    });
    try {
      await action();
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

  Future<void> _move(bool incoming) async {
    if (!_enabled) return;
    setState(() {
      _busy = true;
    });
    try {
      final values = await Future.wait([
        _session.request('api/materials'),
        _session.request('api/inventory/warehouses')
      ]);
      if (!mounted || !_session.active) return;
      final products = {
            for (final r in _maps(values[0]['data']))
              if (r['id'] != null)
                '${r['id']}': '${r['name'] ?? r['code'] ?? r['id']}'
          },
          warehouses = {
            for (final r in _maps(values[1]['data']))
              if (r['id'] != null)
                '${r['id']}': '${r['name'] ?? r['code'] ?? r['id']}'
          };
      if (products.isEmpty || warehouses.isEmpty) throw StateError('请先添加资源和仓库');
      final changed = await Navigator.push<bool>(
          context,
          MaterialPageRoute(
              builder: (_) => NativeRecordEditor(
                  session: _session,
                  title: incoming ? '入库' : '出库',
                  fields: [
                    NativeFormField('product_id', '产品',
                        required: true,
                        number: true,
                        integer: true,
                        minimum: 1,
                        options: products),
                    NativeFormField('warehouse_id', '仓库',
                        required: true,
                        number: true,
                        integer: true,
                        minimum: 1,
                        options: warehouses),
                    const NativeFormField('quantity', '数量',
                        required: true,
                        number: true,
                        integer: true,
                        minimum: 1,
                        defaultValue: 1),
                    if (incoming) const NativeFormField('batch_no', '批次'),
                    const NativeFormField('remark', '备注'),
                  ],
                  save: (body) async {
                    await _session.request(
                        'api/inventory/${incoming ? 'in' : 'out'}',
                        method: 'POST',
                        body: body);
                  })));
      if (changed == true && mounted && _session.active) await _load();
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

  Future<void> _export() async {
    if (!_enabled) return;
    await _perform(() async {
      final bytes = await _session.download('api/materials/export', query: {
        if (_search.text.trim().isNotEmpty) 'search': _search.text.trim(),
        if (_category.isNotEmpty) 'category': _category
      });
      await shareWorkspaceFile('${widget.title}.xlsx', bytes,
          isCurrent: () => mounted && _session.active);
    });
  }

  @override
  Widget build(BuildContext context) => Scaffold(
      backgroundColor: AppTheme.colors(context).page,
      body: SafeArea(
          child: Column(children: [
        WeTopBar(
            title: widget.title,
            showBack: true,
            onBack: () => Navigator.maybePop(context),
            actions: [
              IconButton(
                  onPressed: _loading || _busy ? null : _load,
                  icon: const Icon(Icons.refresh),
                  tooltip: '刷新')
            ]),
        if (!_session.active)
          const Expanded(child: Center(child: Text('账号或连接已切换，请重新打开')))
        else ...[
          SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Row(children: [
                for (final tab in _tabs.entries)
                  Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: ChoiceChip(
                          label: Text(tab.value),
                          selected: _tab == tab.key ||
                              _tab == 'locations' && tab.key == 'warehouses',
                          onSelected: _busy
                              ? null
                              : (_) {
                                  setState(() {
                                    _tab = tab.key;
                                    _rows = [];
                                  });
                                  unawaited(_load());
                                }))
              ])),
          if (_loading || _busy) const LinearProgressIndicator(),
          Expanded(
              child: RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.all(16),
                      children: [
                        if (_tab == 'materials') ...[
                          TextField(
                              controller: _search,
                              decoration: const InputDecoration(
                                  hintText: '搜索资源',
                                  prefixIcon: Icon(Icons.search)),
                              textInputAction: TextInputAction.search,
                              onSubmitted: (_) => _load()),
                          const SizedBox(height: 12),
                          DropdownButtonFormField<String>(
                              key: ValueKey(_category),
                              initialValue: _category,
                              isExpanded: true,
                              decoration:
                                  const InputDecoration(labelText: '分类'),
                              items: [
                                const DropdownMenuItem(
                                    value: '', child: Text('全部分类')),
                                for (final c in {
                                  if (_category.isNotEmpty) _category,
                                  ..._categories
                                })
                                  DropdownMenuItem(value: c, child: Text(c))
                              ],
                              onChanged: _busy
                                  ? null
                                  : (v) {
                                      setState(() {
                                        _category = v ?? '';
                                      });
                                      unawaited(_load());
                                    }),
                        ],
                        if (_tab == 'locations')
                          TextButton(
                              onPressed: _busy
                                  ? null
                                  : () {
                                      setState(() {
                                        _tab = 'warehouses';
                                        _rows = [];
                                      });
                                      unawaited(_load());
                                    },
                              child: const Text('返回仓库列表')),
                        Padding(
                            padding: const EdgeInsets.symmetric(vertical: 12),
                            child: Wrap(
                                spacing: 12,
                                crossAxisAlignment: WrapCrossAlignment.center,
                                children: [
                                  Text(_title,
                                      style: Theme.of(context)
                                          .textTheme
                                          .titleMedium),
                                  if (_tab != 'transactions')
                                    FilledButton.icon(
                                        onPressed:
                                            _enabled ? () => _edit() : null,
                                        icon: const Icon(Icons.add),
                                        label: const Text('添加')),
                                  if (_tab == 'materials')
                                    TextButton(
                                        onPressed: _enabled ? _export : null,
                                        child: const Text('导出 Excel')),
                                  if (_tab == 'transactions') ...[
                                    FilledButton(
                                        onPressed:
                                            _enabled ? () => _move(true) : null,
                                        child: const Text('入库')),
                                    OutlinedButton(
                                        onPressed: _enabled
                                            ? () => _move(false)
                                            : null,
                                        child: const Text('出库'))
                                  ],
                                ])),
                        if (_error != null)
                          ListTile(
                              title: Text(_error!),
                              trailing: TextButton(
                                  onPressed: _busy ? null : _load,
                                  child: const Text('重试'))),
                        if (!_loading && _error == null && _rows.isEmpty)
                          const Padding(
                              padding: EdgeInsets.all(32),
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
                                            '${row['name'] ?? row['product_name'] ?? row['code'] ?? '记录'}',
                                            style: Theme.of(context)
                                                .textTheme
                                                .titleMedium),
                                        for (final e in _labels.entries)
                                          if (row[e.key] != null)
                                            Padding(
                                                padding: const EdgeInsets.only(
                                                    top: 6),
                                                child: Text(
                                                    '${e.value}：${_display(e.key, row[e.key])}')),
                                        if (_tab == 'materials' &&
                                            (num.tryParse(
                                                        '${row['quantity']}') ??
                                                    0) <
                                                (num.tryParse(
                                                        '${row['min_stock']}') ??
                                                    0))
                                          Text('低于库存预警值',
                                              style: TextStyle(
                                                  color: Theme.of(context)
                                                      .colorScheme
                                                      .error)),
                                        if (row['id'] != null)
                                          Wrap(spacing: 12, children: [
                                            if (_tab != 'transactions')
                                              TextButton(
                                                  onPressed: _enabled
                                                      ? () => _edit(row)
                                                      : null,
                                                  child: const Text('编辑')),
                                            if (_tab == 'materials')
                                              TextButton(
                                                  onPressed: _enabled
                                                      ? () => _delete(row)
                                                      : null,
                                                  child: const Text('删除')),
                                            if (_tab == 'warehouses')
                                              TextButton(
                                                  onPressed: _enabled
                                                      ? () {
                                                          setState(() {
                                                            _warehouse = row;
                                                            _tab = 'locations';
                                                            _rows = [];
                                                          });
                                                          unawaited(_load());
                                                        }
                                                      : null,
                                                  child: const Text('管理库位')),
                                          ]),
                                      ]))),
                      ]))),
        ],
      ])));
}

Map<String, Object?> _map(Object? value) =>
    value is Map ? Map<String, Object?>.from(value) : {};
List<Map<String, Object?>> _maps(Object? value) => value is List
    ? value.whereType<Map>().map((v) => Map<String, Object?>.from(v)).toList()
    : [];
String _display(String key, Object? value) => key == 'status'
    ? value == 'active'
        ? '正常'
        : value == 'inactive'
            ? '禁用'
            : '$value'
    : key == 'transaction_type'
        ? value == 'in'
            ? '入库'
            : value == 'out'
                ? '出库'
                : '$value'
        : '$value';
const _labels = {
  'code': '编码',
  'category': '分类',
  'spec': '规格',
  'quantity': '数量',
  'unit': '单位',
  'price': '单价',
  'supplier': '供应商',
  'type': '类型',
  'address': '地址',
  'manager': '负责人',
  'status': '状态',
  'max_capacity': '最大容量',
  'current_capacity': '当前用量',
  'transaction_date': '时间',
  'transaction_type': '操作',
  'warehouse_name': '仓库',
  'operator': '操作人',
  'remark': '备注',
  'contact_person': '联系人',
  'contact_phone': '电话',
  'rating': '评级'
};
const _fields = <String, List<NativeFormField>>{
  'materials': [
    NativeFormField('code', '编码'),
    NativeFormField('name', '名称', required: true),
    NativeFormField('category', '分类'),
    NativeFormField('spec', '规格'),
    NativeFormField('unit', '单位', defaultValue: '个'),
    NativeFormField('quantity', '库存',
        number: true, minimum: 0, defaultValue: 0),
    NativeFormField('price', '单价', number: true, minimum: 0, defaultValue: 0),
    NativeFormField('supplier', '供应商')
  ],
  'warehouses': [
    NativeFormField('code', '编码', required: true),
    NativeFormField('name', '名称', required: true),
    NativeFormField('type', '类型', options: {
      '': '请选择',
      '原材料': '原材料仓',
      '成品': '成品仓',
      '半成品': '半成品仓',
      '其他': '其他'
    }),
    NativeFormField('address', '地址'),
    NativeFormField('manager', '负责人')
  ],
  'locations': [
    NativeFormField('code', '编码', required: true),
    NativeFormField('name', '名称'),
    NativeFormField('max_capacity', '最大容量',
        number: true, minimum: 0, nullable: true)
  ],
  'suppliers': [
    NativeFormField('code', '编码', required: true),
    NativeFormField('name', '名称', required: true),
    NativeFormField('contact_person', '联系人'),
    NativeFormField('contact_phone', '电话'),
    NativeFormField('rating', '评级',
        number: true,
        integer: true,
        defaultValue: 3,
        options: {'1': '★', '2': '★★', '3': '★★★', '4': '★★★★', '5': '★★★★★'})
  ],
};

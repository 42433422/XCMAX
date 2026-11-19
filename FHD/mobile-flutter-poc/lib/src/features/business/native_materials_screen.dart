import 'dart:async';
import 'package:flutter/material.dart';
import '../../data/mobile_repository.dart';
import '../../platform/workspace_file_export.dart';
import '../../policy/mobile_error_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../workspace/native_record_editor.dart';
import '../workspace/native_workspace_session.dart';
import '../workspace/workspace_ui.dart';

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
  bool _loading = true, _busy = false, _movementOutcomeUnknown = false;
  bool _loadedIndustry = false;
  int _ticket = 0, _page = 1;
  bool _hasNextPage = false;
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
                    ? '商品档案'
                    : '物料档案',
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

  Future<void> _load({int page = 1}) async {
    if (!_session.active) return;
    final ticket = ++_ticket, tab = _tab;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final industry = _loadedIndustry
          ? null
          : await _session.request('api/system/industry');
      final result = await _session.request(_paths[tab]!, query: {
        if (tab == 'materials' && _search.text.trim().isNotEmpty)
          'search': _search.text.trim(),
        if (tab == 'materials' && _category.isNotEmpty) 'category': _category,
        if (tab == 'locations') 'warehouse_id': '${_warehouse!['id']}',
        if (tab == 'materials' || tab == 'transactions') ...{
          'page': '$page',
          'per_page': '20',
        },
      });
      if (mounted && _session.active && ticket == _ticket) {
        setState(() {
          if (industry != null) {
            _industry = '${_map(industry['data'])['id'] ?? ''}';
            _loadedIndustry = true;
          }
          _rows = _maps(result['data']);
          _page = page;
          final total = int.tryParse('${result['total']}');
          _hasNextPage = total != null ? page * 20 < total : _rows.length == 20;
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

  Future<Map<String, Object?>> _inventoryProducts() async {
    final rows = <Map<String, Object?>>[];
    final seen = <String>{};
    // Inventory ledger IDs refer to Product, never Material. Read every page
    // before offering a selection; fail closed if the catalog cannot be loaded.
    for (var page = 1; page <= 100; page++) {
      final result = await _session.request('api/products/list', query: {
        'page': '$page',
        'per_page': '100',
      });
      final batch = _maps(result['data']);
      if (batch.length > 100 ||
          batch.any((row) => row['id'] == null || !seen.add('${row['id']}'))) {
        throw StateError('产品目录分页异常，请稍后重试');
      }
      rows.addAll(batch);
      final total = int.tryParse('${result['total']}');
      if (total != null ? rows.length >= total : batch.length < 100) {
        return {'data': rows};
      }
      if (batch.isEmpty) break;
    }
    throw StateError('产品目录未完整读取，请稍后重试');
  }

  Future<void> _move(bool incoming) async {
    if (!_enabled || _movementOutcomeUnknown) return;
    setState(() {
      _busy = true;
    });
    try {
      final values = await Future.wait(
          [_inventoryProducts(), _session.request('api/inventory/warehouses')]);
      if (!mounted || !_session.active) return;
      final products = {
            for (final r in _maps(values[0]['data']))
              if (r['id'] != null) '${r['id']}': _productChoiceLabel(r)
          },
          warehouses = {
            for (final r in _maps(values[1]['data']))
              if (r['id'] != null)
                '${r['id']}': '${r['name'] ?? r['code'] ?? r['id']}'
          };
      if (products.isEmpty || warehouses.isEmpty) throw StateError('请先添加产品和仓库');
      final changed = await Navigator.push<bool>(
          context,
          MaterialPageRoute(
              builder: (_) => NativeRecordEditor(
                  session: _session,
                  title: incoming ? '入库' : '出库',
                  onUncertainSave: () {
                    if (mounted) setState(() => _movementOutcomeUnknown = true);
                  },
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
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Wrap(
                spacing: 8,
                runSpacing: 4,
                children: [
                  for (final tab in _tabs.entries)
                    ChoiceChip(
                      label: Text(tab.value),
                      selected: _tab == tab.key ||
                          _tab == 'locations' && tab.key == 'warehouses',
                      materialTapTargetSize: MaterialTapTargetSize.padded,
                      onSelected: _busy
                          ? null
                          : (_) {
                              setState(() {
                                _tab = tab.key;
                                _rows = [];
                              });
                              unawaited(_load());
                            },
                    ),
                ],
              ),
            ),
          ),
          if (_loading || _busy) const LinearProgressIndicator(),
          Expanded(
              child: RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.all(16),
                      children: [
                        WorkspaceTransition(
                          child: KeyedSubtree(
                              key: ValueKey(_tab), child: _tools()),
                        ),
                        if (_movementOutcomeUnknown)
                          const ListTile(
                              title: Text(
                                  '上次库存操作结果未知。请先核对出入库流水，确认未入账后再重新打开页面操作；刷新不会重新提交。')),
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
                        for (final row in _rows) _resourceCard(row),
                        if (_tab == 'materials' || _tab == 'transactions')
                          Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                TextButton(
                                    onPressed: _enabled && _page > 1
                                        ? () => _load(page: _page - 1)
                                        : null,
                                    child: const Text('上一页')),
                                Text('第 $_page 页'),
                                TextButton(
                                    onPressed: _enabled && _hasNextPage
                                        ? () => _load(page: _page + 1)
                                        : null,
                                    child: const Text('下一页')),
                              ]),
                      ]))),
        ],
      ])));

  Widget _tools() => WorkspacePanel(
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (_tab == 'materials') ...[
          TextField(
              controller: _search,
              enabled: !_busy,
              decoration: InputDecoration(
                  hintText: '搜索资源',
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: IconButton(
                    tooltip: '搜索',
                    onPressed: _busy
                        ? null
                        : () {
                            FocusScope.of(context).unfocus();
                            _load();
                          },
                    icon: const Icon(Icons.arrow_forward),
                  )),
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => _load()),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
              key: ValueKey(_category),
              initialValue: _category,
              isExpanded: true,
              decoration: const InputDecoration(
                  border: OutlineInputBorder(), labelText: '分类'),
              items: [
                const DropdownMenuItem(value: '', child: Text('全部分类')),
                for (final c in {
                  if (_category.isNotEmpty) _category,
                  ..._categories,
                })
                  DropdownMenuItem(
                      value: c,
                      child: Text(c, overflow: TextOverflow.ellipsis)),
              ],
              onChanged: _busy
                  ? null
                  : (value) {
                      setState(() => _category = value ?? '');
                      unawaited(_load());
                    }),
          const SizedBox(height: 12),
        ],
        if (_tab == 'locations')
          TextButton.icon(
              onPressed: _busy
                  ? null
                  : () {
                      setState(() {
                        _tab = 'warehouses';
                        _rows = [];
                      });
                      unawaited(_load());
                    },
              icon: const Icon(Icons.arrow_back),
              label: const Text('返回仓库列表')),
        if (_tab == 'locations')
          Text(_title, style: Theme.of(context).textTheme.titleMedium),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            if (_tab != 'transactions')
              FilledButton.icon(
                  onPressed: _enabled ? () => _edit() : null,
                  icon: const Icon(Icons.add),
                  label: const Text('添加')),
            if (_tab == 'materials')
              TextButton.icon(
                  onPressed: _enabled ? _export : null,
                  icon: const Icon(Icons.file_download_outlined),
                  label: const Text('导出 Excel')),
            if (_tab == 'transactions') ...[
              FilledButton(
                  onPressed: _enabled && !_movementOutcomeUnknown
                      ? () => _move(true)
                      : null,
                  child: const Text('入库')),
              OutlinedButton(
                  onPressed: _enabled && !_movementOutcomeUnknown
                      ? () => _move(false)
                      : null,
                  child: const Text('出库')),
            ],
          ],
        ),
      ]));

  Widget _resourceCard(Map<String, Object?> row) {
    final colors = AppTheme.colors(context);
    final code = row['material_code'] ?? row['code'];
    final title = row['name'] ?? row['product_name'] ?? code ?? '记录';
    final quantity = num.tryParse('${row['quantity']}');
    final lowStock = _tab == 'materials' &&
        quantity != null &&
        quantity < (num.tryParse('${row['min_stock']}') ?? 0);
    final entries = _labels[_tab]!;
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: WorkspacePanel(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('$title', style: Theme.of(context).textTheme.titleMedium),
            if (code != null && code != title)
              Text('$code', style: TextStyle(color: colors.textSecondary)),
            const SizedBox(height: 8),
            if (_tab == 'materials' || _tab == 'transactions')
              Wrap(
                crossAxisAlignment: WrapCrossAlignment.center,
                spacing: 8,
                runSpacing: 4,
                children: [
                  if (quantity != null)
                    Text(
                      '${_tab == 'materials' ? '档案数量' : '数量'} $quantity ${row['unit'] ?? ''}'
                          .trimRight(),
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                  if (lowStock)
                    WorkspaceBadge(label: '低于库存预警值', color: colors.danger),
                  if (row['category'] != null && row['category'] != '')
                    WorkspaceBadge(
                        label: '${row['category']}', color: colors.brand),
                  if (row['transaction_type'] != null)
                    WorkspaceBadge(
                      label:
                          _display('transaction_type', row['transaction_type']),
                      color: row['transaction_type'] == 'out'
                          ? colors.warning
                          : colors.success,
                    ),
                ],
              ),
            for (final entry in entries.entries)
              if (row[entry.key] != null && row[entry.key] != '')
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                      '${entry.value}：${_display(entry.key, row[entry.key])}'),
                ),
            if (row['id'] != null && _tab != 'transactions')
              Wrap(
                spacing: 8,
                children: [
                  TextButton(
                      onPressed: _enabled ? () => _edit(row) : null,
                      child: const Text('编辑')),
                  if (_tab == 'materials')
                    TextButton(
                        onPressed: _enabled ? () => _delete(row) : null,
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
                      child: const Text('管理库位'),
                    ),
                ],
              ),
          ],
        ),
      ),
    );
  }
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
String _productChoiceLabel(Map<String, Object?> row) {
  final name = '${row['name'] ?? row['code'] ?? row['id']}';
  final model = '${row['model_number'] ?? ''}'.trim();
  return model.isEmpty || model == name ? name : '$name · $model';
}

const _labels = {
  'materials': {'specification': '规格', 'unit_price': '单价', 'supplier': '供应商'},
  'warehouses': {
    'type': '类型',
    'address': '地址',
    'manager': '负责人',
    'status': '状态'
  },
  'locations': {
    'max_capacity': '最大容量',
    'current_capacity': '当前用量',
    'status': '状态'
  },
  'transactions': {
    'warehouse_name': '仓库',
    'transaction_date': '时间',
    'operator': '操作人',
    'remark': '备注'
  },
  'suppliers': {'contact_person': '联系人', 'contact_phone': '电话', 'rating': '评级'},
};
const _fields = <String, List<NativeFormField>>{
  'materials': [
    NativeFormField('material_code', '编码'),
    NativeFormField('name', '名称', required: true),
    NativeFormField('category', '分类'),
    NativeFormField('specification', '规格'),
    NativeFormField('unit', '单位', defaultValue: '个'),
    NativeFormField('quantity', '档案数量',
        number: true, minimum: 0, defaultValue: 0),
    NativeFormField('unit_price', '单价',
        number: true, minimum: 0, defaultValue: 0),
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

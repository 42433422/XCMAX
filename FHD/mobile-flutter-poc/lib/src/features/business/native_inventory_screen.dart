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

enum _InventoryTab { balances, alerts, movements }

class NativeInventoryScreen extends StatefulWidget {
  const NativeInventoryScreen({
    super.key,
    required this.repository,
    required this.title,
    this.activeModId = '',
  });

  final MobileRepository repository;
  final String title, activeModId;

  @override
  State<NativeInventoryScreen> createState() => _NativeInventoryScreenState();
}

class _NativeInventoryScreenState extends State<NativeInventoryScreen> {
  static const _pageSize = 20;
  static const _tabLabels = {
    _InventoryTab.balances: '库存台账',
    _InventoryTab.alerts: '库存预警',
    _InventoryTab.movements: '出入库流水',
  };

  late final NativeWorkspaceSession _session;
  final _search = TextEditingController();
  _InventoryTab _tab = _InventoryTab.balances;
  String _keyword = '', _warehouse = '', _batch = '';
  bool _loadedWarehouses = false, _loading = true, _busy = false;
  int _ticket = 0, _page = 1, _total = 0;
  List<Map<String, Object?>> _warehouses = [], _rows = [];
  String? _error;
  Map<String, String>? _movementToCheck;
  bool _checkingMovement = false;

  bool get _canWrite =>
      _session.active &&
      !_loading &&
      !_busy &&
      _error == null &&
      _movementToCheck == null &&
      _activeWarehouses.isNotEmpty;

  List<Map<String, Object?>> get _activeWarehouses => _warehouses
      .where((row) => row['status'] == null || row['status'] == 'active')
      .toList(growable: false);

  @override
  void initState() {
    super.initState();
    _session = NativeWorkspaceSession(widget.repository.client,
        activeModId: widget.activeModId)
      ..addListener(_invalidate);
    unawaited(_load());
  }

  void _invalidate() {
    if (!mounted) return;
    ++_ticket;
    _search.clear();
    setState(() {
      _warehouses = [];
      _rows = [];
      _movementToCheck = null;
    });
  }

  @override
  void dispose() {
    _session.dispose();
    _search.dispose();
    super.dispose();
  }

  Map<String, String> _filters(_InventoryTab tab) {
    if (tab == _InventoryTab.movements && _checkingMovement) {
      return _movementToCheck ?? {};
    }
    return {
      if (_warehouse.isNotEmpty) 'warehouse_id': _warehouse,
      if (tab == _InventoryTab.balances && _keyword.isNotEmpty)
        'keyword': _keyword,
      if (tab == _InventoryTab.balances && _batch.isNotEmpty)
        'batch_no': _batch,
    };
  }

  Future<void> _load({int page = 1, bool reloadWarehouses = false}) async {
    if (!_session.active) return;
    final ticket = ++_ticket;
    final tab = _tab;
    final filters = _filters(tab);
    final fetchWarehouses = !_loadedWarehouses || reloadWarehouses;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final results = await Future.wait([
        _session.request(
          switch (tab) {
            _InventoryTab.balances => 'api/inventory',
            _InventoryTab.alerts => 'api/inventory/alert',
            _InventoryTab.movements => 'api/inventory/transactions',
          },
          query: {
            if (tab != _InventoryTab.alerts) ...filters,
            if (tab != _InventoryTab.alerts) ...{
              'page': '$page',
              'per_page': '$_pageSize',
            },
          },
        ),
        if (fetchWarehouses) _session.request('api/inventory/warehouses'),
      ]);
      if (!mounted || !_session.active || ticket != _ticket) return;
      final data = _inventoryRows(results.first['data']);
      final alerts = tab == _InventoryTab.alerts
          ? data.where((row) =>
              _warehouse.isEmpty ||
              row['warehouse_id'].toString() == _warehouse)
          : null;
      setState(() {
        if (fetchWarehouses) {
          _warehouses = _inventoryRows(results[1]['data']);
          _loadedWarehouses = true;
        }
        _total = alerts?.length ??
            int.tryParse('${results.first['total']}') ??
            data.length;
        _rows = alerts?.skip((page - 1) * _pageSize).take(_pageSize).toList() ??
            data;
        _page = page;
      });
    } catch (error) {
      if (mounted && _session.active && ticket == _ticket) {
        setState(() => _error = mobileErrorText(error));
      }
    } finally {
      if (mounted && ticket == _ticket) setState(() => _loading = false);
    }
  }

  void _selectTab(_InventoryTab tab, {bool checkMovement = false}) {
    if (_busy) return;
    setState(() {
      _tab = tab;
      _checkingMovement = checkMovement;
      _rows = [];
      _total = 0;
    });
    unawaited(_load());
  }

  void _submitSearch(String value) {
    setState(() {
      _keyword = value.trim();
      _rows = [];
      _total = 0;
    });
    unawaited(_load());
  }

  Future<void> _filterBatch() async {
    var batch = _batch;
    final selection = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('按批次筛选'),
        content: TextFormField(
          initialValue: _batch,
          maxLength: 50,
          autofocus: true,
          textInputAction: TextInputAction.search,
          decoration: const InputDecoration(
              border: OutlineInputBorder(), labelText: '批次号', counterText: ''),
          onChanged: (value) => batch = value,
          onFieldSubmitted: (value) => Navigator.pop(context, value.trim()),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, ''),
            child: const Text('清除'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, batch.trim()),
            child: const Text('应用'),
          ),
        ],
      ),
    );
    if (!mounted ||
        !_session.active ||
        selection == null ||
        selection == _batch) {
      return;
    }
    setState(() {
      _batch = selection;
      _rows = [];
      _total = 0;
    });
    await _load();
  }

  String _warehouseName(Map<String, Object?> row) {
    final name = _value(row, 'warehouse_name');
    if (name.isNotEmpty) return name;
    final id = _value(row, 'warehouse_id');
    for (final warehouse in _warehouses) {
      if (_value(warehouse, 'id') == id) return _value(warehouse, 'name');
    }
    return id.isEmpty ? '仓库未知' : '仓库 $id';
  }

  Future<void> _export(String format) async {
    if (_busy || _loading || _error != null || _total == 0) return;
    setState(() => _busy = true);
    try {
      final bytes = await _session.download('api/inventory/export.$format',
          query: _filters(_InventoryTab.balances));
      await shareWorkspaceFile('库存明细.$format', bytes,
          isCurrent: () => mounted && _session.active);
    } catch (error) {
      if (mounted && _session.active) _message(mobileErrorText(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _message(String message) => ScaffoldMessenger.of(context)
      .showSnackBar(SnackBar(content: Text(message)));

  Future<void> _setupWarehouse() async {
    if (_busy || !_session.active) return;
    setState(() => _busy = true);
    try {
      final result = await _session.request('api/inventory/setup/warehouse',
          method: 'POST');
      if (!mounted || !_session.active) return;
      _message(result['message']?.toString() ?? '仓库已就绪');
      await _load(reloadWarehouses: true);
    } catch (error) {
      if (mounted && _session.active) _message(mobileErrorText(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _move(bool incoming, {Map<String, Object?>? stock}) async {
    if (!_canWrite) return;
    setState(() => _busy = true);
    try {
      final product = stock ??
          await Navigator.of(context).push<Map<String, Object?>>(
            MaterialPageRoute(
                builder: (_) => _InventoryProductPicker(session: _session)),
          );
      if (!mounted || !_session.active || product == null) return;
      final productId =
          int.tryParse(_value(product, stock == null ? 'id' : 'product_id'));
      final warehouseId =
          stock == null ? _warehouse : _value(stock, 'warehouse_id');
      final warehouses = {
        for (final row in _activeWarehouses)
          if (_value(row, 'id').isNotEmpty)
            _value(row, 'id'): _value(row, 'name', fallback: _value(row, 'id')),
      };
      if (productId == null ||
          productId <= 0 ||
          stock != null && !warehouses.containsKey(warehouseId)) {
        _message('该产品或仓库当前不可用');
        return;
      }
      final action = incoming ? '入库' : '出库';
      final batch = stock == null ? '' : _value(stock, 'batch_no');
      final location =
          stock == null ? null : int.tryParse(_value(stock, 'location_id'));
      final targetWarehouses =
          stock == null ? warehouses : {warehouseId: warehouses[warehouseId]!};
      Map<String, String>? submittedMovement;
      final saved = await Navigator.of(context).push<bool>(
        MaterialPageRoute(
          builder: (_) => NativeRecordEditor(
            session: _session,
            title: '$action · ${_productLabel(product)}',
            initial: {
              'warehouse_id':
                  warehouses.containsKey(warehouseId) ? warehouseId : '',
              'batch_no': batch,
            },
            fields: [
              NativeFormField('warehouse_id', '仓库',
                  required: true,
                  number: true,
                  integer: true,
                  options: targetWarehouses),
              const NativeFormField('quantity', '数量',
                  required: true,
                  number: true,
                  exclusiveMinimum: 0,
                  defaultValue: 1),
              if (incoming) ...[
                const NativeFormField('batch_no', '批次'),
                const NativeFormField('unit_price', '单价',
                    number: true, minimum: 0, nullable: true),
              ],
              if (!incoming && batch.isNotEmpty)
                NativeFormField('batch_no', '批次', options: {batch: batch}),
              const NativeFormField('remark', '备注'),
            ],
            save: (body) async {
              final selectedWarehouse = body['warehouse_id'].toString();
              submittedMovement = {
                'product_id': '$productId',
                'warehouse_id': selectedWarehouse,
                'transaction_type': incoming ? 'in' : 'out',
              };
              await _session.request('api/inventory/${incoming ? 'in' : 'out'}',
                  method: 'POST',
                  body: {
                    ...body,
                    'product_id': productId,
                    if (!incoming && batch.isNotEmpty) 'batch_no': batch,
                    if (location != null && location > 0)
                      'location_id': location,
                  });
            },
            onUncertainSave: () {
              if (mounted && _session.active) {
                setState(() => _movementToCheck = submittedMovement);
              }
            },
          ),
        ),
      );
      if (saved == true && mounted && _session.active) {
        _message('已$action');
        await _load(page: _page);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
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
              title: widget.title,
              showBack: true,
              actions: [
                IconButton(
                  tooltip: '刷新',
                  onPressed: _loading || _busy || !_session.active
                      ? null
                      : () => _load(page: _page, reloadWarehouses: true),
                  icon: const Icon(Icons.refresh),
                ),
              ],
            ),
            if (!_session.active)
              const Expanded(
                child: Center(child: Text('账号或连接已切换，请重新打开')),
              )
            else
              Expanded(
                child: RefreshIndicator(
                  onRefresh: _busy
                      ? () async {}
                      : () => _load(page: _page, reloadWarehouses: true),
                  child: ListView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    padding: const EdgeInsets.all(16),
                    children: [
                      WorkspaceTransition(
                        child: KeyedSubtree(
                            key: ValueKey(_tab), child: _controls()),
                      ),
                      if (_loading) const LinearProgressIndicator(),
                      if (_movementToCheck != null) _movementNotice(),
                      if (_error != null)
                        _notice(_error!,
                            action: TextButton(
                                onPressed: () => _load(page: _page),
                                child: const Text('重试'))),
                      if (!_loading &&
                          _error == null &&
                          _loadedWarehouses &&
                          _activeWarehouses.isEmpty)
                        _notice('暂无可用仓库',
                            action: TextButton(
                                onPressed: _busy ? null : _setupWarehouse,
                                child: const Text('初始化默认仓库'))),
                      if (!_loading && _error == null && _rows.isEmpty)
                        _notice(switch (_tab) {
                          _InventoryTab.balances => _keyword.isEmpty &&
                                  _warehouse.isEmpty &&
                                  _batch.isEmpty
                              ? '暂无库存明细'
                              : '没有符合条件的库存',
                          _InventoryTab.alerts => '暂无库存预警',
                          _InventoryTab.movements => '暂无匹配的出入库流水',
                        }),
                      for (final row in _rows)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: _tab == _InventoryTab.movements
                              ? _movementCard(row)
                              : _balanceCard(row),
                        ),
                      if (_total > _pageSize)
                        _InventoryPagination(
                          page: _page,
                          total: _total,
                          pageSize: _pageSize,
                          enabled: !_busy && !_loading && _error == null,
                          onPage: (page) => _load(page: page),
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

  Widget _controls() => WorkspacePanel(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 4,
              children: [
                for (final tab in _tabLabels.entries)
                  ChoiceChip(
                    label: Text(tab.value),
                    selected: _tab == tab.key,
                    onSelected: _busy ? null : (_) => _selectTab(tab.key),
                    materialTapTargetSize: MaterialTapTargetSize.padded,
                  ),
              ],
            ),
            const SizedBox(height: 12),
            if (!_checkingMovement)
              DropdownButtonFormField<String>(
                key: ValueKey(_warehouse),
                isExpanded: true,
                initialValue: _warehouse,
                decoration: const InputDecoration(
                    border: OutlineInputBorder(), labelText: '仓库'),
                items: [
                  const DropdownMenuItem(value: '', child: Text('全部仓库')),
                  if (_warehouse.isNotEmpty &&
                      !_warehouses
                          .any((row) => _value(row, 'id') == _warehouse))
                    DropdownMenuItem(
                        value: _warehouse, child: Text('仓库 $_warehouse')),
                  for (final row in _warehouses)
                    if (_value(row, 'id').isNotEmpty)
                      DropdownMenuItem(
                        value: _value(row, 'id'),
                        child: Text(_value(row, 'name'),
                            overflow: TextOverflow.ellipsis),
                      ),
                ],
                onChanged: _busy
                    ? null
                    : (value) {
                        setState(() {
                          _warehouse = value ?? '';
                          _rows = [];
                          _total = 0;
                        });
                        unawaited(_load());
                      },
              ),
            if (_tab == _InventoryTab.balances) ...[
              const SizedBox(height: 12),
              TextField(
                controller: _search,
                enabled: !_busy,
                maxLength: 200,
                textInputAction: TextInputAction.search,
                onSubmitted: _submitSearch,
                decoration: InputDecoration(
                  hintText: '搜索产品名称或型号',
                  counterText: '',
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: IconButton(
                    tooltip: '搜索',
                    onPressed: _busy
                        ? null
                        : () {
                            FocusScope.of(context).unfocus();
                            _submitSearch(_search.text);
                          },
                    icon: const Icon(Icons.arrow_forward),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  FilledButton.icon(
                    onPressed: _canWrite ? () => _move(true) : null,
                    icon: const Icon(Icons.add),
                    label: const Text('入库'),
                  ),
                  OutlinedButton(
                    onPressed: _canWrite ? () => _move(false) : null,
                    child: const Text('出库'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _busy ? null : _filterBatch,
                    icon: const Icon(Icons.filter_list),
                    label: Text(_batch.isEmpty ? '批次' : '批次 $_batch',
                        maxLines: 1, overflow: TextOverflow.ellipsis),
                  ),
                  PopupMenuButton<String>(
                    tooltip: '导出库存',
                    enabled:
                        !_busy && !_loading && _total > 0 && _error == null,
                    onSelected: _export,
                    itemBuilder: (_) => const [
                      PopupMenuItem(value: 'xlsx', child: Text('导出 Excel')),
                      PopupMenuItem(value: 'csv', child: Text('导出 CSV')),
                    ],
                    icon: const Icon(Icons.file_download_outlined),
                  ),
                ],
              ),
            ],
          ],
        ),
      );

  Widget _notice(String label, {Widget? action}) => Padding(
        padding: const EdgeInsets.only(top: 12),
        child: WorkspacePanel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [Text(label), if (action != null) action],
          ),
        ),
      );

  Widget _movementNotice() => _notice(
        _checkingMovement
            ? '正在核对该产品、仓库和操作类型的近期流水。确认结果前请勿重试。'
            : '上次库存操作结果未知，请先核对流水。',
        action: TextButton(
          onPressed: _busy
              ? null
              : () => _selectTab(_InventoryTab.movements,
                  checkMovement: !_checkingMovement),
          child: Text(_checkingMovement ? '查看全部流水' : '核对该笔流水'),
        ),
      );

  Widget _balanceCard(Map<String, Object?> row) {
    final colors = AppTheme.colors(context);
    final available = num.tryParse(_value(row, 'available_quantity'));
    final product = _value(row, 'product_name', fallback: '产品');
    final code = _value(row, 'product_code');
    final unit = _value(row, 'unit');
    final batch = _value(row, 'batch_no');
    final canTargetOut =
        batch.isNotEmpty || (int.tryParse(_value(row, 'location_id')) ?? 0) > 0;
    return WorkspacePanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(product, style: Theme.of(context).textTheme.titleMedium),
          if (code.isNotEmpty)
            Text(code, style: TextStyle(color: colors.textSecondary)),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 4,
            children: [
              WorkspaceBadge(label: _warehouseName(row), color: colors.brand),
              if (batch.isNotEmpty)
                WorkspaceBadge(label: '批次 $batch', color: colors.textSecondary),
              if (available != null && available <= 0)
                WorkspaceBadge(label: '无可用库存', color: colors.danger),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 20,
            runSpacing: 8,
            children: [
              _metric(
                  '可用', _value(row, 'available_quantity', fallback: '—'), unit),
              _metric('库存', _value(row, 'quantity', fallback: '—'), unit),
            ],
          ),
          if (_value(row, 'location_name').isNotEmpty)
            Text('库位 ${_value(row, 'location_name')}'),
          if (_value(row, 'in_date').isNotEmpty)
            Text('入库日期 ${_value(row, 'in_date')}'),
          if (_tab == _InventoryTab.balances)
            Wrap(
              spacing: 8,
              children: [
                TextButton(
                  onPressed: _canWrite ? () => _move(true, stock: row) : null,
                  child: const Text('入库'),
                ),
                TextButton(
                  onPressed: _canWrite &&
                          available != null &&
                          available > 0 &&
                          canTargetOut
                      ? () => _move(false, stock: row)
                      : null,
                  child: const Text('出库'),
                ),
              ],
            ),
        ],
      ),
    );
  }

  Widget _metric(String label, String value, String unit) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: Theme.of(context).textTheme.bodySmall),
          Text(unit.isEmpty ? value : '$value $unit',
              style: Theme.of(context).textTheme.titleLarge),
        ],
      );

  Widget _movementCard(Map<String, Object?> row) {
    final type = _value(row, 'transaction_type');
    final colors = AppTheme.colors(context);
    return WorkspacePanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 4,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(_value(row, 'product_name', fallback: '库存记录'),
                  style: Theme.of(context).textTheme.titleMedium),
              WorkspaceBadge(
                label: switch (type) { 'in' => '入库', 'out' => '出库', _ => '变动' },
                color: type == 'out' ? colors.warning : colors.success,
              ),
            ],
          ),
          Text(
              '${_warehouseName(row)} · 数量 ${_value(row, 'quantity', fallback: '—')}'),
          for (final detail in [
            'transaction_date',
            'batch_no',
            'operator',
            'remark'
          ])
            if (_value(row, detail).isNotEmpty) Text(_value(row, detail)),
        ],
      ),
    );
  }
}

class _InventoryProductPicker extends StatefulWidget {
  const _InventoryProductPicker({required this.session});

  final NativeWorkspaceSession session;

  @override
  State<_InventoryProductPicker> createState() =>
      _InventoryProductPickerState();
}

class _InventoryProductPickerState extends State<_InventoryProductPicker> {
  static const _pageSize = 20;
  final _search = TextEditingController();
  String _keyword = '';
  int _page = 1, _total = 0, _requestId = 0;
  bool _loading = true;
  String? _error;
  List<Map<String, Object?>> _rows = [];

  @override
  void initState() {
    super.initState();
    widget.session.addListener(_invalidate);
    unawaited(_load(1));
  }

  void _invalidate() {
    if (!mounted) return;
    _search.clear();
    setState(() => _rows = []);
  }

  @override
  void dispose() {
    widget.session.removeListener(_invalidate);
    _search.dispose();
    super.dispose();
  }

  Future<void> _load(int page) async {
    if (!widget.session.active) return;
    final requestId = ++_requestId;
    setState(() {
      _loading = true;
      _error = null;
      _rows = [];
    });
    try {
      final result = await widget.session.request('api/products/list', query: {
        'page': '$page',
        'per_page': '$_pageSize',
        if (_keyword.isNotEmpty) 'keyword': _keyword,
      });
      if (!mounted || requestId != _requestId || !widget.session.active) return;
      setState(() {
        _rows = _inventoryRows(result['data'])
            .where((row) => int.tryParse(_value(row, 'id')) != null)
            .toList(growable: false);
        _total = int.tryParse('${result['total']}') ?? _rows.length;
        _page = page;
      });
    } catch (error) {
      if (mounted && requestId == _requestId && widget.session.active) {
        setState(() => _error = mobileErrorText(error));
      }
    } finally {
      if (mounted && requestId == _requestId) setState(() => _loading = false);
    }
  }

  void _submit(String value) {
    _keyword = value.trim();
    unawaited(_load(1));
  }

  @override
  Widget build(BuildContext context) => WorkspaceScaffold(
        backgroundColor: AppTheme.colors(context).page,
        body: SafeArea(
          child: Column(
            children: [
              const WeTopBar(title: '选择产品', showBack: true),
              if (!widget.session.active)
                const Expanded(child: Center(child: Text('账号或连接已切换，请重新打开')))
              else
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      TextField(
                        controller: _search,
                        textInputAction: TextInputAction.search,
                        onSubmitted: _submit,
                        decoration: InputDecoration(
                          hintText: '搜索产品名称或型号',
                          prefixIcon: const Icon(Icons.search),
                          suffixIcon: IconButton(
                            tooltip: '搜索',
                            onPressed: () {
                              FocusScope.of(context).unfocus();
                              _submit(_search.text);
                            },
                            icon: const Icon(Icons.arrow_forward),
                          ),
                        ),
                      ),
                      if (_loading) const LinearProgressIndicator(),
                      if (_error != null)
                        ListTile(
                          title: Text(_error!),
                          trailing: TextButton(
                            onPressed: () => _load(_page),
                            child: const Text('重试'),
                          ),
                        ),
                      if (!_loading && _error == null && _rows.isEmpty)
                        const ListTile(title: Text('没有找到产品')),
                      for (final product in _rows)
                        ListTile(
                          title: Text(_productLabel(product)),
                          trailing: const Icon(Icons.chevron_right),
                          onTap: () {
                            if (widget.session.active) {
                              Navigator.of(context).pop(product);
                            }
                          },
                        ),
                      if (_total > _pageSize)
                        _InventoryPagination(
                          page: _page,
                          total: _total,
                          pageSize: _pageSize,
                          enabled: !_loading && _error == null,
                          onPage: _load,
                        ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      );
}

class _InventoryPagination extends StatelessWidget {
  const _InventoryPagination({
    required this.page,
    required this.total,
    required this.pageSize,
    required this.enabled,
    required this.onPage,
  });

  final int page, total, pageSize;
  final bool enabled;
  final ValueChanged<int> onPage;

  @override
  Widget build(BuildContext context) => Wrap(
        alignment: WrapAlignment.center,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          TextButton(
              onPressed: enabled && page > 1 ? () => onPage(page - 1) : null,
              child: const Text('上一页')),
          Text('$page / ${(total / pageSize).ceil()}'),
          TextButton(
              onPressed: enabled && page * pageSize < total
                  ? () => onPage(page + 1)
                  : null,
              child: const Text('下一页')),
        ],
      );
}

List<Map<String, Object?>> _inventoryRows(Object? data) => data is List
    ? data
        .whereType<Map>()
        .map((row) => Map<String, Object?>.from(row))
        .toList()
    : [];

String _value(Map<String, Object?> row, String key, {String fallback = ''}) {
  final value = row[key]?.toString().trim() ?? '';
  return value.isEmpty ? fallback : value;
}

String _productLabel(Map<String, Object?> row) {
  final name = _value(row, 'name',
      fallback: _value(row, 'product_name', fallback: '产品'));
  final code =
      _value(row, 'model_number', fallback: _value(row, 'product_code'));
  return code.isEmpty || code == name ? name : '$name · $code';
}

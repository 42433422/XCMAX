import 'dart:async';

import 'package:flutter/material.dart';
import 'package:file_selector/file_selector.dart';

import '../../platform/workspace_file_export.dart';

import '../../data/mobile_repository.dart';
import '../../policy/mobile_error_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../workspace/native_workspace_session.dart';
import '../workspace/workspace_ui.dart';

part 'native_catalog_transfer.part.dart';
part 'native_catalog_editor.part.dart';

/// Only known desktop resource routes opt in; arbitrary Mod pages are not
/// interpreted as an ERP resource or silently redirected to host data.
({String resource, String base})? nativeCatalogRoute(String path) {
  if (path.split('/').any((part) => part == '..' || part == '.')) return null;
  final uri = Uri.tryParse(path);
  if (uri == null || uri.hasScheme || uri.hasAuthority) return null;
  final match = RegExp(
          r'^/(?:mod/([a-zA-Z0-9_-]+)/)?(products|customers|shipment-records)/?$')
      .firstMatch(uri.path);
  if (match == null) return null;
  return (
    resource: match[2]!,
    base: match[1] == null ? 'api' : 'api/mod/${match[1]}'
  );
}

class NativeCatalogScreen extends StatefulWidget {
  const NativeCatalogScreen(
      {super.key,
      required this.repository,
      required this.resource,
      required this.apiBase,
      required this.title});
  final MobileRepository repository;
  final String resource, apiBase, title;
  @override
  State<NativeCatalogScreen> createState() => _NativeCatalogScreenState();
}

class _NativeCatalogScreenState extends State<NativeCatalogScreen> {
  late final NativeWorkspaceSession _session;
  final _search = TextEditingController();
  List<Map<String, Object?>> _rows = [];
  final Set<Object> _selected = {};
  List<_Field> _fields = [];
  List<String> _units = [];
  String _unit = '', _keyword = '', _status = 'all';
  String? _error, _schemaError, _unitsError;
  int _page = 1, _ticket = 0;
  int? _total;
  bool _loading = true, _busy = false, _more = false, _schemaLoading = true;
  bool _selecting = false;
  bool get _products => widget.resource == 'products';
  bool get _shipments => widget.resource == 'shipment-records';
  String get _endpoint =>
      '${widget.apiBase}/${_shipments ? 'shipment/shipment-records' : widget.resource}';
  List<_Field> get _defaultFields => _products
      ? _productFields
      : _shipments
          ? _shipmentFields
          : _customerFields;
  List<Map<String, Object?>> get _visibleRows => !_shipments
      ? _rows
      : _rows.where((row) {
          final status = '${row['status'] ?? ''}'.trim().toLowerCase();
          final keyword = _keyword.toLowerCase();
          return (_status == 'all' ||
                  (_status == 'printed'
                      ? status == 'printed'
                      : status == 'pending' || status.isEmpty)) &&
              (keyword.isEmpty ||
                  row.values.any((v) => '$v'.toLowerCase().contains(keyword)));
        }).toList();
  bool get _editable =>
      _session.active &&
      !_loading &&
      !_schemaLoading &&
      !_busy &&
      _error == null &&
      _schemaError == null &&
      (!_shipments || _unitsError == null);

  @override
  void initState() {
    super.initState();
    _session = NativeWorkspaceSession(widget.repository.client,
        activeModId: widget.apiBase.startsWith('api/mod/')
            ? widget.apiBase.split('/').last
            : '')
      ..addListener(_invalidate);
    unawaited(_initialize());
  }

  void _invalidate() {
    if (mounted && !_session.active) {
      ++_ticket;
      setState(() {
        _rows = [];
        _selected.clear();
        _search.clear();
        _keyword = '';
      });
    }
  }

  @override
  void dispose() {
    _session.dispose();
    _search.dispose();
    super.dispose();
  }

  Future<void> _initialize() async {
    await Future.wait([_loadSchema(), _loadUnits(), _load()]);
  }

  Future<void> _loadSchema() async {
    setState(() {
      _schemaLoading = true;
    });
    try {
      final result = await _session.request('api/system/industry');
      final root = _map(result['data']);
      final config = _map(root['config']);
      final schema = _map(
          _map(config['subsystems'] ?? root['subsystems'])[widget.resource]);
      final declared = _maps(schema['fields'])
          .map(_Field.fromJson)
          .where((f) => f.key.isNotEmpty);
      final fields = <String, _Field>{
        for (final field in _defaultFields) field.key: field,
      };
      for (final field in declared) {
        final core = fields[field.key];
        fields[field.key] =
            field.copyRequired(field.required || (core?.required ?? false));
      }
      if (!mounted || !_session.active) return;
      setState(() {
        _fields = fields.values.where((f) => f.visible).toList();
        _schemaError = null;
      });
    } catch (error) {
      if (mounted && _session.active) {
        setState(() {
          _schemaError = mobileErrorText(error);
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          _schemaLoading = false;
        });
      }
    }
  }

  void _setBusy(bool value) => setState(() {
        _busy = value;
      });

  Future<void> _loadUnits() async {
    try {
      final response = await _session.request(
          '${widget.apiBase}/${_products ? 'products/units' : 'shipment/shipment-records/units'}');
      final data = response['data'] ?? response['units'];
      final raw = data is List ? data : _map(data)['units'];
      if (mounted && _session.active) {
        setState(() {
          _unitsError = null;
          _units = raw is List
              ? raw
                  .map((v) => v is Map
                      ? '${v['name'] ?? v['symbol'] ?? v['unit_name'] ?? v['customer_name'] ?? ''}'
                      : v.toString())
                  .where((v) => v.isNotEmpty)
                  .toSet()
                  .toList()
              : [];
        });
      }
    } catch (error) {
      if (mounted && _session.active) {
        setState(() {
          _unitsError = mobileErrorText(error);
        });
      }
    }
  }

  void _submitSearch(String input) {
    if (_busy) return;
    final keyword = input.trim();
    if (_keyword != keyword) {
      _keyword = keyword;
      _resetResults();
    }
    unawaited(_load());
  }

  void _resetResults() {
    _rows = [];
    _total = null;
    _more = false;
  }

  Future<void> _load({bool append = false}) async {
    if (!_session.active) return;
    final ticket = ++_ticket;
    final page = append ? _page + 1 : 1;
    setState(() {
      _loading = true;
      _error = null;
      if (!append) _selected.clear();
    });
    try {
      if (_shipments && _unit.isEmpty) {
        setState(_resetResults);
        return;
      }
      final response = await _session
          .request('$_endpoint/${_shipments ? 'records' : 'list'}', query: {
        'page': '$page',
        'per_page': '30',
        if (_keyword.isNotEmpty) 'keyword': _keyword,
        if (_unit.isNotEmpty)
          (_products
              ? 'unit'
              : _shipments
                  ? 'unit_name'
                  : 'purchase_unit'): _unit,
      });
      final rawRows =
          response['data'] ?? response[_shipments ? 'records' : 'customers'];
      if (rawRows is! List) throw StateError('服务未返回有效记录，请重试');
      final rows = _maps(rawRows);
      final total = num.tryParse('${response['total']}')?.toInt();
      if (!mounted || !_session.active || ticket != _ticket) return;
      setState(() {
        _rows = [if (append) ..._rows, ...rows];
        _page = page;
        _total = total;
        _more = !_shipments &&
            (total == null ? rows.length == 30 : _rows.length < total);
      });
    } catch (error) {
      if (mounted && _session.active && ticket == _ticket) {
        setState(() {
          _error = mobileErrorText(error);
        });
      }
    } finally {
      if (mounted && _session.active && ticket == _ticket) {
        setState(() {
          _loading = false;
        });
      }
    }
  }

  Future<void> _edit([Map<String, Object?>? row]) async {
    if (!_editable) return;
    final changed = await Navigator.of(context).push<Object?>(MaterialPageRoute(
      builder: (_) => _CatalogEditor(
          session: _session,
          title: widget.title,
          endpoint: _endpoint,
          products: _products,
          shipments: _shipments,
          fields: _shipments
              ? (row == null
                  ? _shipmentFields
                  : [
                      for (final field in _shipmentEditFields)
                        if (row.containsKey(field.key)) field
                    ])
              : _fields,
          units: _units,
          initial: row,
          selectedUnit: _unit),
    ));
    if (mounted && _session.active && (changed == true || changed is String)) {
      if (changed is String) {
        setState(() {
          _unit = changed;
          _resetResults();
        });
        await _loadUnits();
      }
      await _load();
    }
  }

  Future<void> _delete(List<Object> ids) async {
    if (!_editable || ids.isEmpty) return;
    final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
              title: Text('删除 ${ids.length} 条记录？'),
              content: Text((_products || _shipments)
                  ? '删除后无法撤销。'
                  : '客户关联的产品和发货记录也会删除，且无法撤销。'),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: const Text('取消')),
                FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: const Text('确认删除'))
              ],
            ));
    if (confirmed != true || !mounted || !_editable) return;
    setState(() {
      _busy = true;
    });
    try {
      if (_shipments) {
        await _session.request(
            'api/mobile/v1/workspace/shipment/shipment-records/record',
            method: 'DELETE',
            body: {'id': ids.single});
      } else if (ids.length > 1) {
        await _session.request('$_endpoint/batch-delete',
            method: 'POST', body: {'ids': ids});
      } else if (_products) {
        await _session.request('$_endpoint/delete',
            method: 'POST', body: {'id': ids.single});
      } else {
        await _session.request(
            '$_endpoint/${Uri.encodeComponent('${ids.single}')}?cascade=true',
            method: 'DELETE');
      }
      if (mounted && _session.active) await _load();
    } catch (error) {
      if (mounted && _session.active) _notice(mobileErrorText(error));
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
        });
      }
    }
  }

  void _notice(String message) => ScaffoldMessenger.of(context)
      .showSnackBar(SnackBar(content: Text(message)));

  @override
  Widget build(BuildContext context) {
    final rows = _visibleRows;
    return WorkspaceScaffold(
      backgroundColor: AppTheme.colors(context).page,
      body: SafeArea(
        child: Column(children: [
          WeTopBar(
            title: widget.title,
            showBack: true,
            actions: [
              _transferMenu(),
              IconButton(
                onPressed: _session.active && !_busy ? _initialize : null,
                tooltip: '刷新',
                icon: const Icon(Icons.refresh),
              ),
            ],
          ),
          if (_session.active)
            Expanded(
              child: RefreshIndicator(
                onRefresh: _initialize,
                child: ListView.builder(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
                  itemCount: rows.length + 2,
                  itemBuilder: (context, index) {
                    if (index == 0) return _listHeader(rows.length);
                    if (index <= rows.length) {
                      final row = rows[index - 1];
                      return Padding(
                        key: ValueKey((widget.resource, row['id'] ?? index)),
                        padding: const EdgeInsets.only(top: 8),
                        child: _recordTile(row),
                      );
                    }
                    return _more
                        ? Padding(
                            padding: const EdgeInsets.only(top: 16),
                            child: OutlinedButton(
                              onPressed: !_loading && !_busy
                                  ? () => _load(append: true)
                                  : null,
                              child: const Text('加载更多'),
                            ),
                          )
                        : const SizedBox.shrink();
                  },
                ),
              ),
            )
          else
            const Expanded(
              child: Center(child: Text('账号或连接已切换，请返回后重新打开')),
            ),
          if (_session.active && _selecting) _selectionBar(),
        ]),
      ),
    );
  }

  Widget _listHeader(int visibleCount) {
    final colors = AppTheme.colors(context);
    final theme = Theme.of(context).textTheme;
    final filtered = _shipments && (_status != 'all' || _keyword.isNotEmpty);
    final count =
        _shipments || _total == null ? '显示 $visibleCount 条' : '共 $_total 条';
    final noMatch = _keyword.isNotEmpty || (_shipments && _status != 'all');
    final empty = _shipments && _unit.isEmpty
        ? '请先选择购买单位'
        : noMatch
            ? '没有符合筛选条件的记录'
            : '暂无记录';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        WorkspacePanel(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (_shipments || _units.isNotEmpty) ...[
                _unitFilter(),
                const SizedBox(height: 12),
              ],
              ValueListenableBuilder(
                valueListenable: _search,
                builder: (context, value, _) => TextField(
                  controller: _search,
                  enabled: !_busy && (!_shipments || _unit.isNotEmpty),
                  textInputAction: TextInputAction.search,
                  onSubmitted: _submitSearch,
                  decoration: InputDecoration(
                    border: const OutlineInputBorder(),
                    hintText: _products
                        ? '搜索型号或名称'
                        : _shipments
                            ? '搜索已读取的出货记录'
                            : '搜索名称、联系人或电话',
                    prefixIcon: const Icon(Icons.search),
                    suffixIcon: value.text.isNotEmpty || _keyword.isNotEmpty
                        ? IconButton(
                            tooltip:
                                value.text.trim() != _keyword ? '搜索' : '清除搜索',
                            onPressed: _loading || _busy
                                ? null
                                : () {
                                    if (value.text.trim() == _keyword) {
                                      _search.clear();
                                    }
                                    _submitSearch(_search.text);
                                  },
                            icon: Icon(value.text.trim() != _keyword
                                ? Icons.arrow_forward
                                : Icons.close),
                          )
                        : null,
                  ),
                ),
              ),
              if (_shipments && _unit.isNotEmpty) ...[
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 4,
                  children: [
                    for (final option in const {
                      'all': '全部状态',
                      'pending': '未打印',
                      'printed': '已打印',
                    }.entries)
                      ChoiceChip(
                        label: Text(option.value),
                        selected: _status == option.key,
                        onSelected: _busy
                            ? null
                            : (_) => setState(() => _status = option.key),
                      ),
                  ],
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 12),
        Wrap(
          alignment: WrapAlignment.spaceBetween,
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: 12,
          runSpacing: 8,
          children: [
            if (!_shipments || _unit.isNotEmpty)
              Semantics(
                liveRegion: true,
                child: Text(
                  filtered ? '$count · 已读取 ${_rows.length} 条' : count,
                  style:
                      theme.bodyMedium?.copyWith(color: colors.textSecondary),
                ),
              ),
            if (!_selecting)
              Wrap(
                crossAxisAlignment: WrapCrossAlignment.center,
                spacing: 4,
                runSpacing: 6,
                children: [
                  if (!_shipments && _rows.isNotEmpty)
                    TextButton(
                      onPressed: _editable
                          ? () => setState(() => _selecting = true)
                          : null,
                      child: const Text('选择'),
                    ),
                  FilledButton.icon(
                    onPressed: _editable ? () => _edit() : null,
                    icon: const Icon(Icons.add),
                    label: const Text('新建'),
                  ),
                ],
              ),
          ],
        ),
        if (_loading || _busy || _schemaLoading) ...[
          const SizedBox(height: 8),
          const LinearProgressIndicator(),
        ],
        if (_unitsError != null) _errorPanel('单位读取失败：$_unitsError', _loadUnits),
        if (_schemaError != null)
          _errorPanel('字段配置读取失败：$_schemaError', _loadSchema),
        if (_error != null) _errorPanel('读取失败：$_error', _load),
        if (!_loading && _error == null && visibleCount == 0)
          WorkspaceTransition(
            child: Padding(
              key: ValueKey(empty),
              padding: const EdgeInsets.symmetric(vertical: 24),
              child: WorkspacePanel(
                child: Column(children: [
                  Icon(
                    noMatch ? Icons.search_off : Icons.inbox_outlined,
                    color: colors.textSecondary,
                  ),
                  const SizedBox(height: 8),
                  Text(empty, textAlign: TextAlign.center),
                ]),
              ),
            ),
          ),
      ],
    );
  }

  Widget _selectionBar() {
    final colors = AppTheme.colors(context);
    return ColoredBox(
      color: colors.surface,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        child: Row(
          children: [
            Expanded(
              child: Semantics(
                liveRegion: true,
                child: Text('已选择 ${_selected.length} 条'),
              ),
            ),
            IconButton(
              tooltip: '删除所选记录',
              onPressed: _editable && _selected.isNotEmpty
                  ? () => _delete(_selected.toList())
                  : null,
              icon: const Icon(Icons.delete_outline),
              color: colors.danger,
            ),
            TextButton(
              onPressed: _busy
                  ? null
                  : () => setState(() {
                        _selecting = false;
                        _selected.clear();
                      }),
              child: const Text('完成'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _unitFilter() => DropdownButtonFormField<String>(
        key: ValueKey('unit-$_unit'),
        initialValue: _unit,
        isExpanded: true,
        decoration: InputDecoration(
          border: const OutlineInputBorder(),
          labelText: _products ? '产品单位' : '购买单位',
        ),
        items: [
          DropdownMenuItem(
            value: '',
            child: Text(_shipments ? '选择单位' : '全部单位'),
          ),
          for (final unit in {if (_unit.isNotEmpty) _unit, ..._units})
            DropdownMenuItem(
              value: unit,
              child: Text(unit, overflow: TextOverflow.ellipsis),
            ),
        ],
        onChanged: _busy || _units.isEmpty
            ? null
            : (value) {
                final unit = value ?? '';
                if (unit == _unit) return;
                setState(() {
                  _unit = unit;
                  _resetResults();
                });
                unawaited(_load());
              },
      );

  Widget _recordTile(Map<String, Object?> row) {
    final colors = AppTheme.colors(context);
    final text = Theme.of(context).textTheme;
    final id = row['id'];
    final title = Text(_name(row), style: text.titleSmall);
    final fields = _shipments
        ? _shipmentEditFields
        : _fields.isEmpty
            ? _defaultFields
            : _fields;
    final summaryKeys = _products
        ? const ['model_number', 'specification', 'price']
        : _shipments
            ? const ['model_number', 'quantity_tins', 'amount']
            : const ['contact_person', 'contact_phone'];
    final shipmentStatus = _shipments ? _shipmentStatus(row['status']) : null;
    final summary = Wrap(
      spacing: 10,
      runSpacing: 4,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        for (final key in summaryKeys)
          for (final field in fields)
            if (field.key == key && '${row[key] ?? ''}'.isNotEmpty)
              Text(
                '${field.label}：${row[key]}',
                style: text.bodySmall?.copyWith(color: colors.textSecondary),
              ),
        if (shipmentStatus != null)
          WorkspaceBadge(
            label: shipmentStatus,
            color: shipmentStatus == '已打印' ? colors.success : null,
          ),
      ],
    );
    void toggleSelection() => setState(() {
          if (id == null) return;
          if (!_selected.add(id)) _selected.remove(id);
        });
    return WorkspacePanel(
      padding: EdgeInsets.zero,
      child: _selecting
          ? ListTile(
              title: title,
              subtitle: summary,
              selected: _selected.contains(id),
              leading: Checkbox(
                semanticLabel: '选择 ${_name(row)}',
                value: _selected.contains(id),
                onChanged:
                    _editable && id != null ? (_) => toggleSelection() : null,
              ),
              onTap: _editable && id != null ? toggleSelection : null,
            )
          : ExpansionTile(
              key: PageStorageKey((widget.resource, id ?? row)),
              title: title,
              subtitle: summary,
              expansionAnimationStyle: AnimationStyle(
                duration: AppTheme.motionDuration(context),
                reverseDuration: AppTheme.motionDuration(context),
              ),
              shape: const Border(),
              collapsedShape: const Border(),
              expandedCrossAxisAlignment: CrossAxisAlignment.start,
              childrenPadding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
              children: [
                for (final field in fields)
                  if (field.key != 'name' &&
                      field.key != 'status' &&
                      !summaryKeys.contains(field.key) &&
                      '${row[field.key] ?? ''}'.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: Text('${field.label}：${row[field.key]}'),
                    ),
                if (id != null)
                  Align(
                    alignment: AlignmentDirectional.centerEnd,
                    child: Wrap(
                      spacing: 8,
                      runSpacing: 4,
                      children: [
                        TextButton(
                          style: TextButton.styleFrom(
                            foregroundColor: colors.danger,
                          ),
                          onPressed: _editable ? () => _delete([id]) : null,
                          child: const Text('删除'),
                        ),
                        FilledButton.tonalIcon(
                          onPressed: _editable ? () => _edit(row) : null,
                          icon: const Icon(Icons.edit_outlined),
                          label: Text('编辑', semanticsLabel: '编辑 ${_name(row)}'),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
    );
  }

  String _shipmentStatus(Object? status) =>
      switch (status?.toString().trim().toLowerCase()) {
        'printed' => '已打印',
        null || '' || 'pending' => '未打印',
        _ => status.toString(),
      };

  Widget _errorPanel(String message, VoidCallback retry) => Padding(
        padding: const EdgeInsets.only(top: 8),
        child: WorkspacePanel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(Icons.error_outline,
                      color: Theme.of(context).colorScheme.error),
                  const SizedBox(width: 8),
                  Expanded(child: Text(message)),
                ],
              ),
              TextButton(
                  onPressed: _busy ? null : retry, child: const Text('重试')),
            ],
          ),
        ),
      );
}

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:file_selector/file_selector.dart';

import '../../platform/workspace_file_export.dart';

import '../../data/mobile_repository.dart';
import '../../policy/mobile_error_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../workspace/native_workspace_session.dart';

part 'native_catalog_transfer.part.dart';

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
  String _unit = '', _status = 'all';
  String? _error, _schemaError, _unitsError;
  int _page = 1, _ticket = 0;
  int? _total;
  bool _loading = true, _busy = false, _more = false, _schemaLoading = true;
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
          final status = '${row['status'] ?? ''}'.toLowerCase();
          final keyword = _search.text.trim().toLowerCase();
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

  Future<void> _load({bool append = false}) async {
    if (!_session.active) return;
    final ticket = ++_ticket;
    final page = append ? _page + 1 : 1;
    setState(() {
      _loading = true;
      _error = null;
      _selected.clear();
    });
    try {
      if (_shipments && _unit.isEmpty) {
        setState(() {
          _rows = [];
          _total = null;
          _more = false;
        });
        return;
      }
      final response = await _session
          .request('$_endpoint/${_shipments ? 'records' : 'list'}', query: {
        'page': '$page',
        'per_page': '30',
        if (_search.text.trim().isNotEmpty) 'keyword': _search.text.trim(),
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
    final colors = AppTheme.colors(context);
    return Scaffold(
        backgroundColor: colors.page,
        body: SafeArea(
            child: Column(children: [
          WeTopBar(
              title: widget.title,
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
              actions: [
                _transferMenu(),
                IconButton(
                    onPressed: _session.active && !_busy ? _initialize : null,
                    tooltip: '刷新',
                    icon: const Icon(Icons.refresh))
              ]),
          if (!_session.active)
            const Expanded(child: Center(child: Text('账号或连接已切换，请返回后重新打开')))
          else
            Expanded(
                child: RefreshIndicator(
                    onRefresh: _initialize,
                    child: ListView(
                        physics: const AlwaysScrollableScrollPhysics(),
                        padding: const EdgeInsets.all(16),
                        children: [
                          TextField(
                              controller: _search,
                              textInputAction: TextInputAction.search,
                              onSubmitted: (_) => _load(),
                              decoration: InputDecoration(
                                  hintText: _products
                                      ? '搜索型号或名称'
                                      : _shipments
                                          ? '搜索当前单位记录'
                                          : '搜索名称、联系人或电话',
                                  prefixIcon: const Icon(Icons.search),
                                  suffixIcon: IconButton(
                                      tooltip: '搜索',
                                      onPressed: _loading ? null : _load,
                                      icon: const Icon(Icons.arrow_forward)))),
                          if (_units.isNotEmpty)
                            Padding(
                                padding: const EdgeInsets.only(top: 12),
                                child: DropdownButtonFormField<String>(
                                    key: ValueKey('unit-$_unit'),
                                    initialValue: _unit,
                                    isExpanded: true,
                                    decoration: const InputDecoration(
                                        labelText: '所属客户'),
                                    items: [
                                      const DropdownMenuItem(
                                          value: '', child: Text('全部客户')),
                                      for (final unit in {
                                        if (_unit.isNotEmpty) _unit,
                                        ..._units
                                      })
                                        DropdownMenuItem(
                                            value: unit,
                                            child: Text(unit,
                                                overflow:
                                                    TextOverflow.ellipsis))
                                    ],
                                    onChanged: _busy
                                        ? null
                                        : (value) {
                                            setState(() {
                                              _unit = value ?? '';
                                            });
                                            unawaited(_load());
                                          })),
                          if (_shipments)
                            Padding(
                                padding: const EdgeInsets.only(top: 12),
                                child: Wrap(spacing: 8, children: [
                                  for (final entry in const {
                                    'all': '全部状态',
                                    'pending': '未打印',
                                    'printed': '已打印'
                                  }.entries)
                                    ChoiceChip(
                                        label: Text(entry.value),
                                        selected: _status == entry.key,
                                        onSelected: (_) => setState(() {
                                              _status = entry.key;
                                            }))
                                ])),
                          const SizedBox(height: 16),
                          Row(children: [
                            Expanded(
                                child: Text(
                                    _total == null
                                        ? '已读取 ${_rows.length} 条'
                                        : '共 $_total 条',
                                    style: Theme.of(context)
                                        .textTheme
                                        .titleMedium)),
                            if (_selected.isNotEmpty)
                              IconButton(
                                  tooltip: '删除所选记录',
                                  onPressed: _editable
                                      ? () => _delete(_selected.toList())
                                      : null,
                                  icon: const Icon(Icons.delete_outline)),
                            FilledButton.icon(
                                onPressed: _editable ? () => _edit() : null,
                                icon: const Icon(Icons.add),
                                label: const Text('新建'))
                          ]),
                          if (_unitsError != null)
                            _errorPanel('购买单位读取失败：$_unitsError', _loadUnits),
                          if (_schemaError != null)
                            _errorPanel('字段配置读取失败：$_schemaError', _loadSchema),
                          if (_error != null)
                            _errorPanel('读取失败：$_error', _load),
                          if (_loading || _busy)
                            const Padding(
                                padding: EdgeInsets.symmetric(vertical: 12),
                                child: LinearProgressIndicator()),
                          if (!_loading && _error == null && _rows.isEmpty)
                            Padding(
                                padding: const EdgeInsets.all(40),
                                child: Center(
                                    child: Text(_shipments && _unit.isEmpty
                                        ? '请先选择购买单位'
                                        : '暂无记录'))),
                          for (final row in _visibleRows)
                            Card(
                                margin: const EdgeInsets.only(top: 12),
                                child: Padding(
                                    padding: const EdgeInsets.all(12),
                                    child: Column(
                                        crossAxisAlignment:
                                            CrossAxisAlignment.start,
                                        children: [
                                          Row(children: [
                                            if (row['id'] != null &&
                                                !_shipments)
                                              Checkbox(
                                                  value: _selected
                                                      .contains(row['id']),
                                                  onChanged: !_editable
                                                      ? null
                                                      : (checked) {
                                                          setState(() {
                                                            if (checked ==
                                                                true) {
                                                              _selected.add(
                                                                  row['id']!);
                                                            } else {
                                                              _selected.remove(
                                                                  row['id']);
                                                            }
                                                          });
                                                        }),
                                            Expanded(
                                                child: Text(_name(row),
                                                    style: Theme.of(context)
                                                        .textTheme
                                                        .titleMedium)),
                                            IconButton(
                                                tooltip: '编辑 ${_name(row)}',
                                                onPressed: _editable &&
                                                        row['id'] != null
                                                    ? () => _edit(row)
                                                    : null,
                                                icon: const Icon(
                                                    Icons.edit_outlined))
                                          ]),
                                          for (final field in (_shipments
                                              ? _shipmentEditFields
                                              : _fields.isEmpty
                                                  ? _defaultFields
                                                  : _fields))
                                            if (field.key != 'name' &&
                                                '${row[field.key] ?? ''}'
                                                    .isNotEmpty)
                                              Padding(
                                                  padding: const EdgeInsets
                                                      .symmetric(vertical: 3),
                                                  child: Text(
                                                      '${field.label}：${row[field.key]}')),
                                          if (row['id'] != null)
                                            Align(
                                                alignment:
                                                    Alignment.centerRight,
                                                child: TextButton(
                                                    onPressed: _editable
                                                        ? () => _delete(
                                                            [row['id']!])
                                                        : null,
                                                    child: const Text('删除'))),
                                        ]))),
                          if (_more)
                            Padding(
                                padding: const EdgeInsets.all(16),
                                child: OutlinedButton(
                                    onPressed: !_loading && !_busy
                                        ? () => _load(append: true)
                                        : null,
                                    child: const Text('加载更多'))),
                        ]))),
        ])));
  }

  Widget _errorPanel(String message, VoidCallback retry) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(message),
        TextButton(onPressed: retry, child: const Text('重试'))
      ]));
}

class _CatalogEditor extends StatefulWidget {
  const _CatalogEditor(
      {required this.session,
      required this.title,
      required this.endpoint,
      required this.products,
      this.shipments = false,
      required this.fields,
      required this.units,
      required this.initial,
      required this.selectedUnit});
  final NativeWorkspaceSession session;
  final String title, endpoint, selectedUnit;
  final bool products, shipments;
  final List<_Field> fields;
  final List<String> units;
  final Map<String, Object?>? initial;
  @override
  State<_CatalogEditor> createState() => _CatalogEditorState();
}

class _CatalogEditorState extends State<_CatalogEditor> {
  final _form = GlobalKey<FormState>();
  late final Map<String, TextEditingController> _controllers;
  bool _busy = false;
  String? _error;
  bool get _edit => widget.initial != null;
  List<_Field> get _fields => widget.fields
      .where((f) => !(_edit &&
          widget.products &&
          const ['quantity', 'unit'].contains(f.key)))
      .toList();
  @override
  void initState() {
    super.initState();
    final row = widget.initial ?? {};
    _controllers = {
      for (final field in _fields)
        field.key: TextEditingController(
            text: '${row[field.key] ?? (field.key == 'name' && _edit ? _name(row) : const [
                'unit',
                'unit_name'
              ].contains(field.key) ? widget.selectedUnit : field.type == 'number' ? 0 : '')}')
    };
    widget.session.addListener(_invalidate);
  }

  void _invalidate() {
    if (mounted) {
      for (final controller in _controllers.values) {
        controller.clear();
      }
      setState(() {});
    }
  }

  @override
  void dispose() {
    widget.session.removeListener(_invalidate);
    for (final c in _controllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    if (_busy || !widget.session.active || !_form.currentState!.validate()) {
      return;
    }
    final body = <String, Object?>{
      for (final field in _fields)
        field.key: field.type == 'number'
            ? num.parse(_controllers[field.key]!.text.trim().isEmpty
                ? '0'
                : _controllers[field.key]!.text.trim())
            : _controllers[field.key]!.text.trim()
    };
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final id = widget.initial?['id'];
      final path = widget.shipments
          ? 'api/mobile/v1/workspace/shipment/shipment-records/record'
          : widget.products
              ? '${widget.endpoint}/${_edit ? 'update' : 'add'}'
              : '${widget.endpoint}${_edit ? '/${Uri.encodeComponent('$id')}' : ''}';
      await widget.session.request(path,
          method: widget.shipments
              ? (_edit ? 'PATCH' : 'POST')
              : _edit && !widget.products
                  ? 'PUT'
                  : 'POST',
          body: widget.shipments
              ? (_edit
                  ? {'id': id, ...body}
                  : {
                      'unit_name': body['unit_name'],
                      'contact_person': body['contact_person'],
                      'contact_phone': body['contact_phone'],
                      'products': [
                        {
                          for (final key in const [
                            'product_name',
                            'model_number',
                            'quantity_tins',
                            'tin_spec',
                            'unit_price',
                            'amount'
                          ])
                            key: body[key]
                        }
                      ],
                    })
              : {
                  if (_edit && widget.products) 'id': id,
                  if (_edit &&
                      widget.products &&
                      widget.initial?['unit'] != null)
                    'unit': widget.initial!['unit'],
                  ...body,
                  if (!widget.products) 'customer_name': body['name'],
                });
      if (mounted && widget.session.active) {
        Navigator.pop(
            context, widget.shipments && !_edit ? body['unit_name'] : true);
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
            title: '${_edit ? '编辑' : '新建'}${widget.title}',
            showBack: true,
            onBack: () => Navigator.maybePop(context)),
        if (!widget.session.active)
          const Expanded(child: Center(child: Text('账号或连接已切换，请返回后重新打开')))
        else
          Expanded(
              child: Form(
                  key: _form,
                  child: ListView(padding: const EdgeInsets.all(20), children: [
                    for (final field in _fields)
                      Padding(
                          padding: const EdgeInsets.only(bottom: 18),
                          child: (field.key == 'unit'
                                      ? widget.units
                                      : field.options)
                                  .isNotEmpty
                              ? DropdownButtonFormField<String>(
                                  initialValue: (field.key == 'unit'
                                              ? widget.units
                                              : field.options)
                                          .contains(
                                              _controllers[field.key]!.text)
                                      ? _controllers[field.key]!.text
                                      : null,
                                  decoration: InputDecoration(
                                      labelText:
                                          '${field.label}${field.required ? ' *' : ''}'),
                                  items: [
                                    for (final option in (field.key == 'unit'
                                        ? widget.units
                                        : field.options))
                                      DropdownMenuItem(
                                          value: option, child: Text(option))
                                  ],
                                  onChanged: _busy
                                      ? null
                                      : (value) {
                                          _controllers[field.key]!.text =
                                              value ?? '';
                                        },
                                  validator: (_) => field
                                      .validate(_controllers[field.key]!.text),
                                )
                              : TextFormField(
                                  key: ValueKey('field-${field.key}'),
                                  controller: _controllers[field.key],
                                  enabled: !_busy,
                                  decoration: InputDecoration(
                                      labelText:
                                          '${field.label}${field.required ? ' *' : ''}'),
                                  keyboardType: field.type == 'number'
                                      ? const TextInputType.numberWithOptions(
                                          decimal: true)
                                      : TextInputType.text,
                                  validator: field.validate)),
                    if (_error != null)
                      Padding(
                          padding: const EdgeInsets.only(bottom: 16),
                          child: Text(_error!)),
                    FilledButton(
                        onPressed: _busy ? null : _save,
                        child: Text(_busy ? '正在保存…' : '保存')),
                  ]))),
      ])));
}

Map<String, Object?> _map(Object? value) =>
    value is Map ? Map<String, Object?>.from(value) : {};
List<Map<String, Object?>> _maps(Object? value) => value is List
    ? value.whereType<Map>().map((v) => Map<String, Object?>.from(v)).toList()
    : [];
String _name(Map<String, Object?> row) =>
    '${row['name'] ?? row['product_name'] ?? row['customer_name'] ?? row['unit_name'] ?? '未命名记录'}';

class _Field {
  const _Field(this.key, this.label,
      {this.type = 'text',
      this.required = false,
      this.visible = true,
      this.validators = const []});
  factory _Field.fromJson(Map<String, Object?> json) =>
      _Field('${json['key'] ?? ''}', '${json['label'] ?? json['key'] ?? ''}',
          type: '${json['type'] ?? 'text'}',
          required: json['required'] == true,
          visible: json['visible'] != false,
          validators: _maps(json['validators']));
  final String key, label, type;
  final bool required, visible;
  final List<Map<String, Object?>> validators;
  _Field copyRequired(bool value) => _Field(key, label,
      type: type, required: value, visible: visible, validators: validators);
  List<String> get options => [
        for (final rule in validators)
          if (rule['type'] == 'oneOf' && rule['params'] is List)
            ...(rule['params'] as List).map((v) => '$v')
      ];
  String? validate(String? raw) {
    final value = raw?.trim() ?? '';
    if (value.isEmpty) return required ? '请输入$label' : null;
    final number = num.tryParse(value);
    if (type == 'number' && (number == null || !number.isFinite)) {
      return '请输入有效数字';
    }
    if (key == 'quantity' &&
        (number == null || number < 0 || number != number.round())) {
      return '库存须为非负整数';
    }
    if (key == 'quantity_tins' &&
        (number == null || number <= 0 || number != number.round())) {
      return '数量须为正整数';
    }
    if (key == 'tin_spec' && (number == null || number <= 0)) return '规格须大于零';
    if (const ['unit_price', 'amount'].contains(key) &&
        number != null &&
        number < 0) {
      return '金额和单价不能为负数';
    }
    for (final rule in validators) {
      final params = _map(rule['params']);
      if (rule['type'] == 'oneOf' && !options.contains(value)) {
        return '请选择有效的$label';
      }
      if (rule['type'] == 'range' && number != null) {
        final min = num.tryParse('${params['min']}'),
            max = num.tryParse('${params['max']}');
        if (min != null && number < min) return '不能小于 $min';
        if (max != null && number > max) return '不能大于 $max';
      }
      if (rule['type'] == 'regex') {
        try {
          if (!RegExp(rule['params'] is String
                  ? rule['params'] as String
                  : '${params['pattern'] ?? ''}')
              .hasMatch(value)) {
            return '格式不正确';
          }
        } on FormatException {
          return '字段规则无效，请刷新';
        }
      }
      if (rule['type'] == 'not_expired') {
        final date = DateTime.tryParse(value), now = DateTime.now();
        if (date == null) return '请输入有效日期';
        if (date.isBefore(DateTime(now.year, now.month, now.day))) {
          return '已过保质期';
        }
      }
    }
    return null;
  }
}

const _productFields = [
  _Field('unit', '所属客户', required: true),
  _Field('model_number', '型号', required: true),
  _Field('name', '名称', required: true),
  _Field('specification', '规格'),
  _Field('price', '价格', type: 'number'),
  _Field('quantity', '初始库存', type: 'number')
];
const _customerFields = [
  _Field('name', '名称', required: true),
  _Field('contact_person', '联系人'),
  _Field('contact_phone', '电话'),
  _Field('contact_address', '地址')
];

const _shipmentFields = [
  _Field('unit_name', '购买单位', required: true),
  _Field('contact_person', '联系人'),
  _Field('contact_phone', '电话'),
  _Field('product_name', '产品名称', required: true),
  _Field('model_number', '型号'),
  _Field('quantity_tins', '数量', type: 'number', required: true),
  _Field('tin_spec', '规格', type: 'number', required: true),
  _Field('unit_price', '单价', type: 'number', required: true),
  _Field('amount', '金额', type: 'number', required: true),
];
const _shipmentEditFields = [
  _Field('purchase_unit', '购买单位'),
  ..._shipmentFields,
  _Field('quantity_kg', '数量（KG）', type: 'number'),
  _Field('status', '状态'),
  _Field('created_at', '创建时间'),
  _Field('printed_at', '打印时间'),
  _Field('printer_name', '打印机'),
];

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import '../../data/local_workspace.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import '../scan/scan_qr_screen.dart';
import 'native_record_editor.dart';

enum _LocalArea {
  customer('客户', 'name', Icons.people_outline),
  product('产品', 'name', Icons.inventory_2_outlined),
  order('订单草稿', 'title', Icons.receipt_long_outlined);

  const _LocalArea(this.label, this.titleKey, this.icon);
  final String label, titleKey;
  final IconData icon;

  static _LocalArea of(String kind) =>
      values.firstWhere((area) => area.name == kind, orElse: () => order);
}

class LocalWorkspaceScreen extends StatefulWidget {
  const LocalWorkspaceScreen({super.key, this.controller});

  final LocalWorkspaceController? controller;

  @override
  State<LocalWorkspaceScreen> createState() => _LocalWorkspaceScreenState();
}

class _LocalWorkspaceScreenState extends State<LocalWorkspaceScreen>
    with WidgetsBindingObserver {
  late final LocalWorkspaceController _workspace;
  final _search = TextEditingController();
  _LocalArea _area = _LocalArea.customer;
  bool _opening = true;
  late final Timer _syncTimer;
  DateTime? _retryAutoSyncAfter;
  String? _openError;

  @override
  void initState() {
    super.initState();
    _workspace = widget.controller ?? LocalWorkspaceController();
    WidgetsBinding.instance.addObserver(this);
    _syncTimer =
        Timer.periodic(const Duration(seconds: 15), (_) => _autoSync());
    unawaited(_open());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _syncTimer.cancel();
    if (widget.controller == null) _workspace.dispose();
    _search.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _retryAutoSyncAfter = null;
      unawaited(_autoSync());
    }
  }

  Future<void> _autoSync() async {
    if (!mounted ||
        _opening ||
        _openError != null ||
        !_workspace.isBound ||
        _workspace.busy) {
      return;
    }
    final state = WidgetsBinding.instance.lifecycleState;
    if (state != null && state != AppLifecycleState.resumed) return;
    if (ModalRoute.of(context)?.isCurrent != true) return;
    final retryAfter = _retryAutoSyncAfter;
    if (retryAfter != null && DateTime.now().isBefore(retryAfter)) return;
    try {
      await _workspace.sync();
      _retryAutoSyncAfter = null;
    } catch (_) {
      // Leave time for local edits when the peer remains offline.
      _retryAutoSyncAfter = DateTime.now().add(const Duration(minutes: 1));
    }
  }

  Future<void> _open() async {
    setState(() {
      _opening = true;
      _openError = null;
    });
    try {
      await _workspace.open();
    } catch (_) {
      if (mounted) setState(() => _openError = '无法打开本机工作台，请重试。');
    } finally {
      if (mounted) {
        setState(() => _opening = false);
        unawaited(_autoSync());
      }
    }
  }

  void _notify(String message) {
    if (mounted) {
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(message)));
    }
  }

  Future<void> _sync() async {
    if (_workspace.busy) return;
    try {
      await _workspace.sync();
      _retryAutoSyncAfter = null;
      _notify(_workspace.conflicts.isEmpty
          ? (_workspace.pendingCount == 0 ? '同步完成' : '还有改动待同步，请重试')
          : '同步完成，请处理数据冲突');
    } catch (_) {
      _notify('同步失败。请确认手机与电脑在同一网络，且电脑已开启本地同步。');
    }
  }

  Future<void> _unbind() async {
    if (!await _confirmLocal(
        context, '解除电脑绑定？', '本机数据会保留，可以继续离线使用。', '解除绑定')) {
      return;
    }
    if (!mounted || _workspace.busy) return;
    try {
      await _workspace.unbind();
      _notify(_workspace.remoteUnbindConfirmed == false
          ? '已解除本机绑定。电脑端离线，可在电脑端解除原有绑定。'
          : '已解除绑定，本机数据已保留');
    } catch (_) {
      _notify('无法解除绑定，请重试。');
    }
  }

  Future<void> _remove(LocalWorkspaceRecord record) async {
    if (!await _confirmLocal(
        context, '删除这条${_area.label}？', _recordTitle(record), '删除')) {
      return;
    }
    if (!mounted || _workspace.busy) return;
    try {
      await _workspace.delete(record.id, kind: record.kind);
      _notify('已删除');
      unawaited(_autoSync());
    } catch (_) {
      _notify('删除失败，请重试。');
    }
  }

  Future<void> _edit([LocalWorkspaceRecord? record]) async {
    if (_workspace.busy) return;
    final area = _area;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => _LocalRecordForm(
          area: area,
          record: record,
          records: _workspace.records,
          onSave: (data) => _workspace.save(area.name, data, id: record?.id),
        ),
      ),
    );
    unawaited(_autoSync());
  }

  Future<void> _bind() async {
    if (_workspace.busy) return;
    final bound = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
          builder: (_) => _LocalWorkspacePairing(workspace: _workspace)),
    );
    if (bound == true) {
      _retryAutoSyncAfter = null;
      _notify('电脑已绑定，数据已同步');
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return AnimatedBuilder(
      animation: _workspace,
      builder: (context, _) => Scaffold(
        backgroundColor: colors.page,
        body: SafeArea(
          child: Column(
            children: [
              const WeTopBar(title: '本地工作台', showBack: true),
              if (_opening || _workspace.busy) const LinearProgressIndicator(),
              if (_openError != null)
                Expanded(
                  child: Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(_openError!),
                        TextButton(onPressed: _open, child: const Text('重试')),
                      ],
                    ),
                  ),
                )
              else if (_opening)
                const Expanded(child: Center(child: Text('正在读取本机数据')))
              else ...[
                Expanded(
                  child: ListView(
                    keyboardDismissBehavior:
                        ScrollViewKeyboardDismissBehavior.onDrag,
                    padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
                    children: [
                      _connectionPanel(),
                      const SizedBox(height: 12),
                      Wrap(
                        spacing: 8,
                        children: [
                          for (final area in _LocalArea.values)
                            ChoiceChip(
                              label: Text(area.label),
                              selected: _area == area,
                              materialTapTargetSize:
                                  MaterialTapTargetSize.padded,
                              showCheckmark: false,
                              onSelected: (_) => setState(() {
                                _area = area;
                                _search.clear();
                              }),
                            ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      TextField(
                        controller: _search,
                        decoration: InputDecoration(
                          labelText: '搜索${_area.label}',
                          prefixIcon: const Icon(Icons.search),
                          suffixIcon: _search.text.isEmpty
                              ? null
                              : IconButton(
                                  tooltip: '清空搜索',
                                  onPressed: () => setState(_search.clear),
                                  icon: const Icon(Icons.clear),
                                ),
                        ),
                        onChanged: (_) => setState(() {}),
                      ),
                      const SizedBox(height: 12),
                      ..._recordList(),
                    ],
                  ),
                ),
                Material(
                  color: colors.surface,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                    child: SizedBox(
                      width: double.infinity,
                      child: FilledButton.icon(
                        style: FilledButton.styleFrom(
                            minimumSize: const Size(0, 48)),
                        onPressed: _workspace.busy ? null : () => _edit(),
                        icon: const Icon(Icons.add),
                        label: Text('新建${_area.label}'),
                      ),
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _connectionPanel() {
    final bound = _workspace.isBound;
    final busy = _workspace.busy;
    final conflicts = _workspace.conflicts.length;
    final archives = _workspace.archives.length;
    final pending = _workspace.pendingCount;
    final text = Theme.of(context).textTheme;
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(bound ? '已绑定电脑' : '仅保存在本机', style: text.titleMedium),
            Text(
              bound ? '待同步 $pending 条 · 冲突 $conflicts 条' : '绑定后可与电脑通过局域网同步。',
              style: text.bodyMedium,
            ),
            if (_workspace.endpoint case final String endpoint when bound)
              if (Uri.tryParse(endpoint) case final Uri uri)
                Text(uri.host, style: text.bodySmall),
            Wrap(
              spacing: 4,
              children: [
                if (bound) ...[
                  TextButton.icon(
                    onPressed: busy ? null : _sync,
                    icon: const Icon(Icons.sync),
                    label: const Text('立即同步'),
                  ),
                  TextButton(
                    onPressed: busy ? null : _unbind,
                    child: const Text('解除绑定'),
                  ),
                ] else
                  TextButton.icon(
                    onPressed: busy ? null : _bind,
                    icon: const Icon(Icons.qr_code_scanner),
                    label: const Text('绑定电脑'),
                  ),
                if (conflicts > 0)
                  TextButton(
                    onPressed: busy
                        ? null
                        : () =>
                            Navigator.of(context).push(MaterialPageRoute<void>(
                              builder: (_) => _LocalWorkspaceConflicts(
                                  workspace: _workspace),
                            )),
                    child: Text('处理冲突（$conflicts）'),
                  ),
                if (archives > 0)
                  TextButton(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => _LocalWorkspaceArchives(
                            archives: _workspace.archives),
                      ),
                    ),
                    child: Text('本机归档（$archives）'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _recordList() {
    final query = _search.text.trim().toLowerCase();
    final records = _workspace.records.where((record) =>
        record.kind == _area.name &&
        jsonEncode(record.data).toLowerCase().contains(query));
    if (records.isEmpty) {
      return [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 24),
          child: Center(
              child: Text(query.isEmpty ? '暂无${_area.label}' : '没有匹配的记录')),
        ),
      ];
    }
    return [
      for (final record in records)
        Card(
          margin: const EdgeInsets.only(bottom: 8),
          child: ListTile(
            leading: Icon(_area.icon),
            title: Text(_recordTitle(record),
                maxLines: 2, overflow: TextOverflow.ellipsis),
            subtitle: Text(_recordSubtitle(record),
                maxLines: 2, overflow: TextOverflow.ellipsis),
            onTap: _workspace.busy ? null : () => _edit(record),
            trailing: IconButton(
              icon: const Icon(Icons.delete_outline),
              tooltip: '删除${_recordTitle(record)}',
              onPressed: _workspace.busy ? null : () => _remove(record),
            ),
          ),
        ),
    ];
  }
}

Future<bool> _confirmLocal(
  BuildContext context,
  String title,
  String body,
  String action,
) async =>
    await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text(title),
        content: Text(body),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dialog, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(dialog, true),
              child: Text(action)),
        ],
      ),
    ) ==
    true;

String? _nonemptyString(Object? value) =>
    value is String && value.trim().isNotEmpty ? value : null;

String _recordTitle(LocalWorkspaceRecord record) {
  final area = _LocalArea.of(record.kind);
  final value = record.data[area.titleKey] ?? record.data['name'];
  return value.toString().trim().isEmpty || value == null
      ? '未命名${area.label}'
      : value.toString();
}

String _recordSubtitle(LocalWorkspaceRecord record) {
  final data = record.data;
  final fields = switch (_LocalArea.of(record.kind)) {
    _LocalArea.customer => [data['contact'], data['phone']],
    _LocalArea.product => [
        data['sku'],
        if (data['unit_price'] != null) '单价 ${data['unit_price']}'
      ],
    _LocalArea.order => [
        data['customer'],
        if (data['items'] case final List items) '${items.length} 项商品'
      ],
  };
  return fields
      .whereType<String>()
      .where((field) => field.isNotEmpty)
      .join(' · ');
}

class _LocalRecordForm extends StatefulWidget {
  const _LocalRecordForm({
    required this.area,
    required this.record,
    required this.records,
    required this.onSave,
  });

  final _LocalArea area;
  final LocalWorkspaceRecord? record;
  final List<LocalWorkspaceRecord> records;
  final Future<void> Function(Map<String, Object?> data) onSave;

  @override
  State<_LocalRecordForm> createState() => _LocalRecordFormState();
}

class _LocalRecordFormState extends State<_LocalRecordForm> {
  static const _price =
      NativeFormField('unit_price', '单价', number: true, minimum: 0);
  static const _quantity =
      NativeFormField('quantity', '数量', number: true, required: true);
  static const _notes = NativeFormField('notes', '备注');
  final _form = GlobalKey<FormState>();
  late final List<NativeFormField> _fields;
  late final Map<String, TextEditingController> _inputs;
  late final Map<String, Object?> _initial;
  final List<_LocalDraftLine> _lines = [];
  String? _customerId;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _initial = widget.record?.data ?? {};
    _fields = switch (widget.area) {
      _LocalArea.customer => const [
          NativeFormField('name', '客户名称', required: true),
          NativeFormField('contact', '联系人'),
          NativeFormField('phone', '电话'),
          _notes,
        ],
      _LocalArea.product => const [
          NativeFormField('name', '产品名称', required: true),
          NativeFormField('sku', '产品编号'),
          _price,
          _notes,
        ],
      _LocalArea.order => const [
          NativeFormField('title', '草稿名称', required: true),
          NativeFormField('customer', '客户名称'),
          _notes,
        ],
    };
    _inputs = {
      for (final field in _fields)
        field.key: TextEditingController(text: '${_initial[field.key] ?? ''}'),
    };
    if (widget.area == _LocalArea.order) {
      _customerId = _nonemptyString(_initial['customer_id']);
      if (_initial['items'] case final List items) {
        _lines.addAll(
            items.whereType<Map<String, Object?>>().map(_LocalDraftLine.new));
      }
    }
  }

  @override
  void dispose() {
    for (final controller in _inputs.values) {
      controller.dispose();
    }
    for (final line in _lines) {
      line.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    final form = _form.currentState;
    if (_saving || form == null) return;
    final invalid = form.validateGranularly();
    if (invalid.isNotEmpty) {
      final field = invalid.first;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (field.mounted) {
          unawaited(Scrollable.ensureVisible(field.context, alignment: 0.25));
        }
      });
      return;
    }
    FocusScope.of(context).unfocus();
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.onSave({
        ..._initial,
        for (final field in _fields)
          field.key: field.parse(_inputs[field.key]!.text),
        if (widget.area == _LocalArea.order) ...{
          'status': 'draft',
          'customer_id': _customerId ?? '',
          'items': [
            for (final line in _lines)
              {
                ...line.initial,
                'product_id': line.productId,
                'product_name': line.productName,
                'quantity': _quantity.parse(line.quantity.text),
                'unit_price': _price.parse(line.price.text),
              },
          ],
        },
      });
      if (mounted) Navigator.of(context).pop();
    } catch (error) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error =
              error is FormatException ? error.message : '本机保存失败，请重试。';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return PopScope(
      canPop: !_saving,
      child: Scaffold(
        backgroundColor: colors.page,
        body: SafeArea(
          child: Column(
            children: [
              WeTopBar(
                title:
                    '${widget.record == null ? '新建' : '编辑'}${widget.area.label}',
                showBack: true,
                onBack: () => Navigator.maybePop(context),
              ),
              Expanded(
                child: Form(
                  key: _form,
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    keyboardDismissBehavior:
                        ScrollViewKeyboardDismissBehavior.onDrag,
                    children: [
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          for (final field in _fields)
                            if (field.key == 'customer')
                              _recordPicker(
                                kind: _LocalArea.customer,
                                label: '选择客户',
                                id: _customerId,
                                savedName: _inputs['customer']!.text,
                                onSelected: (id, customer) {
                                  _customerId = id;
                                  _inputs['customer']!.text = customer == null
                                      ? ''
                                      : _recordTitle(customer);
                                },
                              )
                            else
                              _textField(
                                controller: _inputs[field.key]!,
                                field: field,
                              ),
                          if (widget.area == _LocalArea.order) ...[
                            Text('商品明细',
                                style: Theme.of(context).textTheme.titleMedium),
                            for (var index = 0; index < _lines.length; index++)
                              _lineEditor(index, _lines[index]),
                            if (widget.records
                                .any((record) => record.kind == 'product'))
                              OutlinedButton.icon(
                                onPressed: _saving
                                    ? null
                                    : () => setState(
                                        () => _lines.add(_LocalDraftLine({}))),
                                icon: const Icon(Icons.add),
                                label: const Text('添加商品'),
                              )
                            else if (_lines.isEmpty)
                              const Padding(
                                padding: EdgeInsets.only(top: 8),
                                child: Text('可先保存草稿，添加产品后再补商品明细。'),
                              ),
                          ],
                        ],
                      ),
                    ],
                  ),
                ),
              ),
              Material(
                color: colors.surface,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (_error != null)
                        Semantics(liveRegion: true, child: Text(_error!)),
                      FilledButton(
                        style: FilledButton.styleFrom(
                            minimumSize: const Size(0, 48)),
                        onPressed: _saving ? null : _save,
                        child: Text(_saving ? '保存中…' : '保存'),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _recordPicker({
    required _LocalArea kind,
    required String label,
    required String? id,
    required String savedName,
    required void Function(String? id, LocalWorkspaceRecord? record) onSelected,
    bool requiredSelection = false,
  }) {
    final choices = {
      for (final record in widget.records)
        if (record.kind == kind.name) record.id: record,
    };
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: DropdownButtonFormField<String>(
        initialValue: id ?? '',
        isExpanded: true,
        decoration: InputDecoration(labelText: label),
        items: [
          DropdownMenuItem(
              value: '', child: Text(requiredSelection ? '请选择产品' : '未指定')),
          if (id != null && !choices.containsKey(id))
            DropdownMenuItem(
                value: id, child: Text(savedName.isEmpty ? '原记录' : savedName)),
          for (final entry in choices.entries)
            DropdownMenuItem(
              value: entry.key,
              child: Text(_recordTitle(entry.value),
                  maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
        ],
        validator: requiredSelection
            ? (value) => value == null || value.isEmpty ? '请选择产品' : null
            : null,
        onChanged: _saving
            ? null
            : (value) {
                final next = _nonemptyString(value);
                onSelected(next, choices[next]);
              },
      ),
    );
  }

  Widget _textField({
    required NativeFormField field,
    required TextEditingController controller,
    String? Function(String?)? validator,
  }) =>
      Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: TextFormField(
          controller: controller,
          enabled: !_saving,
          maxLines: field.key == 'notes' ? 3 : 1,
          keyboardType: field.number
              ? const TextInputType.numberWithOptions(decimal: true)
              : field.key == 'phone'
                  ? TextInputType.phone
                  : TextInputType.text,
          decoration: InputDecoration(labelText: field.label),
          validator: validator ?? field.validate,
        ),
      );

  Widget _lineEditor(int index, _LocalDraftLine line) => Card(
        key: ObjectKey(line),
        margin: const EdgeInsets.symmetric(vertical: 6),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(child: Text('商品 ${index + 1}')),
                  IconButton(
                    icon: const Icon(Icons.remove_circle_outline),
                    tooltip: '移除商品 ${index + 1}',
                    onPressed: _saving
                        ? null
                        : () {
                            setState(() => _lines.remove(line));
                            WidgetsBinding.instance
                                .addPostFrameCallback((_) => line.dispose());
                          },
                  ),
                ],
              ),
              _recordPicker(
                kind: _LocalArea.product,
                label: '选择产品',
                id: line.productId,
                savedName: line.productName,
                requiredSelection: true,
                onSelected: (id, product) {
                  line.productId = id;
                  line.productName =
                      product == null ? '' : _recordTitle(product);
                  line.price.text = '${product?.data['unit_price'] ?? ''}';
                },
              ),
              _textField(
                controller: line.quantity,
                field: _quantity,
                validator: (value) =>
                    _quantity.validate(value) ??
                    ((num.tryParse(value!.trim()) ?? 0) <= 0
                        ? '数量必须大于 0'
                        : null),
              ),
              _textField(controller: line.price, field: _price),
            ],
          ),
        ),
      );
}

class _LocalDraftLine {
  _LocalDraftLine(this.initial)
      : productId = _nonemptyString(initial['product_id']),
        productName = _nonemptyString(initial['product_name']) ?? '',
        quantity = TextEditingController(text: '${initial['quantity'] ?? '1'}'),
        price = TextEditingController(text: '${initial['unit_price'] ?? ''}');

  final Map<String, Object?> initial;
  String? productId;
  String productName;
  final TextEditingController quantity, price;

  void dispose() {
    quantity.dispose();
    price.dispose();
  }
}

class _LocalWorkspacePairing extends StatefulWidget {
  const _LocalWorkspacePairing({required this.workspace});

  final LocalWorkspaceController workspace;

  @override
  State<_LocalWorkspacePairing> createState() => _LocalWorkspacePairingState();
}

class _LocalWorkspacePairingState extends State<_LocalWorkspacePairing> {
  final _code = TextEditingController();
  LocalWorkspaceOrigin? _origin;
  bool _binding = false, _showPaste = false;
  String? _error;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _scan() async {
    final code = await Navigator.of(context).push<String>(
      MaterialPageRoute(
          builder: (_) => const ScanQrScreen(returnRawValue: true)),
    );
    if (mounted && code != null) await _bind(code);
  }

  Future<void> _bind(String raw) async {
    final origin = _origin;
    if (_binding || origin == null || raw.trim().isEmpty) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _binding = true;
      _error = null;
    });
    try {
      await widget.workspace.bind(raw.trim(), origin: origin);
      if (mounted) Navigator.of(context).pop(true);
    } on FormatException {
      if (mounted) setState(() => _error = '请使用电脑端本地工作区生成的配对二维码。');
    } catch (_) {
      if (mounted) {
        setState(() => _error = '绑定失败。请确认手机和电脑在同一网络，并在电脑端刷新配对二维码。');
      }
    } finally {
      if (mounted) {
        _code.clear();
        setState(() => _binding = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return PopScope(
      canPop: !_binding,
      child: Scaffold(
        backgroundColor: colors.page,
        body: SafeArea(
          child: Column(
            children: [
              const WeTopBar(title: '绑定电脑', showBack: true),
              if (_binding) const LinearProgressIndicator(),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    Text('选择首次同步的数据来源',
                        style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 12),
                    _source(
                      LocalWorkspaceOrigin.desktop,
                      '以电脑为准',
                      '手机使用电脑上的记录，手机原有记录保留在本机归档。',
                    ),
                    _source(
                      LocalWorkspaceOrigin.mobile,
                      '以手机为准',
                      '使用这部手机的记录建立两端的共同工作台。',
                    ),
                    const SizedBox(height: 12),
                    const Text('请将手机和电脑连到同一网络，再打开电脑端「本地工作区」的配对二维码。'),
                    const SizedBox(height: 16),
                    FilledButton.icon(
                      style: FilledButton.styleFrom(
                          minimumSize: const Size(0, 48)),
                      onPressed: _binding || _origin == null ? null : _scan,
                      icon: const Icon(Icons.qr_code_scanner),
                      label: const Text('扫描配对二维码'),
                    ),
                    TextButton(
                      onPressed: _binding
                          ? null
                          : () => setState(() => _showPaste = !_showPaste),
                      child: Text(_showPaste ? '收起配对内容输入框' : '粘贴二维码内容'),
                    ),
                    if (_showPaste) ...[
                      TextField(
                        controller: _code,
                        enabled: !_binding,
                        obscureText: true,
                        autocorrect: false,
                        enableSuggestions: false,
                        decoration: const InputDecoration(labelText: '二维码内容'),
                        onChanged: (_) => setState(() {}),
                      ),
                      const SizedBox(height: 8),
                      OutlinedButton(
                        onPressed: _binding ||
                                _origin == null ||
                                _code.text.trim().isEmpty
                            ? null
                            : () => _bind(_code.text),
                        child: const Text('使用配对内容绑定'),
                      ),
                    ],
                    if (_error != null)
                      Semantics(
                          liveRegion: true,
                          child: Text(_error!,
                              style: TextStyle(color: colors.danger))),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _source(LocalWorkspaceOrigin value, String title, String description) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        selected: _origin == value,
        leading: Icon(_origin == value
            ? Icons.radio_button_checked
            : Icons.radio_button_unchecked),
        title: Text(title),
        subtitle: Text(description),
        onTap: _binding ? null : () => setState(() => _origin = value),
      ),
    );
  }
}

class _LocalWorkspaceConflicts extends StatelessWidget {
  const _LocalWorkspaceConflicts({required this.workspace});

  final LocalWorkspaceController workspace;

  Future<void> _resolve(
    BuildContext context,
    LocalWorkspaceConflict conflict,
    bool keepLocal,
  ) async {
    try {
      await workspace.resolveConflict(conflict.opId, keepLocal: keepLocal);
    } catch (_) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('未能处理这条冲突，请重试。')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) => _LocalSecondaryScreen(
        title: '同步冲突',
        child: AnimatedBuilder(
          animation: workspace,
          builder: (context, _) => ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (workspace.conflicts.isEmpty)
                const Center(child: Text('没有待处理的冲突')),
              for (final conflict in workspace.conflicts)
                Card(
                  margin: const EdgeInsets.only(bottom: 12),
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(_recordTitle(conflict.local),
                            style: Theme.of(context).textTheme.titleMedium),
                        _recordDetails('本机改动', conflict.local),
                        _recordDetails('电脑版本', conflict.current),
                        OverflowBar(
                          alignment: MainAxisAlignment.end,
                          spacing: 8,
                          children: [
                            OutlinedButton(
                              onPressed: workspace.busy
                                  ? null
                                  : () => _resolve(context, conflict, false),
                              child: const Text('使用电脑版本'),
                            ),
                            FilledButton(
                              onPressed: workspace.busy
                                  ? null
                                  : () => _resolve(context, conflict, true),
                              child: const Text('保留本机改动'),
                            ),
                          ],
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

class _LocalWorkspaceArchives extends StatelessWidget {
  const _LocalWorkspaceArchives({required this.archives});

  final List<LocalWorkspaceArchive> archives;

  @override
  Widget build(BuildContext context) => _LocalSecondaryScreen(
        title: '本机归档',
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            for (final archive in archives)
              Card(
                margin: const EdgeInsets.only(bottom: 12),
                child: ExpansionTile(
                  key: ValueKey(archive.id),
                  title: Text(MaterialLocalizations.of(context)
                      .formatFullDate(archive.createdAt.toLocal())),
                  subtitle: Text('${archive.records.length} 条记录'),
                  children: [
                    for (final record in archive.records)
                      _recordDetails(_recordTitle(record), record),
                  ],
                ),
              ),
          ],
        ),
      );
}

class _LocalSecondaryScreen extends StatelessWidget {
  const _LocalSecondaryScreen({required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: AppTheme.colors(context).page,
        body: SafeArea(
          child: Column(
            children: [
              WeTopBar(title: title, showBack: true),
              Expanded(child: child),
            ],
          ),
        ),
      );
}

Widget _recordDetails(String label, LocalWorkspaceRecord? record) {
  const fields = {
    'name': '名称',
    'title': '名称',
    'customer': '客户',
    'contact': '联系人',
    'phone': '电话',
    'sku': '产品编号',
    'product_name': '产品',
    'unit_price': '单价',
    'quantity': '数量',
    'notes': '备注',
  };
  String summary(Map data) => [
        for (final field in fields.entries)
          if (data[field.key] != null &&
              data[field.key].toString().trim().isNotEmpty)
            '${field.value} ${data[field.key]}',
      ].join('\n');
  var detail =
      record == null || record.deleted ? '此记录不存在或已删除' : summary(record.data);
  if (record?.data['items'] case final List items
      when record?.deleted == false) {
    detail += [
      for (final item in items.whereType<Map>()) '\n${summary(item)}',
    ].join('\n');
  }
  return ExpansionTile(
    tilePadding: const EdgeInsets.symmetric(horizontal: 16),
    title: Text(label),
    childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
    expandedAlignment: Alignment.centerLeft,
    children: [SelectableText(detail.isEmpty ? '暂无记录详情' : detail)],
  );
}

part of 'native_orders_screen.dart';

class NativeOrderFormScreen extends StatefulWidget {
  const NativeOrderFormScreen(
      {super.key,
      required this.repository,
      required this.apiBase,
      this.session});
  final MobileRepository repository;
  final String apiBase;
  final NativeWorkspaceSession? session;
  @override
  State<NativeOrderFormScreen> createState() => _OrderFormState();
}

class _OrderFormState extends State<NativeOrderFormScreen> {
  late final NativeWorkspaceSession _session;
  final _form = GlobalKey<FormState>();
  final _contact = TextEditingController();
  final _date = TextEditingController(
      text: DateTime.now().toIso8601String().split('T').first);
  List<Map<String, Object?>> _templates = [], _units = [];
  final _lines = <_OrderLine>[];
  String _unit = '', _template = '', _number = '';
  int _optionsTicket = 0;
  String? _error;
  Map<String, Object?>? _result;
  bool _loading = true, _busy = false, _optionsReady = false;
  @override
  void initState() {
    super.initState();
    _session = widget.session ??
        NativeWorkspaceSession(
          widget.repository.client,
          activeModId: widget.apiBase.startsWith('api/mod/')
              ? widget.apiBase.split('/').last
              : '',
        );
    _session.addListener(_invalidate);
    unawaited(_loadOptions());
  }

  void _invalidate() {
    if (mounted) {
      setState(() {
        ++_optionsTicket;
        _unit = '';
        _template = '';
        _units = [];
        _templates = [];
        _result = null;
        _contact.clear();
        _number = '';
        for (final line in _lines) {
          line.dispose();
        }
        _lines.clear();
      });
    }
  }

  @override
  void dispose() {
    _session.removeListener(_invalidate);
    if (widget.session == null) _session.dispose();
    _date.dispose();
    _contact.dispose();
    for (final line in _lines) {
      line.dispose();
    }
    super.dispose();
  }

  Future<void> _loadOptions() async {
    if (!_session.active) return;
    final ticket = ++_optionsTicket;
    setState(() {
      _loading = true;
      _optionsReady = false;
      _error = null;
    });
    try {
      final values = await Future.wait([
        _session.request('api/mobile/v1/workspace/templates'),
        _session.request('${widget.apiBase}/purchase_units'),
        if (_number.isEmpty)
          _session.request('${widget.apiBase}/orders/next_number',
              query: {'suffix': 'A'})
      ]);
      if (!mounted || !_session.active || ticket != _optionsTicket) {
        return;
      }
      final templates = (values[0]['templates'] as List? ?? [])
          .whereType<Map>()
          .map((v) => Map<String, Object?>.from(v))
          .where((t) =>
              t['virtual'] != true &&
              t['category'] == 'excel' &&
              (t['business_scope'] == 'orders' ||
                  (t['business_scope'] == null && t['template_type'] == '发货单')))
          .toList();
      final units = _records(values[1]);
      setState(() {
        _templates = templates;
        _units = units;
        if (!_templates.any((row) => '${row['id']}' == _template)) {
          _template = '';
        }
        final selectedUnit = _units
            .where((row) => '${row['unit_name'] ?? row['name'] ?? ''}' == _unit)
            .firstOrNull;
        if (selectedUnit == null) _unit = '';
        _contact.text = '${selectedUnit?['contact_person'] ?? ''}';
        if (values.length > 2) {
          _number = '${_object(values[2]['data'])['order_number'] ?? ''}';
        }
      });
      if (_number.isEmpty) throw StateError('未取得订单编号，请刷新后重试');
      setState(() {
        _optionsReady = true;
      });
    } catch (error) {
      if (mounted && _session.active && ticket == _optionsTicket) {
        setState(() {
          _error = mobileErrorText(error);
        });
      }
    } finally {
      if (mounted && ticket == _optionsTicket) {
        setState(() {
          _loading = false;
        });
      }
    }
  }

  Future<void> _pickProduct() async {
    final products =
        await Navigator.of(context).push<List<Map<String, Object?>>>(
      MaterialPageRoute(
        builder: (_) => _ProductPicker(
          session: _session,
          apiBase: widget.apiBase,
          unit: _unit,
        ),
      ),
    );
    if (products != null && mounted && _session.active) {
      setState(() => _lines.addAll(products.map(_OrderLine.new)));
    }
  }

  Future<void> _pickDate() async {
    final date = await showDatePicker(
      context: context,
      initialDate: DateTime.tryParse(_date.text) ?? DateTime.now(),
      firstDate: DateTime(1900),
      lastDate: DateTime(2100),
    );
    if (date != null && mounted && _session.active && _result == null) {
      _date.text = date.toIso8601String().split('T').first;
    }
  }

  void _startNext() {
    if (_busy || !_session.active || _result == null) return;
    final previous = _lines.toList();
    setState(() {
      _result = null;
      _number = '';
      _lines.clear();
      _date.text = DateTime.now().toIso8601String().split('T').first;
    });
    for (final line in previous) {
      line.dispose();
    }
    unawaited(_loadOptions());
  }

  Future<void> _manageCatalog(String resource) async {
    await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => NativeCatalogScreen(
            repository: widget.repository,
            resource: resource,
            apiBase: widget.apiBase,
            title: resource == 'customers' ? '客户' : '产品')));
    if (mounted && _session.active) await _loadOptions();
  }

  Future<void> _generate() async {
    if (_busy || _loading || !_optionsReady || !_session.active) {
      return;
    }
    final invalid = _form.currentState?.validateGranularly();
    if (invalid == null) return;
    if (invalid.isNotEmpty) {
      await Scrollable.ensureVisible(
        invalid.first.context,
        alignment: 0.25,
        duration: AppTheme.motionDuration(context),
      );
      return;
    }
    if (_lines.isEmpty ||
        _template.isEmpty ||
        _unit.isEmpty ||
        _number.isEmpty) {
      _showIssue('请至少添加一个产品');
      return;
    }
    if (_lines
        .any((line) => line.name.trim().isEmpty || line.model.trim().isEmpty)) {
      _showIssue('产品名称和型号不能为空，请先完善产品资料');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await _session.request(
          '${widget.apiBase}/shipment/generate',
          method: 'POST',
          body: {
            'unit_name': _unit,
            'date': _date.text,
            'order_number': _number,
            'template_id': _template,
            'products': _lines.map((line) => line.payload).toList(),
          });
      if (mounted && _session.active) {
        setState(() {
          _result = result;
        });
      }
    } catch (error) {
      if (mounted && _session.active) {
        _showIssue('${mobileErrorText(error)}。再次提交会沿用当前单号，请先核对出货记录。');
      }
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
        });
      }
    }
  }

  void _showIssue(String message) {
    setState(() => _error = message);
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _download() async {
    final name = '${_result?['doc_name'] ?? ''}';
    if (name.isEmpty || _busy) return;
    setState(() {
      _busy = true;
    });
    try {
      final bytes = await _session.download(
          '${widget.apiBase}/shipment/download/${Uri.encodeComponent(name)}');
      await shareWorkspaceFile(name, bytes,
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

  Widget _details() => WorkspacePanel(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const WeSectionCaption('客户与单据'),
            Text(
                '订单编号：${_number.isNotEmpty ? _number : _loading ? '正在读取…' : '未取得，请刷新'}'),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              key: ValueKey('order-template-$_template'),
              initialValue: _template.isEmpty ? null : _template,
              isExpanded: true,
              decoration: const InputDecoration(
                  border: OutlineInputBorder(), labelText: '发货单模板 *'),
              items: [
                for (final template in _templates)
                  DropdownMenuItem(
                    value: '${template['id']}',
                    child: Text(
                      '${template['name'] ?? template['id']}',
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
              ],
              onChanged: _busy || _loading
                  ? null
                  : (value) {
                      setState(() => _template = value ?? '');
                    },
              validator: (value) =>
                  value == null || value.isEmpty ? '请选择模板' : null,
            ),
            if (!_loading && _optionsReady && _templates.isEmpty)
              const Padding(
                padding: EdgeInsets.only(top: 8),
                child: Text('请在桌面端配置发货单模板，再刷新此页。'),
              ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              key: ValueKey('order-unit-$_unit'),
              initialValue: _unit.isEmpty ? null : _unit,
              isExpanded: true,
              decoration: const InputDecoration(
                  border: OutlineInputBorder(), labelText: '购买单位 *'),
              items: [
                for (final name in _units
                    .map((unit) => '${unit['unit_name'] ?? unit['name'] ?? ''}')
                    .where((name) => name.isNotEmpty)
                    .toSet())
                  DropdownMenuItem(
                    value: name,
                    child: Text(name, overflow: TextOverflow.ellipsis),
                  ),
              ],
              onChanged: _busy || _loading
                  ? null
                  : (value) {
                      setState(() {
                        _unit = value ?? '';
                        final row = _units
                            .where(
                              (unit) =>
                                  '${unit['unit_name'] ?? unit['name']}' ==
                                  _unit,
                            )
                            .firstOrNull;
                        _contact.text = '${row?['contact_person'] ?? ''}';
                      });
                    },
              validator: (value) =>
                  value == null || value.isEmpty ? '请选择购买单位' : null,
            ),
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: TextButton(
                onPressed: _busy ? null : () => _manageCatalog('customers'),
                child: const Text('管理客户'),
              ),
            ),
            if (_contact.text.isNotEmpty) ...[
              Text('联系人 · ${_contact.text}'),
              const SizedBox(height: 12),
            ],
            TextFormField(
              controller: _date,
              enabled: !_busy,
              readOnly: true,
              onTap: _pickDate,
              decoration: const InputDecoration(
                border: OutlineInputBorder(),
                labelText: '发货日期',
                suffixIcon: Icon(Icons.calendar_today_outlined),
              ),
              validator: (value) =>
                  DateTime.tryParse(value ?? '') == null ? '请选择有效日期' : null,
            ),
          ],
        ),
      );

  Widget _lineCard(_OrderLine line) => WorkspacePanel(
        key: ObjectKey(line),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(line.name),
              subtitle: Text('型号 · ${line.model}'),
              trailing: IconButton(
                tooltip: '移除产品',
                onPressed: _busy
                    ? null
                    : () {
                        setState(() => _lines.remove(line));
                        line.dispose();
                      },
                icon: const Icon(Icons.remove_circle_outline),
              ),
            ),
            LayoutBuilder(
              builder: (context, constraints) {
                final scale = MediaQuery.textScalerOf(context).scale(16);
                final width = constraints.maxWidth;
                return Wrap(
                  spacing: 10,
                  runSpacing: 12,
                  children: [
                    for (final entry in line.fields.entries)
                      SizedBox(
                        width: width >= 250 && scale <= 22
                            ? (width - 10) / 2
                            : width,
                        child: TextFormField(
                          controller: entry.value,
                          enabled: !_busy,
                          keyboardType: const TextInputType.numberWithOptions(
                              decimal: true),
                          decoration: InputDecoration(
                              border: const OutlineInputBorder(),
                              labelText: _lineLabels[entry.key]),
                          validator: (value) {
                            final number = num.tryParse(value ?? '');
                            if (number == null ||
                                !number.isFinite ||
                                number < 0) {
                              return '请输入非负数字';
                            }
                            return entry.key == 'quantity_tins' &&
                                    number != number.round()
                                ? '件数须为整数'
                                : null;
                          },
                          onChanged: (_) =>
                              setState(() => line.recalculate(entry.key)),
                        ),
                      ),
                  ],
                );
              },
            ),
            const SizedBox(height: 12),
            WorkspaceBadge(label: '金额：¥${line.amount.toStringAsFixed(2)}'),
          ],
        ),
      );

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = AppTheme.colors(context);
    final canEdit = _session.active && _result == null;
    final amount = _lines.fold<num>(0, (total, line) => total + line.amount);
    return WorkspaceScaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: !canEdit,
        child: Column(
          children: [
            WeTopBar(
              title: '新建发货单',
              showBack: true,
              onBack: () => Navigator.maybePop(context),
              actions: [
                IconButton(
                  tooltip: '刷新选项',
                  onPressed: _busy || !canEdit ? null : _loadOptions,
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
                child: WorkspaceTransition(
                  child: _result == null
                      ? SingleChildScrollView(
                          key: const ValueKey('order-form'),
                          padding: const EdgeInsets.all(16),
                          child: Form(
                            key: _form,
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                if (_error != null)
                                  Padding(
                                    padding: const EdgeInsets.only(bottom: 12),
                                    child: Text(_error!,
                                        style: TextStyle(
                                          color: theme.colorScheme.error,
                                        )),
                                  ),
                                _details(),
                                const SizedBox(height: 14),
                                WorkspacePanel(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text('产品明细',
                                          style: theme.textTheme.titleMedium),
                                      const SizedBox(height: 8),
                                      Wrap(
                                        spacing: 8,
                                        runSpacing: 8,
                                        children: [
                                          FilledButton.tonalIcon(
                                            onPressed:
                                                _busy ? null : _pickProduct,
                                            icon: const Icon(Icons.add),
                                            label: const Text('选择产品'),
                                          ),
                                          TextButton(
                                            onPressed: _busy
                                                ? null
                                                : () =>
                                                    _manageCatalog('products'),
                                            child: const Text('管理产品库'),
                                          ),
                                        ],
                                      ),
                                    ],
                                  ),
                                ),
                                for (final line in _lines)
                                  Padding(
                                    key: ObjectKey(line),
                                    padding: const EdgeInsets.only(top: 10),
                                    child: _lineCard(line),
                                  ),
                              ],
                            ),
                          ),
                        )
                      : ListView(
                          key: const ValueKey('order-result'),
                          padding: const EdgeInsets.all(16),
                          children: [
                            WorkspacePanel(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Semantics(
                                    liveRegion: true,
                                    child: WorkspaceBadge(
                                      label: _result!['duplicate'] == true
                                          ? '该单号已生成，未重复创建'
                                          : '发货单已生成',
                                      color: colors.success,
                                    ),
                                  ),
                                  const SizedBox(height: 12),
                                  Text('${_result!['doc_name'] ?? _number}',
                                      style: theme.textTheme.titleLarge),
                                  if (_error != null) Text(_error!),
                                  const SizedBox(height: 16),
                                  Wrap(
                                    spacing: 8,
                                    runSpacing: 8,
                                    children: [
                                      FilledButton.icon(
                                        onPressed: _busy ||
                                                '${_result!['doc_name'] ?? ''}'
                                                    .isEmpty
                                            ? null
                                            : _download,
                                        icon: const Icon(Icons.ios_share),
                                        label: const Text('保存或分享发货单'),
                                      ),
                                      OutlinedButton(
                                        onPressed: _busy ? null : _startNext,
                                        child: const Text('继续开单'),
                                      ),
                                    ],
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                ),
              ),
            if (canEdit)
              Material(
                color: colors.surface,
                elevation: 2,
                child: SafeArea(
                  top: false,
                  minimum: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Wrap(
                        spacing: 8,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          Text('${_lines.length} 项商品 · 合计'),
                          WorkspaceTransition(
                            child: Text(
                              '¥${amount.toStringAsFixed(2)}',
                              key: ValueKey(amount.toStringAsFixed(2)),
                              style: theme.textTheme.titleMedium,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 6),
                      FilledButton(
                        onPressed: _busy ||
                                _loading ||
                                !_optionsReady ||
                                _number.isEmpty
                            ? null
                            : _generate,
                        child: Text(_busy ? '正在处理…' : '生成发货单'),
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
}

const _lineLabels = {
  'quantity_tins': '数量／件',
  'tin_spec': '规格／KG',
  'quantity_kg': '数量／KG',
  'unit_price': '单价／元'
};

class _OrderLine {
  _OrderLine(Map<String, Object?> product)
      : name = '${product['name'] ?? ''}',
        model = '${product['model_number'] ?? ''}',
        fields = {
          'quantity_tins': TextEditingController(text: '1'),
          'tin_spec': TextEditingController(
              text: '${num.tryParse('${product['specification']}') ?? 0}'),
          'quantity_kg': TextEditingController(),
          'unit_price': TextEditingController(text: '${product['price'] ?? 0}')
        } {
    recalculate('tin_spec');
  }
  final String name, model;
  final Map<String, TextEditingController> fields;
  num number(String key) => num.tryParse(fields[key]!.text) ?? 0;
  num get amount => number('quantity_kg') * number('unit_price');
  void recalculate(String key) {
    if (key == 'quantity_tins' || key == 'tin_spec') {
      fields['quantity_kg']!.text =
          '${number('quantity_tins') * number('tin_spec')}';
    }
  }

  Map<String, Object?> get payload => {
        'name': name,
        'model_number': model,
        for (final key in fields.keys) key: number(key),
        'amount': amount
      };
  void dispose() {
    for (final field in fields.values) {
      field.dispose();
    }
  }
}

class _ProductPicker extends StatefulWidget {
  const _ProductPicker(
      {required this.session, required this.apiBase, required this.unit});
  final NativeWorkspaceSession session;
  final String apiBase, unit;
  @override
  State<_ProductPicker> createState() => _ProductPickerState();
}

class _ProductPickerState extends State<_ProductPicker> {
  final _search = TextEditingController();
  List<Map<String, Object?>> _products = [];
  final _selected = <Object, Map<String, Object?>>{};
  bool _loading = true, _more = false;
  int _page = 0, _ticket = 0;
  String _keyword = '';
  String? _error;
  @override
  void initState() {
    super.initState();
    widget.session.addListener(_changed);
    unawaited(_load());
  }

  void _changed() {
    if (mounted) {
      setState(() {
        _products = [];
        _selected.clear();
        ++_ticket;
      });
    }
  }

  @override
  void dispose() {
    widget.session.removeListener(_changed);
    _search.dispose();
    super.dispose();
  }

  Future<void> _load({bool more = false}) async {
    final ticket = ++_ticket, page = more ? _page + 1 : 1;
    final keyword = more ? _keyword : _search.text.trim();
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await widget.session
          .request('${widget.apiBase}/products/list', query: {
        'page': '$page',
        'per_page': '30',
        if (keyword.isNotEmpty) 'keyword': keyword,
        if (widget.unit.isNotEmpty) 'unit': widget.unit
      });
      final rows = _records(result);
      if (mounted && widget.session.active && ticket == _ticket) {
        setState(() {
          _products = [if (more) ..._products, ...rows];
          _page = page;
          _keyword = keyword;
          _more = result['total'] is num
              ? _products.length < (result['total'] as num)
              : rows.length == 30;
        });
      }
    } catch (error) {
      if (mounted && widget.session.active && ticket == _ticket) {
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

  @override
  Widget build(BuildContext context) => WorkspaceScaffold(
        appBar: AppBar(title: const Text('选择产品')),
        backgroundColor: AppTheme.colors(context).page,
        bottomNavigationBar: !widget.session.active
            ? null
            : SafeArea(
                minimum: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                child: FilledButton(
                  onPressed: _selected.isEmpty
                      ? null
                      : () => Navigator.pop(context, _selected.values.toList()),
                  child: Text('添加所选产品（${_selected.length}）'),
                ),
              ),
        body: !widget.session.active
            ? const Center(child: Text('账号或连接已切换'))
            : Column(
                children: [
                  Padding(
                    padding: const EdgeInsets.all(16),
                    child: TextField(
                      controller: _search,
                      textInputAction: TextInputAction.search,
                      decoration: InputDecoration(
                        border: const OutlineInputBorder(),
                        hintText: '搜索名称或型号',
                        prefixIcon: const Icon(Icons.search),
                        suffixIcon: IconButton(
                          tooltip: '搜索产品',
                          icon: const Icon(Icons.arrow_forward),
                          onPressed: _loading ? null : _load,
                        ),
                      ),
                      onSubmitted: (_) => _load(),
                    ),
                  ),
                  if (_loading) const LinearProgressIndicator(minHeight: 2),
                  if (_error != null)
                    TextButton(onPressed: _load, child: Text('$_error · 重试')),
                  if (!_loading && _error == null && _products.isEmpty)
                    const Text('没有匹配的产品'),
                  Expanded(
                    child: ListView.separated(
                      padding: const EdgeInsets.symmetric(horizontal: 16),
                      itemCount: _products.length + (_more ? 1 : 0),
                      separatorBuilder: (_, index) => const SizedBox(height: 8),
                      itemBuilder: (context, index) {
                        if (index == _products.length) {
                          return TextButton(
                            onPressed:
                                _loading ? null : () => _load(more: true),
                            child: const Text('加载更多'),
                          );
                        }
                        final product = _products[index];
                        final key = product['id'] ??
                            (product['name'], product['model_number']);
                        return WorkspacePanel(
                          key: ValueKey(key),
                          padding: EdgeInsets.zero,
                          child: CheckboxListTile(
                            title: Text('${product['name'] ?? ''}'),
                            subtitle: Text(
                                '${product['model_number'] ?? ''} · ¥${product['price'] ?? '—'}'),
                            value: _selected.containsKey(key),
                            onChanged: _loading || _error != null
                                ? null
                                : (checked) {
                                    setState(() {
                                      if (checked == true) {
                                        _selected[key] = product;
                                      } else {
                                        _selected.remove(key);
                                      }
                                    });
                                  },
                          ),
                        );
                      },
                    ),
                  ),
                ],
              ),
      );
}

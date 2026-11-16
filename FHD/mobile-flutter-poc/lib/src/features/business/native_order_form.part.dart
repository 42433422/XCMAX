part of 'native_orders_screen.dart';

class _OrderForm extends StatefulWidget {
  const _OrderForm(
      {required this.repository, required this.apiBase, required this.session});
  final MobileRepository repository;
  final String apiBase;
  final NativeWorkspaceSession session;
  @override
  State<_OrderForm> createState() => _OrderFormState();
}

class _OrderFormState extends State<_OrderForm> {
  final _form = GlobalKey<FormState>();
  final _contact = TextEditingController();
  final _date = TextEditingController(
      text: DateTime.now().toIso8601String().split('T').first);
  List<Map<String, Object?>> _templates = [], _units = [];
  final _lines = <_OrderLine>[];
  String _unit = '', _template = '', _number = '';
  String? _error;
  Map<String, Object?>? _result;
  bool _loading = true, _busy = false, _optionsReady = false;
  @override
  void initState() {
    super.initState();
    widget.session.addListener(_invalidate);
    unawaited(_loadOptions());
  }

  void _invalidate() {
    if (mounted) {
      setState(() {
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
    widget.session.removeListener(_invalidate);
    _date.dispose();
    _contact.dispose();
    for (final line in _lines) {
      line.dispose();
    }
    super.dispose();
  }

  Future<void> _loadOptions() async {
    if (!widget.session.active) return;
    setState(() {
      _loading = true;
      _optionsReady = false;
      _error = null;
    });
    try {
      final values = await Future.wait([
        widget.session.request('api/mobile/v1/workspace/templates'),
        widget.session.request('${widget.apiBase}/purchase_units'),
        if (_number.isEmpty)
          widget.session.request('${widget.apiBase}/orders/next_number',
              query: {'suffix': 'A'})
      ]);
      if (!mounted || !widget.session.active) return;
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
        if (values.length > 2) {
          _number = '${_object(values[2]['data'])['order_number'] ?? ''}';
        }
      });
      if (_number.isEmpty) throw StateError('未取得订单编号，请刷新后重试');
      setState(() {
        _optionsReady = true;
      });
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

  Future<void> _pickProduct() async {
    final product = await Navigator.of(context).push<Map<String, Object?>>(
        MaterialPageRoute(
            builder: (_) => _ProductPicker(
                session: widget.session,
                apiBase: widget.apiBase,
                unit: _unit)));
    if (product != null && mounted && widget.session.active) {
      setState(() {
        _lines.add(_OrderLine(product));
      });
    }
  }

  Future<void> _manageCatalog(String resource) async {
    await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => NativeCatalogScreen(
            repository: widget.repository,
            resource: resource,
            apiBase: widget.apiBase,
            title: resource == 'customers' ? '客户' : '产品')));
    if (mounted && widget.session.active) await _loadOptions();
  }

  Future<void> _generate() async {
    if (_busy ||
        _loading ||
        !_optionsReady ||
        !widget.session.active ||
        !_form.currentState!.validate()) {
      return;
    }
    if (_lines.isEmpty ||
        _template.isEmpty ||
        _unit.isEmpty ||
        _number.isEmpty) {
      setState(() {
        _error = '请选择模板、购买单位，并至少添加一个产品';
      });
      return;
    }
    if (_lines
        .any((line) => line.name.trim().isEmpty || line.model.trim().isEmpty)) {
      setState(() {
        _error = '产品名称和型号不能为空，请先完善产品资料';
      });
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await widget.session.request(
          '${widget.apiBase}/shipment/generate',
          method: 'POST',
          body: {
            'unit_name': _unit,
            'date': _date.text,
            'order_number': _number,
            'template_id': _template,
            'products': _lines.map((line) => line.payload).toList(),
          });
      if (mounted && widget.session.active) {
        setState(() {
          _result = result;
        });
      }
    } catch (error) {
      if (mounted && widget.session.active) {
        setState(() {
          _error = '${mobileErrorText(error)}。再次提交会沿用当前单号，请先核对出货记录。';
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

  Future<void> _download() async {
    final name = '${_result?['doc_name'] ?? ''}';
    if (name.isEmpty || _busy) return;
    setState(() {
      _busy = true;
    });
    try {
      final bytes = await widget.session.download(
          '${widget.apiBase}/shipment/download/${Uri.encodeComponent(name)}');
      await shareWorkspaceFile(name, bytes,
          isCurrent: () => mounted && widget.session.active);
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
            title: '新建发货单',
            showBack: true,
            onBack: () => Navigator.maybePop(context),
            actions: [
              IconButton(
                  tooltip: '刷新选项',
                  onPressed:
                      _busy || !widget.session.active ? null : _loadOptions,
                  icon: const Icon(Icons.refresh))
            ]),
        if (!widget.session.active)
          const Expanded(child: Center(child: Text('账号或连接已切换，请返回后重新打开')))
        else
          Expanded(
              child: Form(
                  key: _form,
                  child: ListView(padding: const EdgeInsets.all(20), children: [
                    if (_loading || _busy) const LinearProgressIndicator(),
                    if (_error != null)
                      Padding(
                          padding: const EdgeInsets.symmetric(vertical: 12),
                          child: Text(_error!)),
                    if (_result != null)
                      Card(
                          child: Padding(
                              padding: const EdgeInsets.all(16),
                              child: Column(children: [
                                Text(_result!['duplicate'] == true
                                    ? '该单号已生成，未重复创建'
                                    : '发货单已生成'),
                                Text('${_result!['doc_name'] ?? ''}'),
                                FilledButton.icon(
                                    onPressed: _busy ||
                                            '${_result!['doc_name'] ?? ''}'
                                                .isEmpty
                                        ? null
                                        : _download,
                                    icon: const Icon(Icons.download),
                                    label: const Text('保存或分享发货单')),
                              ]))),
                    const WeSectionCaption('基础信息'),
                    DropdownButtonFormField<String>(
                        initialValue: _template.isEmpty ? null : _template,
                        isExpanded: true,
                        decoration: const InputDecoration(labelText: '发货单模板 *'),
                        items: [
                          for (final t in _templates)
                            DropdownMenuItem(
                                value: '${t['id']}',
                                child: Text('${t['name'] ?? t['id']}',
                                    overflow: TextOverflow.ellipsis))
                        ],
                        onChanged: _busy || _result != null
                            ? null
                            : (v) => setState(() {
                                  _template = v ?? '';
                                }),
                        validator: (v) =>
                            v == null || v.isEmpty ? '请选择模板' : null),
                    if (!_loading && _optionsReady && _templates.isEmpty)
                      const Padding(
                          padding: EdgeInsets.symmetric(vertical: 8),
                          child: Text('暂无可用发货单模板，请先配置当前工作区的模板后刷新。')),
                    const SizedBox(height: 16),
                    DropdownButtonFormField<String>(
                        initialValue: _unit.isEmpty ? null : _unit,
                        isExpanded: true,
                        decoration: const InputDecoration(labelText: '购买单位 *'),
                        items: [
                          for (final name in _units
                              .map(
                                  (u) => '${u['unit_name'] ?? u['name'] ?? ''}')
                              .where((n) => n.isNotEmpty)
                              .toSet())
                            DropdownMenuItem(
                                value: name,
                                child:
                                    Text(name, overflow: TextOverflow.ellipsis))
                        ],
                        onChanged: _busy || _result != null
                            ? null
                            : (v) => setState(() {
                                  _unit = v ?? '';
                                  final row = _units
                                      .where((u) =>
                                          '${u['unit_name'] ?? u['name']}' ==
                                          _unit)
                                      .firstOrNull;
                                  _contact.text =
                                      '${row?['contact_person'] ?? ''}';
                                }),
                        validator: (v) =>
                            v == null || v.isEmpty ? '请选择购买单位' : null),
                    TextButton(
                        onPressed:
                            _busy ? null : () => _manageCatalog('customers'),
                        child: const Text('管理客户')),
                    TextFormField(
                        controller: _contact,
                        readOnly: true,
                        decoration: const InputDecoration(labelText: '联系人')),
                    const SizedBox(height: 16),
                    TextFormField(
                        controller: _date,
                        enabled: !_busy && _result == null,
                        decoration:
                            const InputDecoration(labelText: '日期（YYYY-MM-DD）'),
                        validator: (v) => DateTime.tryParse(v ?? '') == null
                            ? '请输入有效日期'
                            : null),
                    const SizedBox(height: 16),
                    Text(
                        '订单编号：${_number.isEmpty ? (_loading ? '正在获取…' : '未取得，请刷新') : _number}'),
                    const WeSectionCaption('产品明细'),
                    Wrap(spacing: 8, children: [
                      OutlinedButton.icon(
                          onPressed:
                              _busy || _result != null ? null : _pickProduct,
                          icon: const Icon(Icons.add),
                          label: const Text('选择产品')),
                      TextButton(
                          onPressed:
                              _busy ? null : () => _manageCatalog('products'),
                          child: const Text('管理产品库'))
                    ]),
                    for (final line in _lines)
                      Card(
                          child: Padding(
                              padding: const EdgeInsets.all(12),
                              child: Column(children: [
                                Row(children: [
                                  Expanded(
                                      child: Text(line.name,
                                          style: Theme.of(context)
                                              .textTheme
                                              .titleMedium)),
                                  IconButton(
                                      tooltip: '移除产品',
                                      onPressed: _busy || _result != null
                                          ? null
                                          : () => setState(() {
                                                _lines.remove(line);
                                                line.dispose();
                                              }),
                                      icon: const Icon(Icons.close))
                                ]),
                                Text('型号：${line.model}'),
                                for (final entry in line.fields.entries)
                                  Padding(
                                      padding: const EdgeInsets.only(top: 12),
                                      child: TextFormField(
                                          controller: entry.value,
                                          enabled: !_busy && _result == null,
                                          keyboardType: const TextInputType
                                              .numberWithOptions(decimal: true),
                                          decoration: InputDecoration(
                                              labelText:
                                                  _lineLabels[entry.key]),
                                          validator: (v) {
                                            final n = num.tryParse(v ?? '');
                                            return n == null ||
                                                    !n.isFinite ||
                                                    n < 0
                                                ? '请输入非负数字'
                                                : entry.key ==
                                                            'quantity_tins' &&
                                                        n != n.round()
                                                    ? '件数须为整数'
                                                    : null;
                                          },
                                          onChanged: (_) => setState(() {
                                                line.recalculate(entry.key);
                                              }))),
                                const SizedBox(height: 12),
                                Text('金额：¥${line.amount.toStringAsFixed(2)}'),
                              ]))),
                    const SizedBox(height: 20),
                    FilledButton(
                        onPressed: _busy ||
                                _loading ||
                                !_optionsReady ||
                                _result != null ||
                                _number.isEmpty
                            ? null
                            : _generate,
                        child: Text(_busy ? '正在处理…' : '生成发货单')),
                  ]))),
      ])));
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
  bool _loading = true, _more = false;
  int _page = 0, _ticket = 0;
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
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await widget.session
          .request('${widget.apiBase}/products/list', query: {
        'page': '$page',
        'per_page': '30',
        if (_search.text.trim().isNotEmpty) 'keyword': _search.text.trim(),
        if (widget.unit.isNotEmpty) 'unit': widget.unit
      });
      final rows = _records(result);
      if (mounted && widget.session.active && ticket == _ticket) {
        setState(() {
          _products = [if (more) ..._products, ...rows];
          _page = page;
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
  Widget build(BuildContext context) => Scaffold(
      appBar: AppBar(title: const Text('选择产品')),
      body: !widget.session.active
          ? const Center(child: Text('账号或连接已切换'))
          : Column(children: [
              Padding(
                  padding: const EdgeInsets.all(16),
                  child: TextField(
                      controller: _search,
                      decoration: const InputDecoration(
                          hintText: '搜索名称或型号', prefixIcon: Icon(Icons.search)),
                      onSubmitted: (_) => _load())),
              if (_loading) const LinearProgressIndicator(),
              if (_error != null)
                TextButton(onPressed: _load, child: Text('$_error · 重试')),
              Expanded(
                  child: ListView(children: [
                for (final product in _products)
                  ListTile(
                      title: Text('${product['name']}'),
                      subtitle: Text(
                          '${product['model_number'] ?? ''} · ¥${product['price'] ?? '—'}'),
                      onTap: _loading || _error != null
                          ? null
                          : () => Navigator.pop(context, product)),
                if (_more)
                  TextButton(
                      onPressed: _loading ? null : () => _load(more: true),
                      child: const Text('加载更多'))
              ])),
            ]));
}

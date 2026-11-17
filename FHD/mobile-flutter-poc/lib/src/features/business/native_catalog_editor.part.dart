part of 'native_catalog_screen.dart';

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

import 'package:flutter/material.dart';
import '../../policy/mobile_error_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';
import 'native_workspace_session.dart';

class NativeFormField {
  const NativeFormField(this.key, this.label,
      {this.required = false,
      this.number = false,
      this.integer = false,
      this.minimum,
      this.options = const {},
      this.defaultValue = '',
      this.nullable = false});
  final String key, label;
  final bool required, number, integer, nullable;
  final num? minimum;
  final Map<String, String> options;
  final Object? defaultValue;
  String? validate(String? raw) {
    final text = raw?.trim() ?? '';
    if (text.isEmpty) return required ? '请填写$label' : null;
    if (options.isNotEmpty && !options.containsKey(text)) return '请选择有效的$label';
    if (number) {
      final n = num.tryParse(text);
      if (n == null || !n.isFinite || integer && n != n.round()) {
        return integer ? '请输入整数' : '请输入有效数字';
      }
      if (minimum != null && n < minimum!) return '$label不能小于 $minimum';
    }
    return null;
  }

  Object? parse(String value) => value.trim().isEmpty && nullable
      ? null
      : number
          ? num.parse(value.trim().isEmpty ? '0' : value.trim())
          : value.trim();
}

class NativeRecordEditor extends StatefulWidget {
  const NativeRecordEditor(
      {super.key,
      required this.session,
      required this.title,
      required this.fields,
      required this.save,
      this.onUncertainSave,
      this.initial = const {}});
  final NativeWorkspaceSession session;
  final String title;
  final List<NativeFormField> fields;
  final Map<String, Object?> initial;
  final Future<void> Function(Map<String, Object?>) save;
  // Opt in for non-idempotent writes: an error is not proof of no commit.
  final VoidCallback? onUncertainSave;
  @override
  State<NativeRecordEditor> createState() => _NativeRecordEditorState();
}

class _NativeRecordEditorState extends State<NativeRecordEditor> {
  final _form = GlobalKey<FormState>();
  late final Map<String, TextEditingController> _fields;
  bool _busy = false, _outcomeUnknown = false;
  String? _error;
  @override
  void initState() {
    super.initState();
    _fields = {
      for (final f in widget.fields)
        f.key: TextEditingController(
            text: '${widget.initial[f.key] ?? f.defaultValue ?? ''}')
    };
    widget.session.addListener(_invalidate);
  }

  void _invalidate() {
    if (mounted) {
      for (final c in _fields.values) {
        c.clear();
      }
      setState(() {});
    }
  }

  @override
  void dispose() {
    widget.session.removeListener(_invalidate);
    for (final c in _fields.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    if (_busy ||
        _outcomeUnknown ||
        !widget.session.active ||
        !_form.currentState!.validate()) {
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.save({
        for (final f in widget.fields) f.key: f.parse(_fields[f.key]!.text)
      });
      if (mounted && widget.session.active) Navigator.pop(context, true);
    } catch (error) {
      if (widget.session.active) widget.onUncertainSave?.call();
      if (mounted && widget.session.active) {
        setState(() {
          _outcomeUnknown = widget.onUncertainSave != null;
          _error = _outcomeUnknown
              ? '保存结果未知，可能已提交。请先核对出入库流水，不要重复保存；输入已保留。'
              : mobileErrorText(error);
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
  Widget build(BuildContext context) => PopScope(
      canPop: !_busy,
      child: Scaffold(
      backgroundColor: AppTheme.colors(context).page,
      body: SafeArea(
          child: Column(children: [
        WeTopBar(
            title: widget.title,
            showBack: true,
            onBack: () => Navigator.maybePop(context)),
        Expanded(
            child: !widget.session.active
                ? const Center(child: Text('账号或连接已切换，请重新打开'))
                : Form(
                    key: _form,
                    child:
                        ListView(padding: const EdgeInsets.all(20), children: [
                      for (final field in widget.fields)
                        Padding(
                            padding: const EdgeInsets.only(bottom: 16),
                            child: field.options.isEmpty
                                ? TextFormField(
                                    key: ValueKey(field.key),
                                    controller: _fields[field.key],
                                    enabled: !_busy && !_outcomeUnknown,
                                    validator: field.validate,
                                    keyboardType: field.number
                                        ? const TextInputType.numberWithOptions(
                                            decimal: true)
                                        : TextInputType.text,
                                    decoration: InputDecoration(
                                        labelText:
                                            '${field.label}${field.required ? ' *' : ''}'))
                                : DropdownButtonFormField<String>(
                                    key: ValueKey(field.key),
                                    isExpanded: true,
                                    initialValue: field.options.containsKey(
                                            _fields[field.key]!.text)
                                        ? _fields[field.key]!.text
                                        : null,
                                    decoration: InputDecoration(
                                        labelText:
                                            '${field.label}${field.required ? ' *' : ''}'),
                                    items: [
                                      for (final e in field.options.entries)
                                        DropdownMenuItem(
                                            value: e.key,
                                            child: Text(e.value,
                                                overflow:
                                                    TextOverflow.ellipsis))
                                    ],
                                    onChanged: _busy || _outcomeUnknown
                                        ? null
                                        : (value) {
                                            _fields[field.key]!.text =
                                                value ?? '';
                                          },
                                    validator: (_) => field
                                        .validate(_fields[field.key]!.text))),
                      if (_error != null)
                        Padding(
                            padding: const EdgeInsets.only(bottom: 16),
                            child: Text(_error!)),
                      FilledButton(
                          onPressed: _busy || _outcomeUnknown ? null : _save,
                          child: Text(_busy
                              ? '正在保存…'
                              : _outcomeUnknown ? '待核对流水' : '保存')),
                    ]))),
      ]))));
}

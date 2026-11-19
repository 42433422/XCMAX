part of 'native_approval_workspace.dart';

class _ApprovalFlowForm extends StatefulWidget {
  const _ApprovalFlowForm(
      {required this.session, required this.apiBase, this.initial});
  final NativeWorkspaceSession session;
  final String apiBase;
  final Map<String, Object?>? initial;
  @override
  State<_ApprovalFlowForm> createState() => _ApprovalFlowFormState();
}

class _ApprovalFlowFormState extends State<_ApprovalFlowForm> {
  final _form = GlobalKey<FormState>();
  late final Map<String, TextEditingController> _fields;
  final List<_FlowNodeDraft> _nodes = [];
  String _business = 'general';
  bool _active = true, _busy = false, _loading = false;
  String? _error;
  bool get _editing => widget.initial != null;
  @override
  void initState() {
    super.initState();
    final row = widget.initial ?? {};
    _fields = {
      for (final key in const ['flow_name', 'flow_key', 'description'])
        key: TextEditingController(text: '${row[key] ?? ''}')
    };
    _business = '${row['business_type'] ?? 'general'}';
    _active = row['is_active'] != false;
    widget.session.addListener(_invalidate);
    if (_editing) {
      unawaited(_loadNodes());
    } else {
      _nodes.add(_FlowNodeDraft());
    }
  }

  void _invalidate() {
    if (mounted) {
      for (final c in _fields.values) {
        c.clear();
      }
      for (final node in _nodes) {
        node.name.clear();
        node.approvers.clear();
      }
      setState(() {});
    }
  }

  Future<void> _loadNodes() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await widget.session
          .request('${widget.apiBase}/flows/${widget.initial!['id']}');
      if (mounted && widget.session.active) {
        setState(() {
          for (final node in _nodes) {
            node.dispose();
          }
          _nodes.clear();
          _nodes.addAll(
              _maps(_map(result['data'])['nodes']).map(_FlowNodeDraft.new));
        });
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
          _loading = false;
        });
      }
    }
  }

  @override
  void dispose() {
    widget.session.removeListener(_invalidate);
    for (final c in _fields.values) {
      c.dispose();
    }
    for (final node in _nodes) {
      node.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    final form = _form.currentState;
    if (_busy || _loading || !widget.session.active || form == null) return;
    final invalid = form.validateGranularly();
    if (invalid.isNotEmpty) {
      final first = invalid.first;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!first.mounted) return;
        unawaited(Scrollable.ensureVisible(
          first.context,
          alignment: 0.2,
          duration: AppTheme.motionDuration(first.context, milliseconds: 180),
        ));
      });
      return;
    }
    FocusScope.of(context).unfocus();
    if (!_editing && _nodes.isEmpty) {
      setState(() {
        _error = '请至少添加一个审批节点';
      });
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final flow = <String, Object?>{
      for (final e in _fields.entries)
        if (!_editing || e.key != 'flow_key') e.key: e.value.text.trim(),
      'business_type': _business,
      if (!_editing) 'is_active': _active
    };
    try {
      await widget.session.request(
          '${widget.apiBase}/flows${_editing ? '/${widget.initial!['id']}' : ''}',
          method: _editing ? 'PUT' : 'POST',
          body: _editing
              ? flow
              : {
                  'flow': flow,
                  'nodes': [
                    for (var i = 0; i < _nodes.length; i++)
                      _nodes[i].toJson(i + 1),
                  ]
                });
      if (mounted && widget.session.active) Navigator.pop(context, true);
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
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final colors = AppTheme.colors(context);
    return WorkspaceScaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        child: Column(
          children: [
            WeTopBar(
              title: _editing ? '编辑审批流程' : '新建审批流程',
              showBack: true,
              onBack: () => Navigator.maybePop(context),
            ),
            if (_loading || _busy) const LinearProgressIndicator(),
            Expanded(
              child: !widget.session.active
                  ? const Center(child: Text('账号或连接已切换，请重新打开'))
                  : Form(
                      key: _form,
                      child: ListView(
                        padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
                        keyboardDismissBehavior:
                            ScrollViewKeyboardDismissBehavior.onDrag,
                        children: [
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              _basicFields(text),
                              const SizedBox(height: 20),
                              Text('审批节点', style: text.titleMedium),
                              if (_editing && !_loading && _nodes.isEmpty)
                                const Padding(
                                  padding: EdgeInsets.symmetric(vertical: 8),
                                  child: Text('暂无审批节点'),
                                ),
                              for (var i = 0; i < _nodes.length; i++)
                                Padding(
                                  key: ObjectKey(_nodes[i]),
                                  padding: const EdgeInsets.only(top: 10),
                                  child: _node(_nodes[i], i),
                                ),
                              if (!_editing)
                                Padding(
                                  padding: const EdgeInsets.only(top: 10),
                                  child: OutlinedButton.icon(
                                    onPressed: _busy
                                        ? null
                                        : () => setState(() {
                                              _nodes.add(_FlowNodeDraft());
                                            }),
                                    icon: const Icon(Icons.add),
                                    label: const Text('添加审批节点'),
                                  ),
                                ),
                            ],
                          ),
                        ],
                      ),
                    ),
            ),
            if (widget.session.active)
              Material(
                color: colors.surface,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (_error != null)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: Semantics(
                            liveRegion: true,
                            child: Text(_error!, style: text.bodySmall),
                          ),
                        ),
                      FilledButton(
                        style: FilledButton.styleFrom(
                          minimumSize: const Size(0, 48),
                        ),
                        onPressed: _busy || _loading ? null : _save,
                        child: Text(_busy ? '正在保存…' : '保存流程'),
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

  Widget _basicFields(TextTheme text) => WorkspacePanel(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('基本信息', style: text.titleMedium),
            const SizedBox(height: 14),
            for (final e in const {
              'flow_name': '流程名称',
              'flow_key': '流程标识',
              'description': '流程描述'
            }.entries)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: TextFormField(
                  key: ValueKey(e.key),
                  controller: _fields[e.key],
                  enabled: !_busy,
                  readOnly: _editing && e.key == 'flow_key',
                  maxLines: e.key == 'description' ? 3 : 1,
                  decoration: InputDecoration(
                    labelText: e.value,
                    helperText:
                        _editing && e.key == 'flow_key' ? '流程标识创建后不可修改' : null,
                    helperMaxLines: 3,
                  ),
                  validator: (v) =>
                      e.key != 'description' && (v == null || v.trim().isEmpty)
                          ? '请填写${e.value}'
                          : null,
                ),
              ),
            DropdownButtonFormField<String>(
              initialValue: _business,
              decoration: const InputDecoration(labelText: '业务类型'),
              isExpanded: true,
              items: [
                for (final e in {
                  ..._businessTypes,
                  if (!_businessTypes.containsKey(_business))
                    _business: _business,
                }.entries)
                  DropdownMenuItem(value: e.key, child: Text(e.value)),
              ],
              onChanged: _busy ? null : (v) => setState(() => _business = v!),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('启用流程'),
              subtitle: _editing ? const Text('在流程管理中启用或停用') : null,
              value: _active,
              onChanged:
                  _busy || _editing ? null : (v) => setState(() => _active = v),
            ),
          ],
        ),
      );

  Widget _node(_FlowNodeDraft node, int index) => WorkspacePanel(
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Expanded(
              child: Text('第 ${index + 1} 级审批',
                  style: Theme.of(context).textTheme.titleSmall)),
          if (!_editing)
            IconButton(
                tooltip: '删除节点',
                onPressed: _busy
                    ? null
                    : () {
                        setState(() {
                          _nodes.remove(node);
                        });
                        // Release after this frame has detached the text fields.
                        WidgetsBinding.instance
                            .addPostFrameCallback((_) => node.dispose());
                      },
                icon: const Icon(Icons.delete_outline))
        ]),
        const SizedBox(height: 10),
        if (_editing) ...[
          Text(node.name.text),
          _detailFact('节点类型', node.type == 'parallel' ? '并行审批' : '串行审批'),
          if (node.approvers.text.isNotEmpty)
            _detailFact('审批人 ID', node.approvers.text),
        ] else ...[
          TextFormField(
              controller: node.name,
              enabled: !_busy,
              decoration: const InputDecoration(labelText: '节点名称'),
              validator: (v) =>
                  v == null || v.trim().isEmpty ? '请输入节点名称' : null),
          const SizedBox(height: 10),
          DropdownButtonFormField<String>(
              isExpanded: true,
              initialValue: node.type,
              decoration: const InputDecoration(labelText: '节点类型'),
              items: const [
                DropdownMenuItem(value: 'serial', child: Text('串行审批')),
                DropdownMenuItem(value: 'parallel', child: Text('并行审批'))
              ],
              onChanged: _busy ? null : (v) => node.type = v!),
          const SizedBox(height: 10),
          DropdownButtonFormField<String>(
              isExpanded: true,
              initialValue: node.approverType,
              decoration: const InputDecoration(labelText: '审批人类型'),
              items: [
                for (final e in const {
                  'user': '指定用户',
                  'role': '指定角色',
                  'position': '指定职位',
                  'dynamic': '动态审批人'
                }.entries)
                  DropdownMenuItem(value: e.key, child: Text(e.value))
              ],
              onChanged: _busy ? null : (v) => node.approverType = v!),
          const SizedBox(height: 10),
          TextFormField(
              controller: node.approvers,
              enabled: !_busy,
              decoration: const InputDecoration(
                  labelText: '审批人 ID',
                  helperText: '多个 ID 用逗号分隔',
                  helperMaxLines: 3),
              validator: (v) {
                if ((v ?? '').trim().isEmpty) return null;
                return v!
                        .split(RegExp('[,，]'))
                        .any((s) => (int.tryParse(s.trim()) ?? 0) <= 0)
                    ? '请填写有效的正整数 ID'
                    : null;
              }),
        ],
      ]));
}

class _FlowNodeDraft {
  _FlowNodeDraft([Map<String, Object?> row = const {}])
      : name = TextEditingController(text: '${row['node_name'] ?? ''}'),
        approvers = TextEditingController(
            text: row['approver_ids'] is List
                ? (row['approver_ids'] as List).join(',')
                : ''),
        type = '${row['node_type'] ?? 'serial'}',
        approverType = '${row['approver_type'] ?? 'user'}',
        active = row['is_active'] != false;
  final TextEditingController name, approvers;
  String type, approverType;
  bool active;
  Map<String, Object?> toJson(int order) => {
        'node_name': name.text.trim(),
        'node_type': type,
        'node_order': order,
        'approver_type': approverType,
        'approver_ids': approvers.text.trim().isEmpty
            ? <int>[]
            : approvers.text
                .split(RegExp('[,，]'))
                .map((v) => int.parse(v.trim()))
                .toList(),
        'is_active': active
      };
  void dispose() {
    name.dispose();
    approvers.dispose();
  }
}

part of 'native_catalog_screen.dart';

extension _CatalogTransfer on _NativeCatalogScreenState {
  Widget _transferMenu() => PopupMenuButton<String>(
        tooltip: '导入与导出',
        enabled: _editable,
        onSelected: (action) =>
            action == 'import' ? _importFile() : _exportFile(action),
        itemBuilder: (_) => [
          if (!_shipments)
            const PopupMenuItem(value: 'import', child: Text('导入 Excel')),
          const PopupMenuItem(value: 'xlsx', child: Text('导出 Excel')),
          if (_products)
            const PopupMenuItem(value: 'docx', child: Text('导出 Word 价格表')),
        ],
      );

  Future<String?> _chooseTemplate(String format) async {
    final result = await _session.request('api/mobile/v1/workspace/templates');
    final rows = _maps(result['templates']).where((row) {
      if (row['virtual'] == true) return false;
      if (_shipments) {
        return row['category'] == 'excel' &&
            (row['business_scope'] == 'shipmentRecords' ||
                const ['出货记录', '考勤记录'].contains(row['template_type'])) &&
            '${row['file_path'] ?? row['path'] ?? ''}'.trim().isNotEmpty;
      }
      if (!_products) {
        return row['category'] == 'excel' &&
            (row['business_scope'] == 'customers' ||
                row['template_type'] == '客户');
      }
      final filename = '${row['filename'] ?? ''}'.toLowerCase();
      final name = '${row['name'] ?? ''}'.toLowerCase();
      final id = '${row['id'] ?? ''}'.toLowerCase();
      return row['category'] == 'word' &&
          (filename.contains('price_list') ||
              id.contains('price_list') ||
              name.contains('price_list') ||
              filename.contains('价目') ||
              filename.contains('价格表') ||
              name.contains('价目') ||
              name.contains('价格表'));
    }).toList();
    if (!mounted || !_session.active) return null;
    if (!_products && rows.isEmpty) throw StateError('没有可用的导出模板，请先在模板管理中配置');
    return showDialog<String>(
        context: context,
        builder: (context) =>
            SimpleDialog(title: const Text('选择导出模板'), children: [
              if (_products)
                SimpleDialogOption(
                    onPressed: () => Navigator.pop(context, ''),
                    child: const Text('默认价格表模板')),
              for (final row in rows)
                SimpleDialogOption(
                    onPressed: () {
                      final filename = '${row['filename'] ?? ''}'.trim();
                      final slug = (filename.isNotEmpty
                              ? filename
                              : '${row['id'] ?? ''}'.trim())
                          .replaceFirst(RegExp(r'^fs:'), '')
                          .replaceFirst(
                              RegExp(r'\.docx$', caseSensitive: false), '');
                      Navigator.pop(context, _products ? slug : '${row['id']}');
                    },
                    child: Text('${row['name'] ?? row['id']}')),
            ]));
  }

  Future<void> _exportFile(String format) async {
    if (!_editable) return;
    if (_shipments && _unit.isEmpty) {
      _notice('请先选择购买单位');
      return;
    }
    _setBusy(true);
    try {
      String? template = '';
      if (!_products || format == 'docx') {
        template = await _chooseTemplate(format);
      }
      if (template == null || !mounted || !_session.active) return;
      final bytes = await _session.download(
          _shipments
              ? 'api/mobile/v1/workspace/shipment/shipment-records/export'
              : '$_endpoint/${_products ? 'export.$format' : 'export'}',
          query: {
            if (template.isNotEmpty) 'template_id': template,
            if ((_products || _shipments) && _unit.isNotEmpty) 'unit': _unit,
            if (_shipments) 'status': _status == 'all' ? '' : _status,
            if (_products && _search.text.trim().isNotEmpty)
              'keyword': _search.text.trim(),
          });
      if (!mounted || !_session.active) return;
      await shareWorkspaceFile('${widget.title}.$format', bytes,
          isCurrent: () => mounted && _session.active);
    } catch (error) {
      if (mounted && _session.active) _notice(mobileErrorText(error));
    } finally {
      if (mounted) {
        _setBusy(false);
      }
    }
  }

  Future<bool> _confirmImport(String name,
      {List<Map<String, Object?>>? rows}) async {
    if (!mounted || !_session.active) return false;
    return await showDialog<bool>(
            context: context,
            builder: (context) => AlertDialog(
                  title: const Text('确认导入'),
                  content: SingleChildScrollView(
                      child: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                        Text(name),
                        const SizedBox(height: 12),
                        Text(rows == null
                            ? '将按桌面端规则更新当前工作区的客户资料。'
                            : '识别到 ${rows.length} 行，将校验并跳过重复记录。'),
                        if (rows != null)
                          ...rows.take(5).map((row) => Padding(
                              padding: const EdgeInsets.only(top: 8),
                              child: Text(
                                  row.values.map((v) => '$v').join(' · '),
                                  maxLines: 3,
                                  overflow: TextOverflow.ellipsis))),
                      ])),
                  actions: [
                    TextButton(
                        onPressed: () => Navigator.pop(context, false),
                        child: const Text('取消')),
                    FilledButton(
                        onPressed: () => Navigator.pop(context, true),
                        child: const Text('确认导入'))
                  ],
                )) ==
        true;
  }

  Future<void> _importFile() async {
    if (!_editable) return;
    _setBusy(true);
    try {
      final file = await openFile(acceptedTypeGroups: [
        XTypeGroup(
            label: 'Excel',
            extensions: _products ? ['xlsx', 'xls'] : ['xlsx'],
            uniformTypeIdentifiers: const [
              'org.openxmlformats.spreadsheetml.sheet',
              'com.microsoft.excel.xls'
            ])
      ]);
      if (file == null || !mounted || !_session.active) return;
      if (await file.length() > 16 * 1024 * 1024) {
        throw StateError('请选择不超过 16MB 的文件');
      }
      final bytes = await file.readAsBytes();
      Map<String, Object?> result;
      if (_products) {
        final extracted = await _session.upload(
            'api/excel/data/extract/upload', bytes, file.name,
            field: 'excel_file');
        final rows = _maps(extracted['rows']);
        if (rows.isEmpty) throw StateError('没有识别到数据，请检查表头和内容');
        if (!await _confirmImport(file.name, rows: rows)) return;
        result = await _session
            .request('api/excel/data/import/products', method: 'POST', body: {
          'file_name': file.name,
          'data': rows,
          'field_mapping': {
            for (final header in _maps(extracted['headers']))
              if (header['value'] != null) '${header['value']}': header['value']
          },
          'options': {
            'skip_duplicates': true,
            'validate_before_import': true,
            'clean_data': true
          },
        });
      } else {
        if (!await _confirmImport(file.name)) return;
        result = await _session.upload('$_endpoint/import', bytes, file.name);
      }
      if (mounted && _session.active) {
        _notice(_products
            ? '导入 ${result['imported'] ?? 0} 条，跳过 ${result['skipped'] ?? 0} 条'
            : '导入完成');
        await _load();
      }
    } catch (error) {
      if (mounted && _session.active) _notice(mobileErrorText(error));
    } finally {
      if (mounted) {
        _setBusy(false);
      }
    }
  }
}

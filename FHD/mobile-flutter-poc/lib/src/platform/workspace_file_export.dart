import 'dart:io';

import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

/// Uses the system file/share sheet; no remote URI or credentials leave Flutter.
Future<void> shareWorkspaceFile(String name, List<int> bytes,
    {required bool Function() isCurrent}) async {
  if (!isCurrent()) return;
  final root =
      Directory('${(await getTemporaryDirectory()).path}/workspace_exports');
  await root.create(recursive: true);
  final directory = await root.createTemp('export-');
  final file =
      File('${directory.path}/${name.replaceAll(RegExp(r'[/\\\r\n]'), '_')}');
  await file.writeAsBytes(bytes, flush: true);
  if (!isCurrent()) {
    await directory.delete(recursive: true);
    return;
  }
  await const MethodChannel('xcagi/workspace_files')
      .invokeMethod<void>('share', {'path': file.path});
}

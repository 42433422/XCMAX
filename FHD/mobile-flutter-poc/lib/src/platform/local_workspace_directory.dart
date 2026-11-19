import 'package:flutter/services.dart';

Future<String> localWorkspaceDatabaseDirectory() async {
  const channel = MethodChannel('xcagi/session_store');
  final path = await channel.invokeMethod<String>('localWorkspaceDirectory');
  if (path == null || path.isEmpty) {
    throw StateError('无法访问不参与备份的本地工作区');
  }
  return path;
}

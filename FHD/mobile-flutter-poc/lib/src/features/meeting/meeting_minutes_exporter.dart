import 'dart:io';

import 'package:flutter/services.dart';

import 'meeting_minutes_docx.dart';

class MeetingMinutesExporter {
  const MeetingMinutesExporter();

  static const _channel = MethodChannel('xcagi/meeting_minutes');

  Future<String> createAndShare(MeetingMinutesDraft draft) async {
    if (!Platform.isAndroid) {
      throw const MeetingMinutesExportException('当前平台暂不支持分享 Word 文档');
    }
    final bytes = MeetingMinutesDocxBuilder.build(draft);
    final path = await _channel.invokeMethod<String>('shareDocx', {
      'filename': _filename(draft.title),
      'bytes': bytes,
    });
    final clean = path?.trim() ?? '';
    if (clean.isEmpty) {
      throw const MeetingMinutesExportException('Word 文档生成失败');
    }
    return clean;
  }

  String _filename(String title) {
    final clean = title
        .trim()
        .replaceAll(RegExp(r'[\\/:*?"<>|]'), '-')
        .replaceAll(RegExp(r'\s+'), '_');
    final safe = clean.isEmpty ? '会议纪要' : clean;
    return '${safe.length > 48 ? safe.substring(0, 48) : safe}.docx';
  }
}

class MeetingMinutesExportException implements Exception {
  const MeetingMinutesExportException(this.message);

  final String message;

  @override
  String toString() => message;
}

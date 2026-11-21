part of 'chat_screen.dart';

abstract class _ChatAttachmentActions extends _ChatStateMessaging {
  final _attachmentSizes = Expando<int>();

  Future<String> _currentAttachmentScope() async {
    final client = _repository!.client;
    final base = await client.resolveSessionBaseUrl();
    return '${client.authGeneration}|$base';
  }

  Future<bool> _checkAttachmentScope() async {
    final expected = _attachmentScope;
    if (expected == null || _repository == null) return true;
    final current = await _currentAttachmentScope();
    if (!mounted || expected != _attachmentScope) return false;
    if (expected == current) return true;
    setState(() {
      _attachments.clear();
      _failedAttachments.clear();
      if (_lastSentAttachments.isNotEmpty) _stopRequested = true;
      _lastSentAttachments = const [];
      _attachmentScope = null;
    });
    _showMessage('账号或连接已切换，请重新选择附件');
    return false;
  }

  Future<void> _pickAttachments() async {
    if (_sending || _uploading) return;
    if (widget.conversation.type != ConversationType.pinnedAssistant) {
      await Navigator.of(context).push(MaterialPageRoute<void>(
          builder: (_) => ChatScreen(
                conversation: const ConversationItem(
                    id: PinnedIds.assistant,
                    type: ConversationType.pinnedAssistant,
                    title: '小C',
                    subtitle: '',
                    timestampText: ''),
                initialMessages: const [],
                repository: _repository,
              )));
      return;
    }
    final selectionScope =
        _repository == null ? null : await _currentAttachmentScope();
    try {
      final files = await (widget.attachmentPicker ?? openFiles)();
      if (mounted && selectionScope == await _currentAttachmentScope()) {
        await _uploadAttachments(files);
      }
    } catch (error) {
      if (mounted) _showMessage('选择文件失败：${mobileErrorText(error)}');
    }
  }

  Future<void> _takeAttachmentPhoto() async {
    if (_sending || _uploading) return;
    final selectionScope =
        _repository == null ? null : await _currentAttachmentScope();
    try {
      final photo = await ImagePicker().pickImage(source: ImageSource.camera);
      if (mounted &&
          photo != null &&
          selectionScope == await _currentAttachmentScope()) {
        await _uploadAttachments([photo]);
      }
    } catch (error) {
      if (mounted) _showMessage('拍照失败：${mobileErrorText(error)}');
    }
  }

  Future<void> _uploadAttachments(List<XFile> files) async {
    final client = _repository?.client;
    if (_sending || _uploading || client == null || files.isEmpty) return;
    if (_attachments.length + files.length > 4) {
      _showMessage('每轮最多 4 个附件，请先移除多余附件');
      return;
    }
    if (!await _checkAttachmentScope() || !mounted) return;
    _attachmentScope = await _currentAttachmentScope();
    final expectedScope = _attachmentScope;
    final expectedBase = await client.resolveSessionBaseUrl();
    final generation = client.authGeneration;
    setState(() {
      _uploading = true;
      _showToolPanel = false;
    });
    for (final file in files) {
      if (!mounted ||
          generation != client.authGeneration ||
          expectedScope != await _currentAttachmentScope()) {
        break;
      }
      try {
        final size = await file.length();
        _attachmentSizes[file] = size;
        if (size > 16 * 1024 * 1024) {
          throw Exception('单个附件不能超过 16MB');
        }
        final attachment = await client.uploadChatAttachment(
            name: file.name,
            bytes: await file.readAsBytes(),
            conversationId: widget.conversation.id,
            expectedAuthGeneration: generation,
            expectedBaseUrl: expectedBase);
        if (!mounted ||
            generation != client.authGeneration ||
            expectedScope != await _currentAttachmentScope()) {
          break;
        }
        setState(() {
          _attachmentSizes[attachment] = size;
          _attachments.add(attachment);
          _failedAttachments.remove(file);
        });
      } catch (error) {
        if (!mounted) break;
        if (generation != client.authGeneration ||
            expectedScope != await _currentAttachmentScope()) {
          await _checkAttachmentScope();
          break;
        }
        setState(() {
          if (!_failedAttachments.contains(file)) _failedAttachments.add(file);
        });
        _showMessage('${file.name}：${mobileErrorText(error)}');
      }
    }
    if (mounted) {
      await _checkAttachmentScope();
      if (mounted) setState(() => _uploading = false);
    }
  }

  Widget _attachmentList() => ConstrainedBox(
        constraints: const BoxConstraints(maxHeight: 176),
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 12),
          child: Column(children: [
            if (_uploading)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 8),
                child: Text('附件上传中…'),
              ),
            for (final attachment in _attachments)
              _ChatAttachmentRow(
                  name: attachment.name,
                  size: _attachmentSizes[attachment],
                  onRemove: _sending || _uploading
                      ? null
                      : () => setState(() => _attachments.remove(attachment))),
            for (final file in _failedAttachments)
              _ChatAttachmentRow(
                  name: file.name,
                  size: _attachmentSizes[file],
                  failed: true,
                  onRetry: _sending || _uploading
                      ? null
                      : () => _uploadAttachments([file]),
                  onRemove: _sending || _uploading
                      ? null
                      : () => setState(() => _failedAttachments.remove(file))),
          ]),
        ),
      );
}

class _ChatAttachmentRow extends StatelessWidget {
  const _ChatAttachmentRow({
    required this.name,
    required this.size,
    required this.onRemove,
    this.failed = false,
    this.onRetry,
  });

  final String name;
  final int? size;
  final bool failed;
  final VoidCallback? onRemove, onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final bytes = size;
    final sizeLabel = bytes == null
        ? ''
        : bytes < 1024
            ? '$bytes B · '
            : bytes < 1024 * 1024
                ? '${(bytes / 1024).toStringAsFixed(1)} KB · '
                : '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB · ';
    return Container(
      margin: const EdgeInsets.only(top: 6),
      padding: const EdgeInsets.only(left: 12),
      decoration: BoxDecoration(
        color: colors.surfaceHigh,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(children: [
        Icon(failed ? Icons.error_outline : Icons.insert_drive_file_outlined,
            size: 24, color: failed ? colors.danger : colors.brand),
        const SizedBox(width: 10),
        Expanded(
            child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 10),
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Tooltip(
                message: name,
                child: Text(name,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                        color: colors.textPrimary,
                        fontSize: 14,
                        fontWeight: FontWeight.w500))),
            const SizedBox(height: 3),
            Text('$sizeLabel${failed ? '上传失败' : '已就绪'}',
                style: TextStyle(
                    fontSize: 12,
                    color: failed ? colors.danger : colors.textSecondary)),
          ]),
        )),
        if (failed) TextButton(onPressed: onRetry, child: const Text('重试')),
        IconButton(
            tooltip: '移除 $name',
            onPressed: onRemove,
            icon: const Icon(Icons.close, size: 18)),
      ]),
    );
  }
}

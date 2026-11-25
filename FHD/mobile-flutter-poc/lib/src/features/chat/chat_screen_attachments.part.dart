part of 'chat_screen.dart';

abstract class _ChatAttachmentActions extends _ChatStateMessaging {
  final _attachmentSizes = Expando<int>();
  bool _cancelAttachmentUploadRequested = false;

  Future<String> _currentAttachmentScope() async {
    final client = _repository!.client;
    final base = await client.resolveSessionBaseUrl();
    return '${client.authGeneration}|$base';
  }

  Future<bool> _checkAttachmentScope() async {
    final expected = _attachmentScope;
    if (expected == null || _repository == null) return true;
    String current;
    try {
      current = await _currentAttachmentScope();
    } catch (_) {
      // An unresolved connection must not admit a new upload.
      return false;
    }
    if (!mounted || _chatInvalidated || expected != _attachmentScope) return false;
    if (expected == current) return true;
    setState(() {
      _attachments.clear();
      _failedAttachments.clear();
      _recoveredAttachmentNames.clear();
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
    if (_repository == null || _chatInvalidated) return;
    try {
      final selectionScope = await _currentAttachmentScope();
      if (!mounted || _chatInvalidated) return;
      final files = await (widget.attachmentPicker ?? openFiles)();
      if (mounted && selectionScope == await _currentAttachmentScope() &&
          mounted && !_chatInvalidated) {
        await _uploadAttachments(files);
      }
    } catch (error) {
      if (mounted) _showMessage('选择文件失败：${mobileErrorText(error)}');
    }
  }

  Future<void> _takeAttachmentPhoto() async {
    if (_sending || _uploading) return;
    if (_repository == null || _chatInvalidated) return;
    try {
      final selectionScope = await _currentAttachmentScope();
      if (!mounted || _chatInvalidated) return;
      final photo = await ImagePicker().pickImage(source: ImageSource.camera);
      if (mounted &&
          photo != null &&
          selectionScope == await _currentAttachmentScope() &&
          mounted && !_chatInvalidated) {
        await _uploadAttachments([photo]);
      }
    } catch (error) {
      if (mounted) _showMessage('拍照失败：${mobileErrorText(error)}');
    }
  }

  Future<void> _uploadAttachments(List<XFile> files) async {
    final client = _repository?.client;
    if (!mounted || _chatInvalidated || _sending || _uploading ||
        client == null || files.isEmpty) return;
    if (_attachments.length + files.length > 4) {
      _showMessage('每轮最多 4 个附件，请先移除多余附件');
      return;
    }

    // Reserve the batch before the first await. Two picker/retry callbacks
    // must not both pass the admission check.
    setState(() {
      _uploading = true;
      _cancelAttachmentUploadRequested = false;
      _showToolPanel = false;
    });
    final generation = client.authGeneration;
    bool active() => mounted && !_chatInvalidated &&
        !_cancelAttachmentUploadRequested &&
        generation == client.authGeneration && generation == _chatGeneration;
    try {
      if (!await _checkAttachmentScope() || !active()) return;
      final expectedBase = await client.resolveSessionBaseUrl();
      if (!active()) return;
      final expectedScope = '$generation|$expectedBase';
      _attachmentScope = expectedScope;

      Future<bool> current() async {
        if (!active() || _attachmentScope != expectedScope) return false;
        final scope = await _currentAttachmentScope();
        return active() && _attachmentScope == expectedScope &&
            scope == expectedScope;
      }

      for (final file in files) {
        if (!await current()) break;
        try {
          final size = await file.length();
          if (!await current()) break;
          _attachmentSizes[file] = size;
          if (size > 16 * 1024 * 1024) {
            throw Exception('单个附件不能超过 16MB');
          }
          final bytes = await file.readAsBytes();
          if (!await current()) break;
          final attachment = await client.uploadChatAttachment(
              name: file.name,
              bytes: bytes,
              conversationId: widget.conversation.id,
              expectedAuthGeneration: generation,
              expectedBaseUrl: expectedBase);
          // A cancellation, session switch or disposed screen makes the
          // in-flight reply ineligible for inclusion in a subsequent send.
          if (!await current()) break;
          setState(() {
            _attachmentSizes[attachment] = size;
            _attachments.add(attachment);
            _recoveredAttachmentNames.removeWhere(
                (name) => name == attachment.name);
            _failedAttachments.remove(file);
          });
        } catch (error) {
          if (!await current()) break;
          setState(() {
            if (!_failedAttachments.contains(file)) _failedAttachments.add(file);
          });
          _showMessage('${file.name}：${mobileErrorText(error)}');
        }
      }
    } catch (error) {
      if (active()) _showMessage('附件上传失败：${mobileErrorText(error)}');
    } finally {
      if (mounted && !_chatInvalidated) {
        await _checkAttachmentScope();
      }
      if (mounted) {
        setState(() {
          _uploading = false;
          _cancelAttachmentUploadRequested = false;
        });
        _scheduleChatDraftSave();
      }
    }
  }

  void _cancelAttachmentUpload() {
    if (!_uploading || _cancelAttachmentUploadRequested) return;
    setState(() => _cancelAttachmentUploadRequested = true);
  }

  Widget _attachmentList() => ConstrainedBox(
        constraints: const BoxConstraints(maxHeight: 176),
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 12),
          child: Column(children: [
            if (_uploading)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Wrap(
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(_cancelAttachmentUploadRequested
                        ? '已取消后续上传，等待当前请求结束；服务端可能已接收当前文件。'
                        : '附件上传中…'),
                    if (!_cancelAttachmentUploadRequested)
                      TextButton(
                        onPressed: _cancelAttachmentUpload,
                        child: const Text('取消上传'),
                      ),
                  ],
                ),
              ),
            if (_recoveredAttachmentNames.isNotEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 6),
                child: Text('上次上传的附件需要重新选择，旧上传凭证不会自动复用。'),
              ),
            for (final name in _recoveredAttachmentNames)
              _ChatAttachmentRow(
                name: name,
                size: null,
                failed: true,
                onRemove: _sending || _uploading ? null : () {
                  setState(() => _recoveredAttachmentNames.remove(name));
                  _scheduleChatDraftSave();
                },
              ),
            for (final attachment in _attachments)
              _ChatAttachmentRow(
                  name: attachment.name,
                  size: _attachmentSizes[attachment],
                  onRemove: _sending || _uploading
                      ? null
                      : () {
                            setState(() => _attachments.remove(attachment));
                            _scheduleChatDraftSave();
                          }),
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
                      : () {
                            setState(() => _failedAttachments.remove(file));
                            _scheduleChatDraftSave();
                          }),
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

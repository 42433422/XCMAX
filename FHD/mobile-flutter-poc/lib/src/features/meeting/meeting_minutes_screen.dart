import 'dart:async';

import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_recognition_error.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../../data/mobile_repository.dart';
import '../../platform/android_record_audio_permission.dart';
import '../../theme/app_theme.dart';
import 'meeting_minutes_docx.dart';
import 'meeting_minutes_exporter.dart';

class MeetingMinutesResult {
  const MeetingMinutesResult({
    required this.title,
    required this.filePath,
    required this.summary,
  });

  final String title;
  final String filePath;
  final String summary;
}

class MeetingMinutesScreen extends StatefulWidget {
  const MeetingMinutesScreen({
    super.key,
    required this.repository,
    this.exporter = const MeetingMinutesExporter(),
  });

  final MobileRepository repository;
  final MeetingMinutesExporter exporter;

  @override
  State<MeetingMinutesScreen> createState() => _MeetingMinutesScreenState();
}

class _MeetingMinutesScreenState extends State<MeetingMinutesScreen> {
  final _speech = SpeechToText();
  final _titleController = TextEditingController();
  final _participantsController = TextEditingController();
  final _locationController = TextEditingController();
  final _transcriptController = TextEditingController();
  Timer? _timer;
  var _recording = false;
  var _generating = false;
  var _elapsedSeconds = 0;
  var _partial = '';
  var _errorText = '';
  String? _generatedPath;
  MeetingMinutesResult? _result;

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _titleController.text =
        '会议纪要 ${now.year}-${_two(now.month)}-${_two(now.day)}';
  }

  @override
  void dispose() {
    _timer?.cancel();
    _speech.cancel();
    _titleController.dispose();
    _participantsController.dispose();
    _locationController.dispose();
    _transcriptController.dispose();
    super.dispose();
  }

  Future<void> _toggleRecording() async {
    if (_recording) {
      await _stopRecording();
    } else {
      await _startRecording();
    }
  }

  Future<void> _startRecording() async {
    final granted = await const AndroidRecordAudioPermission().ensureGranted();
    if (!mounted) return;
    if (!granted) {
      setState(() => _errorText = '需要麦克风权限才能录音转写');
      return;
    }
    final available = await _speech.initialize(
      onStatus: _handleSpeechStatus,
      onError: _handleSpeechError,
    );
    if (!mounted) return;
    if (!available) {
      setState(() => _errorText = '当前设备语音识别不可用');
      return;
    }
    setState(() {
      _recording = true;
      _errorText = '';
      _generatedPath = null;
      _result = null;
    });
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted && _recording) {
        setState(() => _elapsedSeconds += 1);
      }
    });
    await _listen();
  }

  Future<void> _listen() async {
    if (!_recording || _speech.isListening) return;
    try {
      await _speech.listen(
        onResult: _handleSpeechResult,
        listenOptions: SpeechListenOptions(
          listenMode: ListenMode.dictation,
          partialResults: true,
          cancelOnError: false,
          listenFor: const Duration(minutes: 30),
          pauseFor: const Duration(seconds: 4),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      setState(() => _errorText = '录音转写暂时中断：$error');
    }
  }

  Future<void> _stopRecording() async {
    if (!_recording) return;
    setState(() => _recording = false);
    _timer?.cancel();
    try {
      await _speech.stop();
    } catch (_) {
      // The transcript collected so far remains editable and exportable.
    }
    _commitPartial();
  }

  void _handleSpeechResult(SpeechRecognitionResult result) {
    if (!mounted) return;
    final words = result.recognizedWords.trim();
    setState(() {
      _partial = words;
      if (result.finalResult && words.isNotEmpty) {
        _appendTranscript(words);
        _partial = '';
      }
    });
  }

  void _handleSpeechStatus(String status) {
    if (!_recording || (status != 'done' && status != 'notListening')) return;
    _commitPartial();
    Future<void>.delayed(const Duration(milliseconds: 350), () {
      if (mounted && _recording) unawaited(_listen());
    });
  }

  void _handleSpeechError(SpeechRecognitionError error) {
    if (!mounted) return;
    setState(() => _errorText = _friendlySpeechError(error.errorMsg));
    if (_recording) {
      Future<void>.delayed(const Duration(milliseconds: 500), () {
        if (mounted && _recording) unawaited(_listen());
      });
    }
  }

  void _commitPartial() {
    final text = _partial.trim();
    if (text.isNotEmpty) _appendTranscript(text);
    if (mounted) setState(() => _partial = '');
  }

  void _appendTranscript(String text) {
    final clean = text.trim();
    if (clean.isEmpty) return;
    final existing = _transcriptController.text.trimRight();
    if (existing.endsWith(clean)) return;
    _transcriptController.text = existing.isEmpty ? clean : '$existing\n$clean';
    _transcriptController.selection = TextSelection.collapsed(
      offset: _transcriptController.text.length,
    );
  }

  Future<void> _generateWord() async {
    await _stopRecording();
    final transcript = _transcriptController.text.trim();
    if (transcript.isEmpty) {
      setState(() => _errorText = '请先录音，或在转写框中输入会议内容');
      return;
    }
    setState(() {
      _generating = true;
      _errorText = '';
      _generatedPath = null;
    });
    try {
      String organized = '';
      try {
        organized = await widget.repository.summarizeMeetingMinutes(
          title: _titleController.text,
          participants: _participantsController.text,
          transcript: transcript,
        );
      } catch (_) {
        // Offline fallback still creates a complete Word file from transcript.
      }
      final outline = MeetingMinutesOutline.fromAssistantText(
        organized,
        transcript: transcript,
      );
      final draft = MeetingMinutesDraft(
        title: _titleController.text.trim().isEmpty
            ? '会议纪要'
            : _titleController.text.trim(),
        meetingDateText: _meetingDateText(),
        durationText: _durationText(_elapsedSeconds),
        participants: _participantsController.text.trim(),
        location: _locationController.text.trim(),
        transcript: transcript,
        summary: outline.summary,
        discussionPoints: outline.discussionPoints,
        decisions: outline.decisions,
        actionItems: outline.actionItems,
      );
      final path = await widget.exporter.createAndShare(draft);
      if (!mounted) return;
      setState(() {
        _generatedPath = path;
        _result = MeetingMinutesResult(
          title: draft.title,
          filePath: path,
          summary: draft.summary,
        );
      });
    } catch (error) {
      if (mounted) setState(() => _errorText = error.toString());
    } finally {
      if (mounted) setState(() => _generating = false);
    }
  }

  void _returnToAssistant() {
    Navigator.of(context).pop(_result);
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final theme = Theme.of(context);
    return Scaffold(
      backgroundColor: colors.page,
      appBar: AppBar(
        title: const Text('会议纪要'),
        backgroundColor: colors.surface,
        foregroundColor: colors.textPrimary,
        elevation: 0,
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
          children: [
            Text(
              '录下来，小C帮你整理成 Word',
              style: theme.textTheme.headlineSmall?.copyWith(
                color: colors.textPrimary,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              '实时转写可随时编辑；原始音频不会保存在手机中。',
              style: TextStyle(color: colors.textSecondary, fontSize: 13),
            ),
            const SizedBox(height: 18),
            _InputCard(
              children: [
                TextField(
                  key: const ValueKey('meeting_title_field'),
                  controller: _titleController,
                  decoration: const InputDecoration(labelText: '会议主题'),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: _participantsController,
                  decoration: const InputDecoration(
                    labelText: '参会人员',
                    hintText: '例如：张三、李四、小C',
                  ),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: _locationController,
                  decoration: const InputDecoration(
                    labelText: '会议地点',
                    hintText: '选填',
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            _RecordingCard(
              recording: _recording,
              elapsedText: _durationText(_elapsedSeconds),
              partial: _partial,
              onTap: _generating ? null : _toggleRecording,
            ),
            const SizedBox(height: 14),
            _InputCard(
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        '实时转写',
                        style: TextStyle(
                          color: colors.textPrimary,
                          fontWeight: FontWeight.w600,
                          fontSize: 16,
                        ),
                      ),
                    ),
                    Text(
                      '${_transcriptController.text.trim().length} 字',
                      style: TextStyle(color: colors.textSecondary),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                TextField(
                  key: const ValueKey('meeting_transcript_field'),
                  controller: _transcriptController,
                  minLines: 8,
                  maxLines: 16,
                  onChanged: (_) => setState(() {}),
                  decoration: const InputDecoration(
                    hintText: '录音内容会实时出现在这里，也可以手动补充或修改。',
                    alignLabelWithHint: true,
                  ),
                ),
              ],
            ),
            if (_errorText.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                _errorText,
                key: const ValueKey('meeting_error_text'),
                style: TextStyle(color: colors.danger, fontSize: 13),
              ),
            ],
            if (_generatedPath != null) ...[
              const SizedBox(height: 14),
              Container(
                key: const ValueKey('meeting_word_ready'),
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: colors.success.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Row(
                  children: [
                    Icon(Icons.check_circle, color: colors.success),
                    const SizedBox(width: 10),
                    const Expanded(
                      child: Text('Word 已生成，可以保存到文件或分享给同事。'),
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 18),
            FilledButton.icon(
              key: const ValueKey('meeting_generate_word'),
              onPressed: _generating ? null : _generateWord,
              icon: _generating
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.description_outlined),
              label: Text(_generating ? '小C正在整理…' : '整理并生成 Word'),
              style: FilledButton.styleFrom(
                minimumSize: const Size.fromHeight(52),
              ),
            ),
            if (_generatedPath != null) ...[
              const SizedBox(height: 10),
              OutlinedButton(
                onPressed: _returnToAssistant,
                child: const Text('返回小C助理'),
              ),
            ],
          ],
        ),
      ),
    );
  }

  String _meetingDateText() {
    final now = DateTime.now();
    return '${now.year}-${_two(now.month)}-${_two(now.day)} '
        '${_two(now.hour)}:${_two(now.minute)}';
  }
}

class _InputCard extends StatelessWidget {
  const _InputCard({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: colors.divider),
      ),
      child: Column(children: children),
    );
  }
}

class _RecordingCard extends StatelessWidget {
  const _RecordingCard({
    required this.recording,
    required this.elapsedText,
    required this.partial,
    required this.onTap,
  });

  final bool recording;
  final String elapsedText;
  final String partial;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Material(
      color: recording
          ? colors.danger.withValues(alpha: 0.08)
          : colors.brand.withValues(alpha: 0.08),
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        key: const ValueKey('meeting_record_button'),
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Row(
            children: [
              Container(
                width: 54,
                height: 54,
                decoration: BoxDecoration(
                  color: recording ? colors.danger : colors.brand,
                  shape: BoxShape.circle,
                ),
                child: Icon(
                  recording ? Icons.stop_rounded : Icons.mic_rounded,
                  color: Colors.white,
                  size: 28,
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      recording ? '正在录音转写' : '点击开始录音',
                      style: TextStyle(
                        color: colors.textPrimary,
                        fontSize: 17,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      partial.trim().isNotEmpty
                          ? partial.trim()
                          : recording
                              ? '再次点击即可停止 · $elapsedText'
                              : '录完后可编辑，再让小C整理',
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: colors.textSecondary),
                    ),
                  ],
                ),
              ),
              Text(
                elapsedText,
                style: TextStyle(
                  color: recording ? colors.danger : colors.textSecondary,
                  fontFeatures: const [FontFeature.tabularFigures()],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

String _durationText(int seconds) {
  final minutes = seconds ~/ 60;
  final remain = seconds % 60;
  return '${_two(minutes)}:${_two(remain)}';
}

String _two(int value) => value.toString().padLeft(2, '0');

String _friendlySpeechError(String raw) {
  final value = raw.trim().toLowerCase();
  if (value.contains('permission')) return '没有麦克风权限';
  if (value.contains('network')) return '网络不可用，暂时无法继续语音识别';
  if (value.contains('no_match') || value.contains('speech_timeout')) {
    return '暂时没听清，录音会自动继续';
  }
  return '语音识别暂时中断，录音会自动重试';
}

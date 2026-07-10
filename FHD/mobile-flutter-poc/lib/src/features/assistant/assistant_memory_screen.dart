import 'package:flutter/material.dart';

import '../../data/assistant_assets.dart';
import '../../data/mobile_repository.dart';
import '../../theme/app_theme.dart';
import 'assistant_visuals.dart';

class AssistantMemoryScreen extends StatefulWidget {
  const AssistantMemoryScreen({super.key, required this.repository});

  final MobileRepository repository;

  @override
  State<AssistantMemoryScreen> createState() => _AssistantMemoryScreenState();
}

class _AssistantMemoryScreenState extends State<AssistantMemoryScreen> {
  var _loading = true;
  var _enabled = true;
  var _saving = false;
  String _error = '';
  List<AssistantMemoryRecord> _records = const [];

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = '';
    });
    try {
      final enabled = await widget.repository.assistantMemoryEnabled();
      final records = await widget.repository.loadAssistantMemories();
      if (!mounted) return;
      setState(() {
        _enabled = enabled;
        _records = records.where((item) => item.status != 'deleted').toList();
      });
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: AssistantBackdrop(
        child: SafeArea(
          bottom: false,
          child: Column(
            children: [
              AssistantTopBar(
                title: '小C的记忆',
                onBack: () => Navigator.of(context).maybePop(),
                actions: [
                  IconButton.filledTonal(
                    onPressed: _saving ? null : () => _editMemory(),
                    icon: const Icon(Icons.add_rounded, size: 20),
                    tooltip: '添加记忆',
                  ),
                ],
              ),
              Expanded(
                child: RefreshIndicator(
                  onRefresh: _reload,
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(18, 10, 18, 36),
                    children: [
                      Container(
                        padding: const EdgeInsets.all(20),
                        decoration: BoxDecoration(
                          gradient: const LinearGradient(
                            begin: Alignment.topLeft,
                            end: Alignment.bottomRight,
                            colors: [Color(0xFF5758DC), Color(0xFF708DF1)],
                          ),
                          borderRadius: BorderRadius.circular(28),
                          boxShadow: [
                            BoxShadow(
                              color: assistantIndigo.withValues(alpha: 0.24),
                              blurRadius: 32,
                              offset: const Offset(0, 14),
                            ),
                          ],
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Container(
                                  width: 48,
                                  height: 48,
                                  decoration: BoxDecoration(
                                    color: Colors.white.withValues(alpha: 0.16),
                                    borderRadius: BorderRadius.circular(16),
                                  ),
                                  child: const Icon(
                                    Icons.psychology_alt_outlined,
                                    color: Colors.white,
                                    size: 25,
                                  ),
                                ),
                                const SizedBox(width: 14),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      const Text(
                                        '让每次回答更懂你',
                                        style: TextStyle(
                                          color: Colors.white,
                                          fontSize: 20,
                                          fontWeight: FontWeight.w800,
                                          letterSpacing: -0.45,
                                        ),
                                      ),
                                      const SizedBox(height: 6),
                                      Text(
                                        '${_records.length} 条长期记忆 · 只保存你明确确认的内容',
                                        style: TextStyle(
                                          color: Colors.white
                                              .withValues(alpha: 0.72),
                                          fontSize: 11.5,
                                          height: 1.4,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 20),
                            Container(
                              padding: const EdgeInsets.fromLTRB(13, 8, 8, 8),
                              decoration: BoxDecoration(
                                color: Colors.white.withValues(alpha: 0.13),
                                borderRadius: BorderRadius.circular(16),
                              ),
                              child: Row(
                                children: [
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        const Text(
                                          '在回答中使用记忆',
                                          style: TextStyle(
                                            color: Colors.white,
                                            fontSize: 13,
                                            fontWeight: FontWeight.w700,
                                          ),
                                        ),
                                        Text(
                                          '关闭不会删除已经保存的内容',
                                          style: TextStyle(
                                            color: Colors.white
                                                .withValues(alpha: 0.64),
                                            fontSize: 10.5,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                  Switch.adaptive(
                                    value: _enabled,
                                    activeTrackColor: const Color(0xFF8AF0D0),
                                    onChanged: _saving
                                        ? null
                                        : (value) async {
                                            setState(() {
                                              _enabled = value;
                                              _saving = true;
                                            });
                                            await widget.repository
                                                .setAssistantMemoryEnabled(
                                                    value);
                                            if (mounted) {
                                              setState(() => _saving = false);
                                            }
                                          },
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 26),
                      AssistantSectionLabel(
                        '记住的内容',
                        trailing: Text(
                          '轻点可修改或删除',
                          style: TextStyle(
                            color: colors.textSecondary,
                            fontSize: 10.5,
                          ),
                        ),
                      ),
                      const SizedBox(height: 11),
                      if (_loading)
                        const Padding(
                          padding: EdgeInsets.all(34),
                          child: Center(child: CircularProgressIndicator()),
                        )
                      else if (_error.isNotEmpty)
                        _MemoryNotice(
                          icon: Icons.cloud_off_outlined,
                          text: '记忆服务暂不可用\n$_error',
                        )
                      else if (_records.isEmpty)
                        const _MemoryNotice(
                          icon: Icons.auto_awesome_outlined,
                          text: '还没有长期记忆\n添加称呼、偏好或常用要求，小C会在回答中遵守',
                        )
                      else
                        for (var i = 0; i < _records.length; i++) ...[
                          _MemoryCard(
                            record: _records[i],
                            onTap: () => _showMemoryActions(_records[i]),
                          ),
                          if (i < _records.length - 1)
                            const SizedBox(height: 10),
                        ],
                      const SizedBox(height: 18),
                      Row(
                        children: [
                          Icon(Icons.verified_user_outlined,
                              size: 15, color: colors.textSecondary),
                          const SizedBox(width: 7),
                          Expanded(
                            child: Text(
                              '记忆可随时修改、删除或停用，不会从普通聊天里自动猜测。',
                              style: TextStyle(
                                color: colors.textSecondary,
                                fontSize: 11,
                                height: 1.5,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _showMemoryActions(AssistantMemoryRecord record) async {
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.edit_outlined),
              title: const Text('修改'),
              onTap: () {
                Navigator.of(context).pop();
                _editMemory(record);
              },
            ),
            ListTile(
              leading: const Icon(Icons.delete_outline, color: Colors.red),
              title: const Text('让小C忘记', style: TextStyle(color: Colors.red)),
              onTap: () async {
                Navigator.of(context).pop();
                await widget.repository.deleteAssistantMemory(record.id);
                await _reload();
              },
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _editMemory([AssistantMemoryRecord? record]) async {
    final keyController = TextEditingController(text: record?.key ?? '我的偏好');
    final valueController = TextEditingController(text: record?.value ?? '');
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(record == null ? '让小C记住' : '修改记忆'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: keyController,
              decoration: const InputDecoration(labelText: '记忆名称'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: valueController,
              autofocus: record == null,
              minLines: 2,
              maxLines: 4,
              decoration: const InputDecoration(
                labelText: '内容',
                hintText: '例如：回答先给结论，再讲原因',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('保存'),
          ),
        ],
      ),
    );
    final key = keyController.text.trim();
    final value = valueController.text.trim();
    keyController.dispose();
    valueController.dispose();
    if (accepted != true) return;
    if (key.isEmpty || value.isEmpty) return;
    setState(() => _saving = true);
    try {
      if (record == null) {
        await widget.repository.addAssistantMemory(key: key, value: value);
      } else {
        await widget.repository.updateAssistantMemory(
          AssistantMemoryRecord(
            id: record.id,
            type: record.type,
            key: key,
            value: value,
            status: record.status,
            updatedAt: record.updatedAt,
          ),
        );
      }
      await _reload();
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }
}

IconData _memoryIcon(String type) => switch (type) {
      'entity' => Icons.badge_outlined,
      'episodic' => Icons.history_outlined,
      _ => Icons.favorite_border,
    };

class _MemoryCard extends StatelessWidget {
  const _MemoryCard({required this.record, required this.onTap});

  final AssistantMemoryRecord record;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final accent = record.isActive ? assistantMint : assistantAmber;
    return Material(
      color: Colors.transparent,
      borderRadius: BorderRadius.circular(20),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        child: Container(
          padding: const EdgeInsets.fromLTRB(14, 14, 12, 14),
          decoration: assistantSurfaceDecoration(context, radius: 20),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              AssistantIconTile(
                icon: _memoryIcon(record.type),
                color: accent,
                size: 42,
                iconSize: 20,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            record.key,
                            style: TextStyle(
                              color: colors.textPrimary,
                              fontSize: 14,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 7,
                            vertical: 3,
                          ),
                          decoration: BoxDecoration(
                            color: accent.withValues(alpha: 0.09),
                            borderRadius: BorderRadius.circular(999),
                          ),
                          child: Text(
                            record.isActive ? '使用中' : '待确认',
                            style: TextStyle(
                              color: accent,
                              fontSize: 9.5,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(
                      record.value,
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: colors.textSecondary,
                        fontSize: 12.5,
                        height: 1.48,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 5),
              Icon(
                Icons.more_horiz_rounded,
                size: 19,
                color: colors.textSecondary,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _MemoryNotice extends StatelessWidget {
  const _MemoryNotice({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(24, 30, 24, 30),
      decoration: assistantSurfaceDecoration(
        context,
        radius: 22,
        elevated: false,
      ),
      child: Column(
        children: [
          AssistantIconTile(
            icon: icon,
            color: assistantIndigo,
            size: 48,
            iconSize: 23,
          ),
          const SizedBox(height: 14),
          Text(
            text,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: colors.textSecondary,
              fontSize: 12.5,
              height: 1.55,
            ),
          ),
        ],
      ),
    );
  }
}

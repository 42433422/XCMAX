part of 'ai_group_screens.dart';

// 建群页状态类。
class _AiGroupCreateScreenState extends State<AiGroupCreateScreen> {
  late final MobileRepository _repository;
  late Future<void> _future;
  final _nameController = TextEditingController();
  var _candidates = <AiGroupCandidate>[];
  var _selected = <String>{};
  var _creating = false;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _future = _load();
  }

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final picked = _candidates.where(
      (candidate) => _selected.contains(candidate.key),
    );
    final autoName = picked.map((item) => item.name).join('、').take(40);
    return Scaffold(
      backgroundColor: colors.surface,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: '发起群聊',
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
              actions: [
                TextButton(
                  onPressed: _selected.isEmpty || _creating
                      ? null
                      : () => _create(autoName),
                  child: Text(
                    _selected.isEmpty ? '完成' : '完成(${_selected.length})',
                  ),
                ),
              ],
            ),
            Expanded(
              child: FutureBuilder<void>(
                future: _future,
                builder: (context, snapshot) {
                  if (snapshot.connectionState == ConnectionState.waiting &&
                      _candidates.isEmpty) {
                    return Center(
                      child: CircularProgressIndicator(color: colors.brand),
                    );
                  }
                  return Column(
                    children: [
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 8, 16, 10),
                        child: TextField(
                          controller: _nameController,
                          decoration: InputDecoration(
                            hintText: autoName.ifEmpty('群名称（可留空，自动命名）'),
                            filled: true,
                            fillColor: colors.page,
                            border: OutlineInputBorder(
                              borderSide: BorderSide.none,
                              borderRadius: BorderRadius.circular(10),
                            ),
                            isDense: true,
                          ),
                          maxLines: 1,
                        ),
                      ),
                      const Divider(),
                      Expanded(
                        child: _candidates.isEmpty
                            ? const Center(
                                child: Text('暂无可选 AI 员工，先在「AI员工」里同步'),
                              )
                            : ListView.separated(
                                itemCount: _candidates.length,
                                separatorBuilder: (_, __) => const Divider(
                                  indent: MessageAvatarLayout
                                      .employeePickerDividerStart,
                                ),
                                itemBuilder: (context, index) {
                                  final candidate = _candidates[index];
                                  final selected = _selected.contains(
                                    candidate.key,
                                  );
                                  final locked = isRequiredAiGroupMember(
                                    candidate.employeeId,
                                  );
                                  return _CandidateTile(
                                    candidate: candidate,
                                    selected: selected,
                                    locked: locked,
                                    onChanged: locked
                                        ? null
                                        : () {
                                            setState(() {
                                              if (selected) {
                                                _selected.remove(candidate.key);
                                              } else {
                                                _selected.add(candidate.key);
                                              }
                                            });
                                          },
                                  );
                                },
                              ),
                      ),
                    ],
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _load() async {
    final candidates = _mobileGroupMemberCatalog(
      await _repository.loadAiEmployees(),
    );
    if (!mounted) return;
    final selected = <String>{};
    for (final candidate in candidates) {
      if (isRequiredAiGroupMember(candidate.employeeId)) {
        selected.add(candidate.key);
      }
    }
    setState(() {
      _candidates = candidates;
      _selected = selected;
    });
  }

  Future<void> _create(String autoName) async {
    setState(() => _creating = true);
    final members = _candidates
        .where((candidate) => _selected.contains(candidate.key))
        .toList(growable: false);
    final name = _nameController.text.trim().ifEmpty(autoName.ifEmpty('新建群聊'));
    try {
      final group = await _repository.createGroupWithMembers(
        name: name,
        members: members,
      );
      if (!mounted) return;
      Navigator.of(context).pop(group);
    } catch (error) {
      if (!mounted) return;
      setState(() => _creating = false);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(error.toString())));
    }
  }
}

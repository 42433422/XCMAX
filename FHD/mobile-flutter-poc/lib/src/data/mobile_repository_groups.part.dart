part of 'mobile_repository.dart';

abstract class _RepoGroupsBase extends _RepoSessionBase {
  Future<List<AiGroupConversation>> loadAiGroups() async {
    final response = await _client.aiGroups();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('AI 群聊加载失败'));
    }
    return _parseAiGroups(response.data);
  }

  Future<List<AiGroupCandidate>> loadGroupMemberCandidates() async {
    final response = await _client.aiGroupCandidates();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('群成员加载失败'));
    }
    return _parseAiGroupCandidates(response.data);
  }

  Future<AiGroupConversation?> createAiGroup(String name) async {
    final text = name.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('群名称不能为空');
    }
    final response = await _client.createAiGroup(text);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('建群失败'));
    }
    return _groupFromWrap(response.data);
  }

  Future<AiGroupConversation?> createGroupWithMembers({
    required String name,
    required List<AiGroupCandidate> members,
  }) async {
    final group = await createAiGroup(name);
    if (group == null) return null;
    var current = group;
    for (final member in members) {
      final updated = await addAiGroupMember(
        groupId: group.id,
        employeeId: member.employeeId,
        modId: member.modId,
        name: member.name,
        avatar: member.avatarUrl ?? '',
        summary: member.summary,
      );
      if (updated != null) current = updated;
    }
    return current;
  }

  Future<List<AiGroupMessage>> loadAiGroupMessages(String groupId) async {
    if (groupId.trim().isEmpty) return const <AiGroupMessage>[];
    final response = await _client.aiGroupMessages(groupId.trim());
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('群消息加载失败'));
    }
    return _parseAiGroupMessages(response.data);
  }

  Future<List<GitBranchInfo>> loadGitBranches() async {
    final response = await _client.gitBranches();
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('工作分支加载失败'));
    }
    return _parseGitBranches(response.data);
  }

  Future<AiGroupPostResult> postAiGroupMessage({
    required String groupId,
    required String message,
    List<String> mentions = const [],
    String branchContext = '',
    bool forceDispatch = false,
    Map<String, String> context = const {},
  }) async {
    final text = message.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('消息不能为空');
    }
    final branch = branchContext.trim();
    final response = await _client.postAiGroupMessage(
      groupId: groupId,
      message: text,
      mentions: mentions,
      dispatch:
          forceDispatch || branch.isNotEmpty || _shouldDispatchGroupTask(text),
      branchContext: branch,
      context: context,
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('发送失败'));
    }
    return _parseAiGroupPostResult(response.data);
  }

  Future<AiGroupConversation?> addAiGroupMember({
    required String groupId,
    required String employeeId,
    required String modId,
    required String name,
    required String avatar,
    required String summary,
  }) async {
    final response = await _client.addAiGroupMember(
      groupId: groupId,
      employeeId: employeeId,
      modId: modId,
      name: name,
      avatar: avatar,
      summary: summary,
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('添加成员失败'));
    }
    return _groupFromWrap(response.data);
  }

  Future<AiGroupConversation?> removeAiGroupMember({
    required String groupId,
    required String employeeId,
  }) async {
    final response = await _client.removeAiGroupMember(
      groupId: groupId,
      employeeId: employeeId,
    );
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('移除成员失败'));
    }
    return _groupFromWrap(response.data);
  }

  Future<AiGroupConversation?> toggleAiGroupPin(String groupId) async {
    final response = await _client.toggleAiGroupPin(groupId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
    return _groupFromWrap(response.data);
  }

  Future<AiGroupConversation?> markAiGroupUnread(String groupId) async {
    final response = await _client.markAiGroupUnread(groupId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
    return _groupFromWrap(response.data);
  }

  Future<AiGroupConversation?> markAiGroupRead(String groupId) async {
    final response = await _client.markAiGroupRead(groupId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
    return _groupFromWrap(response.data);
  }

  Future<AiGroupConversation?> toggleAiGroupFollowed(String groupId) async {
    final response = await _client.toggleAiGroupFollowed(groupId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
    return _groupFromWrap(response.data);
  }

  Future<AiGroupConversation?> toggleAiGroupHidden(String groupId) async {
    final response = await _client.toggleAiGroupHidden(groupId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
    return _groupFromWrap(response.data);
  }

  Future<void> deleteAiGroup(String groupId) async {
    final response = await _client.deleteAiGroup(groupId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('删除失败'));
    }
  }

  Future<void> toggleConversationPin(String conversationId) async {
    final response = await _client.toggleConversationPin(conversationId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
  }

  Future<void> markConversationUnread(String conversationId) async {
    final response = await _client.markConversationUnread(conversationId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
  }

  Future<void> markConversationRead(String conversationId) async {
    final response = await _client.markConversationRead(conversationId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
  }

  Future<void> toggleConversationUnread(ConversationItem item) async {
    if (item.unreadCount > 0) {
      await markConversationRead(item.id);
      return;
    }
    await markConversationUnread(item.id);
  }

  Future<void> toggleConversationFollowed(String conversationId) async {
    final response = await _client.toggleConversationFollowed(conversationId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
  }

  Future<void> toggleConversationHidden(String conversationId) async {
    final response = await _client.toggleConversationHidden(conversationId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('操作失败'));
    }
  }

  Future<void> deleteConversation(String conversationId) async {
    final response = await _client.deleteConversation(conversationId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('删除失败'));
    }
  }


  Future<void> toggleAiCircleLike(int postId) async {
    final response = await _client.toggleCircleLike(postId);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('点赞失败'));
    }
  }

  Future<void> addAiCircleComment(int postId, String body) async {
    final text = body.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('评论不能为空');
    }
    final response = await _client.addCircleComment(postId, text);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('评论失败'));
    }
  }

  Future<List<AiEmployeeProfile>> loadAiEmployees() async {
    var accountKind = '';
    try {
      accountKind = (await _client.loadSession()).accountKind;
    } catch (_) {
      accountKind = '';
    }
    final mods = await _loadModInfosOrCache(
      adminMode: MobileConversationRuntimePolicy.isAdminAccountKind(
        accountKind,
      ),
    );
    return aiEmployeeProfilesFromMods(mods);
  }

}

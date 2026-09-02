// part 文件：钱包、导航与圈子模型。

part of 'mobile_models.dart';

class WalletBalanceData {
  const WalletBalanceData({
    required this.balance,
    required this.currency,
    required this.membershipLevel,
    required this.experience,
    required this.byokConfigured,
    required this.byokCount,
    required this.synced,
    required this.message,
  });

  final double? balance;
  final String currency;
  final String membershipLevel;
  final int? experience;
  final bool byokConfigured;
  final int byokCount;
  final bool synced;
  final String message;

  factory WalletBalanceData.mobileCurrentFallback() {
    return const WalletBalanceData(
      balance: 10070.30,
      currency: 'CNY',
      membershipLevel: 'vip',
      experience: null,
      byokConfigured: false,
      byokCount: 0,
      synced: true,
      message: '',
    );
  }

  factory WalletBalanceData.fromJson(Map<String, Object?> json) {
    return WalletBalanceData(
      balance: _readDouble(json, const ['balance']),
      currency: _readString(json, const ['currency']).ifEmpty('CNY'),
      membershipLevel: _readString(json, const ['membership_level']),
      experience: _readIntOrNull(json, const ['experience']),
      byokConfigured: _readBool(json, const ['byok_configured']),
      byokCount: _readInt(json, const ['byok_count'], 0),
      synced: _readBool(json, const ['synced']),
      message: _readString(json, const ['message']),
    );
  }
}

class MobileNavMenuData {
  const MobileNavMenuData({required this.items, required this.accountKind});

  final List<MobileNavMenuItem> items;
  final String accountKind;

  factory MobileNavMenuData.fromJson(Map<String, Object?> json) {
    return MobileNavMenuData(
      items: _readList(
        json['items'],
      ).map(MobileNavMenuItem.fromJson).toList(growable: false),
      accountKind: _readString(json, const [
        'account_kind',
      ]).ifEmpty('enterprise'),
    );
  }
}

class MobileNavMenuItem {
  const MobileNavMenuItem({
    required this.key,
    required this.name,
    required this.icon,
    required this.path,
    required this.source,
    required this.modId,
  });

  final String key;
  final String name;
  final String icon;
  final String path;
  final String source;
  final String? modId;

  factory MobileNavMenuItem.fromJson(Map<String, Object?> json) {
    return MobileNavMenuItem(
      key: _readString(json, const ['key', 'id']),
      name: _readString(json, const ['name', 'label', 'title']),
      icon: _readString(json, const ['icon']),
      path: _readString(json, const ['path', 'url', 'route']),
      source: _readString(json, const ['source']).ifEmpty('core'),
      modId: _readOptionalString(json, const ['mod_id']),
    );
  }
}

class AiCircleListData {
  const AiCircleListData({required this.items, required this.count});

  final List<AiCirclePost> items;
  final int count;

  factory AiCircleListData.fromJson(Map<String, Object?> json) {
    final items = _readList(
      json['items'],
    ).map(AiCirclePost.fromJson).toList(growable: false);
    return AiCircleListData(
      items: items,
      count: _readInt(json, const ['count'], items.length),
    );
  }
}

class AiCirclePost {
  const AiCirclePost({
    required this.id,
    required this.authorKind,
    required this.authorUserId,
    required this.employeeId,
    required this.authorName,
    required this.authorAvatar,
    required this.body,
    required this.sourceType,
    required this.createdAt,
    required this.likeCount,
    required this.likedByMe,
    required this.comments,
  });

  final int id;
  final String authorKind;
  final int? authorUserId;
  final String? employeeId;
  final String authorName;
  final String? authorAvatar;
  final String body;
  final String sourceType;
  final String createdAt;
  final int likeCount;
  final bool likedByMe;
  final List<AiCircleComment> comments;

  factory AiCirclePost.fromJson(Map<String, Object?> json) {
    return AiCirclePost(
      id: _readInt(json, const ['id'], 0),
      authorKind: _readString(json, const ['author_kind']),
      authorUserId: _readIntOrNull(json, const ['author_user_id']),
      employeeId: _readOptionalString(json, const ['employee_id']),
      authorName: _readString(json, const ['author_name']).ifEmpty('AI员工'),
      authorAvatar: _readOptionalString(json, const ['author_avatar']),
      body: _readString(json, const ['body', 'content', 'text']),
      sourceType: _readString(json, const ['source_type']),
      createdAt: _readString(json, const ['created_at']),
      likeCount: _readInt(json, const ['like_count'], 0),
      likedByMe: _readBool(json, const ['liked_by_me']),
      comments: _readList(
        json['comments'],
      ).map(AiCircleComment.fromJson).toList(growable: false),
    );
  }

  AiCirclePost copyWith({
    int? likeCount,
    bool? likedByMe,
    List<AiCircleComment>? comments,
  }) {
    return AiCirclePost(
      id: id,
      authorKind: authorKind,
      authorUserId: authorUserId,
      employeeId: employeeId,
      authorName: authorName,
      authorAvatar: authorAvatar,
      body: body,
      sourceType: sourceType,
      createdAt: createdAt,
      likeCount: likeCount ?? this.likeCount,
      likedByMe: likedByMe ?? this.likedByMe,
      comments: comments ?? this.comments,
    );
  }
}

class AiCircleComment {
  const AiCircleComment({
    required this.id,
    required this.authorName,
    required this.body,
    required this.createdAt,
  });

  final int id;
  final String authorName;
  final String body;
  final String createdAt;

  factory AiCircleComment.fromJson(Map<String, Object?> json) {
    return AiCircleComment(
      id: _readInt(json, const ['id'], 0),
      authorName: _readString(json, const ['author_name']).ifEmpty('用户'),
      body: _readString(json, const ['body', 'content', 'text']),
      createdAt: _readString(json, const ['created_at']),
    );
  }
}

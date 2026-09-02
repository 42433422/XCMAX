part of 'mobile_repository.dart';

class AuthQrPayload {
  const AuthQrPayload({required this.qrId, required this.accountKind});

  final String qrId;
  final String accountKind;
}

class OnboardingIndustry {
  const OnboardingIndustry({
    required this.id,
    required this.title,
    required this.subtitle,
  });

  final String id;
  final String title;
  final String subtitle;
}

class MarketCapability {
  const MarketCapability({
    required this.id,
    required this.title,
    required this.subtitle,
    this.payload = const <String, Object?>{},
  });

  final String id;
  final String title;
  final String subtitle;
  final Map<String, Object?> payload;

  factory MarketCapability.fromJson(Map<String, Object?> json) {
    final id = _firstNonBlank([
      _stringField(json, 'id'),
      _stringField(json, 'mod_id'),
      _stringField(json, 'pkg_id'),
      _stringField(json, 'slug'),
    ]);
    return MarketCapability(
      id: id,
      title: _firstNonBlank([
        _stringField(json, 'name'),
        _stringField(json, 'title'),
        _stringField(json, 'label'),
        id,
      ]),
      subtitle: _firstNonBlank([
        _stringField(json, 'description'),
        _stringField(json, 'summary'),
        _stringField(json, 'subtitle'),
        _stringField(json, 'version'),
        '从企业端同步的能力包',
      ]),
      payload: json,
    );
  }
}

class PaymentPlan {
  const PaymentPlan({
    required this.id,
    required this.title,
    required this.subtitle,
    this.payload = const <String, Object?>{},
  });

  final String id;
  final String title;
  final String subtitle;
  final Map<String, Object?> payload;

  factory PaymentPlan.fromJson(Map<String, Object?> json) {
    final id = _firstNonBlank([
      _stringField(json, 'id'),
      _stringField(json, 'plan_id'),
      _stringField(json, 'sku'),
    ]);
    final cents = _firstNonBlank([
      _stringField(json, 'amount_cents'),
      _stringField(json, 'price_cents'),
    ]);
    return PaymentPlan(
      id: id,
      title: _firstNonBlank([
        _stringField(json, 'title'),
        _stringField(json, 'name'),
        id,
      ]),
      subtitle: _firstNonBlank([
        _stringField(json, 'description'),
        cents.isNotEmpty ? _formatCents(cents) : '',
        '模型服务套餐',
      ]),
      payload: json,
    );
  }
}

class ApprovalRequest {
  const ApprovalRequest({
    required this.id,
    required this.title,
    required this.subtitle,
    required this.status,
    required this.applicantName,
    this.payload = const <String, Object?>{},
  });

  final int id;
  final String title;
  final String subtitle;
  final String status;
  final String applicantName;
  final Map<String, Object?> payload;

  factory ApprovalRequest.fromJson(Map<String, Object?> json) {
    final id = _intField(json, 'id');
    final status = _firstNonBlank([
      _stringField(json, 'status'),
      _stringField(json, 'state'),
    ]);
    final applicant = _firstNonBlank([
      _stringField(json, 'applicant_name'),
      _stringField(json, 'applicant'),
      _stringField(json, 'requester_name'),
    ]);
    return ApprovalRequest(
      id: id,
      title: _firstNonBlank([
        _stringField(json, 'title'),
        _stringField(json, 'flow_name'),
        _stringField(json, 'request_no'),
        id > 0 ? '#$id' : '',
      ]),
      subtitle: _firstNonBlank([
        _stringField(json, 'subtitle'),
        applicant,
        _stringField(json, 'description'),
      ]),
      status: status,
      applicantName: applicant,
      payload: json,
    );
  }
}

class ApprovalDetail {
  const ApprovalDetail({
    required this.id,
    required this.requestNo,
    required this.title,
    required this.status,
    required this.applicantName,
    required this.flowName,
    required this.currentNodeName,
    required this.submittedAt,
    required this.description,
    this.payload = const <String, Object?>{},
  });

  final int id;
  final String requestNo;
  final String title;
  final String status;
  final String applicantName;
  final String flowName;
  final String currentNodeName;
  final String submittedAt;
  final String description;
  final Map<String, Object?> payload;

  bool get canAct {
    final normalized = status.trim().toLowerCase();
    return normalized.contains('pending') ||
        normalized.contains('wait') ||
        status.contains('待');
  }

  factory ApprovalDetail.fromJson(
    Map<String, Object?> json, {
    int fallbackId = 0,
  }) {
    final id = _intField(json, 'id');
    final resolvedId = id > 0 ? id : fallbackId;
    final requestNo = _firstNonBlank([
      _stringField(json, 'request_no'),
      _stringField(json, 'no'),
      resolvedId > 0 ? '#$resolvedId' : '',
    ]);
    final flowName = _firstNonBlank([
      _stringField(json, 'flow_name'),
      _stringField(json, 'flow'),
    ]);
    return ApprovalDetail(
      id: resolvedId,
      requestNo: requestNo,
      title: _firstNonBlank([
        _stringField(json, 'title'),
        flowName,
        requestNo,
        '审批详情',
      ]),
      status: _firstNonBlank([
        _stringField(json, 'status'),
        _stringField(json, 'state'),
      ]),
      applicantName: _firstNonBlank([
        _stringField(json, 'applicant_name'),
        _stringField(json, 'applicant'),
        _stringField(json, 'requester_name'),
      ]),
      flowName: flowName,
      currentNodeName: _firstNonBlank([
        _stringField(json, 'current_node_name'),
        _stringField(json, 'node_name'),
      ]),
      submittedAt: _firstNonBlank([
        _stringField(json, 'submitted_at'),
        _stringField(json, 'created_at'),
        _stringField(json, 'updated_at'),
      ]),
      description: _firstNonBlank([
        _stringField(json, 'description'),
        _stringField(json, 'remark'),
        _stringField(json, 'summary'),
        _stringField(json, 'reason'),
      ]),
      payload: json,
    );
  }
}

class ImMessage {
  const ImMessage({
    required this.id,
    required this.senderUserId,
    required this.body,
    required this.createdAt,
  });

  final int id;
  final int senderUserId;
  final String body;
  final String createdAt;

  bool get mine => senderUserId <= 0;

  factory ImMessage.fromJson(Map<String, Object?> json) {
    return ImMessage(
      id: _intField(json, 'id').ifZero(_intField(json, 'message_id')),
      senderUserId: _intField(json, 'sender_user_id'),
      body: _firstNonBlank([
        _stringField(json, 'body'),
        _stringField(json, 'content'),
        _stringField(json, 'text'),
      ]),
      createdAt: _firstNonBlank([
        _stringField(json, 'created_at'),
        _stringField(json, 'timestamp'),
        '刚刚',
      ]),
    );
  }
}

class BusinessListItem {
  const BusinessListItem({
    required this.id,
    required this.title,
    required this.subtitle,
    this.payload = const <String, Object?>{},
  });

  final String id;
  final String title;
  final String subtitle;
  final Map<String, Object?> payload;

  factory BusinessListItem.fromJson(Map<String, Object?> json) {
    final id = _firstNonBlank([
      _stringField(json, 'id'),
      _stringField(json, 'uuid'),
      _stringField(json, 'order_number'),
      _stringField(json, 'sku'),
    ]);
    return BusinessListItem(
      id: id,
      title: _firstNonBlank([
        _stringField(json, 'title'),
        _stringField(json, 'name'),
        _stringField(json, 'order_number'),
        id,
      ]),
      subtitle: _firstNonBlank([
        _stringField(json, 'status'),
        _stringField(json, 'subtitle'),
        _stringField(json, 'description'),
      ]),
      payload: json,
    );
  }
}

class PairingPayload {
  const PairingPayload({
    this.host = '',
    this.port = 0,
    this.nonce = '',
    this.code = '',
    this.token = '',
    this.apiBaseUrl = '',
    this.relayId = '',
    this.relayBaseUrl = '',
    this.version = 1,
  });

  final String host;
  final int port;
  final String nonce;
  final String code;
  final String token;
  final String apiBaseUrl;
  final String relayId;
  final String relayBaseUrl;
  final int version;

  String get hostWithPort => _compactPairingHostPort(host, port);
}

Map<String, Object?> _tryDecodeObject(String text) {
  try {
    final decoded = jsonDecode(text);
    return _objectMap(decoded);
  } catch (_) {
    return const <String, Object?>{};
  }
}

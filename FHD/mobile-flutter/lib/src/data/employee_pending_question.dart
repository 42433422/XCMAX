class EmployeePendingQuestion {
  const EmployeePendingQuestion({
    required this.id,
    required this.employeeId,
    required this.task,
    required this.question,
    required this.status,
    required this.answer,
    required this.askedAt,
    required this.answeredAt,
    required this.expiresAt,
  });

  final int id;
  final String employeeId;
  final String task;
  final String question;
  final String status;
  final String answer;
  final String askedAt;
  final String answeredAt;
  final String expiresAt;

  bool get isPending => status == 'pending';

  String get statusLabel => switch (status) {
        'pending' => '待回答',
        'answered' => '已回答',
        'expired' => '超时未答',
        _ => status,
      };

  EmployeePendingQuestion copyWith({
    String? status,
    String? answer,
    String? answeredAt,
  }) {
    return EmployeePendingQuestion(
      id: id,
      employeeId: employeeId,
      task: task,
      question: question,
      status: status ?? this.status,
      answer: answer ?? this.answer,
      askedAt: askedAt,
      answeredAt: answeredAt ?? this.answeredAt,
      expiresAt: expiresAt,
    );
  }

  factory EmployeePendingQuestion.fromJson(Map<String, Object?> json) {
    return EmployeePendingQuestion(
      id: _int(json['id']),
      employeeId: _string(json['employee_id']),
      task: _string(json['task']),
      question: _string(json['question']),
      status: _string(json['status']).ifEmpty('pending'),
      answer: _string(json['answer']),
      askedAt: _string(json['asked_at']),
      answeredAt: _string(json['answered_at']),
      expiresAt: _string(json['expires_at']),
    );
  }
}

int _int(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse('$value') ?? 0;
}

String _string(Object? value) => value?.toString().trim() ?? '';

extension on String {
  String ifEmpty(String fallback) => isEmpty ? fallback : this;
}

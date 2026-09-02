part of 'ai_group_screens.dart';

// 群组成员候选数据与 AiEmployeeProfile 转换。

const _xiaocGroupCandidate = AiGroupCandidate(
  employeeId: AiGroupMemberIds.xiaocAssistant,
  modId: 'xcagi-core-assistant',
  name: '小C助理',
  summary: '负责群内上下文、任务拆解和工作汇报串联。',
  departmentKey: '通用',
  isSuper: false,
);

const _fixedSuperGroupCandidates = <AiGroupCandidate>[
  AiGroupCandidate(
    employeeId: AiGroupMemberIds.codexSuperEmployee,
    modId: 'super-employee',
    name: '超级员工-Codex',
    summary: 'Codex CLI 超级员工，支持代码任务、测试和汇报。',
    departmentKey: '工程协作',
    isSuper: true,
  ),
  AiGroupCandidate(
    employeeId: AiGroupMemberIds.cursorSuperEmployee,
    modId: 'super-employee',
    name: '超级员工-Cursor',
    summary: 'Cursor Agent 超级员工，支持工程修改和上下文协作。',
    departmentKey: '工程协作',
    isSuper: true,
  ),
  AiGroupCandidate(
    employeeId: AiGroupMemberIds.claudeSuperEmployee,
    modId: 'super-employee',
    name: '超级员工-Claude',
    summary: 'Claude CLI 超级员工，支持分析、编写和任务复盘。',
    departmentKey: '工程协作',
    isSuper: true,
  ),
  AiGroupCandidate(
    employeeId: AiGroupMemberIds.traeSuperEmployee,
    modId: 'super-employee',
    name: '超级员工-Trae',
    summary: 'Trae CLI 超级员工，支持 IDE 执行端、备用额度和补位协作。',
    departmentKey: '工程协作',
    isSuper: true,
  ),
];

List<AiGroupCandidate> _mobileGroupMemberCatalog(
  List<AiEmployeeProfile> employees,
) {
  final catalog = <AiGroupCandidate>[
    _xiaocGroupCandidate,
    ..._fixedSuperGroupCandidates,
    for (final employee in employees) _candidateFromEmployee(employee),
  ];
  final seen = <String>{};
  return [
    for (final candidate in catalog)
      if (seen.add(candidate.employeeId)) candidate,
  ];
}

AiGroupCandidate _candidateFromEmployee(AiEmployeeProfile employee) {
  return AiGroupCandidate(
    employeeId: employee.employeeId,
    modId: employee.modId,
    name: employee.name,
    avatarUrl: employee.avatarUrl,
    summary: employee.summary,
    departmentKey: employee.industryName.ifEmpty(employee.modName),
    isSuper: false,
  );
}

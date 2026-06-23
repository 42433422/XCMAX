import {
  AiEmployeeProfile,
  cleanText,
  ConversationSummary,
  DutyAreaGroup,
  DutyAreaInfo,
  DutyEmployee,
  DutyRosterData,
  FixedContactDto,
  firstChar,
  ModInfo,
  WorkflowEmployeeInfo,
  YUANGON_AREAS
} from '../models/MobileModels';

export function buildEmployees(mods: ModInfo[]): AiEmployeeProfile[] {
  const out: AiEmployeeProfile[] = [];
  mods.forEach((mod: ModInfo) => {
    const modId = cleanText(mod.id);
    if (modId.length === 0) {
      return;
    }
    const modName = cleanText(mod.name, modId);
    const employees = mod.workflow_employees || [];
    employees.forEach((employee: WorkflowEmployeeInfo) => {
      const employeeId = cleanText(employee.id);
      const name = cleanText(employee.label, cleanText(employee.panel_title, employeeId));
      if (employeeId.length === 0 || name.length === 0) {
        return;
      }
      const key = `${modId}:${employeeId}`;
      out.push({
        key: key,
        modId: modId,
        modName: modName,
        modAuthor: cleanText(mod.author),
        employeeId: employeeId,
        name: name,
        title: cleanText(employee.panel_title, name),
        summary: cleanText(employee.panel_summary, cleanText(mod.description, `来自 ${modName}`)),
        apiBasePath: cleanText(employee.api_base_path),
        phoneChannel: cleanText(employee.phone_channel),
        placeholder: employee.workflow_placeholder === true,
        avatarText: firstChar(name)
      });
    });
  });
  return out;
}

/**
 * 登录前/重置态的占位会话(无端信息):小C + 企业端兜底固定条目 + 动态员工。
 * 登录后由 Index 用 composeConversations(后端按端 SSOT) 覆盖。
 */
export function buildConversations(employees: AiEmployeeProfile[]): ConversationSummary[] {
  return composeConversations(fallbackFixedTop('enterprise'), employees, []);
}

export function findEmployee(employees: AiEmployeeProfile[], key: string): AiEmployeeProfile | undefined {
  return employees.find((item: AiEmployeeProfile) => item.key === key);
}

/** 后端固定联系人 DTO → 会话条目。 */
export function fixedToConversation(f: FixedContactDto): ConversationSummary {
  let badge: string = '在线';
  if (f.kind === 'assistant') {
    badge = 'AI在线';
  } else if (f.kind === 'super') {
    badge = '多设备';
  }
  let convId: string = `fixed:${f.id}`;
  if (f.kind === 'assistant') {
    convId = 'assistant';
  } else if (f.kind === 'dedicated_cs') {
    convId = 'customer-service';
  }
  return {
    id: convId,
    title: f.name,
    subtitle: f.summary,
    badge: badge,
    avatar: f.avatar,
    source: 'fixed',
    employeeKey: '',
    route: f.route
  };
}

/**
 * 按 surface SSOT 顺序组装会话列表：固定区(top) + 平台员工(动态) + 固定区(bottom)。
 * top/bottom 来自后端 /contacts/fixed（已按端 gating，含超级员工）。
 */
export function composeConversations(
  top: FixedContactDto[],
  employees: AiEmployeeProfile[],
  bottom: FixedContactDto[]
): ConversationSummary[] {
  const out: ConversationSummary[] = [];
  top.forEach((f: FixedContactDto) => out.push(fixedToConversation(f)));
  employees.forEach((employee: AiEmployeeProfile) => {
    out.push({
      id: `employee:${employee.key}`,
      title: employee.name,
      subtitle: employee.summary,
      badge: '已安装',
      avatar: employee.avatarText,
      source: employee.modName,
      employeeKey: employee.key
    });
  });
  bottom.forEach((f: FixedContactDto) => out.push(fixedToConversation(f)));
  return out;
}

/**
 * 旧后端/拉取失败时的固定区兜底：小C助理始终在；专属客服仅企业端
 * （管理端不显，与 surface SSOT 一致）。超级员工需后端端点提供，兜底不含。
 */
export function fallbackFixedTop(accountKind: string): FixedContactDto[] {
  const top: FixedContactDto[] = [
    {
      id: 'assistant', kind: 'assistant', name: '小C助理',
      summary: '企业 AI 助手，处理搜索、问答和跨工具操作',
      avatar: 'C', route: 'assistant_chat', backend: 'assistant'
    }
  ];
  if (accountKind !== 'admin') {
    top.push({
      id: 'dedicated_cs', kind: 'dedicated_cs', name: '专属客服',
      summary: '企业账号专属服务入口',
      avatar: '客', route: 'cs', backend: 'enterprise-cs'
    });
  }
  return top;
}

/**
 * 构建值班编制总览（员工入岗视图）。
 *
 * 从 mods 的 workflow_employees 解析 duty 员工，按 yuangon_area 归入
 * YUANGON_AREAS 区域；若后端未返回 yuangon_area，则按 employee.id 在
 * 编制表中反查归属。对标前端 yuangonDutyRoster.ts 与后端 duty_roster.json。
 */
export function buildDutyRoster(mods: ModInfo[]): DutyRosterData {
  // 1. 收集全部 duty 员工（含 yuangon_area）
  const collected: DutyEmployee[] = [];
  mods.forEach((mod: ModInfo) => {
    const modId = cleanText(mod.id);
    if (modId.length === 0) return;
    const modName = cleanText(mod.name, modId);
    const employees = mod.workflow_employees || [];
    employees.forEach((employee: WorkflowEmployeeInfo) => {
      const employeeId = cleanText(employee.id);
      const name = cleanText(employee.label, cleanText(employee.panel_title, employeeId));
      if (employeeId.length === 0 || name.length === 0) return;
      const areaId = resolveAreaId(employee, employeeId);
      collected.push({
        key: `${modId}:${employeeId}`,
        employeeId: employeeId,
        name: name,
        title: cleanText(employee.panel_title, name),
        summary: cleanText(employee.panel_summary, cleanText(mod.description, `来自 ${modName}`)),
        areaId: areaId,
        apiBasePath: cleanText(employee.api_base_path),
        phoneChannel: cleanText(employee.phone_channel, 'admin-duty'),
        status: cleanText(employee.status, 'on_duty'),
        isDuty: employee.is_duty_employee !== false,
        avatarText: firstChar(name)
      });
    });
  });

  // 2. 按 YUANGON_AREAS 分组
  const areas: DutyAreaGroup[] = YUANGON_AREAS.map((area: DutyAreaInfo): DutyAreaGroup => {
    const inArea = collected.filter((e: DutyEmployee) => e.areaId === area.id);
    const group: DutyAreaGroup = {
      areaId: area.id,
      areaLabel: area.label,
      plannedCount: area.ids.length,
      onDutyCount: inArea.length,
      employees: inArea
    };
    return group;
  });

  const totalPlanned = areas.reduce((sum: number, a: DutyAreaGroup) => sum + a.plannedCount, 0);
  const totalOnDuty = areas.reduce((sum: number, a: DutyAreaGroup) => sum + a.onDutyCount, 0);
  return { areas, totalPlanned, totalOnDuty };
}

/** yuangon_area 缺失时按 employee.id 反查编制区域。 */
function resolveAreaId(employee: WorkflowEmployeeInfo, employeeId: string): string {
  const direct = cleanText(employee.yuangon_area);
  if (direct.length > 0) return direct;
  for (const area of YUANGON_AREAS) {
    if (area.ids.indexOf(employeeId) >= 0) return area.id;
  }
  return 'platform-core';
}

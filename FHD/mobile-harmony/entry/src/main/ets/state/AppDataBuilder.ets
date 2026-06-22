import {
  AiEmployeeProfile,
  cleanText,
  ConversationSummary,
  DutyAreaGroup,
  DutyAreaInfo,
  DutyEmployee,
  DutyRosterData,
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

export function buildConversations(employees: AiEmployeeProfile[]): ConversationSummary[] {
  const fixed: ConversationSummary[] = [
    {
      id: 'assistant',
      title: '小C助理',
      subtitle: '企业 AI 助手，处理搜索、问答和跨工具操作',
      badge: 'AI在线',
      avatar: 'C',
      source: 'fixed',
      employeeKey: ''
    },
    {
      id: 'customer-service',
      title: '专属客服',
      subtitle: '企业账号专属服务入口',
      badge: '在线',
      avatar: '客',
      source: 'fixed',
      employeeKey: ''
    }
  ];
  const dynamic = employees.map((employee: AiEmployeeProfile): ConversationSummary => {
    return {
      id: `employee:${employee.key}`,
      title: employee.name,
      subtitle: employee.summary,
      badge: '已安装',
      avatar: employee.avatarText,
      source: employee.modName,
      employeeKey: employee.key
    };
  });
  return fixed.concat(dynamic);
}

export function findEmployee(employees: AiEmployeeProfile[], key: string): AiEmployeeProfile | undefined {
  return employees.find((item: AiEmployeeProfile) => item.key === key);
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

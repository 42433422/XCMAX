import {
  AiEmployeeProfile,
  cleanText,
  ConversationSummary,
  firstChar,
  ModInfo,
  WorkflowEmployeeInfo
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

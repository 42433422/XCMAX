/** 桌面后端只允许使用 userData SQLite，不能继承 IDE/代理的 DATABASE_URL。 */
export function desktopBackendEnv(env: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  const isolated = { ...env };
  delete isolated.DATABASE_URL;
  isolated.XCAGI_EMPLOYEE_SCHEDULER ||= '0';
  return isolated;
}

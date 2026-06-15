/** 列表/下拉等 onMounted 加载失败：预期空库或接口未开放时不刷 console.error。 */

function messageOf(error: unknown): string {
  if (error instanceof Error) return error.message || '';
  return String(error ?? '');
}

export function isBenignLoadFailure(error: unknown): boolean {
  const msg = messageOf(error).toLowerCase();
  if (!msg) return false;
  return (
    msg.includes('no such table') ||
    msg.includes('operationalerror') ||
    msg.includes('服务未开放') ||
    msg.includes('not found') ||
    msg.includes('404') ||
    msg.includes('加载客户/购买单位失败') ||
    msg.includes('加载单位失败')
  );
}

export function logLoadFailure(label: string, error: unknown): void {
  if (isBenignLoadFailure(error)) {
    if (import.meta.env.DEV) {
      console.debug(`[load] ${label}:`, messageOf(error) || error);
    }
    return;
  }
  console.error(label, error);
}

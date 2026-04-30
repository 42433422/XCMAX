/** 多包并存且未指定时：唯一 PRIMARY → 否则取 id 字典序第一个 */
export function pickDefaultActiveModId(
  rows: Array<{ id: string; primary?: boolean }>
): string {
  if (!rows.length) return '';
  if (rows.length === 1) return rows[0].id;
  const prim = rows.filter((r) => r.primary);
  if (prim.length === 1) return prim[0].id;
  return [...rows].sort((a, b) => a.id.localeCompare(b.id))[0].id;
}

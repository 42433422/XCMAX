import type { RouteRecordRaw } from 'vue-router';
import { modPhysicalViewGlob } from '@/constants/modPhysicalViewGlob';
import { hostViewGlob } from '@/constants/hostViewGlob';

type ViewLoader = () => Promise<{ default: unknown }>;

function normalizePath(p: string): string {
  return p.replace(/\\/g, '/');
}

function findModViewKey(modId: string, viewFile: string): string | undefined {
  // glob key 始终带 `.vue`，而调用方有的传 `OrdersView`、有的传 `OrdersView.vue`，
  // 因此两种后缀都要匹配，否则 HostModBridgeView 加载 mod 视图会回退 ModRequiredView。
  const suffixes = [
    `/mods/${modId}/frontend/views/${viewFile}`,
    `/mods/${modId}/frontend/views/${viewFile}.vue`,
  ];
  return Object.keys(modPhysicalViewGlob).find((k) => {
    const nk = normalizePath(k);
    return suffixes.some((suffix) => nk.endsWith(suffix));
  });
}

function findHostViewKey(viewFile: string): string | undefined {
  const suffix = `/views/${viewFile}`;
  return Object.keys(hostViewGlob).find((k) => normalizePath(k).endsWith(suffix));
}

/** Mod 包内物理 Vue 页（``mods/<id>/frontend/views/``） */
export function modView(modId: string, viewFile: string): ViewLoader {
  const key = findModViewKey(modId, viewFile);
  if (!key) {
    if (import.meta.env.DEV) {
      console.warn(`[modViews] missing physical view ${modId}/${viewFile}, fallback @/views`);
    }
    const hostKey = findHostViewKey(viewFile);
    if (hostKey) {
      return hostViewGlob[hostKey] as ViewLoader;
    }
    if (import.meta.env.DEV) {
      console.warn(`[modViews] missing host fallback view ${viewFile}`);
    }
    return async () => ({ default: { template: '<div />' } });
  }
  return modPhysicalViewGlob[key] as ViewLoader;
}

/** 宿主 ``frontend/src/views``（里程碑 K 旧路径） */
export function hostView(viewFile: string): ViewLoader {
  const key = findHostViewKey(viewFile);
  if (!key) {
    if (import.meta.env.DEV) {
      console.warn(`[modViews] missing host view ${viewFile}`);
    }
    return async () => ({ default: { template: '<div />' } });
  }
  return hostViewGlob[key] as ViewLoader;
}

/**
 * Mod 业务页组件：优先物理视图，manifest ``views_physical`` 为 false 时用宿主 views。
 */
export function resolveModPageView(
  modId: string,
  viewFile: string,
  physical = true,
): ViewLoader {
  return physical ? modView(modId, viewFile) : hostView(viewFile);
}

export function listPhysicalViewGlobKeys(): string[] {
  return Object.keys(modPhysicalViewGlob);
}

/**
 * 统一的 Mod 物理视图查找入口：仅从单一 glob（modPhysicalViewGlob，按 edition 解析）取 loader。
 * 企业版与 full 版 glob 均指向 SSOT `mods/`（不再读 mods-admin-runtime 副本）。
 * 供 useAdminModHostView 等宿主壳复用，避免各自硬编码目录/glob 造成"构建后视图回退"的漂移。
 */
export function findModViewLoader(modId: string, viewFile: string): ViewLoader | undefined {
  const key = findModViewKey(modId, viewFile);
  if (!key) {
    return undefined;
  }
  return modPhysicalViewGlob[key] as ViewLoader;
}

export function physicalViewExists(modId: string, viewFile: string): boolean {
  return Boolean(findModViewKey(modId, viewFile));
}

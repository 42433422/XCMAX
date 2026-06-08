import { CLIENT_PRIMARY_ERP_MOD_ID } from '@/constants/genericModPack';
import type { ModInfo } from '@/stores/mods';

/** 与 mods/attendance-industry/manifest.json frontend.menu 保持一致 */
export const ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU: NonNullable<ModInfo['menu']> = [
  {
    id: 'attendance-industry-home',
    label: '考勤表转换',
    icon: 'fa-file-excel-o',
    path: '/attendance-industry',
  },
];

export const ATTENDANCE_INDUSTRY_MOD_FALLBACK_OVERRIDES: NonNullable<ModInfo['menu_overrides']> = [
  { key: 'products', label: '人员管理' },
  { key: 'customers', label: '部门管理' },
];

/** @deprecated 使用 ATTENDANCE_INDUSTRY_* 命名 */
export const SUNBIRD_CLIENT_MOD_FALLBACK_MENU = ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU;
export const SUNBIRD_CLIENT_MOD_FALLBACK_OVERRIDES = ATTENDANCE_INDUSTRY_MOD_FALLBACK_OVERRIDES;

/** API 尚未返回考勤行业包时，侧栏/设置页仍可展示考勤转换入口 */
export function buildAttendanceIndustryModStub(): ModInfo {
  return {
    id: CLIENT_PRIMARY_ERP_MOD_ID,
    name: '考勤行业包',
    version: '1.0.0',
    author: 'XCAGI',
    description: '考勤行业通用包',
    primary: true,
    frontend: { pro_entry_path: '/attendance-industry' },
    menu: ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU.map((row) => ({ ...row })),
    menu_overrides: ATTENDANCE_INDUSTRY_MOD_FALLBACK_OVERRIDES.map((row) => ({ ...row })),
    industry: {
      id: '考勤',
      name: '考勤/人事行业',
    },
  };
}

/** @deprecated 使用 buildAttendanceIndustryModStub */
export const buildSunbirdClientModStub = buildAttendanceIndustryModStub;
